"""캐치테이블 '표시 평점'이 어떤 집계 방식인지 역추적하는 일회성 분석 스크립트.

배경: 전체 누적 판정 평균은 4.82인데 앱에는 4.9로 표시됨 (2026-03~04월부터).
→ 표시 평점이 전체 단순평균이 아니라 최근 윈도우(기간/건수) 평균일 가능성이 높다.

전체 리뷰의 (날짜, 원점수)를 수집해:
  1. 후보 윈도우(최근 N일 / 최근 N건)별 현재 평균(원점수·판정점수)과 소수1자리 표시값
  2. 현재 4.9를 만드는 후보들의 과거 월별 표시값 타임라인 → "3~4월부터 4.9"와 대조
  3. 적합 후보 기준 표시 5.0(평균 4.95)까지 필요한 추가 5점 수

실행: .github/workflows/analyze.yml (workflow_dispatch, 토큰 주입) 또는
      CATCHTABLE_TOKEN=... USE_MOCK=0 python scripts/analyze_rating_window.py
"""
import math
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fetchers.catchtable import (  # noqa: E402
    _API_BASE, _PAGE_SIZE, _effective_score, _extract_items, _session_and_shop,
)

_MAX_PAGES = 120  # 6,000건까지


def fetch_all():
    """전체 리뷰의 (작성일, 원점수) 목록을 오래된 순으로 반환."""
    session, shop_seq = _session_and_shop(os.environ.get("CATCHTABLE_STORE_ID", ""))
    out = []
    for page in range(_MAX_PAGES):
        resp = session.get(
            f"{_API_BASE}/reviews",
            params={"shopSeq": shop_seq, "size": _PAGE_SIZE, "page": page},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        items, has_next = _extract_items(data)
        for it in items:
            score = it.get("totalScore")
            raw_date = it.get("regDateTime")
            if score is not None and raw_date:
                out.append((datetime.fromisoformat(raw_date).replace(tzinfo=None), float(score)))
        if not has_next or not items:
            break
    out.sort()
    return out


def display(avg):
    """소수 첫째 자리 반올림 표시값 (round-half-up)."""
    return math.floor(avg * 10 + 0.5) / 10


def stats(reviews, judged):
    if not reviews:
        return None
    scores = [(_effective_score(s) if judged else s) for _, s in reviews]
    total = sum(scores)
    avg = total / len(scores)
    return {"n": len(scores), "sum": total, "avg": avg, "display": display(avg)}


def window_days(reviews, days, asof):
    lo = asof - timedelta(days=days)
    return [(d, s) for d, s in reviews if lo < d <= asof]


def window_count(reviews, n, asof):
    upto = [(d, s) for d, s in reviews if d <= asof]
    return upto[-n:]


def fives_to(target, st):
    """현재 (n, sum)에서 5점 리뷰만 추가로 쌓아 평균 target에 닿기까지 필요한 수."""
    if st["avg"] >= target:
        return 0
    return math.ceil(round((target * st["n"] - st["sum"]) / (5.0 - target), 6))


def main():
    reviews = fetch_all()
    if not reviews:
        print("리뷰 0건 — 토큰/응답 확인 필요")
        return
    asof = max(d for d, _ in reviews)
    print(f"수집 {len(reviews)}건 / 최신 리뷰 {asof:%Y-%m-%d} / 최초 리뷰 {reviews[0][0]:%Y-%m-%d}")

    day_windows = [30, 60, 90, 120, 180, 270, 365, 540, 730]
    cnt_windows = [100, 200, 300, 500, 800, 1000, 1500, 2000]

    candidates = []  # (label, subset_fn) 중 현재 표시 4.9인 것
    print("\n== 1) 후보 윈도우별 현재 평균 (원점수 raw / 판정점수 judged) ==")
    print(f"{'윈도우':<12} {'건수':>5} {'raw평균':>8} {'raw표시':>7} {'jdg평균':>8} {'jdg표시':>7}")

    def report(label, subset_fn):
        subset = subset_fn(asof)
        raw = stats(subset, judged=False)
        jdg = stats(subset, judged=True)
        if not raw:
            return
        print(f"{label:<12} {raw['n']:>5} {raw['avg']:>8.4f} {raw['display']:>7} "
              f"{jdg['avg']:>8.4f} {jdg['display']:>7}")
        for basis, st in (("raw", raw), ("judged", jdg)):
            if st["display"] == 4.9:
                candidates.append((label, basis, subset_fn))

    report("전체", lambda t: [(d, s) for d, s in reviews if d <= t])
    for w in day_windows:
        report(f"최근 {w}일", lambda t, w=w: window_days(reviews, w, t))
    for c in cnt_windows:
        report(f"최근 {c}건", lambda t, c=c: window_count(reviews, c, t))

    print("\n== 2) 현재 4.9인 후보들의 월별 표시값 타임라인 (사실: 2026-03~04부터 4.9) ==")
    months = []
    m = datetime(2025, 6, 1)
    while m <= asof:
        months.append(m)
        m = datetime(m.year + (m.month == 12), m.month % 12 + 1, 1)
    header = "후보(basis)".ljust(22) + " ".join(f"{mm:%y-%m}" for mm in months)
    print(header)
    for label, basis, subset_fn in candidates:
        row = []
        for mm in months:
            st = stats(subset_fn(mm), judged=(basis == "judged"))
            row.append(f"{st['display']:>5}" if st else "  -  ")
        print(f"{label + '(' + basis + ')':<22}" + " ".join(row))

    print("\n== 3) 후보별 표시 5.0(평균 4.95)까지 필요한 추가 5점 수 (지금 즉시 쌓는다고 가정) ==")
    for label, basis, subset_fn in candidates:
        st = stats(subset_fn(asof), judged=(basis == "judged"))
        need = fives_to(4.95, st)
        print(f"{label}({basis}): 현재 {st['avg']:.4f} ({st['n']}건) → 5점 {need:,}개 더 필요")
    if not candidates:
        print("(현재 4.9를 만드는 후보 없음 — 윈도우 밖의 다른 로직일 수 있음)")


if __name__ == "__main__":
    main()

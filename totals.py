"""플랫폼 누적 리뷰 통계 수집·표시.

- 네이버: 누적 리뷰 총 건수 (GraphQL total 필드)
- 캐치테이블: 누적 총 건수 + 평균 평점 + '표시 평점 5.0'까지 필요한 5점 리뷰 수
  (표시 평점 5.0 = 소수 첫째 자리 반올림 기준, 평균 4.95 이상)
- 기간 증가량: store.totals_history의 일자별 스냅샷으로
  이번 주 / 이번 달 / 지난 달 쌓은 리뷰 수를 "시작 → 현재 (+증가)"로 계산

'현황' 명령(status.py)과 아침 다이제스트(main.py collect→post) 양쪽에서 사용한다.
실패해도 본 기능(리뷰 게시/현황)이 죽지 않도록 여기서 예외를 삼킨다.
"""
import traceback
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import store
from fetchers import naver, catchtable

_KST = timezone(timedelta(hours=9))

_PERIOD_LABELS = (("week", "이번 주"), ("month", "이번 달"), ("prev_month", "지난 달"))


def collect_totals(naver_place_id: str = "", catchtable_store_id: str = "") -> dict:
    """누적 통계 dict 반환. 실패한 플랫폼 키는 빠진다.

    키: naver_total, catchtable_total, catchtable_avg, catchtable_fives_needed
    """
    stats: dict = {}

    try:
        stats["naver_total"] = naver.fetch_total(naver_place_id)
    except Exception:
        print(f"[warn] 네이버 누적 통계 수집 실패:\n{traceback.format_exc()}")

    try:
        ct = catchtable.fetch_stats(catchtable_store_id)
        stats["catchtable_total"] = ct["total"]
        if ct["avg"] is not None:
            stats["catchtable_avg"] = ct["avg"]
            need = catchtable.fives_needed(ct["score_sum"], ct["rated"])
            if need is not None:
                stats["catchtable_fives_needed"] = need
    except Exception:
        print(f"[warn] 캐치테이블 누적 통계 수집 실패:\n{traceback.format_exc()}")

    return stats


def _asof_or_earliest(day_iso: str, column: str) -> Optional[int]:
    """day 이하 스냅샷, 없으면(히스토리 초기) 가장 오래된 스냅샷으로 폴백."""
    val = store.totals_asof(day_iso, column)
    if val is not None:
        return val
    earliest = store.totals_earliest(column)
    return earliest[1] if earliest else None


def attach_periods(stats: dict, record: bool = False) -> None:
    """이번 주/이번 달/지난 달 증가량을 stats['periods']에 채운다.

    record=True면 오늘 날짜(KST)로 스냅샷도 기록한다 (아침 collect에서만 사용).
    periods 구조: {"naver": {"week": [시작, 현재], "month": [...], "prev_month": [시작, 끝]}, ...}
    """
    try:
        today = datetime.now(_KST).date()
        if record and ("naver_total" in stats or "catchtable_total" in stats):
            store.record_totals(
                today.isoformat(),
                stats.get("naver_total"), stats.get("catchtable_total"),
            )

        week_start = today - timedelta(days=today.weekday())  # 이번 주 월요일
        month_start = today.replace(day=1)
        prev_month_start = (month_start - timedelta(days=1)).replace(day=1)

        periods: dict = {}
        for platform, column in (("naver", "naver_total"), ("catchtable", "catchtable_total")):
            cur = stats.get(column)
            if cur is None:
                continue
            p: dict = {}
            wk = _asof_or_earliest(week_start.isoformat(), column)
            if wk is not None:
                p["week"] = [wk, cur]
            mo = _asof_or_earliest(month_start.isoformat(), column)
            if mo is not None:
                p["month"] = [mo, cur]
            # 지난 달: 지난달 1일 시점 → 이번 달 1일 시점. 히스토리가 지난달 중간에
            # 시작됐으면 가장 오래된 스냅샷부터 (이번 달 이전인 경우만)
            pm_start = store.totals_asof(prev_month_start.isoformat(), column)
            if pm_start is None:
                earliest = store.totals_earliest(column)
                if earliest and earliest[0] < month_start.isoformat():
                    pm_start = earliest[1]
            pm_end = store.totals_asof(month_start.isoformat(), column)
            if pm_start is not None and pm_end is not None:
                p["prev_month"] = [pm_start, pm_end]
            if p:
                periods[platform] = p
        if periods:
            stats["periods"] = periods
    except Exception:
        print(f"[warn] 기간 증가량 계산 실패:\n{traceback.format_exc()}")


def _period_sublines(p: dict) -> List[str]:
    """기간별 '시작 → 현재 (+증가)' 하위 라인. 예: 이번 주 7,289 → 7,400개 (+111)"""
    out = []
    for key, label in _PERIOD_LABELS:
        se = p.get(key)
        if not se:
            continue
        start, end = se
        out.append(f"    ‣ {label} {start:,} → {end:,}개 ({end - start:+,})")
    return out


def stats_lines(stats: dict) -> List[str]:
    """collect_totals()/attach_periods() 결과를 슬랙 표시용 문자열 목록으로 변환."""
    if not stats:
        return []
    lines = []
    periods = stats.get("periods") or {}

    nv_total = stats.get("naver_total")
    if nv_total is not None:
        lines.append(f"🟢 네이버 누적 리뷰 *{nv_total:,}건*")
        lines += _period_sublines(periods.get("naver") or {})

    ct_total = stats.get("catchtable_total")
    if ct_total is not None:
        line = f"🔵 캐치테이블 누적 리뷰 *{ct_total:,}건*"
        ct_avg = stats.get("catchtable_avg")
        if ct_avg is not None:
            line += f" · 평점 *{ct_avg:.2f}점*"
        lines.append(line)
        lines += _period_sublines(periods.get("catchtable") or {})

    # 🎯 다음 목표
    goals = []
    if nv_total is not None:
        next_milestone = (nv_total // 100 + 1) * 100
        goals.append(f"· 네이버 {next_milestone:,}건까지 *{next_milestone - nv_total:,}건* 남음")
    need = stats.get("catchtable_fives_needed")
    if need is not None:
        if need == 0:
            goals.append("· 캐치테이블 표시 평점 5.0 달성 중! 유지가 목표예요 ⭐")
        else:
            goals.append(
                f"· 캐치테이블 5.0까지 5점 리뷰 *{need:,}개* 더 필요해요"
                " (반올림 표시 5.0 = 평균 4.95 기준)"
            )
    if goals:
        lines.append("🎯 *다음 목표*")
        lines += goals

    return lines

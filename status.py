"""오늘 영업일 리뷰 현황 집계 → Slack 게시.

슬랙 리뷰 채널에서 "현황" 입력 시 GAS가 status.yml workflow_dispatch로 호출.
seen DB와 무관하게 API에서 직접 가져와 오늘 영업일 건수만 센다.

목표: 네이버 15건 / 캐치테이블 10건
영업일: 당일 10:00 KST ~ 익일 03:00 KST
  - 10:00 이후 실행 → 오늘이 영업일
  - 10:00 이전 실행(새벽 포함) → 어제가 영업일
"""
import json
import os
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fetchers import naver, catchtable
import totals

_KST = timezone(timedelta(hours=9))

NAVER_GOAL = 15
CATCHTABLE_GOAL = 10

NAVER_PLACE_ID = os.environ.get("NAVER_PLACE_ID", "1916994932")
CATCHTABLE_STORE_ID = os.environ.get("CATCHTABLE_STORE_ID", "64686")

_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _post_slack(text: str):
    token = os.environ.get("SLACK_TOKEN", "")
    channel = os.environ.get("SLACK_CHANNEL", "#03_매장리뷰_현황")
    if not token or os.environ.get("SLACK_DRY_RUN", "0") == "1":
        print(f"[dry-run]\n{text}")
        return
    payload = json.dumps({"channel": channel, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    urllib.request.urlopen(req)


def _progress_line(label: str, emoji: str, count: int, goal: int) -> str:
    if count >= goal:
        return f"{emoji} {label}: *{count} / {goal}건* ✅ 목표 달성!"
    return f"{emoji} {label}: *{count} / {goal}건* — {goal - count}건 남았어요"


def main():
    now = datetime.now(_KST).replace(tzinfo=None)

    # 영업일 판정: 10시 이전(새벽 포함)이면 어제 영업일이 진행/마감 대상
    biz_date = now.date() if now.hour >= 10 else (now - timedelta(days=1)).date()
    biz_start = datetime(biz_date.year, biz_date.month, biz_date.day, 10, 0)
    biz_end = biz_start + timedelta(hours=17)  # 익일 03:00

    errors = []

    naver_count = 0
    try:
        nv = naver.fetch_reviews(NAVER_PLACE_ID)
        # 네이버 리뷰는 날짜 정보만 있으므로 날짜 일치로 판정
        naver_count = len([r for r in nv if r.created_at.date() == biz_date])
    except Exception:
        errors.append("네이버")
        print(f"[warn] 네이버 수집 실패:\n{traceback.format_exc()}")

    ct_count = 0
    try:
        ct = catchtable.fetch_reviews(CATCHTABLE_STORE_ID)
        ct_count = len([r for r in ct if biz_start <= r.created_at < biz_end])
    except Exception:
        errors.append("캐치테이블")
        print(f"[warn] 캐치테이블 수집 실패:\n{traceback.format_exc()}")

    date_label = f"{biz_date.month}/{biz_date.day}({_WEEKDAY_KO[biz_date.weekday()]})"
    lines = [
        f"📊 *{date_label} 영업일 리뷰 현황*  _{now:%H:%M} 기준_",
        "",
        _progress_line("네이버", "🟢", naver_count, NAVER_GOAL),
        _progress_line("캐치테이블", "🔵", ct_count, CATCHTABLE_GOAL),
    ]
    if naver_count >= NAVER_GOAL and ct_count >= CATCHTABLE_GOAL:
        lines.append("")
        lines.append("🎉 오늘 목표 전부 달성! 고생하셨습니다!")

    # 누적 현황: 총 건수·평점 + 주간/월간 증가량 + 다음 목표
    stats = totals.collect_totals(NAVER_PLACE_ID, CATCHTABLE_STORE_ID)
    totals.attach_periods(stats)  # 스냅샷 기록은 아침 collect만 담당 (여기선 조회만)
    stat_lines = totals.stats_lines(stats)
    if stat_lines:
        lines.append("")
        lines.append("📈 *누적 현황*")
        lines.extend(stat_lines)

    if errors:
        lines.append("")
        lines.append(f"⚠️ {' / '.join(errors)} 수집 실패 — 해당 건수는 0으로 표시됨 (토큰 만료 의심)")

    _post_slack("\n".join(lines))
    print(f"[status] {date_label} 네이버 {naver_count}/{NAVER_GOAL}, 캐치테이블 {ct_count}/{CATCHTABLE_GOAL}")


if __name__ == "__main__":
    main()

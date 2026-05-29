"""매일 1회 실행: 리뷰 수집 → 중복제거 → 어제 리뷰 슬랙 게시.

환경변수:
  USE_MOCK            "1"이면 mock 데이터 사용(기본), "0"이면 실제 수집기 호출
  SLACK_TOKEN         슬랙 사용자 토큰 xoxp-... (없으면 콘솔 출력 dry-run)
  SLACK_CHANNEL       게시할 채널 (기본값: #03_매장리뷰_현황)
  STORE_NAME          매장 표시 이름
  NAVER_PLACE_ID      네이버 pcmap place ID
  CATCHTABLE_STORE_ID 캐치테이블 매장 ID
  NAVER_COOKIE / CATCHTABLE_TOKEN  실제 수집 시 인증값
"""
import os
import traceback
from datetime import datetime, timedelta, timezone, date

import store
import slack_digest
from fetchers import naver, catchtable

STORE_NAME = os.environ.get("STORE_NAME", "주신당 강남점")
NAVER_STORE_ID = os.environ.get("NAVER_STORE_ID", "")
CATCHTABLE_STORE_ID = os.environ.get("CATCHTABLE_STORE_ID", "")

_KST = timezone(timedelta(hours=9))


def _yesterday_kst() -> date:
    return (datetime.now(_KST) - timedelta(days=1)).date()


def _safe(fetch, store_id, label):
    try:
        return fetch(store_id)
    except Exception:
        print(f"[warn] {label} 수집 실패:\n{traceback.format_exc()}")
        return []


def run():
    collected = []
    collected += _safe(naver.fetch_reviews, NAVER_STORE_ID, "네이버")
    collected += _safe(catchtable.fetch_reviews, CATCHTABLE_STORE_ID, "캐치테이블")

    # 신규 리뷰 판별 후 전체를 DB에 기록 (재전송 방지)
    new_reviews = store.filter_new(collected)
    new_reviews.sort(key=lambda r: r.created_at)
    store.mark_seen(new_reviews)

    # 슬랙에는 어제 날짜 리뷰만 전송
    yesterday = _yesterday_kst()
    todays_reviews = [r for r in new_reviews if r.created_at.date() == yesterday]

    status = slack_digest.post(todays_reviews, STORE_NAME, yesterday)
    print(
        f"[done] 수집 {len(collected)}건 / 신규 {len(new_reviews)}건 "
        f"/ 어제({yesterday}) {len(todays_reviews)}건 / slack={status}"
    )


if __name__ == "__main__":
    run()

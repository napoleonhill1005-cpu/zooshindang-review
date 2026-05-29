"""매일 1회 실행: 리뷰 수집 → 중복제거 → 슬랙 다이제스트 게시.

환경변수:
  USE_MOCK            "1"이면 mock 데이터 사용(기본), "0"이면 실제 수집기 호출
  SLACK_TOKEN         슬랙 사용자 토큰 xoxp-... (없으면 콘솔 출력 dry-run)
  SLACK_CHANNEL       게시할 채널 (기본값: #03_매장리뷰_현황)
  STORE_NAME          매장 표시 이름
  NAVER_STORE_ID      네이버 매장 ID
  CATCHTABLE_STORE_ID 캐치테이블 매장 ID
  NAVER_COOKIE / CATCHTABLE_COOKIE  실제 수집 시 인증 쿠키
"""
import os
import traceback

import store
import slack_digest
from fetchers import naver, catchtable

STORE_NAME = os.environ.get("STORE_NAME", "주신당 강남점")
NAVER_STORE_ID = os.environ.get("NAVER_STORE_ID", "")
CATCHTABLE_STORE_ID = os.environ.get("CATCHTABLE_STORE_ID", "")


def _safe(fetch, store_id, label):
    """한 플랫폼 수집이 실패해도 다른 플랫폼은 계속 진행."""
    try:
        return fetch(store_id)
    except Exception:
        print(f"[warn] {label} 수집 실패:\n{traceback.format_exc()}")
        return []


def run():
    collected = []
    collected += _safe(naver.fetch_reviews, NAVER_STORE_ID, "네이버")
    collected += _safe(catchtable.fetch_reviews, CATCHTABLE_STORE_ID, "캐치테이블")

    new_reviews = store.filter_new(collected)
    new_reviews.sort(key=lambda r: r.created_at)

    status = slack_digest.post(new_reviews, STORE_NAME)
    store.mark_seen(new_reviews)

    print(f"[done] 수집 {len(collected)}건 / 신규 {len(new_reviews)}건 / slack={status}")


if __name__ == "__main__":
    run()

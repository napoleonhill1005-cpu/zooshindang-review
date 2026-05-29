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
import base64
import json
import os
import time
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone, date

import store
import slack_digest
from fetchers import naver, catchtable

STORE_NAME = os.environ.get("STORE_NAME", "주신당 강남점")
NAVER_STORE_ID = os.environ.get("NAVER_STORE_ID", "")
CATCHTABLE_STORE_ID = os.environ.get("CATCHTABLE_STORE_ID", "")

_KST = timezone(timedelta(hours=9))
_WARN_DAYS = 7  # 만료 N일 전부터 경고


def _yesterday_kst() -> date:
    return (datetime.now(_KST) - timedelta(days=1)).date()


def _send_slack_alert(text: str):
    """긴급 알림용 단순 텍스트 메시지 전송."""
    token = os.environ.get("SLACK_TOKEN", "")
    channel = os.environ.get("SLACK_CHANNEL", "#03_매장리뷰_현황")
    if not token:
        print(f"[alert] {text}")
        return
    payload = json.dumps({"channel": channel, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    urllib.request.urlopen(req)


def _check_auth_expiry():
    """인증 만료 임박 시 슬랙 경고."""
    # CatchTable JWT 만료 체크
    ct_token = os.environ.get("CATCHTABLE_TOKEN", "")
    if ct_token:
        try:
            payload = ct_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            data = json.loads(base64.b64decode(payload))
            exp = data.get("exp", 0)
            days_left = (exp - time.time()) / 86400
            exp_date = datetime.fromtimestamp(exp, _KST).strftime("%Y-%m-%d")

            if days_left <= 0:
                _send_slack_alert(
                    f"🚨 *CATCHTABLE_TOKEN 만료됨* ({exp_date})\n"
                    "캐치테이블 리뷰 수집이 중단됐습니다.\n"
                    "DevTools에서 cURL 재캡처 후 GitHub Secret `CATCHTABLE_TOKEN` 업데이트 필요"
                )
            elif days_left <= _WARN_DAYS:
                _send_slack_alert(
                    f"⚠️ *CATCHTABLE_TOKEN {int(days_left)}일 후 만료* ({exp_date})\n"
                    "DevTools에서 cURL 재캡처 후 GitHub Secret `CATCHTABLE_TOKEN` 업데이트 해주세요"
                )
        except Exception:
            pass

    # Naver 쿠키 — 테스트 요청으로 유효성 확인
    naver_cookie = os.environ.get("NAVER_COOKIE", "")
    if naver_cookie:
        try:
            import requests
            resp = requests.post(
                "https://pcmap-api.place.naver.com/place/graphql",
                headers={
                    "accept": "*/*", "content-type": "application/json",
                    "origin": "https://pcmap.place.naver.com",
                    "Cookie": naver_cookie,
                },
                json={"query": "{ __typename }", "operationName": None, "variables": {}},
                timeout=10,
            )
            if resp.status_code in (401, 403):
                _send_slack_alert(
                    "🚨 *NAVER_COOKIE 만료됨*\n"
                    "네이버 리뷰 수집이 중단됐습니다.\n"
                    "DevTools에서 cURL 재캡처 후 GitHub Secret `NAVER_COOKIE` 업데이트 필요"
                )
        except Exception:
            pass


def _safe(fetch, store_id, label):
    try:
        return fetch(store_id)
    except Exception:
        print(f"[warn] {label} 수집 실패:\n{traceback.format_exc()}")
        return []


def run():
    _check_auth_expiry()

    collected = []
    collected += _safe(naver.fetch_reviews, NAVER_STORE_ID, "네이버")
    collected += _safe(catchtable.fetch_reviews, CATCHTABLE_STORE_ID, "캐치테이블")

    new_reviews = store.filter_new(collected)
    new_reviews.sort(key=lambda r: r.created_at)
    store.mark_seen(new_reviews)

    yesterday = _yesterday_kst()
    todays_reviews = [r for r in new_reviews if r.created_at.date() == yesterday]

    status = slack_digest.post(todays_reviews, STORE_NAME, yesterday)
    print(
        f"[done] 수집 {len(collected)}건 / 신규 {len(new_reviews)}건 "
        f"/ 어제({yesterday}) {len(todays_reviews)}건 / slack={status}"
    )


if __name__ == "__main__":
    run()

"""리뷰봇 진입점.

실행 모드 (인수로 전달):
  collect  매일 00:00 KST — API에서 신규 리뷰 수집 → seen DB 기록 → pending 저장
  post     매일 09:00 KST — pending 불러와 Slack 게시 → pending 삭제
  (없음)   로컬 테스트용: collect + post 즉시 순차 실행

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
import sys
import time
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone, date

import store
import pending
import slack_digest
from fetchers import naver, catchtable

STORE_NAME = os.environ.get("STORE_NAME", "주신당 강남점")
NAVER_STORE_ID = os.environ.get("NAVER_STORE_ID", "")
CATCHTABLE_STORE_ID = os.environ.get("CATCHTABLE_STORE_ID", "")

_KST = timezone(timedelta(hours=9))
_WARN_DAYS = 3


def _yesterday_kst() -> date:
    return (datetime.now(_KST) - timedelta(days=1)).date()


def _send_slack_alert(text: str):
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


def collect():
    """00:00 KST: 신규 리뷰 수집 → seen DB 기록 → pending 저장 (Slack 미게시)."""
    _check_auth_expiry()

    collected = []
    collected += _safe(naver.fetch_reviews, NAVER_STORE_ID, "네이버")
    collected += _safe(catchtable.fetch_reviews, CATCHTABLE_STORE_ID, "캐치테이블")

    new_reviews = store.filter_new(collected)
    new_reviews.sort(key=lambda r: r.created_at)

    # 기존 pending에 누적 (봇이 여러 번 실행돼도 중복 없이 합산)
    existing = {(r.platform, r.review_id) for r in pending.load()}
    truly_new = [r for r in new_reviews if (r.platform, r.review_id) not in existing]

    store.mark_seen(new_reviews)
    pending.save(pending.load() + truly_new)

    print(f"[collect] 수집 {len(collected)}건 / 신규 {len(truly_new)}건 pending 추가")


def post():
    """09:00 KST: pending 리뷰를 Slack에 게시 후 삭제."""
    reviews = pending.load()
    yesterday = _yesterday_kst()

    if not reviews:
        print(f"[post] pending 없음 — {yesterday} 리뷰 0건")
        slack_digest.post([], STORE_NAME, yesterday)
        return

    status = slack_digest.post(reviews, STORE_NAME, yesterday)
    pending.clear()
    print(f"[post] {len(reviews)}건 게시 / slack={status}")


def run():
    """로컬 테스트용: collect + post 즉시 순차 실행."""
    collect()
    post()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    if mode == "collect":
        collect()
    elif mode == "post":
        post()
    else:
        run()

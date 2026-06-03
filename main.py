"""리뷰봇 진입점.

실행 모드 (인수로 전달):
  collect  매일 08:00 KST — API에서 신규 리뷰 수집 → seen DB 기록 → pending 저장
  post     매일 09:00 KST — pending 불러와 Slack 게시 → pending 삭제
  (없음)   로컬 테스트용: collect + post 즉시 순차 실행

환경변수:
  USE_MOCK            "1"이면 mock 데이터 사용(기본), "0"이면 실제 수집기 호출
  SLACK_TOKEN         슬랙 사용자 토큰 xoxp-... (없으면 콘솔 출력 dry-run)
  SLACK_DRY_RUN       "1"이면 Slack 미게시 테스트 모드 (토큰이 있어도 콘솔만 출력)
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
_USE_MOCK = os.environ.get("USE_MOCK", "1") == "1"
_DRY_RUN = os.environ.get("SLACK_DRY_RUN", "0") == "1"

_KST = timezone(timedelta(hours=9))
_WARN_DAYS = 3
_CATCHUP_DAYS = 7  # seen DB 유실 시 재게시 범위 제한 (일)


def _yesterday_kst() -> date:
    return (datetime.now(_KST) - timedelta(days=1)).date()


def _send_slack_alert(text: str):
    """장애·만료 알림 전용 단순 텍스트 메시지. dry-run 여부와 무관하게 항상 전송."""
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
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"[alert 전송 실패] {e}")


def _check_auth_expiry():
    """인증 만료 임박 시 슬랙 경고."""
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
    """08:00 KST: 신규 리뷰 수집 → seen DB 기록 → pending 저장 (Slack 미게시)."""
    _check_auth_expiry()

    naver_reviews = _safe(naver.fetch_reviews, NAVER_STORE_ID, "네이버")
    ct_reviews = _safe(catchtable.fetch_reviews, CATCHTABLE_STORE_ID, "캐치테이블")
    collected = naver_reviews + ct_reviews

    # 토큰은 있는데 수집이 0건이면 인증 만료 or API 변경 의심
    if not _USE_MOCK:
        if os.environ.get("NAVER_COOKIE") and len(naver_reviews) == 0:
            _send_slack_alert(
                "⚠️ *네이버 리뷰 수집 0건*\n"
                "NAVER_COOKIE 만료 또는 API 변경 의심. GitHub Actions 로그 확인 필요."
            )
        if os.environ.get("CATCHTABLE_TOKEN") and len(ct_reviews) == 0:
            _send_slack_alert(
                "⚠️ *캐치테이블 리뷰 수집 0건*\n"
                "CATCHTABLE_TOKEN 만료 또는 API 변경 의심. GitHub Actions 로그 확인 필요."
            )

    new_reviews = store.filter_new(collected)
    new_reviews.sort(key=lambda r: r.created_at)

    # seen DB 유실 시 오래된 리뷰 대량 재게시 방지: 최근 N일치만 pending에 추가
    cutoff = datetime.now() - timedelta(days=_CATCHUP_DAYS)
    new_reviews = [r for r in new_reviews if r.created_at >= cutoff]

    # 기존 pending에 누적 (봇이 여러 번 실행돼도 중복 없이 합산)
    existing = {(r.platform, r.review_id) for r in pending.load()}
    truly_new = [r for r in new_reviews if (r.platform, r.review_id) not in existing]

    store.mark_seen(new_reviews)
    pending.save(pending.load() + truly_new)

    print(f"[collect] 수집 {len(collected)}건 / 신규 {len(truly_new)}건 pending 추가"
          + (" [DRY-RUN]" if _DRY_RUN else ""))


def post():
    """09:00 KST: pending 리뷰를 Slack에 게시 후 삭제."""
    reviews = pending.load()
    yesterday = _yesterday_kst()

    if not reviews:
        # dry-run이 아닌 정규 실행인데 pending이 없으면 collect 단계 이상 의심
        if not _DRY_RUN:
            _send_slack_alert(
                f"⚠️ *리뷰봇 — {yesterday} pending 없음*\n"
                "collect 단계 실패 또는 신규 리뷰 0건.\n"
                "GitHub Actions `review-collect` 로그를 확인하세요."
            )
        print(f"[post] pending 없음 — {yesterday} 리뷰 0건"
              + (" [DRY-RUN]" if _DRY_RUN else ""))
        return

    status = slack_digest.post(reviews, STORE_NAME, yesterday)
    if not _DRY_RUN:
        pending.clear()
    print(f"[post] {len(reviews)}건 게시 / slack={status}"
          + (" (pending 유지) [DRY-RUN]" if _DRY_RUN else ""))


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

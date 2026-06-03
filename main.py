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

# 영업일 기준: 당일 10:00 KST ~ 익일 03:00 KST (17시간)
_BIZ_START_HOUR = 10
_BIZ_END_HOUR = 3  # 익일 03:00


def _biz_day_range(biz_date: date):
    """영업일 날짜 → (시작 datetime, 종료 datetime) 반환. 모두 naive KST."""
    start = datetime(biz_date.year, biz_date.month, biz_date.day, _BIZ_START_HOUR, 0)
    end = start + timedelta(hours=17)  # 10:00 + 17h = 익일 03:00
    return start, end


def _prev_biz_date() -> date:
    """08:00 KST 실행 기준 — 직전 영업일 날짜 반환.
    08:00는 당일 영업일(10:00 시작) 이전이므로 항상 전날이 직전 영업일."""
    return (datetime.now(_KST) - timedelta(days=1)).date()


def _in_biz_day(r, biz_date: date) -> bool:
    """리뷰가 해당 영업일 범위 안에 있는지 판단.
    - 네이버: 날짜 정보만 있으므로 날짜 일치 비교
    - 캐치테이블: ISO 시간 포함 → 영업일 시간 범위로 비교
    """
    if r.platform == "naver":
        return r.created_at.date() == biz_date
    start, end = _biz_day_range(biz_date)
    return start <= r.created_at < end


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

    # 전체 신규 리뷰를 seen 처리 → DB 유실 시에도 과거 리뷰 재출현 방지
    store.mark_seen(new_reviews)

    # pending에는 직전 영업일(10:00~익일03:00) 리뷰만 저장
    biz_date = _prev_biz_date()
    biz_reviews = sorted(
        [r for r in new_reviews if _in_biz_day(r, biz_date)],
        key=lambda r: r.created_at,
    )

    existing = {(r.platform, r.review_id) for r in pending.load()}
    truly_new = [r for r in biz_reviews if (r.platform, r.review_id) not in existing]
    pending.save(pending.load() + truly_new)

    n_cnt = len([r for r in truly_new if r.platform == "naver"])
    ct_cnt = len([r for r in truly_new if r.platform == "catchtable"])
    biz_start, biz_end = _biz_day_range(biz_date)
    print(f"[collect] 수집 {len(collected)}건 / 전체신규 {len(new_reviews)}건 "
          f"/ 영업일({biz_date} {biz_start:%H:%M}~{biz_end:%m/%d %H:%M}) "
          f"pending {len(truly_new)}건 (네이버 {n_cnt}건, 캐치테이블 {ct_cnt}건)"
          + (" [DRY-RUN]" if _DRY_RUN else ""))


def post():
    """09:00 KST: pending 리뷰를 Slack에 게시 후 삭제."""
    reviews = pending.load()
    biz_date = _prev_biz_date()  # 헤더에 표시할 영업일 날짜

    if not reviews:
        if not _DRY_RUN:
            _send_slack_alert(
                f"⚠️ *리뷰봇 — {biz_date} 영업일 pending 없음*\n"
                "collect 단계 실패 또는 신규 리뷰 0건.\n"
                "GitHub Actions `review-collect` 로그를 확인하세요."
            )
        print(f"[post] pending 없음 — {biz_date} 영업일 리뷰 0건"
              + (" [DRY-RUN]" if _DRY_RUN else ""))
        return

    status = slack_digest.post(reviews, STORE_NAME, biz_date)
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

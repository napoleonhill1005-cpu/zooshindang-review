"""구글 비즈니스 프로필(구 마이비즈니스) 리뷰 수집기 — 공식 API 사용.

네이버/캐치테이블과 달리 구글은 사장님 계정용 **공식 리뷰 API**가 있다.
(Google Business Profile API — 리뷰는 레거시 v4 엔드포인트에만 존재)
쿠키 캡처가 필요 없고, refresh token은 사실상 만료되지 않아 가장 안정적.

인증/설정 (환경변수, 발급 절차는 docs/GOOGLE_SETUP.md 참고):
  GOOGLE_CLIENT_ID      GCP OAuth 클라이언트 ID
  GOOGLE_CLIENT_SECRET  GCP OAuth 클라이언트 시크릿
  GOOGLE_REFRESH_TOKEN  scripts/google_oauth_setup.py 로 1회 발급
  GOOGLE_ACCOUNT_ID     accounts/{숫자} 의 숫자 부분
  GOOGLE_LOCATION_ID    locations/{숫자} 의 숫자 부분

API 특성: pageSize 최대 50, updateTime 내림차순. 최신 50건이면 하루 커버에 충분.
DEBUG_GOOGLE=1 로 실행하면 응답 JSON 앞 3000자를 출력.
"""
import os
import json
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from models import Review

USE_MOCK = os.environ.get("USE_MOCK", "1") == "1"
DEBUG = os.environ.get("DEBUG_GOOGLE", "0") == "1"

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVIEWS_URL = (
    "https://mybusiness.googleapis.com/v4"
    "/accounts/{account}/locations/{location}/reviews"
)
_PAGE_SIZE = 50  # API 최대값

_KST = timezone(timedelta(hours=9))

# starRating 은 숫자가 아니라 enum 문자열로 내려온다
_STAR_RATING = {"ONE": 1.0, "TWO": 2.0, "THREE": 3.0, "FOUR": 4.0, "FIVE": 5.0}


def fetch_reviews(store_id: str) -> List[Review]:
    if USE_MOCK:
        return _mock()

    account = os.environ.get("GOOGLE_ACCOUNT_ID", "")
    location = store_id or os.environ.get("GOOGLE_LOCATION_ID", "")
    if not (account and location and os.environ.get("GOOGLE_REFRESH_TOKEN")):
        print("[google] 미설정 — 수집 건너뜀 (설정 절차: docs/GOOGLE_SETUP.md)")
        return []

    access_token = _get_access_token()
    resp = requests.get(
        _REVIEWS_URL.format(account=account, location=location),
        params={"pageSize": _PAGE_SIZE, "orderBy": "updateTime desc"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    if DEBUG:
        print("[DEBUG Google 응답 (앞 3000자)]")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])

    items = data.get("reviews") or []
    return [_to_review(it) for it in items]


def _get_access_token() -> str:
    """refresh token → access token 교환. invalid_grant 면 재발급 안내 메시지로 실패."""
    resp = requests.post(
        _TOKEN_URL,
        data={
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    if resp.status_code == 400 and "invalid_grant" in resp.text:
        raise RuntimeError(
            "GOOGLE_REFRESH_TOKEN 무효(invalid_grant) — "
            "scripts/google_oauth_setup.py 로 재발급 후 Secret 업데이트 필요"
        )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _parse_created(raw: str) -> datetime:
    """ISO8601 UTC ('2026-06-11T12:34:56.789Z') → naive KST datetime."""
    if not raw:
        return datetime.now()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(_KST).replace(tzinfo=None)
    except ValueError:
        return datetime.now()


def _strip_translation(comment: str) -> str:
    """구글이 자동 번역을 붙인 경우 '(Translated by Google)' 이후는 잘라낸다."""
    marker = "\n\n(Translated by Google)"
    idx = comment.find(marker)
    return comment[:idx] if idx > 0 else comment


def _first_photo(it: dict) -> Optional[str]:
    """리뷰 첨부 사진의 대표 1장 URL. (reviewer.profilePhotoUrl 은 아바타이므로 쓰지 않음)

    v4 리뷰 리소스의 reviewMediaItems[] 에서 thumbnailUrl 을 뽑는다.
    단, 이 필드는 응답에 안 올 수도 있음(output only, 미제공 사례 보고됨).
    없으면 사진 없이 텍스트·별점만 게시된다 — DEBUG_GOOGLE=1 로 실응답 확인.
    """
    for m in (it.get("reviewMediaItems") or []):
        url = m.get("thumbnailUrl") or m.get("googleUrl") or m.get("sourceUrl")
        if url:
            return url
    return None


def _to_review(it: dict) -> Review:
    review_id = str(it.get("reviewId") or "")
    reviewer = it.get("reviewer") or {}
    author = reviewer.get("displayName") or "익명"
    rating: Optional[float] = _STAR_RATING.get(it.get("starRating") or "")
    text = _strip_translation(it.get("comment") or "")
    created_at = _parse_created(it.get("createTime") or "")
    return Review("google", review_id, author, rating, text, created_at,
                  None, _first_photo(it))


def _mock() -> List[Review]:
    now = datetime.now()
    return [
        Review("google", "g3001", "Soyeon K", 5.0,
               "무당집 컨셉이 정말 신선했어요. 외국인 친구 데려갔는데 너무 좋아했습니다!",
               now - timedelta(hours=8),
               None, "https://picsum.photos/seed/zooshindang/400/300"),
        Review("google", "g3002", "David Lee", 4.0,
               "Unique concept bar. Cocktails were creative and the vibe was great.",
               now - timedelta(hours=3)),
    ]

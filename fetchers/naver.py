"""네이버 플레이스 방문자 리뷰 수집기.

인증: NAVER_COOKIE 환경변수 (DevTools cURL의 -b 값 전체)
매장 ID: NAVER_PLACE_ID — pcmap.place.naver.com URL의 숫자 ID (기본값 1916994932)
        NAVER_STORE_ID(스마트플레이스 관리자 ID)와 다른 값임.

API 특성: display 최대 50, page 파라미터 페이지네이션 미지원.
          display=50 단건 요청으로 최신 50건 수집 (하루 리뷰 커버에 충분).
DEBUG_NAVER=1 로 실행하면 응답 JSON 앞 3000자를 출력.
"""
import os
import json
import re
import time
import requests
from datetime import datetime, date
from typing import List

from models import Review, AuthError

USE_MOCK = os.environ.get("USE_MOCK", "1") == "1"
DEBUG = os.environ.get("DEBUG_NAVER", "0") == "1"

_GRAPHQL_URL = "https://pcmap-api.place.naver.com/place/graphql"
_DEFAULT_PLACE_ID = "1916994932"
_BUSINESS_TYPE = "restaurant"
_DISPLAY = 50  # API 최대값

_HEADERS = {
    "accept": "*/*",
    "accept-language": "ko-KR,ko;q=0.9",
    "content-type": "application/json",
    "origin": "https://pcmap.place.naver.com",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
}

_QUERY = """
query getVisitorReviews($input: VisitorReviewsInput) {
  visitorReviews(input: $input) {
    items {
      id
      rating
      author { nickname }
      body
      created
      media { thumbnail }
    }
    total
  }
}
"""


def fetch_reviews(store_id: str) -> List[Review]:
    if USE_MOCK:
        return _mock()

    vr = _request_visitor_reviews(_DISPLAY)
    items = vr.get("items") or []
    return [_to_review(it) for it in items]


def fetch_total(store_id: str = "") -> int:
    """방문자 리뷰 누적 총 건수. display=1 경량 요청으로 total만 읽는다."""
    if USE_MOCK:
        return 128

    vr = _request_visitor_reviews(1)
    total = vr.get("total")
    if total is None:
        raise RuntimeError("Naver 응답에 total 필드가 없습니다.")
    return int(total)


def _request_visitor_reviews(display: int) -> dict:
    """getVisitorReviews GraphQL 호출 → visitorReviews dict 반환."""
    cookie = os.environ.get("NAVER_COOKIE", "").strip()
    place_id = os.environ.get("NAVER_PLACE_ID", _DEFAULT_PLACE_ID)

    session = requests.Session()
    session.headers.update({
        **_HEADERS,
        "referer": (
            f"https://pcmap.place.naver.com/{_BUSINESS_TYPE}/{place_id}/review/visitor"
        ),
        **({"Cookie": cookie} if cookie else {}),
    })

    payload = {
        "operationName": "getVisitorReviews",
        "variables": {
            "input": {
                "businessId": place_id,
                "businessType": _BUSINESS_TYPE,
                "page": 1,
                "display": display,
            }
        },
        "query": _QUERY,
    }

    for attempt in range(3):
        resp = session.post(_GRAPHQL_URL, json=payload, timeout=20)
        if resp.status_code != 429:
            break
        time.sleep(5 * (attempt + 1))
    # 401/403 = 쿠키 만료·무효 → '진짜 0건'과 구별되도록 명시적 예외
    if resp.status_code in (401, 403):
        raise AuthError("naver")
    resp.raise_for_status()
    data = resp.json()

    if DEBUG:
        print("[DEBUG Naver 응답 (앞 3000자)]")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])

    if "errors" in data:
        raise RuntimeError(
            f"Naver GraphQL 오류: {data['errors'][0].get('message', '')}"
        )

    return data["data"]["visitorReviews"] or {}


def _parse_created(raw: str) -> datetime:
    """'5.29.금' 또는 '2025.5.29.금' 형식을 datetime으로 변환."""
    if not raw:
        return datetime.now()
    parts = re.findall(r"\d+", raw)
    today = date.today()
    try:
        if len(parts) >= 3:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        elif len(parts) == 2:
            month, day = int(parts[0]), int(parts[1])
            year = today.year
            if date(year, month, day) > today:
                year -= 1
        else:
            return datetime.now()
        return datetime(year, month, day)
    except (ValueError, IndexError):
        return datetime.now()


def _to_review(it: dict) -> Review:
    review_id = str(it.get("id") or "")
    author_obj = it.get("author") or {}
    author = author_obj.get("nickname") or "익명"
    rating = it.get("rating")
    text = it.get("body") or ""
    created_at = _parse_created(it.get("created") or "")
    media = it.get("media") or []
    photo_url = media[0].get("thumbnail") if media else None
    return Review("naver", review_id, author, rating, text, created_at, None, photo_url)


def _mock() -> List[Review]:
    from datetime import timedelta
    now = datetime.now()
    return [
        Review("naver", "n1001", "김**", 5.0,
               "분위기가 진짜 독특해요. 무당집 컨셉이라더니 칵테일도 컨셉에 딱 맞고 재밌었어요!",
               now - timedelta(hours=9)),
        Review("naver", "n1002", "이**", 4.0,
               "웨이팅이 좀 있었지만 들어가니 만족스러웠습니다. 시그니처 칵테일 강추.",
               now - timedelta(hours=4)),
        Review("naver", "n1003", "박**", None,
               "사진 찍기 좋은 곳! 데이트 코스로 적극 추천합니다.",
               now - timedelta(hours=1)),
    ]

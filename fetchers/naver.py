"""네이버 스마트플레이스 리뷰 수집기.

인증: NAVER_COOKIE 환경변수 (DevTools → Copy as cURL 의 -b 값 전체)
매장: NAVER_STORE_ID (기본값 10037388), NAVER_BOOKING_BUSINESS_ID (기본값 1212070)

Next.js _next/data URL에 build hash가 포함되어 있어 배포 때마다 바뀌므로,
HTML 페이지에서 buildId를 자동 추출한 뒤 리뷰 JSON을 가져온다.

응답 구조가 바뀌면 _find_review_list() 또는 _to_review() 의 필드명만 수정한다.
DEBUG_NAVER=1 로 실행하면 응답 JSON 앞 3000자를 출력해 구조 확인 가능.
"""
import os
import re
import json
import requests
from datetime import datetime
from typing import List

from models import Review

USE_MOCK = os.environ.get("USE_MOCK", "1") == "1"
DEBUG = os.environ.get("DEBUG_NAVER", "0") == "1"

_BASE = "https://new.smartplace.naver.com"
_DEFAULT_BUSINESS_ID = "10037388"
_DEFAULT_BOOKING_ID = "1212070"

_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
}


def fetch_reviews(store_id: str) -> List[Review]:
    if USE_MOCK:
        return _mock()

    cookie = os.environ["NAVER_COOKIE"]
    business_id = store_id or os.environ.get("NAVER_STORE_ID", _DEFAULT_BUSINESS_ID)
    booking_id = os.environ.get("NAVER_BOOKING_BUSINESS_ID", _DEFAULT_BOOKING_ID)

    session = requests.Session()
    session.headers.update({**_HEADERS, "Cookie": cookie})

    build_id = _get_build_id(session, business_id, booking_id)

    resp = session.get(
        f"{_BASE}/_next/data/{build_id}/bizes/place/{business_id}/reviews.json",
        params={
            "bookingBusinessId": booking_id,
            "menu": "visitor",
            "businessType": "place",
            "businessId": business_id,
        },
        headers={
            "x-nextjs-data": "1",
            "Referer": (
                f"{_BASE}/bizes/place/{business_id}/reviews"
                f"?bookingBusinessId={booking_id}&menu=visitor"
            ),
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    if DEBUG:
        print("[DEBUG Naver 응답 (앞 3000자)]")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])

    items = _find_review_list(data)
    return [_to_review(it) for it in items]


def _get_build_id(session: requests.Session, business_id: str, booking_id: str) -> str:
    """HTML 페이지의 __NEXT_DATA__ 에서 현재 buildId를 추출한다."""
    resp = session.get(
        f"{_BASE}/bizes/place/{business_id}/reviews",
        params={"bookingBusinessId": booking_id, "menu": "visitor"},
        headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        timeout=15,
    )
    resp.raise_for_status()
    m = re.search(r'"buildId"\s*:\s*"([^"]+)"', resp.text)
    if not m:
        raise RuntimeError(
            "Naver buildId 추출 실패. 쿠키 만료 여부 확인 또는 DEBUG_NAVER=1 로 HTML 재확인."
        )
    return m.group(1)


def _find_review_list(data: dict) -> list:
    """pageProps 하위 구조에서 리뷰 배열을 찾는다.
    응답 구조가 바뀌면 이 함수의 탐색 경로를 수정한다."""
    page_props = data.get("pageProps", data)

    # 시도 1: pageProps 직속
    for key in ("reviewList", "reviews", "reviewItems", "visitorReviews"):
        if isinstance(page_props.get(key), list):
            return page_props[key]

    # 시도 2: 한 단계 래핑 (reviewData, initialState, data 등)
    for outer in ("reviewData", "initialState", "data", "result"):
        sub = page_props.get(outer)
        if isinstance(sub, dict):
            for key in ("reviewList", "reviews", "reviewItems", "content"):
                if isinstance(sub.get(key), list):
                    return sub[key]

    # 시도 3: React Query dehydratedState
    for query in page_props.get("dehydratedState", {}).get("queries", []):
        result = query.get("state", {}).get("data", {})
        if isinstance(result, dict):
            for key in ("reviewList", "reviews", "content"):
                if isinstance(result.get(key), list):
                    return result[key]

    raise ValueError(
        "응답에서 리뷰 배열을 찾지 못했습니다.\n"
        "DEBUG_NAVER=1 USE_MOCK=0 python main.py 로 재실행해 응답 구조를 확인하고\n"
        "_find_review_list() 의 탐색 경로를 수정하세요.\n"
        f"pageProps 최상위 키: {list(page_props.keys())}"
    )


def _to_review(it: dict) -> Review:
    review_id = str(
        it.get("reviewId") or it.get("id") or it.get("naverReviewId") or ""
    )
    author_obj = it.get("author") or {}
    author = (
        author_obj.get("nickname")
        or it.get("writerName")
        or it.get("authorName")
        or "익명"
    )
    # 방문자리뷰는 별점이 없음 → None 유지
    rating = it.get("rating") or it.get("visitScore") or it.get("starScore")
    text = it.get("body") or it.get("contents") or it.get("reviewBody") or ""
    raw_date = (
        it.get("createDate")
        or it.get("createdAt")
        or it.get("createdDateTime")
        or ""
    )
    created_at = (
        datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        if raw_date
        else datetime.now()
    )
    return Review("naver", review_id, author, rating, text, created_at, it.get("reviewUrl"))


def _mock() -> List[Review]:
    from datetime import timedelta
    now = datetime.now()
    return [
        Review("naver", "n1001", "김**", 5.0,
               "분위기가 진짜 독특해요. 무당집 컨셉이라더니 칵테일도 컨셉에 딱 맞고 재밌었어요!",
               now - timedelta(hours=9), "https://m.place.naver.com/restaurant/0000/review"),
        Review("naver", "n1002", "이**", 4.0,
               "웨이팅이 좀 있었지만 들어가니 만족스러웠습니다. 시그니처 칵테일 강추.",
               now - timedelta(hours=4)),
        Review("naver", "n1003", "박**", None,
               "사진 찍기 좋은 곳! 데이트 코스로 적극 추천합니다.",
               now - timedelta(hours=1)),
    ]

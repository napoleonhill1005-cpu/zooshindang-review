"""캐치테이블 사장님(관리자) 페이지 리뷰 수집기.

인증: CATCHTABLE_TOKEN 환경변수 (DevTools cURL의 Authorization: Bearer 값)
매장: CATCHTABLE_STORE_ID 환경변수 = shopSeq (기본값 64686)

최대 3페이지(page 0-2, size=50)까지 수집한다.
store.py의 ID 기반 중복제거가 있으므로 넉넉하게 가져와도 무방하다.

응답 구조가 바뀌면 _extract_items() 또는 _to_review() 의 필드명만 수정한다.
DEBUG_CATCHTABLE=1 로 실행하면 1페이지 응답 JSON 앞 3000자를 출력해 구조 확인 가능.
"""
import os
import json
import requests
from datetime import datetime
from typing import List, Tuple

from models import Review

USE_MOCK = os.environ.get("USE_MOCK", "1") == "1"
DEBUG = os.environ.get("DEBUG_CATCHTABLE", "0") == "1"

_API_BASE = "https://biz-api.catchtable.co.kr/manager-api/review/api/v1"
_DEFAULT_SHOP_SEQ = "64686"
_PAGE_SIZE = 50
_MAX_PAGES = 3

_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": "https://manager.catchtable.co.kr",
    "Referer": "https://manager.catchtable.co.kr/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
}


def fetch_reviews(store_id: str) -> List[Review]:
    if USE_MOCK:
        return _mock()

    token = os.environ["CATCHTABLE_TOKEN"]
    shop_seq = store_id or os.environ.get("CATCHTABLE_STORE_ID", _DEFAULT_SHOP_SEQ)

    session = requests.Session()
    session.headers.update({
        **_HEADERS,
        "Authorization": f"Bearer {token}",
    })

    all_items: list = []
    for page in range(_MAX_PAGES):
        resp = session.get(
            f"{_API_BASE}/reviews",
            params={"shopSeq": shop_seq, "size": _PAGE_SIZE, "page": page},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        if DEBUG and page == 0:
            print("[DEBUG CatchTable 응답 (page 0, 앞 3000자)]")
            print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])

        items, has_next = _extract_items(data)
        all_items.extend(items)
        if not has_next or not items:
            break

    return [_to_review(it) for it in all_items]


def _extract_items(data: dict) -> Tuple[list, bool]:
    """응답 JSON에서 리뷰 배열과 다음 페이지 존재 여부를 반환한다."""
    # 실제 응답: {"items": [...], "totalPage": N, "currentPage": N, "totalCount": N}
    if isinstance(data.get("items"), list):
        total_pages = int(data.get("totalPage", 1))
        current = int(data.get("currentPage", 0))
        return data["items"], (current + 1 < total_pages)

    if isinstance(data, list):
        return data, False

    raise ValueError(
        "응답에서 리뷰 배열을 찾지 못했습니다.\n"
        "DEBUG_CATCHTABLE=1 USE_MOCK=0 python main.py 로 재실행해 응답 구조를 확인하고\n"
        "_extract_items() 의 탐색 경로를 수정하세요.\n"
        f"응답 최상위 키: {list(data.keys()) if isinstance(data, dict) else type(data)}"
    )


def _to_review(it: dict) -> Review:
    # 실제 필드: reviewSeq, userDisplayName, totalScore, content, regDateTime, photos
    review_id = str(it.get("reviewSeq") or "")
    author = it.get("userDisplayName") or "익명"
    rating = it.get("totalScore")
    text = it.get("content") or ""
    raw_date = it.get("regDateTime") or ""
    created_at = (
        datetime.fromisoformat(raw_date).replace(tzinfo=None)
        if raw_date
        else datetime.now()
    )
    photos = it.get("photos") or []
    photo_url = photos[0].get("reviewImgUrl") if photos else None
    return Review("catchtable", review_id, author, rating, text, created_at, None, photo_url)


def _mock() -> List[Review]:
    from datetime import timedelta
    now = datetime.now()
    return [
        Review("catchtable", "c2001", "미식가J", 4.5,
               "예약하고 방문했는데 안내가 매끄러웠어요. 코스 구성도 알차고 분위기 최고.",
               now - timedelta(hours=7), "https://app.catchtable.co.kr/ct/shop/0000"),
        Review("catchtable", "c2002", "또갈집", 5.0,
               "재방문입니다. 직원분들 친절하시고 음식 퀄리티 일정해서 믿고 가요.",
               now - timedelta(hours=2)),
    ]

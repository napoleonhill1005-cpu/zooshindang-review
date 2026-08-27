"""캐치테이블 사장님(관리자) 페이지 리뷰 수집기.

인증: CATCHTABLE_TOKEN 환경변수 (DevTools cURL의 Authorization: Bearer 값)
매장: CATCHTABLE_STORE_ID 환경변수 = shopSeq (기본값 64686)

최대 3페이지(page 0-2, size=50)까지 수집한다.
store.py의 ID 기반 중복제거가 있으므로 넉넉하게 가져와도 무방하다.

응답 구조가 바뀌면 _extract_items() 또는 _to_review() 의 필드명만 수정한다.
DEBUG_CATCHTABLE=1 로 실행하면 1페이지 응답 JSON 앞 3000자를 출력해 구조 확인 가능.
"""
import math
import os
import json
import requests
from datetime import datetime
from typing import List, Optional, Tuple

from models import Review, AuthError

USE_MOCK = os.environ.get("USE_MOCK", "1") == "1"
DEBUG = os.environ.get("DEBUG_CATCHTABLE", "0") == "1"

_API_BASE = "https://biz-api.catchtable.co.kr/manager-api/review/api/v1"
_DEFAULT_SHOP_SEQ = "64686"
_PAGE_SIZE = 50
_MAX_PAGES = 3
_MAX_STATS_PAGES = 40  # 누적 통계용 전체 페이징 안전 상한 (50건 × 40 = 2,000건)

# 소수 첫째 자리 반올림 표시가 5.0이 되는 최소 평균.
# 진짜 평균 5.0은 5점 아닌 리뷰가 하나라도 있으면 수학적으로 도달 불가이므로
# '표시 평점 5.0'을 목표로 계산한다.
_DISPLAY_TARGET = 4.95

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


def _session_and_shop(store_id: str) -> Tuple[requests.Session, str]:
    # 시크릿에 줄바꿈/공백이 섞이거나 실수로 'Bearer ' 접두어를 같이 넣어도
    # HTTP 헤더가 깨지지 않도록 방어적으로 정리한다.
    token = os.environ["CATCHTABLE_TOKEN"].strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    shop_seq = store_id or os.environ.get("CATCHTABLE_STORE_ID", _DEFAULT_SHOP_SEQ)

    session = requests.Session()
    session.headers.update({
        **_HEADERS,
        "Authorization": f"Bearer {token}",
    })
    return session, shop_seq


def fetch_reviews(store_id: str) -> List[Review]:
    if USE_MOCK:
        return _mock()

    session, shop_seq = _session_and_shop(store_id)

    all_items: list = []
    for page in range(_MAX_PAGES):
        resp = session.get(
            f"{_API_BASE}/reviews",
            params={"shopSeq": shop_seq, "size": _PAGE_SIZE, "page": page},
            timeout=20,
        )
        # 401/403 = 토큰 만료·무효 → '진짜 0건'과 구별되도록 명시적 예외
        if resp.status_code in (401, 403):
            raise AuthError("catchtable")
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


def fetch_stats(store_id: str = "") -> dict:
    """누적 리뷰 통계: 전체 페이지를 돌며 총 건수·평점 합계를 집계한다.

    반환: {"total": 총건수, "rated": 별점있는건수, "score_sum": 별점합, "avg": 평균(둘째자리)}
    """
    if USE_MOCK:
        return {"total": 231, "rated": 231, "score_sum": 1113.4, "avg": 4.82}

    session, shop_seq = _session_and_shop(store_id)

    total_count = 0
    rated = 0
    score_sum = 0.0
    for page in range(_MAX_STATS_PAGES):
        resp = session.get(
            f"{_API_BASE}/reviews",
            params={"shopSeq": shop_seq, "size": _PAGE_SIZE, "page": page},
            timeout=20,
        )
        if resp.status_code in (401, 403):
            raise AuthError("catchtable")
        resp.raise_for_status()
        data = resp.json()

        items, has_next = _extract_items(data)
        if page == 0 and isinstance(data, dict):
            total_count = int(data.get("totalCount", 0) or 0)
        for it in items:
            score = it.get("totalScore")
            if score is not None:
                rated += 1
                score_sum += float(score)
        if not has_next or not items:
            break

    if not total_count:
        total_count = rated
    avg = round(score_sum / rated, 2) if rated else None
    return {"total": total_count, "rated": rated, "score_sum": score_sum, "avg": avg}


def fives_needed(score_sum: float, rated: int, target: float = _DISPLAY_TARGET) -> Optional[int]:
    """표시 평점 5.0(평균 target 이상)까지 추가로 필요한 5점 리뷰 수. 0 = 이미 달성."""
    if rated <= 0:
        return None
    if score_sum / rated >= target:
        return 0
    # round(…, 6): 30.05/0.05 → 601.0000000000018 같은 부동소수점 오차로 1개 더 세지는 것 방지
    return math.ceil(round((target * rated - score_sum) / (5.0 - target), 6))


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

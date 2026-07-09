from dataclasses import dataclass
from datetime import datetime
from typing import Optional


class AuthError(Exception):
    """수집기 인증 실패(HTTP 401/403). 토큰/쿠키 만료·무효 시 발생.
    '진짜 0건(HTTP 200)'과 구별하기 위해 수집기가 명시적으로 던진다."""


@dataclass
class Review:
    """플랫폼 공통 리뷰 형식."""
    platform: str          # "naver" | "catchtable" | "google"
    review_id: str         # 플랫폼 내 고유 ID (중복제거 키로 사용)
    author: str
    rating: Optional[float]  # 별점. 네이버 방문자리뷰처럼 별점이 없으면 None
    text: str
    created_at: datetime
    url: Optional[str] = None        # 리뷰 원문 링크 (있으면)
    photo_url: Optional[str] = None  # 대표 사진 URL (있으면)

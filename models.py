from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Review:
    """플랫폼 공통 리뷰 형식."""
    platform: str          # "naver" | "catchtable"
    review_id: str         # 플랫폼 내 고유 ID (중복제거 키로 사용)
    author: str
    rating: Optional[float]  # 별점. 네이버 방문자리뷰처럼 별점이 없으면 None
    text: str
    created_at: datetime
    url: Optional[str] = None        # 리뷰 원문 링크 (있으면)
    photo_url: Optional[str] = None  # 대표 사진 URL (있으면)

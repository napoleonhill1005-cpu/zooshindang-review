"""수집한 신규 리뷰를 Slack 게시 전까지 임시 저장한다.

collect 단계(00:00 KST)에서 저장하고, post 단계(09:00 KST)에서 불러와 게시 후 삭제.
GitHub Actions 두 워크플로우 간 데이터는 actions/cache로 공유한다.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import List

from models import Review

PENDING_PATH = Path(__file__).parent / "pending_reviews.json"


def save(reviews: List[Review]) -> None:
    data = [
        {
            "platform": r.platform,
            "review_id": r.review_id,
            "author": r.author,
            "rating": r.rating,
            "text": r.text,
            "created_at": r.created_at.isoformat(),
            "url": r.url,
            "photo_url": r.photo_url,
        }
        for r in reviews
    ]
    PENDING_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load() -> List[Review]:
    if not PENDING_PATH.exists():
        return []
    data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    return [
        Review(
            platform=d["platform"],
            review_id=d["review_id"],
            author=d["author"],
            rating=d["rating"],
            text=d["text"],
            created_at=datetime.fromisoformat(d["created_at"]),
            url=d.get("url"),
            photo_url=d.get("photo_url"),
        )
        for d in data
    ]


def clear() -> None:
    PENDING_PATH.unlink(missing_ok=True)

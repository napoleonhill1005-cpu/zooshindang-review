"""이미 슬랙에 올린 리뷰를 기록해 두고, 다음 실행 때 새 리뷰만 골라낸다.

리뷰 ID 기준으로 중복을 제거하므로 '전날 + 새벽 리뷰'가 정확히 한 번씩만 게시된다.
(시간 윈도우로 자르는 방식의 경계 누락/중복 문제를 피하기 위함)
"""
import sqlite3
from pathlib import Path
from typing import List

from models import Review

DB_PATH = Path(__file__).parent / "seen_reviews.db"


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute(
        "CREATE TABLE IF NOT EXISTS seen ("
        "platform TEXT, review_id TEXT, "
        "PRIMARY KEY (platform, review_id))"
    )
    return c


def filter_new(reviews: List[Review]) -> List[Review]:
    """아직 게시한 적 없는 리뷰만 반환."""
    with _conn() as c:
        new = []
        for r in reviews:
            seen = c.execute(
                "SELECT 1 FROM seen WHERE platform=? AND review_id=?",
                (r.platform, r.review_id),
            ).fetchone()
            if not seen:
                new.append(r)
        return new


def mark_seen(reviews: List[Review]) -> None:
    """게시 완료한 리뷰를 기록."""
    with _conn() as c:
        c.executemany(
            "INSERT OR IGNORE INTO seen(platform, review_id) VALUES (?, ?)",
            [(r.platform, r.review_id) for r in reviews],
        )

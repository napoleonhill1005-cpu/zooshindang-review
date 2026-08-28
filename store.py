"""이미 슬랙에 올린 리뷰를 기록해 두고, 다음 실행 때 새 리뷰만 골라낸다.

리뷰 ID 기준으로 중복을 제거하므로 '전날 + 새벽 리뷰'가 정확히 한 번씩만 게시된다.
(시간 윈도우로 자르는 방식의 경계 누락/중복 문제를 피하기 위함)

추가로 totals_history 테이블에 일자별 누적 리뷰 총 건수 스냅샷을 남겨
주간/월간 증가량(이번 주/이번 달/지난 달 쌓은 리뷰 수) 계산에 쓴다.
"""
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

from models import Review

DB_PATH = Path(__file__).parent / "seen_reviews.db"

# totals_history에서 조회 가능한 컬럼 화이트리스트
_TOTAL_COLUMNS = ("naver_total", "catchtable_total")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute(
        "CREATE TABLE IF NOT EXISTS seen ("
        "platform TEXT, review_id TEXT, "
        "PRIMARY KEY (platform, review_id))"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS totals_history ("
        "day TEXT PRIMARY KEY, "
        "naver_total INTEGER, catchtable_total INTEGER)"
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


def record_totals(day: str, naver_total: Optional[int] = None,
                  catchtable_total: Optional[int] = None) -> None:
    """일자(YYYY-MM-DD)별 누적 총 건수 스냅샷 기록.
    같은 날 재기록 시 값이 있는 컬럼만 갱신한다 (한쪽 수집 실패 시 기존 값 보존)."""
    with _conn() as c:
        row = c.execute(
            "SELECT naver_total, catchtable_total FROM totals_history WHERE day=?",
            (day,),
        ).fetchone()
        if row:
            naver_total = naver_total if naver_total is not None else row[0]
            catchtable_total = catchtable_total if catchtable_total is not None else row[1]
        c.execute(
            "INSERT OR REPLACE INTO totals_history(day, naver_total, catchtable_total) "
            "VALUES (?, ?, ?)",
            (day, naver_total, catchtable_total),
        )


def totals_asof(day: str, column: str) -> Optional[int]:
    """day 이하 가장 최근 스냅샷의 해당 플랫폼 총 건수. 없으면 None."""
    assert column in _TOTAL_COLUMNS, column
    with _conn() as c:
        row = c.execute(
            f"SELECT {column} FROM totals_history "
            f"WHERE day<=? AND {column} IS NOT NULL ORDER BY day DESC LIMIT 1",
            (day,),
        ).fetchone()
        return row[0] if row else None


def totals_earliest(column: str) -> Optional[Tuple[str, int]]:
    """가장 오래된 스냅샷 (day, 총건수). 없으면 None. 히스토리 초기 구간 폴백용."""
    assert column in _TOTAL_COLUMNS, column
    with _conn() as c:
        row = c.execute(
            f"SELECT day, {column} FROM totals_history "
            f"WHERE {column} IS NOT NULL ORDER BY day ASC LIMIT 1",
        ).fetchone()
        return (row[0], row[1]) if row else None

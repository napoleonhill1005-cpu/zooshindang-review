"""플랫폼 누적 리뷰 통계 수집·표시.

- 네이버: 누적 리뷰 총 건수 (GraphQL total 필드)
- 캐치테이블: 누적 총 건수 + 평균 평점 + '표시 평점 5.0'까지 필요한 5점 리뷰 수
  (표시 평점 5.0 = 소수 첫째 자리 반올림 기준, 평균 4.95 이상)

'현황' 명령(status.py)과 아침 다이제스트(main.py collect→post) 양쪽에서 사용한다.
실패해도 본 기능(리뷰 게시/현황)이 죽지 않도록 여기서 예외를 삼킨다.
"""
import traceback
from typing import List

from fetchers import naver, catchtable


def collect_totals(naver_place_id: str = "", catchtable_store_id: str = "") -> dict:
    """누적 통계 dict 반환. 실패한 플랫폼 키는 빠진다.

    키: naver_total, catchtable_total, catchtable_avg, catchtable_fives_needed
    """
    stats: dict = {}

    try:
        stats["naver_total"] = naver.fetch_total(naver_place_id)
    except Exception:
        print(f"[warn] 네이버 누적 통계 수집 실패:\n{traceback.format_exc()}")

    try:
        ct = catchtable.fetch_stats(catchtable_store_id)
        stats["catchtable_total"] = ct["total"]
        if ct["avg"] is not None:
            stats["catchtable_avg"] = ct["avg"]
            need = catchtable.fives_needed(ct["score_sum"], ct["rated"])
            if need is not None:
                stats["catchtable_fives_needed"] = need
    except Exception:
        print(f"[warn] 캐치테이블 누적 통계 수집 실패:\n{traceback.format_exc()}")

    return stats


def stats_lines(stats: dict) -> List[str]:
    """collect_totals() 결과를 슬랙 표시용 문자열 목록으로 변환."""
    if not stats:
        return []
    lines = []

    nv_total = stats.get("naver_total")
    if nv_total is not None:
        lines.append(f"🟢 네이버 누적 리뷰 *{nv_total:,}건*")

    ct_total = stats.get("catchtable_total")
    if ct_total is not None:
        line = f"🔵 캐치테이블 누적 리뷰 *{ct_total:,}건*"
        ct_avg = stats.get("catchtable_avg")
        if ct_avg is not None:
            line += f" · 평점 *{ct_avg:.2f}점*"
        lines.append(line)

    need = stats.get("catchtable_fives_needed")
    if need is not None:
        if need == 0:
            lines.append("⭐ 캐치테이블 표시 평점 5.0 달성 중! 유지가 목표예요")
        else:
            lines.append(
                f"⭐ 캐치테이블 5.0까지 5점 리뷰 *{need:,}개* 더 필요해요"
                " (반올림 표시 5.0 = 평균 4.95 기준)"
            )

    return lines

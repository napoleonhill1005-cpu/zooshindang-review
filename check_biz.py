"""전날 영업일 리뷰 건수 확인 (seen DB 무시, Slack 미게시)."""
import os
import sys
from datetime import datetime, date, timedelta

sys.path.insert(0, ".")
from fetchers import naver, catchtable

BIZ_DATE  = date(2026, 6, 2)
BIZ_START = datetime(2026, 6, 2, 10, 0)
BIZ_END   = datetime(2026, 6, 3,  3, 0)

print(f"=== {BIZ_DATE} 영업일 ({BIZ_START.strftime('%H:%M')} ~ {BIZ_END.strftime('%m/%d %H:%M')} KST) ===\n")

# 네이버
try:
    nv = naver.fetch_reviews(os.environ.get("NAVER_PLACE_ID", "1916994932"))
    nv_biz = [r for r in nv if r.created_at.date() == BIZ_DATE]
    print(f"[네이버] API {len(nv)}건 / 영업일 해당 {len(nv_biz)}건")
    for r in sorted(nv_biz, key=lambda r: r.created_at):
        t = r.created_at.strftime("%m/%d")
        print(f"  {t}  {r.author:<12} {r.text[:45]}")
except Exception as e:
    print(f"[네이버] 수집 실패: {e}")

print()

# 캐치테이블
try:
    ct = catchtable.fetch_reviews(os.environ.get("CATCHTABLE_STORE_ID", "64686"))
    ct_biz = [r for r in ct if BIZ_START <= r.created_at < BIZ_END]
    print(f"[캐치테이블] API {len(ct)}건 / 영업일 해당 {len(ct_biz)}건")
    for r in sorted(ct_biz, key=lambda r: r.created_at):
        t = r.created_at.strftime("%m/%d %H:%M")
        star = f"★{int(r.rating)}" if r.rating else "  "
        print(f"  {t}  {star}  {r.author:<12} {r.text[:40]}")
except Exception as e:
    print(f"[캐치테이블] 수집 실패: {e}")

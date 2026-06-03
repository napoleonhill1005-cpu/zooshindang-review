"""6/2 리뷰를 seen_reviews.db 무시하고 강제로 Slack에 게시하는 일회성 스크립트."""
import json
import os
import urllib.request
from datetime import date
from fetchers import naver, catchtable
import slack_digest

TARGET = date(2026, 6, 2)
STORE_NAME = os.environ.get("STORE_NAME", "주신당 강남점")
NAVER_STORE_ID = os.environ.get("NAVER_STORE_ID", "10037388")
CATCHTABLE_STORE_ID = os.environ.get("CATCHTABLE_STORE_ID", "64686")
TOKEN = os.environ.get("SLACK_TOKEN", "")
CHANNEL = os.environ.get("SLACK_CHANNEL", "C0B65DH4EGJ")

naver_reviews = []
ct_reviews = []

try:
    naver_reviews = naver.fetch_reviews(NAVER_STORE_ID)
    print(f"네이버 수집: {len(naver_reviews)}건")
except Exception as e:
    print(f"[warn] 네이버 수집 실패: {e}")

try:
    ct_reviews = catchtable.fetch_reviews(CATCHTABLE_STORE_ID)
    print(f"캐치테이블 수집: {len(ct_reviews)}건")
except Exception as e:
    print(f"[warn] 캐치테이블 수집 실패: {e}")

all_reviews = naver_reviews + ct_reviews
target_reviews = [r for r in all_reviews if r.created_at.date() == TARGET]
target_reviews.sort(key=lambda r: r.created_at)

naver_cnt = len([r for r in target_reviews if r.platform == "naver"])
ct_cnt = len([r for r in target_reviews if r.platform == "catchtable"])
print(f"\n6/2 리뷰: {len(target_reviews)}건 (네이버 {naver_cnt}건, 캐치테이블 {ct_cnt}건)")

if not target_reviews:
    print("게시할 리뷰가 없습니다.")
else:
    blocks = slack_digest.build_blocks(target_reviews, STORE_NAME, TARGET)
    print(f"블록 수: {len(blocks)}")
    chunks = list(slack_digest._chunk(blocks, 48))
    print(f"청크 수: {len(chunks)}")

    for i, chunk in enumerate(chunks):
        payload = json.dumps({
            "channel": CHANNEL,
            "blocks": chunk,
            "text": "6/2 리뷰현황",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {TOKEN}",
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                d = json.loads(resp.read().decode("utf-8"))
                if d.get("ok"):
                    print(f"청크 {i+1}/{len(chunks)} 전송 성공")
                else:
                    print(f"청크 {i+1} 실패: {d.get('error')}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"청크 {i+1} HTTP {e.code}: {body[:300]}")

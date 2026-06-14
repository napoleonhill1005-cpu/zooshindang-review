"""캐치테이블 토큰 진단 (임시).

CATCHTABLE_TOKEN 시크릿을 '출력하지 않고' 다음만 확인한다:
  1) JWT 형태가 맞는지 (점으로 나뉜 3세그먼트)
  2) exp(만료시각) vs 현재시각 → 자연 만료 여부
  3) 실제 리뷰 API 호출 HTTP 상태코드 (401=만료/무효, 200=정상)

이걸로 사용자의 두 가설을 가린다:
  - 세그먼트 깨짐/디코드 실패 → 덮어쓰기 실수(2번)
  - exp 과거 → 토큰 단기 만료(진짜 원인)
  - exp 미래인데 401 → 저장/이름 문제 or 권한 변경
"""
import base64
import json
import os
import time
from datetime import datetime, timezone, timedelta

import requests

_KST = timezone(timedelta(hours=9))


def main():
    raw = os.environ.get("CATCHTABLE_TOKEN", "")
    print("=== CATCHTABLE_TOKEN 진단 ===")
    if not raw:
        print("❌ CATCHTABLE_TOKEN 이 비어 있음 → 시크릿 미저장 또는 이름 오타")
        return

    # 값 자체는 절대 출력하지 않는다. 길이/접두어/공백 흔적만.
    print(f"길이: {len(raw)}")
    print(f"'Bearer ' 접두어 포함됨?: {raw.lower().startswith('bearer ')}  (포함이면 2번: 접두어 중복)")
    print(f"양끝 공백/개행 있음?: {raw != raw.strip()}  (있으면 2번: 복사 시 공백 유입)")

    token = raw.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    seg = token.split(".")
    print(f"JWT 세그먼트 수(정상=3): {len(seg)}")
    if len(seg) != 3:
        print("❌ JWT 형태 아님 → 일부만 복사됐거나 다른 값 → 2번(덮어쓰기 실수) 확정")
        return

    try:
        p = seg[1] + "=" * (-len(seg[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(p))
    except Exception as e:
        print(f"❌ payload 디코드 실패({e}) → 토큰 손상 → 2번(덮어쓰기 실수)")
        return

    exp = payload.get("exp")
    iat = payload.get("iat")
    now = time.time()
    if iat:
        print(f"발급시각(iat): {datetime.fromtimestamp(iat, _KST):%Y-%m-%d %H:%M:%S} KST")
    if exp:
        print(f"만료시각(exp): {datetime.fromtimestamp(exp, _KST):%Y-%m-%d %H:%M:%S} KST")
        print(f"현재시각    : {datetime.fromtimestamp(now, _KST):%Y-%m-%d %H:%M:%S} KST")
        if exp < now:
            mins = int((now - exp) / 60)
            print(f"⛔ 이미 {mins}분 전에 만료됨 → '토큰 단기 만료'가 원인 (복사/덮어쓰기 문제 아님)")
        else:
            mins = int((exp - now) / 60)
            print(f"✅ 아직 {mins}분 남음 → 토큰 자체는 유효")
    else:
        print("⚠️ payload 에 exp 없음")

    # 실제 API 한 번 찔러보기
    try:
        r = requests.get(
            "https://biz-api.catchtable.co.kr/manager-api/review/api/v1/reviews",
            params={"shopSeq": os.environ.get("CATCHTABLE_STORE_ID", "64686"), "size": 1, "page": 0},
            headers={
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://manager.catchtable.co.kr",
                "Referer": "https://manager.catchtable.co.kr/",
                "User-Agent": "Mozilla/5.0",
                "Authorization": f"Bearer {token}",
            },
            timeout=20,
        )
        print(f"실제 API 응답코드: {r.status_code}  (401=만료/무효, 200=정상)")
        print(f"응답 앞 300자: {r.text[:300]}")
    except Exception as e:
        print(f"API 호출 예외: {e}")


if __name__ == "__main__":
    main()

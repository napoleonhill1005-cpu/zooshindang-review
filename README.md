# 주신당 강남점 — 리뷰 자동 집계 → 슬랙

네이버 스마트플레이스 + 캐치테이블 리뷰를 매일 아침 9시에 모아 슬랙 채널에 올려주는 봇.

## 동작 방식
1. 매일 09:00(KST) 실행
2. 두 플랫폼에서 최근 리뷰 수집
3. 이미 올린 리뷰는 ID 기준으로 제외 (→ '전날 + 새벽 리뷰'가 정확히 한 번만 게시)
4. 별점/작성자/본문/원문링크를 보기 좋게 슬랙에 게시

```
fetchers/naver.py        ← 네이버 수집기 (엔드포인트만 채우면 됨)
fetchers/catchtable.py   ← 캐치테이블 수집기 (엔드포인트만 채우면 됨)
slack_digest.py          ← 슬랙 메시지 작성/게시 (완성)
store.py                 ← 중복제거 (완성)
main.py                  ← 전체 실행 (완성)
```

## 1) 지금 바로 미리보기 (mock)
엔드포인트 없이 가짜 데이터로 메시지 포맷부터 확인:
```bash
USE_MOCK=1 python main.py        # SLACK_WEBHOOK_URL 없으면 콘솔에 출력
```
실제 슬랙으로 쏴보고 싶으면:
```bash
USE_MOCK=1 SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..." python main.py
```

## 2) 슬랙 Webhook 만들기
1. https://api.slack.com/apps → Create New App → From scratch
2. 좌측 **Incoming Webhooks** → 켜기 → **Add New Webhook to Workspace**
3. 게시할 채널 선택 → 생성된 URL을 `SLACK_WEBHOOK_URL`로 사용

## 3) 리뷰 엔드포인트 캡처 (핵심, 매장당 1회)
두 플랫폼 다 공개 API가 없으므로, **사장님 페이지가 내부적으로 쓰는 JSON 요청**을 재사용한다.
HTML을 긁는 것보다 훨씬 안 깨진다.

1. 크롬에서 해당 관리자 페이지 로그인 → 리뷰 화면
2. F12 → **Network** 탭 → 상단 **Fetch/XHR** 필터
3. 리뷰 목록 새로고침 → 응답(Response)에 리뷰 본문이 들어있는 요청을 찾기
4. 그 요청 우클릭 → **Copy → Copy as cURL** (URL·헤더·쿠키·바디가 전부 들어있음)
5. `fetchers/naver.py` / `fetchers/catchtable.py` 상단 주석의 안내대로
   URL·바디를 채우고, Cookie 값은 `.env`(`NAVER_COOKIE`, `CATCHTABLE_COOKIE`)로 분리
6. `USE_MOCK=0`으로 실행해 실제 수집 확인

> 클로드 코드로 진행하면, 캡처한 cURL을 그대로 붙여넣고 "이걸 fetch_reviews()에 맞게 변환해줘"라고
> 시키는 게 가장 빠르다. 응답 JSON 구조에 맞춰 필드 매핑까지 해준다.

## 4) 매일 자동 실행 (현재 운영 구조 — GitHub Actions)
- **GAS(Google Apps Script)가 매일 08:45 KST에 `collect.yml`을 workflow_dispatch로 트리거**
  (GitHub cron이 불안정해서 GAS가 방아쇠 역할)
- collect 성공 시 `post.yml`이 즉시 자동 연쇄 실행 → **9시 이전 슬랙 게시 보장**
- `watchdog.yml`(cron)이 매일 collect/post가 실제로 돌았는지 독립 점검 후 슬랙 DM 보고
- 토큰/쿠키는 저장소 Settings → Secrets(`SLACK_TOKEN`, `NAVER_COOKIE`, `CATCHTABLE_TOKEN` 등),
  중복제거 DB는 actions/cache로 보존

> ⚠️ **로컬 PC에서 스케줄 실행 금지.** GitHub Actions 밖에서 `USE_MOCK=0`으로 실행하면
> 자동으로 dry-run으로 전환된다(게시/알림 차단). 정말 로컬에서 실전 실행이 필요하면
> `ALLOW_LOCAL_RUN=1`을 명시해야 한다. — 과거 PC 작업 스케줄러에 남은 옛 사본이
> 낡은 토큰으로 중복 게시한 사고(2026-07-23)의 재발 방지 장치.

## ⚠️ 현실적인 주의점
- **쿠키 만료**: 로그인 세션 쿠키는 일정 기간 뒤 만료된다. 만료되면 캡처를 다시 하거나,
  Playwright의 `storage_state`로 로그인 세션을 저장/자동 갱신하는 방식으로 발전시키면 좋다.
- **약관**: 본인 매장의 사장님 데이터를 본인이 보는 용도라 명분은 깔끔하지만,
  자동 수집은 각 플랫폼 정책 변경에 영향받을 수 있다. 응답 구조가 바뀌면 매핑만 수정하면 된다.
- **매장 추가**: 나중에 매장이 늘면 `STORE_*` 환경변수를 매장별로 분리하고 채널/스레드를
  매장별로 나누면 그대로 확장된다.

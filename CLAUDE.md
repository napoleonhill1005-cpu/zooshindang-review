# CLAUDE.md — 프로젝트 컨텍스트 / 인계 문서

## 이 프로젝트가 하는 일
네이버 스마트플레이스 + 캐치테이블의 매장 리뷰를 **매일 아침 9시(KST)**에 모아
슬랙 채널에 다이제스트로 게시하는 봇. 현재 대상 매장은 **주신당 강남점** 1곳.
운영자는 두 플랫폼 모두 **사장님(관리자) 권한**을 보유.

## 핵심 설계 결정 (바꾸지 말 것)
- 두 플랫폼 다 **공개 리뷰 API가 없다.** HTML 스크래핑 대신, 사장님 관리자 페이지가
  내부적으로 호출하는 **JSON 요청을 캡처해 재사용**한다. (안정성이 훨씬 높음)
- 중복제거는 **리뷰 ID 기준**(시간 윈도우 X). `store.py`의 SQLite가 담당.
  → '전날 + 새벽 리뷰'가 정확히 한 번씩만 게시됨. 이 방식을 유지할 것.
- 모든 수집기는 `models.Review` dataclass로 정규화해서 반환한다.

## 현재 상태
| 구성요소 | 상태 |
|---|---|
| `slack_digest.py` (Block Kit 작성/게시, 50블록 청크, dry-run) | ✅ 완성 |
| `store.py` (SQLite ID 기반 중복제거) | ✅ 완성 |
| `main.py` (수집→중복제거→게시 오케스트레이션) | ✅ 완성 |
| `.github/workflows/daily.yml` (09:00 KST 스케줄) | ✅ 완성 |
| `fetchers/naver.py` | ⛔ **TODO** — mock만 있음, 실제 엔드포인트 미구현 |
| `fetchers/catchtable.py` | ⛔ **TODO** — mock만 있음, 실제 엔드포인트 미구현 |
| `schedule_board.py` + `.github/workflows/schedule.yml` (근무표 알림) | ✅ 완성 |

### 근무 스케줄 알림 (`schedule_board.py`)
- 구글 시트(주차별 근무표)를 **실시간 CSV로 읽어** 슬랙에 게시. 근무자를 코드에 박지 않음
  → **매주 시트만 갱신하면 자동 반영**. (시트 = 진실의 원천)
- ⚠️ 시트는 반드시 **"링크가 있는 모든 사용자 - 뷰어"** 공유여야 함 (Actions 러너엔 구글 로그인 없음).
- 기존 "현황"(status.py)과 동일 패턴: 슬랙 입력 → **GAS가 `schedule.yml` workflow_dispatch 호출**.
  - query 빈값 → 오늘(영업일 기준, 새벽 5시 전이면 전날) 근무표
  - query=이름(예 `오시환`) → 그 직원 주간 근무 / query=요일(예 `금`) → 그 요일 근무표
- 시트 ID는 `schedule_board.py`의 `DEFAULT_SHEET_ID`(또는 `SCHEDULE_SHEET_ID` 환경변수).
- 로컬 검증: `SCHEDULE_CSV_FILE=tests/schedule_fixture.csv SLACK_DRY_RUN=1 python schedule_board.py`

`USE_MOCK=1 python main.py` 로 mock 데이터 전체 파이프라인은 이미 정상 동작 확인됨.

## 지금 해야 할 일 (우선순위 순)
1. **수집기 실구현**: 사용자가 크롬 DevTools에서 캡처한 cURL(리뷰 JSON 요청)을 줄 것이다.
   그걸 `fetchers/naver.py` / `fetchers/catchtable.py`의 `fetch_reviews()`에 맞게 변환.
   - URL/메서드/바디는 코드에, **Cookie 등 비밀값은 환경변수**(`NAVER_COOKIE`,
     `CATCHTABLE_COOKIE`)로 분리. 코드에 하드코딩 금지.
   - 응답 JSON 구조에 맞춰 `Review` 필드 매핑 (별점 없으면 `rating=None`).
   - 변환 후 `USE_MOCK=0`으로 실제 1건이라도 떨어지는지 확인.
2. (옵션) 쿠키 만료 대응: Playwright `storage_state`로 로그인 세션 저장/자동 갱신.
3. (옵션) 매장 다중화: `STORE_*` 환경변수를 매장별로 분리, 채널/스레드 분기.

## 테스트 방법
```bash
USE_MOCK=1 python main.py                       # 콘솔 dry-run (웹훅 없이 포맷 확인)
USE_MOCK=1 SLACK_WEBHOOK_URL=... python main.py # 실제 슬랙 게시 테스트
USE_MOCK=0 ... python main.py                   # 실제 수집 (엔드포인트 구현 후)
```

## 주의
- `seen_reviews.db`는 커밋하지 말 것 (로컬 상태). 깃에 올릴 땐 `.gitignore`에 추가.
- 실제 Cookie/Webhook URL을 코드나 커밋에 남기지 말 것.
- 응답 구조가 바뀌어 깨지면, 수집기의 **필드 매핑만** 수정하면 된다.

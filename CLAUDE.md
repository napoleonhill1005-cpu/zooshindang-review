# CLAUDE.md — 프로젝트 컨텍스트 / 인계 문서

## 이 프로젝트가 하는 일
네이버 스마트플레이스 + 캐치테이블 + 구글 비즈니스 프로필의 매장 리뷰를 매일 자동 수집해
슬랙 채널(`#03_매장리뷰_현황`)에 다이제스트로 게시하는 봇.
현재 대상 매장: **주신당 강남점** 1곳.
(구글은 코드 완성, 아래 "구글 연동 상태" 참고 — 비즈니스 프로필 인증 대기 중이라 아직 라이브 수집 전.)

## 핵심 설계 결정 (바꾸지 말 것)
- 두 플랫폼 다 공개 리뷰 API 없음 → 사장님 관리자 페이지가 내부 호출하는 JSON 요청을 캡처해 재사용 (스크래핑보다 안정적)
- 중복제거는 **리뷰 ID 기준**. `store.py`의 SQLite 담당 → 리뷰가 정확히 한 번씩만 게시됨
- 모든 수집기는 `models.Review` dataclass로 정규화해서 반환
- **영업일 기준**: 당일 10:00 KST ~ 익일 03:00 KST (17시간)
- **collect/post 분리**: 08:00에 수집 → `pending_reviews.json` 저장, 09:00에 Slack 게시

## 현재 상태 (전체 완성, 운영 중)

| 구성요소 | 상태 |
|---|---|
| `fetchers/naver.py` | ✅ 완성 — GraphQL `getVisitorReviews`, display=50 단건, `NAVER_COOKIE` 인증 |
| `fetchers/catchtable.py` | ✅ 완성 — REST `/manager-api/review/api/v1/reviews`, 최대 3페이지, `CATCHTABLE_TOKEN` Bearer 인증 |
| `fetchers/google.py` | ✅ 코드완성 / ⏳ **미가동** — 공식 Business Profile API(v4 `reviews`), OAuth refresh token 인증. 설정·인증 대기 (아래 "구글 연동 상태" 참고) |
| `slack_digest.py` | ✅ 완성 — Block Kit, 50블록 청크, dry-run |
| `store.py` | ✅ 완성 — SQLite ID 기반 중복제거 + `totals_history` 일자별 누적 스냅샷(주간/월간 증가량용) |
| `pending.py` | ✅ 완성 — collect/post 간 `pending_reviews.json`(리뷰) + `pending_stats.json`(누적 통계) 임시 저장 |
| `totals.py` | ✅ 완성 — 누적 통계(네이버 총 건수, 캐치테이블 총 건수·평점·표시 5.0까지 필요한 5점 수) + 이번 주/이번 달/지난 달 증가량("7,289 → 7,400개 (+111)") + 🎯 다음 목표(네이버 100건 단위 마일스톤, 캐치테이블 5.0). 아침 다이제스트와 `status.py`(현황 명령) 양쪽에 표시. 스냅샷 기록은 아침 collect만(`attach_periods(record=True)`), 현황은 조회 전용 |
| `main.py` | ✅ 완성 — collect/post 분리 모드, 영업일 필터링, 인증 만료 체크, 0건 알림 |
| `alert.py` | ✅ 완성 — GitHub Actions failure 단계 장애 알림 헬퍼 |
| `check_biz.py` | ✅ 완성 — 특정 영업일 리뷰 건수 수동 확인 스크립트 |
| `force_post.py` | ✅ 완성 — 강제 게시 스크립트 |
| GitHub Actions 워크플로우 | ✅ 완성 — collect(08:00 KST) / post(09:00 KST) 분리 |

## 환경변수

| 변수 | 용도 | 비고 |
|---|---|---|
| `NAVER_COOKIE` | 네이버 GraphQL 인증 | DevTools cURL의 `-b` 값 전체 |
| `CATCHTABLE_TOKEN` | 캐치테이블 Bearer 토큰 | JWT, 만료일 자동 체크됨 |
| `SLACK_TOKEN` | Slack 게시 (`xoxp-...`) | 없으면 콘솔 dry-run |
| `SLACK_CHANNEL` | 게시 채널 | 기본값: `#03_매장리뷰_현황` |
| `NAVER_PLACE_ID` | 네이버 pcmap place ID | 기본값: `1916994932` |
| `CATCHTABLE_STORE_ID` | 캐치테이블 shopSeq | 기본값: `64686` |
| `STORE_NAME` | 매장 표시 이름 | 기본값: `주신당 강남점` |
| `USE_MOCK` | mock 데이터 사용 | `1`(기본) / `0` |
| `SLACK_DRY_RUN` | 슬랙 미게시 테스트 | `1`이면 콘솔만 출력 |
| `GOOGLE_CLIENT_ID` | GCP OAuth 클라이언트 ID | 미설정 시 구글 자동 스킵 |
| `GOOGLE_CLIENT_SECRET` | GCP OAuth 클라이언트 시크릿 | |
| `GOOGLE_REFRESH_TOKEN` | `scripts/google_oauth_setup.py`로 1회 발급 | invalid_grant 시 재발급 |
| `GOOGLE_ACCOUNT_ID` | `accounts/{숫자}`의 숫자 | |
| `GOOGLE_LOCATION_ID` | `locations/{숫자}`의 숫자, 매장별 | `collect.yml`에 직접 기입(현재 빈 값) |

## 구글 연동 상태 (2026-07-13 기준)
코드는 완성(`fetchers/google.py` + `main.py` 배선 + `docs/GOOGLE_SETUP.md` + `scripts/google_oauth_setup.py`)
이지만 **아직 라이브 수집 전**. 남은 관문과 진행상황:

- ✅ GCP 프로젝트 생성: `zooshindang-review` (프로젝트번호 `968015346555`)
- ⏳ **비즈니스 프로필 인증 대기 = 현재 병목**
  - 사용 계정: `napoleonhill1005@gmail.com`
  - 주신당 강남점 리스팅(오래된 리스팅, listing_id `9784776154810738835`)을 이 계정으로 claim →
    구글이 **매장 주소로 인증 엽서(우편) 발송함** (배송 최대 16일)
  - ⚠️ 엽서를 광고우편으로 착각해 버리지 말 것. 엽서 코드 입력해야 인증 완료
  - 리스팅이 오래돼서 "60일 이상 활성" 조건은 사실상 충족 → **엽서 인증만 통과하면 다음 단계 가능**
- ⬜ (인증 후) Business Profile API 액세스 신청 — GBP API contact form, Basic API Access, 프로젝트번호 입력 → 검토 1~2주
- ⬜ (승인 후) `docs/GOOGLE_SETUP.md` 3~5단계: API 활성화 → OAuth 데스크톱 클라이언트 → `google_oauth_setup.py`로 토큰/ID 발급
- ⬜ (마지막) `collect.yml`의 `GOOGLE_LOCATION_ID` 채우고 GitHub Secrets(`GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN/ACCOUNT_ID`) 등록 → `USE_MOCK=0 DEBUG_GOOGLE=1 SLACK_DRY_RUN=1 python main.py collect`로 확인

## 알림/모니터링 기능
- **CATCHTABLE_TOKEN 만료 임박 (3일 전)**: 슬랙 경고
- **CATCHTABLE_TOKEN 만료됨**: 슬랙 에러 알림
- **NAVER_COOKIE 401/403**: 슬랙 에러 알림
- **수집 0건** (토큰은 있는데): "만료 or API 변경 의심" 슬랙 경고
- **pending 없이 post 실행 시**: "collect 실패 or 신규 리뷰 0건" 알림

## 테스트 방법
```bash
USE_MOCK=1 python main.py                          # mock 전체 파이프라인 (collect+post)
USE_MOCK=1 python main.py collect                  # collect 단계만
USE_MOCK=1 python main.py post                     # post 단계만
USE_MOCK=1 SLACK_WEBHOOK_URL=... python main.py    # 실제 슬랙 게시 테스트
USE_MOCK=0 python main.py                          # 실제 수집
DEBUG_NAVER=1 USE_MOCK=0 python main.py collect    # 네이버 응답 JSON 디버그
DEBUG_CATCHTABLE=1 USE_MOCK=0 python main.py collect  # 캐치테이블 응답 JSON 디버그
DEBUG_GOOGLE=1 USE_MOCK=0 python main.py collect       # 구글 응답 JSON 디버그 (인증/토큰 설정 후)
python check_biz.py                                # 특정 영업일 리뷰 수동 확인
```

## 앞으로 할 수 있는 것 (옵션)
1. **쿠키 자동 갱신**: Playwright `storage_state`로 로그인 세션 저장 → 만료 전 자동 재취득
2. **매장 다중화**: `STORE_*` 환경변수를 매장별로 분리, 채널/스레드 분기
3. **리뷰 답글 기능**: 슬랙에서 이모지/버튼으로 답글 트리거

## 주의
- `seen_reviews.db`, `pending_reviews.json`, `pending_stats.json`은 커밋 금지 (`.gitignore` 등록됨)
- 캐치테이블 점수 판정: 리뷰는 0.5점 단위(1.0, 1.5, …)인데 시스템이 반올림해 후하게 판정 →
  **4.5점 리뷰 = 5점 취급** (`catchtable._effective_score`). 누적 평점·5점 필요 수·다이제스트 별점 집계 모두 이 판정 점수 기준
- '표시 평점 5.0'은 소수 첫째 자리 반올림 기준(평균 4.95 이상). 진짜 평균 5.0은 5점 아닌 리뷰가 있으면 도달 불가라 이 기준으로 계산 (`catchtable.fives_needed`)
- 실제 Cookie/Token/Webhook URL을 코드나 커밋에 남기지 말 것
- 응답 구조 변경 시 수집기의 **필드 매핑만** 수정 (`_to_review()` 또는 `_extract_items()`)
- `force_post.py` 는 seen DB 무시하고 강제 게시하므로 중복 게시 주의

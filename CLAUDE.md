# CLAUDE.md — 프로젝트 컨텍스트 / 인계 문서

## 이 프로젝트가 하는 일
네이버 스마트플레이스 + 캐치테이블의 매장 리뷰를 매일 자동 수집해
슬랙 채널(`#03_매장리뷰_현황`)에 다이제스트로 게시하는 봇.
현재 대상 매장: **주신당 강남점** 1곳.

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
| `slack_digest.py` | ✅ 완성 — Block Kit, 50블록 청크, dry-run |
| `store.py` | ✅ 완성 — SQLite ID 기반 중복제거 |
| `pending.py` | ✅ 완성 — collect/post 간 `pending_reviews.json` 임시 저장 |
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
python check_biz.py                                # 특정 영업일 리뷰 수동 확인
```

## 앞으로 할 수 있는 것 (옵션)
1. **쿠키 자동 갱신**: Playwright `storage_state`로 로그인 세션 저장 → 만료 전 자동 재취득
2. **매장 다중화**: `STORE_*` 환경변수를 매장별로 분리, 채널/스레드 분기
3. **리뷰 답글 기능**: 슬랙에서 이모지/버튼으로 답글 트리거

## 주의
- `seen_reviews.db`, `pending_reviews.json`은 커밋 금지 (`.gitignore` 등록됨)
- 실제 Cookie/Token/Webhook URL을 코드나 커밋에 남기지 말 것
- 응답 구조 변경 시 수집기의 **필드 매핑만** 수정 (`_to_review()` 또는 `_extract_items()`)
- `force_post.py` 는 seen DB 무시하고 강제 게시하므로 중복 게시 주의

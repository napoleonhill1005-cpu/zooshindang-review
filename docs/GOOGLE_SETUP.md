# 구글 리뷰 수집 설정 가이드

구글은 네이버/캐치테이블과 달리 **공식 API**(Google Business Profile API)가 있다.
쿠키 캡처가 필요 없고, 한 번 설정하면 refresh token이 사실상 만료되지 않아 가장 안정적이다.
단, 최초 1회 GCP 설정 + 구글의 API 액세스 승인(영업일 약 2주)이 필요하다.

전제: 매장이 [구글 비즈니스 프로필](https://business.google.com)에 등록되어 있고,
설정에 사용할 구글 계정이 그 매장의 **소유자/관리자**여야 한다.

## 1. GCP 프로젝트 생성
1. https://console.cloud.google.com → 새 프로젝트 생성 (이름 예: `zooshindang-review`)

## 2. Business Profile API 액세스 신청 ← 가장 오래 걸리는 단계
구글은 이 API를 승인제로 운영한다. 승인 전에는 쿼터가 0이라 모든 호출이 403으로 실패한다.
1. https://developers.google.com/my-business/content/prereqs 의 절차에 따라
   [액세스 신청 폼](https://docs.google.com/forms/d/e/1FAIpQLSfC_FK2-rIDOOTGTbZfWIBoQk0DX6X63rEXGqs7-tJaAJ77Hg/viewform) 제출
   - 프로젝트 번호(GCP 콘솔 대시보드에서 확인), 회사/매장 정보 입력
2. 승인 메일이 오면 (보통 1~2주) 다음 단계 진행

## 3. API 활성화
GCP 콘솔 → "API 및 서비스" → 라이브러리에서 아래 3개를 **사용 설정**:
- **Google My Business API** (v4 — 리뷰 조회용)
- **My Business Account Management API** (계정 ID 조회용)
- **My Business Business Information API** (매장 ID 조회용)

## 4. OAuth 클라이언트 생성
1. "API 및 서비스" → "OAuth 동의 화면"
   - User Type: **외부**, 테스트 사용자에 본인 구글 계정 추가
   - 앱을 "프로덕션"으로 게시하지 않으면 refresh token이 **7일마다 만료**되므로,
     테스트 완료 후 반드시 게시 상태로 전환할 것 (검증 불필요 — 내부용이므로 경고 무시 가능)
2. "사용자 인증 정보" → "OAuth 클라이언트 ID 만들기" → 유형: **데스크톱 앱**
3. 발급된 클라이언트 ID / 시크릿을 기록

## 5. Refresh Token + 계정/매장 ID 발급
로컬 PC에서 (브라우저 필요):
```bash
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python scripts/google_oauth_setup.py
```
브라우저에서 매장 관리 계정으로 로그인하면 터미널에 출력된다:
- `GOOGLE_REFRESH_TOKEN`
- `GOOGLE_ACCOUNT_ID` (accounts/{숫자}의 숫자)
- `GOOGLE_LOCATION_ID` (locations/{숫자}의 숫자, 매장별)

## 6. GitHub Secrets / 워크플로 설정
저장소 → Settings → Secrets and variables → Actions에 등록:

| Secret | 값 |
|---|---|
| `GOOGLE_CLIENT_ID` | 4단계 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | 4단계 클라이언트 시크릿 |
| `GOOGLE_REFRESH_TOKEN` | 5단계 출력값 |

`GOOGLE_ACCOUNT_ID` / `GOOGLE_LOCATION_ID`는 비밀값이 아니므로
`.github/workflows/collect.yml`의 env에 직접 기입한다 (현재 빈 값 — 5단계 출력으로 채울 것).

## 7. 동작 확인
```bash
USE_MOCK=0 DEBUG_GOOGLE=1 SLACK_DRY_RUN=1 python main.py collect
```
구글 리뷰가 1건 이상 떨어지면 완료.

## 문제 해결
- **403 PERMISSION_DENIED**: 2단계 승인 전이거나 3단계 API 미활성. 승인 메일 확인.
- **invalid_grant**: refresh token 만료/회수. 4-1단계의 "프로덕션 게시" 여부 확인 후
  5단계 재실행으로 재발급.
- **리뷰 0건인데 실제론 있음**: `GOOGLE_LOCATION_ID`가 다른 매장일 수 있음. 5단계 재실행해 확인.

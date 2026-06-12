"""구글 비즈니스 프로필 OAuth 1회 설정 스크립트 (로컬 PC에서 실행).

하는 일:
  1. 브라우저로 구글 로그인 → GOOGLE_REFRESH_TOKEN 발급
  2. 발급된 토큰으로 계정/매장 목록 조회 → GOOGLE_ACCOUNT_ID, GOOGLE_LOCATION_ID 출력

사전 준비 (docs/GOOGLE_SETUP.md 참고):
  - GCP 프로젝트에서 OAuth 클라이언트(데스크톱 앱) 생성
  - 환경변수 GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET 설정 (또는 실행 시 입력)

실행:
  python scripts/google_oauth_setup.py
"""
import http.server
import os
import sys
import threading
import urllib.parse
import webbrowser

import requests

_SCOPE = "https://www.googleapis.com/auth/business.manage"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
_LOCATIONS_URL = (
    "https://mybusinessbusinessinformation.googleapis.com/v1/{account}/locations"
)
_PORT = 8765
_REDIRECT_URI = f"http://localhost:{_PORT}"

_auth_code = None


class _CodeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _auth_code = (qs.get("code") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "인증 완료! 터미널로 돌아가세요." if _auth_code else "인증 실패 (code 없음)"
        self.wfile.write(f"<h2>{msg}</h2>".encode("utf-8"))

    def log_message(self, *args):
        pass


def _get_authorization_code(client_id: str) -> str:
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": _REDIRECT_URI,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",   # refresh_token 발급에 필수
        "prompt": "consent",        # 재실행 시에도 refresh_token 재발급
    })
    url = f"{_AUTH_URL}?{params}"

    server = http.server.HTTPServer(("localhost", _PORT), _CodeHandler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    print(f"\n브라우저가 열립니다. 매장 관리 권한이 있는 구글 계정으로 로그인하세요.")
    print(f"열리지 않으면 직접 접속: {url}\n")
    webbrowser.open(url)

    server_thread_timeout = 300
    import time
    waited = 0
    while _auth_code is None and waited < server_thread_timeout:
        time.sleep(1)
        waited += 1
    if _auth_code is None:
        sys.exit("5분 내 인증이 완료되지 않았습니다. 다시 실행해 주세요.")
    return _auth_code


def main():
    client_id = os.environ.get("GOOGLE_CLIENT_ID") or input("GOOGLE_CLIENT_ID: ").strip()
    client_secret = (
        os.environ.get("GOOGLE_CLIENT_SECRET") or input("GOOGLE_CLIENT_SECRET: ").strip()
    )

    code = _get_authorization_code(client_id)

    resp = requests.post(_TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": _REDIRECT_URI,
    }, timeout=20)
    resp.raise_for_status()
    tokens = resp.json()
    refresh_token = tokens.get("refresh_token")
    access_token = tokens["access_token"]

    print("\n" + "=" * 60)
    print("GOOGLE_REFRESH_TOKEN (GitHub Secret에 등록):")
    print(refresh_token or "(발급 안 됨 — prompt=consent로 재시도 필요)")
    print("=" * 60)

    headers = {"Authorization": f"Bearer {access_token}"}

    resp = requests.get(_ACCOUNTS_URL, headers=headers, timeout=20)
    if resp.status_code == 403:
        print("\n⚠️ 계정 목록 조회 403 — GCP에서 Business Profile API 액세스 승인이")
        print("   아직 안 났거나 API가 비활성 상태입니다. docs/GOOGLE_SETUP.md 2단계 확인.")
        return
    resp.raise_for_status()
    accounts = resp.json().get("accounts", [])

    for acc in accounts:
        acc_name = acc["name"]  # "accounts/1234567890"
        print(f"\n계정: {acc.get('accountName', '')}  →  GOOGLE_ACCOUNT_ID = {acc_name.split('/')[1]}")
        resp = requests.get(
            _LOCATIONS_URL.format(account=acc_name),
            params={"readMask": "name,title"},
            headers=headers,
            timeout=20,
        )
        resp.raise_for_status()
        for loc in resp.json().get("locations", []):
            loc_id = loc["name"].split("/")[1]  # "locations/9876543210"
            print(f"  매장: {loc.get('title', '')}  →  GOOGLE_LOCATION_ID = {loc_id}")


if __name__ == "__main__":
    main()

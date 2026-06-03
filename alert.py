"""GitHub Actions failure 단계에서 Slack으로 장애 알림을 보내는 헬퍼.

사용법: python alert.py "메시지"
"""
import json
import os
import sys
import urllib.request

message = sys.argv[1] if len(sys.argv) > 1 else "🚨 리뷰봇 오류 발생"
token = os.environ.get("SLACK_TOKEN", "")
channel = os.environ.get("SLACK_CHANNEL", "#03_매장리뷰_현황")

if not token:
    print(f"[alert] SLACK_TOKEN 없음 — 콘솔 출력: {message}")
    sys.exit(0)

payload = json.dumps({"channel": channel, "text": message}).encode("utf-8")
req = urllib.request.Request(
    "https://slack.com/api/chat.postMessage",
    data=payload,
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
)
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("ok"):
            print(f"[alert] 전송 완료: {message}")
        else:
            print(f"[alert] 전송 실패: {data.get('error')}")
except Exception as e:
    print(f"[alert] 예외: {e}")

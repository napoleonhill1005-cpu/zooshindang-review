import os
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.environ["SLACK_TOKEN"]
channel = "#03_매장리뷰_현황"

resp = requests.post(
    "https://slack.com/api/chat.postMessage",
    headers={"Authorization": f"Bearer {token}"},
    json={"channel": channel, "text": "테스트 메시지"},
)

data = resp.json()
if data.get("ok"):
    print("전송 성공:", data["ts"])
else:
    print("전송 실패:", data.get("error"))

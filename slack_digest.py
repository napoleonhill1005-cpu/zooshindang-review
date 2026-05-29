"""수집한 리뷰를 Slack Block Kit 메시지로 만들어 채널에 게시한다.

SLACK_TOKEN 환경변수가 없으면 'dry-run'으로 동작해 메시지를 콘솔에만 출력한다.
(엔드포인트 채우기 전에 포맷을 미리 확인할 때 유용)
"""
import json
import os
import urllib.request
from collections import defaultdict
from datetime import date
from typing import List

from models import Review

SLACK_TOKEN = os.environ.get("SLACK_TOKEN", "")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#03_매장리뷰_현황")
PLATFORM_LABEL = {"naver": "네이버", "catchtable": "캐치테이블"}
MAX_BLOCKS_PER_MSG = 48  # Slack 한 메시지당 50블록 제한 → 여유롭게 자름


def _stars(rating):
    if rating is None:
        return "별점 없음"
    full = int(round(rating))
    return "★" * full + "☆" * (5 - full) + f" ({rating:.1f})"


def build_blocks(reviews: List[Review], store_name: str) -> list:
    today = date.today().strftime("%Y-%m-%d")
    blocks = [{
        "type": "header",
        "text": {"type": "plain_text", "text": f"📋 {store_name} 리뷰 다이제스트 ({today})"},
    }]

    if not reviews:
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": "어제 올라온 새 리뷰가 없습니다 🙂"}})
        return blocks

    by_platform = defaultdict(list)
    for r in reviews:
        by_platform[r.platform].append(r)

    counts = ", ".join(f"{PLATFORM_LABEL.get(p, p)} {len(v)}건"
                       for p, v in by_platform.items())
    rated = [r.rating for r in reviews if r.rating is not None]
    avg = f"  ·  평균 ★{sum(rated) / len(rated):.1f}" if rated else ""
    blocks.append({"type": "section",
                   "text": {"type": "mrkdwn", "text": f"*총 {len(reviews)}건*  —  {counts}{avg}"}})
    blocks.append({"type": "divider"})

    for platform, items in by_platform.items():
        items.sort(key=lambda r: r.created_at)
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn",
                                "text": f"*— {PLATFORM_LABEL.get(platform, platform)} ({len(items)}건) —*"}})
        for r in items:
            text = " ".join(r.text.split())
            if len(text) > 280:
                text = text[:280] + "…"
            line = (f"{_stars(r.rating)}   _{r.author}_   ·   "
                    f"{r.created_at.strftime('%m/%d %H:%M')}\n{text}")
            section = {"type": "section", "text": {"type": "mrkdwn", "text": line}}
            if r.url:
                section["accessory"] = {"type": "button",
                                        "text": {"type": "plain_text", "text": "원문"},
                                        "url": r.url}
            blocks.append(section)
        blocks.append({"type": "divider"})

    return blocks


def _chunk(blocks, size):
    for i in range(0, len(blocks), size):
        yield blocks[i:i + size]


def _send(blocks) -> str:
    if not SLACK_TOKEN:
        print("[dry-run] SLACK_TOKEN 미설정 — 메시지를 게시하지 않고 출력합니다:")
        print(json.dumps({"blocks": blocks}, ensure_ascii=False, indent=2))
        return "dry-run"
    payload = json.dumps({"channel": SLACK_CHANNEL, "blocks": blocks}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SLACK_TOKEN}",
        },
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok"):
            raise RuntimeError(f"Slack API 오류: {data.get('error')}")
        return data["ts"]


def post(reviews: List[Review], store_name: str) -> str:
    blocks = build_blocks(reviews, store_name)
    statuses = [_send(chunk) for chunk in _chunk(blocks, MAX_BLOCKS_PER_MSG)]
    return ",".join(statuses)

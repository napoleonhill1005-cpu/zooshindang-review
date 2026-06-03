"""수집한 리뷰를 Slack 메시지로 만들어 채널에 게시한다.

메시지 양식:
  5/28(목) 리뷰현황
  네이버 14건
  캐치테이블 5점 3건

  [네이버]
  작성자 · 리뷰 텍스트
  ...

  [캐치테이블]
  ★5 · 작성자 · 리뷰 텍스트
  ...

SLACK_TOKEN 환경변수가 없으면 dry-run으로 콘솔에만 출력한다.
"""
import json
import os
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from typing import List

from models import Review

SLACK_TOKEN = os.environ.get("SLACK_TOKEN", "")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#03_매장리뷰_현황")
MAX_BLOCKS_PER_MSG = 48

_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _fmt_date(d: date) -> str:
    return f"{d.month}/{d.day}({_WEEKDAYS[d.weekday()]})"


def build_blocks(reviews: List[Review], store_name: str, target_date: date) -> list:
    naver = [r for r in reviews if r.platform == "naver"]
    ct = [r for r in reviews if r.platform == "catchtable"]

    # 요약 헤더
    summary = f"*{_fmt_date(target_date)} 리뷰현황*"
    if naver:
        summary += f"\n네이버 {len(naver)}건"
    if ct:
        rating_counts = Counter(
            int(r.rating) if r.rating is not None else 0 for r in ct
        )
        ct_str = ", ".join(
            f"{star}점 {cnt}건"
            for star, cnt in sorted(rating_counts.items(), reverse=True)
        )
        summary += f"\n캐치테이블 {ct_str}"

    blocks: list = [{"type": "section", "text": {"type": "mrkdwn", "text": summary}}]

    if not reviews:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_새 리뷰가 없습니다_"},
        })
        return blocks

    # 네이버 리뷰 목록
    if naver:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*[ 네이버 ]*"},
        })
        for r in naver:
            text = " ".join(r.text.split())
            if len(text) > 300:
                text = text[:300] + "…"
            body = f"_{r.author}_\n{text}" if text else f"_{r.author}_ (내용 없음)"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
            if r.photo_url:
                blocks.append({"type": "image", "image_url": r.photo_url, "alt_text": f"{r.author} 사진"})

    # 캐치테이블 리뷰 목록
    if ct:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*[ 캐치테이블 ]*"},
        })
        for r in ct:
            text = " ".join(r.text.split())
            if len(text) > 300:
                text = text[:300] + "…"
            star = f"★{int(r.rating)}" if r.rating is not None else ""
            prefix = f"{star} _{r.author}_" if star else f"_{r.author}_"
            body = f"{prefix}\n{text}" if text else f"{prefix} (내용 없음)"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
            if r.photo_url:
                blocks.append({"type": "image", "image_url": r.photo_url, "alt_text": f"{r.author} 사진"})

    return blocks


def _chunk(blocks, size):
    for i in range(0, len(blocks), size):
        yield blocks[i:i + size]


def _send(blocks, text: str = "") -> str:
    if not SLACK_TOKEN:
        print("[dry-run] SLACK_TOKEN 미설정 — 콘솔 출력:")
        print(json.dumps({"blocks": blocks}, ensure_ascii=False, indent=2))
        return "dry-run"
    payload = json.dumps({"channel": SLACK_CHANNEL, "blocks": blocks, "text": text}).encode("utf-8")
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


def post(reviews: List[Review], store_name: str, target_date: date) -> str:
    blocks = build_blocks(reviews, store_name, target_date)
    text = f"{_fmt_date(target_date)} 리뷰현황"
    statuses = [_send(chunk, text) for chunk in _chunk(blocks, MAX_BLOCKS_PER_MSG)]
    return ",".join(statuses)

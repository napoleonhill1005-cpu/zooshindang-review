"""주신당 근무 스케줄 알림 (주신당지킴이).

구글 시트(주차별 근무표)를 실시간으로 읽어 슬랙에 게시한다.
슬랙 채널에서 직원이 "근무"/"스케줄" 등을 입력하면 GAS(Google Apps Script)가
schedule.yml 워크플로우를 workflow_dispatch로 호출 → 이 스크립트가 게시.
(기존 "현황" → status.py 구조와 동일한 패턴)

핵심 설계
- 시트가 "진실의 원천": 근무자를 코드에 하드코딩하지 않고 매번 시트를 실시간으로 읽는다.
  → 매주 시트만 갱신하면 자동 반영.
- 시트는 반드시 "링크가 있는 모든 사용자 - 뷰어"로 공유돼 있어야 CSV로 읽힌다.
  (GitHub Actions 러너에는 구글 로그인 쿠키가 없으므로 공개 공유 필수)
- 개발 샌드박스는 docs.google.com 접근이 막혀 있을 수 있으나, 운영(GitHub Actions)
  러너는 접근 가능하므로 실시간 fetch가 동작한다. 로컬 검증은 SCHEDULE_CSV_FILE 사용.

환경변수
  SCHEDULE_SHEET_ID         구글 시트 ID (기본값: 운영 시트)
  SCHEDULE_GID              시트 탭 gid (기본 0)
  SCHEDULE_CSV_FILE         (테스트용) 지정 시 네트워크 대신 로컬 CSV 파일 사용
  SCHEDULE_QUERY            직원이 입력한 텍스트 (이름/요일/키워드). argv[1]로도 전달 가능
  SCHEDULE_TODAY            (테스트용) "YYYY-MM-DD"로 오늘 날짜 강제
  SLACK_TOKEN               슬랙 봇 토큰 (없으면 콘솔 출력 dry-run)
  SCHEDULE_SLACK_CHANNEL    게시 채널 (없으면 SLACK_CHANNEL → 기본 #03_매장리뷰_현황)
  SLACK_DRY_RUN             "1"이면 슬랙 미게시, 콘솔만 출력

사용 (로컬)
  SCHEDULE_CSV_FILE=tests/schedule_fixture.csv SLACK_DRY_RUN=1 python schedule_board.py
  ... python schedule_board.py 오시환     # 특정 직원 주간 근무
  ... python schedule_board.py 금          # 특정 요일 근무표
"""
import csv
import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone, date

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_KST = timezone(timedelta(hours=9))
DAY_KO = ["월", "화", "수", "목", "금", "토", "일"]

DEFAULT_SHEET_ID = "1RNROeRkQvksAo_BhBvi3s9UGMrSsOWB4-U3S5apfZkU"

# 요일(월=0 … 일=6) → 시트 열 인덱스 (0=섹션, 1=역할라벨, 2~8=월~일)
_DAY_COL = {wd: wd + 2 for wd in range(7)}

# 디너 마지막 근무가 새벽까지 이어지므로, 새벽 5시 이전 요청은 '전날 영업일'로 본다.
_RESET_HOUR = 5

# 역할 행: 시트 2번째 열(라벨) → (구분, 표시명). 라벨로 행을 식별한다.
_ROLE_LABELS = {
    "주방메인": ("런치", "주방메인"),
    "프리배치, 주방서폿": ("런치", "주방 서폿"),
    "홀오픈": ("런치", "홀 오픈"),
    "주방": ("디너", "주방"),
    "홀서버": ("디너", "홀 서버"),
    "바텐더": ("디너", "바텐더"),
}

_ENTRY_RE = re.compile(r"([가-힣]{2,4})\s*\(([^)]+)\)")
_WEEK_RE = re.compile(r"(\d{2,4})\s*년\s*(\d+)\s*월\s*(\d+)\s*일")


# ──────────────────────────── 시트 로드 ────────────────────────────
def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (jusindang-schedule-bot)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8")


def load_rows():
    """시트를 행 리스트로 반환. SCHEDULE_CSV_FILE 우선, 없으면 시트 CSV를 fetch."""
    path = os.environ.get("SCHEDULE_CSV_FILE")
    if path:
        text = open(path, encoding="utf-8").read()
    else:
        sheet_id = os.environ.get("SCHEDULE_SHEET_ID", DEFAULT_SHEET_ID)
        gid = os.environ.get("SCHEDULE_GID", "0")
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
        text = _http_get(url)
    return list(csv.reader(io.StringIO(text)))


# ──────────────────────────── 파싱 ────────────────────────────
def _cell(row, idx):
    return row[idx].strip() if idx < len(row) else ""


def _parse_entries(cell: str):
    """'이름(시간), 이름(시간)' → [(이름, 시간), ...]"""
    return [(m.group(1), m.group(2).strip()) for m in _ENTRY_RE.finditer(cell)]


def _clean_biz_hours(text: str) -> str:
    """'금_ 02:30 영업시간 / ...' → '02:30 영업시간 / ...'"""
    return re.sub(r"^[월화수목금토일]\s*_?\s*", "", text).strip()


def parse_schedule(rows) -> dict:
    """시트 행 → 구조화된 스케줄 딕셔너리."""
    sched = {
        "week_range": "",
        "week_start": None,
        "biz_hours": {},     # wd -> str
        "roles": [],         # [{"section","label","days": {wd: [(name,time)]}}]
        "duty": {},          # wd -> str
        "last_order": {},    # wd -> str
    }

    for row in rows:
        c0, c1 = _cell(row, 0), _cell(row, 1)
        joined = " ".join(_cell(row, i) for i in range(len(row)))

        # 주차 범위 (최상단)
        if not sched["week_range"] and "년" in c0 and "~" in c0:
            sched["week_range"] = c0
            m = _WEEK_RE.search(c0)
            if m:
                y = int(m.group(1))
                y = 2000 + y if y < 100 else y
                sched["week_start"] = date(y, int(m.group(2)), int(m.group(3)))
            continue

        # 영업시간 헤더
        if "영업시간" in joined and not sched["biz_hours"]:
            for wd, col in _DAY_COL.items():
                sched["biz_hours"][wd] = _clean_biz_hours(_cell(row, col))
            continue

        # 역할 행
        if c1 in _ROLE_LABELS:
            section, label = _ROLE_LABELS[c1]
            days = {wd: _parse_entries(_cell(row, col)) for wd, col in _DAY_COL.items()}
            sched["roles"].append({"section": section, "label": label, "days": days})
            continue

        # 담당자 행 (오픈/마감)
        if "오픈" in joined and "마감" in joined:
            for wd, col in _DAY_COL.items():
                sched["duty"][wd] = _cell(row, col)
            continue

        # 라스트오더 행
        if "라스트 오더" in joined or "라스트오더" in joined:
            for wd, col in _DAY_COL.items():
                sched["last_order"][wd] = _cell(row, col)
            continue

    return sched


def all_names(sched) -> set:
    names = set()
    for role in sched["roles"]:
        for entries in role["days"].values():
            for name, _ in entries:
                names.add(name)
    return names


# ──────────────────────────── 포맷 ────────────────────────────
def _date_for_wd(sched, wd) -> date | None:
    if sched["week_start"] is None:
        return None
    return sched["week_start"] + timedelta(days=wd)


def _date_label(sched, wd) -> str:
    d = _date_for_wd(sched, wd)
    if d:
        return f"{d.month}/{d.day}({DAY_KO[wd]})"
    return f"{DAY_KO[wd]}요일"


def format_day(sched, wd) -> str:
    lines = [f"🗓️ *{_date_label(sched, wd)} 근무표*"]
    biz = sched["biz_hours"].get(wd, "")
    if biz:
        lines.append(f"_{biz}_")
    if sched["week_range"]:
        lines.append(f"주간: {sched['week_range']}")
    lines.append("")

    def block(section, emoji):
        out = []
        for role in sched["roles"]:
            if role["section"] != section:
                continue
            entries = role["days"].get(wd, [])
            if not entries:
                continue
            people = ", ".join(f"{n}({t})" for n, t in entries)
            out.append(f"• {role['label']}: {people}")
        if out:
            return [f"{emoji} *{section}*", *out, ""]
        return []

    lines += block("런치", "☀️")
    lines += block("디너", "🌙")

    duty = sched["duty"].get(wd, "")
    if duty:
        lines.append(f"📌 {duty}")
    lo = sched["last_order"].get(wd, "")
    if lo:
        lines.append(f"⏰ {lo}")

    return "\n".join(lines).rstrip()


def format_person(sched, name) -> str:
    head = f"👤 *{name}님 근무*"
    if sched["week_range"]:
        head += f"  ({sched['week_range']})"
    lines = [head, ""]
    found = False
    for wd in range(7):
        day_lines = []
        for role in sched["roles"]:
            for n, t in role["days"].get(wd, []):
                if n == name:
                    day_lines.append(f"  • {role['section']} {role['label']} {t}")
                    found = True
        if day_lines:
            lines.append(f"*{_date_label(sched, wd)}*")
            lines += day_lines
    if not found:
        return f"👤 *{name}* — 이번 주 근무가 없습니다."
    return "\n".join(lines)


# ──────────────────────────── 슬랙 ────────────────────────────
def post_slack(text: str):
    token = os.environ.get("SLACK_TOKEN", "")
    channel = os.environ.get("SCHEDULE_SLACK_CHANNEL") or os.environ.get("SLACK_CHANNEL", "#03_매장리뷰_현황")
    if not token or os.environ.get("SLACK_DRY_RUN", "0") == "1":
        print(f"[dry-run] channel={channel}\n{text}")
        return
    payload = json.dumps({"channel": channel, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok"):
            print(f"[slack 게시 실패] {data.get('error')}")


# ──────────────────────────── 진입점 ────────────────────────────
def _now_kst() -> datetime:
    override = os.environ.get("SCHEDULE_TODAY")
    if override:
        return datetime.fromisoformat(override).replace(tzinfo=_KST)
    return datetime.now(_KST)


def _biz_weekday(now: datetime) -> int:
    d = now.date()
    if now.hour < _RESET_HOUR:  # 새벽(영업 연장) → 전날 영업일
        d = d - timedelta(days=1)
    return d.weekday()


def resolve(sched, query: str, now: datetime) -> str:
    """직원 입력(query)을 해석해 게시할 텍스트 생성."""
    q = (query or "").strip()
    # 1) 이름 매칭 (정확히 일치하는 직원)
    if q and q in all_names(sched):
        return format_person(sched, q)
    # 2) 요일 ("월"~"일", "월요일" 등)
    if q:
        head = q[0]
        if head in DAY_KO:
            return format_day(sched, DAY_KO.index(head))
    # 3) 기본: 오늘(영업일 기준) 근무표
    return format_day(sched, _biz_weekday(now))


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SCHEDULE_QUERY", "")
    rows = load_rows()
    sched = parse_schedule(rows)

    if not sched["roles"]:
        post_slack(
            "🚨 *근무표를 읽지 못했습니다.*\n"
            "구글 시트 공유 설정('링크가 있는 모든 사용자 - 뷰어')과 형식을 확인해주세요."
        )
        print("[schedule] 파싱 실패 — roles 0건")
        return

    text = resolve(sched, query, _now_kst())
    post_slack(text)
    print(f"[schedule] 게시 완료 (query={query!r})")


if __name__ == "__main__":
    main()

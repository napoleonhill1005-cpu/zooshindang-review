"""리뷰봇 워치독 — 오늘 collect/post 워크플로우가 실제로 돌았는지 독립 점검 후 슬랙 DM 보고.

목적: GAS(08:45 KST) dispatch가 죽은 GitHub PAT 등으로 실패하면 collect/post가
      *아예 트리거조차 안 되는 조용한 실패*가 발생한다. 이때는 봇 자체 장애 알림
      (수집 0건 / post pending 없음 / 워크플로우 failure)도 울리지 않는다.
      워치독은 GitHub Actions cron으로 독립 실행되며, GITHUB_TOKEN(Actions 자동 주입)으로
      자기 레포의 Actions run 이력을 직접 조회해 이 사각지대를 잡는다.

보고: 매일 석지현 슬랙 DM (정상이면 ✅ 하트비트, 이상이면 🚨 경고).
      DM 전송 실패 시 리뷰 채널로 폴백한다.

사용법: python watchdog.py   (GitHub Actions watchdog.yml에서 실행)
환경변수:
  GITHUB_TOKEN            Actions 자동 주입 (repo Actions 읽기)
  GITHUB_REPOSITORY       Actions 자동 주입 (owner/repo)
  SLACK_TOKEN             슬랙 봇 토큰 (chat:write / im:write)
  WATCHDOG_SLACK_TARGET   보고 대상 (기본: 석지현 U0B67DXNP8C)
  SLACK_CHANNEL           DM 실패 시 폴백 채널 (기본: #03_매장리뷰_현황)
"""
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))

REPO = os.environ.get("GITHUB_REPOSITORY", "napoleonhill1005-cpu/zooshindang-review")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")
SLACK_TOKEN = os.environ.get("SLACK_TOKEN", "")
DM_TARGET = os.environ.get("WATCHDOG_SLACK_TARGET", "U0B67DXNP8C")  # 석지현
FALLBACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#03_매장리뷰_현황")

# 점검 대상: (워크플로우 파일, 표시 이름)
_WORKFLOWS = [("collect.yml", "수집(collect)"), ("post.yml", "게시(post)")]


def _gh_api(path: str):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "review-watchdog",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _runs_today(workflow_file: str):
    """해당 워크플로우의 오늘(KST) run 목록 (최신순)."""
    data = _gh_api(f"/repos/{REPO}/actions/workflows/{workflow_file}/runs?per_page=20")
    today = datetime.now(_KST).date()
    out = []
    for run in data.get("workflow_runs", []):
        created = datetime.fromisoformat(
            run["created_at"].replace("Z", "+00:00")
        ).astimezone(_KST)
        if created.date() == today:
            out.append(run)
    return out


def _fmt_time(run) -> str:
    created = datetime.fromisoformat(
        run["created_at"].replace("Z", "+00:00")
    ).astimezone(_KST)
    return created.strftime("%H:%M")


def _summarize(workflow_file: str, label: str):
    """(state, 한 줄 요약) 반환. state ∈ {ok, fail, pending, missing}."""
    runs = _runs_today(workflow_file)
    if not runs:
        return "missing", f"• {label}: ⛔ 오늘 실행 기록 없음 (트리거 안 됨)"
    latest = runs[0]
    if latest.get("status") != "completed":
        return "pending", f"• {label}: ⏳ 실행 중({latest.get('status')})"
    conclusion = latest.get("conclusion")
    if conclusion == "success":
        return "ok", f"• {label}: ✅ 성공 ({_fmt_time(latest)})"
    return "fail", (
        f"• {label}: ❌ {conclusion} ({_fmt_time(latest)})\n"
        f"  └ {latest.get('html_url', '')}"
    )


def _slack_post(channel: str, text: str):
    payload = json.dumps({"channel": channel, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SLACK_TOKEN}",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _report(text: str):
    """석지현 DM 우선, 실패 시 리뷰 채널 폴백."""
    print(text)
    if not SLACK_TOKEN:
        print("[watchdog] SLACK_TOKEN 없음 — 콘솔 출력만")
        return
    try:
        res = _slack_post(DM_TARGET, text)
    except Exception as e:
        print(f"[watchdog] DM 예외: {e}")
        res = {"ok": False, "error": str(e)}
    if res.get("ok"):
        print("[watchdog] 석지현 DM 전송 완료")
        return
    print(f"[watchdog] DM 실패({res.get('error')}) → 리뷰 채널 폴백")
    try:
        res2 = _slack_post(FALLBACK_CHANNEL, text)
        print(f"[watchdog] 채널 전송: {res2.get('ok') or res2.get('error')}")
    except Exception as e:
        print(f"[watchdog] 채널 폴백도 실패: {e}")


def main():
    today = datetime.now(_KST).strftime("%Y-%m-%d")

    if not GH_TOKEN:
        _report(
            f"🚨 *리뷰봇 워치독 자체 오류* ({today})\n"
            "GITHUB_TOKEN이 없어 Actions 상태를 조회하지 못했습니다."
        )
        return

    try:
        results = [(_summarize(wf, label)) for wf, label in _WORKFLOWS]
    except Exception as e:
        _report(
            f"🚨 *리뷰봇 워치독 자체 오류* ({today})\n"
            f"GitHub Actions 조회 중 예외: {e}"
        )
        return

    states = [s for s, _ in results]
    lines = [line for _, line in results]
    body = "\n".join(lines)

    if all(s == "ok" for s in states):
        _report(f"✅ *리뷰봇 정상* ({today})\n{body}")
    elif any(s in ("missing", "fail") for s in states):
        _report(
            f"🚨 *리뷰봇 이상 감지* ({today})\n{body}\n\n"
            "가능성: GAS(08:45) 트리거용 GitHub PAT 만료 시 collect가 아예 안 돕니다. "
            "Actions 로그와 토큰(GITHUB_PAT / CATCHTABLE_TOKEN)을 확인하세요."
        )
    else:
        # pending만 남은 경우 (아직 실행 중) — 참고용 통보
        _report(
            f"⏳ *리뷰봇 점검 — 아직 실행 중* ({today})\n{body}\n"
            "잠시 후 완료 예상. 계속 이 상태면 확인 필요."
        )


if __name__ == "__main__":
    main()

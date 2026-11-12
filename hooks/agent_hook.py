#!/usr/bin/env python3
"""에이전트 상태 훅: Claude Code·Codex 가 어디서 돌든(VS Code, Cursor, iTerm, Ghostty, 터미널, Herdr…)
세션 상태를 ~/.cache/d200/agents/<id>.json 으로 남긴다. 대시보드가 이 파일들을 읽는다.

표준 라이브러리만 쓴다 (시스템 python3 로 실행).

Claude Code (~/.claude/settings.json 의 hooks, stdin 으로 JSON 이 들어온다)
  python3 agent_hook.py claude
    SessionStart                 → idle
    UserPromptSubmit / Pre·PostToolUse → working
    PermissionRequest            → blocked (결정 필요)
    Notification(권한 관련)       → blocked
    Stop                         → done (완료, 아직 안 봄)
    StopFailure                  → error
    SessionEnd                   → 완료·오류 알림을 제외하고 파일 삭제

Codex (~/.codex/config.toml 의 notify, 마지막 인자로 JSON 이 들어온다)
  notify = ["python3", "/path/agent_hook.py", "codex", "--", <기존 notify 명령...>]
    agent-turn-complete          → done
  `--` 뒤에 기존 notify 명령이 있으면 같은 인자로 이어서 실행한다 (기존 연동 유지).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

DIR = os.path.expanduser("~/.cache/d200/agents")

CLAUDE_STATUS = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "PostToolUseFailure": "working",
    "PermissionRequest": "blocked",
    "Stop": "done",
    "StopFailure": "error",
}


def _ps(pid: int, field: str) -> str:
    try:
        return subprocess.run(["ps", "-o", f"{field}=", "-p", str(pid)], capture_output=True, text=True,
                              timeout=2).stdout.strip()
    except Exception:
        return ""


def _project(cwd: str) -> str:
    """git 저장소 최상위 폴더 이름 (없으면 현재 폴더 이름)."""
    try:
        top = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=2).stdout.strip()
        if top:
            # 워크트리면 원래 저장소 이름을 쓴다
            common = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                    capture_output=True, text=True, timeout=2).stdout.strip()
            if common.endswith("/.git"):
                return os.path.basename(os.path.dirname(common))
            return os.path.basename(top)
    except Exception:
        pass
    return os.path.basename(cwd.rstrip("/")) or cwd


def _write(rec: dict) -> None:
    os.makedirs(DIR, exist_ok=True)
    path = os.path.join(DIR, rec["id"].replace("/", "_") + ".json")
    old = {}
    try:
        old = json.load(open(path))
    except Exception:
        pass
    rec = {**old, **rec, "started": old.get("started", rec["updated"])}
    tmp = path + f".{os.getpid()}"
    with open(tmp, "w") as fp:
        json.dump(rec, fp)
    os.replace(tmp, path)


def _base(agent: str, session: str, cwd: str) -> dict:
    ppid = os.getppid()  # 훅을 띄운 에이전트 프로세스
    if os.name == 'nt':
        try:
            import psutil
            executable = 'claude.exe' if agent == 'claude-code' else 'codex.exe'
            # Windows inserts a short-lived shell between the hook and agent.
            for parent in psutil.Process().parents():
                if parent.name().lower() == executable:
                    ppid = parent.pid
                    break
        except Exception:
            pass
    args = _ps(ppid, "args")
    return {
        "id": f"{agent}-{session}",
        "agent": agent,
        "session": session,
        "cwd": cwd,
        "project": _project(cwd),
        "host": socket.gethostname().split(".")[0],
        "pid": ppid,
        "tty": _ps(ppid, "tty"),
        "term_program": os.environ.get("TERM_PROGRAM", ""),
        "bundle": os.environ.get("__CFBundleIdentifier", ""),  # 실행 앱 (VS Code, Cursor, iTerm…)
        # 다른 프로그램이 띄운 비대화형 실행(-p/--print, exec)은 하위 작업으로 본다
        "top": not any(f in f" {args} " for f in (" -p ", " --print ", " exec ")),
        "updated": time.time(),
    }


def claude() -> None:
    try:
        d = json.load(sys.stdin)
    except Exception:
        return
    ev = d.get("hook_event_name", "")
    session = d.get("session_id") or "unknown"
    if ev == "SessionEnd":
        path = os.path.join(DIR, f"claude-code-{session}.json")
        try:
            with open(path, encoding='utf-8') as fp:
                if json.load(fp).get('status') in ('done', 'error'):
                    return
            os.remove(path)
        except FileNotFoundError:
            pass
        return
    status = CLAUDE_STATUS.get(ev)
    if ev == "Notification" and "permission" in (d.get("message") or "").lower():
        status = "blocked"
    if not status:
        return
    rec = _base("claude-code", session, d.get("cwd") or os.getcwd())
    rec.update(status=status, event=ev)
    _write(rec)


def codex(argv: list[str]) -> None:
    # 기존 notify 명령: "--" 뒤 ~ 마지막 인자(JSON) 앞
    forward: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        forward, argv = argv[i + 1:], argv[:i]
    payload = forward[-1] if forward else (argv[-1] if argv else "")
    try:
        d = json.loads(payload)
    except Exception:
        d = {}
    if d.get("type") == "agent-turn-complete":
        session = d.get("thread-id") or d.get("turn-id") or "unknown"
        rec = _base("codex", session, d.get("cwd") or os.getcwd())
        rec.update(status="done", event="agent-turn-complete")
        _write(rec)
    if forward[:-1]:  # 기존 연동(예: Computer Use) 그대로 실행
        try:
            subprocess.Popen(forward, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding='utf-8')
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "claude":
            claude()
        elif len(sys.argv) > 1 and sys.argv[1] == "codex":
            codex(sys.argv[2:])
    except Exception:
        pass  # 훅 실패가 에이전트를 막으면 안 된다
    sys.exit(0)

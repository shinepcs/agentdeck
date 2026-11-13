"""agy(Antigravity CLI)의 읽기 전용 한도를 로컬 또는 SSH로 가져온다.

원격에는 아무것도 설치하지 않는다: 아래 REMOTE 스크립트를 ssh stdin 으로 넘겨 공식 읽기 전용 명령
`agy -p /usage --output-format json` 을 실행한다. 토큰 파일이나 비공개 API 는 쓰지 않는다.
요구 사항은 docs/ANTIGRAVITY.md 참고.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

from config import AGY_HOST
from i18n import t

HOST = AGY_HOST  # SSH 대상 또는 "local" (config.json agy.host), 없으면 비활성
AGY_PATH = 'PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"'
LOGIN_EXIT = 3  # REMOTE 가 "로그인 필요"를 알리는 종료 코드
login_needed = False  # 마지막 조회가 로그인 문제로 실패했는지 (agy 는 SSH 접속용 로그인을 따로 보관한다)


def local_cli() -> str:
    return shutil.which("agy") or str(Path.home() / ".gemini" / "bin" / ("agy.exe" if os.name == "nt" else "agy"))

# /usage 를 지원하는 버전(1.1.11+)인지 먼저 확인한다: 옛 CLI 는 슬래시 명령을 프롬프트로 처리해 한도를 쓸 수 있다.
REMOTE = r'''
import os, re, selectors, subprocess, sys, time

env = dict(os.environ, PATH=os.path.expanduser("~/.local/bin") + ":/opt/homebrew/bin:" + os.environ.get("PATH", ""))
try:
    version = subprocess.run(["agy", "--version"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=10, env=env, check=True)
    # "1.5.3", "v1.5.3", "agy version 1.5.3" 모두 허용. "-preview" 같은 시험판은 제외
    match = re.search(r"(?<![\d.])v?(\d+)\.(\d+)\.(\d+)(?![-\w.])", version.stdout)
    if not match or tuple(map(int, match.groups())) < (1, 1, 11):
        sys.exit(1)
    # 로그인이 풀려 있으면 agy 가 로그인 주소를 찍고 기다린다: 그 안내가 보이면 바로 끝내고 3 으로 알린다
    proc = subprocess.Popen(["agy", "-p", "/usage", "--output-format", "json"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    sel, bufs, deadline = selectors.DefaultSelector(), {proc.stdout: b"", proc.stderr: b""}, time.time() + 60
    for f in bufs:
        sel.register(f, selectors.EVENT_READ)
    while sel.get_map() and time.time() < deadline:
        for key, _ in sel.select(1):
            chunk = os.read(key.fileobj.fileno(), 65536)
            if chunk:
                bufs[key.fileobj] += chunk
            else:
                sel.unregister(key.fileobj)
        if b"authentication required" in (bufs[proc.stdout] + bufs[proc.stderr]).lower():
            proc.kill()
            sys.exit(3)
    if sel.get_map():  # 시간 초과
        proc.kill()
        sys.exit(1)
    if proc.wait(timeout=5) != 0:
        sys.exit(1)
    sys.stdout.buffer.write(bufs[proc.stdout])
except (OSError, subprocess.SubprocessError, UnicodeError):
    sys.exit(1)
'''


@dataclass
class Bucket:
    group: str
    window: str  # "5h" | "weekly"
    remaining: float  # 0~1
    reset: datetime | None


def _bucket(name: str, bucket: object) -> Bucket | None:
    """버킷 하나 해석. 쓸 수 없으면 None (호출 측에서 건너뜀)."""
    if not isinstance(bucket, dict) or bucket.get("disabled") is True or bucket.get("enabled") is False:
        return None
    remaining = bucket.get("remaining_fraction")
    if (isinstance(remaining, bool) or not isinstance(remaining, (int, float))
            or not math.isfinite(remaining) or not 0 <= remaining <= 1):
        return None
    window = bucket.get("window")
    if window not in ("5h", "weekly"):  # 대시보드가 그리는 창만
        return None
    reset = bucket.get("reset_time")
    if reset is not None:
        if not isinstance(reset, str):
            return None
        try:
            reset = datetime.fromisoformat(reset.replace("Z", "+00:00"))
        except (ValueError, OverflowError):
            return None
        if reset.tzinfo is None:
            return None
        reset = reset.astimezone(timezone.utc)
    return Bucket(name, window, float(remaining), reset)


def parse_quota(payload: object) -> list[Bucket] | None:
    """CLI 응답에서 한도만 뽑는다.

    - 응답 전체 형식(status SUCCESS, command.data.groups)이 다르면 None.
    - 그룹·버킷 하나가 이상하거나 모르는 시간 창이면 그것만 건너뛴다 (나머지 한도는 계속 표시).
    - 값이 없거나 꺼진 버킷은 0 으로 만들지 않고 건너뛴다. 토큰 사용량 `usage` 는 한도가 아니다.
    """
    if (not isinstance(payload, dict) or payload.get("status") != "SUCCESS"
            or "error" in payload):
        return None
    command = payload.get("command")
    if not isinstance(command, dict):
        return None
    data = command.get("data")
    if not isinstance(data, dict):
        return None
    groups = data.get("groups")
    if not isinstance(groups, list):
        return None
    out = []
    for group in groups:
        if not isinstance(group, dict) or group.get("disabled") is True or group.get("enabled") is False:
            continue
        name, buckets = group.get("name"), group.get("buckets")
        if not isinstance(name, str) or not name.strip() or not isinstance(buckets, list):
            continue
        for bucket in buckets:
            b = _bucket(name, bucket)
            if b:
                out.append(b)
    return out or None


def agy_quota() -> list[Bucket] | None:
    global login_needed
    if not HOST:
        return None
    login_needed = False
    try:
        if HOST == "local":
            options = dict(stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", timeout=15,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            version = subprocess.run([local_cli(), "--version"], check=True, **options)
            match = re.search(r"(?<![\d.])v?(\d+)\.(\d+)\.(\d+)(?![-\w.])", version.stdout)
            if not match or tuple(map(int, match.groups())) < (1, 1, 11):
                return None
            result = subprocess.run([local_cli(), "-p", "/usage", "--output-format", "json"], **options)
            login_needed = "authentication required" in ((result.stdout or "") + (result.stderr or "")).lower()
            result.check_returncode()
            return parse_quota(json.loads(result.stdout))
        result = subprocess.run(
            ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
             HOST, "python3", "-"],
            input=REMOTE, capture_output=True, text=True, timeout=90,
            check=True,
        )
        login_needed = False
        return parse_quota(json.loads(result.stdout))
    except subprocess.CalledProcessError as e:
        login_needed = login_needed or e.returncode == LOGIN_EXIT
        return None
    except subprocess.TimeoutExpired as e:
        output = e.output or b""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        error = e.stderr or b""
        if isinstance(error, bytes):
            error = error.decode("utf-8", errors="replace")
        login_needed = "authentication required" in (output + error).lower()
        return None
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeError):
        return None


def login_command() -> str:
    """터미널에 넣을 명령: 안내 한 줄을 찍고 원격 agy 를 대화형으로 연다."""
    hint = t("agy 가 로그인 주소를 보여주면 브라우저로 로그인하고, 끝나면 agy 를 종료하세요. 덱은 곧 다시 읽어요.",
             "When agy shows a login URL, sign in with your browser, then quit agy. The deck will retry shortly.")
    command = shlex.quote(local_cli()) if HOST == "local" else f"ssh -t {shlex.quote(HOST)} {shlex.quote(AGY_PATH + ' agy')}"
    return f"echo {shlex.quote(hint)}; {command}"


def open_login() -> bool:
    """맥의 터미널 앱을 열어 사용자가 직접 로그인하게 한다. 비밀번호나 토큰은 이 프로그램이 다루지 않는다."""
    if not HOST:
        return False
    if HOST == "local" and os.name == "nt":
        try:
            subprocess.Popen([local_cli()], creationflags=subprocess.CREATE_NEW_CONSOLE)
            return True
        except OSError:
            return False
    cmd = login_command().replace("\\", "\\\\").replace('"', '\\"')
    try:
        r = subprocess.run(["osascript", "-e", 'tell application "Terminal" to activate',
                            "-e", f'tell application "Terminal" to do script "{cmd}"'],
                           capture_output=True, timeout=15)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


if __name__ == "__main__":
    for b in agy_quota() or []:
        print(b)

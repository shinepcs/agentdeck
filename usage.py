"""로컬 로그에서 LLM 사용량을 집계한다.

- Claude Code: ~/.claude/projects/**/*.jsonl 의 assistant 메시지 usage
- Codex:       ~/.codex/sessions/**/*.jsonl 의 token_count 이벤트 (rate_limits 포함)
- Claude 한도: statusline 래퍼가 저장한 스냅샷(~/.cache/d200/claude_status.json)이 있으면 사용
"""

from __future__ import annotations

import glob
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
CLAUDE_GLOB = f"{HOME}/.claude/projects/**/*.jsonl"
CODEX_GLOB = f"{HOME}/.codex/sessions/**/*.jsonl"
CLAUDE_STATUS = f"{HOME}/.cache/d200/claude_status.json"
BLOCK = timedelta(hours=5)
LOOKBACK_DAYS = 8


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass
class Window:
    used_percent: float | None = None
    resets_at: datetime | None = None


@dataclass
class ClaudeUsage:
    today_tokens: int = 0  # input + cache_creation + output (cache_read 제외)
    today_output: int = 0
    today_cache_read: int = 0
    today_messages: int = 0
    today_sessions: int = 0
    week_tokens: int = 0
    block_tokens: int = 0  # 현재 5시간 블록
    block_end: datetime | None = None
    by_model: dict[str, int] = field(default_factory=dict)
    five_hour: Window = field(default_factory=Window)  # statusline 스냅샷 있을 때만
    seven_day: Window = field(default_factory=Window)


@dataclass
class CodexUsage:
    today_tokens: int = 0
    week_tokens: int = 0
    primary: Window = field(default_factory=Window)
    secondary: Window = field(default_factory=Window)
    primary_window_min: int | None = None
    credits: str | None = None
    updated: datetime | None = None


# 파일별 파싱 결과 캐시: path -> (mtime, size, records)
_cache: dict[str, tuple[float, int, list]] = {}


def _recent_files(pattern: str) -> list[str]:
    cutoff = time.time() - LOOKBACK_DAYS * 86400
    return [f for f in glob.glob(pattern, recursive=True) if os.path.getmtime(f) >= cutoff]


def _parse_cached(path: str, parser) -> list:
    st = os.stat(path)
    hit = _cache.get(path)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    recs = parser(path)
    _cache[path] = (st.st_mtime, st.st_size, recs)
    return recs


def _parse_claude_file(path: str) -> list[tuple]:
    """(key, ts, model, input, cache_create, cache_read, output, session) 목록."""
    out = []
    with open(path, errors="ignore") as fp:
        for line in fp:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message")
            if not isinstance(m, dict) or "usage" not in m or not d.get("timestamp"):
                continue
            u = m["usage"]
            key = f"{m.get('id')}:{d.get('requestId')}"
            out.append((
                key,
                _ts(d["timestamp"]),
                m.get("model") or "?",
                u.get("input_tokens", 0) or 0,
                u.get("cache_creation_input_tokens", 0) or 0,
                u.get("cache_read_input_tokens", 0) or 0,
                u.get("output_tokens", 0) or 0,
                d.get("sessionId"),
            ))
    return out


def _window(raw: dict | None, pct_key: str, reset_key: str) -> Window:
    if not isinstance(raw, dict):
        return Window()
    pct = raw.get(pct_key)
    reset = raw.get(reset_key)
    reset_dt = None
    if isinstance(reset, (int, float)):
        reset_dt = datetime.fromtimestamp(reset, timezone.utc)
    elif isinstance(reset, str):
        try:
            reset_dt = _ts(reset)
        except ValueError:
            pass
    return Window(float(pct) if pct is not None else None, reset_dt)


def claude_usage(now: datetime | None = None) -> ClaudeUsage:
    now = now or datetime.now(timezone.utc)
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    seen: set[str] = set()
    recs = []
    for f in _recent_files(CLAUDE_GLOB):
        for r in _parse_cached(f, _parse_claude_file):
            if r[0] in seen:  # 스트리밍 중복 제거
                continue
            seen.add(r[0])
            recs.append(r)
    recs.sort(key=lambda r: r[1])

    u = ClaudeUsage()
    sessions: set[str] = set()
    # 5시간 블록 (ccusage 방식): 이전 메시지와 5시간 이상 벌어지거나 블록이 끝나면 새 블록
    block_start: datetime | None = None
    block_tokens = 0
    last_ts: datetime | None = None
    for _, ts, model, inp, cc, cr, outp, sid in recs:
        billable = inp + cc + outp
        if ts >= week_start:
            u.week_tokens += billable
        if ts >= local_midnight:
            u.today_tokens += billable
            u.today_output += outp
            u.today_cache_read += cr
            u.today_messages += 1
            u.by_model[model] = u.by_model.get(model, 0) + billable
            if sid:
                sessions.add(sid)
        if block_start is None or ts - block_start >= BLOCK or (last_ts and ts - last_ts >= BLOCK):
            block_start = ts.replace(minute=0, second=0, microsecond=0)
            block_tokens = 0
        block_tokens += billable
        last_ts = ts
    u.today_sessions = len(sessions)
    if block_start and now - block_start < BLOCK:
        u.block_tokens = block_tokens
        u.block_end = block_start + BLOCK

    # statusline 스냅샷(있으면)에서 공식 한도 사용률
    try:
        with open(CLAUDE_STATUS, encoding='utf-8') as fp:
            snap = json.load(fp)
        rl = snap.get("rate_limits") or {}
        u.five_hour = _window(rl.get("five_hour"), "used_percentage", "resets_at")
        u.seven_day = _window(rl.get("seven_day"), "used_percentage", "resets_at")
    except (OSError, ValueError):
        pass
    return u


def _parse_codex_file(path: str) -> list[tuple]:
    """(ts, last_total_tokens, rate_limits) 목록."""
    out = []
    with open(path, errors="ignore") as fp:
        for line in fp:
            if '"token_count"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            p = d.get("payload") or {}
            if p.get("type") != "token_count":
                continue
            info = p.get("info") or {}
            last = (info.get("last_token_usage") or {}).get("total_tokens", 0) or 0
            out.append((_ts(d["timestamp"]), last, p.get("rate_limits")))
    return out


def codex_usage(now: datetime | None = None) -> CodexUsage:
    now = now or datetime.now(timezone.utc)
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    c = CodexUsage()
    latest_rl: tuple[datetime, dict] | None = None
    for f in _recent_files(CODEX_GLOB):
        for ts, tokens, rl in _parse_cached(f, _parse_codex_file):
            if ts >= week_start:
                c.week_tokens += tokens
            if ts >= local_midnight:
                c.today_tokens += tokens
            if rl and (latest_rl is None or ts > latest_rl[0]):
                latest_rl = (ts, rl)
    if latest_rl:
        ts, rl = latest_rl
        c.updated = ts
        c.primary = _window(rl.get("primary"), "used_percent", "resets_at")
        c.secondary = _window(rl.get("secondary"), "used_percent", "resets_at")
        c.primary_window_min = (rl.get("primary") or {}).get("window_minutes")
        credits = rl.get("credits") or {}
        if credits.get("unlimited"):
            c.credits = "무제한"
        elif credits.get("balance") is not None:
            c.credits = str(credits["balance"])
    return c


def codex_live() -> CodexUsage | None:
    """ChatGPT 백엔드에서 Codex 한도를 실시간 조회 (Codex CLI 의 /status 와 같은 출처).

    ~/.codex/auth.json 의 토큰을 사용한다. 실패하면 None (호출 측에서 로그 값으로 대체).
    """
    import ssl
    import urllib.request

    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
        tokens = json.load(open(f"{HOME}/.codex/auth.json"))["tokens"]
        req = urllib.request.Request(
            "https://chatgpt.com/backend-api/wham/usage",
            headers={
                "Authorization": f"Bearer {tokens['access_token']}",
                "ChatGPT-Account-Id": tokens.get("account_id", ""),
                "User-Agent": "codex-cli",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
            d = json.loads(r.read())
    except Exception:
        return None

    def win(w: dict | None) -> tuple[Window, int | None]:
        if not w:
            return Window(), None
        reset = w.get("reset_at")
        return (
            Window(float(w["used_percent"]), datetime.fromtimestamp(reset, timezone.utc) if reset else None),
            (w.get("limit_window_seconds") or 0) // 60 or None,
        )

    rl = d.get("rate_limit") or {}
    c = CodexUsage()
    c.primary, c.primary_window_min = win(rl.get("primary_window"))
    c.secondary, _ = win(rl.get("secondary_window"))
    c.updated = datetime.now(timezone.utc)
    credits = d.get("credits") or {}
    c.credits = "무제한" if credits.get("unlimited") else credits.get("balance")
    return c


def human(n: float) -> str:
    """1234567 -> 1.2M"""
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return str(int(n))


def until(dt: datetime | None, now: datetime | None = None) -> str:
    """남은 시간을 '3h12m' / '2d5h' 형식으로."""
    if not dt:
        return "-"
    sec = (dt - (now or datetime.now(timezone.utc))).total_seconds()
    if sec <= 0:
        return "리셋됨"
    d, rem = divmod(int(sec), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}d{h}h" if d else (f"{h}h{m:02d}m" if h else f"{m}m")


if __name__ == "__main__":
    t = time.time()
    cu, xu = claude_usage(), codex_usage()
    print(f"[{time.time() - t:.2f}s]")
    print("Claude:", cu)
    print("Codex:", xu)

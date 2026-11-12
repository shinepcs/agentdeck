"""Capture Claude Code's documented rate_limits, preserving an existing status line."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def capture(data: dict, path: Path | None = None) -> None:
    limits = data.get('rate_limits') or {}
    if not isinstance(limits, dict) or not any(
        isinstance(limits.get(key), dict) and isinstance(limits[key].get('used_percentage'), (int, float))
        for key in ('five_hour', 'seven_day')
    ):
        return  # The first render before an API response must not erase the last quota.
    path = path or Path.home() / '.cache/d200/claude_status.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'{path.name}.{os.getpid()}')
    temp.write_text(json.dumps({'rate_limits': limits, 'updated_at': time.time()}), encoding='utf-8')
    os.replace(temp, path)


def main() -> int:
    payload = sys.stdin.buffer.read()
    try:
        capture(json.loads(payload))
    except (OSError, ValueError, TypeError, AttributeError):
        pass  # Capturing data must never interrupt the user's existing status line.
    previous = json.loads(base64.b64decode(sys.argv[1])) if len(sys.argv) > 1 else None
    if previous and previous.get('command'):
        return subprocess.run(previous['command'], shell=True, input=payload).returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

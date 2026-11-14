"""Keep the Windows dashboard running across USB disconnects and updates."""
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def main() -> None:
    with (ROOT / 'dashboard.log').open('a', encoding='utf-8') as output, \
         (ROOT / 'dashboard-error.log').open('a', encoding='utf-8') as errors:
        try:
            while True:
                result = subprocess.call(
                    [sys.executable, '-X', 'utf8', '-u', str(ROOT / 'dashboard.py')],
                    cwd=ROOT, stdout=output, stderr=errors,
                )
                print(f'{datetime.now():%Y-%m-%d %H:%M:%S} dashboard exited ({result}); retrying in 5s',
                      file=output, flush=True)
                time.sleep(5)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()

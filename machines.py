"""컴퓨터별 자원 상태 (CPU, 메모리, 디스크) — 로컬 + Tailscale SSH."""

from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from config import EXTERNAL_DRIVES_CFG, MACHINES_CFG

# 외장 드라이브: (볼륨 이름, 연결된 컴퓨터 표시 이름) — 분리되면 경고 (config.json)
EXTERNAL_DRIVES: list[tuple[str, str]] = [(d["volume"], d["machine"]) for d in EXTERNAL_DRIVES_CFG]

# (표시 이름, ssh 대상 — None 이면 이 맥) (config.json)
MACHINES: list[tuple[str, str | None]] = [(m["name"], m.get("ssh")) for m in MACHINES_CFG]

PROBE = r'''
ncpu=$(sysctl -n hw.ncpu); mem=$(sysctl -n hw.memsize)
cpu=$(top -l 2 -n 0 -s 1 | awk '/CPU usage/{u=$3; s=$5} END{gsub("%","",u); gsub("%","",s); print u+s}')
free=$(memory_pressure 2>/dev/null | awk -F': ' '/free percentage/{gsub("%","",$2); print $2}')
read dtot davail <<< $(df -k /System/Volumes/Data | awk 'NR==2{print $2, $4}')
boot=$(sysctl -n kern.boottime | awk -F'[ ,]' '{print $4}')
# 100GB 이상 외장 볼륨만 (설치 이미지 dmg 등 제외)
vols=$(df -kP | awk '{i=index($0," /Volumes/"); if (i>0 && $2+0 >= 104857600) {m=substr($0,i+10); printf "%s{\"name\":\"%s\",\"total_kb\":%s,\"avail_kb\":%s}", sep, m, $2, $4; sep=","}}')
echo "{\"ncpu\":$ncpu,\"cpu\":$cpu,\"mem\":$mem,\"mem_free_pct\":${free:-null},\"disk_total_kb\":$dtot,\"disk_avail_kb\":$davail,\"boot\":$boot,\"volumes\":[$vols]}"
'''


@dataclass
class MachineStat:
    name: str
    online: bool
    cpu: float = 0.0  # 사용률 0~100
    mem_used: float = 0.0  # 0~100 (memory_pressure 기준)
    mem_gb: float = 0.0
    disk_used: float = 0.0  # 0~100
    disk_free_gb: float = 0.0
    uptime_days: float = 0.0
    volumes: list[Volume] = field(default_factory=list)


@dataclass
class Volume:
    name: str
    machine: str
    mounted: bool
    total_gb: float = 0.0
    free_gb: float = 0.0

    @property
    def used_pct(self) -> float:
        return (1 - self.free_gb / self.total_gb) * 100 if self.total_gb else 0.0


def _probe(name: str, target: str | None) -> MachineStat:
    if target is None and os.name == "nt":
        try:
            import psutil

            mem = psutil.virtual_memory()
            disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + os.sep)
            volumes = []
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    volumes.append(Volume(part.mountpoint, name, True, usage.total / 1024**3, usage.free / 1024**3))
                except OSError:
                    continue
            return MachineStat(name, True, cpu=psutil.cpu_percent(interval=0.1), mem_used=mem.percent,
                               mem_gb=mem.total / 1024**3, disk_used=disk.percent,
                               disk_free_gb=disk.free / 1024**3,
                               uptime_days=(time.time() - psutil.boot_time()) / 86400, volumes=volumes)
        except Exception:
            return MachineStat(name, False)
    cmd = ["bash", "-s"] if target is None else \
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", target, "bash", "-s"]
    try:
        r = subprocess.run(cmd, input=PROBE, capture_output=True, text=True, timeout=25)
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return MachineStat(name, False)
    total, avail = d["disk_total_kb"], d["disk_avail_kb"]
    free_pct = d.get("mem_free_pct")
    return MachineStat(
        name=name,
        online=True,
        cpu=float(d["cpu"]),
        mem_used=100 - float(free_pct) if free_pct is not None else 0.0,
        mem_gb=d["mem"] / 1024**3,
        disk_used=(1 - avail / total) * 100 if total else 0.0,
        disk_free_gb=avail / 1024**2,
        uptime_days=(time.time() - d["boot"]) / 86400,
        volumes=[Volume(v["name"], name, True, v["total_kb"] / 1024**2, v["avail_kb"] / 1024**2)
                 for v in d.get("volumes", [])],
    )


def machine_stats(pool: ThreadPoolExecutor | None = None) -> list[MachineStat]:
    own = pool is None
    pool = pool or ThreadPoolExecutor(len(MACHINES))
    try:
        return [f.result() for f in [pool.submit(_probe, n, t) for n, t in MACHINES]]
    finally:
        if own:
            pool.shutdown(wait=False)


def external_drives(stats: list[MachineStat]) -> list[Volume]:
    """설정한 외장 드라이브 상태 (연결된 컴퓨터가 꺼졌거나 분리되면 mounted=False)."""
    found = {(v.name, v.machine): v for m in stats for v in m.volumes}
    return [found.get((name, mach), Volume(name, mach, False)) for name, mach in EXTERNAL_DRIVES]


if __name__ == "__main__":
    st = machine_stats()
    for m in st:
        print(m.name, f"cpu {m.cpu:.0f} mem {m.mem_used:.0f} disk {m.disk_used:.0f}", [v.name for v in m.volumes])
    for v in external_drives(st):
        print(v, f"{v.used_pct:.0f}%")

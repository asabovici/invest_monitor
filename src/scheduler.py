"""systemd user-service integration for the production runner.

Generates `.service` + `.timer` unit files under `~/.config/systemd/user/` so
each registered job can fire on its own schedule without needing cron. All
operations run as the *user* — no sudo, no root daemon. macOS and other
non-systemd platforms are detected and the feature is skipped.

Public surface:
  is_systemd_available()       — bool
  service_unit(job_name)       — str (content of the .service file)
  timer_unit(job_name, mins)   — str (content of the .timer file)
  install(job_name, mins)      — write units + enable --now
  uninstall(job_name)          — disable --now + remove units
  status(job_name)             — { installed, active, enabled, next_run }
  list_scheduled()             — { job_name: status_dict }
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


# ── Environment probing ───────────────────────────────────────────────────────

def is_systemd_available() -> bool:
    """True iff `systemctl --user` works on this machine."""
    if shutil.which("systemctl") is None:
        return False
    try:
        r = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def systemd_user_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    p = Path(base) / "systemd" / "user"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _detect_runner() -> tuple[str, str]:
    """Return (working_dir, ExecStart command string) for invoking the CLI.

    Picks the most reliable launcher available:
      1. `uv run invest-monitor …`  if uv is on PATH AND we're in the project
      2. absolute `invest-monitor`  binary if installed on PATH
      3. `python3 -m src.cli`        as a last resort
    """
    cwd = os.getcwd()
    uv = shutil.which("uv")
    if uv and (Path(cwd) / "pyproject.toml").exists():
        return cwd, f"{uv} run invest-monitor"
    inv = shutil.which("invest-monitor")
    if inv:
        return cwd, inv
    py = shutil.which("python3") or "/usr/bin/python3"
    return cwd, f"{py} -m src.cli"


# ── Unit-file generation ──────────────────────────────────────────────────────

UNIT_PREFIX = "invest-monitor-"


def unit_paths(job_name: str) -> tuple[Path, Path]:
    d = systemd_user_dir()
    return (
        d / f"{UNIT_PREFIX}{job_name}.service",
        d / f"{UNIT_PREFIX}{job_name}.timer",
    )


def service_unit(job_name: str) -> str:
    cwd, base_cmd = _detect_runner()
    return (
        f"[Unit]\n"
        f"Description=invest-monitor production job: {job_name}\n"
        f"After=network-online.target\n"
        f"Wants=network-online.target\n"
        f"\n"
        f"[Service]\n"
        f"Type=oneshot\n"
        f"WorkingDirectory={cwd}\n"
        f"ExecStart={base_cmd} production run-now {job_name}\n"
        f"StandardOutput=journal\n"
        f"StandardError=journal\n"
    )


def timer_unit(job_name: str, interval_minutes: int) -> str:
    # OnUnitActiveSec re-fires X after the *previous* run finishes, which is
    # simpler than wall-clock OnCalendar for our "every N hours" jobs.
    # Persistent=true catches up missed runs after the machine wakes up.
    return (
        f"[Unit]\n"
        f"Description=Timer for invest-monitor job: {job_name}\n"
        f"\n"
        f"[Timer]\n"
        f"OnBootSec=5min\n"
        f"OnUnitActiveSec={interval_minutes}min\n"
        f"Persistent=true\n"
        f"Unit={UNIT_PREFIX}{job_name}.service\n"
        f"\n"
        f"[Install]\n"
        f"WantedBy=timers.target\n"
    )


# ── Install / uninstall ───────────────────────────────────────────────────────

def install(job_name: str, interval_minutes: int) -> dict:
    """Write unit files and enable --now the timer.

    Returns {ok: bool, detail: str}.
    """
    if not is_systemd_available():
        return {"ok": False, "detail": "systemd --user is not available on this system."}

    svc_path, timer_path = unit_paths(job_name)
    svc_path.write_text(service_unit(job_name))
    timer_path.write_text(timer_unit(job_name, interval_minutes))

    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"],
                       check=True, timeout=10, capture_output=True, text=True)
        r = subprocess.run(
            ["systemctl", "--user", "enable", "--now", timer_path.name],
            check=True, timeout=10, capture_output=True, text=True,
        )
        return {"ok": True, "detail": (r.stdout or r.stderr or "").strip()
                                       or f"Installed and started {timer_path.name}."}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "detail": (e.stderr or str(e)).strip()}


def uninstall(job_name: str) -> dict:
    """Disable + stop the timer, remove the unit files."""
    if not is_systemd_available():
        return {"ok": False, "detail": "systemd --user is not available on this system."}

    svc_path, timer_path = unit_paths(job_name)
    # `disable --now` is the same as stop + disable; ignore failures from
    # already-stopped or never-enabled units.
    subprocess.run(["systemctl", "--user", "disable", "--now", timer_path.name],
                   check=False, timeout=10, capture_output=True)
    for p in (svc_path, timer_path):
        if p.exists():
            p.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"],
                   check=False, timeout=10, capture_output=True)
    return {"ok": True, "detail": f"Removed {UNIT_PREFIX}{job_name}.{{service,timer}}."}


# ── Status probing ────────────────────────────────────────────────────────────

def status(job_name: str) -> dict:
    """Return current state of the timer for a job."""
    svc_path, timer_path = unit_paths(job_name)
    if not is_systemd_available():
        return {"available": False, "installed": False, "active": False, "enabled": False}
    if not timer_path.exists():
        return {"available": True, "installed": False, "active": False, "enabled": False}

    def _check(cmd: list[str]) -> str:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return (r.stdout or "").strip()
        except Exception:
            return ""

    active_raw  = _check(["systemctl", "--user", "is-active",  timer_path.name])
    enabled_raw = _check(["systemctl", "--user", "is-enabled", timer_path.name])
    next_run    = _next_run_at(timer_path.name)

    return {
        "available":   True,
        "installed":   True,
        "active":      active_raw == "active",
        "enabled":     enabled_raw == "enabled",
        "active_raw":  active_raw,
        "enabled_raw": enabled_raw,
        "next_run":    next_run,
    }


def _next_run_at(timer_name: str) -> Optional[str]:
    """Parse the NEXT column from `systemctl --user list-timers`."""
    try:
        r = subprocess.run(
            ["systemctl", "--user", "list-timers", "--all", "--no-legend", timer_name],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return None
        line = (r.stdout or "").strip().splitlines()
        if not line:
            return None
        # Format (whitespace-separated): NEXT_DATE NEXT_TIME ZONE LEFT  LAST_DATE LAST_TIME ZONE PASSED UNIT ACTIVATES
        # The first 4 fields are about NEXT — joining them is more reliable
        # than trying to parse columns by character position.
        parts = line[0].split()
        if len(parts) < 4:
            return None
        return " ".join(parts[:4])
    except Exception:
        return None


def list_scheduled() -> dict[str, dict]:
    """Return {job_name: status_dict} for every job registered in the registry."""
    from src.production import JOB_REGISTRY
    return {name: status(name) for name in JOB_REGISTRY}

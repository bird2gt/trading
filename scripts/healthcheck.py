#!/usr/bin/env python3
"""Liveness check for the MT4 trading bot. Run on a schedule (launchd, every 15m).

Healthy = run.py process is up AND the bridge port is listening AND bot.log was
written recently (catches a hung-but-alive process that the supervisor misses).
On failure, send one Telegram alert, throttled so a sustained outage doesn't spam.

Telegram creds come from the project's .env (same TELEGRAM_BOT_TOKEN /
TELEGRAM_CHAT_ID the bot uses), loaded via python-dotenv.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BOT_LOG = ROOT / "logs" / "bot.log"
ALERT_MARKER = ROOT / "logs" / ".healthcheck_alert"
HEARTBEAT = ROOT / "logs" / ".healthcheck_last_run"   # touched every run — proves cron fired
PORT = 8000
MT4_FILES_DIR = Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader4/drive_c/Program Files (x86)/MetaTrader 4/MQL4/Files"
MT4_FILE_STALE_SECONDS = int(os.environ.get("MT4_FILE_STALE_SECONDS", "30"))
LOG_STALE_SECONDS = 20 * 60      # poll is 5m; 20m means several missed cycles
ALERT_THROTTLE_SECONDS = 60 * 60  # at most one alert per hour while down


def _run(args: list[str], timeout: int = 5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _bridge_pids() -> list[str]:
    try:
        r = _run(["/usr/sbin/lsof", "-nP", f"-tiTCP:{PORT}", "-sTCP:LISTEN"])
    except Exception:
        return []
    if r.returncode != 0:
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def _pid_cwd(pid: str) -> str | None:
    try:
        r = _run(["/usr/sbin/lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"])
    except Exception:
        return None
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def _process_up() -> bool:
    return any(_pid_cwd(pid) == str(ROOT) for pid in _bridge_pids())


def _port_listening() -> bool:
    return bool(_bridge_pids())


def _file_check(filename: str, required: bool = True, require_float: bool = False) -> bool:
    path = MT4_FILES_DIR / filename
    if not path.exists():
        return not required
    age_s = max(0.0, time.time() - path.stat().st_mtime)
    if age_s > MT4_FILE_STALE_SECONDS:
        return False
    if require_float:
        try:
            float(path.read_text().strip())
        except Exception:
            return False
    return True


def _bridge_ready_reason() -> str | None:
    checks = {
        "balance": _file_check("balance.txt", require_float=True),
        "positions": _file_check("positions.txt"),
    }
    if all(checks.values()):
        return None
    failed = [
        name for name, ok in checks.items()
        if not ok
    ]
    return "MT4 files not ready: " + (", ".join(failed) if failed else "unknown reason")


def _log_fresh() -> bool:
    try:
        age = time.time() - BOT_LOG.stat().st_mtime
    except OSError:
        return False
    return age < LOG_STALE_SECONDS


def _diagnose() -> str | None:
    """Return a failure reason, or None if healthy."""
    if not _process_up():
        return "run.py process not found"
    if not _port_listening():
        return f"bridge port {PORT} not listening"
    ready_reason = _bridge_ready_reason()
    if ready_reason is not None:
        return ready_reason
    if not _log_fresh():
        return f"bot.log stale (no write in {LOG_STALE_SECONDS // 60}m)"
    return None


def _send_telegram(text: str) -> None:
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("[healthcheck] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
        return
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[healthcheck] telegram send failed: {e}")


def _recently_alerted() -> bool:
    try:
        age = time.time() - ALERT_MARKER.stat().st_mtime
    except OSError:
        return False
    return age < ALERT_THROTTLE_SECONDS


def main() -> int:
    HEARTBEAT.touch()   # record that the check ran, even when the bot is healthy (silent path)
    reason = _diagnose()
    if reason is None:
        ALERT_MARKER.unlink(missing_ok=True)   # recovered — reset throttle
        return 0
    if not _recently_alerted():
        restart_cmd = f"cd {ROOT} && nohup ./scripts/supervise_run_mt4.sh &"
        _send_telegram(
            f"⚠️ Trading bot DOWN: {reason}\n\n"
            f"Подними вручную (напр. после перезагрузки Mac):\n{restart_cmd}"
        )
        ALERT_MARKER.touch()
    print(f"[healthcheck] DOWN: {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

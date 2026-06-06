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
LOG_STALE_SECONDS = 20 * 60      # poll is 5m; 20m means several missed cycles
ALERT_THROTTLE_SECONDS = 60 * 60  # at most one alert per hour while down


def _process_up() -> bool:
    r = subprocess.run(["pgrep", "-f", "run.py"], capture_output=True)
    return r.returncode == 0


def _port_listening() -> bool:
    r = subprocess.run(
        ["/usr/sbin/lsof", f"-tiTCP:{PORT}", "-sTCP:LISTEN"],
        capture_output=True,
    )
    return r.returncode == 0


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

"""
Economic calendar guard — blocks new trades around high-impact events.
Also provides today's event list for the daily digest.

Data source: ForexFactory (unofficial JSON feed, updated weekly).
"""

import os
import json
import time
import requests
import anthropic
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv()

_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_HEADERS   = {"User-Agent": "Mozilla/5.0"}

_cache: tuple[list, float] = ([], 0.0)
_CACHE_TTL = 1800  # re-fetch every 30 minutes

# Which currencies to watch per symbol
_CURRENCIES = {
    "EUR/USD": {"EUR", "USD"},
    "USD/CHF": {"USD", "CHF"},
    "GBP/USD": {"GBP", "USD"},
    "EUR/CHF": {"EUR", "CHF"},
    "USD/CAD": {"USD", "CAD"},
    "AUD/USD": {"AUD", "USD"},
    "USD/JPY": {"USD", "JPY"},
    "BTC/USD": {"USD"},
    "ETH/USD": {"USD"},
    "XAU/USD": {"USD"},
    "XAG/USD": {"USD"},
}

HOURS_BEFORE = 2   # block N hours before event
HOURS_AFTER  = 1   # block N hours after event


def is_high_impact_soon(symbol: str) -> tuple[bool, str]:
    """
    Returns (True, event_title) if a high-impact event for this symbol
    falls within the block window, otherwise (False, "").
    """
    currencies = _CURRENCIES.get(symbol, set())
    if not currencies:
        return False, ""

    now = datetime.now(timezone.utc)
    events = _fetch_events()

    for ev in events:
        if ev.get("impact") != "High":
            continue
        if ev.get("country") not in currencies:
            continue

        ev_time = _parse_time(ev.get("date", ""))
        if ev_time is None:
            continue

        delta = (ev_time - now).total_seconds() / 3600
        if -HOURS_AFTER <= delta <= HOURS_BEFORE:
            return True, ev.get("title", "event")

    return False, ""


def is_high_impact_active(symbol: str, minutes_before: int = 0,
                          minutes_after: int = 60) -> tuple[bool, str]:
    """
    Returns (True, event_title) during the active post-release news window.
    Intended for breakout logic, so the default starts at event time and
    lasts one hour after the release.
    """
    currencies = _CURRENCIES.get(symbol, set())
    if not currencies:
        return False, ""

    now = datetime.now(timezone.utc)
    for ev in _fetch_events():
        if ev.get("impact") != "High":
            continue
        if ev.get("country") not in currencies:
            continue

        ev_time = _parse_time(ev.get("date", ""))
        if ev_time is None:
            continue

        delta_min = (ev_time - now).total_seconds() / 60
        if -minutes_after <= delta_min <= minutes_before:
            return True, ev.get("title", "event")

    return False, ""


def recent_high_impact_events(symbol: str, within_hours: float) -> list[dict]:
    """High-impact events for the symbol's currencies released within the last
    `within_hours`, newest first. Used by the intraday surprise layer to know
    *when* a release happened (the feed carries no actual values). Each item:
    {"time": datetime(UTC), "country": str, "title": str}."""
    currencies = _CURRENCIES.get(symbol, set())
    if not currencies:
        return []
    now = datetime.now(timezone.utc)
    out = []
    for ev in _fetch_events():
        if ev.get("impact") != "High" or ev.get("country") not in currencies:
            continue
        ev_time = _parse_time(ev.get("date", ""))
        if ev_time is None:
            continue
        age_h = (now - ev_time).total_seconds() / 3600
        if 0 <= age_h <= within_hours:
            out.append({"time": ev_time, "country": ev["country"], "title": ev.get("title", "")})
    out.sort(key=lambda e: e["time"], reverse=True)
    return out


_FLAG = {
    "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "CHF": "🇨🇭",
    "JPY": "🇯🇵", "NZD": "🇳🇿", "CAD": "🇨🇦", "AUD": "🇦🇺",
}
_IMPACT_MARK = {"High": "⚡️ ", "Medium": ""}


def get_today_events(min_impact: str = "Medium") -> str:
    """
    Returns a formatted string of today's economic events for the digest.
    min_impact: "High" to show only high-impact, "Medium" for both.
    """
    allowed = {"High"} if min_impact == "High" else {"High", "Medium"}
    now = datetime.now(timezone.utc)
    today = now.date()

    events = _fetch_events()
    lines = []
    for ev in events:
        if ev.get("impact") not in allowed:
            continue
        ev_time = _parse_time(ev.get("date", ""))
        if ev_time is None or ev_time.date() != today:
            continue
        country = ev.get("country", "")
        flag = _FLAG.get(country, f"[{country}]")
        mark = _IMPACT_MARK.get(ev.get("impact", ""), "")
        time_str = ev_time.strftime("%H:%M")
        title = ev.get("title", "")
        forecast = ev.get("forecast", "")
        previous = ev.get("previous", "")
        detail = ""
        if forecast:
            detail += f" — Ожид: {forecast}"
        if previous:
            detail += f" | Пред: {previous}"
        lines.append(f"{time_str} {flag} {mark}{title}{detail}")

    if not lines:
        return ""
    return "\n".join(lines)


_DAYS_RU = {
    "Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда",
    "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье",
}
_MONTHS_RU = {
    "January": "января", "February": "февраля", "March": "марта", "April": "апреля",
    "May": "мая", "June": "июня", "July": "июля", "August": "августа",
    "September": "сентября", "October": "октября", "November": "ноября", "December": "декабря",
}


def _enrich_with_claude(raw_events: list[dict]) -> str:
    events_data = []
    for ev in raw_events:
        ev_time = _parse_time(ev.get("date", ""))
        events_data.append({
            "time": ev_time.strftime("%H:%M") if ev_time else "",
            "country": ev.get("country", ""),
            "impact": ev.get("impact", ""),
            "title": ev.get("title", ""),
            "forecast": ev.get("forecast", ""),
            "previous": ev.get("previous", ""),
        })

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        system=(
            "Ты помощник трейдера. Для каждого события верни JSON массив объектов:\n"
            '{"title_ru": "название на русском", "impact_ru": "краткое влияние или null"}\n'
            "impact_ru — одна строка, например: \"Рост > ожид → USD↑, золото↓\"\n"
            "impact_ru = null если Low или влияние неочевидно.\n"
            "Верни ТОЛЬКО JSON, без пояснений."
        ),
        messages=[{"role": "user", "content": json.dumps(events_data, ensure_ascii=False)}],
    )

    raw = resp.content[0].text.strip()
    # strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    enriched = json.loads(raw.strip())
    lines = []
    for ev, meta in zip(events_data, enriched):
        flag = _FLAG.get(ev["country"], f"[{ev['country']}]")
        mark = _IMPACT_MARK.get(ev["impact"], "")
        title_ru = meta.get("title_ru") or ev["title"]
        detail = ""
        if ev["forecast"]:
            detail += f" — Ожид: {ev['forecast']}"
        if ev["previous"]:
            detail += f" | Пред: {ev['previous']}"
        line = f"{ev['time']} {flag} {mark}{title_ru}{detail}"
        impact_ru = meta.get("impact_ru")
        if impact_ru:
            line += f"\n   → {impact_ru}"
        lines.append(line)
    return "\n\n".join(lines)


def send_calendar_to_telegram() -> None:
    allowed = {"High", "Medium"}
    today = datetime.now(timezone.utc).date()
    raw_events = [
        ev for ev in _fetch_events()
        if ev.get("impact") in allowed
        and _parse_time(ev.get("date", "")) is not None
        and _parse_time(ev.get("date", "")).date() == today
    ]

    if not raw_events:
        print("Calendar: no events today, skipping.")
        return

    now = datetime.now(timezone.utc)
    date_str = f"{_DAYS_RU[now.strftime('%A')]} {now.day} {_MONTHS_RU[now.strftime('%B')]}"

    text = _enrich_with_claude(raw_events)

    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("Calendar: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set.")
        return

    message = f"💥 Календарь событий — {date_str} 💥\n\n{text}"
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        print(f"Calendar sent → Telegram ({len(text)} chars)")
    except Exception as e:
        print(f"Calendar Telegram error: {e}")


def _fetch_events() -> list:
    global _cache
    events, fetched_at = _cache

    if time.time() - fetched_at < _CACHE_TTL:
        return events

    try:
        resp = requests.get(_FEED_URL, headers=_HEADERS, timeout=10)
        events = resp.json()
        _cache = (events, time.time())
    except Exception:
        pass  # keep stale cache on error

    return events


def _parse_time(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    send_calendar_to_telegram()

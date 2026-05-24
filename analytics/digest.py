"""
Daily forecaster digest — runs if new posts appeared since yesterday.

Fetches from top macro analysts and research teams, summarizes with Claude
by symbol and macro/political context, saves draft to forecasts/ for review.

Run manually: python -m analytics.digest
"""

from __future__ import annotations
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import requests
import feedparser
import anthropic
from dotenv import load_dotenv
load_dotenv()

# ── Market forecasters (12) ────────────────────────────────────────────────

FORECASTERS = [
    # Forex / macro
    {
        "name":   "Marc Chandler — Marc to Market",
        "url":    "https://marctomarket.com/feed/",
        "topics": ["EUR/USD", "USD/CHF"],
    },
    {
        "name":   "Calculated Risk",
        "url":    "https://www.calculatedriskblog.com/feeds/posts/default",
        "topics": ["EUR/USD", "USD/CHF", "XAU/USD"],
    },
    {
        "name":   "Barry Ritholtz — The Big Picture",
        "url":    "https://ritholtz.com/feed/",
        "topics": ["EUR/USD", "XAU/USD", "BTC/USD"],
    },
    {
        "name":   "Wolf Street",
        "url":    "https://wolfstreet.com/feed/",
        "topics": ["EUR/USD", "USD/CHF", "XAU/USD"],
    },
    {
        "name":   "Mish Talk",
        "url":    "https://mishtalk.com/feed/",
        "topics": ["EUR/USD", "XAU/USD", "XAG/USD"],
    },
    {
        "name":   "The Felder Report",
        "url":    "https://thefelderreport.com/feed/",
        "topics": ["EUR/USD", "XAU/USD", "BTC/USD"],
    },
    # Research teams
    {
        "name":   "ING Think",
        "url":    "https://think.ing.com/feed/",
        "topics": ["EUR/USD", "USD/CHF"],
    },
    {
        "name":   "NY Fed Liberty Street",
        "url":    "https://libertystreeteconomics.newyorkfed.org/feed.xml",
        "topics": ["EUR/USD", "USD/CHF", "XAU/USD"],
    },
    {
        "name":   "FRED Blog — St. Louis Fed",
        "url":    "https://fredblog.stlouisfed.org/feed/",
        "topics": ["EUR/USD", "USD/CHF", "XAU/USD"],
    },
    {
        "name":   "World Gold Council",
        "url":    "https://www.gold.org/rss",
        "topics": ["XAU/USD", "XAG/USD"],
    },
    {
        "name":   "Glassnode Insights",
        "url":    "https://insights.glassnode.com/rss/",
        "topics": ["BTC/USD"],
    },
    {
        "name":   "Messari",
        "url":    "https://messari.io/rss",
        "topics": ["BTC/USD"],
    },
]

# ── Macro / political economy forecasters (4) ─────────────────────────────

MACRO_POLITICAL = [
    {
        "name":   "VoxEU — CEPR",
        "url":    "https://cepr.org/vox/rss.xml",
        "about":  "European economics, trade policy, sanctions, monetary policy",
    },
    {
        "name":   "Project Syndicate",
        "url":    "https://www.project-syndicate.org/rss",
        "about":  "Global economists on policy: Roubini, Stiglitz, El-Erian",
    },
    {
        "name":   "Econbrowser",
        "url":    "https://econbrowser.com/feed",
        "about":  "Data-driven US macro and policy analysis (Hamilton & Chinn)",
    },
    {
        "name":   "Council on Foreign Relations",
        "url":    "https://www.cfr.org/rss/blog_entries.xml",
        "about":  "Geopolitics and economic policy, trade wars, sanctions",
    },
]

HEADERS   = {"User-Agent": "Mozilla/5.0"}
LOOKBACK  = 1    # days — only posts from the last 24 hours
MAX_POSTS = 5    # posts per forecaster


def _is_approved_today() -> bool:
    """Return True if the user sent any message to the bot today after 06:00 UTC."""
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"limit": 50, "allowed_updates": ["message"]},
            timeout=10,
        )
        updates = resp.json().get("result", [])
        cutoff_today = datetime.now(timezone.utc).replace(hour=6, minute=0, second=0, microsecond=0)
        for upd in updates:
            msg = upd.get("message", {})
            if str(msg.get("chat", {}).get("id", "")) != str(chat_id):
                continue
            ts = msg.get("date", 0)
            msg_time = datetime.fromtimestamp(ts, tz=timezone.utc)
            if msg_time >= cutoff_today:
                return True
    except Exception:
        pass
    return False


def run_digest() -> None:
    today  = date.today()
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK)

    if _is_approved_today():
        print("Digest: already approved by user today, skipping.")
        return

    market_entries = _fetch_all(FORECASTERS, cutoff)
    macro_entries  = _fetch_all(MACRO_POLITICAL, cutoff)

    if not market_entries and not macro_entries:
        print("Digest: no new posts today, skipping.")
        return

    client   = anthropic.Anthropic()
    sections = []

    # Market section — grouped by symbol
    if market_entries:
        by_topic: dict[str, list[str]] = {}
        for e in market_entries:
            for topic in e["topics"]:
                by_topic.setdefault(topic, []).append(f"[{e['source']}] {e['title']}")

        for topic, posts in by_topic.items():
            text = "\n".join(f"- {p}" for p in posts[:20])
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=(
                    "Ты макро-аналитик. Отвечай только на русском языке. "
                    "Суммируй преобладающий взгляд аналитиков на инструмент в 3-5 предложениях. "
                    "Заканчивай строкой 'Bias: бычий/медвежий/нейтральный — причина'."
                ),
                messages=[{"role": "user", "content": f"Посты аналитиков по {topic}:\n\n{text}"}],
            )
            sections.append(f"## {topic}\n\n{resp.content[0].text.strip()}")

    # Macro/political section — single summary
    if macro_entries:
        text = "\n".join(f"- [{e['source']}] {e['title']}" for e in macro_entries[:25])
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=(
                "Ты геополитический макро-аналитик. Отвечай только на русском языке. "
                "Суммируй ключевые политико-экономические темы из постов сегодня "
                "и как они могут повлиять на USD, EUR, золото и крипту. "
                "Указывай конкретное направление и механизм влияния."
            ),
            messages=[{"role": "user", "content": f"Сегодняшние макро/политические посты:\n\n{text}"}],
        )
        sections.append(f"## Макро и политический контекст\n\n{resp.content[0].text.strip()}")

    _save_digest(today, sections)
    _send_telegram("✅ Дайджест отправлен. Ответь любым сообщением — подтверди что прочитал.")


def _fetch_all(forecasters: list[dict], cutoff: datetime) -> list[dict]:
    results = []
    for f in forecasters:
        try:
            resp  = requests.get(f["url"], headers=HEADERS, timeout=10)
            feed  = feedparser.parse(resp.content)
            count = 0
            for entry in feed.entries:
                if count >= MAX_POSTS:
                    break
                published = _entry_time(entry)
                if published and published < cutoff:
                    continue
                results.append({
                    "source": f["name"],
                    "title":  entry.get("title", ""),
                    "topics": f.get("topics", []),
                })
                count += 1
        except Exception:
            continue
    return results


def _entry_time(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t is None:
        return None
    try:
        return datetime(*t[:6], tzinfo=timezone.utc)
    except Exception:
        return None


def _save_digest(today: date, sections: list[str]) -> None:
    path = Path(__file__).parent.parent / "forecasts" / f"{today}_digest.md"
    body = f"# Forecaster Digest — {today}\n\n" + "\n\n".join(sections)
    path.write_text(body, encoding="utf-8")
    print(f"Digest saved → {path}")
    _send_email(today, body)
    _send_telegram(f"📊 *Forecaster Digest — {today}*\n\n" + "\n\n".join(sections))


def _send_email(today: date, body: str) -> None:
    user     = os.environ.get("GMAIL_USER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not user or not password:
        print("Email: GMAIL_USER or GMAIL_APP_PASSWORD not set, skipping.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 Forecaster Digest — {today}"
    msg["From"]    = user
    msg["To"]      = user
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(user, password)
            smtp.sendmail(user, user, msg.as_string())
        print(f"Email sent → {user}")
    except Exception as e:
        print(f"Email error: {e}")


def _send_telegram(text: str) -> None:
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("Telegram: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set, skipping.")
        return

    # Telegram has 4096 char limit per message — split if needed
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception as e:
            print(f"Telegram send error: {e}")


if __name__ == "__main__":
    run_digest()

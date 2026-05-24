import time
import anthropic
from dotenv import load_dotenv
load_dotenv()

_client = None
_cache: dict[str, tuple[str, float]] = {}  # symbol → (sentiment, timestamp)
CACHE_TTL = 3600  # 1 hour


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def analyze_sentiment(symbol: str, headlines: list[str]) -> str:
    if not headlines:
        return "neutral"

    # return cached result if fresh
    if symbol in _cache:
        sentiment, ts = _cache[symbol]
        if time.time() - ts < CACHE_TTL:
            return sentiment

    text = "\n".join(f"- {h}" for h in headlines)

    message = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        system="You are a forex market analyst. Reply with exactly one word.",
        messages=[{
            "role": "user",
            "content": (
                f"Based on these news headlines, what is the outlook for {symbol}? "
                f"Reply with only: bullish, bearish, or neutral.\n\n{text}"
            ),
        }],
    )

    raw = message.content[0].text.strip().lower()
    if "bullish" in raw:
        sentiment = "bullish"
    elif "bearish" in raw:
        sentiment = "bearish"
    else:
        sentiment = "neutral"

    _cache[symbol] = (sentiment, time.time())
    return sentiment

import time
import anthropic
from dotenv import load_dotenv
load_dotenv()

_client = None
_cache: dict[str, tuple[int, float]] = {}  # symbol → (score, timestamp)
CACHE_TTL = 3600  # 1 hour

_SCORE_MAP = {
    "strongly_bearish": -2,
    "mildly_bearish":   -1,
    "neutral":           0,
    "mildly_bullish":    1,
    "strongly_bullish":  2,
}


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def analyze_sentiment(symbol: str, headlines: list[str]) -> int:
    """
    Returns sentiment score: -2 strongly bearish .. 0 neutral .. +2 strongly bullish.
    """
    if not headlines:
        return 0

    if symbol in _cache:
        score, ts = _cache[symbol]
        if time.time() - ts < CACHE_TTL:
            return score

    text = "\n".join(f"- {h}" for h in headlines)

    try:
        message = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            system="You are a forex market analyst. Reply with exactly one phrase.",
            messages=[{
                "role": "user",
                "content": (
                    f"Based on these news headlines, what is the outlook for {symbol}? "
                    f"Reply with only one of: "
                    f"strongly_bearish, mildly_bearish, neutral, mildly_bullish, strongly_bullish.\n\n{text}"
                ),
            }],
        )
        raw = message.content[0].text.strip().lower()
        score = next((v for k, v in _SCORE_MAP.items() if k in raw), 0)
    except Exception as e:
        print(f"[WARN] sentiment fallback neutral for {symbol}: {type(e).__name__}: {e}")
        score = 0

    _cache[symbol] = (score, time.time())
    return score

import requests
import feedparser

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

RSS_FEEDS = [
    "https://www.forexlive.com/feed/",
    "https://www.fxstreet.com/rss/news",
    "https://www.dailyfx.com/feeds/forex-rate-news",
]

KEYWORDS = {
    "EUR/USD": ["euro", "eur", "ecb", "european central", "dollar", "usd", "fed ", "forex"],
    "USD/CHF": ["swiss", "chf", "snb", "swiss national bank", "franc", "dollar", "usd"],
    "BTC/USD": ["bitcoin", "btc", "crypto", "cryptocurrency", "coinbase", "binance", "etf"],
    "XAU/USD": ["gold", "xau", "bullion", "precious metal", "inflation", "fed ", "dollar"],
    "XAG/USD": ["silver", "xag", "precious metals"],
}


def fetch_headlines(symbol: str, max_items: int = 15) -> list[str]:
    keywords = KEYWORDS.get(symbol, [])
    headlines = []

    for url in RSS_FEEDS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8)
            feed = feedparser.parse(resp.content)
            for entry in feed.entries:
                title = entry.get("title", "")
                if any(kw in title.lower() for kw in keywords):
                    headlines.append(title)
                if len(headlines) >= max_items:
                    return headlines
        except Exception:
            continue

    if not headlines:
        for url in RSS_FEEDS[:1]:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=8)
                feed = feedparser.parse(resp.content)
                headlines = [e.get("title", "") for e in feed.entries[:max_items]]
                break
            except Exception:
                continue

    return headlines

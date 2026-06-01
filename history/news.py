import requests
import feedparser

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# Per-symbol RSS feeds — each symbol gets its own relevant sources
FEEDS = {
    "EUR/USD": [
        "https://www.forexlive.com/feed/",
        "https://www.fxstreet.com/rss/news",
        "https://www.dailyfx.com/feeds/forex-rate-news",
        "https://feeds.reuters.com/reuters/topNews",
        "https://feeds.reuters.com/reuters/breakingviews",
        "https://feeds.marketwatch.com/marketwatch/realtimeheadlines/",
        "https://www.ft.com/?format=rss",
        "https://feeds.feedburner.com/zerohedge/feed",
        "https://www.axios.com/feeds/feed.rss",
        # research teams
        "https://think.ing.com/feed/",
        "https://libertystreeteconomics.newyorkfed.org/feed.xml",
        "https://www.piie.com/rss.xml",
    ],
    "USD/CHF": [
        "https://www.forexlive.com/feed/",
        "https://www.fxstreet.com/rss/news",
        "https://feeds.reuters.com/reuters/topNews",
        "https://feeds.reuters.com/reuters/breakingviews",
        "https://feeds.marketwatch.com/marketwatch/realtimeheadlines/",
        "https://www.ft.com/?format=rss",
        "https://feeds.feedburner.com/zerohedge/feed",
        "https://www.axios.com/feeds/feed.rss",
        # research teams
        "https://think.ing.com/feed/",
        "https://libertystreeteconomics.newyorkfed.org/feed.xml",
        "https://www.piie.com/rss.xml",
    ],
    "BTC/USD": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
        "https://www.forexlive.com/feed/",
        "https://www.caixinglobal.com/rss/",
        "https://feeds.reuters.com/reuters/breakingviews",
        "https://feeds.feedburner.com/zerohedge/feed",
        "https://www.axios.com/feeds/feed.rss",
        # research teams
        "https://messari.io/rss",
        "https://insights.glassnode.com/rss/",
    ],
    "XAU/USD": [
        "https://news.kitco.com/rss/",
        "https://www.forexlive.com/feed/",
        "https://feeds.reuters.com/reuters/topNews",
        "https://feeds.reuters.com/reuters/breakingviews",
        "https://www.fxstreet.com/rss/news",
        "https://www.caixinglobal.com/rss/",
        "https://feeds.feedburner.com/zerohedge/feed",
        "https://www.axios.com/feeds/feed.rss",
        # research teams
        "https://www.gold.org/rss",
        "https://libertystreeteconomics.newyorkfed.org/feed.xml",
    ],
    "XAG/USD": [
        "https://news.kitco.com/rss/",
        "https://www.forexlive.com/feed/",
        "https://feeds.reuters.com/reuters/topNews",
        "https://feeds.reuters.com/reuters/breakingviews",
        "https://www.caixinglobal.com/rss/",
        "https://feeds.feedburner.com/zerohedge/feed",
        "https://www.axios.com/feeds/feed.rss",
        # research teams
        "https://www.gold.org/rss",
    ],
}

KEYWORDS = {
    "EUR/USD": ["euro", "eur", "ecb", "european central", "dollar", "usd", "fed ", "forex"],
    "USD/CHF": ["swiss", "chf", "snb", "swiss national bank", "franc", "dollar", "usd"],
    "BTC/USD": ["bitcoin", "btc", "crypto", "cryptocurrency", "coinbase", "binance", "etf"],
    "XAU/USD": ["gold", "xau", "bullion", "precious metal", "inflation", "fed ", "dollar"],
    "XAG/USD": ["silver", "xag", "precious metals", "inflation", "fed ", "dollar", "gold", "bullion"],
}

FEEDS.update({
    "GBP/USD": list(FEEDS["EUR/USD"]),
    "EUR/CHF": list(FEEDS["USD/CHF"]),
    "USD/CAD": list(FEEDS["USD/CHF"]),
    "AUD/USD": list(FEEDS["USD/CHF"]),
    "USD/JPY": list(FEEDS["USD/CHF"]),
    "ETH/USD": list(FEEDS["BTC/USD"]),
})

KEYWORDS.update({
    "GBP/USD": ["pound", "sterling", "gbp", "boe", "bank of england", "dollar", "usd", "fed ", "forex"],
    "EUR/CHF": ["euro", "eur", "ecb", "swiss", "chf", "snb", "franc", "forex"],
    "USD/CAD": ["canadian", "cad", "bank of canada", "boc", "loonie", "oil", "wti", "dollar", "usd", "fed ", "forex"],
    "AUD/USD": ["australian", "aussie", "aud", "rba", "reserve bank of australia", "china", "iron ore", "dollar", "usd", "fed ", "forex"],
    "USD/JPY": ["yen", "jpy", "boj", "bank of japan", "japan", "treasury yields", "dollar", "usd", "fed ", "forex"],
    "ETH/USD": ["ethereum", "ether", "eth", "crypto", "cryptocurrency", "defi", "etf"],
})

# Specialized feeds — headlines already targeted, skip keyword filter
_SKIP_FILTER = {
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://news.kitco.com/rss/",
    "https://www.caixinglobal.com/rss/",
    "https://messari.io/rss",
    "https://insights.glassnode.com/rss/",
    "https://www.gold.org/rss",
    "https://think.ing.com/feed/",
    "https://libertystreeteconomics.newyorkfed.org/feed.xml",
}


def fetch_headlines(symbol: str, max_items: int = 15) -> list[str]:
    feeds    = FEEDS.get(symbol, [])
    keywords = KEYWORDS.get(symbol, [])
    headlines = []

    for url in feeds:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8)
            feed = feedparser.parse(resp.content)
            for entry in feed.entries:
                title = entry.get("title", "")
                if url in _SKIP_FILTER or any(kw in title.lower() for kw in keywords):
                    headlines.append(title)
                if len(headlines) >= max_items:
                    return headlines
        except Exception:
            continue

    # fallback: unfiltered headlines from first feed
    if not headlines and feeds:
        try:
            resp = requests.get(feeds[0], headers=HEADERS, timeout=8)
            feed = feedparser.parse(resp.content)
            headlines = [e.get("title", "") for e in feed.entries[:max_items]]
        except Exception:
            pass

    return headlines

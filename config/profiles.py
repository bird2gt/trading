"""
Single source of truth for trading rules: risk %, ATR stop/target multipliers,
and pip specs. One profile per asset group; per-pair overrides live inside the
group's `symbols` map. Both run_mt4 (live) and backtest_2w import from here.
"""

# One profile per group; `symbols` overrides the group defaults for individual pairs.
PROFILES = {
    "forex": {
        "risk_pct": 0.02, "sl_mult": 1.5, "tp_mult": 1.5,
        "symbols": {
            "GBP/USD": {"sl_mult": 2.0},   # шире ATR-стоп
            "USD/CAD": {"sl_mult": 2.0},   # 1.5/1.5≈безубыток → 2.0/1.5 плюс в обоих окнах (бэктест)
        },
    },
    "crypto": {
        "risk_pct": 0.01, "sl_mult": 1.0, "tp_mult": 1.5,
        "symbols": {},
    },
    "metal": {
        "risk_pct": 0.02, "sl_mult": 1.5, "tp_mult": 1.5,
        "symbols": {
            "XAG/USD": {"sl_mult": 2.0, "tp_mult": 2.0},   # серебро: шире стоп и цель
        },
    },
}

SYMBOL_GROUP = {
    "EUR/USD": "forex", "USD/CHF": "forex", "EUR/CHF": "forex", "AUD/USD": "forex",
    "GBP/USD": "forex", "USD/JPY": "forex", "USD/CAD": "forex",
    "BTC/USD": "crypto", "ETH/USD": "crypto",
    "XAU/USD": "metal",  "XAG/USD": "metal",
}

# pip_size = price per 1 pip; pip_value = USD per pip per standard lot
PIP_CONFIG = {
    "EUR/USD": {"pip_size": 0.0001, "pip_value": 10.0},
    "GBP/USD": {"pip_size": 0.0001, "pip_value": 10.0},
    "USD/CHF": {"pip_size": 0.0001, "pip_value": 10.0},
    "EUR/CHF": {"pip_size": 0.0001, "pip_value": 10.0},
    "USD/CAD": {"pip_size": 0.0001, "pip_value": 7.0},
    "AUD/USD": {"pip_size": 0.0001, "pip_value": 10.0},
    "USD/JPY": {"pip_size": 0.01,   "pip_value": 7.0},
    "BTC/USD": {"pip_size": 1.0,    "pip_value": 1.0},
    "ETH/USD": {"pip_size": 0.1,    "pip_value": 1.0},
    "XAU/USD": {"pip_size": 0.01,   "pip_value": 1.0},
    "XAG/USD": {"pip_size": 0.001,  "pip_value": 5.0},
}

MIN_LOTS = 0.01
MAX_LOTS = 1.0

_DEFAULT_RULES = {"risk_pct": 0.02, "sl_mult": 1.5, "tp_mult": 1.5}


def rules_for(symbol):
    """Group-level defaults merged with the pair's per-symbol override (if any)."""
    group = SYMBOL_GROUP.get(symbol)
    if group is None:
        return dict(_DEFAULT_RULES)
    p = PROFILES[group]
    rules = {"risk_pct": p["risk_pct"], "sl_mult": p["sl_mult"], "tp_mult": p["tp_mult"]}
    rules.update(p.get("symbols", {}).get(symbol, {}))
    return rules

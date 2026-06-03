#!/usr/bin/env python3
"""
Research the user's full MT4 universe for intraday tradability.

The script downloads Yahoo Finance OHLCV data through yfinance, builds 12m/6m
movement charts, and ranks instruments for same-day H4/H1/M15 trading using
volatility, daily range, trend strength, and a practical cost/liquidity factor.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
RUN_DATE = pd.Timestamp.now("UTC").strftime("%Y-%m-%d")
OUT_DIR = ROOT / "research" / f"intraday_universe_{RUN_DATE}"
DATA_DIR = OUT_DIR / "data"
CHART_DIR = OUT_DIR / "charts"


@dataclass(frozen=True)
class Instrument:
    no: int
    symbol: str
    yahoo: tuple[str, ...]
    group: str
    label: str = ""
    derived_from: tuple[str, str] | None = None

    @property
    def display(self) -> str:
        return self.label or self.symbol


INSTRUMENTS: list[Instrument] = [
    Instrument(1, "EURUSD", ("EURUSD=X",), "fx_major"),
    Instrument(2, "GBPUSD", ("GBPUSD=X",), "fx_major"),
    Instrument(3, "USDJPY", ("JPY=X", "USDJPY=X"), "fx_major"),
    Instrument(4, "USDCHF", ("CHF=X", "USDCHF=X"), "fx_major"),
    Instrument(5, "USDCAD", ("CAD=X", "USDCAD=X"), "fx_major"),
    Instrument(6, "AUDUSD", ("AUDUSD=X",), "fx_major"),
    Instrument(7, "EURGBP", ("EURGBP=X",), "fx_cross"),
    Instrument(8, "EURAUD", ("EURAUD=X",), "fx_cross"),
    Instrument(9, "EURCHF", ("EURCHF=X",), "fx_cross"),
    Instrument(10, "EURJPY", ("EURJPY=X",), "fx_cross"),
    Instrument(11, "EURNZD", ("EURNZD=X",), "fx_cross"),
    Instrument(12, "EURCAD", ("EURCAD=X",), "fx_cross"),
    Instrument(13, "GBPCHF", ("GBPCHF=X",), "fx_cross"),
    Instrument(14, "GBPJPY", ("GBPJPY=X",), "fx_cross"),
    Instrument(15, "GBPAUD", ("GBPAUD=X",), "fx_cross"),
    Instrument(16, "GBPCAD", ("GBPCAD=X",), "fx_cross"),
    Instrument(17, "GBPNZD", ("GBPNZD=X",), "fx_cross"),
    Instrument(18, "AUDNZD", ("AUDNZD=X",), "fx_cross"),
    Instrument(19, "AUDCAD", ("AUDCAD=X",), "fx_cross"),
    Instrument(20, "AUDCHF", ("AUDCHF=X",), "fx_cross"),
    Instrument(21, "AUDJPY", ("AUDJPY=X",), "fx_cross"),
    Instrument(22, "CADJPY", ("CADJPY=X",), "fx_cross"),
    Instrument(23, "CADCHF", ("CADCHF=X",), "fx_cross"),
    Instrument(24, "CHFJPY", ("CHFJPY=X",), "fx_cross"),
    Instrument(25, "NZDJPY", ("NZDJPY=X",), "fx_cross"),
    Instrument(26, "NZDUSD", ("NZDUSD=X",), "fx_cross"),
    Instrument(27, "NZDCAD", ("NZDCAD=X",), "fx_cross"),
    Instrument(28, "NZDCHF", ("NZDCHF=X",), "fx_cross"),
    Instrument(29, "XAUUSD", ("XAUUSD=X", "GC=F"), "metal", "XAUUSD"),
    Instrument(30, "XAGUSD", ("XAGUSD=X", "SI=F"), "metal", "XAGUSD"),
    Instrument(31, "XAUEUR", ("XAUEUR=X",), "metal", "XAUEUR", ("XAUUSD", "EURUSD")),
    Instrument(32, ".DE40C", ("^GDAXI",), "index", "DAX 40"),
    Instrument(33, ".JP225", ("^N225",), "index", "Nikkei 225"),
    Instrument(34, ".US500", ("^GSPC",), "index", "S&P 500"),
    Instrument(35, ".USTEC", ("^NDX",), "index", "Nasdaq 100"),
    Instrument(36, ".US30C", ("^DJI",), "index", "Dow Jones 30"),
    Instrument(37, "BRENT", ("BZ=F",), "energy", "BRENT"),
    Instrument(38, "WTI", ("CL=F",), "energy", "WTI"),
    Instrument(39, "BTCUSD", ("BTC-USD",), "crypto"),
    Instrument(40, "ETHUSD", ("ETH-USD",), "crypto"),
    Instrument(41, "SOLUSD", ("SOL-USD",), "crypto"),
    Instrument(42, "DOGEUSD", ("DOGE-USD",), "crypto"),
    Instrument(43, "ADAUSD", ("ADA-USD",), "crypto"),
    Instrument(44, "XRPUSD", ("XRP-USD",), "crypto"),
]


GROUP_NAMES = {
    "fx_major": "Forex major",
    "fx_cross": "Forex cross",
    "metal": "Metal",
    "index": "Index",
    "energy": "Energy",
    "crypto": "Crypto",
}

COST_FACTOR = {
    "fx_major": 1.00,
    "fx_cross": 0.84,
    "metal": 0.90,
    "index": 0.86,
    "energy": 0.82,
    "crypto": 0.76,
}


def safe_name(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", symbol).strip("_")


def all_tickers() -> list[str]:
    tickers: list[str] = []
    for inst in INSTRUMENTS:
        tickers.extend(inst.yahoo)
    return sorted(set(tickers))


def download_interval(period: str, interval: str, chunk_size: int = 12) -> dict[str, pd.DataFrame]:
    tickers = all_tickers()
    result: dict[str, pd.DataFrame] = {}
    for start in range(0, len(tickers), chunk_size):
        chunk = tickers[start : start + chunk_size]
        print(f"Downloading {interval} {period}: {', '.join(chunk)}", flush=True)
        raw = yf.download(
            tickers=" ".join(chunk),
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )
        for ticker in chunk:
            result[ticker] = clean_yf_frame(extract_ticker(raw, ticker))
        time.sleep(0.75)
    return result


def extract_ticker(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    if not isinstance(raw.columns, pd.MultiIndex):
        return raw.copy()

    levels = raw.columns.names
    level0 = raw.columns.get_level_values(0)
    level1 = raw.columns.get_level_values(1)

    if ticker in level0:
        return raw[ticker].copy()
    if ticker in level1:
        return raw.xs(ticker, axis=1, level=1).copy()

    # Single-ticker yfinance may return columns like ("Close", "EURUSD=X").
    if len(set(level1)) == 1 and ticker in set(level1):
        return raw.droplevel(1, axis=1).copy()
    if len(set(level0)) == 1 and levels[0] is None:
        return raw.droplevel(0, axis=1).copy()
    return pd.DataFrame()


def clean_yf_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
    if "close" not in out.columns and "adj_close" in out.columns:
        out["close"] = out["adj_close"]
    needed = ["open", "high", "low", "close"]
    if any(c not in out.columns for c in needed):
        return pd.DataFrame()
    if "volume" not in out.columns:
        out["volume"] = 0.0
    out = out[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    idx = pd.to_datetime(out.index, utc=True, errors="coerce")
    out.index = idx.tz_convert(None)
    out = out[~out.index.isna()]
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.astype(float)


def select_symbol_frame(inst: Instrument, frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, str]:
    for ticker in inst.yahoo:
        df = frames.get(ticker, pd.DataFrame())
        if not df.empty:
            return df.copy(), ticker
    if inst.derived_from:
        base_symbol, denom_symbol = inst.derived_from
        base_inst = instrument_by_symbol(base_symbol)
        denom_inst = instrument_by_symbol(denom_symbol)
        base_df, base_src = select_symbol_frame(base_inst, frames)
        denom_df, denom_src = select_symbol_frame(denom_inst, frames)
        derived = derive_ratio_frame(base_df, denom_df)
        if not derived.empty:
            return derived, f"{base_src}/{denom_src}"
    return pd.DataFrame(), ""


def instrument_by_symbol(symbol: str) -> Instrument:
    for inst in INSTRUMENTS:
        if inst.symbol == symbol:
            return inst
    raise KeyError(symbol)


def derive_ratio_frame(base: pd.DataFrame, denom: pd.DataFrame) -> pd.DataFrame:
    if base.empty or denom.empty:
        return pd.DataFrame()
    joined = pd.concat(
        {
            "b": base[["open", "high", "low", "close"]],
            "d": denom[["open", "high", "low", "close"]],
        },
        axis=1,
        join="inner",
    ).dropna()
    if joined.empty:
        return pd.DataFrame()
    out = pd.DataFrame(index=joined.index)
    out["open"] = joined[("b", "open")] / joined[("d", "open")]
    out["high"] = joined[("b", "high")] / joined[("d", "low")]
    out["low"] = joined[("b", "low")] / joined[("d", "high")]
    out["close"] = joined[("b", "close")] / joined[("d", "close")]
    out["volume"] = 0.0
    return out.dropna()


def resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    return (
        df.resample("4h", origin="epoch")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open", "high", "low", "close"])
    )


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    parts = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return parts.max(axis=1)


def atr_pct(df: pd.DataFrame, period: int = 14, months: int | None = None) -> float:
    if df.empty or len(df) < period + 5:
        return math.nan
    src = clip_months(df, months) if months else df
    if len(src) < period + 5:
        src = df
    atr = true_range(src).rolling(period).mean()
    pct = (atr / src["close"] * 100.0).replace([np.inf, -np.inf], np.nan).dropna()
    return float(pct.median()) if not pct.empty else math.nan


def adx_mean(df: pd.DataFrame, period: int = 14, months: int | None = None) -> float:
    if df.empty or len(df) < period * 3:
        return math.nan
    src = clip_months(df, months) if months else df
    if len(src) < period * 3:
        src = df

    up_move = src["high"].diff()
    down_move = -src["low"].diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=src.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=src.index)
    tr = true_range(src)

    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100.0
    adx = dx.ewm(alpha=alpha, adjust=False).mean().replace([np.inf, -np.inf], np.nan).dropna()
    return float(adx.tail(max(50, period)).mean()) if not adx.empty else math.nan


def clip_months(df: pd.DataFrame, months: int | None) -> pd.DataFrame:
    if df.empty or months is None:
        return df
    end = df.index.max()
    start = end - pd.DateOffset(months=months)
    return df[df.index >= start]


def period_change(df: pd.DataFrame, months: int) -> float:
    src = clip_months(df, months)
    if len(src) < 2:
        return math.nan
    return float((src["close"].iloc[-1] / src["close"].iloc[0] - 1.0) * 100.0)


def period_range(df: pd.DataFrame, months: int) -> float:
    src = clip_months(df, months)
    if len(src) < 2:
        return math.nan
    return float((src["high"].max() - src["low"].min()) / src["close"].iloc[-1] * 100.0)


def daily_range_metrics(df_h1: pd.DataFrame, months: int = 6) -> tuple[float, float]:
    src = clip_months(df_h1, months)
    if src.empty:
        return math.nan, math.nan
    tmp = src.copy()
    tmp["date"] = tmp.index.date
    daily = tmp.groupby("date").agg({"high": "max", "low": "min", "close": "last"})
    if daily.empty:
        return math.nan, math.nan
    rng = ((daily["high"] - daily["low"]) / daily["close"] * 100.0).replace([np.inf, -np.inf], np.nan).dropna()
    if rng.empty:
        return math.nan, math.nan
    return float(rng.median()), float(rng.quantile(0.90))


def data_factor(h1: pd.DataFrame, m15: pd.DataFrame) -> float:
    h1_factor = min(1.0, len(h1) / 1500.0) if not h1.empty else 0.0
    m15_factor = min(1.0, len(m15) / 1000.0) if not m15.empty else 0.75
    return max(0.35, 0.75 * h1_factor + 0.25 * m15_factor)


def classify(score: float) -> str:
    if score >= 67:
        return "A"
    if score >= 52:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def timeframe_hint(row: pd.Series) -> str:
    h4_adx = row.get("h4_adx_6m", math.nan)
    h1_adx = row.get("h1_adx_6m", math.nan)
    m15_atr = row.get("m15_atr_pct", math.nan)
    h1_atr = row.get("h1_atr_pct_6m", math.nan)

    parts: list[str] = []
    if not math.isnan(h4_adx) and h4_adx >= 24:
        parts.append("H4 regime")
    if not math.isnan(h1_adx) and h1_adx >= 22:
        parts.append("H1 entry")
    if not math.isnan(m15_atr) and not math.isnan(h1_atr) and m15_atr >= h1_atr / 3.2:
        parts.append("M15 timing")
    if not parts:
        parts.append("H1 only")
    return " + ".join(parts)


def session_hint(inst: Instrument) -> str:
    if inst.group in {"fx_major", "fx_cross"}:
        if "JPY" in inst.symbol:
            return "Tokyo open + London open; avoid dead NY afternoon"
        if any(ccy in inst.symbol for ccy in ("AUD", "NZD")):
            return "Asia/London transition + London/NY overlap"
        return "London + London/NY overlap"
    if inst.group == "metal":
        return "London metals + NY/CME"
    if inst.group == "index":
        if inst.symbol == ".JP225":
            return "Tokyo cash session"
        if inst.symbol == ".DE40C":
            return "Frankfurt/London open"
        return "US cash open + first 2h"
    if inst.group == "energy":
        return "London + NY energy session"
    if inst.group == "crypto":
        return "EU/US overlap; avoid thin weekend ranges"
    return ""


def pct_rank(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() == 0:
        return pd.Series(0.5, index=s.index)
    filled = s.fillna(s.median())
    return filled.rank(pct=True)


def compute_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    ranks = {
        "range": pct_rank(out["median_day_range_6m_pct"]),
        "p90": pct_rank(out["p90_day_range_6m_pct"]),
        "h1_atr": pct_rank(out["h1_atr_pct_6m"]),
        "m15_atr": pct_rank(out["m15_atr_pct"]),
        "h4_atr": pct_rank(out["h4_atr_pct_6m"]),
        "h4_adx": pct_rank(out["h4_adx_6m"]),
        "h1_adx": pct_rank(out["h1_adx_6m"]),
    }
    raw = (
        0.30 * ranks["range"]
        + 0.12 * ranks["p90"]
        + 0.18 * ranks["h1_atr"]
        + 0.12 * ranks["m15_atr"]
        + 0.10 * ranks["h4_atr"]
        + 0.10 * ranks["h4_adx"]
        + 0.08 * ranks["h1_adx"]
    )
    out["practical_factor"] = out["group"].map(COST_FACTOR).fillna(0.8) * out["data_factor"]
    out["opportunity_score"] = (100.0 * raw * out["practical_factor"]).round(1)
    out["rank"] = out["opportunity_score"].rank(ascending=False, method="first").astype(int)
    out["class"] = out["opportunity_score"].apply(classify)
    out["timeframe"] = out.apply(timeframe_hint, axis=1)
    return out.sort_values(["opportunity_score", "median_day_range_6m_pct"], ascending=False)


def save_svg_line_chart(df: pd.DataFrame, path: Path, title: str, subtitle: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 920, 360
    ml, mr, mt, mb = 62, 18, 48, 42
    chart_w, chart_h = width - ml - mr, height - mt - mb

    if df.empty or len(df) < 2:
        path.write_text(
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>"
            f"<rect width='100%' height='100%' fill='#fff'/><text x='24' y='42' "
            f"font-family='Arial' font-size='18'>{title}: no data</text></svg>",
            encoding="utf-8",
        )
        return

    close = df["close"].astype(float)
    normalized = close / close.iloc[0] * 100.0
    y_min = float(normalized.min())
    y_max = float(normalized.max())
    pad = max((y_max - y_min) * 0.10, 0.5)
    y_min -= pad
    y_max += pad

    xs = np.linspace(ml, ml + chart_w, len(normalized))
    ys = mt + (y_max - normalized.to_numpy()) / (y_max - y_min) * chart_h
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    color = "#1f77b4" if normalized.iloc[-1] >= normalized.iloc[0] else "#d62728"

    grid = []
    for i in range(5):
        val = y_min + (y_max - y_min) * i / 4
        y = mt + (y_max - val) / (y_max - y_min) * chart_h
        grid.append(
            f"<line x1='{ml}' y1='{y:.1f}' x2='{ml + chart_w}' y2='{y:.1f}' stroke='#e6e8eb'/>"
            f"<text x='12' y='{y + 4:.1f}' font-family='Arial' font-size='11' fill='#68707a'>{val:.1f}</text>"
        )

    start_label = df.index.min().strftime("%Y-%m-%d")
    end_label = df.index.max().strftime("%Y-%m-%d")
    change = normalized.iloc[-1] - 100.0

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#ffffff"/>
<text x="24" y="26" font-family="Arial" font-size="18" font-weight="700" fill="#101418">{title}</text>
<text x="24" y="44" font-family="Arial" font-size="12" fill="#68707a">{subtitle}; normalized close, start=100, change={change:+.1f}%</text>
{''.join(grid)}
<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt + chart_h}" stroke="#c8cdd2"/>
<line x1="{ml}" y1="{mt + chart_h}" x2="{ml + chart_w}" y2="{mt + chart_h}" stroke="#c8cdd2"/>
<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
<text x="{ml}" y="{height - 14}" font-family="Arial" font-size="11" fill="#68707a">{start_label}</text>
<text x="{ml + chart_w - 68}" y="{height - 14}" font-family="Arial" font-size="11" fill="#68707a">{end_label}</text>
<text x="{width - 128}" y="28" font-family="Arial" font-size="12" fill="{color}">{close.iloc[-1]:.5g}</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def save_svg_bar_chart(rows: pd.DataFrame, path: Path, title: str, value_col: str, suffix: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = rows.copy().head(15)
    width = 920
    row_h = 27
    height = 58 + row_h * len(rows) + 24
    ml, mr = 145, 56
    chart_w = width - ml - mr
    max_value = float(rows[value_col].max()) if not rows.empty else 1.0
    max_value = max(max_value, 1e-9)

    bars = []
    for idx, (_, row) in enumerate(rows.iterrows()):
        y = 58 + idx * row_h
        value = float(row[value_col])
        bar_w = chart_w * value / max_value
        bars.append(
            f"<text x='18' y='{y + 17}' font-family='Arial' font-size='12' fill='#222'>{row['symbol']}</text>"
            f"<rect x='{ml}' y='{y}' width='{chart_w}' height='17' fill='#eef1f4'/>"
            f"<rect x='{ml}' y='{y}' width='{bar_w:.1f}' height='17' fill='#2b7bbb'/>"
            f"<text x='{ml + bar_w + 8:.1f}' y='{y + 13}' font-family='Arial' font-size='11' fill='#222'>{value:.1f}{suffix}</text>"
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#ffffff"/>
<text x="24" y="30" font-family="Arial" font-size="18" font-weight="700" fill="#101418">{title}</text>
{''.join(bars)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def markdown_table(df: pd.DataFrame, columns: list[str], n: int | None = None) -> str:
    src = df.head(n) if n else df
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines = [header, sep]
    for _, row in src.iterrows():
        vals = []
        for col in columns:
            val = row[col]
            if isinstance(val, float):
                vals.append("" if math.isnan(val) else f"{val:.2f}")
            else:
                vals.append(str(val))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def build_report(summary: pd.DataFrame, failures: list[str], asof: str, sources: dict[str, dict[str, str]]) -> str:
    top = summary.sort_values("opportunity_score", ascending=False)
    fx = top[top["group"].isin(["fx_major", "fx_cross"])].head(12)
    non_fx = top[~top["group"].isin(["fx_major", "fx_cross"])].head(12)
    low = top.sort_values("opportunity_score").head(10)

    cols = [
        "rank",
        "symbol",
        "group_name",
        "class",
        "opportunity_score",
        "median_day_range_6m_pct",
        "h1_atr_pct_6m",
        "m15_atr_pct",
        "h4_adx_6m",
        "change_6m_pct",
        "timeframe",
    ]
    source_lines = []
    for symbol, by_interval in sources.items():
        compact = ", ".join(f"{k}:{v}" for k, v in by_interval.items() if v)
        if compact:
            source_lines.append(f"- {symbol}: {compact}")

    text = f"""# Intraday universe research ({asof})

Scope: 44 MT4 instruments from the user's list. Data source: Yahoo Finance via yfinance.
Daily charts cover roughly 12 months and 6 months. H4 is resampled from H1. M15 history is limited by Yahoo Finance and usually covers about 60 days.

Important: this is a tradability/volatility ranking, not a promise of profit. Broker spread, swaps, CFD session breaks, slippage, news filters, and execution quality must be checked in MT4 before enabling a symbol.

## Best overall for same-day trades

{markdown_table(top, cols, 15)}

## Best Forex candidates

{markdown_table(fx, cols, 12)}

## Best non-Forex candidates

{markdown_table(non_fx, cols, 12)}

## Lowest priority / avoid unless there is a special setup

{markdown_table(low, cols, 10)}

## How the score was built

- 30% median daily H1 range over the last 6 months.
- 12% 90th percentile daily H1 range over the last 6 months.
- 18% H1 ATR percent over the last 6 months.
- 12% M15 ATR percent over the last available M15 window.
- 10% H4 ATR percent over the last 6 months.
- 18% H4/H1 ADX trend strength.
- Multiplied by a practical factor for spread/liquidity and data coverage.

## Practical reading

- Class A: enough movement for H1 entries with H4 context; worth backtesting first.
- Class B: tradable when the session is active or there is a clean H4/H1 setup.
- Class C: secondary watchlist; often needs news/session catalyst.
- Class D: low priority for intraday automation unless broker spread is exceptionally good.

## Data sources used by symbol

{chr(10).join(source_lines)}

## Failed or incomplete symbols

{chr(10).join(f'- {x}' for x in failures) if failures else '- None'}

Generated files:

- `summary.csv`: full metric table.
- `charts/*_12m.svg` and `charts/*_6m.svg`: movement charts.
- `charts/top_15_score.svg`: top-score chart.
- `charts/top_15_range.svg`: top daily-range chart.
"""
    return text


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CHART_DIR.mkdir(parents=True, exist_ok=True)

    daily_by_ticker = download_interval("13mo", "1d")
    h1_by_ticker = download_interval("1y", "1h")
    m15_by_ticker = download_interval("60d", "15m")

    rows: list[dict[str, object]] = []
    failures: list[str] = []
    sources: dict[str, dict[str, str]] = {}
    last_dates: list[pd.Timestamp] = []

    daily_by_symbol: dict[str, pd.DataFrame] = {}
    h1_by_symbol: dict[str, pd.DataFrame] = {}
    h4_by_symbol: dict[str, pd.DataFrame] = {}
    m15_by_symbol: dict[str, pd.DataFrame] = {}

    for inst in INSTRUMENTS:
        daily, daily_src = select_symbol_frame(inst, daily_by_ticker)
        h1, h1_src = select_symbol_frame(inst, h1_by_ticker)
        m15, m15_src = select_symbol_frame(inst, m15_by_ticker)
        h4 = resample_4h(h1)

        daily_by_symbol[inst.symbol] = daily
        h1_by_symbol[inst.symbol] = h1
        h4_by_symbol[inst.symbol] = h4
        m15_by_symbol[inst.symbol] = m15
        sources[inst.symbol] = {"1d": daily_src, "1h": h1_src, "15m": m15_src}

        if daily.empty:
            failures.append(f"{inst.symbol}: no daily data")
            continue
        if h1.empty:
            failures.append(f"{inst.symbol}: no H1 data")
        if m15.empty:
            failures.append(f"{inst.symbol}: no M15 data")

        last_dates.append(daily.index.max())
        median_range, p90_range = daily_range_metrics(h1, months=6)
        row = {
            "no": inst.no,
            "symbol": inst.symbol,
            "display": inst.display,
            "group": inst.group,
            "group_name": GROUP_NAMES.get(inst.group, inst.group),
            "source_1d": daily_src,
            "source_1h": h1_src,
            "source_15m": m15_src,
            "last_daily_bar": daily.index.max().strftime("%Y-%m-%d"),
            "last_close": float(daily["close"].iloc[-1]),
            "change_12m_pct": period_change(daily, 12),
            "change_6m_pct": period_change(daily, 6),
            "range_12m_pct": period_range(daily, 12),
            "range_6m_pct": period_range(daily, 6),
            "median_day_range_6m_pct": median_range,
            "p90_day_range_6m_pct": p90_range,
            "daily_atr_pct_12m": atr_pct(daily, months=12),
            "h4_atr_pct_6m": atr_pct(h4, months=6),
            "h1_atr_pct_6m": atr_pct(h1, months=6),
            "m15_atr_pct": atr_pct(m15),
            "h4_adx_6m": adx_mean(h4, months=6),
            "h1_adx_6m": adx_mean(h1, months=6),
            "h1_bars": len(h1),
            "m15_bars": len(m15),
            "data_factor": data_factor(h1, m15),
            "session": session_hint(inst),
        }
        rows.append(row)

        daily.to_csv(DATA_DIR / f"{safe_name(inst.symbol)}_1d.csv", index_label="datetime")
        h1.to_csv(DATA_DIR / f"{safe_name(inst.symbol)}_1h.csv", index_label="datetime")
        h4.to_csv(DATA_DIR / f"{safe_name(inst.symbol)}_4h.csv", index_label="datetime")
        m15.to_csv(DATA_DIR / f"{safe_name(inst.symbol)}_15m.csv", index_label="datetime")

    if not rows:
        raise SystemExit("No data downloaded.")

    summary = compute_scores(pd.DataFrame(rows))
    summary = summary.sort_values("rank")
    summary.to_csv(OUT_DIR / "summary.csv", index=False)

    for _, row in summary.iterrows():
        symbol = row["symbol"]
        daily = daily_by_symbol[symbol]
        inst = instrument_by_symbol(symbol)
        save_svg_line_chart(
            clip_months(daily, 12),
            CHART_DIR / f"{safe_name(symbol)}_12m.svg",
            f"{symbol} 12m",
            GROUP_NAMES.get(inst.group, inst.group),
        )
        save_svg_line_chart(
            clip_months(daily, 6),
            CHART_DIR / f"{safe_name(symbol)}_6m.svg",
            f"{symbol} 6m",
            GROUP_NAMES.get(inst.group, inst.group),
        )

    save_svg_bar_chart(
        summary.sort_values("opportunity_score", ascending=False),
        CHART_DIR / "top_15_score.svg",
        "Top 15 intraday opportunity score",
        "opportunity_score",
    )
    save_svg_bar_chart(
        summary.sort_values("median_day_range_6m_pct", ascending=False),
        CHART_DIR / "top_15_range.svg",
        "Top 15 median daily H1 range, 6m",
        "median_day_range_6m_pct",
        "%",
    )

    asof = max(last_dates).strftime("%Y-%m-%d") if last_dates else RUN_DATE
    report = build_report(summary, failures, asof, sources)
    (OUT_DIR / "report.md").write_text(report, encoding="utf-8")
    print(f"Done: {OUT_DIR}", flush=True)
    print(summary[["rank", "symbol", "group_name", "class", "opportunity_score", "median_day_range_6m_pct", "h1_atr_pct_6m", "m15_atr_pct", "h4_adx_6m", "change_6m_pct"]].head(20).to_string(index=False))


if __name__ == "__main__":
    main()

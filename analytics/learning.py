"""
Learning reports for the MT4 bot.

This module is intentionally advisory: it reads closed trades, writes a JSON
recommendation file, and saves a human-readable report. Live trading rules are
not changed automatically.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Iterable

from config.profiles import SYMBOL_GROUP

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "forecasts" / "journal.db"
FILTERS_PATH = ROOT / "config" / "learned_filters.json"
REPORT_DIR = ROOT / "forecasts"

MIN_SYMBOL_TRADES = 20
MIN_SEGMENT_TRADES = 8
WATCH_TRADES = 8

MT4_SYMBOL_ALIASES = {
    "BTCUSD": "BTC/USD",
    "ETHUSD": "ETH/USD",
    "XAUUSD": "XAU/USD",
    "XAGUSD": "XAG/USD",
    "NZDCHF": "NZD/CHF",
    "AUDCHF": "AUD/CHF",
    "NZDJPY": "NZD/JPY",
    "NZDCAD": "NZD/CAD",
    "US500CASH": "US500",
    "US500": "US500",
    "DE40CASH": "DE40",
    "DE40C": "DE40",
    "DE40": "DE40",
    "JP225CASH": "JP225",
    "JP225": "JP225",
    "USTECCASH": "USTEC",
    "USTEC": "USTEC",
    "BRENT": "BRENT",
    "WTI": "WTI",
}


@dataclass(frozen=True)
class Trade:
    ticket: int
    symbol: str
    side: str
    lots: float
    open_price: float
    close_price: float
    open_time: datetime | None
    close_time: datetime | None
    sl: float
    tp: float
    profit: float
    swap: float
    comment: str

    @property
    def gross_profit(self) -> float:
        return self.profit + self.swap

    @property
    def session(self) -> str:
        if self.open_time is None:
            return "unknown"
        hour = self.open_time.hour
        if hour < 8 or hour >= 22:
            return "asian"
        if hour < 12 or (hour == 12 and self.open_time.minute < 30):
            return "london"
        if hour < 21:
            return "us"
        return "rollover"

    @property
    def weekday(self) -> str:
        if self.open_time is None:
            return "unknown"
        return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][self.open_time.weekday()]

    @property
    def realized_r(self) -> float | None:
        risk = abs(self.open_price - self.sl)
        if risk <= 0 or not math.isfinite(risk):
            return None
        move = self.close_price - self.open_price
        if self.side.upper() == "SELL":
            move = -move
        return move / risk


def run_learning(today: date | None = None) -> dict:
    """Generate advisory learned filters and a markdown report."""
    today = today or date.today()
    trades = load_trades()
    payload = build_recommendations(trades)
    write_filters(payload)
    report_path = write_report(today, payload)
    print(f"Learning report saved -> {report_path}")
    print(f"Learned filters saved -> {FILTERS_PATH}")
    return payload


def load_trades(db_path: Path = DB_PATH) -> list[Trade]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT ticket, symbol, side, lots, open_price, close_price,
                   open_time, close_time, sl, tp, profit, swap, comment
            FROM trades
            WHERE profit IS NOT NULL
            ORDER BY open_time, ticket
            """
        ).fetchall()
    finally:
        conn.close()

    trades: list[Trade] = []
    for row in rows:
        try:
            trades.append(
                Trade(
                    ticket=int(row[0]),
                    symbol=normalize_symbol(str(row[1])),
                    side=str(row[2]).upper(),
                    lots=float(row[3]),
                    open_price=float(row[4]),
                    close_price=float(row[5]),
                    open_time=parse_mt4_time(row[6]),
                    close_time=parse_mt4_time(row[7]),
                    sl=float(row[8]),
                    tp=float(row[9]),
                    profit=float(row[10]),
                    swap=float(row[11] or 0.0),
                    comment=str(row[12] or ""),
                )
            )
        except Exception:
            continue
    return trades


def build_recommendations(trades: list[Trade]) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "mode": "recommendations_only",
        "generated_at": generated_at,
        "min_symbol_trades": MIN_SYMBOL_TRADES,
        "min_segment_trades": MIN_SEGMENT_TRADES,
        "summary": summarize(trades),
        "symbols": {},
    }

    for symbol in sorted({t.symbol for t in trades}):
        symbol_trades = [t for t in trades if t.symbol == symbol]
        metrics = metrics_for(symbol_trades)
        session_metrics = compact_segments(
            {
                session: metrics_for([t for t in symbol_trades if t.session == session])
                for session in ("asian", "london", "us", "rollover", "unknown")
            }
        )
        side_metrics = compact_segments(
            {
                side: metrics_for([t for t in symbol_trades if t.side == side])
                for side in ("BUY", "SELL")
            }
        )
        weekday_metrics = compact_segments(
            {
                weekday: metrics_for([t for t in symbol_trades if t.weekday == weekday])
                for weekday in ("mon", "tue", "wed", "thu", "fri", "sat", "sun", "unknown")
            }
        )

        recommendation = recommend_symbol(metrics, session_metrics, side_metrics)
        payload["symbols"][symbol] = {
            "asset_group": SYMBOL_GROUP.get(symbol, "unknown"),
            "metrics": metrics,
            "sessions": session_metrics,
            "sides": side_metrics,
            "weekdays": weekday_metrics,
            "recommendation": recommendation,
        }

    return payload


def summarize(trades: list[Trade]) -> dict:
    metrics = metrics_for(trades)
    return {
        "trades": metrics["trades"],
        "net_profit": metrics["net_profit"],
        "expectancy": metrics["expectancy"],
        "win_rate": metrics["win_rate"],
        "profit_factor": metrics["profit_factor"],
        "avg_realized_r": metrics["avg_realized_r"],
    }


def compact_segments(segments: dict[str, dict]) -> dict[str, dict]:
    return {name: data for name, data in segments.items() if data["trades"] > 0}


def metrics_for(trades: Iterable[Trade]) -> dict:
    rows = list(trades)
    profits = [t.gross_profit for t in rows]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]
    r_values = [t.realized_r for t in rows if t.realized_r is not None]
    net = sum(profits)
    pf = None
    if losses:
        pf = abs(sum(wins) / sum(losses)) if wins else 0.0
    elif wins:
        pf = None
    return {
        "trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "net_profit": round(net, 2),
        "expectancy": round(net / len(rows), 2) if rows else 0.0,
        "win_rate": round(len(wins) / len(rows) * 100, 1) if rows else 0.0,
        "avg_win": round(mean(wins), 2) if wins else 0.0,
        "avg_loss": round(mean(losses), 2) if losses else 0.0,
        "profit_factor": round(pf, 2) if pf is not None else None,
        "avg_realized_r": round(mean(r_values), 2) if r_values else None,
    }


def recommend_symbol(metrics: dict, sessions: dict[str, dict], sides: dict[str, dict]) -> dict:
    n = metrics["trades"]
    expectancy = metrics["expectancy"]
    pf = metrics["profit_factor"]

    status = "insufficient_data"
    reason = f"Need at least {MIN_SYMBOL_TRADES} closed trades for a hard decision."
    recommended_disabled = False

    if n >= MIN_SYMBOL_TRADES:
        if expectancy < 0 and (pf is not None and pf < 0.9):
            status = "review_disable"
            reason = "Negative expectancy with weak profit factor on a sufficient sample."
            recommended_disabled = True
        elif expectancy > 0 and (pf is None or pf >= 1.1):
            status = "keep"
            reason = "Positive expectancy on a sufficient sample."
        else:
            status = "watch"
            reason = "Mixed result on a sufficient sample."
    elif n >= WATCH_TRADES:
        status = "watch"
        reason = "Sample is still small, but large enough to watch."

    allowed_sessions = []
    avoid_sessions = []
    for name, sm in sessions.items():
        if name == "unknown" or sm["trades"] < MIN_SEGMENT_TRADES:
            continue
        if sm["expectancy"] > 0 and (sm["profit_factor"] is None or sm["profit_factor"] >= 1.05):
            allowed_sessions.append(name)
        if sm["expectancy"] < 0 and sm["win_rate"] < 45:
            avoid_sessions.append(name)

    preferred_sides = []
    avoid_sides = []
    for side, sm in sides.items():
        if sm["trades"] < MIN_SEGMENT_TRADES:
            continue
        if sm["expectancy"] > 0 and (sm["profit_factor"] is None or sm["profit_factor"] >= 1.05):
            preferred_sides.append(side)
        if sm["expectancy"] < 0 and sm["win_rate"] < 45:
            avoid_sides.append(side)

    return {
        "status": status,
        "reason": reason,
        "disabled": False,
        "recommended_disabled": recommended_disabled,
        "allowed_sessions": allowed_sessions,
        "avoid_sessions": avoid_sessions,
        "preferred_sides": preferred_sides,
        "avoid_sides": avoid_sides,
    }


def write_filters(payload: dict, path: Path = FILTERS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_report(today: date, payload: dict) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"{today.isoformat()}_learning.md"
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def render_report(payload: dict) -> str:
    lines = [
        "# Learning report",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "Mode: recommendations_only. The bot does not apply these filters automatically.",
        "",
        "## Summary",
        "",
        format_metrics(payload["summary"]),
        "",
        "## Symbol recommendations",
        "",
    ]

    ranked = sorted(
        payload["symbols"].items(),
        key=lambda item: (
            -item[1]["metrics"]["trades"],
            item[0],
        ),
    )
    for symbol, data in ranked:
        m = data["metrics"]
        if m["trades"] == 0:
            continue
        rec = data["recommendation"]
        lines.extend(
            [
                f"### {symbol}",
                "",
                format_metrics(m),
                f"Status: {rec['status']} - {rec['reason']}",
                f"Recommended disabled: {rec['recommended_disabled']}",
                f"Allowed sessions: {', '.join(rec['allowed_sessions']) or '-'}",
                f"Avoid sessions: {', '.join(rec['avoid_sessions']) or '-'}",
                f"Preferred sides: {', '.join(rec['preferred_sides']) or '-'}",
                f"Avoid sides: {', '.join(rec['avoid_sides']) or '-'}",
                "",
                "| Segment | Trades | Net | Exp | WR | PF |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for name, sm in data["sessions"].items():
            if sm["trades"]:
                lines.append(format_segment(name, sm))
        for side, sm in data["sides"].items():
            if sm["trades"]:
                lines.append(format_segment(side, sm))
        lines.append("")

    if all(data["metrics"]["trades"] == 0 for data in payload["symbols"].values()):
        lines.append("No closed trades yet.")
        lines.append("")

    return "\n".join(lines)


def format_metrics(m: dict) -> str:
    pf = "-" if m["profit_factor"] is None else f"{m['profit_factor']:.2f}"
    avg_r = "-" if m["avg_realized_r"] is None else f"{m['avg_realized_r']:.2f}R"
    return (
        f"Trades: {m['trades']} | Net: ${m['net_profit']:+.2f} | "
        f"Expectancy: ${m['expectancy']:+.2f} | Win rate: {m['win_rate']:.1f}% | "
        f"PF: {pf} | Avg R: {avg_r}"
    )


def format_segment(name: str, m: dict) -> str:
    pf = "-" if m["profit_factor"] is None else f"{m['profit_factor']:.2f}"
    return (
        f"| {name} | {m['trades']} | ${m['net_profit']:+.2f} | "
        f"${m['expectancy']:+.2f} | {m['win_rate']:.1f}% | {pf} |"
    )


def normalize_symbol(symbol: str) -> str:
    raw = symbol.strip().upper().replace(".", "")
    if raw in MT4_SYMBOL_ALIASES:
        return MT4_SYMBOL_ALIASES[raw]
    for known in SYMBOL_GROUP:
        if known.replace("/", "").upper() == raw:
            return known
    return symbol.strip()


def parse_mt4_time(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


if __name__ == "__main__":
    run_learning()

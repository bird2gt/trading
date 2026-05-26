"""
Trade journal — syncs closed trades from MT4 EA into SQLite.

Usage:
    from analytics.journal import sync, stats
    sync()   # pull new trades from bridge
    stats()  # print summary to console
"""

from __future__ import annotations
import sqlite3
from pathlib import Path
import requests

BRIDGE_URL = "http://127.0.0.1:8000"
DB_PATH    = Path(__file__).parent.parent / "forecasts" / "journal.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            ticket      INTEGER PRIMARY KEY,
            symbol      TEXT,
            side        TEXT,
            lots        REAL,
            open_price  REAL,
            close_price REAL,
            open_time   TEXT,
            close_time  TEXT,
            sl          REAL,
            tp          REAL,
            profit      REAL,
            swap        REAL,
            comment     TEXT
        )
    """)
    conn.commit()
    return conn


def sync() -> int:
    """Fetch trades from bridge, insert new ones. Returns count of new rows."""
    try:
        rows = requests.get(f"{BRIDGE_URL}/trades", timeout=5).json()
    except Exception as e:
        print(f"[journal] sync failed: {e}")
        return 0

    conn = _connect()
    new = 0
    for r in rows:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO trades
                (ticket, symbol, side, lots, open_price, close_price,
                 open_time, close_time, sl, tp, profit, swap, comment)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                int(r["ticket"]),
                r["symbol"],
                r["side"],
                float(r["lots"]),
                float(r["open_price"]),
                float(r["close_price"]),
                r["open_time"],
                r["close_time"],
                float(r["sl"]),
                float(r["tp"]),
                float(r["profit"]),
                float(r["swap"]),
                r.get("comment", ""),
            ))
            if conn.execute("SELECT changes()").fetchone()[0]:
                new += 1
        except Exception:
            continue
    conn.commit()
    conn.close()
    if new:
        print(f"[journal] +{new} new trade(s) synced")
    return new


def stats() -> None:
    conn = _connect()
    rows = conn.execute(
        "SELECT symbol, side, profit FROM trades WHERE profit IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        print("[journal] no closed trades yet")
        return

    total   = len(rows)
    wins    = [p for _, _, p in rows if p > 0]
    losses  = [p for _, _, p in rows if p <= 0]
    net_pnl = sum(p for _, _, p in rows)

    win_rate = len(wins) / total * 100
    avg_win  = sum(wins)   / len(wins)   if wins   else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    pf = abs(sum(wins) / sum(losses)) if losses else float("inf")

    print(f"\n{'─'*40}")
    print(f"  Trade Journal  ({total} trades)")
    print(f"{'─'*40}")
    print(f"  Net P&L:      ${net_pnl:+.2f}")
    print(f"  Win rate:     {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Avg win:      ${avg_win:.2f}   Avg loss: ${avg_loss:.2f}")
    print(f"  Profit factor: {pf:.2f}")

    by_symbol: dict[str, list[float]] = {}
    for sym, _, p in rows:
        by_symbol.setdefault(sym, []).append(p)
    print()
    for sym, profits in sorted(by_symbol.items()):
        w = sum(1 for p in profits if p > 0)
        print(f"  {sym:10s}  {len(profits):3d} trades  "
              f"{w/len(profits)*100:.0f}% WR  ${sum(profits):+.2f}")
    print(f"{'─'*40}\n")


if __name__ == "__main__":
    sync()
    stats()

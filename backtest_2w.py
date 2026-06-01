"""
Two-week walk-forward simulation.
Forex: ZScoreAdx (pullback to EMA200 in ADX trend)
Metals + Crypto: SMACross 5/20
Matches live bot: signal on closed H4 bars (df_h4.iloc[:-1])
"""
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.sma_cross import SMACross
from strategy.forex.z_score_adx import ZScoreAdx
from strategy.structure import market_structure, fib_tp

ATR_PERIOD   = 14
ATR_TP1_MULT = 1.5

SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/CHF", "USD/JPY",
    "AUD/USD", "EUR/CHF", "USD/CAD",
    "XAU/USD", "XAG/USD",
    "BTC/USD", "ETH/USD",
]

FOREX_SYMBOLS = {
    "EUR/USD", "GBP/USD", "USD/CHF", "EUR/CHF",
    "AUD/USD", "USD/JPY", "USD/CAD",
}

STRATEGY_FOREX = ZScoreAdx(
    z_period=20, z_entry=2.0,
    adx_period=14, ema_period=200, adx_threshold=25.0,
)
STRATEGY_OTHER = SMACross(fast=5, slow=20)

TWO_WEEKS_H4 = 84
WARMUP_H4    = 250
TOTAL_H4     = TWO_WEEKS_H4 + WARMUP_H4

INITIAL_BALANCE = 10_000.0
RISK_PCT = 0.02

PIP_CONFIG = {
    "EUR/USD": {"pip_size": 0.0001, "pip_value": 10.0},
    "GBP/USD": {"pip_size": 0.0001, "pip_value": 10.0},
    "USD/CHF": {"pip_size": 0.0001, "pip_value": 10.0},
    "EUR/CHF": {"pip_size": 0.0001, "pip_value": 10.0},
    "USD/JPY": {"pip_size": 0.01,   "pip_value": 7.0},
    "USD/CAD": {"pip_size": 0.0001, "pip_value": 7.0},
    "AUD/USD": {"pip_size": 0.0001, "pip_value": 10.0},
    "XAU/USD": {"pip_size": 0.01,   "pip_value": 1.0},
    "XAG/USD": {"pip_size": 0.001,  "pip_value": 5.0},
    "BTC/USD": {"pip_size": 1.0,    "pip_value": 1.0},
    "ETH/USD": {"pip_size": 0.1,    "pip_value": 1.0},
}

SL_MULT = {
    "EUR/USD": 1.5, "USD/CHF": 1.5, "EUR/CHF": 1.5,
    "AUD/USD": 1.5, "USD/CAD": 1.5,
    "GBP/USD": 2.0,
    "USD/JPY": 1.5,
    "XAU/USD": 1.0, "XAG/USD": 1.0,
    "BTC/USD": 1.0, "ETH/USD": 1.0,
}


def _atr_series(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lot_size(entry: float, sl: float, symbol: str, balance: float) -> float:
    cfg = PIP_CONFIG.get(symbol, {"pip_size": 0.0001, "pip_value": 10.0})
    sl_pips = abs(entry - sl) / cfg["pip_size"]
    if sl_pips == 0:
        return 0.01
    lots = balance * RISK_PCT / (sl_pips * cfg["pip_value"])
    return max(0.01, min(2.0, round(lots, 2)))


def _pnl(entry: float, exit_: float, direction: int, lots: float, symbol: str) -> float:
    cfg = PIP_CONFIG.get(symbol, {"pip_size": 0.0001, "pip_value": 10.0})
    pips = (exit_ - entry) * direction / cfg["pip_size"]
    return round(pips * cfg["pip_value"] * lots, 2)


def backtest_symbol(symbol: str, df_h4: pd.DataFrame, df_d1: pd.DataFrame) -> list[dict]:
    atr      = _atr_series(df_h4)
    sl_mult  = SL_MULT.get(symbol, 1.5)
    strategy = STRATEGY_FOREX if symbol in FOREX_SYMBOLS else STRATEGY_OTHER
    trades   = []
    in_trade = False
    balance  = INITIAL_BALANCE
    start_i  = len(df_h4) - TWO_WEEKS_H4

    for i in range(start_i, len(df_h4)):
        bar_time = df_h4.index[i]

        # ── exit check ───────────────────────────────────────────────────────
        if in_trade:
            h = df_h4["high"].iloc[i]
            l = df_h4["low"].iloc[i]
            hit_sl = (direction ==  1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction ==  1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                exit_p = tp if hit_tp else sl
                pnl = _pnl(entry_price, exit_p, direction, lots, symbol)
                balance += pnl
                trades.append({
                    "symbol":  symbol,
                    "entry_t": entry_t,
                    "exit_t":  bar_time,
                    "dir":     "BUY" if direction == 1 else "SELL",
                    "entry":   entry_price,
                    "exit":    exit_p,
                    "sl":      sl,
                    "tp":      tp,
                    "lots":    lots,
                    "pnl":     pnl,
                    "result":  "WIN" if hit_tp else "LOSS",
                    "balance": round(balance, 2),
                })
                in_trade = False
            continue

        # ── signal on closed bars only (iloc[:i]) ────────────────────────────
        if i == 0:
            continue
        df_closed = df_h4.iloc[:i]
        bar_date  = df_h4.index[i - 1].date()
        df_d1_sl  = df_d1[df_d1.index.date <= bar_date]

        if symbol in FOREX_SYMBOLS:
            signal = strategy.generate_signal(df_closed)
        else:
            signal = strategy.generate_signal(
                df_closed,
                df_trend=df_d1_sl if len(df_d1_sl) >= 55 else None,
            )

        if signal == 0:
            continue

        # market structure filter (forex only — ZScoreAdx already has EMA200 filter)
        if symbol not in FOREX_SYMBOLS:
            struct = market_structure(df_closed)
            if signal == 1 and struct == -1:
                continue
            if signal == -1 and struct == 1:
                continue

        entry_price = df_h4["close"].iloc[i - 1]
        atr_val     = atr.iloc[i - 1]
        if pd.isna(atr_val) or atr_val == 0:
            continue

        sl = (entry_price - sl_mult * atr_val if signal == 1
              else entry_price + sl_mult * atr_val)

        # TP: Fib 1.272 for non-forex, ATR 1:1 for forex (mean-reversion, closer target)
        if symbol in FOREX_SYMBOLS:
            tp = (entry_price + ATR_TP1_MULT * atr_val if signal == 1
                  else entry_price - ATR_TP1_MULT * atr_val)
        else:
            tp_fib = fib_tp(df_closed, signal, level=1.272)
            tp = tp_fib if tp_fib else (
                entry_price + ATR_TP1_MULT * atr_val if signal == 1
                else entry_price - ATR_TP1_MULT * atr_val
            )

        lots      = _lot_size(entry_price, sl, symbol, balance)
        direction = signal
        entry_t   = bar_time
        in_trade  = True

    return trades


def main():
    print(f"2-week simulation  Forex=ZScoreAdx  Metals/Crypto=SMACross\n"
          f"({TWO_WEEKS_H4} H4 bars + {WARMUP_H4} warmup,  $10k balance,  2% risk/trade)\n")

    data = {}
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        try:
            df_h4 = fetch_ohlcv(sym, outputsize=TOTAL_H4 + 1, interval="4h")
            df_d1 = fetch_ohlcv(sym, outputsize=TOTAL_H4 // 4, interval="1day")
            data[sym] = (df_h4, df_d1)
            window_start = df_h4.index[-TWO_WEEKS_H4].date()
            strat = "ZScoreAdx" if sym in FOREX_SYMBOLS else "SMACross "
            print(f"ok  [{strat}]  {len(df_h4)} bars, window from {window_start}")
        except Exception as e:
            print(f"FAIL — {e}")
        time.sleep(1)

    print()
    all_trades = []
    for sym, (df_h4, df_d1) in data.items():
        if len(df_h4) < WARMUP_H4 + 10:
            print(f"{sym}: not enough data, skipping")
            continue
        trades = backtest_symbol(sym, df_h4, df_d1)
        all_trades.extend(trades)

    if not all_trades:
        print("No trades in the 2-week window.")
        return

    df = pd.DataFrame(all_trades)

    # ── per-symbol summary ───────────────────────────────────────────────────
    print(f"{'Symbol':<10} {'Strat':<11} {'Tr':>3} {'W':>3} {'L':>3} {'Win%':>6} {'PnL $':>9}")
    print("─" * 52)
    for sym in SYMBOLS:
        sub = df[df["symbol"] == sym]
        strat = "ZScoreAdx" if sym in FOREX_SYMBOLS else "SMACross"
        if sub.empty:
            print(f"{sym:<10} {strat:<11} {'–':>3}")
            continue
        w = (sub["pnl"] > 0).sum()
        l = len(sub) - w
        print(f"{sym:<10} {strat:<11} {len(sub):>3} {w:>3} {l:>3} "
              f"{w/len(sub)*100:>5.0f}% {sub['pnl'].sum():>+9.2f}")

    total = len(df)
    wins  = (df["pnl"] > 0).sum()
    pnl   = df["pnl"].sum()
    print("─" * 52)
    print(f"{'TOTAL':<10} {'':<11} {total:>3} {wins:>3} {total-wins:>3} "
          f"{wins/total*100:>5.0f}% {pnl:>+9.2f}")
    print(f"\nReturn on $10k: {pnl/INITIAL_BALANCE*100:+.1f}%   "
          f"Avg trade: {pnl/total:+.2f}$")

    # ── trade log ────────────────────────────────────────────────────────────
    print(f"\n{'#':<3} {'Symbol':<10} {'Dir':<5} {'Date':<12} "
          f"{'Entry':>9} {'Exit':>9} {'Lots':>5} {'PnL $':>9}  Result")
    print("─" * 70)
    for n, t in enumerate(all_trades, 1):
        print(f"{n:<3} {t['symbol']:<10} {t['dir']:<5} {str(t['entry_t'].date()):<12} "
              f"{t['entry']:>9.4f} {t['exit']:>9.4f} {t['lots']:>5.2f} "
              f"{t['pnl']:>+9.2f}  {t['result']}")

    # ── equity by strategy type ──────────────────────────────────────────────
    forex_df = df[df["symbol"].isin(FOREX_SYMBOLS)]
    other_df = df[~df["symbol"].isin(FOREX_SYMBOLS)]
    if len(forex_df):
        fw = (forex_df["pnl"] > 0).sum()
        print(f"\nForex  (ZScoreAdx): {len(forex_df)} trades, "
              f"win {fw/len(forex_df)*100:.0f}%, PnL {forex_df['pnl'].sum():+.2f}$")
    if len(other_df):
        ow = (other_df["pnl"] > 0).sum()
        print(f"Other  (SMACross ): {len(other_df)} trades, "
              f"win {ow/len(other_df)*100:.0f}%, PnL {other_df['pnl'].sum():+.2f}$")


if __name__ == "__main__":
    main()

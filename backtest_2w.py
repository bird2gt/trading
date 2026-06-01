"""
Two-week walk-forward simulation.
Forex:   Forex profile strategy — ZScoreAdx(adx≥25, z≥2.0)
Metals:  MetalsSession profile — XAU ZScoreAdxTrend, XAG Silver+GSR
Crypto:  Crypto profile strategy — BreakoutADX(adx≥25, rising≥5)
Signal on closed H4 bars only (df_h4.iloc[:-1]) — no repaint.
"""
import time
import pandas as pd
from history.fetcher import fetch_ohlcv
from strategy.crypto import Crypto
from strategy.forex import Forex
from strategy.metals import MetalsSession
from strategy.sma_cross import SMACross  # exit MA only, not used for signals

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
CRYPTO_SYMBOLS = {"BTC/USD", "ETH/USD"}

STRATEGY_FOREX = Forex(
    z_period=20, z_entry=2.0,
    adx_period=14, adx_threshold=25.0,
)
STRATEGY_METALS_XAU = MetalsSession("XAUUSD")
STRATEGY_METALS_XAG = MetalsSession("XAGUSD")
STRATEGY_CRYPTO = Crypto(
    period=20, adx_period=14, adx_threshold=25.0,
    vol_ma=20, vol_mult=1.2, adx_rising_bars=5,
)

ATR_PERIOD   = 14
TWO_WEEKS_H4 = 84
WARMUP_H4    = 250
TOTAL_H4     = TWO_WEEKS_H4 + WARMUP_H4
INITIAL_BALANCE = 10_000.0
RISK_PCT        = 0.02

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
    "AUD/USD": 1.5, "USD/CAD": 1.5, "GBP/USD": 2.0,
    "USD/JPY": 1.5, "XAU/USD": 1.5, "XAG/USD": 2.0,
    "BTC/USD": 1.0, "ETH/USD": 1.0,
}
TP_MULT = {
    "XAG/USD": 2.0,
}
DEFAULT_TP_MULT = 1.5


def _atr_series(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lot_size(entry: float, sl: float, symbol: str, balance: float) -> float:
    cfg = PIP_CONFIG.get(symbol, {"pip_size": 0.0001, "pip_value": 10.0})
    sl_pips = abs(entry - sl) / cfg["pip_size"]
    if sl_pips == 0:
        return 0.01
    return max(0.01, min(2.0, round(balance * RISK_PCT / (sl_pips * cfg["pip_value"]), 2)))


def _pnl(entry: float, exit_: float, direction: int, lots: float, symbol: str) -> float:
    cfg = PIP_CONFIG.get(symbol, {"pip_size": 0.0001, "pip_value": 10.0})
    pips = (exit_ - entry) * direction / cfg["pip_size"]
    return round(pips * cfg["pip_value"] * lots, 2)


def backtest_symbol(symbol: str, df_h4: pd.DataFrame, df_xau_h4: pd.DataFrame | None = None) -> list[dict]:
    if symbol in FOREX_SYMBOLS:
        strategy = STRATEGY_FOREX
    elif symbol in CRYPTO_SYMBOLS:
        strategy = STRATEGY_CRYPTO
    elif symbol == "XAG/USD":
        strategy = STRATEGY_METALS_XAG
    else:
        strategy = STRATEGY_METALS_XAU
    sl_mult  = SL_MULT.get(symbol, 1.5)
    tp_mult  = TP_MULT.get(symbol, DEFAULT_TP_MULT)
    atr      = _atr_series(df_h4)
    trades   = []
    in_trade = False
    balance  = INITIAL_BALANCE
    start_i  = max(WARMUP_H4, len(df_h4) - TWO_WEEKS_H4)

    for i in range(start_i, len(df_h4)):
        bar_time = df_h4.index[i]

        if in_trade:
            h = df_h4["high"].iloc[i]
            l = df_h4["low"].iloc[i]
            hit_sl = (direction ==  1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction ==  1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                exit_p = tp if hit_tp else sl
                pnl    = _pnl(entry_price, exit_p, direction, lots, symbol)
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

        if i == 0:
            continue
        df_closed = df_h4.iloc[:i]  # closed bars only — no repaint
        if symbol == "XAG/USD" and df_xau_h4 is not None:
            xau_closed = df_xau_h4[df_xau_h4.index <= df_closed.index[-1]]
            signal = strategy.generate_signal(df_closed, df_xau=xau_closed)
        else:
            signal = strategy.generate_signal(df_closed, symbol=symbol)
        if signal == 0:
            continue

        entry_price = df_h4["close"].iloc[i - 1]
        atr_val     = atr.iloc[i - 1]
        if pd.isna(atr_val) or atr_val == 0:
            continue

        sl = (entry_price - sl_mult * atr_val if signal == 1
              else entry_price + sl_mult * atr_val)
        tp = (entry_price + tp_mult * atr_val if signal == 1
              else entry_price - tp_mult * atr_val)

        lots      = _lot_size(entry_price, sl, symbol, balance)
        direction = signal
        entry_t   = bar_time
        in_trade  = True

    return trades


def main():
    print("2-week walk-forward simulation\n"
          "Forex: Forex profile  Metals: MetalsSession profile  Crypto: Crypto profile\n"
          f"$10k balance · 2% risk/trade · "
          f"{TWO_WEEKS_H4} H4 bars + {WARMUP_H4} warmup\n")

    data = {}
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        try:
            df_h4 = fetch_ohlcv(sym, outputsize=TOTAL_H4 + 1, interval="4h")
            data[sym] = df_h4
            wstart = df_h4.index[-TWO_WEEKS_H4].date()
            if sym in FOREX_SYMBOLS:
                tag = "ZScoreAdx(25/2.0)"
            elif sym in CRYPTO_SYMBOLS:
                tag = "BreakoutADX(25/r5)"
            else:
                tag = "MetalsSession"
            print(f"ok  [{tag}]  window from {wstart}")
        except Exception as e:
            print(f"FAIL — {e}")
        time.sleep(1)

    all_trades = []
    df_xau_h4 = data.get("XAU/USD")
    for sym, df_h4 in data.items():
        if len(df_h4) < WARMUP_H4 + 10:
            print(f"{sym}: not enough data, skipping")
            continue
        all_trades.extend(backtest_symbol(sym, df_h4, df_xau_h4=df_xau_h4))

    if not all_trades:
        print("\nNo trades.")
        return

    df = pd.DataFrame(all_trades)
    forex_df = df[df["symbol"].isin(FOREX_SYMBOLS)]

    # ── per-symbol table ─────────────────────────────────────────────────────
    print(f"\n{'Symbol':<10} {'Strategy':<20} {'Tr':>3} {'W':>3} {'L':>3} {'Win%':>6} {'PnL $':>9}")
    print("─" * 58)
    for sym in SYMBOLS:
        sub  = df[df["symbol"] == sym]
        if sym in FOREX_SYMBOLS:
            tag = "ZScoreAdx(25/2.0)"
        elif sym in CRYPTO_SYMBOLS:
            tag = "BreakoutADX(25/r5)"
        else:
            tag = "MetalsSession"
        if sub.empty:
            print(f"{sym:<10} {tag:<20} {'–':>3}")
            continue
        w = (sub["pnl"] > 0).sum()
        l = len(sub) - w
        print(f"{sym:<10} {tag:<20} {len(sub):>3} {w:>3} {l:>3} "
              f"{w/len(sub)*100:>5.0f}% {sub['pnl'].sum():>+9.2f}")

    total = len(df)
    wins  = (df["pnl"] > 0).sum()
    pnl   = df["pnl"].sum()
    print("─" * 58)
    print(f"{'TOTAL':<10} {'':<20} {total:>3} {wins:>3} {total-wins:>3} "
          f"{wins/total*100:>5.0f}% {pnl:>+9.2f}")
    print(f"\nReturn on $10k: {pnl/INITIAL_BALANCE*100:+.1f}%   "
          f"Avg trade: {pnl/total:+.2f}$   Max loss: {df['pnl'].min():+.2f}$")

    # ── by group ─────────────────────────────────────────────────────────────
    crypto_df = df[df["symbol"].isin(CRYPTO_SYMBOLS)]
    metals_df = df[~df["symbol"].isin(FOREX_SYMBOLS) & ~df["symbol"].isin(CRYPTO_SYMBOLS)]
    if len(forex_df):
        fw = (forex_df["pnl"] > 0).sum()
        print(f"\nForex  ZScoreAdx(25/2.0):  {len(forex_df):>2} trades  "
              f"{fw/len(forex_df)*100:.0f}% win  {forex_df['pnl'].sum():>+8.2f}$")
    if len(crypto_df):
        cw = (crypto_df["pnl"] > 0).sum()
        print(f"Crypto BreakoutADX(25/r5): {len(crypto_df):>2} trades  "
              f"{cw/len(crypto_df)*100:.0f}% win  {crypto_df['pnl'].sum():>+8.2f}$")
    if len(metals_df):
        mw = (metals_df["pnl"] > 0).sum()
        print(f"Metals MetalsSession:      {len(metals_df):>2} trades  "
              f"{mw/len(metals_df)*100:.0f}% win  {metals_df['pnl'].sum():>+8.2f}$")

    # ── trade log ────────────────────────────────────────────────────────────
    print(f"\n{'#':<3} {'Symbol':<10} {'Dir':<5} {'Date':<12} "
          f"{'Entry':>9} {'Exit':>9} {'Lots':>5} {'PnL $':>9}  Result")
    print("─" * 70)
    for n, t in enumerate(all_trades, 1):
        print(f"{n:<3} {t['symbol']:<10} {t['dir']:<5} {str(t['entry_t'].date()):<12} "
              f"{t['entry']:>9.4f} {t['exit']:>9.4f} {t['lots']:>5.2f} "
              f"{t['pnl']:>+9.2f}  {t['result']}")

    # ── equity curve ─────────────────────────────────────────────────────────
    print(f"\nEquity ($10k base):")
    cum = 0.0
    for t in all_trades:
        cum += t["pnl"]
        bar  = ("▲" if t["pnl"] > 0 else "▼") + "█" * min(int(abs(t["pnl"]) / 50), 20)
        print(f"  {t['symbol']:<10} {t['dir']:<5} {str(t['entry_t'].date()):<12} "
              f"{cum:>+9.0f}$  {bar}")


if __name__ == "__main__":
    main()

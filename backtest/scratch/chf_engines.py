"""
Engine bake-off on USD/CHF & EUR/CHF for the week of Mon 2026-06-01.
Same backtest mechanics as live (H4, R:R 1.5/1.5 ATR, 2% risk), but swap the
engine to see if a trend engine would have caught the move the live profiles missed.
"""
import inspect
import pandas as pd
from history.fetcher import fetch_ohlcv
from config.profiles import PIP_CONFIG
from strategy.forex.take_profit import AdxMa, TwoB
from strategy.forex.breakout_adx import BreakoutAdx
from strategy.forex.z_score_adx import ZScoreAdx
from strategy.forex.ema_psar_trend import EmaPsarTrend

ATR_PERIOD = 14
WARMUP = 250
RISK_PCT = 0.02
BALANCE = 10_000.0
SL_MULT = TP_MULT = 1.5
WINDOW = pd.Timestamp("2026-06-01")


def _atr(df):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _lots(entry, sl, sym):
    cfg = PIP_CONFIG[sym]
    sl_pips = abs(entry - sl) / cfg["pip_size"]
    return max(0.01, min(1.0, round(BALANCE * RISK_PCT / (sl_pips * cfg["pip_value"]), 2)))


def _pnl(entry, exit_, direction, lots, sym):
    cfg = PIP_CONFIG[sym]
    pips = (exit_ - entry) * direction / cfg["pip_size"]
    return round(pips * cfg["pip_value"] * lots, 2)


def _sig(engine, sub, sym):
    """Call generate_signal handling the two signatures in this codebase."""
    if "symbol" in inspect.signature(engine.generate_signal).parameters or \
       any(p.kind == p.VAR_KEYWORD for p in inspect.signature(engine.generate_signal).parameters.values()):
        try:
            return engine.generate_signal(sub, symbol=sym)
        except TypeError:
            return engine.generate_signal(sub)
    return engine.generate_signal(sub)


def run(sym, df, atr, engine):
    in_trade = False
    entry = sl = tp = lots = direction = None
    trades, log = [], []
    for i in range(WARMUP, len(df)):
        t = df.index[i]
        if in_trade:
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            hit_sl = (direction == 1 and l <= sl) or (direction == -1 and h >= sl)
            hit_tp = (direction == 1 and h >= tp) or (direction == -1 and l <= tp)
            if hit_tp or hit_sl:
                px = tp if hit_tp else sl
                pnl = _pnl(entry, px, direction, lots, sym)
                trades.append(pnl)
                log.append(f"    EXIT {t}  {'TP' if hit_tp else 'SL'} @ {px:.5f}  ${pnl:+.0f}")
                in_trade = False
            continue
        if t < WINDOW:
            continue
        sig = _sig(engine, df.iloc[:i], sym)
        if sig == 0:
            continue
        entry = df["close"].iloc[i - 1]
        a = atr.iloc[i - 1]
        if pd.isna(a) or a == 0:
            continue
        sl = entry - SL_MULT * a if sig == 1 else entry + SL_MULT * a
        tp = entry + TP_MULT * a if sig == 1 else entry - TP_MULT * a
        lots = _lots(entry, sl, sym)
        direction = sig
        in_trade = True
        log.append(f"    ENTRY {t}  {'LONG' if sig==1 else 'SHORT'} @ {entry:.5f}  "
                   f"SL {sl:.5f} TP {tp:.5f} lots {lots}")
    open_upnl = None
    if in_trade:
        cur = df['close'].iloc[-1]
        open_upnl = _pnl(entry, cur, direction, lots, sym)
        log.append(f"    OPEN still in @ {df.index[-1]} mark {cur:.5f} unreal ${open_upnl:+.0f}")
    return trades, open_upnl, log


ENGINES = {
    "BreakoutAdx(30) [LIVE USD/CHF]": BreakoutAdx(period=30, adx_period=14, adx_threshold=20.0, adx_rising_bars=3),
    "ZScoreAdx [LIVE EUR/CHF]": ZScoreAdx(z_period=20, z_entry=2.0, adx_period=14, adx_threshold=25.0, z_signal_period=3),
    "TwoB(20) [trend, GBP/AUD]": TwoB(lookback=20),
    "AdxMa(21) [trend, EUR/USD]": AdxMa(ma_period=21, adx_period=14, adx_threshold=20.0),
    "EmaPsarTrend": EmaPsarTrend(),
}

for sym in ["USD/CHF", "EUR/CHF"]:
    df = fetch_ohlcv(sym, interval="4h", outputsize=2600)
    atr = _atr(df)
    print(f"\n{'='*70}\n{sym}   (week of {WINDOW.date()}, {len(df[df.index>=WINDOW])} H4 bars)\n{'='*70}")
    for name, eng in ENGINES.items():
        trades, upnl, log = run(sym, df, atr, eng)
        realized = sum(trades)
        total = realized + (upnl or 0)
        tag = f"  realized ${realized:+.0f}"
        if upnl is not None:
            tag += f" + open ${upnl:+.0f} = ${total:+.0f}"
        if not trades and upnl is None:
            tag = "  no entries"
        print(f"\n  {name}:{tag}")
        for line in log:
            print(line)

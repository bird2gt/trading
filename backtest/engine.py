import pandas as pd
from strategy.base import BaseStrategy


def run(df: pd.DataFrame, strategy: BaseStrategy, initial_balance: float = 10_000.0) -> dict:
    balance = initial_balance
    trades = []

    position = 0
    entry_price = 0.0

    for i in range(50, len(df)):
        window = df.iloc[:i]
        signal = strategy.generate_signal(window)

        price = df["close"].iloc[i]

        if position == 0 and signal != 0:
            position = signal
            entry_price = price

        elif position != 0 and signal == -position:
            pnl = (price - entry_price) * position
            balance += pnl
            trades.append({"entry": entry_price, "exit": price, "pnl": pnl, "balance": balance})
            position = 0
            entry_price = 0.0

    total_pnl = balance - initial_balance
    wins = [t for t in trades if t["pnl"] > 0]

    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0,
        "total_pnl": round(total_pnl, 2),
        "final_balance": round(balance, 2),
    }

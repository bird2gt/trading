import time
from config.settings import SYMBOLS
from history.fetcher import fetch_ohlcv
from strategy.sma_cross import SMACross
from broker import bybit_client
from risk.manager import lot_size, is_drawdown_ok

STRATEGY = SMACross(fast=20, slow=50)
POLL_INTERVAL = 60  # seconds


def main():
    print("Starting live trading (Bybit Testnet)")
    start_balance = bybit_client.get_balance("USDT")
    print(f"Starting balance: {start_balance:.2f} USDT")

    while True:
        for symbol in SYMBOLS:
            df = fetch_ohlcv(symbol, outputsize=100)
            signal = STRATEGY.generate_signal(df)

            if signal == 0:
                print(f"{symbol}: no signal")
                continue

            balance = bybit_client.get_balance("USDT")
            if not is_drawdown_ok(start_balance, balance):
                print("Max drawdown reached, skipping")
                continue

            entry = df["close"].iloc[-1]
            sl = entry * (1 - 0.02) if signal == 1 else entry * (1 + 0.02)
            volume = lot_size(balance, entry, sl)

            if volume > 0:
                result = bybit_client.open_order(symbol, signal, volume, sl)
                print(f"{symbol}: signal={'BUY' if signal == 1 else 'SELL'}, qty={volume}, entry={entry:.2f}, orderId={result.get('orderId')}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()

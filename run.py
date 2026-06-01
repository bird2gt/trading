import time
import importlib
from config.settings import PROFILES
from history.fetcher import fetch_ohlcv
from broker import bybit_client
from risk.manager import lot_size, is_drawdown_ok

POLL_INTERVAL = 60  # seconds


def load_strategy(profile_name, asset_class, strategy_name, strategy_params):
    """Load strategy class and instantiate with params."""
    try:
        module = importlib.import_module(f"strategy.{asset_class}.{strategy_name}")
        strategy_class = getattr(module, _camelize(strategy_name))
        return strategy_class(**strategy_params)
    except (ImportError, AttributeError) as e:
        print(f"Warning: failed to load strategy {asset_class}/{strategy_name}: {e}")
        return None


def _camelize(name):
    """Convert snake_case to CamelCase."""
    return ''.join(w.capitalize() for w in name.split('_'))


def main():
    print("Starting live trading (Bybit Testnet)")
    start_balance = bybit_client.get_balance("USDT")
    print(f"Starting balance: {start_balance:.2f} USDT")

    # Load strategies for enabled profiles
    strategies = {}
    for profile_name, profile in PROFILES.items():
        if not profile["enabled"]:
            continue
        strategy = load_strategy(
            profile_name,
            profile_name,
            profile["strategy"],
            profile["strategy_params"],
        )
        if strategy:
            strategies[profile_name] = strategy
            print(f"Loaded {profile_name}: {profile['strategy']} with {profile['strategy_params']}")

    if not strategies:
        print("No strategies loaded, exiting")
        return

    while True:
        for profile_name, strategy in strategies.items():
            profile = PROFILES[profile_name]
            for symbol in profile["symbols"]:
                df = fetch_ohlcv(symbol, outputsize=250)
                if df is None or df.empty:
                    print(f"{symbol}: no data")
                    continue

                signal = strategy.generate_signal(df)
                if signal == 0:
                    print(f"{symbol}: no signal")
                    continue

                balance = bybit_client.get_balance("USDT")
                if not is_drawdown_ok(start_balance, balance):
                    print("Max drawdown reached, skipping")
                    continue

                entry = df["close"].iloc[-1]
                sl_pct = profile["risk_params"].get("sl_pct", 0.02)
                sl = entry * (1 - sl_pct) if signal == 1 else entry * (1 + sl_pct)
                volume = lot_size(balance, entry, sl)

                if volume > 0:
                    result = bybit_client.open_order(symbol, signal, volume, sl)
                    print(f"[{profile_name}] {symbol}: signal={'BUY' if signal == 1 else 'SELL'}, qty={volume}, entry={entry:.2f}, SL={sl:.2f}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()

import hashlib
import hmac
import time
import requests
from config.settings import BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET

BASE_URL = "https://api-testnet.bybit.com" if BYBIT_TESTNET else "https://api.bybit.com"

# Bybit linear perpetual symbols differ from our internal "BTC/USD" notation
_BYBIT_SYMBOL_MAP = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
}

def _bybit_symbol(symbol: str) -> str:
    return _BYBIT_SYMBOL_MAP.get(symbol, symbol.replace("/", ""))


def _sign(params: dict) -> dict:
    ts = str(int(time.time() * 1000))
    recv_window = "5000"
    param_str = ts + BYBIT_API_KEY + recv_window + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    signature = hmac.new(BYBIT_API_SECRET.encode(), param_str.encode(), hashlib.sha256).hexdigest()
    return {
        "X-BAPI-API-KEY": BYBIT_API_KEY,
        "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-RECV-WINDOW": recv_window,
        "X-BAPI-SIGN": signature,
    }


def _get(path: str, params: dict = {}) -> dict:
    headers = _sign(params)
    resp = requests.get(BASE_URL + path, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data["retCode"] != 0:
        raise RuntimeError(f"Bybit error: {data['retMsg']}")
    return data["result"]


def _post(path: str, body: dict) -> dict:
    ts = str(int(time.time() * 1000))
    recv_window = "5000"
    import json
    body_str = json.dumps(body)
    param_str = ts + BYBIT_API_KEY + recv_window + body_str
    signature = hmac.new(BYBIT_API_SECRET.encode(), param_str.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY": BYBIT_API_KEY,
        "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-RECV-WINDOW": recv_window,
        "X-BAPI-SIGN": signature,
        "Content-Type": "application/json",
    }
    resp = requests.post(BASE_URL + path, json=body, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data["retCode"] != 0:
        raise RuntimeError(f"Bybit error: {data['retMsg']}")
    return data["result"]


def get_balance(coin: str = "USDT") -> float:
    result = _get("/v5/account/wallet-balance", {"accountType": "UNIFIED", "coin": coin})
    for account in result["list"]:
        for c in account["coin"]:
            if c["coin"] == coin:
                return float(c["walletBalance"])
    return 0.0


def open_order(symbol: str, direction: int, qty: float, sl: float = 0, tp: float = 0) -> dict:
    side = "Buy" if direction == 1 else "Sell"
    body = {
        "category": "linear",
        "symbol": _bybit_symbol(symbol),
        "side": side,
        "orderType": "Market",
        "qty": str(qty),
        "positionIdx": 0,  # one-way mode
    }
    if sl > 0:
        body["stopLoss"] = str(sl)
    if tp > 0:
        body["takeProfit"] = str(tp)
    return _post("/v5/order/create", body)


def get_positions(symbol: str = "") -> list:
    params = {"category": "linear"}
    if symbol:
        params["symbol"] = _bybit_symbol(symbol)
    return _get("/v5/position/list", params).get("list", [])


def close_position(symbol: str) -> dict:
    bsym = _bybit_symbol(symbol)
    positions = get_positions(symbol)
    for pos in positions:
        if float(pos.get("size", 0)) == 0:
            continue
        side = "Sell" if pos["side"] == "Buy" else "Buy"
        return _post("/v5/order/create", {
            "category": "linear",
            "symbol": bsym,
            "side": side,
            "orderType": "Market",
            "qty": pos["size"],
            "positionIdx": 0,
            "reduceOnly": True,
        })
    return {}

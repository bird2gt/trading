import hashlib
import hmac
import time
import requests
from config.settings import BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET

BASE_URL = "https://api-testnet.bybit.com" if BYBIT_TESTNET else "https://api.bybit.com"


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


def open_order(symbol: str, direction: int, qty: float, sl: float = 0) -> dict:
    side = "Buy" if direction == 1 else "Sell"
    body = {
        "category": "spot",
        "symbol": symbol.replace("/", ""),
        "side": side,
        "orderType": "Market",
        "qty": str(qty),
    }
    if sl > 0:
        body["stopLoss"] = str(sl)
    return _post("/v5/order/create", body)


def get_positions(symbol: str = "") -> list:
    params = {"category": "linear"}
    if symbol:
        params["symbol"] = symbol.replace("/", "")
    return _get("/v5/position/list", params).get("list", [])


def close_position(symbol: str) -> dict:
    positions = get_positions(symbol)
    for pos in positions:
        if float(pos["size"]) == 0:
            continue
        direction = -1 if pos["side"] == "Buy" else 1
        return open_order(symbol, direction, float(pos["size"]))
    return {}

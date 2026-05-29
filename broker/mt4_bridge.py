from pathlib import Path
import os
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel
import csv
import uvicorn

app = FastAPI()

BRIDGE_TOKEN = os.environ.get("MT4_BRIDGE_TOKEN", "")


def _verify_token(authorization: str = Header(default="")):
    if BRIDGE_TOKEN and authorization != f"Bearer {BRIDGE_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


MT4_FILES_DIR = Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader4/drive_c/Program Files (x86)/MetaTrader 4/MQL4/Files"

_signals: dict[str, dict] = {}


class Signal(BaseModel):
    symbol: str
    action: str  # BUY, SELL, CLOSE, NONE
    lots: float = 0.01
    sl: float = 0.0
    tp: float = 0.0


def _write_signal_file(symbol: str, action: str, lots: float, sl: float, tp: float):
    MT4_FILES_DIR.mkdir(parents=True, exist_ok=True)
    path = MT4_FILES_DIR / f"signal_{symbol}.txt"
    path.write_text(f"{action},{lots},{sl},{tp}")


@app.get("/signal")
def get_signal(symbol: str = "EURUSD"):
    return _signals.get(symbol, {"symbol": symbol, "action": "NONE", "lots": 0.01})


@app.post("/signal")
def set_signal(signal: Signal, _=Depends(_verify_token)):
    _signals[signal.symbol] = signal.model_dump()
    _write_signal_file(signal.symbol, signal.action, signal.lots, signal.sl, signal.tp)
    return {"ok": True}


@app.get("/signals")
def list_signals():
    return _signals


def write_signal(symbol: str, action: str, lots: float = 0.01, sl: float = 0.0, tp: float = 0.0):
    _signals[symbol] = {"symbol": symbol, "action": action, "lots": lots, "sl": sl, "tp": tp}
    _write_signal_file(symbol, action, lots, sl, tp)


@app.get("/balance")
def get_balance():
    path = MT4_FILES_DIR / "balance.txt"
    try:
        return {"balance": float(path.read_text().strip())}
    except Exception:
        return {"balance": None}


@app.get("/account")
def get_account():
    path = MT4_FILES_DIR / "account_info.txt"
    try:
        info = {}
        for line in path.read_text().strip().splitlines():
            k, v = line.split("=", 1)
            info[k] = v
        info["balance"] = float(info["balance"])
        info["equity"]  = float(info["equity"])
        info["leverage"] = int(info["leverage"])
        return info
    except Exception:
        return {}


@app.get("/positions")
def get_positions():
    path = MT4_FILES_DIR / "positions.txt"
    result = []
    try:
        for line in path.read_text().strip().splitlines():
            if not line:
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                result.append({"symbol": parts[0], "action": parts[1], "open_price": float(parts[2])})
    except Exception:
        pass
    return result


@app.get("/trades")
def get_trades():
    rows = []
    for path in MT4_FILES_DIR.glob("trades_*.csv"):
        try:
            with path.open(encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows.extend(list(reader))
        except Exception:
            pass
    return rows


def run_server(host: str = "0.0.0.0", port: int = 8000):
    uvicorn.run(app, host=host, port=port, log_level="warning")

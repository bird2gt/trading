from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

app = FastAPI()

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
def set_signal(signal: Signal):
    _signals[signal.symbol] = signal.model_dump()
    _write_signal_file(signal.symbol, signal.action, signal.lots, signal.sl, signal.tp)
    return {"ok": True}


@app.get("/signals")
def list_signals():
    return _signals


def write_signal(symbol: str, action: str, lots: float = 0.01, sl: float = 0.0, tp: float = 0.0):
    _signals[symbol] = {"symbol": symbol, "action": action, "lots": lots, "sl": sl, "tp": tp}
    _write_signal_file(symbol, action, lots, sl, tp)


def run_server(host: str = "0.0.0.0", port: int = 8000):
    uvicorn.run(app, host=host, port=port, log_level="warning")

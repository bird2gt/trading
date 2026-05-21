from config.settings import MAX_RISK_PER_TRADE, MAX_DRAWDOWN


def lot_size(balance: float, entry: float, stop_loss: float, contract_size: float = 1.0) -> float:
    risk_amount = balance * MAX_RISK_PER_TRADE
    pip_risk = abs(entry - stop_loss)
    if pip_risk == 0:
        return 0.0
    return round(risk_amount / (pip_risk * contract_size), 2)


def is_drawdown_ok(balance: float, equity: float) -> bool:
    drawdown = (balance - equity) / balance
    return drawdown < MAX_DRAWDOWN

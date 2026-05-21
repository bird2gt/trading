#property strict
#property description "Reads signal from file written by Python bridge"

input double LotSize        = 0.01;
input int    PollSeconds    = 5;
input int    Slippage       = 3;
input int    TrailPips      = 20;  // trailing distance in pips
input int    TrailStartPips = 10;  // min profit (pips) before trailing starts

string lastAction = "NONE";
int    pipFactor  = 1;


int OnInit() {
    pipFactor = (Digits == 5 || Digits == 3) ? 10 : 1;
    EventSetTimer(PollSeconds);
    return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
    EventKillTimer();
}

void OnTimer() {
    TrailOrders();
    ReadSignal();
}

void OnTick() {}


// ── signal file reader ─────────────────────────────────────────────────────

void ReadSignal() {
    string filename = "signal_" + Symbol() + ".txt";
    int fh = FileOpen(filename, FILE_READ | FILE_TXT | FILE_ANSI);
    if (fh == INVALID_HANDLE) return;

    string line = FileReadString(fh);
    FileClose(fh);
    if (StringLen(line) == 0) return;

    // format: ACTION,lots,sl,tp
    string parts[];
    int n = StringSplit(line, ',', parts);

    string action = parts[0];
    double lots = (n > 1) ? StringToDouble(parts[1]) : LotSize;
    double sl   = (n > 2) ? StringToDouble(parts[2]) : 0.0;
    double tp   = (n > 3) ? StringToDouble(parts[3]) : 0.0;
    if (lots <= 0) lots = LotSize;

    if (action == lastAction) return;

    if (action == "BUY") {
        CloseAll(OP_SELL);
        if (CountOrders(OP_BUY) == 0) OpenOrder(OP_BUY, lots, sl, tp);
    } else if (action == "SELL") {
        CloseAll(OP_BUY);
        if (CountOrders(OP_SELL) == 0) OpenOrder(OP_SELL, lots, sl, tp);
    } else if (action == "CLOSE") {
        CloseAll(-1);
    }

    lastAction = action;
    Print("Signal applied: ", action, " lots=", lots, " SL=", sl, " TP=", tp);
}


// ── trailing stop ──────────────────────────────────────────────────────────

void TrailOrders() {
    double trail = TrailPips      * pipFactor * Point;
    double start = TrailStartPips * pipFactor * Point;

    for (int i = 0; i < OrdersTotal(); i++) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderSymbol() != Symbol()) continue;

        if (OrderType() == OP_BUY) {
            double profit = Bid - OrderOpenPrice();
            if (profit < start) continue;
            double newSL = Bid - trail;
            if (newSL > OrderStopLoss() + Point)
                OrderModify(OrderTicket(), OrderOpenPrice(), NormalizeDouble(newSL, Digits),
                            OrderTakeProfit(), 0, clrYellow);
        }

        if (OrderType() == OP_SELL) {
            double profit = OrderOpenPrice() - Ask;
            if (profit < start) continue;
            double newSL = Ask + trail;
            if (OrderStopLoss() == 0 || newSL < OrderStopLoss() - Point)
                OrderModify(OrderTicket(), OrderOpenPrice(), NormalizeDouble(newSL, Digits),
                            OrderTakeProfit(), 0, clrYellow);
        }
    }
}


// ── helpers ────────────────────────────────────────────────────────────────

void OpenOrder(int type, double lots, double sl, double tp) {
    double price = (type == OP_BUY) ? Ask : Bid;
    int ticket = OrderSend(Symbol(), type, lots, price, Slippage, sl, tp,
                           "SignalBridge", 0, 0,
                           (type == OP_BUY) ? clrBlue : clrRed);
    if (ticket < 0) Print("OrderSend error: ", GetLastError());
}

void CloseAll(int type) {
    for (int i = OrdersTotal() - 1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderSymbol() != Symbol()) continue;
        if (type != -1 && OrderType() != type) continue;
        double price = (OrderType() == OP_BUY) ? Bid : Ask;
        if (!OrderClose(OrderTicket(), OrderLots(), price, Slippage, clrWhite))
            Print("OrderClose error: ", GetLastError());
    }
}

int CountOrders(int type) {
    int n = 0;
    for (int i = 0; i < OrdersTotal(); i++) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderSymbol() == Symbol() && OrderType() == type) n++;
    }
    return n;
}

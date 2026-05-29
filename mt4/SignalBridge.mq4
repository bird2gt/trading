#property strict
#property description "Reads signal from file written by Python bridge"

input double LotSize             = 0.01;
input int    PollSeconds         = 5;
input int    Slippage            = 3;
// Breakeven (for calm pairs: EUR/USD, USD/CHF)
input bool   UseBreakeven        = true;
input double BreakevenATRMult    = 1.0;   // move SL to entry after X ATR profit
// Chandelier trailing — H4 bar close only
input int    ChandelierATRPeriod = 14;
input double ChandelierATRMult   = 2.0;   // SL = highest_high - X*ATR

string   lastAction   = "NONE";
int      pipFactor    = 1;
datetime s_lastBarTime = 0;
double   s_highestHigh = 0;
double   s_lowestLow   = 0;


int OnInit() {
    pipFactor = (Digits == 5 || Digits == 3) ? 10 : 1;
    EventSetTimer(PollSeconds);
    return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }

void OnTimer() {
    PartialClose();
    ChandelierTrail();
    ReadSignal();
    WriteBalance();
    WritePositions();
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

    string parts[];
    int n = StringSplit(line, ',', parts);

    string action = parts[0];
    double lots   = (n > 1) ? StringToDouble(parts[1]) : LotSize;
    double sl     = (n > 2) ? StringToDouble(parts[2]) : 0.0;
    double tp1    = (n > 3) ? StringToDouble(parts[3]) : 0.0;
    if (lots <= 0) lots = LotSize;

    // CLOSE must retry until flat — don't let the lastAction guard suppress it
    // (e.g. an OrderClose rejected near market close would otherwise never retry)
    if (action == "CLOSE") {
        if (CountOrders(OP_BUY) > 0 || CountOrders(OP_SELL) > 0) {
            CloseAll(-1);
            _resetChandelier();
            Print("Signal applied: CLOSE");
        }
        lastAction = action;
        return;
    }

    if (action == lastAction) return;

    if (action == "BUY") {
        CloseAll(OP_SELL);
        if (CountOrders(OP_BUY) == 0) { _resetChandelier(); OpenOrder(OP_BUY, lots, sl, tp1); }
    } else if (action == "SELL") {
        CloseAll(OP_BUY);
        if (CountOrders(OP_SELL) == 0) { _resetChandelier(); OpenOrder(OP_SELL, lots, sl, tp1); }
    }

    lastAction = action;
    Print("Signal applied: ", action, " lots=", lots, " SL=", sl, " TP1=", tp1);
}


// ── partial close at TP1 ───────────────────────────────────────────────────

void PartialClose() {
    for (int i = OrdersTotal() - 1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderSymbol() != Symbol()) continue;
        if (StringFind(OrderComment(), "SB_partial") >= 0) continue;

        double tp = OrderTakeProfit();
        if (tp == 0) continue;

        bool hitTP1 = (OrderType() == OP_BUY  && Bid >= tp) ||
                      (OrderType() == OP_SELL && Ask <= tp);
        if (!hitTP1) continue;

        double halfLots = NormalizeDouble(OrderLots() / 2.0, 2);
        if (halfLots < MarketInfo(Symbol(), MODE_MINLOT)) continue;

        double price = (OrderType() == OP_BUY) ? Bid : Ask;
        if (OrderClose(OrderTicket(), halfLots, price, Slippage, clrGold)) {
            if (OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
                OrderModify(OrderTicket(), OrderOpenPrice(), OrderStopLoss(), 0, 0, clrYellow);
            Print("Partial close 50% at TP1=", tp, " — chandelier takes over");
        }
    }
}


// ── chandelier trailing (H4 bar close) + breakeven (tick) ─────────────────

void ChandelierTrail() {
    bool   hasOrders      = false;
    double atr            = iATR(Symbol(), PERIOD_H4, ChandelierATRPeriod, 1);
    datetime currentBar   = iTime(Symbol(), PERIOD_H4, 0);
    bool   newBar         = (currentBar != s_lastBarTime);
    if (newBar) s_lastBarTime = currentBar;

    for (int i = 0; i < OrdersTotal(); i++) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderSymbol() != Symbol()) continue;
        if (OrderTakeProfit() != 0) continue;  // only after partial close
        hasOrders = true;

        if (OrderType() == OP_BUY) {
            // Breakeven: on tick, only while SL is still below entry
            if (UseBreakeven && OrderStopLoss() < OrderOpenPrice() - Point) {
                if (Bid >= OrderOpenPrice() + BreakevenATRMult * atr) {
                    OrderModify(OrderTicket(), OrderOpenPrice(),
                                NormalizeDouble(OrderOpenPrice(), Digits), 0, 0, clrGreen);
                    Print("BUY breakeven → ", OrderOpenPrice());
                }
            }
            // Chandelier: track highest H4 high, update SL only on bar close
            if (!newBar) continue;
            double high = iHigh(Symbol(), PERIOD_H4, 1);
            if (s_highestHigh == 0) s_highestHigh = high;
            if (high > s_highestHigh) s_highestHigh = high;
            double newSL = NormalizeDouble(s_highestHigh - ChandelierATRMult * atr, Digits);
            if (newSL > OrderStopLoss() + Point)
                OrderModify(OrderTicket(), OrderOpenPrice(), newSL, 0, 0, clrYellow);
        }

        if (OrderType() == OP_SELL) {
            // Breakeven: on tick, only while SL is still above entry
            if (UseBreakeven && (OrderStopLoss() > OrderOpenPrice() + Point || OrderStopLoss() == 0)) {
                if (Ask <= OrderOpenPrice() - BreakevenATRMult * atr) {
                    OrderModify(OrderTicket(), OrderOpenPrice(),
                                NormalizeDouble(OrderOpenPrice(), Digits), 0, 0, clrGreen);
                    Print("SELL breakeven → ", OrderOpenPrice());
                }
            }
            // Chandelier: track lowest H4 low, update SL only on bar close
            if (!newBar) continue;
            double low = iLow(Symbol(), PERIOD_H4, 1);
            if (s_lowestLow == 0) s_lowestLow = low;
            if (low < s_lowestLow) s_lowestLow = low;
            double newSL = NormalizeDouble(s_lowestLow + ChandelierATRMult * atr, Digits);
            if (OrderStopLoss() == 0 || newSL < OrderStopLoss() - Point)
                OrderModify(OrderTicket(), OrderOpenPrice(), newSL, 0, 0, clrYellow);
        }
    }

    if (!hasOrders) _resetChandelier();
}

void _resetChandelier() {
    s_highestHigh = 0;
    s_lowestLow   = 0;
}


// ── balance writer ─────────────────────────────────────────────────────────

void WriteBalance() {
    int fh = FileOpen("balance.txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
    if (fh == INVALID_HANDLE) return;
    FileWriteString(fh, DoubleToString(AccountBalance(), 2));
    FileClose(fh);

    int fh2 = FileOpen("account_info.txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
    if (fh2 == INVALID_HANDLE) return;
    FileWriteString(fh2,
        "balance="  + DoubleToString(AccountBalance(), 2)  + "\n" +
        "equity="   + DoubleToString(AccountEquity(), 2)   + "\n" +
        "leverage="  + IntegerToString(AccountLeverage())   + "\n" +
        "currency=" + AccountCurrency()                     + "\n" +
        "broker="   + AccountCompany()                      + "\n"
    );
    FileClose(fh2);
}


// ── positions writer ───────────────────────────────────────────────────────

void WritePositions() {
    int fh = FileOpen("positions.txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
    if (fh == INVALID_HANDLE) return;
    for (int i = 0; i < OrdersTotal(); i++) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderType() != OP_BUY && OrderType() != OP_SELL) continue;
        string type = (OrderType() == OP_BUY) ? "BUY" : "SELL";
        FileWriteString(fh, OrderSymbol() + "," + type + "," +
                        DoubleToString(OrderOpenPrice(), 5) + "\n");
    }
    FileClose(fh);
}


// ── helpers ────────────────────────────────────────────────────────────────

void OpenOrder(int type, double lots, double sl, double tp) {
    double price = (type == OP_BUY) ? Ask : Bid;
    int ticket = OrderSend(Symbol(), type, lots, price, Slippage, sl, tp,
                           "SB_full", 0, 0,
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

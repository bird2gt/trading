#property strict
#property description "Capybara — Hull MA trend + martingale/grid EA"

// ── Time filter ───────────────────────────────────────────────────────────
input int    StartHour         = 0;
input int    StartMinute       = 0;
input int    EndHour           = 23;
input int    EndMinute         = 59;

// ── Lot sizing ────────────────────────────────────────────────────────────
input double Lot               = 0.01;
input bool   UseVariableLots   = false;
input double MarginPer001      = 1000.0;      // free margin per 0.01 lot
input double Multiplication    = 1.5;
input double MaxLots           = 500.0;

// ── TP / SL ───────────────────────────────────────────────────────────────
input int    TakeProfit        = 150;         // combined TP in points (150 = 15 pips on 5-digit)
input int    StopLoss          = 0;           // individual SL in points (0 = off)
input double GridStopLossPct   = 0.0;         // close all when total loss >= X% of balance (0 = off)

// ── Grid ──────────────────────────────────────────────────────────────────
input int    GridDistance      = 200;         // points between grid orders
input int    VarDistOrder      = 6;           // start variable distance after X orders
input int    VarDistanceStart  = 200;         // variable distance start in points
input double DistMult          = 1.4;

// ── Overlay ───────────────────────────────────────────────────────────────
input bool   OverlayEnabled    = true;        // close first+last order together in profit
input int    OverlayAfterX     = 10;          // activate only after X orders
input double OverlayPct        = 5.0;         // % of balance profit to trigger overlay

// ── Display ───────────────────────────────────────────────────────────────
input bool   DrawProfitTags    = true;
input string TypefaceName      = "Arial Black";
input int    FontSizeResult    = 10;
input color  TypefaceColor     = clrOrange;

// ── Panel settings ────────────────────────────────────────────────────────
input color  ButtonTextOn      = clrDarkOrchid;
input color  ButtonTextOff     = clrPurple;
input color  ColorBackground   = clrNavy;
input string PanelFontFace     = "Cambria";
input int    PanelFontSize     = 8;

// ── Control ───────────────────────────────────────────────────────────────
input int    MagicNumber       = 20125;
input bool   EnableBuy         = true;
input bool   EnableSell        = true;
input bool   ControlManual     = false;
input bool   AllowHedging      = true;
input int    MaxLongs          = 100;
input int    MaxShorts         = 100;
input string TradeDescription  = "Capybara";
input int    HamaPeriod        = 20;

bool     g_prevBlue, g_curBlue;
datetime g_lastBar;
int      g_pipFactor;

int OnInit() {
    g_pipFactor = (Digits == 5 || Digits == 3) ? 10 : 1;
    g_lastBar   = 0;
    g_curBlue   = HamaIsBlue(1);
    g_prevBlue  = g_curBlue;
    DrawPanel();
    return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
    ObjectsDeleteAll(0, TradeDescription + "_");
}

void OnTick() {
    if (!IsTradeAllowed()) return;
    if (!InTradingHours()) return;

    datetime barTime = iTime(NULL, 0, 0);
    if (barTime != g_lastBar) {
        g_lastBar  = barTime;
        g_prevBlue = g_curBlue;
        g_curBlue  = HamaIsBlue(1);
    }

    CheckGridSL();
    CheckTP();
    CheckOverlay();
    ManageGrid();
    if (DrawProfitTags) DrawProfit();
}

// ── Time filter ───────────────────────────────────────────────────────────

bool InTradingHours() {
    int now = Hour()*60+Minute(), start = StartHour*60+StartMinute, end = EndHour*60+EndMinute;
    if (start <= end) return now >= start && now <= end;
    return now >= start || now <= end;
}

// ── Hama: simplified Hull MA (2·WMA(n/2) − WMA(n)), rising = blue ────────

bool HamaIsBlue(int shift) {
    int h = MathMax(2, HamaPeriod / 2);
    double h0 = 2.0*iMA(NULL,0,h,0,MODE_LWMA,PRICE_CLOSE,shift)   - iMA(NULL,0,HamaPeriod,0,MODE_LWMA,PRICE_CLOSE,shift);
    double h1 = 2.0*iMA(NULL,0,h,0,MODE_LWMA,PRICE_CLOSE,shift+1) - iMA(NULL,0,HamaPeriod,0,MODE_LWMA,PRICE_CLOSE,shift+1);
    return h0 > h1;
}

// ── Order helpers ─────────────────────────────────────────────────────────

int CountByType(int type) {
    int n = 0;
    for (int i = 0; i < OrdersTotal(); i++) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() == type) n++;
    }
    return n;
}

double DeepestPrice(int type) {
    double res = -1;
    for (int i = 0; i < OrdersTotal(); i++) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != type) continue;
        double op = OrderOpenPrice();
        if (type == OP_BUY  && (res < 0 || op < res)) res = op;
        if (type == OP_SELL && (res < 0 || op > res)) res = op;
    }
    return res;
}

double TotalProfit(int type) {
    double p = 0;
    for (int i = 0; i < OrdersTotal(); i++) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber) continue;
        if (type != -1 && OrderType() != type) continue;
        p += OrderProfit() + OrderSwap() + OrderCommission();
    }
    return p;
}

double WeightedAvgPrice(int type) {
    double sumPL = 0, sumL = 0;
    for (int i = 0; i < OrdersTotal(); i++) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber) continue;
        if (OrderType() != type) continue;
        sumPL += OrderOpenPrice() * OrderLots();
        sumL  += OrderLots();
    }
    return sumL > 0 ? sumPL / sumL : 0;
}

double NextLot(int existingCount) {
    double lots = UseVariableLots
        ? NormalizeDouble(AccountFreeMargin() / MarginPer001 * 0.01, 2)
        : Lot;
    for (int i = 0; i < existingCount; i++) lots = NormalizeDouble(lots * Multiplication, 2);
    return MathMin(MathMax(lots, MarketInfo(Symbol(), MODE_MINLOT)), MaxLots);
}

// Distance in raw MT4 points for the N-th grid add
int GridDist(int existingCount) {
    if (existingCount < VarDistOrder) return GridDistance;
    double d = VarDistanceStart;
    for (int i = 0; i < existingCount - VarDistOrder; i++) d *= DistMult;
    return (int)MathRound(d);
}

void OpenOrder(int type, double lots) {
    double price = (type == OP_BUY) ? Ask : Bid;
    double sl = 0;
    if (StopLoss > 0) {
        double slPts = StopLoss * Point;
        sl = NormalizeDouble(type == OP_BUY ? price - slPts : price + slPts, Digits);
    }
    string comment = TradeDescription + "_" + IntegerToString(type) + "_" + IntegerToString(CountByType(type)+1);
    int ticket = OrderSend(Symbol(), type, lots, price, 3, sl, 0, comment, MagicNumber, 0,
                           type == OP_BUY ? clrBlue : clrRed);
    if (ticket < 0) Print("OrderSend error: ", GetLastError(), " type=", type, " lots=", lots);
}

void CloseAll(int type) {
    for (int i = OrdersTotal()-1; i >= 0; i--) {
        if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
        if (OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber) continue;
        if (type != -1 && OrderType() != type) continue;
        double price = (OrderType() == OP_BUY) ? Bid : Ask;
        if (!OrderClose(OrderTicket(), OrderLots(), price, 3, clrWhite))
            Print("OrderClose error: ", GetLastError());
    }
}

// ── Percentage grid stop loss ─────────────────────────────────────────────

void CheckGridSL() {
    if (GridStopLossPct <= 0) return;
    double loss = TotalProfit(-1), balance = AccountBalance();
    if (balance > 0 && loss < 0 && MathAbs(loss)/balance*100.0 >= GridStopLossPct) {
        Print("Grid SL triggered at ", DoubleToString(MathAbs(loss)/balance*100, 2), "%");
        CloseAll(-1);
    }
}

// ── Combined TP: close when price reaches weighted avg +/- TakeProfit points

void CheckTP() {
    if (TakeProfit <= 0) return;
    double tpPts = TakeProfit * Point;

    if (CountByType(OP_BUY) > 0) {
        double avg = WeightedAvgPrice(OP_BUY);
        if (Bid >= avg + tpPts) { Print("BUY TP hit. Avg=", avg); CloseAll(OP_BUY); }
    }
    if (CountByType(OP_SELL) > 0) {
        double avg = WeightedAvgPrice(OP_SELL);
        if (Ask <= avg - tpPts) { Print("SELL TP hit. Avg=", avg); CloseAll(OP_SELL); }
    }
}

// ── Overlay: close first + last order when combined profit >= OverlayPct% ─

void CheckOverlay() {
    if (!OverlayEnabled) return;
    int types[2] = {OP_BUY, OP_SELL};
    for (int t = 0; t < 2; t++) {
        int type = types[t], count = CountByType(type);
        if (count < OverlayAfterX || count < 2) continue;

        int    firstTicket = -1, lastTicket = -1;
        double firstPrice  = -1, lastPrice  = -1;
        for (int i = 0; i < OrdersTotal(); i++) {
            if (!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
            if (OrderSymbol() != Symbol() || OrderMagicNumber() != MagicNumber) continue;
            if (OrderType() != type) continue;
            double op = OrderOpenPrice();
            if (type == OP_BUY) {
                if (firstPrice < 0 || op > firstPrice) { firstPrice = op; firstTicket = OrderTicket(); }
                if (lastPrice  < 0 || op < lastPrice)  { lastPrice  = op; lastTicket  = OrderTicket(); }
            } else {
                if (firstPrice < 0 || op < firstPrice) { firstPrice = op; firstTicket = OrderTicket(); }
                if (lastPrice  < 0 || op > lastPrice)  { lastPrice  = op; lastTicket  = OrderTicket(); }
            }
        }
        if (firstTicket < 0 || lastTicket < 0 || firstTicket == lastTicket) continue;

        double combined = 0;
        if (OrderSelect(firstTicket, SELECT_BY_TICKET, MODE_TRADES))
            combined += OrderProfit() + OrderSwap() + OrderCommission();
        if (OrderSelect(lastTicket,  SELECT_BY_TICKET, MODE_TRADES))
            combined += OrderProfit() + OrderSwap() + OrderCommission();

        if (combined < AccountBalance() * OverlayPct / 100.0) continue;

        double price = (type == OP_BUY) ? Bid : Ask;
        if (OrderSelect(firstTicket, SELECT_BY_TICKET, MODE_TRADES)) OrderClose(firstTicket, OrderLots(), price, 3, clrGold);
        if (OrderSelect(lastTicket,  SELECT_BY_TICKET, MODE_TRADES)) OrderClose(lastTicket,  OrderLots(), price, 3, clrGold);
    }
}

// ── Grid management ───────────────────────────────────────────────────────

void ManageGrid() {
    if (EnableBuy) {
        int bCount = CountByType(OP_BUY);
        if (bCount == 0) {
            if (g_curBlue && !g_prevBlue && (AllowHedging || CountByType(OP_SELL) == 0))
                OpenOrder(OP_BUY, NextLot(0));
        } else if (bCount < MaxLongs) {
            double deep = DeepestPrice(OP_BUY);
            if (deep > 0 && Ask <= deep - GridDist(bCount) * Point)
                OpenOrder(OP_BUY, NextLot(bCount));
        }
    }
    if (EnableSell) {
        int sCount = CountByType(OP_SELL);
        if (sCount == 0) {
            if (!g_curBlue && g_prevBlue && (AllowHedging || CountByType(OP_BUY) == 0))
                OpenOrder(OP_SELL, NextLot(0));
        } else if (sCount < MaxShorts) {
            double deep = DeepestPrice(OP_SELL);
            if (deep > 0 && Bid >= deep + GridDist(sCount) * Point)
                OpenOrder(OP_SELL, NextLot(sCount));
        }
    }
}

// ── Profit label ──────────────────────────────────────────────────────────

void DrawProfit() {
    double profit = TotalProfit(-1);
    string name = TradeDescription + "_profit";
    string text = "P/L: " + (profit >= 0 ? "+" : "") + DoubleToString(profit, 2);
    if (ObjectFind(0, name) < 0) ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
    ObjectSetString (0, name, OBJPROP_TEXT,       text);
    ObjectSetString (0, name, OBJPROP_FONT,       TypefaceName);
    ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   FontSizeResult);
    ObjectSetInteger(0, name, OBJPROP_COLOR,      TypefaceColor);
    ObjectSetInteger(0, name, OBJPROP_CORNER,     CORNER_LEFT_UPPER);
    ObjectSetInteger(0, name, OBJPROP_XDISTANCE,  10);
    ObjectSetInteger(0, name, OBJPROP_YDISTANCE,  20);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

// ── Info panel ────────────────────────────────────────────────────────────

void DrawPanel() {
    string bg = TradeDescription + "_panel_bg";
    if (ObjectFind(0, bg) < 0) ObjectCreate(0, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0);
    ObjectSetInteger(0, bg, OBJPROP_CORNER,     CORNER_LEFT_UPPER);
    ObjectSetInteger(0, bg, OBJPROP_XDISTANCE,  5);
    ObjectSetInteger(0, bg, OBJPROP_YDISTANCE,  5);
    ObjectSetInteger(0, bg, OBJPROP_XSIZE,      160);
    ObjectSetInteger(0, bg, OBJPROP_YSIZE,      40);
    ObjectSetInteger(0, bg, OBJPROP_BGCOLOR,    ColorBackground);
    ObjectSetInteger(0, bg, OBJPROP_BORDER_TYPE, BORDER_FLAT);
    ObjectSetInteger(0, bg, OBJPROP_SELECTABLE, false);

    string lbl = TradeDescription + "_panel_lbl";
    if (ObjectFind(0, lbl) < 0) ObjectCreate(0, lbl, OBJ_LABEL, 0, 0, 0);
    ObjectSetString (0, lbl, OBJPROP_TEXT,       TradeDescription + " EA");
    ObjectSetString (0, lbl, OBJPROP_FONT,       PanelFontFace);
    ObjectSetInteger(0, lbl, OBJPROP_FONTSIZE,   PanelFontSize);
    ObjectSetInteger(0, lbl, OBJPROP_COLOR,      ButtonTextOn);
    ObjectSetInteger(0, lbl, OBJPROP_CORNER,     CORNER_LEFT_UPPER);
    ObjectSetInteger(0, lbl, OBJPROP_XDISTANCE,  12);
    ObjectSetInteger(0, lbl, OBJPROP_YDISTANCE,  12);
    ObjectSetInteger(0, lbl, OBJPROP_SELECTABLE, false);
}

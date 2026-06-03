# Intraday universe research (2026-06-03)

Scope: 44 MT4 instruments from the user's list. Data source: Yahoo Finance via yfinance.
Daily charts cover roughly 12 months and 6 months. H4 is resampled from H1. M15 history is limited by Yahoo Finance and usually covers about 60 days.

Important: this is a tradability/volatility ranking, not a promise of profit. Broker spread, swaps, CFD session breaks, slippage, news filters, and execution quality must be checked in MT4 before enabling a symbol.

## Best overall for same-day trades

| rank | symbol | group_name | class | opportunity_score | median_day_range_6m_pct | h1_atr_pct_6m | m15_atr_pct | h4_adx_6m | change_6m_pct | timeframe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | XAGUSD | Metal | A | 77.20 | 5.34 | 1.17 | 0.45 | 19.87 | 30.13 | M15 timing |
| 2 | WTI | Energy | A | 72.80 | 3.71 | 0.91 | 0.57 | 34.71 | 61.00 | H4 regime + M15 timing |
| 3 | BRENT | Energy | A | 70.60 | 3.30 | 0.88 | 0.49 | 36.87 | 54.91 | H4 regime + M15 timing |
| 4 | XAUEUR | Metal | A | 68.60 | 2.14 | 0.58 | 0.26 | 26.37 | 7.48 | H4 regime + H1 entry + M15 timing |
| 5 | .JP225 | Index | A | 67.50 | 1.48 | 0.54 | 0.31 | 29.78 | 37.73 | H4 regime + H1 entry + M15 timing |
| 6 | ADAUSD | Crypto | B | 65.90 | 4.68 | 0.78 | 0.33 | 17.20 | -53.37 | H1 entry + M15 timing |
| 7 | SOLUSD | Crypto | B | 65.70 | 4.27 | 0.74 | 0.30 | 23.60 | -49.40 | H1 entry + M15 timing |
| 8 | XAUUSD | Metal | B | 65.00 | 2.15 | 0.48 | 0.22 | 25.34 | 7.48 | H4 regime + H1 entry + M15 timing |
| 9 | .USTEC | Index | B | 64.90 | 1.23 | 0.49 | 0.23 | 35.95 | 19.97 | H4 regime + H1 entry + M15 timing |
| 10 | ETHUSD | Crypto | B | 64.40 | 3.81 | 0.74 | 0.28 | 21.85 | -42.33 | H1 entry + M15 timing |
| 11 | DOGEUSD | Crypto | B | 64.30 | 4.29 | 0.75 | 0.34 | 19.14 | -39.28 | H1 entry + M15 timing |
| 12 | XRPUSD | Crypto | B | 62.40 | 3.61 | 0.63 | 0.26 | 23.27 | -44.97 | H1 entry + M15 timing |
| 13 | BTCUSD | Crypto | B | 61.60 | 3.10 | 0.56 | 0.21 | 30.18 | -29.05 | H4 regime + H1 entry + M15 timing |
| 14 | .US500 | Index | B | 58.20 | 0.87 | 0.35 | 0.17 | 30.89 | 11.43 | H4 regime + H1 entry + M15 timing |
| 15 | .DE40C | Index | B | 57.90 | 1.12 | 0.40 | 0.23 | 22.21 | 5.96 | H1 entry + M15 timing |

## Best Forex candidates

| rank | symbol | group_name | class | opportunity_score | median_day_range_6m_pct | h1_atr_pct_6m | m15_atr_pct | h4_adx_6m | change_6m_pct | timeframe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 16 | NZDCHF | Forex cross | B | 56.00 | 0.96 | 0.21 | 0.10 | 36.25 | 1.29 | H4 regime + H1 entry + M15 timing |
| 18 | AUDCHF | Forex cross | C | 46.30 | 0.81 | 0.26 | 0.18 | 16.94 | 7.15 | M15 timing |
| 19 | NZDJPY | Forex cross | C | 45.60 | 0.75 | 0.16 | 0.08 | 23.60 | 5.82 | H1 entry + M15 timing |
| 20 | NZDCAD | Forex cross | C | 44.10 | 0.64 | 0.15 | 0.09 | 26.19 | 2.22 | H4 regime + H1 entry + M15 timing |
| 21 | CADCHF | Forex cross | C | 42.70 | 0.60 | 0.23 | 0.17 | 28.05 | -0.93 | H4 regime + M15 timing |
| 22 | NZDUSD | Forex cross | C | 41.60 | 0.79 | 0.14 | 0.06 | 21.70 | 3.14 | H1 entry + M15 timing |
| 23 | AUDCAD | Forex cross | C | 41.20 | 0.63 | 0.20 | 0.14 | 18.61 | 8.16 | H1 entry + M15 timing |
| 24 | USDCHF | Forex major | C | 40.80 | 0.60 | 0.13 | 0.07 | 18.63 | -1.79 | H1 entry + M15 timing |
| 25 | AUDJPY | Forex cross | C | 40.50 | 0.75 | 0.16 | 0.08 | 16.16 | 11.96 | M15 timing |
| 26 | GBPNZD | Forex cross | D | 38.80 | 0.60 | 0.13 | 0.07 | 30.46 | -1.25 | H4 regime + H1 entry + M15 timing |
| 27 | AUDUSD | Forex major | D | 38.20 | 0.72 | 0.13 | 0.06 | 16.57 | 9.14 | M15 timing |
| 28 | EURNZD | Forex cross | D | 32.80 | 0.56 | 0.13 | 0.07 | 26.57 | -3.02 | H4 regime + H1 entry + M15 timing |

## Best non-Forex candidates

| rank | symbol | group_name | class | opportunity_score | median_day_range_6m_pct | h1_atr_pct_6m | m15_atr_pct | h4_adx_6m | change_6m_pct | timeframe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | XAGUSD | Metal | A | 77.20 | 5.34 | 1.17 | 0.45 | 19.87 | 30.13 | M15 timing |
| 2 | WTI | Energy | A | 72.80 | 3.71 | 0.91 | 0.57 | 34.71 | 61.00 | H4 regime + M15 timing |
| 3 | BRENT | Energy | A | 70.60 | 3.30 | 0.88 | 0.49 | 36.87 | 54.91 | H4 regime + M15 timing |
| 4 | XAUEUR | Metal | A | 68.60 | 2.14 | 0.58 | 0.26 | 26.37 | 7.48 | H4 regime + H1 entry + M15 timing |
| 5 | .JP225 | Index | A | 67.50 | 1.48 | 0.54 | 0.31 | 29.78 | 37.73 | H4 regime + H1 entry + M15 timing |
| 6 | ADAUSD | Crypto | B | 65.90 | 4.68 | 0.78 | 0.33 | 17.20 | -53.37 | H1 entry + M15 timing |
| 7 | SOLUSD | Crypto | B | 65.70 | 4.27 | 0.74 | 0.30 | 23.60 | -49.40 | H1 entry + M15 timing |
| 8 | XAUUSD | Metal | B | 65.00 | 2.15 | 0.48 | 0.22 | 25.34 | 7.48 | H4 regime + H1 entry + M15 timing |
| 9 | .USTEC | Index | B | 64.90 | 1.23 | 0.49 | 0.23 | 35.95 | 19.97 | H4 regime + H1 entry + M15 timing |
| 10 | ETHUSD | Crypto | B | 64.40 | 3.81 | 0.74 | 0.28 | 21.85 | -42.33 | H1 entry + M15 timing |
| 11 | DOGEUSD | Crypto | B | 64.30 | 4.29 | 0.75 | 0.34 | 19.14 | -39.28 | H1 entry + M15 timing |
| 12 | XRPUSD | Crypto | B | 62.40 | 3.61 | 0.63 | 0.26 | 23.27 | -44.97 | H1 entry + M15 timing |

## Lowest priority / avoid unless there is a special setup

| rank | symbol | group_name | class | opportunity_score | median_day_range_6m_pct | h1_atr_pct_6m | m15_atr_pct | h4_adx_6m | change_6m_pct | timeframe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 44 | EURUSD | Forex major | D | 11.50 | 0.47 | 0.09 | 0.04 | 16.71 | 0.00 | M15 timing |
| 43 | EURCAD | Forex cross | D | 11.80 | 0.39 | 0.10 | 0.06 | 23.87 | -0.88 | M15 timing |
| 42 | EURJPY | Forex cross | D | 12.30 | 0.47 | 0.11 | 0.05 | 18.12 | 2.87 | M15 timing |
| 41 | EURGBP | Forex cross | D | 14.60 | 0.30 | 0.07 | 0.04 | 31.83 | -1.81 | H4 regime + H1 entry + M15 timing |
| 40 | GBPCAD | Forex cross | D | 18.90 | 0.49 | 0.11 | 0.06 | 25.78 | 0.94 | H4 regime + M15 timing |
| 39 | EURCHF | Forex cross | D | 19.80 | 0.38 | 0.12 | 0.08 | 25.65 | -2.06 | H4 regime + H1 entry + M15 timing |
| 38 | GBPJPY | Forex cross | D | 20.40 | 0.53 | 0.12 | 0.06 | 17.03 | 4.49 | H1 entry + M15 timing |
| 37 | GBPUSD | Forex major | D | 22.10 | 0.57 | 0.11 | 0.05 | 17.87 | 1.83 | M15 timing |
| 36 | USDCAD | Forex major | D | 23.00 | 0.40 | 0.11 | 0.07 | 36.83 | -0.87 | H4 regime + M15 timing |
| 35 | CHFJPY | Forex cross | D | 24.90 | 0.55 | 0.12 | 0.06 | 21.63 | 4.52 | H1 entry + M15 timing |

## How the score was built

- 30% median daily H1 range over the last 6 months.
- 12% 90th percentile daily H1 range over the last 6 months.
- 18% H1 ATR percent over the last 6 months.
- 12% M15 ATR percent over the last available M15 window.
- 10% H4 ATR percent over the last 6 months.
- 18% H4/H1 ADX trend strength.
- Multiplied by a practical factor for spread/liquidity and data coverage.

## Practical reading

- Class A: enough movement for H1 entries with H4 context; worth backtesting first.
- Class B: tradable when the session is active or there is a clean H4/H1 setup.
- Class C: secondary watchlist; often needs news/session catalyst.
- Class D: low priority for intraday automation unless broker spread is exceptionally good.

## Data sources used by symbol

- EURUSD: 1d:EURUSD=X, 1h:EURUSD=X, 15m:EURUSD=X
- GBPUSD: 1d:GBPUSD=X, 1h:GBPUSD=X, 15m:GBPUSD=X
- USDJPY: 1d:JPY=X, 1h:JPY=X, 15m:JPY=X
- USDCHF: 1d:CHF=X, 1h:CHF=X, 15m:CHF=X
- USDCAD: 1d:CAD=X, 1h:CAD=X, 15m:CAD=X
- AUDUSD: 1d:AUDUSD=X, 1h:AUDUSD=X, 15m:AUDUSD=X
- EURGBP: 1d:EURGBP=X, 1h:EURGBP=X, 15m:EURGBP=X
- EURAUD: 1d:EURAUD=X, 1h:EURAUD=X, 15m:EURAUD=X
- EURCHF: 1d:EURCHF=X, 1h:EURCHF=X, 15m:EURCHF=X
- EURJPY: 1d:EURJPY=X, 1h:EURJPY=X, 15m:EURJPY=X
- EURNZD: 1d:EURNZD=X, 1h:EURNZD=X, 15m:EURNZD=X
- EURCAD: 1d:EURCAD=X, 1h:EURCAD=X, 15m:EURCAD=X
- GBPCHF: 1d:GBPCHF=X, 1h:GBPCHF=X, 15m:GBPCHF=X
- GBPJPY: 1d:GBPJPY=X, 1h:GBPJPY=X, 15m:GBPJPY=X
- GBPAUD: 1d:GBPAUD=X, 1h:GBPAUD=X, 15m:GBPAUD=X
- GBPCAD: 1d:GBPCAD=X, 1h:GBPCAD=X, 15m:GBPCAD=X
- GBPNZD: 1d:GBPNZD=X, 1h:GBPNZD=X, 15m:GBPNZD=X
- AUDNZD: 1d:AUDNZD=X, 1h:AUDNZD=X, 15m:AUDNZD=X
- AUDCAD: 1d:AUDCAD=X, 1h:AUDCAD=X, 15m:AUDCAD=X
- AUDCHF: 1d:AUDCHF=X, 1h:AUDCHF=X, 15m:AUDCHF=X
- AUDJPY: 1d:AUDJPY=X, 1h:AUDJPY=X, 15m:AUDJPY=X
- CADJPY: 1d:CADJPY=X, 1h:CADJPY=X, 15m:CADJPY=X
- CADCHF: 1d:CADCHF=X, 1h:CADCHF=X, 15m:CADCHF=X
- CHFJPY: 1d:CHFJPY=X, 1h:CHFJPY=X, 15m:CHFJPY=X
- NZDJPY: 1d:NZDJPY=X, 1h:NZDJPY=X, 15m:NZDJPY=X
- NZDUSD: 1d:NZDUSD=X, 1h:NZDUSD=X, 15m:NZDUSD=X
- NZDCAD: 1d:NZDCAD=X, 1h:NZDCAD=X, 15m:NZDCAD=X
- NZDCHF: 1d:NZDCHF=X, 1h:NZDCHF=X, 15m:NZDCHF=X
- XAUUSD: 1d:GC=F, 1h:GC=F, 15m:GC=F
- XAGUSD: 1d:SI=F, 1h:SI=F, 15m:SI=F
- XAUEUR: 1d:GC=F/EURUSD=X, 1h:GC=F/EURUSD=X, 15m:GC=F/EURUSD=X
- .DE40C: 1d:^GDAXI, 1h:^GDAXI, 15m:^GDAXI
- .JP225: 1d:^N225, 1h:^N225, 15m:^N225
- .US500: 1d:^GSPC, 1h:^GSPC, 15m:^GSPC
- .USTEC: 1d:^NDX, 1h:^NDX, 15m:^NDX
- .US30C: 1d:^DJI, 1h:^DJI, 15m:^DJI
- BRENT: 1d:BZ=F, 1h:BZ=F, 15m:BZ=F
- WTI: 1d:CL=F, 1h:CL=F, 15m:CL=F
- BTCUSD: 1d:BTC-USD, 1h:BTC-USD, 15m:BTC-USD
- ETHUSD: 1d:ETH-USD, 1h:ETH-USD, 15m:ETH-USD
- SOLUSD: 1d:SOL-USD, 1h:SOL-USD, 15m:SOL-USD
- DOGEUSD: 1d:DOGE-USD, 1h:DOGE-USD, 15m:DOGE-USD
- ADAUSD: 1d:ADA-USD, 1h:ADA-USD, 15m:ADA-USD
- XRPUSD: 1d:XRP-USD, 1h:XRP-USD, 15m:XRP-USD

## Failed or incomplete symbols

- None

Generated files:

- `summary.csv`: full metric table.
- `charts/*_12m.svg` and `charts/*_6m.svg`: movement charts.
- `charts/top_15_score.svg`: top-score chart.
- `charts/top_15_range.svg`: top daily-range chart.

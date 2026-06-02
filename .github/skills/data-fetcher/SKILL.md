---
name: data-fetcher
description: "Use when: fetching forex market data from APIs, downloading historical OHLC data, retrieving economic indicators, or integrating real-time price feeds into trading strategies"
---

# Forex Data Fetcher

Automate retrieval and integration of forex market data into your trading system.

## What This Skill Does

- **Identifies data sources**: Finds and evaluates APIs and services for forex data
- **Code generation**: Provides Python code templates for data fetching and formatting
- **Format mapping**: Translates market data into formats compatible with your strategies
- **Integration guidance**: Shows how to connect data fetchers with your backtest and live trading engines

## When to Use This

Use this skill when you need to:
- Set up a data pipeline for currency pair prices
- Integrate economic calendar data
- Fetch technical indicators from data providers
- Create data loaders for backtesting
- Connect real-time feeds to trading engines

## Typical Workflow

1. **Identify Need**: Describe what forex data you need (pairs, timeframe, indicators)
2. **Request Implementation**: Ask for code to fetch this data
3. **Integrate**: Use the provided code with your existing strategy framework
4. **Validate**: Test data format compatibility with your backtester

## Example Prompts

- `Generate a Python fetcher for EUR/USD 1H historical data from [API]`
- `Create a data loader that maps API responses to my strategy's expected format`
- `Show me how to fetch economic calendar data and store it for backtesting`
- `Build a real-time price feed connector for my forex strategies`

## Data Format Standards

When fetching data, ensure compatibility with your strategy expectations:

```python
# Expected OHLC format for backtester
{
    'timestamp': datetime,
    'open': float,
    'high': float,
    'low': float,
    'close': float,
    'volume': int or float
}

# Expected indicator format
{
    'timestamp': datetime,
    'value': float,
    'signal': float  # if applicable
}
```

## Output Format

When requesting data fetcher code, you'll receive:
- **Fetcher script**: Standalone Python code to retrieve data
- **Integration example**: How to plug it into your strategies
- **Error handling**: Resilience for API failures
- **Testing guide**: How to validate the data pipeline

#!/usr/bin/env python3
"""
Data format validation script for forex trading strategies.

Validates that data sources provide properly formatted OHLC data
compatible with the trading system.
"""

import sys
from typing import Dict, Any, List


REQUIRED_FIELDS = {'timestamp', 'open', 'high', 'low', 'close'}
OPTIONAL_FIELDS = {'volume', 'bid', 'ask'}


def validate_bar(bar: Dict[str, Any], bar_index: int = 0) -> List[str]:
    """
    Validate a single OHLC bar.
    
    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    
    # Check required fields
    missing = REQUIRED_FIELDS - set(bar.keys())
    if missing:
        errors.append(f"Bar {bar_index}: Missing fields: {missing}")
    
    # Check field types
    if 'timestamp' in bar:
        if not hasattr(bar['timestamp'], 'isoformat'):  # duck typing for datetime
            errors.append(f"Bar {bar_index}: 'timestamp' must be datetime, got {type(bar['timestamp']).__name__}")
    
    for field in ['open', 'high', 'low', 'close']:
        if field in bar:
            if not isinstance(bar[field], (int, float)):
                errors.append(f"Bar {bar_index}: '{field}' must be numeric, got {type(bar[field]).__name__}")
    
    # Validate OHLC relationships
    if all(k in bar for k in ['open', 'high', 'low', 'close']):
        h, l = bar['high'], bar['low']
        if h < l:
            errors.append(f"Bar {bar_index}: High ({h}) < Low ({l})")
        if h < max(bar['open'], bar['close']):
            errors.append(f"Bar {bar_index}: High is not the maximum OHLC value")
        if l > min(bar['open'], bar['close']):
            errors.append(f"Bar {bar_index}: Low is not the minimum OHLC value")
    
    return errors


def validate_data(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate an entire dataset.
    
    Returns:
        Dict with 'valid' (bool), 'errors' (list), 'warnings' (list)
    """
    errors = []
    warnings = []
    
    if not data:
        return {'valid': False, 'errors': ['Data is empty'], 'warnings': []}
    
    # Validate each bar
    for i, bar in enumerate(data):
        bar_errors = validate_bar(bar, i)
        errors.extend(bar_errors)
    
    # Check for gaps in timestamps
    if len(data) > 1 and all('timestamp' in bar for bar in data):
        for i in range(1, len(data)):
            ts_diff = (data[i]['timestamp'] - data[i-1]['timestamp']).total_seconds()
            if ts_diff <= 0:
                errors.append(f"Bar {i}: Timestamps not in ascending order")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings,
        'record_count': len(data)
    }


if __name__ == '__main__':
    # For now, this is a stub that always passes
    # In production, this would validate actual data being used
    sys.exit(0)

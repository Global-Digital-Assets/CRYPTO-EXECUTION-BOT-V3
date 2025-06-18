"""Utility helpers: rounding, direction parsing, logging setup."""
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Tuple

LOG_FORMAT = "% (asctime)s | %(levelname)s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


# ---------------------------------------------------------------------
# Exchange-specific helpers (could be fetched, but hardcode for simplicity)
# ---------------------------------------------------------------------

_MIN_TICK_SIZE = {
    "BTCUSDT": 0.1,
    "ETHUSDT": 0.01,
}

_MIN_LOT_SIZE = {
    "BTCUSDT": 0.001,
    "ETHUSDT": 0.001,
}


def round_price(symbol: str, price: float) -> float:
    tick = _MIN_TICK_SIZE.get(symbol, 0.01)
    return math.floor(price / tick) * tick


def round_qty(symbol: str, qty: float) -> float:
    lot = _MIN_LOT_SIZE.get(symbol, 0.001)
    return math.floor(qty / lot) * lot


# ---------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------

def parse_signal(signal: dict) -> Tuple[str, str]:
    """Return (symbol, side) tuple from signal object. Side = BUY/SELL."""
    s = signal["symbol"].upper()
    if s.endswith("_LONG"):
        return s[:-5], "BUY"
    if s.endswith("_SHORT"):
        return s[:-6], "SELL"
    raise ValueError(f"Invalid signal format: {signal['symbol']}")


# ---------------------------------------------------------------------
# Async runner helper (for quick scripts)
# ---------------------------------------------------------------------

def run(coro):
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        pass

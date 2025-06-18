"""Utility helpers: rounding, direction parsing, logging setup."""
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Tuple

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"


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
# Symbol aliasing and parsing helpers
# ---------------------------------------------------------------------

# Some Binance futures contracts are issued in 100/1000-multiples (e.g. 1000PEPEUSDT).
# The signal service might emit the plain symbol (PEPEUSDT). Map those here.
ALIAS_MAP = {
    "PEPEUSDT": "1000PEPEUSDT",
    "ORDIUSDT": "1000ORDIUSDT",
    "BONKUSDT": "1000BONKUSDT",
    "WIFUSDT": "1000WIFUSDT",
}


def _resolve_alias(symbol: str) -> str:
    """Return Binance-valid symbol, applying ALIAS_MAP if necessary."""
    return ALIAS_MAP.get(symbol, symbol)


def parse_signal(signal: dict) -> Tuple[str, str]:
    """Extract (binance_symbol, side) from signal.

    Accepted signal["symbol"] forms:
        DYMUSDT_LONG, PEPEUSDT_SHORT, etc.
    Returns:
        binance_symbol – resolved against ALIAS_MAP
        side – "BUY" | "SELL"
    """
    s = signal["symbol"].upper()
    if s.endswith("_LONG"):
        raw_symbol = s[:-5]
        return _resolve_alias(raw_symbol), "BUY"
    if s.endswith("_SHORT"):
        raw_symbol = s[:-6]
        return _resolve_alias(raw_symbol), "SELL"
    raise ValueError(f"Invalid signal format: {signal['symbol']}")


# ---------------------------------------------------------------------
# Async runner helper (for quick scripts)
# ---------------------------------------------------------------------

def run(coro):
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        pass

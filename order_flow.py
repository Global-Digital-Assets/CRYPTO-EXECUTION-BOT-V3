"""Order flow: fetch signals, size position, place entry + SL."""
from __future__ import annotations

import logging
from typing import List

import aiohttp

from binance_client import BinanceClient
from risk import FIXED_PCT_PER_TRADE, LEVERAGE, MAX_CONCURRENT_POSITIONS, STOP_LOSS_PCT
from utils import parse_signal, round_price, round_qty

_LOGGER = logging.getLogger(__name__)

SIGNAL_API = "http://127.0.0.1:8000/api/analysis"


async def fetch_signals(conf_threshold: float = 0.7) -> List[dict]:
    """Return list of raw signal dicts with confidence >= threshold."""
    async with aiohttp.ClientSession() as s:
        async with s.get(SIGNAL_API, timeout=10) as resp:
            data = await resp.json()
    return [item for item in data if item.get("confidence", 0) >= conf_threshold]


async def process_signals():
    """Main trade cycle – robust against external failures."""
    try:
        async with BinanceClient() as client:
            positions = await client.current_positions()
            open_symbols = {p["symbol"] for p in positions}
            margin_pct = await client.margin_usage_pct()
            if margin_pct >= MAX_CONCURRENT_POSITIONS * (100 / MAX_CONCURRENT_POSITIONS):
                _LOGGER.info("Margin usage %.2f%% ≥ cap – skipping cycle", margin_pct)
                return

            try:
                signals = await fetch_signals()
            except Exception as e:
                _LOGGER.error("Fetch signals failed: %s", e)
                return

            if not signals:
                _LOGGER.info("No qualifying signals this cycle")
                return

            for sig in signals:
                symbol, side = parse_signal(sig)
                if symbol in open_symbols:
                    _LOGGER.info("%s already open – skipping", symbol)
                    continue
                if len(open_symbols) >= MAX_CONCURRENT_POSITIONS:
                    _LOGGER.info("Positions cap hit – skipping remaining signals")
                    break
                try:
                    await open_position(client, symbol, side)
                    open_symbols.add(symbol)
                except Exception as e:
                    _LOGGER.exception("Failed to open %s: %s", symbol, e)
    except Exception as e:
        _LOGGER.exception("Trade cycle fatal error: %s", e)


async def open_position(client: BinanceClient, symbol: str, side: str):
    """Place MARKET order + visible reduce-only SL."""
    bal = await client.wallet_balance()
    notional = bal * FIXED_PCT_PER_TRADE * LEVERAGE  # USDT value
    mark_price = await client.get_mark_price(symbol)
    quantity = round_qty(symbol, notional / mark_price)

    await client.set_leverage(symbol, LEVERAGE)

    # Entry
    entry_resp = await client.place_market_order(symbol, side, quantity)
    entry_price = float(entry_resp["avgPrice"] or mark_price)

    # SL side is opposite
    sl_side = "SELL" if side == "BUY" else "BUY"
    sl_price = round_price(symbol, entry_price * (1 - STOP_LOSS_PCT) if side == "BUY" else entry_price * (1 + STOP_LOSS_PCT))

    await client.place_market_order(
        symbol,
        sl_side,
        quantity,
        reduce_only=True,
        working_type="MARK_PRICE",
        stop_price=sl_price,
    )
    _LOGGER.info("Opened %s %s qty %.4f @ %.2f – SL %.2f", side, symbol, quantity, entry_price, sl_price)

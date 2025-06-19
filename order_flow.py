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


async def _coerce(item):
    """Convert API item to canonical dict with keys symbol/confidence."""
    if isinstance(item, dict):
        return {"symbol": str(item.get("symbol")), "confidence": float(item.get("confidence", 0))}
    # assume string like "PEPEUSDT_LONG 0.88" or comma-separated
    if isinstance(item, str):
        parts = item.replace(",", " ").split()
        if len(parts) >= 2:
            try:
                conf = float(parts[-1])
                symbol = " ".join(parts[:-1])
                return {"symbol": symbol, "confidence": conf}
            except ValueError:
                return None
    return None

async def fetch_signals(conf_threshold: float = 0.7) -> List[dict]:
    """Return list of signal dicts meeting confidence threshold."""
    _LOGGER.info("Fetching signals from %s", SIGNAL_API)
    
    async with aiohttp.ClientSession() as s:
        async with s.get(SIGNAL_API, timeout=10) as resp:
            data = await resp.json()
    
    # Handle new JSON format with opportunities array
    if "opportunities" in data:
        opportunities = data["opportunities"]
        _LOGGER.info("Found %d opportunities in API response", len(opportunities))
        signals = []
        for opp in opportunities:
            if opp.get("probability", 0) >= conf_threshold:
                # Convert model_id like "BOMEUSDT_long_v1750166329" to "BOMEUSDT_LONG"
                model_id = opp.get("model_id", "")
                if "_long_" in model_id:
                    symbol = model_id.split("_long_")[0] + "_LONG"
                elif "_short_" in model_id:
                    symbol = model_id.split("_short_")[0] + "_SHORT"
                else:
                    continue
                signals.append({
                    "symbol": symbol,
                    "confidence": float(opp["probability"])
                })
                _LOGGER.info("Qualified signal: %s (confidence: %.3f)", symbol, opp["probability"])
        
        _LOGGER.info("Filtered to %d qualifying signals (>= %.2f confidence)", len(signals), conf_threshold)
        return signals
    
    # Fallback for old format
    _LOGGER.warning("API returned old format, using fallback parser")
    return [item for item in data if item.get("confidence", 0) >= conf_threshold]


async def process_signals():
    """Main trade cycle – robust against external failures."""
    _LOGGER.info("=== STARTING TRADE CYCLE ===")
    try:
        async with BinanceClient() as client:
            _LOGGER.info("Connected to Binance client")
            
            positions = await client.current_positions()
            open_symbols = {p["symbol"] for p in positions}
            _LOGGER.info("Current positions: %d open (%s)", len(open_symbols), list(open_symbols))
            
            margin_pct = await client.margin_usage_pct()
            _LOGGER.info("Current margin usage: %.2f%%", margin_pct)
            
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

            _LOGGER.info("Processing %d signals for potential trades", len(signals))
            
            for sig in signals:
                symbol, side = parse_signal(sig)
                _LOGGER.info("Evaluating signal: %s %s (confidence: %.3f)", 
                           side, symbol, sig["confidence"])
                
                if symbol in open_symbols:
                    _LOGGER.info("%s already open – skipping", symbol)
                    continue
                if len(open_symbols) >= MAX_CONCURRENT_POSITIONS:
                    _LOGGER.info("Positions cap hit – skipping remaining signals")
                    break
                try:
                    _LOGGER.info("Opening position: %s %s", side, symbol)
                    await open_position(client, symbol, side)
                    open_symbols.add(symbol)
                    _LOGGER.info("✅ Successfully opened %s %s", side, symbol)
                except Exception as e:
                    _LOGGER.exception("Failed to open %s: %s", symbol, e)
                    
        _LOGGER.info("=== TRADE CYCLE COMPLETE ===")
    except Exception as e:
        _LOGGER.exception("Trade cycle fatal error: %s", e)


async def get_proper_quantity(client: BinanceClient, symbol: str, notional: float) -> float:
    """Get properly rounded quantity based on Binance exchange info."""
    try:
        symbol_info = await client.get_symbol_info(symbol)
        for filter_info in symbol_info["filters"]:
            if filter_info["filterType"] == "LOT_SIZE":
                step_size = float(filter_info["stepSize"])
                mark_price = await client.get_mark_price(symbol)
                raw_qty = notional / mark_price
                # Round down to nearest step_size
                qty = int(raw_qty / step_size) * step_size
                _LOGGER.info("Symbol %s: stepSize=%.8f, raw_qty=%.6f, final_qty=%.6f", 
                           symbol, step_size, raw_qty, qty)
                return qty
    except Exception as e:
        _LOGGER.warning("Failed to get precision for %s: %s, using fallback", symbol, e)
        # Fallback: use more conservative rounding
        mark_price = await client.get_mark_price(symbol)
        raw_qty = notional / mark_price
        if raw_qty >= 1000:
            return float(int(raw_qty))  # Round to whole numbers for large quantities
        elif raw_qty >= 10:
            return round(raw_qty, 1)    # 1 decimal place
        else:
            return round(raw_qty, 3)    # 3 decimal places for small quantities


async def get_proper_price(client: BinanceClient, symbol: str, price: float) -> float:
    """Get properly rounded price based on Binance exchange info."""
    try:
        symbol_info = await client.get_symbol_info(symbol)
        for filter_info in symbol_info["filters"]:
            if filter_info["filterType"] == "PRICE_FILTER":
                tick_size = float(filter_info["tickSize"])
                # Round price to nearest tick_size
                rounded_price = round(price / tick_size) * tick_size
                _LOGGER.info("Symbol %s: tickSize=%.8f, raw_price=%.8f, rounded_price=%.8f", 
                           symbol, tick_size, price, rounded_price)
                return rounded_price
    except Exception as e:
        _LOGGER.warning("Failed to get price precision for %s: %s, using fallback", symbol, e)
        # Fallback: round to 6 decimal places
        return round(price, 6)
    
    # If no PRICE_FILTER found, use fallback
    return round(price, 6)


async def open_position(client: BinanceClient, symbol: str, side: str):
    """Open a position with fixed sizing and place protective stop-loss."""
    _LOGGER.info("Opening position for %s %s", side, symbol)
    
    # Set leverage
    await client.set_leverage(symbol, LEVERAGE)
    _LOGGER.info("Set leverage to %dx for %s", LEVERAGE, symbol)
    
    # Calculate position size
    balance = await client.wallet_balance()
    _LOGGER.info("Current wallet balance: %.2f USDT", balance)
    
    notional = balance * FIXED_PCT_PER_TRADE * LEVERAGE  # USDT value
    quantity = await get_proper_quantity(client, symbol, notional)
    
    if quantity == 0:
        _LOGGER.warning("Calculated quantity is 0 for %s - skipping", symbol)
        return
        
    _LOGGER.info("Calculated position size: %.6f %s", quantity, symbol)
    
    # Place market order
    _LOGGER.info("Placing MARKET %s order: %s qty=%.6f", side, symbol, quantity)
    entry_resp = await client.place_market_order(symbol, side, quantity)
    
    # Get actual fill price - use mark price if avgPrice is not available
    entry_price = float(entry_resp.get("avgPrice") or 0)
    if entry_price == 0:
        entry_price = await client.get_mark_price(symbol)
        _LOGGER.warning("avgPrice not available, using mark price: %.6f", entry_price)
    
    _LOGGER.info("Market order filled: %s at price %.6f", 
                entry_resp.get("orderId", "N/A"), entry_price)
    
    # Calculate and place stop-loss
    sl_side = "SELL" if side == "BUY" else "BUY"
    if side == "BUY":
        sl_price = entry_price * (1 - STOP_LOSS_PCT / 100)
    else:
        sl_price = entry_price * (1 + STOP_LOSS_PCT / 100)
    
    sl_price = await get_proper_price(client, symbol, sl_price)
    
    # Validate prices before placing orders
    if entry_price <= 0:
        _LOGGER.error("Invalid entry price %.8f - skipping position", entry_price)
        return
        
    if sl_price <= 0:
        _LOGGER.error("Invalid SL price %.8f - skipping position", sl_price) 
        return
        
    # Calculate actual SL distance for verification
    if side == "BUY":
        actual_sl_pct = ((entry_price - sl_price) / entry_price) * 100
    else:
        actual_sl_pct = ((sl_price - entry_price) / entry_price) * 100
        
    _LOGGER.info("🎯 STOP-LOSS VERIFICATION: target=%.1f%%, actual=%.2f%%, entry=%.8f, sl=%.8f",
                STOP_LOSS_PCT * 100, actual_sl_pct, entry_price, sl_price)
    
    # Safety check: if SL is more than 2x target, abort
    if actual_sl_pct > (STOP_LOSS_PCT * 100) * 2:
        _LOGGER.error("🚨 SL TOO FAR: %.2f%% > %.1f%% - ABORTING TRADE", 
                     actual_sl_pct, STOP_LOSS_PCT * 2 * 100)
        return
    
    _LOGGER.info("Placing SL %s order at %.6f (%.1f%% from entry %.6f)", 
                sl_side, sl_price, STOP_LOSS_PCT * 100, entry_price)
    
    # Only place SL if we have a valid price
    if sl_price > 0:
        sl_resp = await client.place_market_order(
            symbol, sl_side, quantity, 
            reduce_only=True, stop_price=sl_price
        )
        _LOGGER.info("Stop-loss order placed: %s", sl_resp.get("orderId", "N/A"))
    else:
        _LOGGER.error("Invalid SL price %.6f - skipping SL placement", sl_price)
    
    _LOGGER.info("✅ Position opened: %s %s qty=%.6f entry=%.6f sl=%.6f", 
                side, symbol, quantity, entry_price, sl_price)

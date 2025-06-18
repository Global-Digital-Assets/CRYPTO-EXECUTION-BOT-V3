"""Minimal async Binance Futures REST client – only the endpoints needed by the execution bot.
Keeps footprint small and avoids external heavy SDKs. All requests are signed per Binance
Futures API docs. Only supports MARKET orders and reduce-only STOP-MARKET orders.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import time
from hashlib import sha256
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import ClientSession
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

BASE_URL = "https://fapi.binance.com"

_LOGGER = logging.getLogger(__name__)


class BinanceClient:
    """Tiny subset of Binance Futures HTTP endpoints (async)."""

    def __init__(self, api_key: str = API_KEY, api_secret: str = API_SECRET):
        if not api_key or not api_secret:
            raise ValueError("API keys missing – set BINANCE_API_KEY & BINANCE_API_SECRET env vars")
        self._api_key = api_key
        self._api_secret = api_secret.encode()
        self._session: Optional[ClientSession] = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._session:
            await self._session.close()

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    def _sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return params dict with signature added."""
        query = "&".join(f"{k}={v}" for k, v in params.items())
        signature = hmac.new(self._api_secret, query.encode(), sha256).hexdigest()
        params["signature"] = signature
        return params

    async def _request(self, method: str, path: str, signed: bool, **kwargs) -> Any:
        if not self._session:
            raise RuntimeError("Session not started – use `async with BinanceClient()`")
        url = f"{BASE_URL}{path}"
        headers = {"X-MBX-APIKEY": self._api_key}
        params = kwargs.pop("params", {})
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params = self._sign(params)
        async with self._session.request(method, url, params=params, headers=headers, **kwargs) as resp:
            if resp.status != 200:
                txt = await resp.text()
                raise RuntimeError(f"Binance API error {resp.status}: {txt}")
            return await resp.json()

    # ---------------------------------------------------------------------
    # Public/Private API wrappers
    # ---------------------------------------------------------------------
    async def get_mark_price(self, symbol: str) -> float:
        data = await self._request("GET", "/fapi/v1/premiumIndex", signed=False, params={"symbol": symbol})
        return float(data["markPrice"])

    async def get_account_info(self) -> Dict[str, Any]:
        return await self._request("GET", "/fapi/v2/account", signed=True)

    async def set_leverage(self, symbol: str, leverage: int = 5) -> None:
        await self._request("POST", "/fapi/v1/leverage", signed=True, params={"symbol": symbol, "leverage": leverage})

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        reduce_only: bool = False,
        working_type: Optional[str] = None,
        stop_price: Optional[float] = None,
        position_side: str = "BOTH",
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,  # BUY / SELL
            "type": "MARKET" if not stop_price else "STOP_MARKET",
            "quantity": quantity,
            "reduceOnly": "true" if reduce_only else "false",
            "positionSide": position_side,
        }
        if stop_price:
            params["stopPrice"] = stop_price
            params["workingType"] = working_type or "MARK_PRICE"
        return await self._request("POST", "/fapi/v1/order", signed=True, params=params)

    async def get_exchange_info(self) -> Dict[str, Any]:
        """Get exchange info for symbol precision."""
        return await self._request("GET", "/fapi/v1/exchangeInfo", signed=False)

    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Get specific symbol trading rules."""
        info = await self.get_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                return s
        raise ValueError(f"Symbol {symbol} not found in exchange info")

    # Utility wrappers
    async def current_positions(self) -> List[Dict[str, Any]]:
        acc = await self.get_account_info()
        return [p for p in acc["positions"] if float(p["positionAmt"]) != 0.0]

    async def wallet_balance(self) -> float:
        acc = await self.get_account_info()
        return float(acc["totalWalletBalance"])

    async def margin_usage_pct(self) -> float:
        acc = await self.get_account_info()
        im = float(acc["totalInitialMargin"])
        wb = float(acc["totalWalletBalance"])
        return (im / wb) * 100 if wb else 0.0

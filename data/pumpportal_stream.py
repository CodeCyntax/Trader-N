"""
Free Real-Time PumpPortal WebSocket Stream for New Token Launches.
Subscribes to newly created tokens, extracting metadata, dev wallet addresses,
and initial bonding curve conditions with zero API cost.
"""
import asyncio
import json
import logging
from typing import Callable, Optional
import websockets
from core.models import TokenMetadata
from core.constants import PUMP_PORTAL_WS_URL

logger = logging.getLogger("PumpPortalStream")


class PumpPortalTokenStream:
    """
    Subscribes to PumpPortal's free new token creation feed.
    """

    def __init__(self, on_new_token_callback: Callable[[TokenMetadata, dict], None]):
        self.on_new_token_callback = on_new_token_callback
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Starts the token streaming loop."""
        self.is_running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Stops the streaming loop."""
        self.is_running = False
        if self._task:
            self._task.cancel()

    async def _run_loop(self):
        while self.is_running:
            try:
                logger.info("Connecting to PumpPortal Token Creation stream...")
                async with websockets.connect(
                    PUMP_PORTAL_WS_URL,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))
                    logger.info("Subscribed successfully to live PumpPortal new tokens.")

                    while self.is_running:
                        msg = await ws.recv()
                        data = json.loads(msg)

                        if data.get("txType") == "create" and "mint" in data:
                            meta = TokenMetadata(
                                mint=data["mint"],
                                name=data.get("name", "Unknown"),
                                symbol=data.get("symbol", "TOKEN"),
                                uri=data.get("uri"),
                                dev_wallet=data.get("traderPublicKey", ""),
                                initial_buy_sol=float(data.get("solAmount", 0.0)),
                                initial_buy_tokens=float(data.get("initialBuy", 0.0)),
                            )
                            self.on_new_token_callback(meta, data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"PumpPortal WS disconnected: {e}. Reconnecting in 3s...")
                await asyncio.sleep(3.0)

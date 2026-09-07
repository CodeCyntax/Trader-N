"""
Free Real-Time Solana WebSocket Stream for Pump.fun Transactions.
Subscribes directly to on-chain program logs, decoding all live trades, buys, sells,
and bonding curve updates with zero API fees.
"""
import asyncio
import base64
import json
import logging
import struct
import time
from typing import Callable, Optional, List
import base58
import websockets
from core.models import TradeEvent, TradeType
from core.constants import PUMP_PROGRAM_ID, TOKEN_DECIMALS, LAMPORTS_PER_SOL

logger = logging.getLogger("SolanaStream")
# Pump.fun TradeEvent Anchor discriminator: 8 bytes [227, 87, 127, 211, 78, 230, 97, 238]
TRADE_DISCRIMINATOR_PREFIX = "vdt/007mYe4="
FALLBACK_WS_URLS = [
    "wss://api.mainnet-beta.solana.com",
    "wss://solana-rpc.publicnode.com",
]


class SolanaTradeStream:
    """
    Subscribes to Solana public WebSocket to receive and decode all pump.fun trades.
    """

    def __init__(self, on_trade_callback: Callable[[TradeEvent], None]):
        self.on_trade_callback = on_trade_callback
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    def decode_trade_log(self, log_line: str, signature: Optional[str] = None) -> Optional[TradeEvent]:
        """
        Extracts and decodes Borsh binary TradeEvent from 'Program data: ...'
        """
        if not log_line.startswith("Program data: "):
            return None

        raw_b64 = log_line[len("Program data: "):].strip()
        try:
            raw_bytes = base64.b64decode(raw_b64)
            if len(raw_bytes) < 113:
                return None

            # Check discriminator: TradeEvent = [189, 219, 127, 211, 78, 230, 97, 238]
            disc = raw_bytes[:8]
            if disc != b"\xbd\xdb\x7f\xd3\x4e\xe6\x61\xee":
                return None

            mint = base58.b58encode(raw_bytes[8:40]).decode("ascii")
            sol_lamports, token_raw, is_buy = struct.unpack("<QQ?", raw_bytes[40:57])
            user = base58.b58encode(raw_bytes[57:89]).decode("ascii")
            ts, v_sol, v_tokens = struct.unpack("<qQQ", raw_bytes[89:113])

            sol_amount = sol_lamports / LAMPORTS_PER_SOL
            token_amount = token_raw / (10 ** TOKEN_DECIMALS)

            return TradeEvent(
                signature=signature,
                mint=mint,
                tx_type=TradeType.BUY if is_buy else TradeType.SELL,
                sol_amount=sol_amount,
                token_amount=token_amount,
                trader_public_key=user,
                timestamp=float(ts) if ts > 0 else time.time(),
                virtual_sol_reserves=v_sol,
                virtual_token_reserves=v_tokens,
            )
        except Exception as e:
            return None

    async def start(self):
        """Starts the persistent WebSocket connection loop."""
        self.is_running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Stops the streaming loop."""
        self.is_running = False
        if self._task:
            self._task.cancel()

    async def _run_loop(self):
        url_idx = 0
        while self.is_running:
            url = FALLBACK_WS_URLS[url_idx % len(FALLBACK_WS_URLS)]
            try:
                logger.info(f"Connecting to Solana WebSocket: {url}...")
                async with websockets.connect(
                    url,
                    ping_interval=25,
                    ping_timeout=25,
                    max_size=10_000_000,
                ) as ws:
                    sub_payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [PUMP_PROGRAM_ID]},
                            {"commitment": "processed"},
                        ],
                    }
                    await ws.send(json.dumps(sub_payload))
                    sub_ack = await ws.recv()
                    logger.info("Subscribed successfully to live Pump.fun trade logs.")

                    while self.is_running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        value = data.get("params", {}).get("result", {}).get("value")
                        if not value:
                            continue

                        logs = value.get("logs", [])
                        signature = value.get("signature")

                        for line in logs:
                            trade = self.decode_trade_log(line, signature)
                            if trade:
                                self.on_trade_callback(trade)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"WebSocket error on {url}: {e}. Reconnecting in 3s...")
                url_idx += 1
                await asyncio.sleep(3.0)

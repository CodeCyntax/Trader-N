"""
Asynchronous aiohttp Web Server & Real-time WebSocket Hub for Trader-N.
Provides interactive REST APIs and live streaming data to the browser dashboard.
"""
import asyncio
import base64
import csv
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Set, Optional
from aiohttp import web
from core.bonding_curve import PumpBondingCurve

logger = logging.getLogger("WebServer")
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


class WebDashboardServer:
    """
    Hosts the HTTP dashboard and synchronizes real-time state via WebSockets.
    Includes optional HTTP Basic Auth and Token validation for secure 24/7 online hosting.
    """

    def __init__(self, agent, host: str = "0.0.0.0", port: int = 8080):
        self.agent = agent
        self.host = host
        self.port = port
        
        # Authentication Configuration
        self.auth_user = os.getenv("TRADER_AUTH_USER", "admin")
        self.auth_pass = os.getenv("TRADER_AUTH_PASS", "")
        self.auth_enabled = os.getenv("TRADER_AUTH_ENABLED", "1" if self.auth_pass else "0").lower() in ("1", "true", "yes")

        self.app = web.Application(middlewares=[self._create_auth_middleware()])
        self.active_sockets: Set[web.WebSocketResponse] = set()
        self.runner: Optional[web.AppRunner] = None
        self.is_running = False
        self._broadcast_task: Optional[asyncio.Task] = None

        self._setup_routes()

    def _create_auth_middleware(self):
        """
        Creates an aiohttp middleware closure that guards routes with HTTP Basic Auth or query token.
        Allows unauthenticated access to /health for uptime checkers and container health probes.
        """
        @web.middleware
        async def middleware(request: web.Request, handler):
            if not self.auth_enabled:
                return await handler(request)

            # 1. Health check whitelist
            if request.path == "/health":
                return await handler(request)

            # 2. HTTP Basic Auth Header
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                    u, p = decoded.split(":", 1)
                    if u == self.auth_user and p == self.auth_pass:
                        return await handler(request)
                except Exception:
                    pass

            # 3. Query parameter auth (used by browser WebSockets or 1-click download links)
            token = request.query.get("token") or request.query.get("auth")
            if token and token == self.auth_pass:
                return await handler(request)

            return web.Response(
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="Trader-N Private Operational Command"'},
                text="401 Unauthorized: Invalid Trader-N credentials.\n",
            )

        return middleware

    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/ws", self.handle_ws)
        self.app.router.add_static("/static", path=STATIC_DIR, name="static")

        # REST API endpoints
        self.app.router.add_get("/api/token/{mint}", self.handle_get_token)
        self.app.router.add_get("/api/wallet/{address}", self.handle_get_wallet)
        self.app.router.add_post("/api/portfolio/deposit", self.handle_deposit)
        self.app.router.add_post("/api/portfolio/withdraw", self.handle_withdraw)
        self.app.router.add_post("/api/portfolio/set_balance", self.handle_set_balance)
        self.app.router.add_post("/api/portfolio/reset", self.handle_reset)
        self.app.router.add_post("/api/strategy/params", self.handle_update_params)
        self.app.router.add_post("/api/positions/close", self.handle_close_position)
        self.app.router.add_post("/api/agent/toggle", self.handle_toggle_agent)

        # Analytics & Data Exporters
        self.app.router.add_get("/api/analytics/summary", self.handle_analytics_summary)
        self.app.router.add_get("/api/analytics/equity_curve", self.handle_analytics_equity_curve)
        self.app.router.add_get("/api/analytics/export/trades.csv", self.handle_export_trades_csv)
        self.app.router.add_get("/api/analytics/export/learnings.json", self.handle_export_learnings_json)

    async def handle_index(self, request: web.Request) -> web.Response:
        index_path = TEMPLATES_DIR / "index.html"
        if not index_path.exists():
            return web.Response(text="Dashboard template not found", status=404)
        return web.Response(text=index_path.read_text(), content_type="text/html")

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.active_sockets.add(ws)
        logger.info(f"Dashboard client connected. Active clients: {len(self.active_sockets)}")

        # Send immediate state on connect
        try:
            state = self._build_state_payload()
            await ws.send_json({"type": "state_update", "payload": state})

            async for msg in ws:
                pass
        finally:
            self.active_sockets.remove(ws)
            logger.info(f"Dashboard client disconnected. Active clients: {len(self.active_sockets)}")

        return ws

    def _build_state_payload(self) -> dict:
        broker = self.agent.broker
        db = self.agent.db
        summary = broker.get_portfolio_summary()
        closed_trades = db.get_closed_positions(limit=50)
        realized_pnl = sum(r["unrealized_pnl_sol"] for r in closed_trades) if closed_trades else 0.0

        with db.get_connection() as conn:
            burners_count = conn.execute("SELECT COUNT(*) FROM wallets WHERE is_burner = 1").fetchone()[0]
            persistent_count = conn.execute("SELECT COUNT(*) FROM wallets WHERE is_burner = 0 AND persistence_score >= 0.3").fetchone()[0]

        open_pos_list = []
        for p in broker.open_positions.values():
            p_dict = p.model_dump()
            curve = broker.active_curves.get(p.mint) or self.agent.active_tokens.get(p.mint, {}).get("curve")
            if curve:
                p_dict["bonding_progress_pct"] = curve.get_bonding_curve_progress_pct()
                p_dict["market_cap_sol"] = curve.get_market_cap_sol()
                p_dict["virtual_sol"] = curve.virtual_sol / 1e9
            else:
                p_dict["bonding_progress_pct"] = 0.0
                p_dict["market_cap_sol"] = 0.0
                p_dict["virtual_sol"] = 30.0
            open_pos_list.append(p_dict)

        ml_telemetry = {}
        try:
            if hasattr(self.agent, "ml_engine") and self.agent.ml_engine:
                ml_telemetry = self.agent.ml_engine.get_model_telemetry()
        except Exception as e:
            logger.warning(f"Could not retrieve ML telemetry: {e}")

        # Cognitive Organism & Multi-Brain Telemetry
        cognitive_state = {}
        try:
            if hasattr(self.agent, "meta_brain") and self.agent.meta_brain:
                cognitive_state = self.agent.meta_brain.get_telemetry()
            if hasattr(self.agent, "cluster_tracker") and self.agent.cluster_tracker:
                cognitive_state["cluster_summary"] = self.agent.cluster_tracker.get_cluster_summary()
            clusters = db.get_all_clusters(limit=10)
            cognitive_state["top_clusters"] = [c.model_dump() for c in clusters]
        except Exception as e:
            logger.warning(f"Could not retrieve cognitive telemetry: {e}")

        counterfactual_summary = {}
        try:
            if hasattr(self.agent, "counterfactual_engine") and self.agent.counterfactual_engine:
                counterfactual_summary = self.agent.counterfactual_engine.get_summary()
                active_cf = list(self.agent.counterfactual_engine.active_shadows.values())[:10]
                counterfactual_summary["active_shadows"] = [r.model_dump() for r in active_cf]
            else:
                counterfactual_summary = db.get_counterfactual_summary()
        except Exception as e:
            logger.warning(f"Could not retrieve counterfactual summary: {e}")

        recent_decisions = []
        try:
            if hasattr(self.agent, "counterfactual_engine") and self.agent.counterfactual_engine:
                recent_decisions = self.agent.counterfactual_engine.get_recent_decisions(limit=15)
        except Exception as e:
            logger.warning(f"Could not retrieve recent decisions: {e}")

        hypothesis_evolution = {}
        try:
            hypos = db.get_hypotheses(limit=15)
            exp_counts = db.get_experience_counts()
            hypothesis_evolution = {
                "hypotheses": [h.model_dump() for h in hypos],
                "experience_counts": exp_counts,
            }
        except Exception as e:
            logger.warning(f"Could not retrieve hypothesis evolution: {e}")

        analytics_summary = {}
        try:
            analytics_summary = {
                "metrics": db.get_performance_metrics(),
                "equity_curve": db.get_equity_curve_history(limit=50),
            }
        except Exception as e:
            logger.warning(f"Could not retrieve analytics summary: {e}")

        return {
            "portfolio": {
                "cash_sol": summary["cash_sol"],
                "positions_value_sol": summary["positions_value_sol"],
                "total_portfolio_sol": summary["total_portfolio_sol"],
                "unrealized_pnl_sol": summary["unrealized_pnl_sol"],
                "total_realized_pnl": realized_pnl,
            },
            "params": self.agent.params.model_dump(),
            "open_positions": open_pos_list,
            "closed_positions": closed_trades,
            "top_wallets": db.get_top_persistent_wallets(limit=15),
            "recent_learnings": db.get_recent_learnings(limit=10),
            "deep_dive": db.get_agent_deep_dive_metrics(),
            "ml_brain": ml_telemetry,
            "cognitive_state": cognitive_state,
            "counterfactual_summary": counterfactual_summary,
            "recent_decisions": recent_decisions,
            "hypothesis_evolution": hypothesis_evolution,
            "analytics": analytics_summary,
            "stats": {
                "total_burners_screened": burners_count,
                "total_persistent_wallets": persistent_count,
            },
        }

    async def broadcast_trade(self, trade_dict: dict):
        """Immediately broadcasts newly decoded on-chain trades to UI."""
        if not self.active_sockets:
            return
        msg = json.dumps({"type": "new_trade", "payload": trade_dict})
        dead = set()
        for ws in self.active_sockets:
            try:
                await ws.send_str(msg)
            except Exception:
                dead.add(ws)
        self.active_sockets.difference_update(dead)

    async def broadcast_state(self):
        """Immediately forces a state broadcast to all active WebSocket clients."""
        if not self.active_sockets:
            return
        state = self._build_state_payload()
        msg = json.dumps({"type": "state_update", "payload": state})
        dead = set()
        for ws in self.active_sockets:
            try:
                await ws.send_str(msg)
            except Exception:
                dead.add(ws)
        self.active_sockets.difference_update(dead)

    async def _broadcast_loop(self):
        while self.is_running:
            await asyncio.sleep(1.0)
            await self.broadcast_state()

    # --- REST Handlers ---

    async def handle_deposit(self, request: web.Request) -> web.Response:
        data = await request.json()
        amount = float(data.get("amount", 0.0))
        if amount <= 0:
            return web.json_response({"status": "error", "error": "Invalid amount"}, status=400)
        try:
            new_bal = self.agent.db.deposit(amount)
            await self.broadcast_state()
            return web.json_response({"status": "ok", "balance": new_bal})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    async def handle_withdraw(self, request: web.Request) -> web.Response:
        data = await request.json()
        amount = float(data.get("amount", 0.0))
        if amount <= 0:
            return web.json_response({"status": "error", "error": "Invalid amount"}, status=400)
        try:
            new_bal = self.agent.db.withdraw(amount)
            await self.broadcast_state()
            return web.json_response({"status": "ok", "balance": new_bal})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=400)

    async def handle_set_balance(self, request: web.Request) -> web.Response:
        data = await request.json()
        balance = float(data.get("balance", 0.0))
        if balance <= 0:
            return web.json_response({"status": "error", "error": "Invalid balance"}, status=400)
        try:
            if hasattr(self.agent, "soft_reset"):
                new_bal = self.agent.soft_reset(balance)
            else:
                new_bal = self.agent.db.reset_portfolio_balance(balance)
            await self.broadcast_state()
            return web.json_response({"status": "ok", "balance": new_bal})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    async def handle_reset(self, request: web.Request) -> web.Response:
        """
        Handles both Soft Reset (balance only) and Hard Reset (factory wipe).
        Payload: {"type": "soft"|"hard", "balance": float}
        """
        data = await request.json()
        reset_type = str(data.get("type", "soft")).lower()
        balance = float(data.get("balance", 10.0))
        if balance <= 0:
            return web.json_response({"status": "error", "error": "Balance must be positive"}, status=400)

        try:
            if reset_type == "hard":
                if hasattr(self.agent, "hard_reset"):
                    new_bal = self.agent.hard_reset(default_balance=balance)
                else:
                    new_bal = self.agent.db.hard_reset_all_data(default_balance=balance)
                msg = f"Hard reset complete: All history, positions, wallets, and ML weights wiped. Starting balance set to {new_bal:.4f} SOL."
            else:
                if hasattr(self.agent, "soft_reset"):
                    new_bal = self.agent.soft_reset(balance=balance)
                else:
                    new_bal = self.agent.db.reset_portfolio_balance(balance)
                msg = f"Soft reset complete: Paper balance set to {new_bal:.4f} SOL. All learnings and history preserved."

            # Immediately broadcast refreshed clean state to all connected dashboard tabs
            await self.broadcast_state()

            return web.json_response({
                "status": "ok",
                "type": reset_type,
                "balance": new_bal,
                "message": msg,
            })
        except Exception as e:
            logger.error(f"Reset failed ({reset_type}): {e}")
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    async def handle_update_params(self, request: web.Request) -> web.Response:
        data = await request.json()
        try:
            params = self.agent.params
            if "base_trade_sol" in data:
                params.base_trade_sol = float(data["base_trade_sol"])
            if "max_trade_sol" in data:
                params.max_trade_sol = float(data["max_trade_sol"])
            if "trailing_stop_pct" in data:
                params.trailing_stop_pct = float(data["trailing_stop_pct"])
            if "take_profit_pct" in data:
                params.take_profit_pct = float(data["take_profit_pct"])
            if "min_wallet_persistence_score" in data:
                params.min_wallet_persistence_score = float(data["min_wallet_persistence_score"])

            params.version += 1
            self.agent.db.save_strategy_params(params)
            self.agent.params = params
            self.agent.risk_manager.params = params
            self.agent.strategy_evaluator.params = params

            return web.json_response({"status": "ok", "params": params.model_dump()})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=400)

    async def handle_close_position(self, request: web.Request) -> web.Response:
        data = await request.json()
        mint = data.get("mint")
        reason = data.get("reason", "MANUAL_USER_LIQUIDATION")
        if not mint or mint not in self.agent.broker.open_positions:
            return web.json_response({"status": "error", "error": "Position not open"}, status=404)

        try:
            curve = self.agent.active_tokens.get(mint, {}).get("curve")
            closed_res = self.agent.broker.execute_sell(mint, exit_reason=reason, curve=curve)
            if closed_res:
                closed_pos, pnl = closed_res
                # Trigger autopsy
                log = self.agent.post_mortem.conduct_autopsy(closed_pos, curve or PumpBondingCurve())
                self.agent.policy_tuner.update_policy_from_learning(log)
                return web.json_response({"status": "ok", "pnl_sol": pnl})
            return web.json_response({"status": "error", "error": "Execution failed"}, status=500)
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    async def handle_toggle_agent(self, request: web.Request) -> web.Response:
        data = await request.json()
        paused = bool(data.get("paused", False))
        self.agent.is_paused = paused
        return web.json_response({"status": "ok", "paused": self.agent.is_paused})

    async def handle_get_token(self, request: web.Request) -> web.Response:
        mint = request.match_info.get("mint")
        if not mint:
            return web.json_response({"status": "error", "error": "Missing mint"}, status=400)

        token_entry = self.agent.active_tokens.get(mint, {})
        curve = token_entry.get("curve") or self.agent.broker.active_curves.get(mint)
        meta = token_entry.get("meta")

        # Fallback if curve not cached
        if not curve:
            pos = self.agent.broker.open_positions.get(mint)
            if pos:
                curve = self.agent.broker.active_curves.get(mint)

        data = {
            "mint": mint,
            "symbol": meta.symbol if meta else "COIN",
            "name": meta.name if meta else "Pump Token",
            "dev_wallet": meta.creator_address if meta else None,
            "dev_initial_buy_sol": meta.initial_buy_sol if meta else 0.0,
            "spot_price_sol": curve.get_spot_price_sol() if curve else 0.0,
            "market_cap_sol": curve.get_market_cap_sol() if curve else 0.0,
            "bonding_progress_pct": curve.get_bonding_curve_progress_pct() if curve else 0.0,
            "virtual_sol": (curve.virtual_sol / 1e9) if curve else 30.0,
            "real_tokens_remaining": (curve.real_tokens_remaining / 1e6) if curve else 0.0,
            "dexscreener_url": f"https://dexscreener.com/solana/{mint}",
            "pumpfun_url": f"https://pump.fun/coin/{mint}",
            "solscan_url": f"https://solscan.io/token/{mint}",
        }
        return web.json_response({"status": "ok", "token": data})

    async def handle_get_wallet(self, request: web.Request) -> web.Response:
        address = request.match_info.get("address")
        if not address:
            return web.json_response({"status": "error", "error": "Missing address"}, status=400)

        profile = self.agent.wallet_tracker.wallets.get(address)
        if not profile:
            profile = self.agent.db.get_wallet(address)

        if not profile:
            return web.json_response({"status": "error", "error": "Wallet not found"}, status=404)

        data = profile.model_dump()
        data["tokens_traded"] = list(profile.tokens_traded)
        data["solscan_url"] = f"https://solscan.io/account/{address}"
        return web.json_response({"status": "ok", "wallet": data})

    async def handle_health(self, request: web.Request) -> web.Response:
        """Lightweight unauthenticated endpoint for uptime checks and container health probes."""
        return web.json_response({
            "status": "healthy",
            "service": "Trader-N",
            "uptime_active": self.is_running,
            "clients_connected": len(self.active_sockets),
            "timestamp": time.time(),
        })

    async def handle_analytics_summary(self, request: web.Request) -> web.Response:
        """Returns comprehensive performance telemetry, win rate, profit factor, and drawdown."""
        metrics = self.agent.db.get_performance_metrics()
        return web.json_response({"status": "ok", "metrics": metrics})

    async def handle_analytics_equity_curve(self, request: web.Request) -> web.Response:
        """Returns time-series cumulative equity progression across all closed trades."""
        limit = int(request.query.get("limit", 500))
        points = self.agent.db.get_equity_curve_history(limit=limit)
        return web.json_response({"status": "ok", "points": points})

    async def handle_export_trades_csv(self, request: web.Request) -> web.Response:
        """Generates and streams a downloadable RFC-4180 CSV file of all trades."""
        trades = self.agent.db.export_all_trades_rows()
        output = io.StringIO()
        if trades:
            writer = csv.DictWriter(output, fieldnames=list(trades[0].keys()))
            writer.writeheader()
            writer.writerows(trades)
        else:
            output.write("position_id,symbol,mint,status,entry_time,exit_time,hold_duration_seconds,entry_sol_cost,exit_sol_received,entry_price_sol,exit_or_current_price_sol,pnl_sol,pnl_pct,exit_reason,trigger_wallet,confidence_score\n")

        filename = f"trader_n_trades_{int(time.time())}.csv"
        return web.Response(
            text=output.getvalue(),
            content_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    async def handle_export_learnings_json(self, request: web.Request) -> web.Response:
        """Generates and streams a downloadable JSON dump of full episodic learning memory."""
        data = self.agent.db.export_all_learnings_records()
        filename = f"trader_n_learnings_{int(time.time())}.json"
        return web.Response(
            text=json.dumps(data, indent=2),
            content_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    async def start(self):
        """Starts the aiohttp server and broadcast task."""
        self.is_running = True
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        logger.info(f"Dashboard Web UI online at http://localhost:{self.port}")

    async def stop(self):
        """Stops the aiohttp server."""
        self.is_running = False
        if self._broadcast_task:
            self._broadcast_task.cancel()
        for ws in list(self.active_sockets):
            await ws.close()
        if self.runner:
            await self.runner.cleanup()
        logger.info("Dashboard Web UI stopped.")

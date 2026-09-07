"""
Unit tests for Web Dashboard Server and REST APIs.
"""
import unittest
from pathlib import Path
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from memory.database import DatabaseManager
from memory.wallet_tracker import WalletTracker
from engine.paper_broker import PaperBroker
from engine.risk_manager import RiskManager
from engine.strategy_evaluator import StrategyEvaluator
from learning.post_mortem import PostMortemAnalyzer
from learning.policy_tuner import PolicyTuner
from web.server import WebDashboardServer


class MockAgent:
    def __init__(self, db_path: Path):
        self.db = DatabaseManager(db_path)
        self.params = self.db.get_strategy_params()
        self.broker = PaperBroker(self.db)
        self.wallet_tracker = WalletTracker(self.db)
        self.risk_manager = RiskManager(self.params)
        self.strategy_evaluator = StrategyEvaluator(self.wallet_tracker, self.broker, self.risk_manager, self.params)
        self.post_mortem = PostMortemAnalyzer(self.db)
        self.policy_tuner = PolicyTuner(self.db)
        self.active_tokens = {}
        self.is_paused = False


class TestWebServer(AioHTTPTestCase):

    async def get_application(self):
        self.test_db_path = Path("data_store/test_web.db")
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        self.agent = MockAgent(self.test_db_path)
        self.web_server = WebDashboardServer(self.agent, port=8089)
        return self.web_server.app

    async def tearDownAsync(self):
        await super().tearDownAsync()
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    @unittest_run_loop
    async def test_index_page(self):
        """Verify GET / returns 200 and serves HTML template."""
        resp = await self.client.request("GET", "/")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("TRADER-N", text)
        self.assertIn("PUMP.FUN AGENT", text)

    @unittest_run_loop
    async def test_deposit_api(self):
        """Verify POST /api/portfolio/deposit credits balance."""
        resp = await self.client.post("/api/portfolio/deposit", json={"amount": 5.0})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["balance"], 15.0)

    @unittest_run_loop
    async def test_withdraw_api(self):
        """Verify POST /api/portfolio/withdraw debits balance."""
        resp = await self.client.post("/api/portfolio/withdraw", json={"amount": 2.0})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["balance"], 8.0)

    @unittest_run_loop
    async def test_update_params_api(self):
        """Verify POST /api/strategy/params updates strategy hyperparameters."""
        payload = {
            "base_trade_sol": 0.25,
            "max_trade_sol": 0.75,
            "trailing_stop_pct": 0.20,
            "take_profit_pct": 0.60,
            "min_wallet_persistence_score": 0.50,
        }
        resp = await self.client.post("/api/strategy/params", json=payload)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["params"]["base_trade_sol"], 0.25)
        self.assertEqual(data["params"]["min_wallet_persistence_score"], 0.50)

    @unittest_run_loop
    async def test_toggle_agent_api(self):
        """Verify POST /api/agent/toggle toggles pause status."""
        resp = await self.client.post("/api/agent/toggle", json={"paused": True})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["paused"])
        self.assertTrue(self.agent.is_paused)


    @unittest_run_loop
    async def test_get_token_api(self):
        """Verify GET /api/token/{mint} returns token metadata & curve info."""
        resp = await self.client.get("/api/token/So11111111111111111111111111111111111111112")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("token", data)
        self.assertIn("dexscreener_url", data["token"])
        self.assertIn("pumpfun_url", data["token"])

    @unittest_run_loop
    async def test_get_wallet_api(self):
        """Verify GET /api/wallet/{address} returns wallet profile."""
        addr = "CGj5ksNAQ4zUYrRFdqLzhQteL7iY4NeYKKEeX3jeM8bD"
        # Seed wallet in test DB
        from core.models import WalletProfile
        self.agent.db.upsert_wallet(WalletProfile(address=addr, persistence_score=0.85, realized_pnl_sol=4.5))

        resp = await self.client.get(f"/api/wallet/{addr}")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["wallet"]["address"], addr)
        self.assertEqual(data["wallet"]["persistence_score"], 0.85)

    @unittest_run_loop
    async def test_websocket_state_sync(self):
        """Verify WebSocket /ws connects and receives state_update payload with ml_brain."""
        from learning.ml_brain import LocalOnlineMLEngine
        self.agent.ml_engine = LocalOnlineMLEngine(db_manager=self.agent.db)
        ws = await self.client.ws_connect("/ws")
        msg = await ws.receive_json()
        self.assertEqual(msg["type"], "state_update")
        self.assertIn("portfolio", msg["payload"])
        self.assertIn("ml_brain", msg["payload"])
        self.assertIn("weights", msg["payload"]["ml_brain"])
        await ws.close()

    @unittest_run_loop
    async def test_reset_api_soft_and_hard(self):
        """Verify POST /api/portfolio/reset handles both soft and hard reset types."""
        # 1. Soft reset
        resp = await self.client.post("/api/portfolio/reset", json={"type": "soft", "balance": 42.0})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["type"], "soft")
        self.assertEqual(data["balance"], 42.0)
        self.assertEqual(self.agent.db.get_balance(), 42.0)

        # 2. Hard reset
        resp = await self.client.post("/api/portfolio/reset", json={"type": "hard", "balance": 10.0})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["type"], "hard")
        self.assertEqual(data["balance"], 10.0)
        self.assertEqual(self.agent.db.get_balance(), 10.0)

    @unittest_run_loop
    async def test_health_check(self):
        """Verify GET /health returns 200 healthy status."""
        resp = await self.client.get("/health")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "Trader-N")

    @unittest_run_loop
    async def test_analytics_summary_api(self):
        """Verify GET /api/analytics/summary returns performance metrics."""
        resp = await self.client.get("/api/analytics/summary")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("metrics", data)
        self.assertIn("win_rate_pct", data["metrics"])
        self.assertIn("profit_factor", data["metrics"])

    @unittest_run_loop
    async def test_analytics_equity_curve_api(self):
        """Verify GET /api/analytics/equity_curve returns points array."""
        resp = await self.client.get("/api/analytics/equity_curve")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("points", data)
        self.assertGreaterEqual(len(data["points"]), 1)

    @unittest_run_loop
    async def test_export_trades_csv(self):
        """Verify GET /api/analytics/export/trades.csv returns valid CSV attachment."""
        resp = await self.client.get("/api/analytics/export/trades.csv")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/csv", resp.headers.get("Content-Type", ""))
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))
        text = await resp.text()
        self.assertIn("position_id", text)

    @unittest_run_loop
    async def test_export_learnings_json(self):
        """Verify GET /api/analytics/export/learnings.json returns full JSON dump."""
        resp = await self.client.get("/api/analytics/export/learnings.json")
        self.assertEqual(resp.status, 200)
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))
        data = await resp.json()
        self.assertIn("episodic_learnings", data)
        self.assertIn("counterfactual_ledger", data)
        self.assertIn("discovered_hypotheses", data)

    @unittest_run_loop
    async def test_authentication_middleware_enabled(self):
        """Verify that when authentication is enabled, unauthorized requests are rejected."""
        server = self.web_server
        server.auth_enabled = True
        server.auth_user = "testadmin"
        server.auth_pass = "supersecret123"

        # 1. Unauthenticated request to / -> 401
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 401)
        self.assertIn("WWW-Authenticate", resp.headers)

        # 2. Health check bypasses auth -> 200
        resp_health = await self.client.get("/health")
        self.assertEqual(resp_health.status, 200)

        # 3. Authenticated request with Basic Auth -> 200
        import base64
        token_b64 = base64.b64encode(b"testadmin:supersecret123").decode()
        resp_auth = await self.client.get("/", headers={"Authorization": f"Basic {token_b64}"})
        self.assertEqual(resp_auth.status, 200)

        # 4. Authenticated request with query token -> 200
        resp_query = await self.client.get("/?token=supersecret123")
        self.assertEqual(resp_query.status, 200)

        # Reset server auth
        server.auth_enabled = False


if __name__ == "__main__":
    unittest.main()



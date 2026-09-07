# Trader-N: Autonomous Solana & Pump.fun AI Trading Agent

Trader-N is a custom-engineered, fully autonomous trading and cognitive learning agent designed specifically for high-volatility **Pump.fun** bonding curves and Solana DEX tokens.

Built with an ultra-realistic paper execution engine (exact constant product math, AMM curve slippage, and on-chain network priority fees), a smart wallet persistence profiler that actively eliminates one-off burner/sybil wallets, and an episodic retrospective learning loop that dynamically adapts strategy parameters from real trade outcomes.

---

## ⚡ Core Pillars & Architecture

1. **100% Free Live Streaming Pipeline**:
   - **Solana Public WebSocket Logs**: Subscribes directly to on-chain program logs for Pump.fun (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`), decoding real-time Anchor `TradeEvent` binary payloads (over 40+ trades per second with zero API fees).
   - **PumpPortal New Token Stream**: Ingests freshly created tokens, metadata, and dev creator wallet addresses in real time.

2. **Mathematically Exact Paper Broker (Zero Fake Math)**:
   - Evaluates fills directly against the Pump.fun constant product bonding curve formula ($x \cdot y = k$) with virtual reserves ($30\text{ SOL} \times 1,073,000,000\text{ tokens}$).
   - Accurately deducts the 1.0% platform fee and models realistic Solana priority fees (0.0005 SOL) and base transaction fees (5,000 lamports).
   - Simulates real price impact based on trade size relative to pool liquidity.

3. **Smart Wallet Persistence & Anti-Burner Profiler**:
   - Rejects single-token deployer/insider burner wallets and one-hit snipers.
   - Calculates continuous persistence scores based on multi-day activity, multi-token diversity ($\ge 3$ distinct tokens), win rate, and realized SOL profit.

4. **Autonomous Sizing & Dynamic Exits**:
   - **Position Sizing**: Starts conservatively at 0.10 SOL on cold start and scales up autonomously (capped at 15% portfolio allocation or 0.40–0.50 SOL) as confidence and wallet track records increase.
   - **Holding Time Decisions**: The agent autonomously determines exits using real-time market catalysts:
     - *Emergency Dev Dump*: Detects large sales from token creators and immediately exits.
     - *Tracked Wallet Exit*: Follows exits when the leading smart wallet liquidates.
     - *Dynamic Trailing Stop*: Trails behind peak prices (18% standard, tightens to 9% when in high profit to protect gains).
     - *Momentum Stall*: Automatically liquidates if bonding curve volume freezes.

5. **Episodic Learning & Policy Tuning**:
   - After every closed trade, the agent conducts an autopsy categorizing the outcome (`HIGH_CONVICTION_WIN`, `TRAILING_STOP_PROFIT`, `DEV_RUG`, `TRAILING_STOP_LOSS`, `MOMENTUM_STALL`).
   - Dynamically adapts hyperparameters (increments `min_wallet_persistence_score`, adjusts `max_dev_holding_pct`, tunes sizing limits) and persists strategy versions to SQLite.

---

## 🚀 Quick Start: Launching the Web App & Agent

All dependencies are pre-installed in the local `.venv`.

### 1. Launch the Live Trading Agent + Web Dashboard
Run the agent and open the interactive web dashboard in your browser:
```bash
.venv/bin/python main.py --port 8080
```
Then navigate to:
👉 **`http://localhost:8080`**

From the Web UI, you can:
- **Watch Live Stream**: Real-time Solana on-chain trades and newly minted tokens ticking live.
- **Inspect Positions**: View active position cards with live PnL %, peak price, and dynamic trailing stop lines.
- **Manual Liquidation**: Hit the "Liquidate Position" button on any active card to execute an immediate exit.
- **Capital Operations**: Deposit, withdraw, or reset paper SOL balance directly from the UI header modals.
- **Smart Wallet Dossier**: Inspect the top persistent wallets and view the count of screened burner wallets.
- **AI Learning Log**: Read post-trade autopsies and view how hyperparameters self-tune over time.
- **Strategy Sliders**: Tweak base trade size, max trade size, trailing stop %, and minimum persistence score live.

### 2. Run Headless in Terminal (Without Browser UI)
If you prefer running strictly in the terminal:
```bash
.venv/bin/python main.py --no-web --interval 15
```

### 3. Inspect Analytics from Terminal
```bash
.venv/bin/python main.py --mode analyze
```

### 3. Adjust Portfolio Capital
Set, deposit, or withdraw paper trading capital at any time:
```bash
# Set specific balance (e.g. 10 SOL)
.venv/bin/python main.py --balance 10.0

# Deposit funds (e.g. add 5 SOL)
.venv/bin/python main.py --deposit 5.0

# Withdraw funds (e.g. withdraw 2 SOL)
.venv/bin/python main.py --withdraw 2.0
```

---

## 🧪 Running Automated Tests
Run the comprehensive test suite verifying bonding curve math, wallet filtering, paper execution, and the learning engine:
```bash
.venv/bin/python -m unittest discover -s tests -p "test_*.py" -v
```

---

## 📂 Project Directory Structure

```
Trader-N/
├── config/                  # Configuration & settings
├── core/
│   ├── constants.py         # Protocol parameters, fees, and thresholds
│   ├── bonding_curve.py     # Exact invariant k = vSol * vToken math
│   └── models.py            # Pydantic models for trades, wallets, positions
├── data/
│   ├── solana_stream.py     # Free on-chain Solana WebSocket log decoder
│   └── pumpportal_stream.py # Free PumpPortal token creation stream
├── memory/
│   ├── database.py          # SQLite persistence layer (WAL mode)
│   └── wallet_tracker.py    # Multi-dimensional persistence & anti-sybil engine
├── engine/
│   ├── paper_broker.py      # Exact fill execution, slippage & fee modeling
│   ├── risk_manager.py      # Trailing stops, profit targets & dynamic sizing
│   └── strategy_evaluator.py# Smart wallet entry trigger synthesizer
├── learning/
│   ├── post_mortem.py       # Retrospective trade autopsy & causal attribution
│   ├── policy_tuner.py      # Dynamic parameter & hyperparameter updater
│   └── dashboard_reporter.py# Visual terminal dashboard formatter
├── tests/                   # 13 comprehensive unit tests
├── main.py                  # Main CLI entrypoint
└── requirements.txt         # Project dependencies
```

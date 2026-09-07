"""
Constants and configuration defaults for the Pump.fun & Solana DEX AI Trading System.
"""
from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data_store"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "trader.db"

# Solana & Pump.fun Protocol Constants
PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
TOKEN_DECIMALS = 6
SOL_DECIMALS = 9
LAMPORTS_PER_SOL = 1_000_000_000

# Pump.fun Constant Product Invariant Parameters
# Initial Virtual SOL: 30 SOL in lamports
INITIAL_VIRTUAL_SOL_LAMPORTS = 30 * LAMPORTS_PER_SOL
# Initial Virtual Tokens: 1,073,000,000 with 6 decimals
INITIAL_VIRTUAL_TOKEN_RESERVES = 1_073_000_000 * (10 ** TOKEN_DECIMALS)
# Invariant K = vSol * vToken
INITIAL_INVARIANT_K = INITIAL_VIRTUAL_SOL_LAMPORTS * INITIAL_VIRTUAL_TOKEN_RESERVES
# Total tokens allocated to the bonding curve in Pump.fun protocol (793.1M tokens, leaving 206.9M for Raydium)
BONDING_CURVE_REAL_TOKEN_RESERVES = 793_100_000 * (10 ** TOKEN_DECIMALS)
# Exact SOL required to complete the bonding curve: (k / (1073M - 793.1M)) - 30 SOL = 85.005359 SOL
MIGRATION_SOL_LAMPORTS = 85_005_359_056
SPL_ATA_RENT_EXEMPT_LAMPORTS = 2_039_280  # 165 bytes rent-exempt reserve for Associated Token Account

# Fee Structures
PUMP_FEE_BPS = 100  # 1.00% platform fee
SOLANA_BASE_FEE_LAMPORTS = 5_000  # 0.000005 SOL
SIMULATED_PRIORITY_FEE_LAMPORTS = 500_000  # 0.0005 SOL (realistic Jito/priority fee for competitive inclusion)
LATENCY_SLIPPAGE_BPS = 35  # 0.35% (35 bps) conservative adverse latency slippage for 1-slot propagation delay

# Data Streams & Free Endpoints
PUMP_PORTAL_WS_URL = "wss://pumpportal.fun/api/data"
DEFAULT_PUBLIC_RPCS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-rpc.publicnode.com",
    "https://rpc.ankr.com/solana",
]

# Smart Wallet Filtering Criteria (Anti-Burner / Anti-Sybil)
MIN_WALLET_TRADES_FOR_EVAL = 5       # Ignore wallets with fewer than 5 trades
MIN_DISTINCT_TOKENS_TRADED = 3       # Must trade multiple tokens, not just dev's own single coin
MIN_WALLET_ACTIVE_HOURS = 24.0       # Must have activity span of at least 24 hours
MIN_WIN_RATE_THRESHOLD = 0.55        # Minimum 55% win rate to be considered "smart"
MIN_PERSISTENCE_SCORE = 0.40         # Cutoff for smart money tracking

# Autonomous Sizing Defaults
INITIAL_BASE_TRADE_SOL = 0.10        # Cold-start simulated trade size
MAX_POSITION_SIZE_SOL = 0.50         # Scaled maximum trade size for high-confidence signals
MAX_PORTFOLIO_ALLOCATION_PCT = 0.15  # Never risk more than 15% of total balance on a single trade
MAX_CONCURRENT_POSITIONS = 3         # Max simultaneous active positions

# Risk Safeguards
DEFAULT_TRAILING_STOP_PCT = 0.18     # 18% trailing stop from peak price
DEFAULT_TAKE_PROFIT_PCT = 0.50       # 50% first TP milestone (or dynamic exit on momentum exhaustion)
MAX_HOLDING_TIME_SECONDS = 1800      # 30-minute max time safety exit if momentum stalls

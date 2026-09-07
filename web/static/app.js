/**
 * Trader-N Frontend Application.
 * Handles real-time WebSocket state synchronization, live ticker,
 * interactive DexScreener charts, 1-click copy buttons, smart wallet dossier,
 * learning logs, and portfolio controls.
 */

let ws = null;
let currentTab = 'positionsTab';
let isAgentPaused = false;
let paramsLoaded = false;
let currentModalMint = null;

// --- Tab Switching ---
function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
    document.querySelectorAll('.tab-btn').forEach(el => {
        el.classList.remove('text-accent-cyan', 'border-accent-cyan', 'font-semibold');
        el.classList.add('text-gray-400', 'border-transparent', 'font-medium');
    });

    const targetTab = document.getElementById(tabId);
    const targetBtn = document.getElementById('tabBtn-' + tabId);
    if (targetTab) targetTab.classList.remove('hidden');
    if (targetBtn) {
        targetBtn.classList.remove('text-gray-400', 'border-transparent', 'font-medium');
        targetBtn.classList.add('text-accent-cyan', 'border-accent-cyan', 'font-semibold');
    }
    currentTab = tabId;
}

// --- Modal Helpers ---
function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('hidden');
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('hidden');
    // If closing chart modal, clear iframe src to stop background video/network
    if (id === 'tokenChartModal') {
        const iframe = document.getElementById('tokenChartIframe');
        if (iframe) iframe.src = '';
    }
}

// --- Clipboard & Toast Helpers ---
function copyToClipboard(text, label = 'Address') {
    if (!text) return;
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text);
    } else {
        const el = document.createElement('textarea');
        el.value = text;
        el.style.position = 'fixed';
        el.style.left = '-9999px';
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
    }
    showToast('Copied to Clipboard!', `${label}: ${text.slice(0, 8)}...${text.slice(-6)}`, 'success');
}

function copyModalMint() {
    const mint = document.getElementById('modalTokenMint').innerText;
    if (mint) copyToClipboard(mint, 'Token CA');
}

function copyModalDev() {
    const addr = document.getElementById('modalDevAddress').innerText;
    if (addr && addr !== 'Unknown') copyToClipboard(addr, 'Dev Wallet');
}

function copyModalTrigger() {
    const addr = document.getElementById('modalTriggerWallet').innerText;
    if (addr && addr !== 'None') copyToClipboard(addr, 'Trigger Wallet');
}

function copyWalletDossierAddr() {
    const addr = document.getElementById('modalWalletFullAddress').innerText;
    if (addr) copyToClipboard(addr, 'Wallet');
}

function showToast(title, message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    const borderClass = type === 'success' ? 'border-accent-emerald/40 bg-dark-800' : 'border-dark-600 bg-dark-800';
    const icon = type === 'success' 
        ? '<i data-lucide="check-circle" class="w-4 h-4 text-accent-emerald flex-shrink-0"></i>' 
        : '<i data-lucide="info" class="w-4 h-4 text-accent-cyan flex-shrink-0"></i>';

    toast.className = `p-3 rounded-xl border ${borderClass} shadow-2xl flex items-center space-x-2.5 text-xs text-white max-w-sm pointer-events-auto transition transform translate-y-2 opacity-0 duration-300`;
    toast.innerHTML = `
        ${icon}
        <div>
            <div class="font-bold text-white">${title}</div>
            <div class="text-gray-400 text-[11px]">${message}</div>
        </div>
    `;

    container.appendChild(toast);
    lucide.createIcons();

    setTimeout(() => {
        toast.classList.remove('translate-y-2', 'opacity-0');
    }, 10);

    setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-y-2');
        setTimeout(() => toast.remove(), 300);
    }, 3200);
}

// --- WebSocket Connection ---
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        const badge = document.getElementById('wsStatusText');
        if (badge) {
            badge.innerText = 'SOLANA MAINNET CONNECTED';
            badge.className = 'text-emerald-400 font-medium';
        }
    };

    ws.onclose = () => {
        const badge = document.getElementById('wsStatusText');
        if (badge) {
            badge.innerText = 'RECONNECTING TO AGENT...';
            badge.className = 'text-amber-400 font-medium';
        }
        setTimeout(connectWebSocket, 2000);
    };

    ws.onerror = (err) => {
        console.error('WebSocket Error:', err);
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'state_update') {
                updateDashboard(data.payload);
            } else if (data.type === 'new_trade') {
                appendTradeTicker(data.payload);
            }
        } catch (e) {
            console.error('Error parsing WebSocket message:', e);
        }
    };
}

function setText(id, text, className) {
    const el = document.getElementById(id);
    if (!el) return;
    if (text !== undefined && text !== null) el.innerText = text;
    if (className) el.className = className;
}

// --- Dashboard State Updates ---
function updateDashboard(state) {
    const portfolio = state.portfolio || {};
    const params = state.params || {};
    const openPositions = state.open_positions || [];
    const closedPositions = state.closed_positions || [];
    const topWallets = state.top_wallets || [];
    const learnings = state.recent_learnings || [];
    const stats = state.stats || {};

    // 1. Navigation & Portfolio Cards
    const cash = portfolio.cash_sol || 0.0;
    const posVal = portfolio.positions_value_sol || 0.0;
    const totalEquity = cash + posVal;

    setText('navCashBalance', `${cash.toFixed(3)} SOL`);
    setText('statTotalEquity', `${totalEquity.toFixed(4)} SOL`);
    setText('statEquitySub', `Cash: ${cash.toFixed(3)} | In Trades: ${posVal.toFixed(3)}`);

    // Realized PnL & Win Rate
    const realizedPnl = portfolio.total_realized_pnl || 0.0;
    setText('statRealizedPnl', `${realizedPnl >= 0 ? '+' : ''}${realizedPnl.toFixed(4)} SOL`, `text-xl font-bold mt-1 ${realizedPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`);

    const wins = closedPositions.filter(p => (p.unrealized_pnl_sol || 0) > 0).length;
    const totalClosed = closedPositions.length;
    const winRate = totalClosed > 0 ? (wins / totalClosed * 100.0).toFixed(1) : '0.0';
    setText('statWinRate', `Win Rate: ${winRate}% (${wins}/${totalClosed} closed)`);

    // Active Trades Count
    setText('statOpenPositionsCount', `${openPositions.length} Open`);
    setText('posBadgeCount', openPositions.length);
    const unrealizedTotal = openPositions.reduce((acc, p) => acc + (p.unrealized_pnl_sol || 0), 0);
    setText('statUnrealizedPnl', `Unrealized: ${unrealizedTotal >= 0 ? '+' : ''}${unrealizedTotal.toFixed(3)} SOL`, `text-xs mt-0.5 ${unrealizedTotal >= 0 ? 'text-emerald-400' : 'text-rose-400'}`);

    // Persistent Wallets Badge
    setText('statPersistentWallets', `${topWallets.length} Tracked`);
    setText('statBurnersScreened', `${stats.total_burners_screened || 0} Burners Rejected`);
    setText('burnerCountBadge', `${stats.total_burners_screened || 0} Burners Screened & Rejected`);

    // Strategy Parameters Ribbon
    setText('statPolicyVersion', `v${params.version || 1} (Base: ${params.base_trade_sol || 0.1} SOL)`);
    setText('statMinPersistence', `Min Persistence: ${(params.min_wallet_persistence_score || 0.4).toFixed(2)}`);

    // Form inputs prefill
    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el && val !== undefined && val !== null) el.value = val;
    };
    if (!paramsLoaded && params.version) {
        setVal('paramBaseSize', params.base_trade_sol);
        setVal('paramMaxSize', params.max_trade_sol);
        setVal('paramTrailingStop', params.trailing_stop_pct);
        setVal('paramTakeProfit', params.take_profit_pct);
        setVal('paramMinPersistence', params.min_wallet_persistence_score);
        paramsLoaded = true;
    }

    // 2. Render Open Positions Cards
    try { renderPositions(openPositions); } catch (e) { console.error('renderPositions error:', e); }

    // 3. Render Top Persistent Wallets
    try { renderWallets(topWallets); } catch (e) { console.error('renderWallets error:', e); }

    // 4. Render AI Learnings & Deep Dive
    try { renderLearnings(learnings); } catch (e) { console.error('renderLearnings error:', e); }
    try {
        if (state.deep_dive) {
            renderDeepDive(state.deep_dive, params);
        }
    } catch (e) { console.error('renderDeepDive error:', e); }

    // 5. Render Cognitive Organism, Multi-Brain Decisions & Counterfactual Ledger
    try {
        renderCognitiveOrganism(state);
    } catch (e) { console.error('renderCognitiveOrganism error:', e); }

    // 6. Render Analytics, Equity Curve & Historical Trade Performance
    try {
        renderAnalytics(state.analytics, state.closed_positions);
    } catch (e) { console.error('renderAnalytics error:', e); }
}

// --- Position Cards Rendering ---
function renderPositions(positions) {
    const container = document.getElementById('positionsContainer');
    if (!container) return;

    if (!positions || positions.length === 0) {
        container.innerHTML = `
            <div class="bg-dark-800 border border-dark-600 rounded-xl p-8 text-center text-gray-500 text-sm">
                <i data-lucide="inbox" class="w-8 h-8 mx-auto mb-2 opacity-50"></i>
                No active positions. Scanning live Solana stream for high-persistence smart money entries...
            </div>
        `;
        lucide.createIcons();
        return;
    }

    let html = '';
    for (const pos of positions) {
        const isProfitable = pos.unrealized_pnl_pct >= 0;
        const pnlClass = isProfitable ? 'text-emerald-400' : 'text-rose-400';
        const progress = pos.bonding_progress_pct || 0.0;

        html += `
            <div class="bg-dark-800 border border-dark-600 rounded-xl p-4 transition hover:border-dark-500 space-y-3 shadow-lg">
                <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-3">
                        <div class="w-10 h-10 rounded-xl bg-accent-purple/20 text-accent-purple flex items-center justify-center font-bold text-xs border border-accent-purple/30">
                            ${pos.symbol.slice(0, 3)}
                        </div>
                        <div>
                            <div class="flex items-center space-x-2 flex-wrap gap-y-1">
                                <span class="text-white font-bold text-sm">${pos.symbol}</span>
                                ${pos.is_moonbag ? `<span class="px-2 py-0.5 rounded text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/30 font-bold">💎 MOONBAG (RISK-FREE)</span>` : ''}
                                ${(pos.realized_sol_harvested || 0) > 0 ? `<span class="px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-mono font-semibold">+${pos.realized_sol_harvested.toFixed(3)} SOL LOCKED</span>` : ''}
                                <span class="text-[11px] text-accent-cyan font-mono">${pos.mint.slice(0, 6)}...${pos.mint.slice(-4)}</span>
                                <button onclick="copyToClipboard('${pos.mint}', 'Token CA')" class="text-gray-400 hover:text-white transition p-0.5" title="Copy Mint Contract Address">
                                    <i data-lucide="copy" class="w-3 h-3"></i>
                                </button>
                                <a href="https://pump.fun/coin/${pos.mint}" target="_blank" class="text-gray-400 hover:text-accent-emerald transition p-0.5" title="View on Pump.fun">
                                    <i data-lucide="external-link" class="w-3 h-3"></i>
                                </a>
                            </div>
                            <div class="flex items-center space-x-2 text-[11px] text-gray-400 mt-0.5">
                                <span>Trigger:</span>
                                ${pos.trigger_wallet ? `
                                    <button onclick="openWalletModal('${pos.trigger_wallet}')" class="font-mono text-accent-cyan hover:underline flex items-center space-x-1">
                                        <span>${pos.trigger_wallet.slice(0, 5)}...</span>
                                    </button>
                                ` : '<span class="text-gray-500">DIRECT</span>'}
                                <span>|</span>
                                <span>Conf: ${(pos.confidence_score * 100).toFixed(0)}%</span>
                            </div>
                        </div>
                    </div>
                    <div class="text-right">
                        <div class="text-base font-bold font-mono ${pnlClass}">
                            ${pos.unrealized_pnl_pct >= 0 ? '+' : ''}${pos.unrealized_pnl_pct.toFixed(2)}%
                        </div>
                        <div class="text-[11px] font-mono ${pnlClass}">
                            ${pos.unrealized_pnl_sol >= 0 ? '+' : ''}${pos.unrealized_pnl_sol.toFixed(4)} SOL
                        </div>
                    </div>
                </div>

                <!-- Bonding Curve Progress Bar -->
                <div class="bg-dark-900/40 p-2.5 rounded-lg border border-dark-700/50 space-y-1">
                    <div class="flex justify-between text-[10px] text-gray-400 font-mono">
                        <span class="flex items-center space-x-1">
                            <i data-lucide="activity" class="w-3 h-3 text-accent-cyan"></i>
                            <span>Curve Migration:</span>
                        </span>
                        <span class="text-accent-cyan font-bold">${progress.toFixed(1)}%</span>
                    </div>
                    <div class="w-full bg-dark-700 h-1.5 rounded-full overflow-hidden">
                        <div class="bg-gradient-to-r from-accent-cyan to-accent-emerald h-full rounded-full transition-all duration-300" style="width: ${Math.min(100, Math.max(0, progress))}%"></div>
                    </div>
                </div>

                <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 border-t border-dark-700 text-xs text-gray-400 font-mono">
                    <div>
                        <span class="text-[10px] text-gray-500 block">COST:</span>
                        <span class="text-gray-200">${pos.entry_sol_cost.toFixed(3)} SOL</span>
                    </div>
                    <div>
                        <span class="text-[10px] text-gray-500 block">CURRENT VAL:</span>
                        <span class="text-gray-200">${pos.current_value_sol.toFixed(3)} SOL</span>
                    </div>
                    <div>
                        <span class="text-[10px] text-gray-500 block">PEAK PRICE:</span>
                        <span class="text-gray-200">${pos.highest_price_sol.toFixed(7)}</span>
                    </div>
                    <div>
                        <span class="text-[10px] text-gray-500 block">CURRENT PRICE:</span>
                        <span class="text-gray-200">${pos.current_price_sol.toFixed(7)}</span>
                    </div>
                </div>

                <div class="flex items-center justify-between pt-1">
                    <button onclick="openTokenChartModal('${pos.mint}')" class="bg-accent-cyan/10 hover:bg-accent-cyan/20 text-accent-cyan border border-accent-cyan/30 px-3 py-1 rounded-lg text-xs font-semibold flex items-center space-x-1.5 transition">
                        <i data-lucide="bar-chart-2" class="w-3.5 h-3.5"></i>
                        <span>Live Chart & Analysis</span>
                    </button>
                    <button onclick="emergencyClose('${pos.mint}')" class="bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 px-3 py-1 rounded-lg text-xs font-semibold flex items-center space-x-1.5 transition">
                        <i data-lucide="x" class="w-3.5 h-3.5"></i>
                        <span>Liquidate Position</span>
                    </button>
                </div>
            </div>
        `;
    }
    container.innerHTML = html;
    lucide.createIcons();
}

// --- Smart Wallets Dossier Rendering ---
function renderWallets(wallets) {
    const tbody = document.getElementById('walletsTableBody');
    if (!tbody) return;

    if (!wallets || wallets.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-gray-500">Profiling live on-chain traders... Filtering out one-off burners...</td></tr>`;
        return;
    }

    let html = '';
    let rank = 1;
    for (const w of wallets) {
        const closed = w.closed_trades || 0;
        const total = w.total_trades || 0;
        const wins = w.profitable_trades || 0;
        const wr = closed > 0 ? (wins / closed * 100).toFixed(1) : '0.0';
        const isPos = w.realized_pnl_sol > 0;
        const pnlColor = isPos ? 'text-emerald-400 font-semibold' : 'text-gray-400';

        let rankBadge = `<span class="text-gray-400 font-mono text-xs w-6 inline-block text-center">#${rank}</span>`;
        if (rank === 1) rankBadge = `<span class="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold text-xs border border-amber-500/30">#1 👑</span>`;
        else if (rank === 2) rankBadge = `<span class="px-1.5 py-0.5 rounded bg-slate-400/20 text-slate-200 font-bold text-xs border border-slate-400/30">#2 🥈</span>`;
        else if (rank === 3) rankBadge = `<span class="px-1.5 py-0.5 rounded bg-amber-700/20 text-amber-500 font-bold text-xs border border-amber-700/30">#3 🥉</span>`;

        const isElite = w.persistence_score >= 0.40;
        const badgeClass = isElite 
            ? 'bg-accent-emerald/10 text-accent-emerald border border-accent-emerald/30 font-bold' 
            : 'bg-dark-700 text-gray-400 border border-dark-600 font-medium';

        html += `
            <tr class="hover:bg-dark-700/50 transition">
                <td class="py-3 px-3 flex items-center space-x-2">
                    ${rankBadge}
                    <button onclick="openWalletModal('${w.address}')" class="font-mono text-accent-cyan hover:underline text-left" title="Inspect Wallet Dossier">
                        ${w.address.slice(0, 6)}...${w.address.slice(-4)}
                    </button>
                    <button onclick="copyToClipboard('${w.address}', 'Wallet Address')" class="text-gray-500 hover:text-white transition p-0.5" title="Copy Wallet Address">
                        <i data-lucide="copy" class="w-3 h-3"></i>
                    </button>
                    <a href="https://solscan.io/account/${w.address}" target="_blank" class="text-gray-500 hover:text-accent-cyan transition p-0.5" title="View on Solscan">
                        <i data-lucide="external-link" class="w-3 h-3"></i>
                    </a>
                </td>
                <td class="py-3 px-3 font-bold text-white text-sm font-mono">${w.persistence_score.toFixed(3)}</td>
                <td class="py-3 px-3 font-mono text-xs text-gray-200">${closed} <span class="text-gray-500">/ ${total}</span></td>
                <td class="py-3 px-3 font-mono text-xs">${w.tokens_traded_count} coins</td>
                <td class="py-3 px-3 text-emerald-400 font-bold font-mono text-sm">${wr}%</td>
                <td class="py-3 px-3 font-mono ${pnlColor}">${isPos ? '+' : ''}${w.realized_pnl_sol.toFixed(3)} SOL</td>
                <td class="py-3 px-3 text-gray-400 font-mono">${w.active_hours.toFixed(1)}h</td>
                <td class="py-3 px-3">
                    <span class="px-2 py-0.5 rounded text-[10px] ${badgeClass}">
                        ${isElite ? 'ELITE HUNTER' : 'QUALIFIED'}
                    </span>
                </td>
            </tr>
        `;
        rank++;
    }
    tbody.innerHTML = html;
    lucide.createIcons();
}

// --- AI Learnings Rendering ---
function renderLearnings(learnings) {
    const container = document.getElementById('learningLogsContainer');
    if (!container) return;

    if (!learnings || learnings.length === 0) {
        container.innerHTML = `
            <div class="text-center py-8 text-gray-500 text-sm">
                No closed trades yet. The agent logs a complete causal autopsy whenever a position exits.
            </div>
        `;
        return;
    }

    let html = '';
    for (const l of learnings) {
        const isWin = l.net_pnl_sol >= 0;
        const color = isWin ? 'text-emerald-400' : 'text-rose-400';
        const badgeBg = isWin ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20';

        html += `
            <div class="p-4 rounded-xl bg-dark-700/40 border border-dark-600 space-y-2">
                <div class="flex items-center justify-between text-xs">
                    <div class="flex items-center space-x-2">
                        <span class="px-2 py-0.5 rounded font-bold border ${badgeBg}">${l.outcome_category}</span>
                        <span class="font-mono text-gray-300">${l.mint ? l.mint.slice(0, 6) + '...' : 'UNKNOWN'}</span>
                        <button onclick="copyToClipboard('${l.mint}', 'Mint CA')" class="text-gray-500 hover:text-white" title="Copy CA">
                            <i data-lucide="copy" class="w-3 h-3"></i>
                        </button>
                        <button onclick="openTokenChartModal('${l.mint}')" class="text-gray-500 hover:text-accent-cyan" title="View Chart">
                            <i data-lucide="bar-chart-2" class="w-3 h-3"></i>
                        </button>
                    </div>
                    <span class="font-mono font-bold ${color}">${l.net_pnl_sol >= 0 ? '+' : ''}${l.net_pnl_sol.toFixed(4)} SOL (${l.net_pnl_pct.toFixed(1)}%)</span>
                </div>
                <p class="text-xs text-gray-300 leading-relaxed">${l.lesson_learned}</p>
                <div class="flex items-center justify-between text-[11px] text-gray-500 font-mono pt-1 border-t border-dark-600/50">
                    <span>Trigger: ${l.trigger_wallet ? l.trigger_wallet.slice(0, 6) + '...' : 'DIRECT'}</span>
                    <span>Reason: ${l.exit_reason}</span>
                    <span>Curve: ${l.curve_pct_at_entry}% &rarr; ${l.curve_pct_at_exit}%</span>
                </div>
            </div>
        `;
    }
    container.innerHTML = html;
    lucide.createIcons();
}

// --- Agent Cognitive Brain & Deep Dive Rendering ---
function renderDeepDive(d) {
    if (!d) return;

    // 1. Cognitive Evolution Ribbon
    const evo = d.cognitive_evolution || {};
    const kScore = evo.knowledge_score || 0;
    const kBar = document.getElementById('deepKnowledgeBar');
    if (kBar && kBar.style) kBar.style.width = `${Math.min(100, Math.max(0, kScore))}%`;

    const elKScore = document.getElementById('deepKnowledgeScore');
    if (elKScore) elKScore.innerText = kScore.toFixed(0);

    const elAutopsies = document.getElementById('deepAutopsiesCount');
    if (elAutopsies) elAutopsies.innerText = `${evo.total_autopsies_conducted || 0} autopsies conducted`;

    const elPf = document.getElementById('deepProfitFactor');
    if (elPf) elPf.innerText = `${(d.profit_factor || 1.0).toFixed(2)}x`;

    const elWl = document.getElementById('deepWinLossRatio');
    if (elWl) elWl.innerText = `${d.wins_count || 0}W / ${d.losses_count || 0}L`;

    const elWr = document.getElementById('deepWinRatePct');
    if (elWr) elWr.innerText = `${(d.win_rate_pct || 0).toFixed(1)}%`;

    const elNet = document.getElementById('deepNetProfitSol');
    if (elNet) {
        const net = d.net_profit_sol || 0.0;
        elNet.innerText = `${net >= 0 ? '+' : ''}${net.toFixed(3)} SOL`;
        elNet.className = net >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
    }

    const elVer = document.getElementById('deepPolicyVer');
    if (elVer) elVer.innerText = `v${evo.policy_version || 1}`;

    const elVel = document.getElementById('deepVelocity');
    if (elVel) elVel.innerText = `${evo.adaptation_velocity || 0} shifts/10tr`;

    const elRugs = document.getElementById('deepRugsBlocked');
    if (elRugs) elRugs.innerText = evo.dev_rugs_mitigated || 0;

    const elStops = document.getElementById('deepStopsLocked');
    if (elStops) elStops.innerText = evo.trailing_stops_locked || 0;

    const elMaxWin = document.getElementById('deepMaxWinPct');
    if (elMaxWin) elMaxWin.innerText = `+${(d.max_win_pct || 0).toFixed(1)}%`;

    const elMaxLoss = document.getElementById('deepMaxLossPct');
    if (elMaxLoss) elMaxLoss.innerText = `${(d.max_loss_pct || 0).toFixed(1)}%`;

    const elAvgWin = document.getElementById('deepAvgWinPct');
    if (elAvgWin) elAvgWin.innerText = `+${(d.avg_win_pct || 0).toFixed(1)}%`;

    // 2. Multiplier Distribution
    const dist = d.distribution || {};
    const elMoon = document.getElementById('distMoonshots');
    if (elMoon) elMoon.innerText = dist.moonshots_100x_plus || 0;

    const elRun = document.getElementById('distRunners');
    if (elRun) elRun.innerText = dist.runners_25_to_100 || 0;

    const elScalp = document.getElementById('distScalps');
    if (elScalp) elScalp.innerText = dist.scalp_wins_5_to_25 || 0;

    const elScratch = document.getElementById('distScratches');
    if (elScratch) elScratch.innerText = dist.scratch_wins_0_to_5 || 0;

    const elLoss = document.getElementById('distLosses');
    if (elLoss) elLoss.innerText = dist.controlled_losses || 0;

    // 3. Hall of Fame Table
    const hofTbody = document.getElementById('hallOfFameTableBody');
    if (hofTbody) {
        const topTrades = d.top_trades || [];
        if (topTrades.length === 0) {
            hofTbody.innerHTML = `<tr><td colspan="5" class="text-center py-6 text-gray-500">No winning trades closed yet. The agent logs every successful runner here.</td></tr>`;
        } else {
            let html = '';
            let rank = 1;
            for (const t of topTrades) {
                let rankBadge = `<span class="text-gray-400 font-mono text-xs w-6 inline-block text-center">#${rank}</span>`;
                if (rank === 1) rankBadge = `<span class="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold text-xs border border-amber-500/30">#1 👑</span>`;
                else if (rank === 2) rankBadge = `<span class="px-1.5 py-0.5 rounded bg-slate-400/20 text-slate-200 font-bold text-xs border border-slate-400/30">#2 🥈</span>`;
                else if (rank === 3) rankBadge = `<span class="px-1.5 py-0.5 rounded bg-amber-700/20 text-amber-500 font-bold text-xs border border-amber-700/30">#3 🥉</span>`;

                const pnlPct = t.unrealized_pnl_pct || 0.0;
                const pnlSol = t.unrealized_pnl_sol || 0.0;
                let multiplierBadge = `<span class="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-mono font-bold text-xs">+${pnlPct.toFixed(1)}%</span>`;
                if (pnlPct >= 100.0) multiplierBadge = `<span class="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 font-mono font-bold text-xs">💎 +${pnlPct.toFixed(1)}%</span>`;
                else if (pnlPct >= 25.0) multiplierBadge = `<span class="px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-300 font-mono font-bold text-xs">🚀 +${pnlPct.toFixed(1)}%</span>`;

                html += `
                    <tr class="hover:bg-dark-700/50 transition font-mono">
                        <td class="py-2.5 px-2 flex items-center space-x-1.5">
                            ${rankBadge}
                            <span class="text-white font-bold">${t.symbol || 'COIN'}</span>
                            <span class="text-[10px] text-gray-500">${(t.mint || '').slice(0, 4)}...</span>
                            <button onclick="copyToClipboard('${t.mint}', 'Token CA')" class="text-gray-500 hover:text-white transition p-0.5" title="Copy CA">
                                <i data-lucide="copy" class="w-3 h-3"></i>
                            </button>
                            <button onclick="openTokenChartModal('${t.mint}')" class="text-gray-500 hover:text-accent-cyan transition p-0.5" title="Open Chart">
                                <i data-lucide="bar-chart-2" class="w-3 h-3"></i>
                            </button>
                        </td>
                        <td class="py-2.5 px-2">${multiplierBadge}</td>
                        <td class="py-2.5 px-2 text-emerald-400 font-bold">+${pnlSol.toFixed(4)} SOL</td>
                        <td class="py-2.5 px-2 text-gray-400 text-[11px] truncate max-w-[140px]" title="${t.exit_reason || ''}">${(t.exit_reason || 'TAKE_PROFIT').replace(/_/g, ' ')}</td>
                        <td class="py-2.5 px-2">
                            ${t.trigger_wallet ? `
                                <button onclick="openWalletModal('${t.trigger_wallet}')" class="text-accent-cyan hover:underline text-left text-[11px]">
                                    ${t.trigger_wallet.slice(0, 4)}...${t.trigger_wallet.slice(-3)}
                                </button>
                            ` : '<span class="text-gray-500 text-[11px]">DIRECT</span>'}
                        </td>
                    </tr>
                `;
                rank++;
            }
            hofTbody.innerHTML = html;
            lucide.createIcons();
        }
    }

    // 4. Mistakes & Causal Autopsies Container
    const mistakesContainer = document.getElementById('mistakesContainer');
    if (mistakesContainer) {
        const mistakes = d.mistakes || [];
        if (mistakes.length === 0) {
            mistakesContainer.innerHTML = `<div class="text-center py-6 text-gray-500 text-xs">No failure autopsies recorded yet.</div>`;
        } else {
            let mHtml = '';
            for (const m of mistakes) {
                let badgeClass = 'bg-rose-500/10 text-rose-400 border border-rose-500/20';
                if (m.outcome_category === 'DEV_RUG') badgeClass = 'bg-amber-500/10 text-amber-400 border border-amber-500/20';

                mHtml += `
                    <div class="p-3.5 bg-dark-900/60 border border-dark-700 rounded-xl space-y-2 text-xs">
                        <div class="flex items-center justify-between">
                            <div class="flex items-center space-x-2">
                                <span class="px-2 py-0.5 rounded font-bold text-[10px] ${badgeClass}">${m.outcome_category}</span>
                                <span class="font-mono text-gray-300 font-semibold">${(m.mint || '').slice(0, 6)}...</span>
                                <button onclick="copyToClipboard('${m.mint}', 'Mint CA')" class="text-gray-500 hover:text-white" title="Copy CA">
                                    <i data-lucide="copy" class="w-3 h-3"></i>
                                </button>
                                <button onclick="openTokenChartModal('${m.mint}')" class="text-gray-500 hover:text-accent-cyan" title="Open Chart">
                                    <i data-lucide="bar-chart-2" class="w-3 h-3"></i>
                                </button>
                            </div>
                            <span class="font-mono font-bold text-rose-400">${(m.net_pnl_sol || 0).toFixed(4)} SOL (${(m.net_pnl_pct || 0).toFixed(1)}%)</span>
                        </div>
                        <p class="text-gray-300 leading-relaxed text-[11px]">${m.lesson_learned}</p>
                        <div class="flex items-center justify-between text-[10px] text-gray-500 font-mono pt-1 border-t border-dark-700/60">
                            <span>Reason: ${m.exit_reason}</span>
                            <span>Curve: ${m.curve_pct_at_entry}% &rarr; ${m.curve_pct_at_exit}%</span>
                        </div>
                    </div>
                `;
            }
            mistakesContainer.innerHTML = mHtml;
            lucide.createIcons();
        }
    }

    // 5. Autonomous Self-Tuned Brain Parameters & Adaptation Timeline
    if (params) {
        const regime = params.market_regime || 'RUNNER_ALPHA';
        setText('deepMarketRegime', regime === 'RUNNER_ALPHA' ? 'RUNNER_ALPHA 🚀' : 'DEFENSIVE_SCALP 🛡️');
        setText('deepRunnerLeash', `${((params.runner_leash_pct || 0.28) * 100).toFixed(1)}%`);
        setText('deepBreakevenLock', `+${((params.breakeven_lock_threshold_pct || 0.35) * 100).toFixed(1)}%`);
        setText('deepHoldingHorizon', `${Math.round((params.max_holding_seconds || 3600) / 60)}m (Adaptive)`);
        setText('deepDecoupling', `${((params.smart_money_decoupling_pct || 0.60) * 100).toFixed(1)}%`);

        const adaptContainer = document.getElementById('adaptationHistoryContainer');
        if (adaptContainer) {
            const history = params.adaptation_history || [];
            if (history.length === 0) {
                adaptContainer.innerHTML = `<div class="text-center py-4 text-gray-500 text-xs">Autonomous learning active. The agent records every self-tuning adjustment here as trades complete.</div>`;
            } else {
                let aHtml = '';
                for (const a of history) {
                    const timeStr = new Date(a.timestamp * 1000).toLocaleTimeString();
                    aHtml += `
                        <div class="p-2.5 bg-dark-900/80 rounded-lg border border-dark-700/80 space-y-1">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center space-x-2">
                                    <span class="px-1.5 py-0.5 rounded text-[10px] bg-accent-cyan/10 text-accent-cyan font-bold font-mono">v${a.version}</span>
                                    <span class="text-gray-300 font-semibold text-[11px]">${(a.changes || []).join(' • ')}</span>
                                </div>
                                <span class="text-[10px] text-gray-500 font-mono">${timeStr}</span>
                            </div>
                            <p class="text-[10px] text-gray-400 leading-tight italic">Reason: "${a.reasoning}"</p>
                        </div>
                    `;
                }
                adaptContainer.innerHTML = aHtml;
            }
        }
    }

    // 6. Online Machine Learning Brain (AdaGrad / SGDW Engine)
    const ml = payload.ml_brain || {};
    const elUpdates = document.getElementById('mlTotalUpdates');
    if (elUpdates) elUpdates.innerText = `${ml.total_updates || 0} Trades Learned`;

    const elBrier = document.getElementById('mlBrierScore');
    if (elBrier && ml.rolling_brier_score !== undefined) {
        elBrier.innerText = ml.rolling_brier_score.toFixed(4);
    }

    const weightsContainer = document.getElementById('mlFeatureWeightsContainer');
    if (weightsContainer && ml.weights) {
        let wHtml = '';
        const names = ml.feature_names || Object.keys(ml.weights);
        for (const f of names) {
            const val = ml.weights[f] !== undefined ? ml.weights[f] : 0.0;
            const isPos = val >= 0;
            const colorClass = isPos ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' : 'text-rose-400 border-rose-500/30 bg-rose-500/10';
            wHtml += `
                <div class="p-2.5 rounded-xl border ${colorClass} text-center space-y-1">
                    <span class="text-[10px] text-gray-400 truncate block uppercase tracking-wider" title="${f}">${f.replace(/_/g, ' ')}</span>
                    <span class="font-bold text-xs block font-mono">${isPos ? '+' : ''}${val.toFixed(3)}</span>
                </div>
            `;
        }
        weightsContainer.innerHTML = wHtml;
    }
}


// --- Live Trade Ticker ---
function appendTradeTicker(trade) {
    const ticker = document.getElementById('tradeTicker');
    if (!ticker) return;

    if (ticker.innerText.includes('Connecting')) {
        ticker.innerHTML = '';
    }

    const isBuy = trade.tx_type === 'buy';
    const color = isBuy ? 'text-emerald-400' : 'text-rose-400';
    const actionBadge = isBuy 
        ? '<span class="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold">BUY</span>' 
        : '<span class="px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20 font-bold">SELL</span>';

    const item = document.createElement('div');
    item.className = 'py-1.5 px-2 bg-dark-700/50 rounded border border-dark-600/50 flex items-center justify-between text-[11px] animate-fade-in hover:border-dark-500 transition';
    item.innerHTML = `
        <div class="flex items-center space-x-1.5">
            ${actionBadge}
            <button onclick="openTokenChartModal('${trade.mint}')" class="font-mono text-gray-300 hover:text-accent-cyan transition text-left" title="Inspect Chart & Token">
                ${trade.mint.slice(0, 4)}...${trade.mint.slice(-3)}
            </button>
            <button onclick="copyToClipboard('${trade.mint}', 'Token CA')" class="text-gray-500 hover:text-white transition p-0.5" title="Copy Mint CA">
                <i data-lucide="copy" class="w-3 h-3"></i>
            </button>
        </div>
        <div class="flex items-center space-x-2">
            <span class="font-bold font-mono ${color}">${trade.sol_amount.toFixed(3)} SOL</span>
            <button onclick="openWalletModal('${trade.trader_public_key}')" class="text-gray-400 hover:text-accent-cyan font-mono text-[10px]" title="Inspect Wallet Dossier">
                ${trade.trader_public_key.slice(0, 4)}
            </button>
        </div>
    `;

    ticker.prepend(item);

    while (ticker.children.length > 35) {
        ticker.removeChild(ticker.lastChild);
    }
    lucide.createIcons();
}

// --- Interactive Modals: Token Chart & Wallet Dossier ---

async function openTokenChartModal(mint) {
    if (!mint) return;
    currentModalMint = mint;

    const iframe = document.getElementById('tokenChartIframe');
    iframe.src = `https://dexscreener.com/solana/${mint}?embed=1&theme=dark&trades=0&info=0`;

    document.getElementById('modalTokenMint').innerText = mint;
    document.getElementById('modalPumpFunLink').href = `https://pump.fun/coin/${mint}`;
    document.getElementById('modalDexScreenerLink').href = `https://dexscreener.com/solana/${mint}`;

    openModal('tokenChartModal');
    lucide.createIcons();

    try {
        const res = await fetch(`/api/token/${mint}`);
        const json = await res.json();
        if (json.status === 'ok' && json.token) {
            const t = json.token;
            document.getElementById('modalTokenSymbol').innerText = t.symbol || 'COIN';
            document.getElementById('modalTokenName').innerText = t.name || 'Pump Token';
            document.getElementById('modalTokenBadge').innerText = (t.symbol || 'COIN').slice(0, 3);
            
            const progress = t.bonding_progress_pct || 0.0;
            document.getElementById('modalBondingPct').innerText = `${progress.toFixed(1)}%`;
            const bBar = document.getElementById('modalBondingBar');
            if (bBar && bBar.style) bBar.style.width = `${Math.min(100, Math.max(0, progress))}%`;
            document.getElementById('modalVirtualSol').innerText = t.virtual_sol ? t.virtual_sol.toFixed(2) : '30.0';

            document.getElementById('modalSpotPrice').innerText = t.spot_price_sol ? `${t.spot_price_sol.toFixed(8)} SOL` : '--';
            document.getElementById('modalMarketCap').innerText = t.market_cap_sol ? `${t.market_cap_sol.toFixed(1)} SOL` : '--';
            document.getElementById('modalTokensLeft').innerText = t.real_tokens_remaining ? `${(t.real_tokens_remaining / 1e6).toFixed(1)}M` : '--';
            document.getElementById('modalDevBuy').innerText = t.dev_initial_buy_sol ? `${t.dev_initial_buy_sol.toFixed(3)} SOL` : '0.0 SOL';

            if (t.dev_wallet) {
                document.getElementById('modalDevAddress').innerText = t.dev_wallet;
                document.getElementById('modalDevSolscan').href = `https://solscan.io/account/${t.dev_wallet}`;
            } else {
                document.getElementById('modalDevAddress').innerText = 'Unknown';
            }
        }
    } catch (e) {
        console.error('Error fetching token details:', e);
    }
}

async function openWalletModal(address) {
    if (!address) return;

    document.getElementById('modalWalletFullAddress').innerText = address;
    document.getElementById('modalWalletSolscan').href = `https://solscan.io/account/${address}`;

    openModal('walletDossierModal');
    lucide.createIcons();

    try {
        const res = await fetch(`/api/wallet/${address}`);
        const json = await res.json();
        if (json.status === 'ok' && json.wallet) {
            const w = json.wallet;
            const closed = w.closed_trades || 0;
            const total = w.total_trades || 0;
            const wins = w.profitable_trades || 0;
            const wr = closed > 0 ? (wins / closed * 100.0).toFixed(1) : '0.0';

            document.getElementById('modalWalletScore').innerText = w.persistence_score.toFixed(3);
            document.getElementById('modalWalletWinRate').innerText = `${wr}%`;
            document.getElementById('modalWalletPnL').innerText = `${w.realized_pnl_sol >= 0 ? '+' : ''}${w.realized_pnl_sol.toFixed(3)} SOL`;
            document.getElementById('modalWalletTrades').innerText = `${closed} / ${total}`;
            
            const hours = ((w.last_seen - w.first_seen) / 3600.0).toFixed(1);
            document.getElementById('modalWalletHours').innerText = `${hours}h`;

            const badge = document.getElementById('modalWalletBadge');
            if (w.persistence_score >= 0.40) {
                badge.innerText = 'ELITE HUNTER';
                badge.className = 'px-2 py-0.5 rounded text-[10px] font-bold bg-accent-emerald/20 text-accent-emerald border border-accent-emerald/30';
            } else {
                badge.innerText = 'QUALIFIED';
                badge.className = 'px-2 py-0.5 rounded text-[10px] font-semibold bg-dark-700 text-gray-300 border border-dark-600';
            }

            const tokensContainer = document.getElementById('modalWalletTokensList');
            const tokens = w.tokens_traded || [];
            if (tokens.length === 0) {
                tokensContainer.innerHTML = '<span class="text-xs text-gray-500">No tokens recorded.</span>';
            } else {
                let tagsHtml = '';
                for (const t of tokens) {
                    tagsHtml += `
                        <div class="px-2 py-1 bg-dark-800 rounded border border-dark-600 flex items-center space-x-1.5 text-[11px] font-mono">
                            <span class="text-accent-cyan">${t.slice(0, 5)}...${t.slice(-4)}</span>
                            <button onclick="copyToClipboard('${t}', 'Token CA')" class="text-gray-400 hover:text-white" title="Copy Mint">
                                <i data-lucide="copy" class="w-3 h-3"></i>
                            </button>
                            <button onclick="openTokenChartModal('${t}')" class="text-gray-400 hover:text-accent-cyan" title="Open Chart">
                                <i data-lucide="bar-chart-2" class="w-3 h-3"></i>
                            </button>
                            <a href="https://pump.fun/coin/${t}" target="_blank" class="text-gray-400 hover:text-accent-emerald" title="Pump.fun">
                                <i data-lucide="external-link" class="w-3 h-3"></i>
                            </a>
                        </div>
                    `;
                }
                tokensContainer.innerHTML = tagsHtml;
                lucide.createIcons();
            }
        }
    } catch (e) {
        console.error('Error fetching wallet details:', e);
    }
}

// --- Interactive Capital Controls ---

async function handleDeposit() {
    const input = document.getElementById('depositInput');
    const amount = parseFloat(input.value);
    if (!amount || amount <= 0) return alert('Enter a valid positive SOL amount');

    try {
        const res = await fetch('/api/portfolio/deposit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount }),
        });
        const rawText = await res.text();
        let data;
        try {
            data = JSON.parse(rawText);
        } catch (parseErr) {
            throw new Error(`Server returned HTTP ${res.status}: ${rawText || res.statusText}`);
        }

        if (res.ok && data.status === 'ok') {
            closeModal('depositModal');
            input.value = '';
            showToast('Deposit Confirmed', `Successfully added +${amount} SOL to cash balance.`, 'success');
        } else {
            alert('Deposit failed: ' + (data.error || `HTTP ${res.status}`));
        }
    } catch (e) {
        alert('Deposit error: ' + e.message);
    }
}

async function handleWithdraw() {
    const input = document.getElementById('withdrawInput');
    const amount = parseFloat(input.value);
    if (!amount || amount <= 0) return alert('Enter a valid positive SOL amount');

    try {
        const res = await fetch('/api/portfolio/withdraw', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount }),
        });
        const rawText = await res.text();
        let data;
        try {
            data = JSON.parse(rawText);
        } catch (parseErr) {
            throw new Error(`Server returned HTTP ${res.status}: ${rawText || res.statusText}`);
        }

        if (res.ok && data.status === 'ok') {
            closeModal('withdrawModal');
            input.value = '';
            showToast('Withdrawal Confirmed', `Successfully withdrew -${amount} SOL from cash balance.`, 'info');
        } else {
            alert('Withdraw failed: ' + (data.error || `HTTP ${res.status}`));
        }
    } catch (e) {
        alert('Withdrawal error: ' + e.message);
    }
}

async function handleSoftReset() {
    const input = document.getElementById('softResetBalanceInput');
    const amount = parseFloat(input ? input.value : 10.0);
    if (!amount || amount <= 0) return alert('Enter a valid positive SOL amount (e.g. 10.0)');

    try {
        const res = await fetch('/api/portfolio/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'soft', balance: amount }),
        });
        const rawText = await res.text();
        let data;
        try {
            data = JSON.parse(rawText);
        } catch (parseErr) {
            throw new Error(`Server returned HTTP ${res.status}: ${rawText || res.statusText}`);
        }

        if (res.ok && data.status === 'ok') {
            closeModal('resetBalanceModal');
            showToast('Soft Reset Complete', data.message || `Paper balance set to ${amount.toFixed(4)} SOL. All learnings preserved.`, 'success');
        } else {
            alert('Soft reset failed: ' + (data.error || data.message || `HTTP ${res.status}`));
        }
    } catch (e) {
        alert('Error executing soft reset: ' + e.message);
    }
}

async function handleHardReset() {
    const input = document.getElementById('hardResetBalanceInput');
    const amount = parseFloat(input ? input.value : 10.0);
    if (!amount || amount <= 0) return alert('Enter a valid positive SOL amount (e.g. 10.0)');

    const confirmMsg = "⚠️ WARNING: Hard Reset will completely WIPE all agent memory:\n\n" +
        "• All open and closed paper positions\n" +
        "• All smart wallet dossiers & blacklist history\n" +
        "• All episodic learnings & trade autopsies\n" +
        "• All Online Machine Learning weights & calibration\n" +
        "• Strategy policy version reset to v1\n\n" +
        "The agent will start 100% brand new with " + amount.toFixed(2) + " SOL.\n\nAre you sure you want to proceed?";

    if (!confirm(confirmMsg)) return;

    try {
        const res = await fetch('/api/portfolio/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'hard', balance: amount }),
        });
        const rawText = await res.text();
        let data;
        try {
            data = JSON.parse(rawText);
        } catch (parseErr) {
            throw new Error(`Server returned HTTP ${res.status}: ${rawText || res.statusText}`);
        }

        if (res.ok && data.status === 'ok') {
            closeModal('resetBalanceModal');
            showToast('Factory Wipe Complete', data.message || `Agent hard-reset to v1 clean state with ${amount.toFixed(4)} SOL.`, 'success');
        } else {
            alert('Hard reset failed: ' + (data.error || data.message || `HTTP ${res.status}`));
        }
    } catch (e) {
        alert('Error executing hard reset: ' + e.message);
    }
}

async function handleResetBalance() {
    return handleSoftReset();
}

async function emergencyClose(mint) {
    if (!confirm('Are you sure you want to manually close and liquidate this position?')) return;

    try {
        const res = await fetch('/api/positions/close', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mint, reason: 'MANUAL_USER_LIQUIDATION' }),
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast('Position Liquidated', `Closed position for mint ${mint.slice(0, 6)}... PnL: ${data.pnl_sol >= 0 ? '+' : ''}${data.pnl_sol.toFixed(4)} SOL`, 'info');
        } else {
            alert('Close position failed: ' + data.error);
        }
    } catch (e) {
        alert('Error: ' + e);
    }
}

async function submitParams(e) {
    e.preventDefault();
    const payload = {
        base_trade_sol: parseFloat(document.getElementById('paramBaseSize').value),
        max_trade_sol: parseFloat(document.getElementById('paramMaxSize').value),
        trailing_stop_pct: parseFloat(document.getElementById('paramTrailingStop').value),
        take_profit_pct: parseFloat(document.getElementById('paramTakeProfit').value),
        min_wallet_persistence_score: parseFloat(document.getElementById('paramMinPersistence').value),
    };

    try {
        const res = await fetch('/api/strategy/params', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast('Strategy Updated', 'Parameters committed to SQLite and loaded into live risk engine.', 'success');
        } else {
            alert('Update failed: ' + data.error);
        }
    } catch (err) {
        alert('Error: ' + err);
    }
}

async function toggleAgent() {
    isAgentPaused = !isAgentPaused;
    const btn = document.getElementById('toggleAgentBtn');
    const text = document.getElementById('toggleText');
    const icon = document.getElementById('toggleIcon');

    if (isAgentPaused) {
        text.innerText = 'Resume';
        btn.className = 'bg-accent-emerald/10 hover:bg-accent-emerald/20 text-accent-emerald border border-accent-emerald/30 px-3.5 py-1.5 rounded-lg text-xs font-bold flex items-center space-x-1.5 transition';
    } else {
        text.innerText = 'Pause';
        btn.className = 'bg-accent-cyan/10 hover:bg-accent-cyan/20 text-accent-cyan border border-accent-cyan/30 px-3.5 py-1.5 rounded-lg text-xs font-bold flex items-center space-x-1.5 transition';
    }

    try {
        await fetch('/api/agent/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paused: isAgentPaused }),
        });
        showToast(isAgentPaused ? 'Trading Paused' : 'Trading Resumed', isAgentPaused ? 'Agent will not open new positions.' : 'Agent actively scanning smart money entries.', 'info');
    } catch (e) {
        console.error('Toggle error:', e);
    }
}

// --- Autonomous Cognitive Organism & Multi-Brain Rendering ---
function renderCognitiveOrganism(state) {
    const cog = state.cognitive_state || {};
    const cf = state.counterfactual_summary || {};
    const decisions = state.recent_decisions || [];
    const hypoEvo = state.hypothesis_evolution || {};
    const exp = hypoEvo.experience_counts || {};
    const hypotheses = hypoEvo.hypotheses || [];

    // 1. Top Ribbon & Cognitive Header
    const regime = cog.active_regime || 'ORGANIC_MOMENTUM';
    const hurdle = cog.hurdle_rate !== undefined ? cog.hurdle_rate : 0.05;
    const hurdlePct = (hurdle * 100).toFixed(1);

    setText('statActiveRegime', regime.replace(/_/g, ' '));
    setText('statHurdleRate', `Hurdle: +${hurdlePct}% Edge`);
    setText('cogRegimeBadge', regime);
    setText('cogHurdleBadge', `Hurdle: +${hurdlePct}% Expected Edge`);

    // Dynamic Regime Badge Colors
    const badge = document.getElementById('cogRegimeBadge');
    if (badge) {
        if (regime === 'CABAL_PREDATORY') {
            badge.className = 'px-2.5 py-0.5 rounded text-xs font-bold font-mono bg-rose-500/20 text-rose-400 border border-rose-500/30';
        } else if (regime === 'LOW_LIQUIDITY_DEADZONE') {
            badge.className = 'px-2.5 py-0.5 rounded text-xs font-bold font-mono bg-blue-500/20 text-blue-400 border border-blue-500/30';
        } else {
            badge.className = 'px-2.5 py-0.5 rounded text-xs font-bold font-mono bg-emerald-500/20 text-emerald-400 border border-emerald-500/30';
        }
    }

    const preserved = cf.estimated_capital_preserved_sol || 0.0;
    setText('statCounterfactualsPreserved', `+${preserved.toFixed(3)} SOL Rugs Dodged`);
    setText('statHypothesesMined', `${hypotheses.length || 3} Hypotheses Active`);

    // Experience Counters
    setText('expTokensSeen', exp.total_tokens_seen || 0);
    setText('expClustersMapped', exp.total_clusters_mapped || 0);
    setText('expAutopsiesConducted', exp.total_autopsies_conducted || 0);
    setText('expCounterfactualsTracked', exp.total_counterfactuals_tracked || 0);
    setText('expHypothesesDiscovered', exp.hypotheses_discovered || hypotheses.length || 3);

    // Brain weights
    const weights = cog.brain_weights || {};
    if (weights.GraphBrain) setText('weightGraphBrain', `${(weights.GraphBrain * 100).toFixed(0)}% Weight`);
    if (weights.FlowBrain) setText('weightFlowBrain', `${(weights.FlowBrain * 100).toFixed(0)}% Weight`);
    if (weights.RunnerBrain) setText('weightRunnerBrain', `${(weights.RunnerBrain * 100).toFixed(0)}% Weight`);
    if (weights.AdversaryBrain) setText('weightAdversaryBrain', `${(weights.AdversaryBrain * 100).toFixed(0)}% + VETO`);
    if (weights.ContrarianBrain) setText('weightContrarianBrain', `${(weights.ContrarianBrain * 100).toFixed(0)}% Weight`);

    // 2. Render Causal Decision Audit Feed
    renderCausalDecisions(decisions);

    // 3. Render Counterfactual Ledger & Active Shadows
    renderCounterfactualLedger(cf);

    // 4. Render Discovered Hypotheses
    renderHypotheses(hypotheses);

    // 5. Render Clusters Dossier
    renderClusters(cog.top_clusters || []);
}

function renderCausalDecisions(decisions) {
    const tbody = document.getElementById('decisionsTableBody');
    if (!tbody) return;

    if (!decisions || decisions.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center py-6 text-gray-500">Awaiting candidate token evaluations...</td></tr>`;
        return;
    }

    let html = '';
    for (const d of decisions) {
        const timeStr = new Date(d.timestamp * 1000).toLocaleTimeString();
        let decBadge = '';
        if (d.decision === 'EXECUTE') {
            decBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">EXECUTE 🚀</span>`;
        } else if (d.veto_active) {
            decBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">VETO 🛑</span>`;
        } else {
            decBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-dark-700 text-gray-400 border border-dark-600">PASS</span>`;
        }

        const edgeClass = d.expected_edge > 0 ? 'text-emerald-400 font-bold' : 'text-rose-400';
        const edgeStr = `${d.expected_edge >= 0 ? '+' : ''}${(d.expected_edge * 100).toFixed(1)}%`;
        const hurdleStr = `${(d.hurdle_rate * 100).toFixed(1)}%`;

        let brainScoresHtml = '<div class="flex items-center space-x-1.5 flex-wrap gap-y-1 text-[10px] font-mono">';
        if (d.brain_scores) {
            for (const [bName, bData] of Object.entries(d.brain_scores)) {
                const shortName = bName.replace('Brain', '');
                const scoreColor = bData.score >= 0.65 ? 'text-emerald-400' : (bData.score < 0.40 ? 'text-rose-400' : 'text-gray-300');
                const vetoTag = bData.veto ? '<span class="text-rose-400 font-bold">!VETO</span>' : '';
                brainScoresHtml += `
                    <span class="px-1.5 py-0.5 rounded bg-dark-900 border border-dark-700" title="${bData.evidence || ''}">
                        ${shortName}: <b class="${scoreColor}">${(bData.score * 100).toFixed(0)}%</b>${vetoTag}
                    </span>
                `;
            }
        }
        brainScoresHtml += '</div>';

        html += `
            <tr class="hover:bg-dark-700/40 transition">
                <td class="py-2.5 px-3">
                    <div class="text-white font-bold text-xs">${d.symbol || 'TOKEN'}</div>
                    <div class="text-gray-500 text-[10px] flex items-center space-x-1">
                        <span>${timeStr}</span>
                        <span>•</span>
                        <span class="text-accent-cyan">${d.mint ? d.mint.slice(0, 6) + '...' : ''}</span>
                    </div>
                </td>
                <td class="py-2.5 px-3">${decBadge}</td>
                <td class="py-2.5 px-3">
                    <span class="${edgeClass}">${edgeStr}</span>
                    <span class="text-gray-500 text-[10px] block">Hurdle: ${hurdleStr}</span>
                </td>
                <td class="py-2.5 px-3 text-xs text-gray-300 max-w-xs">
                    ${d.dominant_reason || d.thesis || '--'}
                </td>
                <td class="py-2.5 px-3">${brainScoresHtml}</td>
            </tr>
        `;
    }
    tbody.innerHTML = html;
}

function renderCounterfactualLedger(cf) {
    if (!cf) return;
    setText('cfCurrentlyTracking', `${cf.currently_tracking || 0} Tokens`);
    setText('cfConfirmedRugs', `${cf.confirmed_rug_dodges || 0} Dodged`);
    setText('cfConfirmedChops', `${cf.confirmed_chop_dodges || 0} Dodged`);
    setText('cfMissedRunners', `${cf.missed_runners_count || 0} Missed`);
    setText('cfCapitalPreservedBadge', `+${(cf.estimated_capital_preserved_sol || 0).toFixed(3)} SOL Preserved`);

    const tbody = document.getElementById('shadowTableBody');
    if (!tbody) return;

    const active = cf.active_shadows || [];
    if (active.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-gray-500 font-mono">No active shadow positions being tracked currently. The agent continuously monitors passed candidates.</td></tr>`;
        return;
    }

    let html = '';
    const now = Date.now() / 1000;
    for (const s of active) {
        const ageMin = Math.max(0, Math.floor((now - (s.evaluation_time || now)) / 60));
        const mult = s.peak_multiplier || 1.0;
        const multClass = mult >= 3.0 ? 'text-amber-400 font-bold' : (mult >= 1.5 ? 'text-emerald-400 font-bold' : 'text-gray-300');
        const ret = s.final_return_pct || 0.0;
        const retClass = ret >= 0 ? 'text-emerald-400 font-semibold' : 'text-rose-400 font-semibold';

        html += `
            <tr class="hover:bg-dark-700/40 transition">
                <td class="py-2.5 px-3">
                    <span class="text-white font-bold">${s.symbol || 'TOKEN'}</span>
                    <span class="text-gray-500 text-[10px] block">${s.mint ? s.mint.slice(0, 6) + '...' : ''}</span>
                </td>
                <td class="py-2.5 px-3 font-mono">${(s.initial_price_sol || 0).toFixed(7)}</td>
                <td class="py-2.5 px-3 font-mono ${multClass}">${mult.toFixed(2)}x</td>
                <td class="py-2.5 px-3 font-mono ${retClass}">${ret >= 0 ? '+' : ''}${ret.toFixed(1)}%</td>
                <td class="py-2.5 px-3 font-mono text-gray-400">${(s.initial_curve_pct || 0).toFixed(1)}%</td>
                <td class="py-2.5 px-3 text-xs text-gray-400 max-w-xs truncate">${s.dominant_reason || '--'}</td>
                <td class="py-2.5 px-3 text-gray-400 font-mono">${ageMin}m / 60m</td>
            </tr>
        `;
    }
    tbody.innerHTML = html;
}

function renderHypotheses(hypotheses) {
    const container = document.getElementById('hypothesesContainer');
    if (!container) return;

    if (!hypotheses || hypotheses.length === 0) {
        container.innerHTML = `<div class="text-center py-6 text-gray-500 text-xs font-mono">Awaiting offline hypothesis discovery cycles...</div>`;
        return;
    }

    let html = '';
    for (const h of hypotheses) {
        const isRunner = h.target_outcome.includes('RUNNER') || h.target_outcome.includes('REVIVAL');
        const badgeColor = isRunner ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20';
        const statusBadge = h.status === 'ACTIVE' || h.status === 'CONFIRMED'
            ? `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">${h.status}</span>`
            : `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-dark-700 text-gray-400 border border-dark-600">${h.status}</span>`;

        html += `
            <div class="p-3.5 rounded-xl bg-dark-900/60 border border-dark-700 space-y-2">
                <div class="flex items-center justify-between text-xs">
                    <div class="flex items-center space-x-2">
                        <span class="px-2 py-0.5 rounded font-bold text-[10px] border ${badgeColor}">${h.target_outcome}</span>
                        ${statusBadge}
                    </div>
                    <div class="flex items-center space-x-3 font-mono text-[11px]">
                        <span>Lift: <b class="text-amber-400 text-xs">${h.lift.toFixed(2)}x</b></span>
                        <span>Confidence: <b class="text-emerald-400">${(h.confidence * 100).toFixed(1)}%</b></span>
                        <span class="text-gray-500">N=${h.sample_size}</span>
                        <span class="text-gray-500">p=${h.p_value.toFixed(3)}</span>
                    </div>
                </div>
                <p class="text-xs text-gray-300 leading-relaxed font-sans">${h.statement}</p>
            </div>
        `;
    }
    container.innerHTML = html;
}

function renderClusters(clusters) {
    const tbody = document.getElementById('clustersTableBody');
    if (!tbody) return;

    if (!clusters || clusters.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-gray-500 font-mono">Mapping on-chain wallet topology... No multi-wallet clusters detected yet.</td></tr>`;
        return;
    }

    let html = '';
    for (const c of clusters) {
        let archBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-dark-700 text-gray-300">${c.archetype}</span>`;
        if (c.archetype === 'INSIDER_CABAL') {
            archBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">INSIDER CABAL</span>`;
        } else if (c.archetype === 'DEPLOYER_SYBIL') {
            archBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">DEPLOYER SYBIL</span>`;
        } else if (c.archetype === 'ORGANIC_SMART') {
            archBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">ORGANIC SMART</span>`;
        }

        const prob = c.coordination_probability || 0.0;
        const probClass = prob >= 0.70 ? 'text-rose-400 font-bold' : (prob >= 0.40 ? 'text-amber-400' : 'text-gray-300');
        const membersList = (c.member_addresses || []).map(a => `${a.slice(0, 4)}...`).join(', ');

        html += `
            <tr class="hover:bg-dark-700/40 transition">
                <td class="py-2.5 px-3 font-mono text-accent-cyan font-semibold">${c.cluster_id}</td>
                <td class="py-2.5 px-3">${archBadge}</td>
                <td class="py-2.5 px-3 text-xs text-gray-400" title="${(c.member_addresses || []).join('\n')}">
                    ${c.member_count || (c.member_addresses ? c.member_addresses.length : 0)} wallets (${membersList})
                </td>
                <td class="py-2.5 px-3 font-mono ${probClass}">${(prob * 100).toFixed(0)}%</td>
                <td class="py-2.5 px-3 font-mono text-gray-300">${(c.temporal_synchrony_delta_sec || 0).toFixed(2)}s</td>
                <td class="py-2.5 px-3">
                    <span class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-dark-700 text-gray-300 border border-dark-600">TRACKED</span>
                </td>
            </tr>
        `;
    }
    tbody.innerHTML = html;
}

// --- Long-Term Performance & Deep Analytics Rendering ---
let allClosedTradesCache = [];

function renderAnalytics(analytics, closedPositions) {
    if (!analytics) return;
    const m = analytics.metrics || {};
    const points = analytics.equity_curve || [];
    allClosedTradesCache = closedPositions || [];

    // 1. KPI Ribbon
    const net = m.net_pnl_sol !== undefined ? m.net_pnl_sol : 0.0;
    const netClass = net >= 0 ? 'text-emerald-400' : 'text-rose-400';
    setText('analyticsNetPnl', `${net >= 0 ? '+' : ''}${net.toFixed(4)} SOL`, `text-xl font-bold mt-1 ${netClass}`);
    setText('analyticsTotalTrades', `${m.total_trades || 0} trades closed`);

    setText('analyticsProfitFactor', `${(m.profit_factor || 1.0).toFixed(2)}x`);
    setText('analyticsGrossPnL', `+${(m.gross_profit_sol || 0).toFixed(2)} / -${(m.gross_loss_sol || 0).toFixed(2)} SOL`);

    setText('analyticsWinRate', `${(m.win_rate_pct || 0).toFixed(1)}%`);
    setText('analyticsWinsLosses', `${m.wins || 0}W / ${m.losses || 0}L`);

    setText('analyticsAvgWinLoss', `+${(m.avg_win_pct || 0).toFixed(1)}%`);
    setText('analyticsAvgLossPct', `Loss: ${(m.avg_loss_pct || 0).toFixed(1)}%`);

    setText('analyticsMaxDrawdown', `-${(m.max_drawdown_pct || 0).toFixed(1)}%`);
    setText('analyticsMaxDrawdownSol', `-${(m.max_drawdown_sol || 0).toFixed(4)} SOL`);

    setText('analyticsMaxWinPct', `+${(m.max_win_pct || 0).toFixed(1)}%`);
    setText('analyticsWorstLossPct', `Worst: ${(m.max_loss_pct || 0).toFixed(1)}%`);

    // 2. Render Equity Curve SVG
    renderEquityCurve(points);

    // 3. Exit Reasons Attribution Breakdown
    renderExitReasons(m.exit_reasons || {});

    // 4. Populate Closed Trades Table
    renderClosedTradesTable(allClosedTradesCache);
}

function renderEquityCurve(points) {
    const notice = document.getElementById('equityEmptyNotice');
    const svg = document.getElementById('equityCurveSvg');
    if (!svg) return;

    if (!points || points.length < 2) {
        if (notice) notice.classList.remove('hidden');
        svg.classList.add('hidden');
        return;
    }

    if (notice) notice.classList.add('hidden');
    svg.classList.remove('hidden');

    const firstEq = points[0].equity_sol || 10.0;
    const lastEq = points[points.length - 1].equity_sol || firstEq;
    setText('equityStartVal', `Start: ${firstEq.toFixed(3)} SOL`);
    setText('equityCurrentVal', `Current: ${lastEq.toFixed(3)} SOL`, `text-xs font-mono px-2.5 py-1 rounded-lg border font-bold ${lastEq >= firstEq ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' : 'text-rose-400 bg-rose-500/10 border-rose-500/30'}`);

    const equities = points.map(p => p.equity_sol);
    const minEq = Math.min(...equities) * 0.998;
    const maxEq = Math.max(...equities) * 1.002;
    const range = (maxEq - minEq) || 1.0;

    const width = 800;
    const height = 200;
    const padding = 20;

    const coords = points.map((p, i) => {
        const x = padding + (i / (points.length - 1)) * (width - 2 * padding);
        const y = height - padding - ((p.equity_sol - minEq) / range) * (height - 2 * padding);
        return { x, y, p };
    });

    const pathD = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' ');
    const areaD = `${pathD} L ${coords[coords.length - 1].x.toFixed(1)} ${height - padding} L ${coords[0].x.toFixed(1)} ${height - padding} Z`;

    const isProfit = lastEq >= firstEq;
    const strokeColor = isProfit ? '#10b981' : '#f43f5e';
    const fillGradient = isProfit ? 'url(#greenGradient)' : 'url(#redGradient)';

    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.innerHTML = `
        <defs>
            <linearGradient id="greenGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#10b981" stop-opacity="0.3"/>
                <stop offset="100%" stop-color="#10b981" stop-opacity="0.0"/>
            </linearGradient>
            <linearGradient id="redGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#f43f5e" stop-opacity="0.3"/>
                <stop offset="100%" stop-color="#f43f5e" stop-opacity="0.0"/>
            </linearGradient>
        </defs>
        <!-- Horizontal grid line at start value -->
        <line x1="${padding}" y1="${height - padding - ((firstEq - minEq) / range) * (height - 2 * padding)}" x2="${width - padding}" y2="${height - padding - ((firstEq - minEq) / range) * (height - 2 * padding)}" stroke="#374151" stroke-dasharray="4" stroke-width="1"/>
        <!-- Area fill -->
        <path d="${areaD}" fill="${fillGradient}"/>
        <!-- Polyline -->
        <path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
        <!-- Data points dots -->
        ${coords.map(c => `
            <circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="3" fill="${strokeColor}">
                <title>${c.p.symbol}: ${c.p.equity_sol.toFixed(4)} SOL (${c.p.pnl_sol >= 0 ? '+' : ''}${c.p.pnl_sol} SOL)</title>
            </circle>
        `).join('')}
    `;
}

function renderExitReasons(exitReasons) {
    const container = document.getElementById('exitReasonsContainer');
    if (!container) return;

    const entries = Object.entries(exitReasons);
    if (entries.length === 0) {
        container.innerHTML = `<div class="text-gray-500 text-xs text-center py-4">No exit triggers recorded yet.</div>`;
        return;
    }

    let html = '';
    for (const [reason, data] of entries) {
        const net = data.net_pnl_sol || 0.0;
        const color = net >= 0 ? 'text-emerald-400' : 'text-rose-400';
        html += `
            <div class="flex items-center justify-between p-2 rounded-lg bg-dark-900/60 border border-dark-700">
                <div class="flex items-center space-x-2">
                    <span class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-dark-700 text-gray-300">${reason.replace(/_/g, ' ')}</span>
                    <span class="text-gray-400 font-mono text-[11px]">x${data.count}</span>
                </div>
                <span class="font-mono font-bold text-xs ${color}">${net >= 0 ? '+' : ''}${net.toFixed(4)} SOL</span>
            </div>
        `;
    }
    container.innerHTML = html;
}

function renderClosedTradesTable(trades) {
    const tbody = document.getElementById('tradeHistoryTableBody');
    if (!tbody) return;

    if (!trades || trades.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-gray-500">No closed trades recorded yet. Scanning live stream for entries...</td></tr>`;
        return;
    }

    let html = '';
    for (const t of trades) {
        const pnlSol = t.unrealized_pnl_sol || 0.0;
        const pnlPct = t.unrealized_pnl_pct || 0.0;
        const isProf = pnlSol >= 0;
        const pnlClass = isProf ? 'text-emerald-400' : 'text-rose-400';

        const entryTimeStr = t.entry_timestamp ? new Date(t.entry_timestamp * 1000).toLocaleTimeString() : '--';
        const exitTimeStr = t.exit_timestamp ? new Date(t.exit_timestamp * 1000).toLocaleTimeString() : '--';
        const holdSec = (t.exit_timestamp && t.entry_timestamp) ? Math.round(t.exit_timestamp - t.entry_timestamp) : 0;
        const holdStr = holdSec >= 60 ? `${Math.floor(holdSec / 60)}m ${holdSec % 60}s` : `${holdSec}s`;

        html += `
            <tr class="hover:bg-dark-700/40 transition trade-row" data-search="${(t.symbol || '').toLowerCase()} ${(t.mint || '').toLowerCase()}">
                <td class="py-2.5 px-3">
                    <div class="text-white font-bold">${t.symbol || 'COIN'}</div>
                    <div class="text-[10px] text-gray-500 font-mono flex items-center space-x-1">
                        <span>${(t.mint || '').slice(0, 6)}...</span>
                        <button onclick="copyToClipboard('${t.mint}', 'Token CA')" class="text-gray-500 hover:text-white p-0.5" title="Copy CA">
                            <i data-lucide="copy" class="w-2.5 h-2.5"></i>
                        </button>
                    </div>
                </td>
                <td class="py-2.5 px-3 text-gray-400 text-xs font-mono">${entryTimeStr} &rarr; ${exitTimeStr}</td>
                <td class="py-2.5 px-3 text-gray-400 font-mono">${holdStr}</td>
                <td class="py-2.5 px-3 font-mono text-gray-300">${(t.entry_sol_cost || 0.0).toFixed(3)}</td>
                <td class="py-2.5 px-3 font-mono ${pnlClass} font-bold">
                    ${isProf ? '+' : ''}${pnlSol.toFixed(4)} (${isProf ? '+' : ''}${pnlPct.toFixed(1)}%)
                </td>
                <td class="py-2.5 px-3 text-xs text-gray-400">${(t.exit_reason || 'CLOSED').replace(/_/g, ' ')}</td>
                <td class="py-2.5 px-3 font-mono text-accent-cyan text-xs">
                    ${t.trigger_wallet ? `<span title="${t.trigger_wallet}">${t.trigger_wallet.slice(0, 4)}...${t.trigger_wallet.slice(-3)}</span>` : '<span class="text-gray-500">DIRECT</span>'}
                </td>
            </tr>
        `;
    }
    tbody.innerHTML = html;
    lucide.createIcons();
}

function filterTradeHistory() {
    const q = (document.getElementById('tradeHistorySearch')?.value || '').toLowerCase().trim();
    const rows = document.querySelectorAll('.trade-row');
    rows.forEach(r => {
        const text = r.getAttribute('data-search') || '';
        if (!q || text.includes(q)) {
            r.style.display = '';
        } else {
            r.style.display = 'none';
        }
    });
}

// Start WebSocket on page load
window.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
});

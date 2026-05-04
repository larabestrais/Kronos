// ============================================
// KRONOS SIGNAL // GRID — Dashboard Frontend
// ============================================

const API = {
  state: '/api/state',
  cycle: '/api/cycle',
  reset: '/api/reset',
};

const POLL_INTERVAL = 3000;
const NEON = '#ff5a3c';
const PINK = '#ff4d7a';
const AMBER = '#ffb347';
const GREEN = '#5fff8e';
const RED = '#ff3852';

let state = null;
let secCounter = 0;
let lastPnl = 0;
let cycleStartTime = null;

// ============================================
// UTILITIES
// ============================================

function formatMoney(v, signed = true) {
  if (v === null || v === undefined) return '—';
  const abs = Math.abs(v);
  let str;
  if (abs >= 1000) str = abs.toLocaleString('en-US', { maximumFractionDigits: 0 });
  else str = abs.toFixed(2);
  const sign = v >= 0 ? '+' : '-';
  return `${signed ? sign : ''}$${str}`;
}

function formatPct(v, decimals = 1) {
  if (v === null || v === undefined) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${v.toFixed(decimals)}%`;
}

function flashUpdate(el) {
  if (!el) return;
  el.classList.remove('flash-update');
  void el.offsetWidth;
  el.classList.add('flash-update');
}

function animateNumber(el, from, to, duration = 800, formatter = formatMoney) {
  if (!el) return;
  const start = performance.now();
  function tick(now) {
    const t = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - t, 3);
    const value = from + (to - from) * eased;
    el.textContent = formatter(value);
    if (t < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

// ============================================
// API
// ============================================

async function fetchState() {
  try {
    const res = await fetch(API.state);
    if (!res.ok) throw new Error(res.statusText);
    return await res.json();
  } catch (e) {
    console.error('[fetchState]', e);
    return null;
  }
}

async function runCycle() {
  const btn = document.getElementById('run-cycle-btn');
  btn.disabled = true;
  btn.textContent = '▶ RUNNING...';
  cycleStartTime = Date.now();
  try {
    const res = await fetch(API.cycle, { method: 'POST' });
    const data = await res.json();
    if (data.status === 'started') {
      console.log('Cycle started');
    }
  } catch (e) {
    console.error('[runCycle]', e);
  }
}

async function resetBot() {
  if (!confirm('Réinitialiser le portfolio ? Toutes les positions seront fermées.')) return;
  await fetch(API.reset, { method: 'POST' });
  await refresh();
}

// ============================================
// RENDERERS
// ============================================

function renderTopStats(s) {
  const summary = s.summary;

  const pnlEl = document.getElementById('stat-pnl');
  const newPnl = summary.pnl_total || 0;
  if (Math.abs(newPnl - lastPnl) > 0.01) {
    animateNumber(pnlEl, lastPnl, newPnl, 800);
    flashUpdate(pnlEl);
    lastPnl = newPnl;
  } else {
    pnlEl.textContent = formatMoney(newPnl);
  }
  pnlEl.style.color = newPnl >= 0 ? NEON : RED;

  document.getElementById('stat-win').textContent = `${s.win_rate}%`;
  document.getElementById('stat-win-sub').textContent = `${summary.trades_total} TRD`;

  const positions = s.positions || [];
  let avgHold = 0;
  if (positions.length > 0) {
    const now = Date.now();
    avgHold = positions.reduce((sum, p) => {
      const entry = new Date(p.entry_time).getTime();
      return sum + (now - entry) / 3600000;
    }, 0) / positions.length;
  }
  document.getElementById('stat-hold').textContent = `${avgHold.toFixed(1)}H`;

  document.getElementById('stat-pos').textContent = positions.length;

  const scansPerHour = s.summary.trades_total > 0 ? Math.round(s.summary.trades_total * 4) : 0;
  document.getElementById('stat-scan').textContent = scansPerHour > 999 ? `${(scansPerHour/1000).toFixed(1)}K/H` : `${scansPerHour}/H`;
}

function renderSignalRadar(s) {
  const list = document.getElementById('signal-list');
  const signals = s.signals || [];

  if (signals.length === 0) {
    list.innerHTML = '<div class="empty-state">EN ATTENTE DE CYCLE...</div>';
    return;
  }

  list.innerHTML = signals.slice(0, 6).map(sig => {
    const tagClass = sig.action === 'BUY' ? 'buy' : sig.action === 'SELL' ? 'sell' : '';
    const statusClass = sig.action === 'HOLD' ? 'hold' : '';
    const ret = (sig.predicted_return * 100).toFixed(1);
    return `
      <div class="signal-item">
        <span class="signal-tag ${tagClass}">${sig.symbol}</span>
        <div class="signal-content">
          <div class="signal-name">${sig.action} · ${ret}%</div>
          <div class="signal-meta">CONF ${(sig.confidence * 100).toFixed(0)}% · @ $${sig.current_close.toFixed(2)}</div>
        </div>
        <div class="signal-status ${statusClass}"></div>
      </div>
    `;
  }).join('');
}

function renderNews(s) {
  const list = document.getElementById('news-list');
  const news = s.news || [];

  if (news.length === 0) {
    list.innerHTML = '<div class="empty-state">EN ATTENTE...</div>';
    return;
  }

  list.innerHTML = news.slice(0, 12).map(n => {
    const tagClass = n.category.toLowerCase();
    return `
      <div class="news-item">
        <span class="news-tag ${tagClass}">${n.category}</span>
        <span class="news-text">${n.message}</span>
        <span class="news-time">${n.timestamp}</span>
      </div>
    `;
  }).join('');
}

function renderDeskMetrics(s) {
  const summary = s.summary;
  const deployed = summary.valeur_totale - summary.cash;
  document.getElementById('cap-deployed').textContent = formatMoney(deployed, false);

  const velocity = summary.trades_total / Math.max(1, (Date.now() - (cycleStartTime || Date.now())) / 1000 / 60);
  document.getElementById('cap-velocity').textContent = velocity > 0 ? `${velocity.toFixed(1)}x` : '0.0x';
}

function updateFlowTimer() {
  if (!cycleStartTime) {
    document.getElementById('flow-timer').textContent = '00:00:00';
    return;
  }
  const elapsed = Math.floor((Date.now() - cycleStartTime) / 1000);
  const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
  const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
  const sec = String(elapsed % 60).padStart(2, '0');
  document.getElementById('flow-timer').textContent = `${h}:${m}:${sec}`;
}

function renderPulse(s) {
  const summary = s.summary;
  const pnl = summary.pnl_total || 0;
  document.getElementById('pulse-pnl').textContent = formatMoney(pnl);
  document.getElementById('pulse-pnl').style.color = pnl >= 0 ? NEON : RED;

  const pctEl = document.getElementById('pulse-pct');
  const pct = summary.pnl_total_pct || 0;
  const arrow = pct >= 0 ? '▲' : '▼';
  pctEl.textContent = `${arrow} ${formatPct(pct)} TOTAL`;
  pctEl.className = pct >= 0 ? 'meta-positive' : 'meta-negative';

  const equity = s.equity || [];
  let sharpe = 0;
  if (equity.length > 5) {
    const values = equity.map(e => e.total_value);
    const returns = [];
    for (let i = 1; i < values.length; i++) {
      returns.push((values[i] - values[i-1]) / values[i-1]);
    }
    const mean = returns.reduce((a,b) => a+b, 0) / returns.length;
    const std = Math.sqrt(returns.reduce((a,b) => a + Math.pow(b - mean, 2), 0) / returns.length);
    sharpe = std > 0 ? (mean / std) * Math.sqrt(252) : 0;
  }
  document.getElementById('sharpe').textContent = sharpe.toFixed(2);

  const sessionId = String(Math.floor(equity.length / 10)).padStart(3, '0');
  document.getElementById('session-id').textContent = sessionId;

  const bidFlow = pnl >= 0 ? Math.min(95, 50 + Math.abs(pct)) : Math.max(5, 50 - Math.abs(pct));
  document.getElementById('bid-flow-pct').textContent = `${Math.round(bidFlow)}%`;
  document.getElementById('bid-flow-bar').style.width = `${bidFlow}%`;

  const notional = summary.valeur_totale - summary.cash;
  document.getElementById('notional').textContent = `+${notional.toFixed(0)}`;
  document.getElementById('match-speed').innerHTML = `${(40 + Math.random() * 8).toFixed(0)}<span class="unit">ms</span>`;
  document.getElementById('impact-bps').textContent = (Math.abs(pct) * 0.4).toFixed(2);

  drawEquityChart(equity);
  drawVolumeChart(equity);
}

function renderFlow(s) {
  document.getElementById('flow-percent').textContent = `${Math.round(s.long_pct)}%`;
  document.getElementById('flow-direction').textContent = s.long_pct >= 50 ? 'LONG' : 'SHORT';
  document.getElementById('flow-pnl').textContent = formatMoney(s.summary.pnl_total);
}

function renderPositions(s) {
  const list = document.getElementById('positions-list');
  const positions = s.positions || [];

  document.getElementById('positions-count').textContent = positions.length;

  if (positions.length === 0) {
    list.innerHTML = '<div class="empty-state">AUCUNE POSITION</div>';
    return;
  }

  list.innerHTML = positions.map(p => {
    const cls = p.side.toLowerCase();
    const pnlCls = p.unrealized_pnl >= 0 ? 'positive' : 'negative';
    return `
      <div class="whale-item ${cls}">
        <span class="whale-symbol">${p.symbol} <span style="color: var(--text-muted); font-size: 9px;">${p.side}</span></span>
        <span class="whale-pnl ${pnlCls}">${formatMoney(p.unrealized_pnl)}</span>
        <span class="whale-pct">${formatPct(p.pnl_pct, 1)}</span>
      </div>
    `;
  }).join('');
}

function renderConfidenceMix(s) {
  const signals = s.signals || [];
  if (signals.length === 0) {
    document.getElementById('conf-low').style.width = '0%';
    document.getElementById('conf-med').style.width = '0%';
    document.getElementById('conf-high').style.width = '0%';
    return;
  }

  let low = 0, med = 0, high = 0;
  signals.forEach(sig => {
    if (sig.confidence < 0.4) low++;
    else if (sig.confidence < 0.7) med++;
    else high++;
  });

  const total = signals.length;
  document.getElementById('conf-low').style.width = `${(low / total) * 100}%`;
  document.getElementById('conf-med').style.width = `${(med / total) * 100}%`;
  document.getElementById('conf-high').style.width = `${(high / total) * 100}%`;
}

function renderSymbolYield(s) {
  const list = document.getElementById('sector-list');
  const trades = s.trades || [];

  const symbolPnl = {};
  trades.forEach(t => {
    if (t.side.startsWith('CLOSE')) {
      symbolPnl[t.symbol] = (symbolPnl[t.symbol] || { pnl: 0, count: 0 });
      symbolPnl[t.symbol].pnl += t.pnl;
      symbolPnl[t.symbol].count++;
    }
  });

  (s.signals || []).forEach(sig => {
    if (!symbolPnl[sig.symbol]) {
      symbolPnl[sig.symbol] = { pnl: 0, count: 0, signal: true };
    }
  });

  const symbols = Object.entries(symbolPnl);
  document.getElementById('sector-count').textContent = `${symbols.length} SYM`;

  if (symbols.length === 0) {
    list.innerHTML = '<div class="empty-state">EN ATTENTE...</div>';
    return;
  }

  const maxAbs = Math.max(...symbols.map(([_, v]) => Math.abs(v.pnl)), 1);

  list.innerHTML = symbols.slice(0, 5).map(([sym, v]) => {
    const width = Math.max(5, (Math.abs(v.pnl) / maxAbs) * 100);
    return `
      <div class="sector-row">
        <div class="sector-info">
          <span class="sector-name">${sym}</span>
          <div class="sector-bar"><div class="sector-bar-fill" style="width: ${width}%"></div></div>
        </div>
        <div class="sector-meta">
          <span class="sector-value">${formatMoney(v.pnl)}</span>
          <span class="sector-trades">${v.count} TRD</span>
        </div>
      </div>
    `;
  }).join('');
}

function renderConfig(s) {
  document.getElementById('info-model').textContent = (s.config.model || '').split('/').pop();
  document.getElementById('info-pred-len').textContent = s.config.pred_len;
  document.getElementById('info-symbols').textContent = (s.config.symbols || []).join(' · ');
}

// ============================================
// CHARTS (Canvas)
// ============================================

function drawEquityChart(equity) {
  const canvas = document.getElementById('equity-chart');
  if (!canvas) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  ctx.clearRect(0, 0, w, h);

  // Grid background
  ctx.strokeStyle = 'rgba(255, 90, 60, 0.06)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i++) {
    const y = (h / 5) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
  for (let i = 0; i <= 8; i++) {
    const x = (w / 8) * i;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }

  // Données: si vide, courbe simulée pour montrer le design
  let values;
  if (equity.length < 2) {
    values = Array.from({ length: 50 }, (_, i) => 10000 + Math.sin(i / 5) * 200 + i * 30 + Math.random() * 100);
  } else {
    values = equity.map(e => e.total_value);
  }

  if (values.length < 2) return;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const padding = 20;

  const xStep = (w - padding * 2) / (values.length - 1);
  const points = values.map((v, i) => ({
    x: padding + i * xStep,
    y: padding + (h - padding * 2) * (1 - (v - min) / range),
  }));

  // Gradient fill
  const fillGrad = ctx.createLinearGradient(0, 0, 0, h);
  fillGrad.addColorStop(0, 'rgba(255, 90, 60, 0.3)');
  fillGrad.addColorStop(1, 'rgba(255, 90, 60, 0)');

  ctx.beginPath();
  ctx.moveTo(points[0].x, h - padding);
  points.forEach(p => ctx.lineTo(p.x, p.y));
  ctx.lineTo(points[points.length - 1].x, h - padding);
  ctx.closePath();
  ctx.fillStyle = fillGrad;
  ctx.fill();

  // Glow line (multi-pass)
  ctx.shadowColor = NEON;
  ctx.shadowBlur = 16;
  ctx.strokeStyle = NEON;
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';

  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i++) {
    ctx.lineTo(points[i].x, points[i].y);
  }
  ctx.stroke();

  ctx.shadowBlur = 0;
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = '#ffaa88';
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i++) {
    ctx.lineTo(points[i].x, points[i].y);
  }
  ctx.stroke();

  // End point glow
  const last = points[points.length - 1];
  ctx.shadowColor = NEON;
  ctx.shadowBlur = 20;
  ctx.fillStyle = NEON;
  ctx.beginPath();
  ctx.arc(last.x, last.y, 4, 0, Math.PI * 2);
  ctx.fill();

  ctx.shadowBlur = 0;
  ctx.fillStyle = '#fff';
  ctx.beginPath();
  ctx.arc(last.x, last.y, 1.5, 0, Math.PI * 2);
  ctx.fill();
}

function drawVolumeChart(equity) {
  const canvas = document.getElementById('volume-chart');
  if (!canvas) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  ctx.clearRect(0, 0, w, h);

  let bars;
  if (equity.length < 2) {
    bars = Array.from({ length: 50 }, () => 0.3 + Math.random() * 0.7);
  } else {
    bars = [];
    for (let i = 1; i < equity.length; i++) {
      const change = Math.abs(equity[i].total_value - equity[i-1].total_value);
      bars.push(change);
    }
    if (bars.length === 0) bars = [1];
    const maxB = Math.max(...bars, 0.01);
    bars = bars.map(b => 0.2 + (b / maxB) * 0.8);
  }

  const padding = 20;
  const barWidth = (w - padding * 2) / bars.length;
  const gap = barWidth * 0.2;

  bars.forEach((v, i) => {
    const x = padding + i * barWidth;
    const barH = v * (h - 8);
    const y = h - barH;

    const grad = ctx.createLinearGradient(x, y, x, h);
    grad.addColorStop(0, NEON);
    grad.addColorStop(0.5, AMBER);
    grad.addColorStop(1, 'rgba(255, 179, 71, 0.3)');
    ctx.fillStyle = grad;
    ctx.shadowColor = NEON;
    ctx.shadowBlur = 4;
    ctx.fillRect(x + gap / 2, y, barWidth - gap, barH);
  });
  ctx.shadowBlur = 0;
}

// ============================================
// MAIN LOOP
// ============================================

async function refresh() {
  const newState = await fetchState();
  if (!newState) return;
  state = newState;

  if (state.cycle_running && cycleStartTime === null) {
    cycleStartTime = Date.now();
  } else if (!state.cycle_running && cycleStartTime !== null) {
    const btn = document.getElementById('run-cycle-btn');
    btn.disabled = false;
    btn.textContent = '▶ RUN CYCLE';
  }

  renderTopStats(state);
  renderSignalRadar(state);
  renderNews(state);
  renderDeskMetrics(state);
  renderPulse(state);
  renderFlow(state);
  renderPositions(state);
  renderConfidenceMix(state);
  renderSymbolYield(state);
  renderConfig(state);
}

function tickSecCounter() {
  secCounter++;
  document.getElementById('sec-counter').textContent = String(secCounter).padStart(3, '0');
}

// ============================================
// INIT
// ============================================

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('run-cycle-btn').addEventListener('click', runCycle);
  document.getElementById('reset-btn').addEventListener('click', resetBot);

  refresh();
  setInterval(refresh, POLL_INTERVAL);
  setInterval(tickSecCounter, 1000);
  setInterval(updateFlowTimer, 1000);

  window.addEventListener('resize', () => {
    if (state) {
      drawEquityChart(state.equity || []);
      drawVolumeChart(state.equity || []);
    }
  });

  // Demo charts on first load
  drawEquityChart([]);
  drawVolumeChart([]);
});

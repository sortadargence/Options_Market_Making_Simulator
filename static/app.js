const defaults = JSON.parse(document.getElementById('defaults').textContent);
const form = document.getElementById('controls-form');
const state = { result: null, config: null, index: 0, timer: null, multiRun: null, multiSeeds: null, multiRunning: false };
const colors = { stock: '#4de1d2', ask: '#eeb765', bid: '#f18b8a', model: '#73a8f1', truth: '#4de1d2', pnl: '#eeb765', hedge: '#f18b8a' };
const $ = id => document.getElementById(id);
const money = value => value == null ? '—' : (value < 0 ? '−' : '') + Math.abs(value).toFixed(3);
const signed = value => value == null ? '—' : (value >= 0 ? '+' : '−') + Math.abs(value).toFixed(3);
const signedPrecise = value => value == null ? '—' : (value >= 0 ? '+' : '−') + Math.abs(value).toFixed(5);
const compact = value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 });

for (const [name, value] of Object.entries(defaults)) {
  const input = form.elements.namedItem(name);
  if (input && value !== null) input.value = value;
}
const followVolatility = $('follow-volatility');
followVolatility.checked = defaults.pricing_volatility === null;
function syncPricingVolatility() {
  const input = form.elements.namedItem('pricing_volatility');
  input.disabled = followVolatility.checked;
  input.required = !followVolatility.checked;
  $('pricing-vol-field').classList.toggle('dimmed', followVolatility.checked);
}
followVolatility.addEventListener('change', syncPricingVolatility);
syncPricingVolatility();

function readPayload() {
  if (!form.reportValidity()) throw new Error('Check the highlighted inputs.');
  const data = {};
  for (const [name, value] of new FormData(form).entries()) {
    data[name] = ['option_type', 'price_path_model', 'option_pricing_model'].includes(name) ? value : Number(value);
  }
  data.pricing_volatility = followVolatility.checked ? null : Number(form.elements.namedItem('pricing_volatility').value);
  const seed = form.elements.namedItem('seed').value.trim();
  data.seed = seed === '' ? null : Number(seed);
  return data;
}

function showMessage(message) {
  $('message').textContent = message;
  $('message').hidden = !message;
}

async function postJson(url, data) {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  let payload;
  try { payload = await response.json(); } catch { throw new Error('The server did not return JSON.'); }
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status}).`);
  return payload;
}

async function postJsonLines(url, data, onEvent) {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `Request failed (${response.status}).`);
  }
  if (!response.body) throw new Error('This browser cannot read the progress stream.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finished = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      let newline;
      while ((newline = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (line) await onEvent(JSON.parse(line));
      }
      if (done) break;
    }
    if (buffer.trim()) await onEvent(JSON.parse(buffer));
    finished = true;
  } finally {
    if (!finished) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

function stopReplay() {
  if (state.timer !== null) clearInterval(state.timer);
  state.timer = null;
  $('play-button').textContent = '▶ Play';
}

function setTab(name) {
  for (const tab of document.querySelectorAll('.tab')) {
    const active = tab.dataset.tab === name;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
  }
  $('replay-panel').hidden = name !== 'replay';
  $('multi-run-panel').hidden = name !== 'multi-run';
  if (name !== 'replay') stopReplay();
}
document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => setTab(tab.dataset.tab)));

form.addEventListener('input', event => {
  if (state.result) $('run-badge').textContent = 'INPUTS CHANGED';
  if (state.multiRun && !state.multiRunning && event.target.name !== 'seed') $('multi-run-status').textContent = 'Inputs changed. The chart still shows the previous 40 runs.';
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  stopReplay();
  showMessage('');
  let data;
  try { data = readPayload(); } catch (error) { showMessage(error.message); return; }
  const button = $('run-button');
  button.disabled = true;
  button.firstElementChild.textContent = 'Running simulation…';
  $('run-badge').textContent = 'CALCULATING';
  try {
    const payload = await postJson('/api/simulate', data);
    state.result = payload.result;
    state.config = payload.config;
    state.index = 0;
    $('tick-slider').max = state.result.t.length - 1;
    $('tick-slider').disabled = false;
    $('play-button').disabled = false;
    $('step-button').disabled = false;
    $('run-badge').textContent = 'RUN COMPLETE';
    setTab('replay');
    renderReplay();
  } catch (error) {
    showMessage(error.message);
    $('run-badge').textContent = state.result ? 'LAST RUN AVAILABLE' : 'READY TO RUN';
  } finally {
    button.disabled = false;
    button.firstElementChild.textContent = 'Run experiment';
  }
});

function setIndex(index) {
  if (!state.result) return;
  state.index = Math.max(0, Math.min(state.result.t.length - 1, index));
  renderReplay();
  if (state.index === state.result.t.length - 1) stopReplay();
}
$('tick-slider').addEventListener('input', event => { stopReplay(); setIndex(Number(event.target.value)); });
$('step-button').addEventListener('click', () => { stopReplay(); setIndex(state.index + 1); });
$('play-button').addEventListener('click', () => {
  if (!state.result) return;
  if (state.timer !== null) { stopReplay(); return; }
  if (state.index >= state.result.t.length - 1) setIndex(0);
  $('play-button').textContent = 'Ⅱ Pause';
  state.timer = setInterval(() => setIndex(state.index + 1), Number($('speed-select').value));
});
$('speed-select').addEventListener('change', () => {
  if (state.timer !== null) { stopReplay(); $('play-button').click(); }
});

const chart = { width: 640, height: 230, left: 48, right: 14, top: 14, bottom: 30 };
const plotWidth = chart.width - chart.left - chart.right;
const plotHeight = chart.height - chart.top - chart.bottom;
function scaleRange(values, includeZero = false) {
  const finite = values.filter(Number.isFinite);
  let low = finite.length ? Math.min(...finite) : 0;
  let high = finite.length ? Math.max(...finite) : 1;
  if (includeZero) { low = Math.min(low, 0); high = Math.max(high, 0); }
  const pad = (high - low || Math.max(Math.abs(high), 1)) * 0.08;
  return [low - pad, high + pad];
}
function yValue(value, range) { return chart.top + (range[1] - value) * plotHeight / (range[1] - range[0]); }
function xValue(index, length) { return chart.left + index * plotWidth / Math.max(1, length - 1); }
function svgBase(range, startLabel = '0', endLabel = '', formatter = money) {
  let markup = '';
  for (let line = 0; line <= 3; line++) {
    const y = chart.top + line * plotHeight / 3;
    const value = range[1] - line * (range[1] - range[0]) / 3;
    markup += `<line class="gridline" x1="${chart.left}" y1="${y}" x2="${chart.width - chart.right}" y2="${y}"/><text class="axis-label" x="${chart.left - 6}" y="${y + 3}" text-anchor="end">${formatter(value)}</text>`;
  }
  markup += `<text class="axis-label" x="${chart.left}" y="${chart.height - 5}">${startLabel}</text><text class="axis-label" x="${chart.width - chart.right}" y="${chart.height - 5}" text-anchor="end">${endLabel}</text>`;
  return markup;
}
function polyline(values, range, length, color, width = 2, opacity = 1) {
  if (length === 1) {
    return `<circle cx="${xValue(0, values.length)}" cy="${yValue(values[0], range)}" r="3" fill="${color}" fill-opacity="${opacity}"/>`;
  }
  const points = values.slice(0, length).map((value, index) => `${xValue(index, values.length).toFixed(1)},${yValue(value, range).toFixed(1)}`).join(' ');
  return `<polyline fill="none" stroke="${color}" stroke-width="${width}" stroke-opacity="${opacity}" stroke-linejoin="round" stroke-linecap="round" points="${points}"/>`;
}
function drawLines(id, series, length, cursor = null, includeZero = false, endLabel = '', showZero = false, formatter = money) {
  const svg = $(id);
  const total = series[0].values.length;
  const range = scaleRange(series.flatMap(item => item.values.slice(0, length)), includeZero);
  let markup = svgBase(range, '0', endLabel, formatter);
  if (showZero) {
    const zeroY = yValue(0, range);
    markup += `<line class="zero-line" x1="${chart.left}" x2="${chart.width - chart.right}" y1="${zeroY}" y2="${zeroY}"/>`;
  }
  for (const item of series) markup += polyline(item.values, range, length, item.color, item.width || 2, item.opacity || 1);
  if (cursor !== null) {
    const x = xValue(cursor, total);
    markup += `<line class="cursor" x1="${x}" x2="${x}" y1="${chart.top}" y2="${chart.top + plotHeight}"/>`;
    for (const item of series) markup += `<circle class="cursor-dot" cx="${x}" cy="${yValue(item.values[cursor], range)}" r="4" fill="${item.color}"/>`;
  }
  svg.setAttribute('viewBox', `0 0 ${chart.width} ${chart.height}`);
  svg.innerHTML = markup;
}

function renderReplay() {
  const r = state.result;
  if (!r) return;
  const i = state.index;
  const end = r.t.length - 1;
  $('tick-slider').value = i;
  $('tick-indicator').textContent = `TICK ${i} / ${end}`;
  $('stock-current').textContent = money(r.S[i]);
  $('quote-time').textContent = `t = ${r.t[i].toFixed(3)} yr`;
  $('quote-heading').textContent = i === end ? 'FINAL OBSERVATION' : 'POSTED QUOTE';
  $('quote-bid').textContent = money(r.bid[i]);
  $('quote-ask').textContent = money(r.ask[i]);
  $('quote-model').textContent = money(r.model_price[i]);
  $('quote-truth').textContent = money(r.true_price[i]);
  $('metric-pnl').textContent = signed(r.realized_pnl[i]);
  $('metric-pnl').className = r.realized_pnl[i] < 0 ? 'negative' : 'positive';
  $('metric-volume').textContent = compact(r.cumulative_volume[i]);
  $('metric-average').textContent = signed(r.average_fill_pnl[i]);
  $('metric-average').className = r.average_fill_pnl[i] == null ? '' : (r.average_fill_pnl[i] < 0 ? 'negative' : 'positive');
  $('metric-average-contract').textContent = `Per contract ${signed(r.average_trade_pnl[i])}`;
  $('metric-sides').textContent = `Bought ${compact(r.buy_fills[i])} · Sold ${compact(r.sell_fills[i])}`;
  $('metric-model-edge').textContent = signed(r.model_marked_to_market[i]);
  $('metric-truth-edge').textContent = signed(r.true_marked_to_market[i]);
  if (i === 0) {
    $('quote-fills').textContent = '—';
    $('quote-callout').textContent = 'This quote is posted. Move one tick to see its fills and completed trade outcomes.';
  } else {
    const buys = r.buy_fills[i] - r.buy_fills[i - 1];
    const sells = r.sell_fills[i] - r.sell_fills[i - 1];
    const pnl = r.realized_pnl[i] - r.realized_pnl[i - 1];
    $('quote-fills').textContent = `${compact(buys)} bought · ${compact(sells)} sold`;
    let note = buys + sells ? `At prior quote #${i - 1}, ${compact(buys + sells)} contracts filled. Their combined discounted P&L: ${signed(pnl)}.` : `No fills at prior quote #${i - 1}.`;
    if (i === end) note += ' No new fill is drawn at this final observation.';
    $('quote-callout').textContent = note;
  }
  if (r.bid[i] < 0) $('quote-callout').textContent += ' The simulated bid is negative.';
  $('summary-card').hidden = i !== end;
  if (i === end) {
    const summary = r.summary;
    $('summary-average').textContent = signed(summary.average_realized_edge);
    $('summary-drawdown').textContent = money(summary.realized_max_drawdown);
    $('summary-volatility').textContent = money(summary.pnl_step_volatilty);
    $('summary-match').textContent = summary.models_match ? 'Yes · family only' : 'No';
  }
  drawLines('stock-chart', [{ values: r.S, color: colors.stock }], i + 1, i, false, `${state.config.simulation_horizon} yr`);
  drawLines('quote-chart', [
    { values: r.ask, color: colors.ask }, { values: r.bid, color: colors.bid },
    { values: r.model_price, color: colors.model }, { values: r.true_price, color: colors.truth, width: 2.5 }
  ], i + 1, i, false, `${state.config.simulation_horizon} yr`);
  drawLines('pnl-chart', [
    { values: r.realized_pnl, color: colors.pnl, width: 2.5 },
    { values: r.model_marked_to_market, color: colors.model },
    { values: r.true_marked_to_market, color: colors.truth }
  ], i + 1, i, true, `${state.config.simulation_horizon} yr`);
  updateTradeSelect();
}

function updateTradeSelect() {
  const select = $('trade-select');
  const available = state.result.trade_examples.filter(trade => trade.quote_index < state.index);
  const prior = select.value;
  select.replaceChildren();
  if (!available.length) {
    select.add(new Option('No completed fills yet', ''));
    select.disabled = true;
    $('trade-empty').hidden = false;
    $('trade-empty').textContent = state.result.trade_examples.length ? 'Play or scrub forward to the first fill.' : 'No fills were generated in this run.';
    $('trade-detail').hidden = true;
    return;
  }
  available.forEach((trade, index) => select.add(new Option(`#${index + 1} · tick ${trade.quote_index} · ${trade.side} ${trade.quantity}`, String(index))));
  select.disabled = false;
  select.value = prior !== '' && available[Number(prior)] ? prior : String(available.length - 1);
  $('trade-empty').hidden = true;
  $('trade-detail').hidden = false;
  renderTrade(available[Number(select.value)]);
}
$('trade-select').addEventListener('change', () => renderTrade(state.result.trade_examples[Number($('trade-select').value)]));

function renderTrade(trade) {
  if (!trade) return;
  const trace = trade.trace;
  const rows = trace.rows;
  const signedQuantity = trade.side === 'buy' ? trade.quantity : -trade.quantity;
  const residuals = rows.map(row => row.reference_residual_shares);
  const pieces = [
    ['Side', `${trade.side.toUpperCase()} ${trade.quantity}`], ['Premium / contract', money(trade.premium)],
    ['Premium cash PV', signed(trace.premium_pv)], ['Option payoff PV', signed(trace.payoff_pv)],
    ['Total trade P&L', signed(trace.total_pnl)],
    ['Initial position Δ · shares', signedPrecise(signedQuantity * rows[0].delta)],
    ['Initial stock hedge · shares', signedPrecise(rows[0].hedge_shares)],
    ['Initial residual · shares', signedPrecise(residuals[0])],
    ['Max |residual| · shares', Math.max(...residuals.map(Math.abs)).toFixed(5)]
  ];
  $('trade-summary').replaceChildren(...pieces.map(([label, value]) => {
    const item = document.createElement('span');
    item.textContent = `${label} · `;
    const strong = document.createElement('strong');
    strong.textContent = value;
    item.append(strong);
    return item;
  }));
  const spots = [trade.starting_spot, ...rows.map(row => row.spot_end)];
  const hedge = [rows[0].hedge_shares, ...rows.map(row => row.hedge_shares)];
  drawDualLines('hedge-chart', spots, hedge, state.config.T);
  drawLines('delta-compare-chart', [
    { values: rows.map(row => row.delta), color: colors.model, width: 2.5 },
    { values: rows.map(row => row.reference_delta), color: colors.truth, width: 2.5 }
  ], rows.length, null, false, `${rows.length} hedge steps`, false, value => value.toFixed(4));
  drawLines('delta-residual-chart', [
    { values: residuals, color: colors.pnl, width: 2.5 }
  ], rows.length, null, true, `${rows.length} hedge steps`, true, value => value.toFixed(5));
  $('hedge-rows').replaceChildren(...rows.map((row, index) => {
    const tr = document.createElement('tr');
    const values = [index + 1, row.time.toFixed(3), `${money(row.spot_start)} → ${money(row.spot_end)}`, row.delta.toFixed(4), row.reference_delta.toFixed(4), signedPrecise(signedQuantity * row.delta), signedPrecise(row.hedge_shares), signedPrecise(row.reference_residual_shares), signed(row.stock_move_pv), signed(row.funding_pv), signed(row.dividend_pv), signed(row.step_pnl_pv)];
    values.forEach(value => { const td = document.createElement('td'); td.textContent = value; tr.append(td); });
    return tr;
  }));
}

function drawDualLines(id, leftValues, rightValues, timeEnd) {
  const svg = $(id);
  const left = scaleRange(leftValues);
  const right = scaleRange(rightValues);
  let markup = svgBase(left, '0', `${timeEnd} yr`);
  markup += polyline(leftValues, left, leftValues.length, colors.stock, 2.5);
  markup += polyline(rightValues, right, rightValues.length, colors.hedge, 2);
  markup += `<text class="axis-label" x="${chart.width - 2}" y="${chart.top + 8}" text-anchor="end">shares ${right[1].toFixed(2)}</text>`;
  markup += `<text class="axis-label" x="${chart.width - 2}" y="${chart.top + plotHeight - 2}" text-anchor="end">${right[0].toFixed(2)}</text>`;
  svg.setAttribute('viewBox', `0 0 ${chart.width} ${chart.height}`);
  svg.innerHTML = markup;
}

$('multi-run-button').addEventListener('click', async () => {
  showMessage('');
  let data;
  try { data = readPayload(); } catch (error) { showMessage(error.message); return; }
  const reused = $('reuse-seeds').checked && state.multiSeeds !== null;
  if (reused) data.seeds = state.multiSeeds;
  const button = $('multi-run-button');
  button.disabled = true;
  button.firstElementChild.textContent = 'Starting 40 runs…';
  state.multiRunning = true;
  $('multi-run-status').textContent = 'Starting 40 runs…';
  $('multi-run-progress').hidden = false;
  $('multi-run-progress').value = 0;
  let completed = false;
  let started = false;
  let pendingSeeds = null;
  try {
    await postJsonLines('/api/multi-run/stream', data, async event => {
      if (event.type === 'error') throw new Error(event.error);
      if (event.type === 'start') {
        started = true;
        pendingSeeds = event.seeds;
        state.multiRun = { paths: [], average_pnl: [], total_pnl: 0, total_contracts: 0,
          buy_pnl: 0, buy_contracts: 0, sell_pnl: 0, sell_contracts: 0,
          loss_runs: 0, half_spread: event.config.half_spread };
        const path = event.config.price_path_model === 'merton_jump_diffusion' ? 'Merton jumps' : 'GBM';
        const maker = event.config.option_pricing_model === 'merton_jump_diffusion' ? 'Merton jumps' : 'Black–Scholes–Merton';
        const makerVolatility = event.config.pricing_volatility ?? event.config.volatility;
        $('multi-run-settings').textContent = `Running: path ${path} (σ ${event.config.volatility}) · maker ${maker} (σ ${makerVolatility}) · half spread ${money(event.config.half_spread)}`;
        $('multi-run-content').hidden = true;
        $('multi-run-empty').hidden = false;
        $('multi-run-empty').textContent = 'Waiting for the first completed seed…';
      } else if (event.type === 'run') {
        const result = state.multiRun;
        const record = event.record;
        const count = result.paths.length + 1;
        result.paths.push({ seed: record.seed, pnl: record.pnl });
        if (count === 1) result.average_pnl = record.pnl.slice();
        else record.pnl.forEach((value, index) => {
          result.average_pnl[index] += (value - result.average_pnl[index]) / count;
        });
        result.total_pnl += record.pnl.at(-1);
        result.total_contracts += record.contracts;
        result.buy_pnl += record.buy_pnl;
        result.buy_contracts += record.buy_contracts;
        result.sell_pnl += record.sell_pnl;
        result.sell_contracts += record.sell_contracts;
        result.loss_runs += Number(record.pnl.at(-1) < 0);
        $('multi-run-progress').value = count;
        $('multi-run-status').textContent = `${count} of 40 seeds complete. The mean now includes ${count} ${count === 1 ? 'run' : 'runs'}.`;
        button.firstElementChild.textContent = `Running ${count} / 40…`;
        renderMultiRun();
        await new Promise(resolve => setTimeout(resolve, 16));
      } else if (event.type === 'done') {
        if (!state.multiRun || state.multiRun.paths.length !== 40) throw new Error('The stream ended before all 40 seeds finished.');
        completed = true;
        state.multiSeeds = pendingSeeds;
        $('reuse-seeds').disabled = false;
        $('multi-run-status').textContent = `All 40 seeds complete. ${reused ? 'Reused' : 'Generated'} the ${reused ? 'previous' : 'new'} seed batch.`;
      }
    });
    if (!completed) throw new Error('The stream ended before all 40 seeds finished.');
  } catch (error) {
    showMessage(error.message);
    $('multi-run-status').textContent = started && state.multiRun?.paths.length
      ? `Stopped after ${state.multiRun.paths.length} of 40 seeds. Results shown are partial.`
      : 'The comparison could not start.';
  } finally {
    state.multiRunning = false;
    button.disabled = false;
    button.firstElementChild.textContent = 'Run 40 seeds';
  }
});

function renderMultiRun() {
  const result = state.multiRun;
  const count = result.paths.length;
  $('multi-run-empty').hidden = true;
  $('multi-run-content').hidden = false;
  const metric = (id, value) => {
    $(id).textContent = signed(value);
    $(id).className = value == null ? '' : (value < 0 ? 'negative' : 'positive');
  };
  metric('multi-mean', result.average_pnl.at(-1));
  $('multi-mean-sub').textContent = `Average of ${count} completed ${count === 1 ? 'run' : 'runs'}`;
  metric('multi-per-contract', result.total_contracts ? result.total_pnl / result.total_contracts : null);
  $('multi-half-spread').textContent = money(result.half_spread);
  $('multi-losses').textContent = `${result.loss_runs} / ${count}`;
  $('multi-losses-sub').textContent = `Out of ${count} completed ${count === 1 ? 'run' : 'runs'}`;
  metric('multi-buy', result.buy_contracts ? result.buy_pnl / result.buy_contracts : null);
  metric('multi-sell', result.sell_contracts ? result.sell_pnl / result.sell_contracts : null);
  const lines = [
    ...result.paths.map(path => ({ values: path.pnl, color: colors.model, opacity: .3, width: 1.2 })),
    { values: result.average_pnl, color: colors.stock, opacity: 1, width: 3.5 }
  ];
  drawLines('multi-run-chart', lines, result.average_pnl.length, null, true, `${result.average_pnl.length - 1} ticks`);
}



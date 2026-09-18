'use strict';
const SCREENS = [
  ['PORT', 'PORTFOLIO'], ['PERF', 'PERFORMANCE'], ['PNL', 'REALIZED P&L'], ['TRD', 'TRADES'],
  ['ALOC', 'ALLOCATION'], ['RULE', 'RULES'], ['EVT', 'EVENTS'], ['INC', 'INCOME'], ['AUD', 'DECISION AUDIT'], ['SIM', 'WHAT-IF'], ['DATA', 'DATA & FETCH'], ['IMP', 'IMPORT'],
];
const NO_DATA_OK = new Set(['IMP', 'DATA', 'HELP']);
const BENCH_COLOR = { 'XEQT.TO': 'var(--s2)', 'VOO': 'var(--s3)' };
const state = { screen: 'PORT', range: 'ALL', mode: 'VALUE', basis: 'INVESTED', acct: 'ALL', tradeAcct: 'ALL', tradeSym: '', sym: null,
  imp: { preview: null, busy: false, force: false, result: null },
  contribMonths: '12', optionFocus: null, auditHorizon: '20d', auditDay: null, auditPlaying: false, auditSpeed: 650, auditRefocus: false, auditLoading: false, intradaySpan: '5D', simMode: 'FREEZE', frz: { date: null, trade: null, deposits: 'CASH', result: null, sweep: null, sweepFor: null, busy: false, chart: 'RETURN', sym: '', err: '' },
  simAcct: 'ALL', simSym: '', simSide: 'ALL', simRedirect: 'CASH', simSel: new Set(loadSel()), simResult: null };
let vimMode = (() => { try { return localStorage.getItem('vim-mode') === '1'; } catch { return false; } })();
function loadSel() { try { return JSON.parse(localStorage.getItem('sim-exclude') || '[]'); } catch { return []; } }
function saveSel() { try { localStorage.setItem('sim-exclude', JSON.stringify([...state.simSel])); } catch {} }
let D = null;

// ---------- helpers ----------
// Every call goes through api(): the custom header is the server's CSRF check.
async function api(path, { method = 'GET', json, body } = {}) {
  const headers = { 'X-Requested-With': 'portfolio' };
  if (json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
  const r = await fetch(path, { method, headers, body, cache: 'no-store' });
  let data = null;
  try { data = await r.json(); } catch { data = { ok: false, log: `${r.status} ${r.statusText}` }; }
  if (!r.ok && data && data.ok === undefined) data.ok = false;
  if (!r.ok && data && !data.log) data.log = data.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : `${r.status}`;
  return { status: r.status, data };
}
const $ = (s, el = document) => el.querySelector(s);
const RAW_TRANSLATABLE = new Set(['USD CASH', 'CAD CASH']);  // generated labels that share the ticker column
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  const raw = attrs.raw;
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false || k === 'raw') continue;
    if (k === 'title' || k === 'placeholder' || k === 'aria-label') { el.setAttribute(k, tr(v)); continue; }
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'style') el.style.cssText = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) {
    const text = kid instanceof Node ? null : String(kid);
    el.append(kid instanceof Node ? kid : document.createTextNode(raw && !RAW_TRANSLATABLE.has(text) ? text : tr(text)));
  }
  return el;
}
const svgNS = 'http://www.w3.org/2000/svg';
function s(tag, attrs = {}) { const el = document.createElementNS(svgNS, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); return el; }
const nf0 = new Intl.NumberFormat('en-CA', { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money = (v, d = 0) => v == null ? '—' : (v < 0 ? '-' : '') + '$' + (d ? nf2 : nf0).format(Math.abs(v));
const num = (v, d = 2) => v == null ? '—' : (d ? nf2 : nf0).format(v);
const pct = (v, d = 1) => v == null ? '—' : (v * 100).toFixed(d) + '%';
function signed(v, fmt = money, eps = 0.005) {  // gain/loss never relies on color alone; eps = half the smallest shown unit
  if (v == null) return h('span', { class: 'mut' }, '—');
  const cls = v >= eps ? 'up' : v <= -eps ? 'down' : 'mut';
  const g = v >= eps ? '▲' : v <= -eps ? '▼' : '';
  return h('span', { class: cls }, `${g}${fmt(Math.abs(v))}`);  // the glyph carries the sign
}
const signedPct = (v, d = 1) => signed(v, x => pct(x, d), 0.5 * 10 ** -(d + 2));
const signedPP = (v, d = 1) => signed(v, x => `${(x * 100).toFixed(d)}pp`, 0.5 * 10 ** -(d + 2));  // difference of two rates
function panel(title, sub, ctl, ...body) {
  return h('section', { class: 'panel' }, h('h2', {}, title, sub ? h('span', { class: 'sub' }, sub) : null, ctl ? h('span', { class: 'ctl' }, ctl) : null), ...body);
}
function stat(label, value, sub) { return h('div', { class: 'stat' }, h('div', { class: 'l' }, label), h('div', { class: 'v' }, value), sub ? h('div', { class: 's' }, sub) : null); }
function seg(options, current, onPick) {
  return options.map(o => h('button', { 'aria-pressed': String(o === current), onclick: () => onPick(o) }, o));
}
function msg(t) { $('#msg').textContent = tr(t); }

// Sortable table. cols: [{k, label, l, fmt(row) -> node|string, sort(row)}]
function table(cols, rows, { sortKey, desc = true, onRow, max } = {}) {
  let key = sortKey, dir = desc ? -1 : 1;
  const wrap = h('div', { class: 'tw scroll' });
  function draw() {
    const col = cols.find(c => c.k === key);
    const sorted = col ? [...rows].sort((a, b) => {
      const va = col.sort ? col.sort(a) : a[col.k], vb = col.sort ? col.sort(b) : b[col.k];
      if (va == null) return 1; if (vb == null) return -1;
      return (va > vb ? 1 : va < vb ? -1 : 0) * dir;
    }) : rows;
    const thead = h('thead', {}, h('tr', {}, cols.map(c => h('th', {
      class: [c.l ? 'l' : '', c.sm === false ? 'sm-hide' : ''].join(' ').trim() || null, 'aria-sort': c.k === key ? (dir < 0 ? 'descending' : 'ascending') : null, scope: 'col',
      tabindex: 0,
      onclick: () => { if (key === c.k) dir = -dir; else { key = c.k; dir = -1; } draw(); },
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } },
    }, c.label))));
    const tbody = h('tbody', {}, (max ? sorted.slice(0, max) : sorted).map(r => h('tr', {
      class: onRow ? 'click' : null, tabindex: onRow ? 0 : null, onclick: onRow ? () => onRow(r) : null,
      onkeydown: onRow ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRow(r); } } : null,
    },
      cols.map(c => h('td', { class: [c.l ? 'l' : '', c.sm === false ? 'sm-hide' : ''].join(' ').trim() || null }, c.fmt ? c.fmt(r) : (r[c.k] ?? '—'))))));
    wrap.replaceChildren(h('table', {}, thead, tbody));
  }
  draw();
  return wrap;
}

// ---------- line chart with crosshair ----------
function lineChart({ dates, series, yfmt, height = 300, markers = [], zeroLine = false, onPick = null, pickLabel = '', xfmt = null }) {
  const root = h('div', { class: 'chart' });
  const legend = h('div', { class: 'legend' }, series.map(sr => h('span', {}, h('i', { style: `background:${sr.color}` }), sr.name)));
  const tip = h('div', { class: 'tip', role: 'status' });
  const host = h('div', {});
  root.append(host, tip);
  const wrap = h('div', {}, series.length > 1 ? legend : null, root);

  function draw() {
    const W = Math.max(280, host.clientWidth || 800), H = Math.min(height, Math.max(210, Math.round(window.innerWidth * 0.62)));
    const m = { l: 62, r: series.length <= 4 ? (W < 500 ? 70 : 96) : 12, t: 10, b: 22 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b, n = dates.length;
    const all = series.flatMap(sr => sr.values.filter(v => v != null));
    for (const mk of markers) all.push(mk.y);
    let lo = Math.min(...all), hi = Math.max(...all);
    if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
    const step = niceStep((hi - lo) / 5), t0 = Math.ceil(lo / step) * step;
    const X = i => m.l + (n <= 1 ? 0 : i / (n - 1) * iw), Y = v => m.t + (1 - (v - lo) / (hi - lo)) * ih;
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, height: H, role: 'img', 'aria-label': series.map(x => tr(x.name)).join(', ') });
    const g = s('g', { class: 'grid' });
    for (let v = t0; v <= hi; v += step) {
      g.append(s('line', { x1: m.l, x2: m.l + iw, y1: Y(v), y2: Y(v) }));
      const t = s('text', { x: m.l - 6, y: Y(v) + 3, 'text-anchor': 'end' }); t.textContent = yfmt(v); svg.append(t);
    }
    svg.prepend(g);
    svg.append(s('line', { class: 'base', x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih }));
    if (zeroLine && lo < 0 && hi > 0) svg.append(s('line', { x1: m.l, x2: m.l + iw, y1: Y(0), y2: Y(0), stroke: 'var(--ink2)', 'stroke-width': 1 }));
    const ticks = Math.max(2, Math.min(7, n, Math.floor(iw / 90)));
    for (let k = 0; k < ticks; k++) {
      const i = Math.round(k * (n - 1) / Math.max(1, ticks - 1));
      const t = s('text', { x: X(i), y: H - 6, 'text-anchor': k === 0 ? 'start' : k === ticks - 1 ? 'end' : 'middle' });
      t.textContent = xfmt ? xfmt(dates[i]) : fmtDate(dates[i], n > 90); svg.append(t);
    }
    for (const sr of series) {
      let d = '', pen = false;
      sr.values.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; pen = true; });
      svg.append(s('path', { d, fill: 'none', stroke: sr.color, 'stroke-width': sr.width || 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    }
    // trade markers: ▲ buy below the price, ▼ sell above (shape carries the side)
    for (const mk of markers) {
      const i = mk.i, x = X(i), y = Y(mk.y), up = mk.side === 'BUY';
      const p = up ? `M${x},${y + 3} l5,9 h-10 z` : `M${x},${y - 3} l5,-9 h-10 z`;
      svg.append(s('path', { d: p, fill: up ? 'var(--up)' : 'var(--down)', stroke: 'var(--panel)', 'stroke-width': 2, 'paint-order': 'stroke' }));
    }
    // direct end labels, de-collided
    if (series.length <= 4) {
      const ends = series.map(sr => { let i = sr.values.length - 1; while (i > 0 && sr.values[i] == null) i--; return { sr, y: Y(sr.values[i]), v: sr.values[i] }; })
        .sort((a, b) => a.y - b.y);
      for (let k = 1; k < ends.length; k++) if (ends[k].y - ends[k - 1].y < 13) ends[k].y = ends[k - 1].y + 13;
      for (const e of ends) {
        svg.append(s('line', { x1: m.l + iw + 6, x2: m.l + iw + 14, y1: e.y, y2: e.y, stroke: e.sr.color, 'stroke-width': 2 }));
        const t = s('text', { x: m.l + iw + 18, y: e.y + 3 }); t.textContent = tr(e.sr.short || e.sr.name); t.style.fill = 'var(--ink2)'; svg.append(t);
      }
    }
    const cross = s('line', { class: 'cross', y1: m.t, y2: m.t + ih, visibility: 'hidden' });
    const dots = series.map(sr => { const c = s('circle', { r: 4, fill: sr.color, stroke: 'var(--panel)', 'stroke-width': 2, visibility: 'hidden' }); svg.append(c); return c; });
    svg.append(cross);
    const hit = s('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent', tabindex: 0, style: onPick ? 'cursor:crosshair' : '' });
    if (onPick) { hit.addEventListener('click', () => onPick(cur)); hit.addEventListener('keydown', e => { if (e.key === 'Enter') onPick(cur); }); }
    svg.append(hit);
    let cur = n - 1;
    function show(i) {
      cur = Math.max(0, Math.min(n - 1, i));
      const x = X(cur);
      cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.setAttribute('visibility', 'visible');
      series.forEach((sr, k) => { const v = sr.values[cur]; if (v == null) return dots[k].setAttribute('visibility', 'hidden'); dots[k].setAttribute('cx', x); dots[k].setAttribute('cy', Y(v)); dots[k].setAttribute('visibility', 'visible'); });
      tip.replaceChildren(...[h('div', { class: 'd' }, xfmt ? xfmt(dates[cur], true) : dates[cur]),
        ...series.map(sr => h('div', { class: 'r' }, h('i', { style: `background:${sr.color}` }), h('span', {}, sr.name),
          h('b', {}, sr.values[cur] == null ? '—' : yfmt(sr.values[cur], true),
            sr.alt && sr.alt[cur] != null ? h('span', { class: 'mut' }, `  ${sr.altFmt(sr.alt[cur])}`) : null))),
        onPick && pickLabel ? h('div', { class: 'r' }, h('span', { class: 'amb' }, pickLabel)) : null,
        ...markers.filter(mk => mk.i === cur).map(mk => h('div', { class: 'r' }, h('span', { class: mk.side === 'BUY' ? 'up' : 'down' }, `${mk.side === 'BUY' ? '▲' : '▼'} ${mk.label}`)))].filter(Boolean));
      tip.style.display = 'block';
      const tw = tip.offsetWidth, scale = host.clientWidth / W;
      let left = x * scale + 14; if (left + tw > host.clientWidth) left = x * scale - tw - 14;
      tip.style.left = Math.max(0, left) + 'px'; tip.style.top = (m.t + 4) + 'px';
    }
    function hide() { cross.setAttribute('visibility', 'hidden'); dots.forEach(d => d.setAttribute('visibility', 'hidden')); tip.style.display = 'none'; }
    hit.addEventListener('pointermove', e => { const r = svg.getBoundingClientRect(); const x = (e.clientX - r.left) * W / r.width; show(Math.round((x - m.l) / iw * (n - 1))); });
    hit.addEventListener('pointerleave', hide);
    hit.addEventListener('focus', () => show(cur));
    hit.addEventListener('blur', hide);
    hit.addEventListener('keydown', e => { if (e.key === 'ArrowLeft') { show(cur - 1); e.preventDefault(); } if (e.key === 'ArrowRight') { show(cur + 1); e.preventDefault(); } });
    host.replaceChildren(svg);
  }
  requestAnimationFrame(draw);
  resizeHooks.push(draw);
  return wrap;
}
// 1.0000× is neutral, so the glyph — not the colour, and not an absolute value — carries the direction.
const factorBadge = v => v == null ? h('span', { class: 'mut' }, '—')
  : h('span', { class: v > 1.00005 ? 'up' : v < 0.99995 ? 'down' : 'mut' },
    `${v > 1.00005 ? '▲' : v < 0.99995 ? '▼' : ''}${v.toFixed(4)}×`);

// Small multiples. Eight decision classes on one axis needed eight hues and still read as a tangle;
// one panel each needs no palette at all, because the heading carries the identity.
function factorFacets({ dates, facets }) {
  const VW = 320, VH = 96, m = { l: 4, r: 4, t: 8, b: 8 };
  const iw = VW - m.l - m.r, ih = VH - m.t - m.b, n = dates.length;
  const pool = facets.flatMap(f => f.values.filter(v => v != null));
  let lo = Math.min(1, ...pool), hi = Math.max(1, ...pool);
  if (!pool.length) { lo = 0.98; hi = 1.02; }
  const pad = (hi - lo) * 0.16 || 0.01; lo -= pad; hi += pad;
  const X = i => m.l + (n <= 1 ? 0 : i / (n - 1) * iw);
  const Y = v => m.t + (1 - (v - lo) / (hi - lo)) * ih;
  const tip = h('div', { class: 'tip', role: 'status' });
  const grid = h('div', { class: 'facets' });

  for (const f of facets) {
    const last = [...f.values].reverse().find(v => v != null);
    const seen = f.counts ? f.counts[f.values.length - 1] : null;
    // preserveAspectRatio:none lets the card stretch; non-scaling strokes keep the lines 2px wide.
    const svg = s('svg', { viewBox: `0 0 ${VW} ${VH}`, preserveAspectRatio: 'none', role: 'img',
      'aria-label': `${tr(f.name)}: ${last == null ? tr('no evidence yet') : last.toFixed(4)}` });
    svg.append(s('line', { class: 'facet-base', x1: m.l, x2: m.l + iw, y1: Y(1), y2: Y(1) }));
    let d = '', pen = false;
    f.values.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; pen = true; });
    svg.append(s('path', { class: 'facet-line', d, fill: 'none', stroke: f.color }));
    const cross = s('line', { class: 'facet-cross', x1: 0, x2: 0, y1: m.t, y2: m.t + ih, opacity: 0 });
    const dot = s('circle', { class: 'facet-dot', r: 3, fill: f.color, opacity: 0 });
    svg.append(cross, dot);

    const card = h('article', { class: 'facet' },
      h('header', {}, h('b', {}, f.name), h('span', { class: 'mut' }, seen == null ? '' : `n=${seen}`)),
      // signed() takes the absolute value before formatting, which would print 0.9956× as 1.0044×.
      h('div', { class: 'facet-v' }, factorBadge(last)),
      svg);
    const read = e => {
      const r = svg.getBoundingClientRect();
      const i = Math.max(0, Math.min(n - 1, Math.round((e.clientX - r.left) / r.width * (n - 1))));
      const v = f.values[i];
      cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('opacity', 1);
      if (v == null) { dot.setAttribute('opacity', 0); } else {
        dot.setAttribute('cx', X(i)); dot.setAttribute('cy', Y(v)); dot.setAttribute('opacity', 1);
      }
      tip.replaceChildren(h('b', {}, f.name), h('span', { class: 'd' }, dates[i]),
        h('span', {}, v == null ? tr('no matured score yet') : `${v.toFixed(4)}×`),
        f.counts ? h('span', { class: 'mut' }, `n=${f.counts[i]}`) : null);
      const box = grid.getBoundingClientRect();
      tip.style.display = 'block';
      tip.style.left = `${Math.max(0, Math.min(e.clientX - box.left + 12, grid.clientWidth - 170))}px`;
      tip.style.top = `${e.clientY - box.top + 12}px`;
    };
    svg.addEventListener('pointermove', read);
    svg.addEventListener('pointerleave', () => {
      tip.style.display = 'none'; cross.setAttribute('opacity', 0); dot.setAttribute('opacity', 0);
    });
    grid.append(card);
  }
  grid.append(tip);
  return grid;
}
function niceStep(raw) { const p = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1))), f = raw / p; return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p; }
const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
function fmtDate(d, long) {
  const [y, mo, da] = d.split('-');
  if (LANG === 'zh') return long ? `${y.slice(2)}年${+mo}月` : `${+mo}月${+da}日`;
  return long ? `${MON[+mo - 1]} ${y.slice(2)}` : `${+da} ${MON[+mo - 1]}`;
}
let resizeHooks = [];
let rt; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => resizeHooks.forEach(f => f()), 120); });

// diverging bar list: identity via label, sign via ▲▼ text
function barList(items, fmt = money, eps = 0.005) {
  const max = Math.max(...items.map(i => Math.abs(i.value))) || 1;
  const hasNeg = items.some(i => i.value < 0), hasPos = items.some(i => i.value > 0);
  const zero = hasNeg && hasPos ? 50 : hasNeg ? 100 : 0;
  const span = hasNeg && hasPos ? 50 : 100;
  return h('div', { class: 'bars body' }, items.map(it => {
    const w = Math.abs(it.value) / max * span;
    const bar = h('div', { class: 'bar ' + (it.value >= 0 ? 'pos' : 'neg'), style: it.value >= 0 ? `left:${zero}%;width:${w}%` : `left:${zero - w}%;width:${w}%` });
    return h('div', { class: 'br', title: it.title || '', role: it.onclick ? 'button' : null, tabindex: it.onclick ? 0 : null,
      onclick: it.onclick || null, onkeydown: it.onclick ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); it.onclick(); } } : null,
      style: it.onclick ? 'cursor:pointer' : '' },
      h('span', { class: 'lab' }, it.label), h('div', { class: 'track' }, h('div', { class: 'zero', style: `left:${zero}%` }), bar), h('span', { class: 'val' }, signed(it.value, fmt, eps)));
  }));
}

// ---------- range slicing ----------
// Time-weighted return over a slice: strip each day's deposits so contributions don't count as performance.
function twrOf(values, contribs) {
  let idx = 1;
  for (let i = 1; i < values.length; i++) {
    const flow = contribs[i] - contribs[i - 1];
    if (values[i - 1] > 50) idx *= (values[i] - flow) / values[i - 1];
  }
  return idx - 1;
}
function rangeStart(dates, range) {
  if (range === 'ALL') return 0;
  const end = new Date(dates[dates.length - 1]);
  const from = new Date(end);
  if (range === 'YTD') { from.setMonth(0, 1); }
  else { const mo = { '1M': 1, '3M': 3, '6M': 6, '1Y': 12 }[range]; from.setMonth(from.getMonth() - mo); }
  const iso = from.toISOString().slice(0, 10);
  const i = dates.findIndex(d => d >= iso);
  return i < 0 ? 0 : i;
}

let auditReplayTimer = null;
async function ensureAuditDecisions() {
  if (!D || !D.audit || D.audit.decisions || state.auditLoading) return;
  state.auditLoading = true;
  try {
    const r = await fetch('/audit_decisions.json', { cache: 'no-store' });
    D.audit.decisions = r.ok ? await r.json() : [];
  } catch { D.audit.decisions = []; }
  state.auditLoading = false;
  render();
}
function setAuditDay(i, keepPlaying = false, refocus = false) {
  const dates = D && D.audit && D.audit.indices.dates;
  if (!dates || !dates.length) return;
  state.auditDay = Math.max(0, Math.min(dates.length - 1, +i));
  state.auditRefocus = refocus;
  if (!keepPlaying) { state.auditPlaying = false; clearTimeout(auditReplayTimer); }
  render();
}
function auditSliderKey(e) {
  const vimBack = vimMode && e.key === 'h', vimForward = vimMode && e.key === 'l';
  const back = e.key === 'ArrowLeft' || e.key === 'ArrowDown' || vimBack;
  const forward = e.key === 'ArrowRight' || e.key === 'ArrowUp' || vimForward;
  if (e.key === 'Home') { e.preventDefault(); e.stopPropagation(); return setAuditDay(0, false, true); }
  if (e.key === 'End') { e.preventDefault(); e.stopPropagation(); return setAuditDay(D.audit.indices.dates.length - 1, false, true); }
  if (!back && !forward) return;
  e.preventDefault();
  e.stopPropagation();
  setAuditDay(state.auditDay + (back ? -1 : 1) * (e.shiftKey ? 5 : 1), false, true);
}
function runAuditReplay() {
  clearTimeout(auditReplayTimer);
  if (!state.auditPlaying || state.screen !== 'AUD' || !D.audit.indices.dates.length) return;
  auditReplayTimer = setTimeout(() => {
    const last = D.audit.indices.dates.length - 1;
    if (state.auditDay >= last) { state.auditPlaying = false; render(); return; }
    state.auditDay += 1;
    render();
    runAuditReplay();
  }, state.auditSpeed);
}
function toggleAuditReplay() {
  const last = D.audit.indices.dates.length - 1;
  if (!state.auditPlaying && state.auditDay >= last) state.auditDay = 0;
  state.auditPlaying = !state.auditPlaying;
  render();
  runAuditReplay();
}

// ---------- screens ----------
const SCREEN = {
  PORT() {
    const S = D.summary;
    const stats = h('div', { class: 'stats' },
      stat('TOTAL VALUE (CAD)', money(S.total), `USDCAD ${D.fx.toFixed(4)}`),
      stat('DAY CHANGE', signed(S.day), 'Yahoo last two closes'),
      stat('NET DEPOSITED', money(S.contrib), 'all accounts, all time'),
      stat('TOTAL GAIN', signed(S.gain), signedPct(S.gain / S.contrib)),
      stat('REALIZED', signed(S.realized), 'avg-cost, all time'),
      stat('UNREALIZED', signed(S.unreal), 'open positions'),
    );
    const accts = table([
      { k: 'acct', label: 'ACCOUNT', l: true },
      { k: 'value', label: 'VALUE', fmt: r => money(r.value) },
      { k: 'weight', sm: false, label: 'WEIGHT', fmt: r => pct(r.weight) },
      { k: 'contrib', sm: false, label: 'DEPOSITED', fmt: r => money(r.contrib) },
      { k: 'gain', label: 'GAIN', fmt: r => signed(r.gain) },
      { k: 'ret', label: 'GAIN %', sort: r => r.gain / r.contrib, fmt: r => signedPct(r.gain / r.contrib) },
    ], D.accounts, { sortKey: 'value', onRow: r => { state.acct = r.acct; go('PERF'); } });
    const hold = table([
      { k: 'sym', label: 'SYMBOL', l: true, fmt: r => h('span', {}, h('span', { class: 'amb', raw: true }, r.sym), ' ', h('span', { class: 'tag' }, r.cur)) },
      { k: 'acct', sm: false, label: 'ACCOUNT', l: true },
      { k: 'cat', sm: false, label: 'BUCKET', l: true, fmt: r => h('span', { class: 'mut' }, r.cat.toUpperCase()) },
      { k: 'qty', sm: false, label: 'QTY', fmt: r => r.qty == null ? '—' : +r.qty.toFixed(6) },
      { k: 'avg', sm: false, label: 'AVG COST', fmt: r => num(r.avg) },
      { k: 'px', sm: false, label: 'LAST', fmt: r => r.px == null ? '—' : (r.px < 1 ? r.px.toPrecision(3) : num(r.px)) },
      { k: 'day_pct', label: 'DAY', fmt: r => signedPct(r.day_pct, 2) },
      { k: 'mv_cad', label: 'VALUE CAD', fmt: r => money(r.mv_cad) },
      { k: 'weight', sm: false, label: 'WT', fmt: r => pct(r.weight) },
      { k: 'upl', sm: false, label: 'UNREAL', fmt: r => r.upl ? signed(r.upl) : '—' },
      { k: 'upl_pct', label: 'UNREAL %', fmt: r => signedPct(r.upl_pct) },
    ], D.holdings, { sortKey: 'mv_cad', onRow: r => r.qty != null && openSymbol(r.sym, r.cur) });
    return [stats, h('div', { class: 'row', style: 'grid-template-columns:1fr' }, panel('ACCOUNTS', 'click a row for its history', null, accts)),
      panel('HOLDINGS', `${D.holdings.length} lines · from your activity ledger · click a row to open the symbol`, null, hold),
      reconcilePanel()];
  },

  PERF() {
    const sr = D.series, i0 = rangeStart(sr.dates, state.range);
    // ALL MONEY: every deposit, cash included. INVESTED: cash and cash ETFs excluded on both sides, so the
    // benchmark only gets money when you actually bought a risk asset.
    const invested = state.basis === 'INVESTED' && sr.invested;
    const P = invested ? { total: sr.invested.value, contrib: sr.invested.capital, twr: sr.invested.twr, bench: sr.invested.bench }
                       : { total: sr.total, contrib: sr.contrib, twr: sr.twr, bench: sr.bench };
    const dates = sr.dates.slice(i0);
    const acct = state.acct;
    let series, yfmt, statsEl;
    if (acct !== 'ALL') {
      const v = sr.accounts[acct].slice(i0);
      const c = (sr.account_contrib && sr.account_contrib[acct] ? sr.account_contrib[acct] : sr.contrib).slice(i0);
      const added = c[c.length - 1] - c[0];                       // deposits and transfers in this range
      const change = v[v.length - 1] - v[0];                      // what the balance did
      series = [
        { name: acct.toUpperCase(), short: 'VALUE', color: 'var(--s1)', values: v },
        { name: 'NET DEPOSITED', short: 'DEPOSITED', color: 'var(--ref)', width: 1.5, values: c },
      ];
      yfmt = v => money(v);
      statsEl = h('div', { class: 'stats' },
        stat('VALUE', money(v[v.length - 1]), `${dates[0]} → ${dates[dates.length - 1]}`),
        stat('BALANCE CHANGE', signed(change), 'money added + investment gain'),
        stat('MONEY ADDED', signed(added), 'deposits and transfers in range'),
        stat('INVESTMENT GAIN', signed(change - added), 'balance change minus money added'),
        stat('RETURN', signedPct(twrOf(v, c)), 'time-weighted, money in and out removed'));
    } else if (state.mode === 'GAIN') {
      // Money made or lost inside the range: value change minus money put in, so 0 = break even.
      const dep = P.contrib.slice(i0), base = dep[0];
      const gainOf = arr => { const a = arr.slice(i0), v0 = a[0]; return a.map((v, k) => (v - v0) - (dep[k] - base)); };
      const rebaseTwr = arr => { const a = arr.slice(i0), b = a[0]; return a.map(v => v / b - 1); };
      series = [
        { name: invested ? 'INVESTED GAIN' : 'YOUR GAIN', short: 'YOU', color: 'var(--s1)', values: gainOf(P.total),
          alt: rebaseTwr(P.twr), altFmt: v => pct(v, 2) },
        ...Object.entries(P.bench).map(([b, x]) => ({ name: `${b.replace('.TO', '')} WITH THE SAME MONEY`, short: b.replace('.TO', ''),
          color: BENCH_COLOR[b], values: gainOf(x.value), alt: rebaseTwr(x.twr), altFmt: v => pct(v, 2) })),
      ];
      yfmt = (v, full) => full ? money(v) : Math.abs(v) >= 1000 ? (v < 0 ? '-$' : '$') + nf0.format(Math.round(Math.abs(v) / 1000)) + 'K' : money(v);
    } else if (state.mode === 'VALUE') {
      series = [
        { name: invested ? 'INVESTED (NO CASH)' : 'PORTFOLIO', short: 'YOU', color: 'var(--s1)', values: P.total.slice(i0) },
        ...Object.entries(P.bench).map(([b, x]) => ({ name: invested ? `SAME MONEY IN ${b.replace('.TO', '')}` : `ALL DEPOSITS IN ${b.replace('.TO', '')}`, short: b.replace('.TO', ''), color: BENCH_COLOR[b], values: x.value.slice(i0) })),
        { name: invested ? 'CAPITAL DEPLOYED' : 'NET DEPOSITED', short: invested ? 'CAPITAL' : 'DEPOSITED', color: 'var(--ref)', width: 1.5, values: P.contrib.slice(i0) },
      ];
      yfmt = v => v >= 1000 ? '$' + nf0.format(Math.round(v / 1000)) + 'K' : money(v);
      yfmt = ((f) => (v, full) => full ? money(v) : f(v))(yfmt);
    } else {
      const rebase = arr => { const a = arr.slice(i0), b = a[0]; return a.map(v => v / b - 1); };
      const dep2 = P.contrib.slice(i0), base2 = dep2[0];
      const gainOf2 = arr => { const a = arr.slice(i0), v0 = a[0]; return a.map((v, k) => (v - v0) - (dep2[k] - base2)); };
      series = [
        { name: invested ? 'INVESTED MONEY (TIME-WEIGHTED)' : 'PORTFOLIO (TIME-WEIGHTED)', short: 'YOU', color: 'var(--s1)',
          values: rebase(P.twr), alt: gainOf2(P.total), altFmt: v => money(v, 2) },
        ...Object.entries(P.bench).map(([b, x]) => ({ name: `${b.replace('.TO', '')} TOTAL RETURN (CAD)`, short: b.replace('.TO', ''),
          color: BENCH_COLOR[b], values: rebase(x.twr), alt: gainOf2(x.value), altFmt: v => money(v, 2) })),
      ];
      yfmt = (v, full) => (v * 100).toFixed(full ? 2 : 0) + '%';
    }
    if (acct === 'ALL') {
      const last = a => a[a.length - 1];
      const you = series[0].values;
      // Every figure is shown both ways: the rate, and the money it is worth over this range.
      const slice = arr => arr.slice(i0);
      const val = slice(P.total), dep = slice(P.contrib);
      const added = last(dep) - dep[0];
      const gainYou = last(val) - val[0] - added;
      const retYou = last(slice(P.twr)) / slice(P.twr)[0] - 1;
      const marks = Object.entries(P.bench).map(([b, x]) => {
        const bv = slice(x.value), bt = slice(x.twr);
        return { short: b.replace('.TO', ''), gain: last(bv) - bv[0] - added, ret: last(bt) / bt[0] - 1 };
      });
      if (state.mode !== 'RETURN') {
        statsEl = h('div', { class: 'stats' },
          stat(invested ? 'CAPITAL DEPLOYED' : 'MONEY ADDED', signed(added), invested ? 'net buys of risk assets in range' : 'deposits minus withdrawals in range'),
          stat('BALANCE CHANGE', signed(last(val) - val[0]), invested ? 'invested value change' : 'portfolio value change'),
          stat('INVESTMENT GAIN', signed(gainYou), h('span', {}, 'rate: ', signedPct(retYou))),
          ...marks.map(m => stat(`${m.short} INSTEAD`, signed(m.gain), h('span', {}, 'you vs it: ', signed(gainYou - m.gain), ' · ', signedPP(retYou - m.ret)))));
      } else {
        statsEl = h('div', { class: 'stats' },
          stat('YOUR RETURN', signedPct(retYou), h('span', {}, 'worth ', signed(gainYou), ' in range')),
          ...marks.map(m => stat(m.short, signedPct(m.ret), h('span', {}, 'you vs it: ', signedPP(retYou - m.ret), ' · ', signed(gainYou - m.gain)))));
      }
    }
    const ctl = [
      h('select', { 'aria-label': 'Account', onchange: e => { state.acct = e.target.value; render(); } },
        ['ALL', ...D.accounts.map(a => a.acct)].map(a => h('option', { value: a, selected: a === acct }, a.toUpperCase()))),
      h('span', { style: 'width:10px' }),
      ...(acct === 'ALL' ? seg(['VALUE', 'GAIN', 'RETURN'], state.mode, m => { state.mode = m; render(); }) : []),
      h('span', { style: 'width:10px' }),
      ...(acct === 'ALL' && sr.invested ? seg(['INVESTED', 'ALL MONEY'], state.basis, b => { state.basis = b; render(); }) : []),
      h('span', { style: 'width:10px' }),
      ...seg(['1M', '3M', '6M', 'YTD', '1Y', 'ALL'], state.range, r => { state.range = r; render(); }),
    ];
    const notes = [];
    if (acct !== 'ALL') notes.push('Account value in CAD, including cash.');
    else {
      if (state.mode === 'GAIN') notes.push('Money made or lost since the range start, deposits removed: 0 is break even. Hover shows the time-weighted rate beside each amount.');
      else if (state.mode === 'RETURN') notes.push('Time-weighted returns rebased to 0% at the range start; hover shows what each rate is worth in CAD.');
      else notes.push('Benchmark lines replay every deposit and withdrawal into that ETF on the same day (dividends reinvested).');
      notes.push(invested
        ? 'Cash and cash ETFs (CCAD, TCSH, CBIL) are excluded from both sides: the benchmark receives money only when you bought a risk asset, and dividends leave the sleeve as they do in reality.'
        : 'ALL MONEY includes what you parked in cash ETFs, which is why a benchmark can lead. Switch to INVESTED for a like-for-like comparison.');
    }
    const note = notes.join(' ');
    return [panel('PERFORMANCE', `${dates[0]} → ${dates[dates.length - 1]}`, ctl, statsEl,
      h('div', { class: 'body' }, lineChart({ dates, series, yfmt, height: 340, zeroLine: state.mode !== 'VALUE' })),
      h('div', { class: 'body mut' }, note))];
  },

  PNL() {
    const pos = D.positions.filter(p => Math.abs(p.realized_cad) >= 0.5);
    const worst = pos.slice(0, 12), best = pos.slice(-12).reverse();
    const item = p => ({ label: `${p.sym.trim()} ${p.acct === 'Non-registered' ? 'NREG' : p.acct.toUpperCase()}`, value: p.realized_cad, title: `${p.buys} buys · ${p.sells} sells · ${p.first} → ${p.last}`, onclick: () => openSymbol(p.sym, p.cur) });
    const S = D.summary;
    return [
      h('div', { class: 'stats' },
        stat('REALIZED (CAD)', signed(S.realized), 'avg-cost, all time'),
        ...D.by_year.map(y => stat(`REALIZED ${y.year}`, signed(y.realized_cad)))),
      h('div', { class: 'row' },
        panel('BEST 12', 'realized, CAD', null, barList(best.map(item))),
        panel('WORST 12', 'realized, CAD', null, barList(worst.map(item)))),
      h('div', { class: 'row' },
        panel('BY BUCKET', null, null, table([
          { k: 'cat', label: 'BUCKET', l: true, fmt: r => r.cat.toUpperCase() },
          { k: 'realized_cad', label: 'REALIZED', fmt: r => signed(r.realized_cad) },
          { k: 'sells', label: 'SELLS' },
          { k: 'win', label: 'WIN %', fmt: r => pct(r.win, 0) },
        ], D.by_cat, { sortKey: 'realized_cad' })),
        panel('BY HOLDING TIME', 'days since position opened', null, table([
          { k: 'bucket', label: 'HELD', l: true },
          { k: 'n', label: 'SELLS' },
          { k: 'sum_cad', label: 'REALIZED', fmt: r => signed(r.sum_cad) },
          { k: 'avg', label: 'AVG / SELL', sort: r => r.sum_cad / r.n, fmt: r => signed(r.sum_cad / r.n, x => money(x, 2)) },
          { k: 'win', label: 'WIN %', fmt: r => pct(r.win, 0) },
        ], D.hold_buckets, {}))),
      panel('ALL POSITIONS', `${pos.length} with realized P&L`, null, table([
        { k: 'sym', label: 'SYMBOL', l: true, fmt: r => h('span', { class: 'amb', raw: true }, r.sym) },
        { k: 'acct', sm: false, label: 'ACCOUNT', l: true },
        { k: 'cat', sm: false, label: 'BUCKET', l: true, fmt: r => h('span', { class: 'mut' }, r.cat.toUpperCase()) },
        { k: 'buys', sm: false, label: 'BUYS' }, { k: 'sells', sm: false, label: 'SELLS' },
        { k: 'realized', label: 'REALIZED', fmt: r => h('span', {}, signed(r.realized, x => money(x, 2)), ' ', h('span', { class: 'tag' }, r.cur)) },
        { k: 'realized_cad', label: 'CAD', fmt: r => signed(r.realized_cad) },
        { k: 'first', sm: false, label: 'FIRST' }, { k: 'last', sm: false, label: 'LAST' },
        { k: 'open', label: 'OPEN', fmt: r => r.open ? 'Y' : '' },
      ], pos, { sortKey: 'realized_cad', onRow: r => openSymbol(r.sym, r.cur) })),
    ];
  },

  TRD() {
    let rows = D.trades;
    if (state.tradeAcct !== 'ALL') rows = rows.filter(t => t.acct === state.tradeAcct);
    if (state.tradeSym) rows = rows.filter(t => t.sym.trim().startsWith(state.tradeSym));
    const sells = rows.filter(t => t.side === 'SELL' && t.edge != null);
    const buys = rows.filter(t => t.side === 'BUY' && t.edge != null);
    const sum = a => a.reduce((x, t) => x + (t.edge_cad ?? 0), 0);  // native amounts differ in currency; totals use CAD
    const ad = rows.filter(t => t.avgdown).length;
    const ctl = [
      h('select', { 'aria-label': 'Account', onchange: e => { state.tradeAcct = e.target.value; render(); } },
        ['ALL', ...D.accounts.map(a => a.acct)].map(a => h('option', { value: a, selected: a === state.tradeAcct }, a.toUpperCase()))),
      h('input', { 'aria-label': 'Symbol filter', placeholder: 'SYMBOL', value: state.tradeSym, style: 'background:var(--hl);border:0;color:var(--ink);font:inherit;width:90px;padding:0 4px;text-transform:uppercase;margin-left:6px',
        onchange: e => { state.tradeSym = e.target.value.toUpperCase().trim(); render(); } }),
    ];
    return [
      h('div', { class: 'stats' },
        stat('TRADES', nf0.format(rows.length), `${buys.length} buys · ${sells.length} sells (priced)`),
        stat('SELLS VS HOLDING (CAD)', signed(sum(sells)), 'positive = you sold above today’s price'),
        stat('BUYS SINCE (CAD)', signed(sum(buys)), 'gain from buy price to today'),
        stat('AVERAGING-DOWN BUYS', nf0.format(ad), 'stock/spec buys >2% below avg cost')),
      panel('TRADE BLOTTER', 'native currency · hindsight uses latest close, split-adjusted', ctl, table([
        { k: 'date', label: 'DATE', l: true },
        { k: 'acct', sm: false, label: 'ACCOUNT', l: true },
        { k: 'side', label: 'SIDE', l: true, fmt: r => h('span', { class: r.side === 'BUY' ? 'up' : 'down' }, r.side === 'BUY' ? '▲' : '▼', h('span', { class: 'sm-hide' }, ' ' + r.side)) },
        { k: 'sym', label: 'SYMBOL', l: true, fmt: r => h('span', {}, h('span', { class: 'amb', raw: true }, r.sym), ' ', h('span', { class: 'tag' }, r.cur)) },
        { k: 'qty', sm: false, label: 'QTY', fmt: r => +r.qty.toFixed(6) },
        { k: 'px', sm: false, label: 'PRICE', fmt: r => r.px < 1 ? r.px.toPrecision(3) : num(r.px) },
        { k: 'amt', sm: false, label: 'AMOUNT', fmt: r => num(r.amt) },
        { k: 'now', sm: false, label: 'NOW', fmt: r => r.now == null ? '—' : r.now < 1 ? r.now.toPrecision(3) : num(r.now) },
        { k: 'edge', label: 'HINDSIGHT', fmt: r => signed(r.edge, x => money(x, 2)) },
        { k: 'avgdown', label: 'FLAG', fmt: r => r.avgdown ? h('span', { class: 'amb' }, 'AVG↓') : '' },
      ], rows, { sortKey: 'date', max: 1500, onRow: r => openSymbol(r.sym, r.cur) })),
    ];
  },

  ALOC() {
    const A = D.alloc, inv = A.invested, now = A.now;
    const total = Object.values(now).reduce((a, b) => a + b, 0);
    const rows = Object.entries(A.targets).map(([k, t]) => {
      const share = (now[k] || 0) / inv, diff = share - t;
      return h('div', { class: 'ar' }, h('span', { class: 'amb' }, k.toUpperCase()),
        h('div', { class: 'track', title: `now ${pct(share)} · target ${pct(t, 0)}` }, h('div', { class: 'fill', style: `width:${Math.min(100, share * 100)}%` }), h('div', { class: 'tgt', style: `left:${t * 100}%` })),
        h('span', {}, `${pct(share)} `, h('span', { class: 'mut' }, `/ ${pct(t, 0)} `), signed(diff * inv)));
    });
    const byAcct = {};
    for (const x of D.holdings) { byAcct[x.acct] ??= {}; byAcct[x.acct][x.cat] = (byAcct[x.acct][x.cat] || 0) + x.mv_cad; }
    const cats = ['cash', 'core', 'stocks', 'speculative'];
    return [
      h('div', { class: 'stats' },
        stat('CASH & CASH ETFS', money(now.cash), `${pct(now.cash / total)} of total`),
        stat('INVESTED', money(inv), `${pct(inv / total)} of total`),
        ...Object.keys(A.targets).map(k => stat(k.toUpperCase(), pct((now[k] || 0) / inv), `target ${pct(A.targets[k], 0)} of invested`))),
      panel('INVESTED MIX VS TARGET', 'bar = now · white tick = target · $ = amount over (+) or under (−) target', null, h('div', { class: 'body alloc' }, rows)),
      contributionsPanel(),
      panel('BY ACCOUNT', 'CAD', null, table([
        { k: 'acct', label: 'ACCOUNT', l: true },
        ...cats.map(c => ({ k: c, label: c.toUpperCase(), fmt: r => r[c] ? money(r[c]) : h('span', { class: 'mut' }, '—') })),
        { k: 'tot', label: 'TOTAL', fmt: r => money(r.tot) },
      ], Object.entries(byAcct).map(([acct, v]) => ({ acct, ...v, tot: Object.values(v).reduce((a, b) => a + b, 0) })), { sortKey: 'tot' })),
    ];
  },

  RULE() {
    const bad = D.rules.filter(r => !r.ok).length;
    return [
      h('div', { class: 'stats' }, stat('RULES', `${D.rules.length - bad}/${D.rules.length} PASS`, 'edit thresholds in pipeline/config.json')),
      panel('CHECKS', `as of ${D.price_date}`, null, h('div', {}, D.rules.map(r => h('div', { class: 'rule' },
        h('span', { class: 'st ' + (r.ok ? 'up' : 'down') }, r.ok ? '✓ PASS' : '✕ FAIL'),
        h('div', {}, h('div', {}, h('span', { class: 'nm' }, r.name), '  ', h('span', { class: 'mut' }, r.detail)),
          r.items.length ? h('ul', {}, r.items.map(i => h('li', {}, i))) : null))))),
    ];
  },

  EVT() {
    const today = D.price_date;
    const rows = D.events.map(e => ({ ...e, days: Math.round((new Date(e.date) - new Date(today)) / 864e5) }));
    return [panel('EVENTS', 'holdings only · ETF ex-dividend dates are projected from past payments', null, table([
      { k: 'date', label: 'DATE', l: true, fmt: r => h('span', { class: r.days < 0 ? 'mut' : '' }, r.date) },
      { k: 'days', label: 'IN', fmt: r => r.days < 0 ? h('span', { class: 'mut' }, `${-r.days}D AGO`) : r.days === 0 ? h('span', { class: 'amb' }, 'TODAY') : `${r.days}D` },
      { k: 'ticker', label: 'TICKER', l: true, fmt: r => h('span', { class: 'amb', raw: true }, r.ticker) },
      { k: 'event', label: 'EVENT', l: true, fmt: r => r.event.toUpperCase() },
    ], rows, { sortKey: 'date', desc: false }))];
  },

  INC() {
    const rows = D.income.map(r => ({ ...r, gross: (r.Dividend || 0) + (r.Interest || 0) + (r.BonusPayment || 0), cost: (r.Tax || 0) + (r.Fee || 0) }))
      .map(r => ({ ...r, net: r.gross + r.cost }));
    const sum = k => rows.reduce((a, r) => a + (r[k] || 0), 0);
    const last12 = rows.slice(-12);
    return [
      h('div', { class: 'stats' },
        stat('DIVIDENDS', money(sum('Dividend')), 'all time, CAD'),
        stat('INTEREST + BONUS', money(sum('Interest') + sum('BonusPayment'))),
        stat('WITHHOLDING TAX', signed(sum('Tax')), 'US non-resident tax'),
        stat('FEES', signed(sum('Fee')), 'subscription'),
        stat('NET, LAST 12 MO', signed(last12.reduce((a, r) => a + r.net, 0)))),
      h('div', { class: 'row' },
        panel('NET INCOME BY MONTH', 'income minus tax and fees, CAD', null, barList(rows.slice(-18).map(r => ({ label: r.month, value: r.net, title: `gross ${money(r.gross, 2)} · tax/fees ${money(r.cost, 2)}` })), x => money(x, 2))),
        panel('DETAIL', null, null, table([
          { k: 'month', label: 'MONTH', l: true },
          { k: 'Dividend', label: 'DIVIDEND', fmt: r => num(r.Dividend) },
          { k: 'Interest', label: 'INTEREST', fmt: r => num(r.Interest) },
          { k: 'Tax', label: 'TAX', fmt: r => num(r.Tax) },
          { k: 'Fee', label: 'FEE', fmt: r => num(r.Fee) },
          { k: 'net', label: 'NET', fmt: r => signed(r.net, x => money(x, 2)) },
        ], rows, { sortKey: 'month' }))),
    ];
  },

  AUD() {
    const A = D.audit;
    if (!A) return [h('div', { class: 'skeleton' }, 'REBUILD DATA TO GENERATE THE DECISION AUDIT')];
    ensureAuditDecisions();   // the per-decision rows are their own file; only this screen needs them
    const C = A.concentration, AD = A.averaging_down, RC = A.reconciliation, horizon = state.auditHorizon;
    const decisionName = s => ({
      ALL: 'ALL DECISIONS', OPEN: 'INITIAL ENTRY', ADD_TO_LOSER: 'ADD BELOW COST', ADD_TO_WINNER: 'ADD ABOVE COST',
      REDUCE_LOSER: 'PARTIAL EXIT BELOW COST', REDUCE_WINNER: 'PARTIAL EXIT ABOVE COST',
      CLOSE_LOSER: 'FULL EXIT BELOW COST', CLOSE_WINNER: 'FULL EXIT ABOVE COST',
    })[s] || s.replaceAll('_', ' ');
    const decisionMeaning = s => ({
      OPEN: 'The position moved from zero to positive. This starts a new campaign and measures the initial entry.',
      ADD_TO_LOSER: 'More shares were bought while the previous completed close was below the pre-trade average cost.',
      ADD_TO_WINNER: 'More shares were bought while the previous completed close was at or above the pre-trade average cost.',
      REDUCE_LOSER: 'Part of the position was sold below average cost, while some shares remained.',
      REDUCE_WINNER: 'Part of the position was sold at or above average cost, while some shares remained.',
      CLOSE_LOSER: 'The remaining position was sold below average cost, ending the campaign.',
      CLOSE_WINNER: 'The remaining position was sold at or above average cost, ending the campaign.',
    })[s] || '';
    const hypothesisName = s => ({
      add_to_loser: 'ADD BELOW COST', add_to_winner: 'ADD ABOVE COST', initial_entry: 'INITIAL ENTRY',
      partial_profit_taking: 'PARTIAL EXIT ABOVE COST', full_exit: 'FULL EXIT', short_horizon_exit: 'SHORT-HORIZON EXIT',
      concentration_top3: 'TOP-3 CONCENTRATION', concentration_top5: 'TOP-5 CONCENTRATION',
    })[s] || s.replaceAll('_', ' ');
    const band = (r, n) => r[`lo_${n}d`] == null ? '—' : `${(r[`lo_${n}d`] * 100).toFixed(2)}% → ${(r[`hi_${n}d`] * 100).toFixed(2)}%`;
    // Entry amber, exit blue, total ink: each facet is titled, so colour only separates the two sides.
    const classColor = cls => cls === 'ALL' ? 'var(--ink)' : cls.startsWith('ADD') || cls === 'OPEN' ? 'var(--s1)' : 'var(--s2)';
    const dates = A.indices.dates;
    if (state.auditDay == null || state.auditDay >= dates.length) state.auditDay = Math.max(0, dates.length - 1);
    const slide = state.auditDay, slideDate = dates[slide], horizonDays = parseInt(horizon, 10);
    const facets = Object.entries(A.indices.curves).map(([cls, byH]) => ({
      cls, name: decisionName(cls), color: classColor(cls),
      values: byH[horizon].slice(0, slide + 1), counts: A.indices.counts[cls][horizon].slice(0, slide + 1),
    }));
    const rows = A.decisions || [];
    const started = rows.filter(d => d.date === slideDate);
    const matured = rows.filter(d => d[`end_${horizon}`] === slideDate && d[`er_${horizon}`] != null);
    const pending = rows.filter(d => d.date <= slideDate && d[`end_${horizon}`] && d[`end_${horizon}`] > slideDate);
    const loadingRows = !A.decisions;
    const evidenceCols = [
      { k: 'cls', label: 'DECISION CLASS', l: true, fmt: r => decisionName(r.cls) },
      { k: 'decisions', label: 'N' }, { k: 'campaigns', label: 'CAMPAIGNS' },
      ...A.horizons.map(n => ({ k: `er_${n}d`, label: `${n}D AVG EXCESS`, fmt: r => h('span', {}, signedPct(r[`er_${n}d`], 2), h('span', { class: 'mut' }, ` · n=${r[`n_${n}d`]}`)) })),
      { k: 'band20', sm: false, label: '20D 10–90% BAND', sort: r => r.lo_20d, fmt: r => band(r, 20) },
      { k: 'band60', sm: false, label: '60D 10–90% BAND', sort: r => r.lo_60d, fmt: r => band(r, 60) },
    ];
    const removals = C.removals.map(r => ({ ...r, label: r.n ? `WITHOUT TOP ${r.n}` : 'ACTUAL PORTFOLIO' }));
    const ranked = C.ranked.slice(0, 30);
    const explain = [
      ['CAMPAIGN', 'One continuous position in one account: it starts when shares move from zero to positive and ends when they return to zero. Transactions inside it are related, not independent bets.'],
      ['ABOVE / BELOW COST', 'The previous completed daily close is compared with average cost immediately before the decision. This avoids using a close that occurred after the trade.'],
      ['EXCESS RETURN', `Security return in CAD minus ${A.benchmark.replace('.TO', '')} return over the same fixed horizon. Positive means the decision beat the benchmark.`],
      ['EXIT SCORE', 'For a sale the sign is reversed: benchmark return minus the sold security return. Positive means selling added relative value; negative means holding would have done better.'],
      ['AVERAGE RELATIVE FACTOR', 'Each matured score is one factor: security divided by benchmark for buys, benchmark divided by security for sells. The panels show the running average of those factors, never their product — a 60-day window overlaps its neighbours, so multiplying would count one market move dozens of times.'],
      ['10–90% BAND', 'Campaigns are resampled as blocks and every decision inside a drawn campaign is pooled, so the band brackets the same average the table prints. This is a concentration-sensitivity range, not a statistical confidence interval and not a probability of skill.'],
    ];
    return [
      h('div', { class: 'stats' },
        stat('PORTFOLIO TWR', signedPct(C.actual_return, 2), 'daily, cash flows removed'),
        stat(`${A.benchmark.replace('.TO', '')} RETURN`, signedPct(C.benchmark_return, 2), 'CAD total return over the same period'),
        stat('EXCESS VS BENCHMARK', signedPP(C.actual_excess, 2), 'portfolio TWR minus benchmark return'),
        stat('TOP 1 / POSITIVE P&L', pct(C.top_positive_share['1'], 0), 'campaign concentration'),
        stat('TOP 3 / POSITIVE P&L', pct(C.top_positive_share['3'], 0), `${C.ranked.length} campaigns`),
        stat('DAILY COVERAGE', pct(A.coverage.daily_pct, 1), `${A.coverage.daily_priced}/${A.coverage.decisions} equity decisions`)),
      panel('HOW TO READ THIS AUDIT', 'definitions used throughout this screen', null,
        h('div', { class: 'tw help' }, h('table', {}, h('tbody', {}, explain.map(([term, meaning]) => h('tr', {},
          h('td', { class: 'amb', style: 'vertical-align:top;white-space:nowrap' }, term),
          h('td', { style: 'white-space:normal' }, meaning))))))),
      panel('DAILY EVIDENCE REPLAY', `${horizonDays}-trading-day score · slide ${slide + 1} of ${dates.length} · no look-ahead`, [
        h('button', { onclick: () => setAuditDay(0), title: 'First day' }, '|◀'),
        h('button', { onclick: () => setAuditDay(slide - 1), title: 'Previous day' }, '◀'),
        h('button', { 'aria-pressed': String(state.auditPlaying), onclick: toggleAuditReplay }, state.auditPlaying ? 'Ⅱ PAUSE' : '▶ PLAY'),
        h('button', { onclick: () => setAuditDay(slide + 1), title: 'Next day' }, '▶'),
        h('button', { onclick: () => setAuditDay(dates.length - 1), title: 'Latest day' }, '▶|'),
        h('select', { 'aria-label': 'Score horizon', onchange: e => { state.auditHorizon = e.target.value; render(); } },
          A.horizons.map(n => h('option', { value: `${n}d`, selected: horizon === `${n}d` }, `${n}D`))),
        h('select', { 'aria-label': 'Replay speed', onchange: e => { state.auditSpeed = +e.target.value; if (state.auditPlaying) runAuditReplay(); } },
          [[1200, 'SLOW'], [650, 'NORMAL'], [250, 'FAST']].map(([v, name]) => h('option', { value: v, selected: state.auditSpeed === v }, name))),
      ],
        h('div', { class: 'audit-slide' },
          h('div', { class: 'audit-date' }, h('span', { class: 'mut' }, 'EVIDENCE AS OF'), h('b', {}, slideDate),
            h('span', { class: 'audit-counter' }, `${slide + 1} / ${dates.length}`)),
          h('input', { class: 'audit-scrub', type: 'range', min: 0, max: Math.max(0, dates.length - 1), value: slide,
            'aria-label': 'Replay day', title: 'Anywhere on AUD: arrows move one day, Shift+arrows move five, Vim H/L move one',
            onchange: e => setAuditDay(e.target.value), onkeydown: auditSliderKey }),
          h('div', { class: 'audit-keyhint' }, 'ANYWHERE ON AUD: ←/→ = 1 DAY · SHIFT+←/→ = 5 · VIM H/L = 1 · SLIDER ALSO: h/l, HOME/END'),
          h('div', { class: 'audit-tape' },
            h('span', { class: 'tag' }, 'TODAY'),
            matured.length ? h('span', {}, `${matured.length} SCORES MATURED`) : h('span', { class: 'mut' }, 'NO SCORE MATURED'),
            started.length ? h('span', {}, `${started.length} NEW DECISIONS`) : null,
            h('span', { class: 'mut' }, `${pending.length} PENDING`)),
          h('section', { class: 'audit-explain' },
            h('h3', {}, 'WHAT THIS DAY MEANS'),
            h('div', { class: 'audit-glossary' },
              h('div', {}, h('b', {}, 'DECISION MADE'), h('span', {}, 'A transaction was classified from the portfolio state immediately before it. Its future score is still unknown.')),
              h('div', {}, h('b', {}, 'EVIDENCE MATURED'), h('span', {}, 'The selected observation window has fully elapsed. Only now does its score enter the average.')),
              h('div', {}, h('b', {}, 'PENDING'), h('span', {}, 'The decision exists, but its selected horizon has not finished. Pending is not a gain, loss, or missing-data verdict.'))),
            h('div', { class: 'audit-stories scroll' },
              ...started.map(d => h('article', { class: 'audit-story' },
                h('div', { class: 'audit-story-head' }, h('span', { class: 'tag' }, 'DECISION MADE'),
                  h('b', { class: 'amb', raw: true }, d.sym), h('strong', {}, decisionName(d.class))),
                h('p', {}, decisionMeaning(d.class)),
                h('div', { class: 'audit-metrics' },
                  h('span', {}, h('small', {}, 'NOTIONAL'), h('b', {}, money(d.notional_cad))),
                  h('span', {}, h('small', {}, 'SCORE DATE'), h('b', {}, d[`end_${horizon}`] || 'NO COMPLETE WINDOW'))))),
              ...matured.map(d => h('article', { class: 'audit-story' },
                h('div', { class: 'audit-story-head' }, h('span', { class: 'tag' }, 'EVIDENCE MATURED'),
                  h('b', { class: 'amb', raw: true }, d.sym), h('strong', {}, decisionName(d.class))),
                h('p', {}, `The ${horizonDays}-trading-day window from ${d.date} is complete. This score is posted today, not on the decision date.`),
                h('div', { class: 'audit-metrics' },
                  h('span', {}, h('small', {}, 'SECURITY RETURN'), signedPct(d[`cad_${horizon}`], 2)),
                  h('span', {}, h('small', {}, 'BENCHMARK RETURN'), signedPct(d[`benchmark_${horizon}`], 2)),
                  h('span', {}, h('small', {}, 'EXCESS SCORE'), signedPct(d[`er_${horizon}`], 2)),
                  h('span', {}, h('small', {}, 'RELATIVE FACTOR'), h('b', {}, d[`factor_${horizon}`] == null ? '—' : `${d[`factor_${horizon}`].toFixed(4)}×`))),
                h('p', { class: 'mut' }, d.cls === 'EXIT'
                  ? 'For an exit, a positive score means the benchmark beat the sold security afterward, so selling added relative value. A negative score means holding would have done better.'
                  : 'For an entry, a positive score means the security beat the benchmark after the purchase. A negative score means the benchmark did better.'))),
              loadingRows ? h('article', { class: 'audit-story quiet' }, h('b', {}, 'LOADING DECISIONS'),
                h('p', {}, 'The per-decision rows are fetched separately so the other screens do not carry them.')) : null,
              !loadingRows && !started.length && !matured.length ? h('article', { class: 'audit-story quiet' },
                h('b', {}, 'NO NEW EVIDENCE TODAY'),
                h('p', {}, `No decision was made and no ${horizonDays}-trading-day score matured. The averages carry forward unchanged; ${pending.length} earlier decisions remain pending.`)) : null)),
          h('div', { class: 'row audit-events' },
            panel('DECISIONS MADE', `${started.length} on this trading day`, null,
              started.length ? table([
                { k: 'class', label: 'CLASS', l: true, fmt: r => decisionName(r.class) },
                { k: 'sym', label: 'SYMBOL', l: true, fmt: r => h('span', { class: 'amb', raw: true }, r.sym) },
                { k: 'notional_cad', label: 'NOTIONAL', fmt: r => money(r.notional_cad) },
                { k: 'matures', label: 'SCORE DATE', fmt: r => r[`end_${horizon}`] || 'PENDING' },
              ], started, { sortKey: 'class', desc: false }) : h('div', { class: 'body mut' }, loadingRows ? 'Loading decisions…' : 'No equity decision was made on this day.')),
            panel('EVIDENCE MATURED', `${matured.length} fixed-horizon scores posted today`, null,
              matured.length ? table([
                { k: 'date', label: 'DECISION DATE', l: true },
                { k: 'class', label: 'CLASS', l: true, fmt: r => decisionName(r.class) },
                { k: 'sym', label: 'SYMBOL', l: true, fmt: r => h('span', { class: 'amb', raw: true }, r.sym) },
                { k: 'score', label: 'EXCESS SCORE', sort: r => r[`er_${horizon}`], fmt: r => signedPct(r[`er_${horizon}`], 2) },
                { k: 'factor', label: 'RELATIVE FACTOR', sort: r => r[`factor_${horizon}`], fmt: r => r[`factor_${horizon}`] == null ? '—' : `${r[`factor_${horizon}`].toFixed(4)}×` },
              ], matured, { sortKey: 'score' }) : h('div', { class: 'body mut' }, loadingRows ? 'Loading decisions…' : 'No fixed-horizon score matured on this day; the averages carry forward.'))))),
      panel('AVERAGE RELATIVE FACTOR', `one panel per decision class · ${horizonDays}-day scores averaged, never compounded · 1.0000× is neutral`, null,
        h('div', { class: 'body' }, facets.length
          ? factorFacets({ dates: dates.slice(0, slide + 1), facets })
          : h('span', { class: 'mut' }, 'No priced decisions yet.')),
        h('div', { class: 'body mut' }, A.methodology)),
      panel('DECISION EVIDENCE', 'average CAD excess return at fixed trading-day horizons · n = priced decisions', null,
        table(evidenceCols, A.summary, { sortKey: 'cls', desc: false }),
        h('div', { class: 'body mut' }, 'The 10–90% bands resample whole campaigns, preserving dependence between transactions in the same position. Wide bands mean the result depends heavily on which campaigns occurred.')),
      h('div', { class: 'row' },
        panel('CONCENTRATION STRESS TEST', 'remove the highest-P&L campaigns and replay the remaining ledger', null,
          table([
            { k: 'label', label: 'SCENARIO', l: true },
            { k: 'return_', label: 'RETURN', fmt: r => signedPct(r.return_, 2) },
            { k: 'excess', label: 'VS BENCH', fmt: r => signedPP(r.excess, 2) },
            { k: 'end_value', label: 'END VALUE', fmt: r => money(r.end_value) },
            { k: 'trades_removed', label: 'TRADES OUT' },
          ], removals, { sortKey: 'n', desc: false }),
          h('div', { class: 'body mut' }, 'Campaigns are ranked by dollars but the column is a rate, so removing a large winner that earned less than the portfolio average can raise the return. The freed cash is not reinvested; it sits idle for the rest of the history.')),
        panel('AVERAGING-DOWN ROBUSTNESS', `${AD.decisions} decisions in ${AD.campaigns} campaigns`, null,
          h('div', { class: 'stats' },
            stat('20D EST. RELATIVE EFFECT', signed(AD.impact_20d), 'trade notional × 20D excess return'),
            stat('60D EST. RELATIVE EFFECT', signed(AD.impact_60d), 'trade notional × 60D excess return'),
            stat('MEDIAN CAMPAIGN P&L', signed(AD.campaign_pnl_with), 'campaigns containing an add below cost'),
            stat('NO ADD BELOW COST', signed(AD.campaign_pnl_without), 'median of other campaigns')),
          table([
            { k: 'sym', label: 'TICKER', l: true, fmt: r => h('span', { class: 'amb', raw: true }, r.sym) },
            { k: 'decisions', label: 'N' },
            { k: 'impact_20d', label: '20D EFFECT', fmt: r => signed(r.impact_20d) },
            { k: 'impact_60d', label: '60D EFFECT', fmt: r => signed(r.impact_60d) },
          ], AD.by_ticker, { sortKey: 'impact_60d' }))),
      panel('CAMPAIGN P&L', `${C.ranked.length} total · options included in P&L but excluded from timing tests`, null,
        table([
          { k: 'sym', label: 'SYMBOL', l: true, fmt: r => h('span', {}, h('span', { class: 'amb', raw: true }, r.sym),
            r.option ? [' ', h('span', { class: 'tag' }, 'OPTION')] : null,
            r.transferred ? [' ', h('span', { class: 'tag' }, 'TRANSFER')] : null) },
          { k: 'acct', label: 'ACCOUNT', l: true, sm: false },
          { k: 'start', label: 'START' }, { k: 'end', label: 'END', fmt: r => r.end || 'OPEN' },
          { k: 'decisions', label: 'DECISIONS' },
          { k: 'avg_down', label: 'AVG↓', fmt: r => r.avg_down ? 'YES' : '—' },
          { k: 'realized_cad', label: 'REALIZED', fmt: r => signed(r.realized_cad) },
          { k: 'unrealized_cad', label: 'UNREALIZED', fmt: r => signed(r.unrealized_cad) },
          { k: 'pnl_cad', label: 'P&L CAD', fmt: r => signed(r.pnl_cad) },
        ], ranked, { sortKey: 'pnl_cad' }),
        A.coverage.transferred_campaigns ? h('div', { class: 'body mut' },
          `${A.coverage.transferred_campaigns} campaigns end or begin at a share transfer between Wealthsimple accounts. A transfer moves shares at a stated book value rather than selling them, so P&L stops and restarts at that value instead of running through.`) : null),
      panel('WHERE THE GAIN COMES FROM', 'campaign P&L is trades only · this ties it to the figure PERF reports', null,
        h('div', { class: 'stats' },
          stat('CAMPAIGN P&L', signed(RC.campaign_pnl), `${C.ranked.length} campaigns, realized + unrealized`),
          stat('INCOME & COSTS', signed(RC.income_total), 'dividends, interest, fees, tax, FX conversions'),
          stat('RESIDUAL', signed(RC.residual), 'cash drift and FX translation not attributable to a campaign'),
          stat('PORTFOLIO GAIN', signed(RC.portfolio_gain), 'the same number PERF shows')),
        table([
          { k: 'kind', label: 'SOURCE', l: true },
          { k: 'cad', label: 'CAD', fmt: r => signed(r.cad) },
        ], RC.income, { sortKey: 'cad' })),
      panel('SCOPE & LIMITATIONS', 'frozen hypotheses · explicit exclusions', null,
        h('div', { class: 'body' },
          h('div', { class: 'amb' }, 'PRE-REGISTERED V1 QUESTIONS'),
          h('div', {}, A.hypotheses.map(x => { const [id, name] = x.split(' '); return h('span', { style: 'display:inline-block;margin:3px 14px 3px 0' }, `${id} · `, hypothesisName(name)); })),
          h('ul', { class: 'plain', style: 'margin-top:8px;color:var(--muted);display:grid;gap:4px' },
            h('li', {}, 'Decision scoring uses daily closes only. The hourly bars on a symbol page are there to read a session back, and never enter a score.'),
            h('li', {}, `Options remain in actual P&L (${A.options.campaigns} campaigns, ${money(A.options.pnl_cad)}) but are excluded from equity timing tests without contract history.`),
            h('li', {}, 'The class averages weight every decision equally, regardless of size. They are diagnostic evidence paths, not portfolio returns.'),
            h('li', {}, 'The relative-effect dollars are exposure-weighted approximations, not a separately tradable portfolio return.'),
            h('li', {}, 'Shapley attribution, weekly-block bootstrap, and feasible timing randomization are not estimated in V1.'),
            h('li', {}, 'This audit reports what happened in this history. It never labels the result as proof of an edge.')))),
    ];
  },


  SIM() {
    const bar = panel('WHAT-IF MODE', state.simMode === 'FREEZE' ? 'stop all trading after a trade or day and let the portfolio ride' : 'remove specific past trades and replay history',
      seg(['FREEZE', 'REMOVE TRADES'], state.simMode, m => { state.simMode = m; render(); if (m === 'REMOVE TRADES' && !state.simResult) scheduleSim(); if (m === 'FREEZE') ensureFreeze(); }));
    return [bar, ...(state.simMode === 'FREEZE' ? freezeView() : SCREEN.SIM_REMOVE())];
  },
  SIM_REMOVE() {
    const sel = state.simSel, R = state.simResult;
    const byId = Object.fromEntries(D.trades.map(t => [t.id, t]));
    let shown = D.trades;
    if (state.simAcct !== 'ALL') shown = shown.filter(t => t.acct === state.simAcct);
    if (state.simSide !== 'ALL') shown = shown.filter(t => t.side === state.simSide);
    if (state.simSym) shown = shown.filter(t => t.sym.trim().startsWith(state.simSym));
    const change = () => { saveSel(); if (!sel.size) state.simResult = null; const y = window.scrollY; render(); window.scrollTo(0, y); scheduleSim(); };
    const presets = [
      ['AVG↓ BUYS', t => t.avgdown], ['SPECULATIVE', t => t.cat === 'speculative' && t.sym.length <= 10 && t.acct !== 'Crypto'],
      ['OPTIONS', t => t.sym.length > 10], ['CRYPTO', t => t.acct === 'Crypto'],
    ];
    const sumCost = [...sel].map(id => byId[id]).filter(Boolean);
    const stats = h('div', { class: 'stats' },
      stat('TRADES REMOVED', nf0.format(sel.size), `${sumCost.filter(t => t.side === 'BUY').length} buys · ${sumCost.filter(t => t.side === 'SELL').length} sells`),
      stat('ACTUAL VALUE', R ? money(R.summary.actual) : '—', 'replayed from your trades'),
      stat('SIMULATED VALUE', R ? money(R.summary.simulated) : sel.size ? 'RUNNING…' : '—', state.simRedirect === 'CASH' ? 'freed cash stays idle' : `freed cash buys ${state.simRedirect}`),
      stat('DIFFERENCE', R ? signed(R.summary.simulated - R.summary.actual) : '—', R ? signedPct((R.summary.simulated - R.summary.actual) / R.summary.actual, 2) : null),
      stat('REALIZED P&L', R ? h('span', {}, money(R.summary.realized_actual), h('span', { class: 'mut' }, ' → '), money(R.summary.realized_sim)) : '—', R && R.summary.clipped ? `${R.summary.clipped} later sells/transfers shrunk` : 'CAD'));
    const ctl = [
      ...seg(['CASH', 'CASH ETF', 'XEQT', 'VOO'], state.simRedirect, m => { state.simRedirect = m; state.simResult = null; render(); scheduleSim(); }),
    ];
    const pickCtl = [
      h('select', { 'aria-label': 'Account', onchange: e => { state.simAcct = e.target.value; render(); } },
        ['ALL', ...D.accounts.map(a => a.acct)].map(a => h('option', { value: a, selected: a === state.simAcct }, a.toUpperCase()))),
      h('select', { 'aria-label': 'Side', onchange: e => { state.simSide = e.target.value; render(); } },
        ['ALL', 'BUY', 'SELL'].map(a => h('option', { value: a, selected: a === state.simSide }, a))),
      h('input', { 'aria-label': 'Symbol filter', placeholder: 'SYMBOL', value: state.simSym, style: 'background:var(--hl);border:0;color:var(--ink);font:inherit;width:80px;padding:0 4px;text-transform:uppercase',
        onchange: e => { state.simSym = e.target.value.toUpperCase().trim(); render(); } }),
      h('button', { onclick: () => { shown.forEach(t => sel.add(t.id)); change(); } }, `+ALL ${shown.length}`),
      h('button', { onclick: () => { shown.forEach(t => sel.delete(t.id)); change(); } }, '−ALL'),
    ];
    const picker = table([
      { k: 'x', label: 'OUT', l: true, sort: r => sel.has(r.id) ? 1 : 0, fmt: r => h('input', { type: 'checkbox', checked: sel.has(r.id), 'aria-label': `Remove ${r.side} ${r.sym} ${r.date}`,
          onclick: e => e.stopPropagation(), onchange: e => { e.target.checked ? sel.add(r.id) : sel.delete(r.id); change(); } }) },
      { k: 'date', label: 'DATE', l: true },
      { k: 'acct', sm: false, label: 'ACCOUNT', l: true },
      { k: 'side', label: 'SIDE', l: true, fmt: r => h('span', { class: r.side === 'BUY' ? 'up' : 'down' }, r.side === 'BUY' ? '▲' : '▼', h('span', { class: 'sm-hide' }, ' ' + r.side)) },
      { k: 'sym', label: 'SYMBOL', l: true, fmt: r => h('span', { class: sel.has(r.id) ? 'mut' : 'amb', raw: true, style: sel.has(r.id) ? 'text-decoration:line-through' : '' }, r.sym) },
      { k: 'qty', sm: false, label: 'QTY', fmt: r => +r.qty.toFixed(6) },
      { k: 'amt', label: 'AMOUNT', fmt: r => h('span', {}, num(r.amt), ' ', h('span', { class: 'tag' }, r.cur)) },
      { k: 'edge', label: 'HINDSIGHT', fmt: r => signed(r.edge, x => money(x, 2)) },
    ], shown, { sortKey: 'date', max: 1500, onRow: r => { sel.has(r.id) ? sel.delete(r.id) : sel.add(r.id); change(); } });

    const out = [stats,
      panel('WHAT-IF', 'remove past trades and replay history · removed buys shrink later sells of those shares · the freed cash goes to →', ctl,
        h('div', { class: 'body', style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' },
          h('span', { class: 'mut' }, 'ADD PRESET:'),
          ...presets.map(([name, f]) => h('button', { class: 'amb', style: 'background:var(--hl);padding:0 8px', onclick: () => { D.trades.filter(f).forEach(t => sel.add(t.id)); change(); } }, `+ ${name}`)),
          h('button', { style: 'background:var(--hl);padding:0 8px;margin-left:auto', onclick: () => { sel.clear(); change(); } }, 'CLEAR ALL')))];
    if (R) {
      const i0 = rangeStart(R.dates, state.range);
      const dates = R.dates.slice(i0);
      out.push(panel('ACTUAL VS SIMULATED', 'CAD', seg(['3M', '6M', 'YTD', '1Y', 'ALL'], state.range, r => { state.range = r; render(); }),
        h('div', { class: 'body' }, lineChart({ dates, height: 300,
          yfmt: (v, full) => full ? money(v) : v >= 1000 ? '$' + nf0.format(Math.round(v / 1000)) + 'K' : money(v),
          series: [
            { name: 'ACTUAL', short: 'ACTUAL', color: 'var(--s1)', values: R.actual.slice(i0) },
            { name: 'SIMULATED', short: 'SIM', color: 'var(--s2)', values: R.simulated.slice(i0) },
            { name: 'NET DEPOSITED', short: 'DEPOSITED', color: 'var(--ref)', width: 1.5, values: R.contrib.slice(i0) },
          ] }))));
    }
    out.push(h('div', { class: 'row', style: 'grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr))' },
      panel('PICK TRADES', `${shown.length} shown · click a row or tick OUT`, pickCtl, picker),
      panel('WHAT CHANGES TODAY', R ? `${R.diffs.length} lines differ` : 'select trades to run', null,
        R ? table([
          { k: 'sym', label: 'POSITION', l: true, fmt: r => h('span', {}, h('span', { class: 'amb', raw: true }, r.sym), ' ', h('span', { class: 'tag' }, r.acct)) },
          { k: 'qty', label: 'ACTUAL QTY', fmt: r => r.qty == null ? '—' : +(+r.qty).toFixed(4) },
          { k: 'sim_qty', label: 'SIM QTY', fmt: r => r.sim_qty == null ? '—' : +(+r.sim_qty).toFixed(4) },
          { k: 'd', label: 'VALUE Δ CAD', sort: r => r.sim_value - r.value, fmt: r => signed(r.sim_value - r.value) },
        ], R.diffs, { sortKey: 'd' }) : h('div', { class: 'body mut' }, 'Tick trades on the left, or use a preset.'),
        R && R.clipped.length ? h('div', { class: 'body mut' }, h('div', { class: 'amb' }, 'SHRUNK BECAUSE SHARES WERE REMOVED'),
          ...R.clipped.slice(0, 20).map(c => h('div', {}, `${c.date} ${c.acct} ${c.sym}: ${+c.qty.toFixed(4)} → ${+c.kept.toFixed(4)}`))) : null)));
    out.push(h('div', { class: 'mut', style: 'padding:0 4px' }, 'Approximation: other trades are kept exactly as they happened, so the simulation ignores that you might have acted differently with the extra cash or shares. Options without price history are carried at cost.'));
    return out;
  },

  DATA() {
    if (!ST) { pollStatus().then(() => ST && state.screen === 'DATA' && render()); return [h('div', { class: 'skeleton' }, 'LOADING STATUS…')]; }
    const P = ST.plan, L = ST.limits, hist = ST.history;
    const d0 = new Date(), today = `${d0.getFullYear()}-${String(d0.getMonth() + 1).padStart(2, '0')}-${String(d0.getDate()).padStart(2, '0')}`;  // log times are local
    const reqToday = hist.filter(x => x.started.slice(0, 10) === today).reduce((a, x) => a + x.requests, 0);
    const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString();
    const rl7 = hist.filter(x => x.started >= weekAgo).reduce((a, x) => a + (x.rate_limited || 0), 0);
    const tiers = { held: 0, benchmark: 0, closed: 0 };
    P.tickers.forEach(t => tiers[t.tier]++);
    const ctl = [
      h('button', { 'aria-pressed': 'false', disabled: ST.job.running, onclick: () => startJob('fetch') }, 'FETCH DUE'),
      h('button', { 'aria-pressed': 'false', disabled: ST.job.running, onclick: () => startJob('rebuild') }, 'REBUILD'),
      h('button', { 'aria-pressed': 'false', disabled: ST.job.running, onclick: () => startJob('fetch', true) }, 'FORCE FULL…'),
    ];
    const budget = [
      ['SOURCE', 'Yahoo Finance (unofficial, via yfinance) for prices + calendars; Bank of Canada Valet for USD/CAD. Both free, no API key.'],
      ['COST', '$0. The real constraint is Yahoo throttling: it publishes no limit and answers bursts with HTTP 429.'],
      ['PACING', `${L.request_gap_s}s between requests, sequential (never parallel), so a burst is at most ~2–3 requests/second. On a 429: pause ${L.rate_limit_pause_s}s and retry once; a second 429 stops the run and keeps cached data.`],
      ['SKIPS', `A ticker is only requested when a newer daily close should exist than its last check. Held + benchmarks: every session (${tiers.held + tiers.benchmark}). Closed positions (${tiers.closed}): weekly, staggered by weekday. Delisted: weekly re-check.`],
      ['CALENDARS', `Stocks: once per ${L.calendar_ttl_h}h. ETFs have none, remembered for 30 days (ETF ex-dividend dates are projected locally).`],
      ['BUTTON', `${L.cooldown_s}s cooldown after each fetch; only one job at a time. REBUILD never touches the network.`],
      ['TYPICAL', `~30–40 requests per trading day (~15 held/benchmark, ~16 staggered closed, 1 FX, a few calendars), ~2 on weekends (crypto). Full forced re-download: ~${P.tickers.length + 14} requests, ~45s.`],
    ];
    return [
      h('div', { class: 'stats' },
        stat('DUE NOW', `${P.requests} REQ`, P.requests ? `~${P.est_seconds}s · ${P.price_due} prices · ${P.hourly_due || 0} hourly · ${P.calendar_due} calendars${P.fx_due ? ' · FX' : ''}` : 'everything is current'),
        stat('LAST FETCH', hist[0] ? ago(hist[0].started) : '—', hist[0] ? `${hist[0].requests} req · ${hist[0].seconds}s` : null),
        stat('REQUESTS TODAY', nf0.format(reqToday), `${hist.filter(x => x.started.slice(0, 10) === today).length} runs`),
        stat('429s, LAST 7D', h('span', { class: rl7 ? 'warn' : '' }, nf0.format(rl7)), rl7 ? 'slow down: raise REQUEST_GAP' : 'no throttling seen'),
        stat('JOB', ST.job.running ? `${ST.job.kind.toUpperCase()}…` : ST.job.kind ? (ST.job.ok ? 'OK' : h('span', { class: 'down' }, 'FAILED')) : 'IDLE', ST.cooldown ? `cooldown ${ST.cooldown}s` : null)),
      panel('FETCH HISTORY', 'market/fetch_log.jsonl', ctl, table([
        { k: 'started', label: 'STARTED', l: true, fmt: r => r.started.replace('T', ' ') },
        { k: 'requests', label: 'REQUESTS' },
        { k: 'seconds', label: 'SECONDS' },
        { k: 'price_updated', label: 'PRICES UPD', fmt: r => r.price_updated ?? '—' },
        { k: 'price_skipped', sm: false, label: 'SKIPPED', fmt: r => r.price_skipped ?? '—' },
        { k: 'calendar_skipped', sm: false, label: 'CAL CACHED', fmt: r => r.calendar_skipped ?? '—' },
        { k: 'fx', sm: false, label: 'FX', fmt: r => (r.fx || '—').toUpperCase() },
        { k: 'rate_limited', label: '429s', fmt: r => r.rate_limited ? h('span', { class: 'warn' }, r.rate_limited) : '0' },
        { k: 'errors', label: 'ISSUES', l: true, sort: r => r.errors.length, fmt: r => r.aborted ? h('span', { class: 'down' }, r.aborted) : r.errors.length ? h('span', { class: 'warn', title: r.errors.join('\n') }, `${r.errors.length} errors`) : h('span', { class: 'mut' }, r.force ? 'forced' : '—') },
      ], hist, { sortKey: 'started' })),
      h('div', { class: 'row' },
        panel('REQUEST BUDGET', 'how fetching stays cheap', null, h('div', { class: 'tw help' }, h('table', {}, h('tbody', {}, budget.map(([a, b]) => h('tr', {}, h('td', { class: 'amb', style: 'vertical-align:top' }, a), h('td', { style: 'white-space:normal' }, b))))))),
        panel('TICKERS', `${P.tickers.length} · ${P.price_due} due`, null, table([
          { k: 'ticker', label: 'TICKER', l: true, fmt: r => h('span', { class: 'amb', raw: true }, r.ticker) },
          { k: 'tier', label: 'TIER', l: true, fmt: r => h('span', { class: r.tier === 'closed' ? 'mut' : '' }, r.tier.toUpperCase()) },
          { k: 'last', label: 'LAST BAR', fmt: r => r.last || '—' },
          { k: 'checked', sm: false, label: 'CHECKED', fmt: r => ago(r.checked) },
          { k: 'due', label: 'DUE', sort: r => r.due ? 1 : 0, fmt: r => r.due ? h('span', { class: 'amb' }, 'YES') : h('span', { class: 'mut' }, '—') },
        ], P.tickers, { sortKey: 'due' }))),
    ];
  },

  IMP() {
    const E = ST && ST.exports, P = state.imp.preview, busy = state.imp.busy;
    if (!ST) pollStatus().then(() => state.screen === 'IMP' && rerenderKeepScroll());
    const input = h('input', { type: 'file', accept: '.csv,text/csv', multiple: true, id: 'impfile', class: 'visually-hidden',
      onchange: e => uploadFiles([...e.target.files]) });
    const zone = h('label', { for: 'impfile', class: 'drop' + (busy ? ' busy' : ''), tabindex: 0,
      ondragover: e => { e.preventDefault(); e.currentTarget.classList.add('over'); },
      ondragleave: e => e.currentTarget.classList.remove('over'),
      ondrop: e => { e.preventDefault(); e.currentTarget.classList.remove('over'); uploadFiles([...e.dataTransfer.files]); },
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } } },
      h('div', { class: 'drop-title' }, busy ? 'CHECKING FILES…' : 'DROP CSV EXPORTS HERE'),
      h('div', { class: 'mut' }, 'or click to choose · activities export and/or holdings report · up to 10 files'),
      h('div', { class: 'mut' }, 'Overlapping date ranges are fine: rows you already have are skipped.'), input);
    const out = [
      h('div', { class: 'stats' },
        stat('ACTIVITY ROWS', E && E.activities.rows ? nf0.format(E.activities.rows) : '—', E && E.activities.rows ? `${E.activities.first} → ${E.activities.last}` : 'nothing imported yet'),
        stat('HOLDINGS AS OF', E && E.holdings_asof ? E.holdings_asof.replace('T', ' ') : '—', 'latest holdings report'),
        stat('ACCOUNTS', E && E.activities.accounts ? E.activities.accounts.length : '—', E && E.activities.accounts ? E.activities.accounts.join(' · ') : null),
        stat('UPLOADS ARCHIVED', E ? nf0.format(E.uploads) : '—', E && E.inbox ? h('span', { class: 'warn' }, `${E.inbox} waiting in inbox`) : 'originals kept, never modified')),
      panel('IMPORT EXPORTS', 'Wealthsimple activities export and holdings report, the same CSV formats as before', null, h('div', { class: 'body' }, zone)),
    ];
    if (E && E.activities.rows && !E.holdings_asof) out.splice(1, 0,
      panel('ACTIVITY-DERIVED HOLDINGS', 'portfolio panes use transactions plus latest Yahoo prices', null,
        h('div', { class: 'body warn' }, 'Estimated mode: open quantities, cash and cost basis are reconstructed from the activity ledger. A holdings report is optional and can later verify the snapshot.')));
    if (P) {
      const needsForce = P.files.some(f => f.warnings.some(w => w.startsWith('Older than current holdings')));
      out.push(
        h('div', { class: 'stats' },
          stat('NEW ACTIVITY ROWS', signed(P.added, nf0.format, 1), `${nf0.format(P.duplicates)} duplicates skipped`),
          stat('HISTORY AFTER', P.after.rows ? nf0.format(P.after.rows) : '—', P.after.rows ? `${P.after.first} → ${P.after.last}` : null),
          stat('HOLDINGS', P.holdings_asof ? P.holdings_asof.replace('T', ' ') : 'unchanged', P.current_holdings_asof ? `current ${P.current_holdings_asof.replace('T', ' ')}` : null),
          stat('NEW SYMBOLS', nf0.format(P.new_symbols.length), P.new_symbols.length ? 'prices will be fetched' : null),
          stat('RECONCILIATION', P.reconciliation_total ? h('span', { class: 'warn' }, `${P.reconciliation_total} ISSUES`) : h('span', { class: 'up' }, '✓ MATCHES'), 'activities vs holdings quantities')),
        panel('FILES', `preview ${P.id}`, null, table([
          { k: 'ok', label: 'STATUS', l: true, fmt: r => h('span', { class: r.ok ? 'up' : 'down' }, r.ok ? '✓ OK' : '✕ REJECTED') },
          { k: 'file', label: 'FILE', l: true },
          { k: 'kind', label: 'TYPE', l: true, fmt: r => (r.kind || 'unknown').toUpperCase() },
          { k: 'rows', label: 'ROWS', fmt: r => r.rows ?? '—' },
          { k: 'range', label: 'COVERS', l: true, sm: false, fmt: r => r.kind === 'holdings' ? `as of ${(r.asof || '?').replace('T', ' ')}` : r.first ? `${r.first} → ${r.last}` : '—' },
          { k: 'notes', label: 'NOTES', l: true, fmt: r => h('div', { class: 'notes' }, ...r.errors.map(e => h('div', { class: 'down' }, e)), ...r.warnings.map(w => h('div', { class: 'warn' }, w))) },
        ], P.files, {})),
        P.reconciliation.length ? panel('RECONCILIATION', 'usually means the two exports were taken on different days; import both from the same day to clear', null,
          h('div', { class: 'body' }, h('ul', { class: 'plain' }, P.reconciliation.map(x => h('li', { class: 'warn' }, x))))) : null,
        panel('COMMIT', null, null, h('div', { class: 'body actions' },
          needsForce ? h('label', {}, h('input', { type: 'checkbox', checked: state.imp.force, onchange: e => { state.imp.force = e.target.checked; } }), ' Replace holdings even though the file is older') : null,
          h('button', { class: 'fetchbtn', disabled: !P.committable || busy, onclick: commitImport }, P.added || P.holdings_asof ? 'COMMIT & REBUILD' : 'NOTHING NEW · COMMIT ANYWAY'),
          h('button', { class: 'amb', disabled: busy, onclick: () => { state.imp.preview = null; render(); } }, 'CANCEL'))));
    }
    if (state.imp.result) {
      const R = state.imp.result;
      out.push(panel('LAST IMPORT', null, null, h('div', { class: 'body' },
        h('div', {}, h('span', { class: 'up' }, '✓ '), `+${nf0.format(R.added)} activity rows · ${nf0.format(R.duplicates)} duplicates skipped · holdings ${R.holdings_updated ? 'updated' : 'unchanged'} · ${R.job ? R.job.toUpperCase() + ' started' : 'no rebuild'}`),
        h('div', { class: 'mut' }, `Archived: ${R.archived.join(', ')}`))));
    }
    out.push(exportGuide());
    out.push(panel('OTHER WAYS IN', null, null, h('div', { class: 'tw help' }, h('table', {}, h('tbody', {},
      h('tr', {}, h('td', { class: 'amb' }, 'INBOX'), h('td', { style: 'white-space:normal' }, 'Copy CSVs into exports/inbox/ on the server (scp, Syncthing…). They are imported within 5 minutes or on REBUILD; rejected files move to inbox/rejected/.')),
      h('tr', {}, h('td', { class: 'amb' }, 'CLI'), h('td', { style: 'white-space:normal' }, 'docker compose exec portfolio python pipeline/store.py /data/exports/inbox/<file>.csv')))))));
    return out;
  },

  HELP() {
    const cmds = [...SCREENS.map(([k, n], i) => [`${k} <GO>  or  ${i + 1}`, n]),
      ['NVDA <GO>', 'Open a symbol: price history with your buys ▲ and sells ▼'],
      ['T.TO <GO>', 'Use the Yahoo ticker to disambiguate (T = AT&T, T.TO = Telus)'],
      ['/  or start typing', 'Focus the command line'], ['LANG <GO>', 'Language: English / 中文'], ['FETCH <GO>', 'Download only market data that is due, then rebuild'], ['REBUILD <GO>', 'Recompute from exports and cached prices (no network)'], ['ESC', 'Back to previous screen'],
      ['VIM <GO>  or  top-right VIM', 'Enable Vim keys: h/j/k/l move between panel controls · Enter/Space activate · gg/G top/bottom · Ctrl-d/Ctrl-u half-page · b back · i/: command'],
      [':q  or  top-right EXIT VIM', 'Exit Vim mode'],
      ['DATA <GO>  or  0', 'Fetch history, request budget, per-ticker freshness'],
      ['IMPORT <GO>', 'Upload new Wealthsimple CSV exports (preview before commit)'],
      ['NEW EXPORTS', 'Drop them into WS/, then REBUILD (or FETCH if prices are due). Thresholds and buckets: pipeline/config.json']];
    return [panel('HELP', null, null, h('div', { class: 'tw help' }, h('table', {}, h('tbody', {}, cmds.map(([a, b]) => h('tr', {}, h('td', { class: 'amb' }, a), h('td', {}, b)))))))];
  },

  SYM() {
    const t = state.sym;
    const el = h('div', {}, h('div', { class: 'skeleton' }, `LOADING ${t.yahoo}…`));
    loadSymbol(t).then(view => el.replaceChildren(...view.filter(Boolean))).catch(e => el.replaceChildren(h('div', { class: 'skeleton' }, `NO PRICE DATA FOR ${t.yahoo}: ${e.message}`)));
    return [el];
  },
};

// ---------- option positions (a contract has no chart of its own; project from the underlying) ----------
function optionsPanel(ticker, rootSym) {
  const list = (D.options || []).filter(o => o.underlying === ticker || o.root === rootSym);
  if (!list.length) return null;
  const focus = list.find(o => o.symbol === state.optionFocus) || list[0];
  const pts = focus.payoff || [];
  const chart = pts.length ? lineChart({
    dates: pts.map(p => p.spot), height: 240, zeroLine: true,
    xfmt: (v, full) => money(+v, full ? 2 : (+v < 10 ? 2 : 0)),
    yfmt: (v, full) => full ? money(v, 2) : money(v),
    series: [{ name: `P&L AT EXPIRY · ${focus.symbol}`, short: 'P&L', color: 'var(--s1)', values: pts.map(p => p.pl) }],
  }) : null;
  return panel('OPTION POSITIONS', `carried at cost · ${focus.right} ${money(focus.strike, 2)} expiring ${focus.expiry}`, null,
    h('div', { class: 'stats' },
      stat('CONTRACTS', `${+focus.contracts} × ${focus.right}`, `strike ${money(focus.strike, 2)} · ${focus.acct}`),
      stat('PREMIUM PAID', money(focus.cost, 2), `${money(focus.premium_per_share, 2)}/share · ${money(focus.cost_cad)} CAD`),
      stat('BREAK-EVEN', money(focus.breakeven, 2), focus.to_breakeven == null ? 'at expiry'
        : h('span', {}, 'underlying needs ', signedPct(focus.to_breakeven, 1))),
      stat('UNDERLYING NOW', focus.spot == null ? '—' : money(focus.spot, 2), focus.moneyness == null ? null
        : h('span', {}, focus.moneyness >= 0 ? 'in the money ' : 'out of the money ', signedPct(focus.moneyness, 1))),
      stat('DAYS TO EXPIRY', focus.expired ? 'EXPIRED' : `${focus.days_to_expiry}D`,
        focus.intrinsic_pl == null ? 'no underlying price' : h('span', {}, 'if it expired today: ', signed(focus.intrinsic_pl)))),
    chart ? h('div', { class: 'body' }, chart) : null,
    h('div', { class: 'body mut' }, 'Contracts have no price history to chart, so the position is held at cost. The curve is the payoff at expiry: intrinsic value minus the premium paid, ignoring any time value left.'),
    list.length > 1 ? table([
      { k: 'symbol', label: 'CONTRACT', l: true, fmt: r => h('span', { class: r.symbol === focus.symbol ? 'amb' : '', raw: true }, r.symbol) },
      { k: 'acct', label: 'ACCOUNT', l: true, sm: false },
      { k: 'contracts', label: 'QTY', fmt: r => +r.contracts },
      { k: 'strike', label: 'STRIKE', fmt: r => money(r.strike, 2) },
      { k: 'expiry', label: 'EXPIRY' },
      { k: 'cost', label: 'PREMIUM', fmt: r => money(r.cost, 2) },
      { k: 'intrinsic_pl', label: 'IF EXPIRED TODAY', fmt: r => r.intrinsic_pl == null ? '—' : signed(r.intrinsic_pl) },
    ], list, { sortKey: 'expiry', onRow: r => { state.optionFocus = r.symbol; rerenderKeepScroll(); } }) : null);
}

// ---------- intraday (60-minute bars, rolling one-month window) ----------
const INTRADAY_SPANS = [['5D', 5], ['10D', 10], ['1M', 30]];
const vol = v => v == null ? '—' : v >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : nf0.format(v);
const barTime = ts => `${fmtDate(ts.slice(0, 10))} ${ts.slice(11, 16)}`;
// Yahoo attributes no volume to the opening bar on most TSX listings. A bar that clearly traded -- it
// has a high above its low -- but reports none has unknown volume, not zero, and must not average in.
const volReported = b => b.Volume > 0 || b.High <= b.Low;

function intradayPanel(t, bars, trades, toListed) {
  if (!bars) {
    return panel('INTRADAY · 60-MINUTE BARS', 'not tracked for this ticker', null,
      h('div', { class: 'body mut' }, 'Hourly bars are kept only for current holdings, the benchmarks, and anything traded in the last five weeks. Yahoo serves intraday history for a recent window only, so there is nothing to back-fill for an older position.'));
  }
  const days = [...new Set(bars.map(b => b.Datetime.slice(0, 10)))];
  const span = INTRADAY_SPANS.find(([k]) => k === state.intradaySpan) || INTRADAY_SPANS[0];
  const keep = new Set(days.slice(-span[1]));
  const win = bars.filter(b => keep.has(b.Datetime.slice(0, 10)));
  const ctl = seg(INTRADAY_SPANS.map(([k]) => k), span[0], k => { state.intradaySpan = k; render(); });
  if (!win.length) return panel('INTRADAY · 60-MINUTE BARS', 'no bars in this window', ctl);

  const rows = win.map((b, i) => ({
    ...b, prev: i ? win[i - 1].Close : null,
    chg: i && win[i - 1].Close ? b.Close / win[i - 1].Close - 1 : null,
    range: b.High - b.Low, rangePct: b.Low ? b.High / b.Low - 1 : null,
  }));
  const closes = rows.map(r => r.Close), last = rows[rows.length - 1];
  const hi = Math.max(...rows.map(r => r.High)), lo = Math.min(...rows.map(r => r.Low));
  const moved = rows.filter(r => r.chg != null);
  const best = moved.reduce((a, r) => (a && a.chg >= r.chg ? a : r), null);
  const worst = moved.reduce((a, r) => (a && a.chg <= r.chg ? a : r), null);
  const known = rows.filter(volReported);
  const avgVol = known.length ? known.reduce((a, r) => a + r.Volume, 0) / known.length : null;
  const up = moved.filter(r => r.chg > 0).length;

  // Only an order placed inside its own session has a time worth trusting. One queued earlier filled at
  // some unknown point, so it is drawn at the open rather than claiming an hour it never had.
  const markers = [];
  for (const tr of trades) {
    if (!keep.has(tr.date)) continue;
    const session = rows.filter(r => r.Datetime.slice(0, 10) === tr.date);
    if (!session.length) continue;
    const placed = !tr.queued && tr.time ? `${tr.date}T${tr.time}` : null;
    const bar = (placed && [...session].reverse().find(r => r.Datetime.slice(0, 16) <= placed)) || session[0];
    markers.push({ i: rows.indexOf(bar), y: toListed(tr.px, tr.cur, tr.date), side: tr.side,
      label: `${tr.acct} ${tr.qty} @ ${num(tr.px)} ${tr.cur} · ${placed ? `ordered ${tr.time}` : 'queued before the open'}` });
  }

  return panel('INTRADAY · 60-MINUTE BARS', `${rows.length} bars over ${Math.min(days.length, span[1])} sessions · exchange local time`, ctl,
    h('div', { class: 'stats' },
      stat('LAST BAR', num(last.Close, 2), h('span', {}, barTime(last.Datetime), ' · ', signedPct(last.chg, 2))),
      stat('WINDOW RANGE', `${num(lo, 2)} – ${num(hi, 2)}`, hi > lo
        ? h('span', {}, 'last close sits at ', pct((last.Close - lo) / (hi - lo), 0), ' of it') : null),
      stat('BEST HOUR', best ? signedPct(best.chg, 2) : '—', best ? barTime(best.Datetime) : null),
      stat('WORST HOUR', worst ? signedPct(worst.chg, 2) : '—', worst ? barTime(worst.Datetime) : null),
      stat('HOURS UP', moved.length ? `${up} / ${moved.length}` : '—', moved.length ? pct(up / moved.length, 0) : null),
      stat('AVG HOURLY VOLUME', vol(avgVol), known.length === rows.length
        ? h('span', {}, 'last bar ', vol(last.Volume))
        : h('span', { class: 'mut' }, `${rows.length - known.length} bars report none`))),
    h('div', { class: 'body' }, lineChart({
      dates: rows.map(r => r.Datetime), height: 300, markers,
      series: [{ name: `${t.yahoo} 60m`, short: t.yahoo, color: 'var(--s1)', values: closes }],
      yfmt: (v, full) => num(v, full || v < 100 ? 2 : 0),
      xfmt: v => barTime(v),   // index-based ticks repeat a day, so every label carries its hour
    })),
    table([
      { k: 'Datetime', label: 'BAR', l: true, fmt: r => h('span', {}, fmtDate(r.Datetime.slice(0, 10)), ' ', h('b', {}, r.Datetime.slice(11, 16))) },
      { k: 'Open', label: 'OPEN', fmt: r => num(r.Open, 2) },
      { k: 'High', label: 'HIGH', fmt: r => num(r.High, 2) },
      { k: 'Low', label: 'LOW', fmt: r => num(r.Low, 2) },
      { k: 'Close', label: 'CLOSE', fmt: r => h('b', {}, num(r.Close, 2)) },
      { k: 'chg', label: 'CHG', fmt: r => signedPct(r.chg, 2) },
      { k: 'rangePct', label: 'RANGE', sm: false, fmt: r => h('span', {}, num(r.range, 2), h('span', { class: 'mut' }, ` · ${pct(r.rangePct, 2)}`)) },
      { k: 'Volume', label: 'VOLUME', fmt: r => volReported(r) ? vol(r.Volume) : h('span', { class: 'mut', title: 'Yahoo reported no volume for this bar' }, '—') },
    ], rows, { sortKey: 'Datetime', max: 400 }),
    h('div', { class: 'body mut' }, 'A bar is stamped with the hour it opened, in the exchange\'s own time. Wealthsimple stamps an order when it was placed, never when it filled, so ▲/▼ mark the hour an order was entered; one queued before the open is drawn at the open, because nothing in the export says when it actually executed. While a session is open the newest bar is still forming. Yahoo reports no volume for the opening bar on most TSX listings; those show as — and stay out of the average rather than counting as zero. Intraday bars are not split- or dividend-adjusted; only the last month is available from Yahoo, and it is refetched rather than accumulated.'));
}

// ---------- ledger vs broker snapshot ----------
// Positions and NAV are computed from the activity ledger, so an import moves them immediately. The
// holdings report is Wealthsimple's own count on its own date: here it exists only to be checked
// against, and to explain itself when it disagrees rather than quietly overriding anything.
function reconcilePanel() {
  const R = D.reconcile;
  if (!R) {
    return panel('LEDGER VS BROKER SNAPSHOT', 'no holdings report imported', null,
      h('div', { class: 'body mut' }, 'Everything is computed from your activity history, which is enough on its own. Importing a holdings report adds an independent check on the share counts and cash.'));
  }
  const n = R.differences.length;
  const sub = R.stale ? `report is from ${R.asof} · your trades run to ${R.newest_activity}` : `report is from ${R.asof}`;
  const verdict = !n
    ? h('div', { class: 'body' }, h('span', { class: 'up' }, '▲ MATCHES'), h('span', { class: 'mut' }, ' — every share count and cash balance agrees with the broker.'))
    : h('div', { class: 'body' }, R.stale
      ? 'Positions and NAV come from your activity ledger, so these lines are simply the trades made after the report was taken. Export a fresh holdings report to clear them.'
      : 'The report is not older than your trades, so these lines are a real disagreement: an activity export may be missing rows. Re-export the full activity history.');
  return panel('LEDGER VS BROKER SNAPSHOT', sub, null,
    h('div', { class: 'stats' },
      stat('LEDGER NAV', money(R.ledger_value), 'computed from your trades'),
      stat('REPORT NAV', money(R.report_value), `as of ${R.asof}`),
      stat('LINES DIFFER', n ? String(n) : '—', n ? 'share counts and cash below' : 'nothing to explain'),
      stat('REPORT AGE', R.stale ? 'BEHIND' : 'CURRENT', R.stale ? `trades run to ${R.newest_activity}` : 'covers every trade')),
    verdict,
    n ? table([
      { k: 'acct', label: 'ACCOUNT', l: true },
      { k: 'sym', label: 'SYMBOL', l: true, fmt: r => h('span', { class: 'amb', raw: true }, r.sym) },
      { k: 'ledger', label: 'LEDGER', fmt: r => num(r.ledger, 4) },
      { k: 'report', label: 'REPORT', fmt: r => num(r.report, 4) },
      { k: 'diff', label: 'DIFFERENCE', fmt: r => signed(r.diff, x => num(x, 4)) },
    ], R.differences, { sortKey: 'diff' }) : null);
}

// ---------- symbol screen ----------
const csvCache = {};
// The first column is a timestamp: a date for daily files, a full exchange-local stamp for hourly ones.
async function fetchCSV(url, keepTime = false) {
  if (csvCache[url]) return csvCache[url];
  const r = await fetch(url); if (!r.ok) throw new Error(r.status);
  const [head, ...lines] = (await r.text()).trim().split(/\r?\n/);
  const cols = head.split(',');
  return csvCache[url] = lines.map(l => { const v = l.split(','); return Object.fromEntries(cols.map((c, i) => [c, i ? +v[i] : (keepTime ? v[i] : v[i].slice(0, 10))])); });
}
async function loadSymbol(t) {
  const px = await fetchCSV(`/prices/${encodeURIComponent(t.yahoo)}.csv`);
  const fx = await fetchCSV('/fx_usdcad.csv');
  // Only tracked for what is still worth an intraday look; a 404 is the normal answer for the rest.
  const bars = await fetchCSV(`/hourly/${encodeURIComponent(t.yahoo)}.csv`, true).catch(() => null);
  const fxAt = d => { let lo = 0, hi = fx.length - 1, best = fx[0].USDCAD; while (lo <= hi) { const m = (lo + hi) >> 1; if (fx[m].Date <= d) { best = fx[m].USDCAD; lo = m + 1; } else hi = m - 1; } return best; };
  const cadListed = /\.(TO|NE)$|-CAD$/.test(t.yahoo);
  const splitAfter = d => px.filter(p => p.Date > d && p['Stock Splits'] > 0).reduce((a, p) => a * p['Stock Splits'], 1);
  // One rule for putting a fill on a chart: convert a CAD-booked trade, then undo any later split.
  const toListed = (price, cur, d) => (cur === 'CAD' && !cadListed ? price / fxAt(d) : price) / splitAfter(d);
  const trades = D.trades.filter(x => x.sym === t.sym && (D.tickers.find(k => k.sym === x.sym && k.cur === x.cur) || {}).yahoo === t.yahoo);
  const i0 = rangeStart(px.map(p => p.Date), state.range);
  const rows = px.slice(i0), dates = rows.map(r => r.Date);
  const idx = d => { let i = dates.findIndex(x => x >= d); return i < 0 ? -1 : i; };
  const markers = [];
  for (const tr of trades) {
    const i = idx(tr.date); if (i < 0 || tr.date < dates[0]) continue;
    markers.push({ i, y: toListed(tr.px, tr.cur, tr.date), side: tr.side, label: `${tr.acct} ${tr.qty} @ ${num(tr.px)} ${tr.cur}` });
  }
  const last = rows[rows.length - 1], first = rows[0];
  const same = new Set(D.tickers.filter(k => k.yahoo === t.yahoo).map(k => `${k.sym}|${k.cur}`));
  const held = D.holdings.filter(x => same.has(`${x.sym}|${x.cur}`));
  const pos = D.positions.filter(p => same.has(`${p.sym}|${p.cur}`));
  const ctl = seg(['1M', '3M', '6M', 'YTD', '1Y', 'ALL'], state.range, r => { state.range = r; render(); });
  return [
    h('div', { class: 'stats' },
      stat(`${t.yahoo} · ${cadListed ? 'CAD' : 'USD'}`, num(last.Close), h('span', { raw: true }, t.name)),
      stat('CHANGE IN RANGE', signedPct(last.Close / first.Close - 1), `${first.Date} → ${last.Date}`),
      stat('HELD NOW', held.length ? held.map(x => `${+x.qty.toFixed(4)} ${x.acct}`).join(' · ') : '—', held.length ? h('span', {}, 'unreal ', signed(held.reduce((a, x) => a + (x.upl || 0), 0))) : null),
      stat('REALIZED (CAD)', pos.length ? signed(pos.reduce((a, p) => a + p.realized_cad, 0)) : '—', `${trades.length} trades`)),
    panel(`${t.yahoo} <EQUITY>`, `split-adjusted close${cadListed ? '' : ' (USD; CAD-booked trades converted)'} · ▲ your buys · ▼ your sells`, ctl,
      h('div', { class: 'body' }, lineChart({ dates, series: [{ name: t.yahoo, short: t.yahoo, color: 'var(--s1)', values: rows.map(r => r.Close) }], yfmt: (v, full) => num(v, full || v < 100 ? 2 : 0), height: 340, markers }))),
    intradayPanel(t, bars, trades, toListed),
    optionsPanel(t.yahoo, t.sym),
    panel('TRADES', null, h('button', { 'aria-pressed': 'false', onclick: () => { trades.forEach(x => state.simSel.add(x.id)); saveSel(); state.simResult = null; state.simMode = 'REMOVE TRADES'; go('SIM'); } }, `SIMULATE WITHOUT ${t.sym} →`), table([
      { k: 'date', label: 'EXECUTED', l: true, fmt: r => h('span', {}, r.date, r.time
        ? h('span', { class: 'mut', title: r.queued ? `ordered ${r.booked} ${r.time}, executed next session` : 'order placed' }, ` ${r.queued ? '◷' : ''}${r.time}`)
        : null) },
      { k: 'acct', sm: false, label: 'ACCOUNT', l: true },
      { k: 'side', label: 'SIDE', l: true, fmt: r => h('span', { class: r.side === 'BUY' ? 'up' : 'down' }, r.side === 'BUY' ? '▲' : '▼', h('span', { class: 'sm-hide' }, ' ' + r.side)) },
      { k: 'qty', sm: false, label: 'QTY', fmt: r => +r.qty.toFixed(6) }, { k: 'px', sm: false, label: 'PRICE', fmt: r => h('span', {}, num(r.px), ' ', h('span', { class: 'tag' }, r.cur)) },
      { k: 'edge', label: 'HINDSIGHT', fmt: r => signed(r.edge, x => money(x, 2)) },
    ], trades, { sortKey: 'date' })),
  ];
}
function optionRoot(sym) {                      // 'OPEN  261002C00002500' -> 'OPEN'
  const m = /^([A-Z][A-Z0-9.]{0,5})\s+\d{6}[CP]\d{8}$/.exec((sym || '').trim());
  return m ? m[1] : null;
}
function openSymbol(sym, cur) {
  const root = optionRoot(sym);
  if (root) {                                    // contracts have no chart of their own: show the underlying
    state.optionFocus = sym.trim();
    return openSymbol(root, cur);
  }
  const t = D.tickers.find(k => k.sym === sym && k.cur === cur) || D.tickers.find(k => k.sym === sym);
  if (!t) return msg(`NO PRICE HISTORY FOR ${sym}`);
  state.sym = t; go('SYM');
}


let simTimer, simSeq = 0;
function scheduleSim() {
  clearTimeout(simTimer);
  if (!state.simSel.size) return;
  simTimer = setTimeout(async () => {
    const seq = ++simSeq;
    try {
      const redirect = { XEQT: 'XEQT.TO', VOO: 'VOO', 'CASH ETF': 'CCAD.TO' }[state.simRedirect] || null;
      const { data: j } = await api('/api/simulate', { method: 'POST', json: { exclude: [...state.simSel], redirect } });
      if (!j.ok) throw new Error(j.log);
      if (seq !== simSeq) return;
      state.simResult = j;
      if (state.screen === 'SIM') { const y = window.scrollY; render(); window.scrollTo(0, y); }
    } catch (e) { msg(`SIMULATION FAILED: ${e.message}`); }
  }, 350);
}

// ---------- how to export from Wealthsimple ----------
const EXPORT_STEPS = [
  { img: 'guide-1-activity.png', title: 'Open Activity and start the export',
    lines: ['In the Wealthsimple desktop web app, select the clock icon in the left sidebar to open **Activity**.',
            'On the Activity page, select **Download activities** above the transaction list.'] },
  { img: 'guide-2-period.png', title: 'Choose the period',
    lines: ['Set **Select period** to **Custom period**.',
            '**Start date**: a date before your first trade — 2000-01-01 is a safe catch-all. Full history is what lets the app compute cost basis; a partial range still imports and merges.',
            'Leave **End date** as today, then **Next**.'] },
  { img: 'guide-3-accounts.png', title: 'Pick the accounts and download',
    lines: ['Tick **All accounts** so every account lands in one file (TFSA, FHSA, RRSP, Non-registered, Crypto).',
            'Expand **Closed / Archived** if you once held accounts that are now closed — their trades still affect your history.',
            'Select **Download CSV** and wait for the download to finish.'] },
  { img: 'guide-4-download.png', title: 'Upload the downloaded CSV',
    lines: ['Open your browser downloads and find the newest **activities-export-YYYY-MM-DD.csv** file.',
            'Drag that file into **DROP CSV EXPORTS HERE** above. If you also have a **holdings-report-YYYY-MM-DD.csv**, upload both together so the app can check current positions against the activity ledger.'] },
];
function exportGuide() {
  const bold = text => {
    const out = [];
    text.split(/\*\*(.+?)\*\*/g).forEach((part, i) => out.push(i % 2 ? h('b', { class: 'amb' }, part) : part));
    return out;
  };
  return panel('HOW TO EXPORT FROM WEALTHSIMPLE', 'activities CSV in four steps · upload it above', null,
    h('div', { class: 'guide' }, EXPORT_STEPS.map((step, i) => h('figure', {},
      h('figcaption', {}, h('span', { class: 'step' }, i + 1), h('span', { class: 'amb' }, step.title),
        h('ul', { class: 'plain' }, step.lines.map(l => h('li', {}, bold(l))))),
      h('img', { src: `/static/img/${step.img}`, alt: step.title, loading: 'lazy' })))),
    h('div', { class: 'body mut' }, 'Exports overlap safely: inside the range an export covers it is treated as the truth, so a row the broker later corrects (a settled trade, an added FX rate) replaces the old version instead of doubling up. Rows outside that range are untouched, so a monthly full-history export is the simplest routine.'));
}

// ---------- import ----------
async function uploadFiles(files) {
  files = files.filter(f => /\.csv$/i.test(f.name) || f.type === 'text/csv');
  if (!files.length) return msg('Choose .csv files');
  const form = new FormData();
  files.slice(0, 10).forEach(f => form.append('files', f, f.name));
  state.imp.busy = true; state.imp.result = null; render();
  const { data } = await api('/api/import/preview', { method: 'POST', body: form });
  state.imp.busy = false;
  if (!data || !data.id) { msg(`IMPORT FAILED · ${data && data.log}`); return render(); }
  state.imp.preview = data; state.imp.force = false;
  msg(data.committable ? `Preview ready: +${data.added} rows` : 'No valid files in upload');
  render();
}
async function commitImport() {
  const P = state.imp.preview; if (!P) return;
  state.imp.busy = true; render();
  const { data } = await api('/api/import/commit', { method: 'POST', json: { id: P.id, force_holdings: state.imp.force, fetch: true } });
  state.imp.busy = false;
  if (!data.ok) { msg(`COMMIT FAILED · ${data.log}`); return render(); }
  state.imp.preview = null; state.imp.result = data;
  await pollStatus(); render();
  if (data.job) await waitForJob(data.job === 'import-fetch' ? 'Imported · fetching prices for new symbols…' : 'Imported · rebuilding…', 'import');
  else if (data.missing_exports && data.missing_exports.includes('activities')) {
    msg(`IMPORT SAVED · upload ${data.missing_exports.join(' and ')} CSV to continue`);
    render();
  } else await load();
}

// ---------- monthly contributions into the equity core ----------
function contributionsPanel() {
  const C = D.contributions;
  if (!C || !C.months.length) return null;
  const n = state.contribMonths === 'ALL' ? C.months.length : Math.min(C.months.length, +state.contribMonths);
  const cut = C.months.length - n;
  const months = C.months.slice(cut);
  const dates = months.map(m => `${m}-01`);
  const colors = ['var(--s1)', 'var(--s2)', 'var(--s3)'];
  const series = Object.entries(C.groups).slice(0, 3).map(([name, vals], i) => ({
    name, short: name.replace(' 500', '').replace(' 100', ''), color: colors[i], values: vals.slice(cut),
  }));
  const P = C.core_pace, trend = P.last3 != null && P.prev3 != null ? P.last3 - P.prev3 : null;
  const stats = h('div', { class: 'stats' },
    stat('CORE BUYS / MONTH', money(P.last6), h('span', {}, 'last 6 months · 3M ', signed(trend), ' vs previous 3M')),
    stat('RUN RATE', money(P.run_rate), 'last 6 months × 12'),
    stat('INVESTED IN CORE', money(P.total), `${C.months.length} months tracked`),
    ...Object.entries(C.group_pace).slice(0, 3).map(([name, p]) => stat(name, money(p.last6), h('span', {}, 'per month · ', signed(p.last3 - p.prev3), ' vs prev 3M'))),
    stat('MONTHS WITHOUT A BUY', `${P.skipped_last6}/6`, P.skipped_last6 ? 'gaps break the habit' : 'bought every month'));
  const ctl = seg(['6', '12', '24', 'ALL'], state.contribMonths, m => { state.contribMonths = m; render(); });
  return h('div', {},
    panel('CORE CONTRIBUTIONS', 'net buys per month (buys minus sells), equivalent tickers grouped: VOO+VFV, QQQ+XQQ, XEQT', ctl,
      stats,
      h('div', { class: 'body' }, lineChart({ dates, series, height: 260, zeroLine: true,
        yfmt: (v, full) => full ? money(v) : v >= 1000 || v <= -1000 ? '$' + nf0.format(Math.round(v / 1000)) + 'K' : money(v) })),
      table([
        { k: 'sym', label: 'TICKER', l: true, fmt: r => h('span', { class: 'amb', raw: true }, r.sym) },
        { k: 'group', label: 'TRACKS', l: true, sm: false },
        { k: 'cad', label: 'NET INVESTED', fmt: r => money(r.cad) },
        { k: 'shares', label: 'NET SHARES', fmt: r => +r.shares.toFixed(2) },
        { k: 'avg_cost', label: 'NET COST/SHARE', sm: false, fmt: r => r.avg_cost == null ? '—' : num(r.avg_cost) },
        { k: 'held', label: 'HELD NOW', fmt: r => +r.held.toFixed(2) },
        { k: 'last', label: 'LAST 6 MO', sort: r => r.monthly.slice(-6).reduce((a, b) => a + b, 0),
          fmt: r => money(r.monthly.slice(-6).reduce((a, b) => a + b, 0)) },
      ], C.tickers, { sortKey: 'cad' })));
}

// ---------- freeze (stop trading) simulation ----------
const FRZ_DEPOSITS = { CASH: 'cash', 'CASH ETF': 'CCAD.TO', XEQT: 'XEQT.TO', VOO: 'VOO', NONE: 'none' };
let frzTimer, frzSeq = 0;
function ensureFreeze() {
  const F = state.frz;
  if (!D) return;
  if (!F.date && !F.trade) {
    const end = new Date(D.price_date); end.setMonth(end.getMonth() - 3);
    F.date = end.toISOString().slice(0, 10);
  }
  if (!F.result) runFreeze();
  if (F.sweepFor !== D.built) {
    F.sweepFor = D.built;
    api('/api/freeze/sweep').then(({ data }) => { if (data.ok) { F.sweep = data; if (state.screen === 'SIM') rerenderKeepScroll(); } });
  }
}
function runFreeze(delay = 250) {
  clearTimeout(frzTimer);
  frzTimer = setTimeout(async () => {
    const F = state.frz, seq = ++frzSeq;
    F.busy = true;
    const body = { deposits: FRZ_DEPOSITS[F.deposits], ...(F.trade ? { trade: F.trade } : { date: F.date }) };
    const { data } = await api('/api/freeze', { method: 'POST', json: body });
    if (seq !== frzSeq) return;
    F.busy = false;
    if (data.ok) { F.result = data; F.err = ''; } else F.err = data.log || 'Freeze failed';
    if (state.screen === 'SIM' && state.simMode === 'FREEZE') rerenderKeepScroll();
  }, delay);
}
function freezeAtDate(d) { const F = state.frz; F.date = d; F.trade = null; runFreeze(0); }
function freezeAtTrade(t) { const F = state.frz; F.trade = t.id; F.date = t.date; runFreeze(0); window.scrollTo({ top: 0, behavior: 'smooth' }); }

function freezeView() {
  const F = state.frz, R = F.result, S = F.sweep;
  const pp = v => v == null ? '—' : `${(v * 100).toFixed(2)}pp`;
  const signedPP = v => signed(v, x => `${(x * 100).toFixed(2)}pp`, 0.00005);
  const depNote = { CASH: 'deposits after the freeze arrive and sit as cash', 'CASH ETF': 'deposits after the freeze buy CCAD, the cash ETF you actually park money in', XEQT: 'deposits after the freeze buy XEQT the same day', VOO: 'deposits after the freeze buy VOO the same day', NONE: 'deposits after the freeze are ignored: compare returns only' }[F.deposits];
  const first = D.series.dates[0], last = D.price_date;
  const dateInput = h('input', { type: 'date', min: first, max: last, value: F.date || '', 'aria-label': 'Freeze date', class: 'dateinput',
    onchange: e => { if (e.target.value) freezeAtDate(e.target.value); } });
  const quick = [['1M', 1], ['3M', 3], ['6M', 6], ['1Y', 12]].map(([k, mo]) => h('button', { onclick: () => { const d = new Date(last); d.setMonth(d.getMonth() - mo); freezeAtDate(d.toISOString().slice(0, 10)); } }, `${k} AGO`));
  const out = [
    panel('FREEZE POINT', R ? (F.trade ? `frozen ${R.label}` : `frozen at the ${R.label}`) : F.err || 'choose a day, or pick a trade below', [
      dateInput, ...quick,
      F.trade ? h('button', { 'aria-pressed': 'true', onclick: () => freezeAtDate(F.date) }, 'TRADE ✕') : null,
    ], h('div', { class: 'body freeze-controls' },
      h('span', { class: 'mut' }, 'MONEY ADDED AFTER:'), ...seg(Object.keys(FRZ_DEPOSITS), F.deposits, m => { F.deposits = m; runFreeze(0); render(); }),
      h('span', { class: 'mut freeze-note' }, depNote))),
  ];
  if (F.err && !R) { out.push(h('div', { class: 'skeleton' }, F.err)); return out; }
  if (!R) { out.push(h('div', { class: 'skeleton' }, 'SIMULATING…')); return out; }

  const H = R.horizons, todate = H[H.length - 1], valueMode = F.deposits !== 'NONE';
  const lastA = R.actual[R.actual.length - 1], lastF = R.frozen[R.frozen.length - 1];
  out.push(h('div', { class: 'stats' + (F.busy ? ' stale' : '') },
    stat('FROZEN ON', R.freeze_date, `${nf0.format(R.trades_skipped)} later trades skipped`),
    stat('VALUE AT FREEZE', money(R.start_value), R.options_closed_at_cost ? `open options closed at cost ${money(R.options_closed_at_cost)}` : 'same starting line for both paths'),
    valueMode ? stat('VALUE TODAY', h('span', {}, money(lastA), h('span', { class: 'mut' }, ' vs '), money(lastF)), 'actual vs frozen') : stat('VALUE TODAY', money(lastA), 'actual (frozen excludes new money)'),
    stat('FROZEN − ACTUAL, $', signed(todate.gain_diff), 'gain since freeze, deposits removed'),
    stat('RETURN SINCE FREEZE', h('span', {}, signedPct(todate.actual), h('span', { class: 'mut' }, ' vs '), signedPct(todate.frozen)), h('span', {}, 'actual vs frozen · ', signedPP(todate.diff)))));

  const verdict = todate.diff > 0.0005 ? h('span', { class: 'warn' }, 'Doing nothing would have been better since then.') : todate.diff < -0.0005 ? h('span', { class: 'up' }, 'Your trading after this point added value.') : 'About even.';
  out.push(h('div', { class: 'row' },
    panel('SHORT VS LONG TERM', 'frozen minus actual, time-weighted return', null,
      barList(H.filter(x => x.end).map(x => ({ label: x.name, value: x.diff, title: `to ${x.end} · actual ${pct(x.actual, 2)} · frozen ${pct(x.frozen, 2)} · ${money(x.gain_diff)}` })), x => `${(x * 100).toFixed(2)}pp`, 0.00005),
      h('div', { class: 'body' }, verdict)),
    panel('HORIZONS', null, null, table([
      { k: 'name', label: 'HORIZON', l: true },
      { k: 'end', label: 'ENDS', sm: false, fmt: r => r.end || h('span', { class: 'mut' }, 'not yet') },
      { k: 'actual', label: 'ACTUAL', fmt: r => r.end ? signedPct(r.actual, 2) : '—' },
      { k: 'frozen', label: 'FROZEN', fmt: r => r.end ? signedPct(r.frozen, 2) : '—' },
      { k: 'diff', label: 'F − A', fmt: r => r.end ? signedPP(r.diff) : '—' },
      { k: 'gain_diff', label: 'F − A $', fmt: r => r.end ? signed(r.gain_diff) : '—' },
    ], H, {}))));

  const i0 = rangeStart(R.dates, state.range);
  const dates = R.dates.slice(i0);
  const rebaseTW = arr => { const b = arr[i0]; return arr.slice(i0).map(v => v / b - 1); };
  const chart = F.chart === 'RETURN'
    ? lineChart({ dates, height: 320, zeroLine: true, yfmt: (v, full) => `${(v * 100).toFixed(full ? 2 : 0)}%`, series: [
        { name: 'ACTUAL', short: 'ACTUAL', color: 'var(--s1)', values: rebaseTW(R.twr_actual) },
        { name: 'FROZEN', short: 'FROZEN', color: 'var(--s2)', values: rebaseTW(R.twr_frozen) },
        { name: 'XEQT', short: 'XEQT', color: 'var(--ref)', width: 1.5, values: rebaseTW(R.bench['XEQT.TO']) },
      ] })
    : lineChart({ dates, height: 320, yfmt: (v, full) => full ? money(v) : v >= 1000 ? '$' + nf0.format(Math.round(v / 1000)) + 'K' : money(v), series: [
        { name: 'ACTUAL', short: 'ACTUAL', color: 'var(--s1)', values: R.actual.slice(i0) },
        { name: 'FROZEN', short: 'FROZEN', color: 'var(--s2)', values: R.frozen.slice(i0) },
        { name: 'NET DEPOSITED', short: 'DEPOSITED', color: 'var(--ref)', width: 1.5, values: R.contrib_actual.slice(i0) },
      ] });
  out.push(panel('SINCE THE FREEZE', F.chart === 'RETURN' ? 'time-weighted return from the freeze day (XEQT for reference)' : valueMode ? 'portfolio value, CAD' : 'value, CAD · frozen line excludes money added later',
    [...seg(['RETURN', 'VALUE'], F.chart, c => { F.chart = c; render(); }), h('span', { style: 'width:10px' }), ...seg(['1M', '3M', '6M', '1Y', 'ALL'], state.range, r => { state.range = r; render(); })],
    h('div', { class: 'body' }, chart)));

  if (S && S.dates.length) {
    const share = arr => { const v = arr.filter(x => x != null); return v.length ? v.filter(x => x > 0).length / v.length : null; };
    out.push(panel('HINDSIGHT MAP', 'freeze on each date (weekly) · above 0 = doing nothing from that date would have beaten what you did · click to freeze there',
      null,
      h('div', { class: 'stats' },
        stat('FREEZING WON · 1M', pct(share(S['1M']), 0), 'of freeze dates'),
        stat('FREEZING WON · 3M', pct(share(S['3M']), 0), 'of freeze dates'),
        stat('FREEZING WON · TO DATE', pct(share(S.to_date), 0), 'of freeze dates'),
        stat('MEDIAN · 3M', pp(median(S['3M'])), 'frozen − actual')),
      h('div', { class: 'body' }, lineChart({ dates: S.dates, height: 260, zeroLine: true, pickLabel: 'CLICK TO FREEZE HERE',
        onPick: i => freezeAtDate(S.dates[i]),
        yfmt: (v, full) => `${(v * 100).toFixed(full ? 2 : 0)}pp`, series: [
          { name: 'NEXT 1 MONTH', short: '1M', color: 'var(--s1)', values: S['1M'] },
          { name: 'NEXT 3 MONTHS', short: '3M', color: 'var(--s2)', values: S['3M'] },
          { name: 'TO DATE', short: 'TO DATE', color: 'var(--s3)', values: S.to_date },
        ] })),
      h('div', { class: 'body mut' }, 'Deposits are ignored so every point compares pure returns. Starts once the portfolio passed $5,000; smaller balances swing too much to compare.')));
  }

  out.push(h('div', { class: 'row', style: 'grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr))' },
    panel('HOLDINGS AT FREEZE', 'left untouched; returns include dividends', null, table([
      { k: 'ticker', label: 'HOLDING', l: true, fmt: r => h('span', { class: 'amb', raw: true }, r.ticker) },
      { k: 'qty', label: 'QTY', sm: false, fmt: r => +(+r.qty).toFixed(4) },
      { k: 'value_then', label: 'THEN', fmt: r => money(r.value_then) },
      { k: 'value_now', label: 'NOW', fmt: r => money(r.value_now) },
      { k: 'ret', label: 'RETURN', fmt: r => r.ret == null ? '—' : signedPct(r.ret) },
      { k: 'actual_qty_now', label: 'YOU HOLD NOW', sm: false, fmt: r => r.actual_qty_now == null ? '—' : +(+r.actual_qty_now).toFixed(4) },
    ], R.holdings, { sortKey: 'value_then' })),
    panel('FREEZE AFTER A TRADE', 'click a trade to stop right after it', [
      h('input', { 'aria-label': 'Symbol filter', placeholder: 'SYMBOL', value: F.sym, class: 'textinput', onchange: e => { F.sym = e.target.value.toUpperCase().trim(); render(); } }),
    ], table([
      { k: 'date', label: 'DATE', l: true, fmt: r => h('span', { class: r.id === F.trade ? 'amb' : '' }, r.date) },
      { k: 'acct', sm: false, label: 'ACCOUNT', l: true },
      { k: 'side', label: 'SIDE', l: true, fmt: r => h('span', { class: r.side === 'BUY' ? 'up' : 'down' }, r.side === 'BUY' ? '▲' : '▼', h('span', { class: 'sm-hide' }, ' ' + r.side)) },
      { k: 'sym', label: 'SYMBOL', l: true, fmt: r => h('span', { class: 'amb', raw: true }, r.sym) },
      { k: 'amt', label: 'AMOUNT', sm: false, fmt: r => num(r.amt) },
    ], F.sym ? D.trades.filter(t => t.sym.trim().startsWith(F.sym)) : D.trades, { sortKey: 'date', max: 1500, onRow: freezeAtTrade }))));
  out.push(h('div', { class: 'mut', style: 'padding:0 4px' }, 'Frozen portfolio: the same shares held untouched with dividends reinvested, cash left as cash (USD still moves with the exchange rate), open options closed at cost, subscription fees still charged, no trades, conversions or transfers.'));
  return out;
}
function median(arr) { const v = arr.filter(x => x != null).sort((a, b) => a - b); return v.length ? v[Math.floor(v.length / 2)] : null; }

// ---------- navigation ----------
const back = [];
function go(screen, push = true) {
  if (push && state.screen !== screen) back.push({ screen: state.screen, sym: state.sym });
  state.screen = screen; render();
  window.scrollTo(0, 0);
  const hash = screen === 'SYM' ? `#SYM/${state.sym.yahoo}` : `#${screen}`;
  if (location.hash !== hash) history.pushState(null, '', hash);
  if (screen === 'SIM') { if (state.simMode === 'FREEZE') ensureFreeze(); else if (!state.simResult) scheduleSim(); }
}
function goBack() {
  if (!back.length) return;
  const p = back.pop(); state.sym = p.sym; go(p.screen, false);
}
function updateVimUI() {
  const b = $('#vimbtn');
  b.textContent = tr(vimMode ? 'EXIT VIM' : 'VIM');
  b.title = tr(vimMode ? 'Exit Vim mode (:q)' : 'Enable Vim keyboard navigation');
  b.setAttribute('aria-pressed', String(vimMode));
  document.body.classList.toggle('vim-mode', vimMode);
}
function setVimMode(enabled) {
  vimMode = Boolean(enabled);
  try { localStorage.setItem('vim-mode', vimMode ? '1' : '0'); } catch {}
  if (!vimMode) document.querySelectorAll('.vim-focus').forEach(el => el.classList.remove('vim-focus'));
  updateVimUI();
  msg(vimMode ? 'VIM MODE · h/j/k/l controls · Enter activates · gg/G edges · i/: command' : 'VIM MODE OFF');
}
const VIM_TARGET_SELECTOR = [
  'button:not([disabled])', 'a[href]', 'select:not([disabled])',
  'input:not([disabled]):not([type="hidden"]):not([type="file"])', 'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');
function vimTargets() {
  return [...new Set([...$('#main').querySelectorAll(VIM_TARGET_SELECTOR)])].filter(el => {
    const box = el.getBoundingClientRect(), style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && !el.closest('[inert]');
  });
}
function moveVimFocus(direction) {
  const targets = vimTargets();
  if (!targets.length) return;
  const current = targets.includes(document.activeElement) ? document.activeElement : null;
  let next;
  if (!current) {
    const ordered = targets.map(el => ({ el, box: el.getBoundingClientRect() }))
      .sort((a, b) => a.box.top - b.box.top || a.box.left - b.box.left);
    next = (direction === 'h' || direction === 'k' ? ordered.at(-1) : ordered[0]).el;
  } else {
    const from = current.getBoundingClientRect();
    const fx = from.left + from.width / 2, fy = from.top + from.height / 2;
    const horizontal = direction === 'h' || direction === 'l';
    const sign = direction === 'h' || direction === 'k' ? -1 : 1;
    const scored = targets.filter(el => el !== current).map(el => {
      const box = el.getBoundingClientRect(), x = box.left + box.width / 2, y = box.top + box.height / 2;
      const primary = sign * (horizontal ? x - fx : y - fy);
      if (primary <= 3) return null;
      const overlaps = horizontal
        ? box.top < from.bottom && box.bottom > from.top
        : box.left < from.right && box.right > from.left;
      const cross = Math.abs(horizontal ? y - fy : x - fx);
      return { el, score: primary + (overlaps ? cross * .15 : cross * 3) };
    }).filter(Boolean).sort((a, b) => a.score - b.score);
    next = scored[0] && scored[0].el;
  }
  if (!next) return;
  document.querySelectorAll('.vim-focus').forEach(el => el.classList.remove('vim-focus'));
  next.classList.add('vim-focus');
  next.focus({ preventScroll: true });
  next.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
}
function render() {
  resizeHooks = [];
  $('#fkeys').replaceChildren(...SCREENS.map(([k, n], i) => h('button', { 'aria-current': String(state.screen === k), onclick: () => go(k), title: n, raw: true }, h('span', { class: 'k' }, i < 9 ? i + 1 : i === 9 ? 0 : '·'), k)),
    h('button', { 'aria-current': String(state.screen === 'HELP'), onclick: () => go('HELP'), title: 'HELP', raw: true }, h('span', { class: 'k' }, '?'), 'HELP'));
  const title = state.screen === 'SYM' ? `${state.sym.yahoo} <EQUITY>` : (SCREENS.find(x => x[0] === state.screen) || [0, state.screen])[1];
  document.title = tr(`${title} · Portfolio Terminal`);
  const keep = [...document.querySelectorAll('#main .scroll')].map(el => el.scrollTop);
  const same = render.last === state.screen; render.last = state.screen;
  if (!D && !NO_DATA_OK.has(state.screen)) state.screen = 'IMP';
  $('#main').replaceChildren(...SCREEN[state.screen]().filter(Boolean));
  if (same) document.querySelectorAll('#main .scroll').forEach((el, i) => { if (keep[i]) el.scrollTop = keep[i]; });
  if (state.auditRefocus && state.screen === 'AUD') {
    state.auditRefocus = false;
    requestAnimationFrame(() => $('.audit-scrub')?.focus({ preventScroll: true }));
  }
}
function runCommand(raw) {
  const c = raw.trim().toUpperCase().replace(/\s*<?GO>?$/, '');
  if (!c) return;
  if (c === 'VIM') return setVimMode(true);
  if (c === ':Q' || c === 'VIM OFF' || c === 'NOVIM') return setVimMode(false);
  const alias = { IMPORT: 'IMP', UPLOAD: 'IMP', PORTFOLIO: 'PORT', PNL: 'PNL', 'P&L': 'PNL', TRADES: 'TRD', ALLOC: 'ALOC', RULES: 'RULE', EVENTS: 'EVT', INCOME: 'INC', AUDIT: 'AUD', '?': 'HELP' };
  const k = alias[c] || c;
  if (SCREEN[k] && k !== 'SYM') { msg(''); return go(k); }
  if (c === 'LANG' || c === '中文' || c === 'ZH' || c === 'EN' || c === 'ENGLISH') { msg(''); return switchLang(c === 'LANG' ? null : c === 'EN' || c === 'ENGLISH' ? 'en' : 'zh'); }
  if (c === 'FETCH' || c === 'REFRESH') return startJob('fetch');
  if (c === 'REBUILD') return startJob('rebuild');
  if (!D) return msg('NO DATA YET — IMPORT YOUR EXPORTS');
  const exact = D.tickers.filter(t => t.yahoo === c);
  const bySym = D.tickers.filter(t => t.sym === c);
  const best = list => list.find(t => t.held) || list.find(t => t.cur === 'USD') || list[0];
  const pick = best(exact) || best(bySym);
  if (pick) { if (new Set(bySym.map(t => t.yahoo)).size > 1 && !exact.length) msg(`${c}: also ${[...new Set(bySym.filter(t => t.yahoo !== pick.yahoo).map(t => t.yahoo))].join(', ')}`); else msg(''); state.sym = pick; return go('SYM'); }
  msg(`UNKNOWN: ${c} — type HELP`);
}

// ---------- chrome ----------
function renderTicker() {
  if (!D) return $('#tick').replaceChildren(h('span', { class: 'warn' }, 'NO DATA · IMPORT YOUR EXPORTS'));
  const S = D.summary;
  $('#tick').replaceChildren(
    h('span', {}, h('span', {}, 'NAV '), h('b', {}, money(S.total))),
    h('span', {}, h('span', {}, 'DAY '), signed(S.day)),
    h('span', {}, h('span', {}, 'GAIN '), signed(S.gain)),
    h('span', {}, h('span', {}, 'USDCAD '), h('b', {}, D.fx.toFixed(4))),
    h('span', {}, h('span', {}, 'PX '), h('b', {}, D.price_date)),
    h('span', {}, h('span', {}, 'EXPORT '), h('b', {}, D.asof)));
}
async function load() {
  const r = await fetch('/data.json', { cache: 'no-store' });
  D = r.ok ? await r.json() : null;
  renderTicker();
  if (!D) { load.done = true; load.wasEmpty = true; return go('IMP', false); }
  if (load.wasEmpty) { load.wasEmpty = false; return go('PORT', false); }
  if (load.done) return render();
  load.done = true;
  routeFromHash();
}
function routeFromHash() {
  const [scr, arg] = decodeURIComponent(location.hash.slice(1)).split('/');
  if (scr === 'SYM' && arg) { if (!state.sym || state.sym.yahoo !== arg || state.screen !== 'SYM') runCommand(arg); }
  else if (SCREEN[scr] && scr !== 'SYM') {
    if (scr === 'SIM' && arg === 'FREEZE') state.simMode = 'FREEZE';
    if (scr === 'SIM' && arg && arg !== 'FREEZE' && D) { state.simMode = 'REMOVE TRADES'; const f = { SPECULATIVE: t => t.cat === 'speculative', AVGDOWN: t => t.avgdown }[arg]; if (f) D.trades.filter(f).forEach(t => state.simSel.add(t.id)); }
    if (state.screen !== scr || !render.last) go(scr, false);
  } else render();
}
window.addEventListener('hashchange', () => { if (load.done) routeFromHash(); });
let ST = null, cooldownUntil = 0;
const ago = iso => { if (!iso) return '—'; const m = Math.round((Date.now() - new Date(iso)) / 60000); return m < 1 ? 'NOW' : m < 60 ? `${m}MIN AGO` : m < 1440 ? `${Math.round(m / 60)}H AGO` : `${Math.round(m / 1440)}D AGO`; };
async function pollStatus() {
  try { const r = await api('/api/status'); ST = r.status === 200 ? r.data : null; }
  catch { ST = null; }
  if (ST) cooldownUntil = Date.now() + ST.cooldown * 1000;
  updateFetchUI();
  return ST;
}
function updateFetchUI() {
  const b = $('#fetch'), rb = $('#rebuild'), info = $('#fetchinfo'), guest = $('#guestbadge'), end = $('#endsession');
  guest.hidden = !(ST && ST.guest);
  end.hidden = !(ST && ST.guest);
  guest.textContent = tr('GUEST · EPHEMERAL');
  guest.title = tr('One browser owns this guest workspace. END SESSION erases its portfolio data; only public market data persists.');
  if (!ST) { b.disabled = true; b.textContent = tr('OFFLINE'); info.textContent = tr('server not reachable'); return; }
  const j = ST.job, cd = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
  const complete = Boolean(ST.exports.activities.rows);
  rb.disabled = j.running || !complete;
  if (j.running) {
    b.disabled = true;
    const p = ST.progress;
    b.textContent = tr(j.kind === 'rebuild' ? 'REBUILDING…' : p ? `FETCHING ${p.requests}/${p.planned ?? '?'}` : `FETCHING… ${Math.round(j.elapsed)}s`);
  } else if (cd > 0) { b.disabled = true; b.textContent = tr(`FETCH ${cd}s`); }
  else if (!complete) { b.disabled = true; b.textContent = tr(ST.exports.activities.rows ? 'FETCH · NEED HOLDINGS' : 'FETCH · NO DATA'); }
  else { b.disabled = false; b.textContent = tr(ST.plan.requests ? `FETCH · ${ST.plan.requests} DUE` : 'FETCH · UP TO DATE'); }
  const last = ST.history[0];
  info.replaceChildren(last ? h('span', {}, `LAST FETCH ${ago(last.started)} · ${last.requests} REQ · ${last.seconds}s`,
    last.rate_limited || last.aborted ? h('span', { class: 'warn' }, ' · RATE LIMITED') : last.errors.length ? h('span', { class: 'warn' }, ` · ${last.errors.length} ERR`) : '') : 'NEVER FETCHED');
}
async function startJob(kind, force = false) {
  if (kind === 'fetch' && force && !confirm(tr(`Force a full re-download of every ticker?\nThat is about ${ST ? ST.plan.tickers.length + 14 : 110} requests to Yahoo.`))) return;
  const { data: j } = await api(`/api/${kind}${force ? '?force=true' : ''}`, { method: 'POST' });
  if (!j.ok) { msg(j.log); return pollStatus(); }
  await waitForJob(kind === 'fetch' ? 'Fetching due market data…' : 'Rebuilding…', kind);
}
async function waitForJob(label, kind) {
  msg(label);
  document.body.style.setProperty('--dim', '1');
  $('#main').style.opacity = .7;
  while (true) {
    await new Promise(res => setTimeout(res, 700));
    const st = await pollStatus();
    if (state.screen === 'DATA') rerenderKeepScroll();
    if (!st || !st.job.running) break;
  }
  $('#main').style.opacity = 1;
  if (ST && ST.job.ok) {
    Object.keys(csvCache).forEach(k => delete csvCache[k]);
    await load();
    const line = (ST.job.log || '').split('\n').find(l => /requests in|total \$/.test(l)) || 'done';
    msg(`${kind.toUpperCase()} OK · ${line}`);
  } else if (ST) msg(`${kind.toUpperCase()} FAILED · ${(ST.job.log || '').split('\n').filter(Boolean).slice(-1)[0] || ''}`);
}
function rerenderKeepScroll() { const y = window.scrollY; render(); window.scrollTo(0, y); }
$('#cmdform').addEventListener('submit', e => { e.preventDefault(); const i = $('#cmd'); runCommand(i.value); i.value = ''; });
$('#fetch').addEventListener('click', () => startJob('fetch'));
$('#rebuild').addEventListener('click', () => startJob('rebuild'));
$('#fetchinfo').addEventListener('click', () => go('DATA'));
$('#vimbtn').addEventListener('click', () => setVimMode(!vimMode));
$('#endsession').addEventListener('click', async () => {
  if (!confirm(tr('End this guest session and permanently erase all uploaded portfolio data? Public market prices will remain cached.'))) return;
  const { data } = await api('/api/session/end', { method: 'POST' });
  if (!data.ok) return msg(data.log || 'Could not end guest session');
  location.replace('/');
});
setInterval(() => { if (cooldownUntil > Date.now()) updateFetchUI(); }, 1000);
setInterval(() => { if (!ST || !ST.job.running) pollStatus().then(() => state.screen === 'DATA' && rerenderKeepScroll()); }, 60000);
let vimGAt = 0;
document.addEventListener('keydown', e => {
  const active = document.activeElement;
  const typing = active && (active.id === 'cmd' || active.matches('textarea, input:not([type="checkbox"]):not([type="radio"]):not([type="button"]):not([type="submit"])'));
  if (e.key === 'Escape') { if (typing) document.activeElement.blur(); else goBack(); return; }
  const auditSlider = active && active.classList.contains('audit-scrub');
  if (state.screen === 'AUD' && D && D.audit && (!typing || auditSlider) && !e.metaKey && !e.altKey && !e.ctrlKey) {
    const arrowBack = e.key === 'ArrowLeft';
    const arrowForward = e.key === 'ArrowRight';
    const vimBack = vimMode && e.key === 'H';
    const vimForward = vimMode && e.key === 'L';
    if (arrowBack || arrowForward || vimBack || vimForward) {
      e.preventDefault();
      const amount = (arrowBack || arrowForward) && e.shiftKey ? 5 : 1;
      setAuditDay(state.auditDay + (arrowBack || vimBack ? -amount : amount), false, auditSlider);
      return;
    }
  }
  if (typing || e.metaKey || e.altKey) return;
  if (vimMode) {
    const halfPage = Math.max(160, Math.round(innerHeight * .5));
    if (e.ctrlKey && (e.key === 'd' || e.key === 'u')) { e.preventDefault(); scrollBy({ top: e.key === 'd' ? halfPage : -halfPage, behavior: 'smooth' }); return; }
    if (e.ctrlKey) return;
    if (/^[hjkl]$/.test(e.key)) { e.preventDefault(); moveVimFocus(e.key); return; }
    if (e.key === 'b') { e.preventDefault(); goBack(); return; }
    if (e.key === 'G') { e.preventDefault(); scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' }); vimGAt = 0; return; }
    if (e.key === 'g') { e.preventDefault(); const now = Date.now(); if (now - vimGAt < 700) { scrollTo({ top: 0, behavior: 'smooth' }); vimGAt = 0; } else vimGAt = now; return; }
    vimGAt = 0;
    if (e.key === ':' || e.key === '/' || e.key === 'i') { e.preventDefault(); const input = $('#cmd'); input.value = e.key === ':' ? ':' : ''; input.focus(); input.setSelectionRange(input.value.length, input.value.length); return; }
  }
  if (e.ctrlKey) return;
  if (e.key === '/') { e.preventDefault(); $('#cmd').focus(); return; }
  if (e.key === '?') return go('HELP');
  if (e.key === '0' && SCREENS[9]) return go(SCREENS[9][0]);
  const n = +e.key; if (n >= 1 && n <= 9) return go(SCREENS[n - 1][0]);
  if (!vimMode && /^[a-z]$/i.test(e.key)) { $('#cmd').focus(); }   // start typing a command anywhere
});
setInterval(() => { $('#clock').textContent = new Date().toLocaleString('en-CA', { hour12: false }).replace(',', ''); }, 1000);
pollStatus();
load().catch(e => { $('#main').replaceChildren(h('div', { class: 'skeleton' }, `COULD NOT LOAD DATA (${e.message})`)); });
function applyStaticText() {
  const narrow = matchMedia('(max-width: 760px)').matches;
  $('#cmd').placeholder = narrow ? tr('Command or ticker…') : 'PORT · PERF · PNL · TRD · ALOC · RULE · EVT · INC · AUD · SIM · DATA · IMPORT · ' + (LANG === 'zh' ? '或输入代码（NVDA、T.TO）· HELP · LANG' : 'or a ticker (NVDA, T.TO) · HELP · LANG');
  $('#rebuild').textContent = tr('REBUILD');
  $('#rebuild').title = tr('Recompute from exports and cached prices, no network (REBUILD <GO>)');
  $('#fetch').title = tr('Fetch due market data, then rebuild (FETCH <GO>)');
  $('#fetchinfo').title = tr('Open DATA screen');
  $('#langbtn').textContent = LANG === 'zh' ? 'EN' : '中文';
  $('#langbtn').title = tr('Language');
  updateVimUI();
}
function switchLang(lang) {
  setLang(lang || (LANG === 'zh' ? 'en' : 'zh'));
  applyStaticText();
  if (D) renderTicker(); else if (load.done) renderTicker();
  updateFetchUI();
  if (load.done) rerenderKeepScroll();
}
$('#langbtn').addEventListener('click', () => switchLang());
applyStaticText();

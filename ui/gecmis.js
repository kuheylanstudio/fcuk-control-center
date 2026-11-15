/* FCUK Control Center - Gecmis sayfasi: son 1 saatin sicaklik / guc / fan grafigi, kisilma isaretleri,
   CSV disa aktarma, kalici gunluk kayit ve pil asinma gecmisi.
   Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.

   Motor bu betigi sayfalar.js'ten sonra index.html'in sonuna ekler. Sayfa gorunurken 5 sn'de bir /api/history
   okunur; gorunmezken hicbir istek yapilmaz. */
(() => {
'use strict';
const I = window.I18N || {};
const LOC = I.locale || 'tr-TR';
const T = (k, v) => { let s = I[k] != null ? I[k] : k; if (v) s = s.replace(/\{(\w+)\}/g, (m, n) => (n in v ? v[n] : m)); return s; };
const F = (v, d = 0) => v == null || Number.isNaN(+v) ? '–' : Number(v).toLocaleString(LOC, { minimumFractionDigits: d, maximumFractionDigits: d });
const $ = (s, r = document) => r.querySelector(s);
const E = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
async function api(path, body) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || 'HTTP ' + r.status); }
  return path.includes('.csv') ? r.text() : r.json();
}
function toast(text, ok) {
  const b = $('#banner'); if (!b) return;
  b.textContent = text; b.classList.toggle('info', !!ok); b.classList.remove('closed');
  clearTimeout(toast.t); if (ok) toast.t = setTimeout(() => b.classList.add('closed'), 3000);
}

const css = E('style');
css.textContent = `
.hist-bar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:var(--s-3)}
.hist-range{display:flex;gap:6px}
.hist-range button[aria-pressed=true]{border-color:var(--live-ink);color:var(--text-hi)}
.chart canvas{display:block;width:100%;height:150px}
.chart .readout{min-height:18px;color:var(--text-2);font-size:var(--fs-2);font-variant-numeric:tabular-nums}
.legend{display:flex;flex-wrap:wrap;gap:var(--s-3);color:var(--text-2);font-size:var(--fs-2)}
.legend i{display:inline-block;width:14px;height:3px;margin-right:6px;vertical-align:middle;border-radius:2px}
.legend i.zone{height:10px;width:10px;opacity:.35}
.hist-stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:var(--s-3)}
.hist-stats .kv{flex-direction:column;justify-content:flex-start;gap:4px}
.hist-stats .kv b{text-align:left;font:600 var(--fs-4)/1.2 var(--f-display);color:var(--text-hi);font-variant-numeric:tabular-nums}
.hist-tiles{display:grid;gap:var(--s-3)}
`;
document.head.append(css);

/* ---------- menu dugmesi ve sayfa ---------- */
const rail = $('.rail'), anchor = $('.rail .nav[data-view="ayarlar"]'), shell = $('.shell');
if (!rail || !shell) return;
const ID = 'gecmis';
const nav = E('button', 'nav'); nav.type = 'button'; nav.dataset.view = ID;
nav.append(E('span', '', T('nav.gecmis')), E('small', '', T('nav.gecmis.sub')));
nav.addEventListener('click', () => {
  document.querySelectorAll('.nav').forEach(b => b.setAttribute('aria-current', b.dataset.view === ID ? 'page' : 'false'));
  document.querySelectorAll('.view').forEach(v => { v.hidden = v.id !== 'v-' + ID; });
  try { localStorage.setItem('cc.view', ID); } catch (e) { /* depolama yok */ }
});
rail.insertBefore(nav, anchor || rail.querySelector('.foot'));
const view = E('section', 'view'); view.id = 'v-' + ID; view.hidden = true; view.setAttribute('aria-label', T('nav.gecmis'));
const page = E('div', 'page'); view.append(page); shell.append(view);

let minutes = 60, data = null, bat = null, built = false, hover = null;
// [olcum, renk belirteci, kesikli, etiket]
const SERIES = {
  temp: [['cpu_temp', '--live-ink', false, 'hist.cpuTemp'], ['gpu_temp', '--text-2', true, 'hist.gpuTemp']],
  power: [['cpu_power', '--live-ink', false, 'hist.cpuPower'], ['gpu_power', '--text-2', true, 'hist.gpuPower']],
  fan: [['cpu_rpm', '--live-ink', false, 'hist.cpuFan'], ['gpu_rpm', '--text-2', true, 'hist.gpuFan']],
};
const UNIT = { temp: '°C', power: ' W', fan: ' rpm' };
const profName = id => id ? T('prof.' + id) : T('chip.noProfile');

function legend(kind) {
  const d = E('div', 'legend');
  for (const [, color, dash, key] of SERIES[kind]) {
    const s = E('span'); const i = E('i');
    i.style.background = dash ? `repeating-linear-gradient(90deg,${cssVar(color)} 0 4px,transparent 4px 7px)` : cssVar(color);
    s.append(i, document.createTextNode(T(key))); d.append(s);
  }
  if (kind === 'temp') {
    for (const [c, key] of [['--danger', 'hist.thermal'], ['--warn', 'hist.power']]) {
      const s = E('span'); const i = E('i', 'zone'); i.style.background = cssVar(c); s.append(i, document.createTextNode(T(key))); d.append(s);
    }
  }
  return d;
}
function chartTile(kind) {
  const t = E('article', 'tile');
  t.append(E('span', 'lbl', T('hist.c.' + kind)), legend(kind));
  const c = E('div', 'chart');
  const cv = E('canvas'); cv.id = 'histC-' + kind; cv.setAttribute('role', 'img'); cv.setAttribute('aria-label', T('hist.c.' + kind));
  const ro = E('div', 'readout'); ro.id = 'histR-' + kind; ro.setAttribute('aria-live', 'off');
  cv.addEventListener('mousemove', e => { const r = cv.getBoundingClientRect(); hover = e.clientX - r.left; drawAll(); });
  cv.addEventListener('mouseleave', () => { hover = null; drawAll(); });
  c.append(cv, ro); t.append(c);
  return t;
}
const stat = (label, id) => { const d = E('div', 'kv', label); const b = E('b', '', '–'); b.id = id; d.append(b); return d; };

function build() {
  page.textContent = '';
  const h = E('header', 'page-head');
  h.append(E('h2', '', T('hist.title')), E('p', '', T('hist.intro')));
  page.append(h);

  const bar = E('div', 'hist-bar');
  const rg = E('div', 'hist-range'); rg.setAttribute('role', 'group'); rg.setAttribute('aria-label', T('hist.range'));
  for (const m of [5, 15, 30, 60]) {
    const b = E('button', 'btn', T('hist.min', { n: m })); b.type = 'button'; b.dataset.min = m;
    b.setAttribute('aria-pressed', m === minutes ? 'true' : 'false');
    b.addEventListener('click', () => {
      minutes = m;
      rg.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', +x.dataset.min === m ? 'true' : 'false'));
      load();
    });
    rg.append(b);
  }
  const exp = E('button', 'btn solid', T('hist.export')); exp.type = 'button'; exp.addEventListener('click', exportCsv);
  bar.append(rg, exp);
  page.append(bar);

  const stats = E('article', 'tile');
  stats.append(E('span', 'lbl', T('hist.summary')));
  const g = E('div', 'hist-stats');
  g.append(stat(T('hist.cpuMax'), 'hsCpu'), stat(T('hist.gpuMax'), 'hsGpu'), stat(T('hist.cpuPowAvg'), 'hsCpuW'),
    stat(T('hist.gpuPowAvg'), 'hsGpuW'), stat(T('hist.thermalTime'), 'hsTh'), stat(T('hist.powerTime'), 'hsPw'));
  stats.append(g);
  page.append(stats);

  const tiles = E('div', 'hist-tiles');
  tiles.append(chartTile('temp'), chartTile('power'), chartTile('fan'));
  page.append(tiles);

  const rec = E('article', 'tile form');
  rec.append(E('span', 'lbl', T('hist.record')));
  const sw = E('label', 'switch');
  const inp = E('input'); inp.type = 'checkbox'; inp.id = 'histLog';
  inp.addEventListener('change', async () => {
    try { await api('/api/rules', { log_csv: inp.checked }); toast(T(inp.checked ? 'hist.logOn' : 'hist.logOff'), true); load(); }
    catch (e) { inp.checked = !inp.checked; toast(T('perf.ruleFail', { err: e.message })); }
  });
  const tr = E('span', 'track'); tr.setAttribute('aria-hidden', 'true');
  sw.append(inp, tr, E('span', '', T('hist.logEnable')));
  const files = E('p', 'hint'); files.id = 'histFiles';
  rec.append(sw, E('p', 'hint', T('hist.logHint')), files);
  page.append(rec);

  const bt = E('article', 'tile'); bt.id = 'histBat';
  page.append(bt);
  built = true;
}

/* ---------- cizim ---------- */
function draw(kind) {
  const cv = document.getElementById('histC-' + kind);
  if (!cv || !cv.offsetWidth || !data) return;
  const dpr = devicePixelRatio || 1, w = cv.offsetWidth, h = cv.offsetHeight;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  const ts = data.t, n = ts.length;
  const pad = { l: 34, r: 6, t: 6, b: 16 };
  const now = Date.now() / 1000, t0 = now - minutes * 60;
  const X = t => pad.l + (t - t0) / (now - t0) * (w - pad.l - pad.r);
  let lo = Infinity, hi = -Infinity;
  for (const [k] of SERIES[kind]) for (const v of data[k]) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  if (!isFinite(lo)) {  // bu olcum bu bilgisayarda yok (or. fan devri okunamiyor)
    g.fillStyle = cssVar('--text-3'); g.font = '12px "Segoe UI", sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(T('ovl.noData'), w / 2, h / 2);
    return;
  }
  if (kind === 'temp') { lo = Math.min(lo, 30); hi = Math.max(hi, 90); } else { lo = 0; hi = hi * 1.1 || 1; }
  const Y = v => h - pad.b - (v - lo) / (hi - lo || 1) * (h - pad.t - pad.b);
  // kisilma bolgeleri
  const zone = { thermal: cssVar('--danger'), power: cssVar('--warn') };
  g.globalAlpha = 0.16;
  for (let i = 0; i < n; i++) {
    const k = data.throttle[i]; if (!k) continue;
    const x0 = X(i ? ts[i - 1] : ts[i] - 1), x1 = X(ts[i]);
    g.fillStyle = zone[k]; g.fillRect(x0, pad.t, Math.max(1, x1 - x0), h - pad.t - pad.b);
  }
  g.globalAlpha = 1;
  // izgara ve eksenler
  g.strokeStyle = cssVar('--line'); g.fillStyle = cssVar('--text-3'); g.lineWidth = 1;
  g.font = '11px "Segoe UI", sans-serif'; g.textAlign = 'right'; g.textBaseline = 'middle';
  for (let i = 0; i <= 3; i++) {
    const v = lo + (hi - lo) * i / 3, y = Math.round(Y(v)) + .5;
    g.beginPath(); g.moveTo(pad.l, y); g.lineTo(w - pad.r, y); g.stroke();
    g.fillText(F(v), pad.l - 4, y);
  }
  g.textAlign = 'center'; g.textBaseline = 'top';
  for (let i = 0; i <= 4; i++) {
    const t = t0 + (now - t0) * i / 4;
    const lbl = new Date(t * 1000).toLocaleTimeString(LOC, { hour: '2-digit', minute: '2-digit' });
    g.fillText(lbl, Math.min(Math.max(X(t), pad.l + 14), w - 18), h - pad.b + 3);
  }
  // profil / uygulama degisimleri (etiket yalnizca sicaklik grafiginde)
  g.setLineDash([2, 3]); g.strokeStyle = cssVar('--text-3'); g.textAlign = 'left';
  for (let i = 1; i < n; i++) {
    if (data.profile[i] === data.profile[i - 1] && data.app[i] === data.app[i - 1]) continue;
    const x = Math.round(X(ts[i])) + .5;
    g.beginPath(); g.moveTo(x, pad.t); g.lineTo(x, h - pad.b); g.stroke();
    if (kind === 'temp') g.fillText(data.app[i] || profName(data.profile[i]), x + 3, pad.t);
  }
  g.setLineDash([]);
  // seriler
  for (const [k, color, dash] of SERIES[kind]) {
    g.beginPath(); let on = false;
    for (let i = 0; i < n; i++) {
      const v = data[k][i];
      if (v == null) { on = false; continue; }
      if (on) g.lineTo(X(ts[i]), Y(v)); else g.moveTo(X(ts[i]), Y(v));
      on = true;
    }
    g.setLineDash(dash ? [5, 3] : []); g.strokeStyle = cssVar(color); g.lineWidth = 1.6; g.stroke();
  }
  g.setLineDash([]);
  // imlec ve okuma satiri
  const ro = document.getElementById('histR-' + kind);
  if (hover != null && n) {
    const t = t0 + (hover - pad.l) / (w - pad.l - pad.r) * (now - t0);
    let best = 0;
    for (let i = 1; i < n; i++) if (Math.abs(ts[i] - t) < Math.abs(ts[best] - t)) best = i;
    const x = Math.round(X(ts[best])) + .5;
    g.strokeStyle = cssVar('--text-2'); g.beginPath(); g.moveTo(x, pad.t); g.lineTo(x, h - pad.b); g.stroke();
    const parts = [new Date(ts[best] * 1000).toLocaleTimeString(LOC)];
    for (const [k, , , key] of SERIES[kind]) {
      if (data[k][best] != null) parts.push(T(key) + ' ' + F(data[k][best], kind === 'power' ? 1 : 0) + UNIT[kind]);
    }
    if (data.throttle[best]) parts.push(T('hist.' + data.throttle[best]));
    if (data.app[best]) parts.push(data.app[best]);
    if (ro) ro.textContent = parts.join(' · ');
  } else if (ro) ro.textContent = '';
}
function drawAll() { for (const k of Object.keys(SERIES)) draw(k); }

/* ---------- veri ---------- */
const secs = s => s == null ? '–' : s < 60 ? T('hist.sec', { n: s }) : T('hist.minSec', { m: Math.floor(s / 60), s: s % 60 });
function paint(r) {
  data = r.series;
  const s = r.summary || {};
  const mx = (o, u) => o ? F(o.max) + u : '–';
  const av = (o, u) => o ? F(o.avg, 1) + u : '–';
  const set = (id, v) => { const n = document.getElementById(id); if (n && n.textContent !== v) n.textContent = v; };
  set('hsCpu', mx(s.cpu_temp, '°C')); set('hsGpu', mx(s.gpu_temp, '°C'));
  set('hsCpuW', av(s.cpu_power, ' W')); set('hsGpuW', av(s.gpu_power, ' W'));
  set('hsTh', secs(s.thermal_s)); set('hsPw', secs(s.power_s));
  const lg = document.getElementById('histLog'); if (lg) lg.checked = !!r.log_csv;
  set('histFiles', r.log_csv ? T('hist.files', { folder: r.folder, n: (r.files || []).length }) : '');
  drawAll();
}
function paintBattery() {
  const box = document.getElementById('histBat'); if (!box) return;
  box.textContent = '';
  box.append(E('span', 'lbl', T('bat.title')));
  const rows = (bat && bat.rows) || [];
  if (!rows.length) { box.append(E('p', 'hint', T('bat.none'))); return; }
  const last = rows[rows.length - 1];
  const g = E('div', 'hist-stats');
  const kv = (l, v) => { const d = E('div', 'kv', l); d.append(E('b', '', v)); return d; };
  g.append(kv(T('bat.health'), F(bat.health, 1) + ' %'), kv(T('bat.full'), F(last.full_wh, 1) + ' Wh'),
    kv(T('bat.design'), F(last.design_wh, 1) + ' Wh'), kv(T('bat.cycles'), last.cycles ? F(last.cycles) : '–'),
    kv(T('bat.loss'), bat.loss_per_year != null ? T('bat.lossVal', { v: F(bat.loss_per_year, 1) }) : T('bat.lossWait')),
    kv(T('bat.since'), new Date(rows[0].date + 'T12:00:00').toLocaleDateString(LOC)));
  box.append(g);
  if (rows.length >= 2) {
    const cv = E('canvas'); cv.style.cssText = 'display:block;width:100%;height:90px';
    cv.setAttribute('role', 'img'); cv.setAttribute('aria-label', T('bat.chart'));
    box.append(cv);
    requestAnimationFrame(() => {
      const dpr = devicePixelRatio || 1, w = cv.offsetWidth, h = cv.offsetHeight; if (!w) return;
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
      const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0);
      const vals = rows.map(r => r.full_wh * 100 / r.design_wh);
      const lo = Math.min(...vals, 60), hi = Math.max(...vals, 100);
      const X = i => 4 + i / (rows.length - 1) * (w - 8), Y = v => h - 4 - (v - lo) / (hi - lo || 1) * (h - 8);
      c.strokeStyle = cssVar('--line'); c.beginPath(); c.moveTo(0, Math.round(Y(100)) + .5); c.lineTo(w, Math.round(Y(100)) + .5); c.stroke();
      c.beginPath(); vals.forEach((v, i) => (i ? c.lineTo(X(i), Y(v)) : c.moveTo(X(i), Y(v))));
      c.strokeStyle = cssVar('--live-ink'); c.lineWidth = 1.6; c.stroke();
    });
  }
  box.append(E('p', 'hint', T('bat.hint')));
}
async function load() {
  if (!built) build();
  try { paint(await api('/api/history?min=' + minutes)); } catch (e) { /* motor yeniden basliyor */ }
}
async function loadBattery() {
  try { bat = await api('/api/battery'); } catch (e) { bat = null; }
  paintBattery();
}
async function exportCsv() {
  try {
    const text = await api('/api/history.csv?min=' + minutes);
    const d = new Date(), p = x => String(x).padStart(2, '0');
    const name = `fcuk-gecmis-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}.csv`;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.kaydet) {
      const path = await window.pywebview.api.kaydet(name, text.replace(/^﻿/, ''));
      if (path) toast(T('hist.saved', { path }), true);
    } else {  // Edge --app yedek penceresi: tarayici indirmesi
      const a = E('a'); a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' })); a.download = name;
      document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    }
  } catch (e) { toast(T('hist.exportFail', { err: e.message })); }
}

let timer = 0, wasShown = false;
function onShow() {
  const shown = !view.hidden;
  if (shown && !wasShown) { load(); loadBattery(); clearInterval(timer); timer = setInterval(load, 5000); }
  if (!shown && wasShown) clearInterval(timer);
  wasShown = shown;
}
new MutationObserver(onShow).observe(view, { attributes: true, attributeFilter: ['hidden'] });
addEventListener('resize', () => { if (!view.hidden) drawAll(); });
onShow();
})();

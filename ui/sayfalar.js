/* FCUK Control Center - Donanim, NVIDIA ve Islemci sayfalari.
   Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.

   Motor bu betigi index.html'in sonuna ekler. Betik kendi menu dugmelerini ve sayfalarini kurar; ana
   betigin show() islevi tum .view ve .nav ogelerini her tiklamada yeniden taradigi icin bu sayfalar
   ondan bagimsiz calisir. Gorunur sayfa varken saniyede bir /api/now okunur, yoksa hicbir sey yapilmaz. */
(() => {
'use strict';
const I = window.I18N || {};
const LOC = I.locale || 'tr-TR';
const T = (k, v) => { let s = I[k] != null ? I[k] : k; if (v) s = s.replace(/\{(\w+)\}/g, (m, n) => (n in v ? v[n] : m)); return s; };
const F = (v, d = 0) => v == null || v === '' || Number.isNaN(+v) ? '–' : Number(v).toLocaleString(LOC, { minimumFractionDigits: d, maximumFractionDigits: d });
const P = v => v == null ? '–' : T('fmt.pct', { v: F(v) });
const $ = (s, r = document) => r.querySelector(s);
const E = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
async function api(path, body) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || 'HTTP ' + r.status);
  return j;
}
function toast(text, ok) {  // ana betigin bildirim seridini kullanir
  const b = $('#banner'); if (!b) return;
  b.textContent = text; b.classList.toggle('info', !!ok); b.classList.remove('closed');
  clearTimeout(toast.t); if (ok) toast.t = setTimeout(() => b.classList.add('closed'), 3000);
}

/* ---------- ek stil: yalnizca mevcut belirtecler ---------- */
const css = E('style');
css.textContent = `
.hw-name{font:600 var(--fs-4)/1.25 var(--f-display);color:var(--text-hi);overflow-wrap:anywhere}
.hw-sub{color:var(--text-3);font-size:var(--fs-2)}
.hw-list{display:grid;gap:var(--s-3)}
.hw-item{display:grid;gap:var(--s-2);padding-top:var(--s-3);border-top:1px solid var(--line)}
.hw-item:first-child{padding-top:0;border-top:0}
.kv b.ok{color:var(--live-ink)} .kv b.warn{color:var(--warn)} .kv b.bad{color:var(--danger)}
.tiles.wide2{grid-template-columns:repeat(auto-fill,minmax(340px,1fr))}
.ctl{display:grid;grid-template-columns:minmax(0,1fr);gap:var(--s-2);align-content:start}
.ctl .row{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s-2);min-width:0}
.ctl select{flex:1 1 13em;min-width:0;width:100%}
.ctl .row .btn{flex:none}
.ctl .tag{font:600 var(--fs-1)/1 var(--f-display);letter-spacing:.1em;text-transform:uppercase;color:var(--live-ink)}
`;
document.head.append(css);

/* ---------- menu ve sayfalar ---------- */
// Sekmeler ana betigin gezinmesine (window.ccNav) eklenir: Donanim "Izleme", Islemci ve NVIDIA "Performans" altinda.
const PAGES = [['donanim', 'nav.donanim'], ['islemci', 'nav.islemci'], ['nvidia', 'nav.nvidia']];
const shell = $('.shell');
if (!shell || !window.ccNav) return;
const views = {};
for (const [id, key] of PAGES) views[id] = window.ccNav.add(id, key);
const visible = () => PAGES.map(p => p[0]).find(id => !document.getElementById('v-' + id).hidden);

let hw = null, nv = null, cpu = null, now = {};
const built = {};
function head(page, key) {
  const h = E('header', 'page-head');
  h.append(E('h2', '', T(key + '.title')), E('p', '', T(key + '.intro')));
  page.append(h);
}
const kv = (label, id, cls) => { const d = E('div', 'kv', label); const b = E('b', cls || '', '–'); if (id) b.id = id; d.append(b); return d; };
const set = (id, txt, cls) => { const n = document.getElementById(id); if (!n) return; if (n.textContent !== txt) n.textContent = txt; if (cls !== undefined) n.className = cls; };
const tile = label => { const t = E('article', 'tile'); t.append(E('span', 'lbl', label)); return t; };
const kvs = (...rows) => { const d = E('div', 'kvs'); d.append(...rows); return d; };
const fill = (box, vals) => box.querySelectorAll('.kv b').forEach((b, i) => { if (i < vals.length) b.textContent = vals[i] == null || vals[i] === '' ? '–' : vals[i]; });
const tempCls = (t, warn = 80, hot = 90) => t == null ? '' : t >= hot ? 'bad' : t >= warn ? 'warn' : '';
const mbs = v => v == null ? '–' : F(v, v < 10 ? 1 : 0) + ' MB/s';
const kbs = v => v == null ? '–' : v >= 1024 ? F(v / 1024, 1) + ' MB/s' : F(v) + ' KB/s';
const cpuSub = c => [c.vendor, c.arch, c.gen ? T('hw.genN', { v: c.gen }) : c.series, c.segment ? T('seg.' + c.segment) : ''].filter(Boolean).join(' · ');

/* ================================================================ DONANIM */
function buildHardware() {
  const page = views.donanim; page.textContent = ''; head(page, 'hw');
  if (!hw || !hw.ready) {
    page.append(E('p', 'hint', T('hw.scanning')));
    clearTimeout(built.hwRetry); built.hwRetry = setTimeout(loadHardware, 2000);
    return;
  }
  const g = E('div', 'tiles wide2');
  const sys = hw.system || {}, c = hw.cpu || {};

  const ts = tile(T('hw.system'));
  ts.append(E('div', 'hw-name', [sys.maker, sys.model].filter(Boolean).join(' ') || '–'),
    kvs(kv(T('hw.board')), kv(T('hw.bios')), kv(T('hw.os')), kv(T('hw.boot'))));
  fill(ts, [sys.board, [sys.bios, sys.bios_date].filter(Boolean).join(' · '),
    sys.os ? sys.os + (sys.os_build ? ' · ' + T('hw.build', { v: sys.os_build }) : '') : '', sys.boot]);
  ts.querySelectorAll('.kv b').forEach(b => { b.style.whiteSpace = 'normal'; b.style.textAlign = 'right'; });
  g.append(ts);

  const tc = tile(T('hw.cpu'));
  tc.append(E('div', 'hw-name', c.name || '–'), E('div', 'hw-sub', cpuSub(c)),
    kvs(kv(T('hw.cores')), kv(T('hw.threads')), kv(T('hw.base')), kv(T('hw.cache')),
      kv(T('hw.temp'), 'hwCpuT'), kv(T('hw.power'), 'hwCpuW'), kv(T('hw.load'), 'hwCpuL'), kv(T('hw.fastest'), 'hwCpuM')));
  fill(tc, [c.hybrid ? T('hw.coresPE', { p: c.p_cores, e: c.e_cores }) : F(c.cores), F(c.threads),
    c.base_mhz ? F(c.base_mhz) + ' MHz' : '', c.l3_kb ? 'L2 ' + F(c.l2_kb / 1024, 1) + ' · L3 ' + F(c.l3_kb / 1024) + ' MB' : '']);
  g.append(tc);

  const tg = tile(T('hw.gpus')); const gl = E('div', 'hw-list');
  for (const x of hw.gpus || []) {
    const it = E('div', 'hw-item'), nvd = x.vendor === 'NVIDIA', pre = nvd ? 'hwNv' : 'hwIg';
    it.append(E('div', 'hw-name', x.name),
      E('div', 'hw-sub', [x.vendor, nvd ? '' : T('hw.integrated'), x.res, x.hz ? x.hz + ' Hz' : ''].filter(Boolean).join(' · ')),
      kvs(kv(T('hw.driver')), kv(T('hw.load'), pre + 'L'),
        ...(nvd ? [kv(T('hw.state'), 'hwNvS'), kv(T('hw.temp'), 'hwNvT'), kv(T('hw.clock'), 'hwNvC'), kv(T('hw.power'), 'hwNvW')] : [])));
    fill(it, [[x.nv_driver, x.driver_date || x.driver].filter(Boolean).join(' · ')]);
    gl.append(it);
  }
  tg.append(gl); g.append(tg);

  const m = hw.memory || {}, mods = m.modules || [], first = mods[0] || {};
  const tm = tile(T('hw.memory'));
  tm.append(E('div', 'hw-name', F(m.total_gb) + ' GB ' + [first.type, first.speed ? F(first.speed) + ' MT/s' : ''].filter(Boolean).join(' ')),
    E('div', 'hw-sub', [T(m.channels >= 2 ? 'hw.dual' : 'hw.single'), T('hw.slotsUsed', { u: mods.length, n: m.slots || mods.length }),
      m.max_gb ? T('hw.maxRam', { v: F(m.max_gb) }) : ''].filter(Boolean).join(' · ')),
    kvs(kv(T('hw.used'), 'hwRam')));
  const ml = E('div', 'hw-list');
  for (const x of mods) {
    const it = E('div', 'hw-item');
    it.append(E('div', 'hw-sub', x.slot), kvs(kv(T('hw.module')), kv(T('hw.speed'))),
      E('div', 'hw-sub', [x.maker, x.part, x.volt ? F(x.volt, 2) + ' V' : ''].filter(Boolean).join(' · ')));
    fill(it, [[F(x.gb) + ' GB', x.type, x.form].filter(Boolean).join(' '), x.speed ? F(x.speed) + ' MT/s' : '']);
    ml.append(it);
  }
  tm.append(ml); g.append(tm);

  const td = tile(T('hw.disks')); const dl = E('div', 'hw-list');
  for (const d of hw.disks || []) {
    const it = E('div', 'hw-item'), id = 'hwD' + d.id;
    it.append(E('div', 'hw-name', d.name || '–'),
      E('div', 'hw-sub', [d.bus, d.media, d.gb ? F(d.gb) + ' GB' : '', d.firmware].filter(Boolean).join(' · ')),
      kvs(kv(T('hw.health'), id + 'H'), kv(T('hw.temp'), id + 'T'), kv(T('hw.life'), id + 'L'), kv(T('hw.written'), id + 'W'),
        kv(T('hw.hours'), id + 'O'), kv(T('hw.unsafe'), id + 'U'), kv(T('hw.rw'), id + 'R'), kv(T('hw.busy'), id + 'B')));
    for (const v of d.volumes || []) {
      const row = E('div', 'kv', v.letter + ':' + (v.label ? ' ' + v.label : ''));
      row.append(E('b', '', T('hw.freeOf', { f: F(v.free_gb), t: F(v.gb) })));
      const mt = E('div', 'meter'); const i = E('i'); i.style.setProperty('--v', v.gb ? Math.min(1, (v.gb - v.free_gb) / v.gb) : 0); mt.append(i);
      it.append(row, mt);
    }
    dl.append(it);
  }
  td.append(dl); g.append(td);

  if (hw.battery) {
    const bt = hw.battery, tb = tile(T('hw.battery'));
    const hc = bt.health == null ? '' : bt.health >= 80 ? 'ok' : bt.health >= 60 ? 'warn' : 'bad';
    tb.append(E('div', 'hw-name', [bt.maker, bt.name].filter(Boolean).join(' ') || T('hw.battery')),
      kvs(kv(T('hw.batHealth'), '', hc), kv(T('hw.capacity')), kv(T('hw.cycles')), kv(T('hw.charge'), 'hwBatP'), kv(T('hw.source'), 'hwBatS')));
    fill(tb, [bt.health != null ? P(bt.health) : '', bt.full_wh ? F(bt.full_wh, 1) + (bt.design_wh ? ' / ' + F(bt.design_wh, 1) : '') + ' Wh' : '',
      bt.cycles != null ? F(bt.cycles) : '']);
    g.append(tb);
  }

  const tn = tile(T('hw.network')); const nl = E('div', 'hw-list');
  for (const n of hw.network || []) {
    const it = E('div', 'hw-item');
    it.append(E('div', 'hw-name', n.desc || n.name), kvs(kv(T('hw.link'), '', n.up ? 'ok' : '')));
    fill(it, [n.up ? n.speed : T('hw.disconnected')]);
    nl.append(it);
  }
  tn.append(nl, kvs(kv(T('hw.down'), 'hwNetD'), kv(T('hw.up'), 'hwNetU')));
  const mons = (hw.monitors || []).map(x => [x.maker, x.name].filter(Boolean).join(' ')).filter(Boolean);
  if (mons.length) tn.append(E('span', 'lbl', T('hw.monitors')), E('div', 'hw-sub', mons.join(', ')));
  g.append(tn);

  page.append(g);
  if (hw.error) page.append(E('p', 'hint', hw.error));
  built.donanim = true;
}
function liveHardware(s) {
  set('hwCpuT', s.cpu_temp != null ? F(s.cpu_temp) + ' °C' : '–', tempCls(s.cpu_temp));
  set('hwCpuW', s.cpu_power != null ? F(s.cpu_power, 1) + ' W' : '–');
  set('hwCpuL', P(s.cpu_load));
  set('hwCpuM', s.cpu_mhz ? F(s.cpu_mhz) + ' MHz' : '–');
  const awake = s.gpu_state === 'active';
  set('hwNvS', T(awake ? 'hw.active' : s.gpu_state === 'off' ? 'gpu.off' : 'hw.sleep'), awake ? 'ok' : '');
  set('hwNvL', P(s.gpu_load)); set('hwIgL', P(s.igpu_load));
  set('hwNvT', s.gpu_temp ? F(s.gpu_temp) + ' °C' : '–', tempCls(s.gpu_temp, 78, 87));
  set('hwNvC', awake && s.gpu_clock != null ? F(s.gpu_clock) + ' MHz' : '–');
  set('hwNvW', awake && s.gpu_power != null ? F(s.gpu_power, 1) + ' W' : '–');
  set('hwRam', s.ram_total ? F(s.ram_used, 1) + ' / ' + F(s.ram_total, 1) + ' GB' : '–');
  for (const d of (hw && hw.disks) || []) {
    const h = (s.disks || {})[d.id] || {}, io = (s.disk_io || {})[d.id], id = 'hwD' + d.id;
    const bad = d.health && d.health !== 'Healthy', crit = h.critical > 0;
    set(id + 'H', crit ? T('hw.critical') : !d.health ? '–' : T(bad ? 'hw.warning' : 'hw.healthy'), crit || bad ? 'bad' : 'ok');
    set(id + 'T', h.temp != null ? F(h.temp) + ' °C' : '–', tempCls(h.temp, h.temp_warn ? h.temp_warn - 10 : 60, h.temp_warn || 70));
    set(id + 'L', h.life != null ? P(h.life) : '–', h.life == null ? '' : h.life < 10 ? 'bad' : h.life < 30 ? 'warn' : '');
    set(id + 'W', h.written_tb != null ? F(h.written_tb, 1) + ' TB' : '–');
    set(id + 'O', h.hours != null ? T('hw.hoursV', { v: F(h.hours) }) : '–');
    set(id + 'U', h.unsafe != null ? F(h.unsafe) : '–');
    set(id + 'R', io ? mbs(io.r) + ' / ' + mbs(io.w) : '–');
    set(id + 'B', io ? P(io.busy) : '–');
  }
  const b = s.battery || {};
  set('hwBatP', b.percent == null ? '–' : P(b.percent)); set('hwBatS', T(b.ac ? 'hw.ac' : 'hw.dc'));
  set('hwNetD', kbs(s.net_down)); set('hwNetU', kbs(s.net_up));
}
async function loadHardware() {
  try { hw = await api('/api/hardware'); } catch (e) { return; }
  buildHardware(); liveHardware(now);
}

/* ================================================================ ISLEMCI */
function control(c, value) {
  const box = E('div', 'tile ctl');
  const top = E('div', 'field-top'); const out = E('output');
  top.append(E('span', 'lbl', c.label), out); box.append(top);
  const send = async v => {
    try { cpu = await api('/api/cpu', { id: c.id, value: v }); toast(T('cpup.saved', { name: c.label }), true); }
    catch (e) { toast(T('cpup.failed', { err: e.message })); }
  };
  if (c.kind === 'select') {
    const s = E('select'); s.setAttribute('aria-label', c.label);
    for (const o of c.opts) s.append(new Option(o.t, o.v));
    if (value != null) s.value = String(value);
    s.addEventListener('change', () => send(+s.value));
    box.append(s);
  } else {
    const [lo, hi, step] = c.kind === 'mhz' ? [0, 5000, 100] : c.range;
    const r = E('input'); r.type = 'range'; r.min = lo; r.max = hi; r.step = step; r.setAttribute('aria-label', c.label);
    const paint = v => {
      r.value = v; r.style.setProperty('--p', (v - lo) / (hi - lo) * 100 + '%');
      out.textContent = c.kind === 'mhz' ? (+v ? F(v / 1000, 1) + ' GHz' : T('cpup.unlimited')) : c.id === 'epp' ? F(v) : P(v);
    };
    paint(value == null ? lo : Math.min(hi, value));
    let tm = 0;
    r.addEventListener('input', () => { paint(+r.value); clearTimeout(tm); tm = setTimeout(() => send(+r.value), 350); });
    box.append(r);
  }
  box.append(E('p', 'hint', c.desc));
  return box;
}
function buildCpu() {
  const page = views.islemci; page.textContent = ''; head(page, 'cpup');
  if (!cpu || !cpu.cpu || !cpu.cpu.name) { page.append(E('p', 'hint', T('hw.scanning'))); return; }
  const c = cpu.cpu, f = c.features || {};
  const g = E('div', 'tiles wide2');
  const tm = tile(T('cpup.model'));
  tm.append(E('div', 'hw-name', c.name), E('div', 'hw-sub', cpuSub(c)),
    kvs(kv(T('hw.cores')), kv(T('hw.threads')), kv(T('hw.base')), kv(T('hw.cache'))));
  fill(tm, [c.hybrid ? T('hw.coresPE', { p: c.p_cores, e: c.e_cores }) : F(c.cores), F(c.threads),
    c.base_mhz ? F(c.base_mhz) + ' MHz' : '', c.l3_kb ? 'L3 ' + F(c.l3_kb / 1024) + ' MB' : '']);
  const yn = (k, on) => { const d = kv(T(k), '', on ? 'ok' : ''); d.querySelector('b').textContent = T(on ? 'cpup.yes' : 'cpup.no'); return d; };
  const feats = kvs(yn('cpup.fSpeedShift', f.epp), yn('cpup.fHybrid', f.hybrid));
  if (c.virt_fw != null) feats.append(yn('cpup.fVirt', c.virt_fw));
  tm.append(E('span', 'lbl', T('cpup.features')), feats);
  g.append(tm);

  const tl = tile(T('cpup.live'));
  const groups = c.hybrid ? [['P', 'cpup.pCores'], ['E', 'cpup.eCores']] : [['A', 'cpup.allCores']];
  tl.append(kvs(kv(T('hw.temp'), 'cpT'), kv(T('hw.power'), 'cpW'), kv(T('hw.load'), 'cpL'), kv(T('hw.fastest'), 'cpM')),
    kvs(...groups.map(([k, key]) => kv(T(key), 'cpG' + k))), E('p', 'hint', T('cpup.noPL')));
  g.append(tl);
  page.append(g);

  page.append(E('h3', '', T('cpup.controls')), E('p', 'hint', T('cpup.note') + (cpu.own_scheme ? '' : ' ' + T('cpup.otherScheme'))));
  const ctl = E('div', 'tiles');
  for (const x of cpu.controls || []) ctl.append(control(x, (cpu.values || {})[x.id]));
  page.append(ctl);
  built.islemci = true;
}
function liveCpu(s) {
  set('cpT', s.cpu_temp != null ? F(s.cpu_temp) + ' °C' : '–', tempCls(s.cpu_temp));
  set('cpW', s.cpu_power != null ? F(s.cpu_power, 1) + ' W' : '–');
  set('cpL', P(s.cpu_load)); set('cpM', s.cpu_mhz ? F(s.cpu_mhz) + ' MHz' : '–');
  const lps = (cpu && cpu.cpu && cpu.cpu.lps) || [], acc = {};
  (s.cores || []).forEach((x, i) => { const k = (lps[i] || {}).t || 'A'; (acc[k] = acc[k] || []).push(x); });
  for (const [k, arr] of Object.entries(acc)) {
    const mhz = arr.reduce((a, x) => a + x.mhz, 0) / arr.length, load = arr.reduce((a, x) => a + x.load, 0) / arr.length;
    set('cpG' + k, F(mhz) + ' MHz · ' + P(Math.round(load)));
  }
}
async function loadCpu() {
  try { cpu = await api('/api/cpu'); } catch (e) { return; }
  buildCpu(); liveCpu(now);
}

/* ================================================================ NVIDIA */
function buildNvidia() {
  const page = views.nvidia; page.textContent = ''; head(page, 'nvp');
  if (!nv) return;
  if (!nv.present) { page.append(E('p', 'hint', T('nvp.none'))); return; }
  const k = nv.card || {}, g = E('div', 'tiles wide2');
  const tc = tile(T('nvp.card'));
  tc.append(E('div', 'hw-name', k.name || '–'),
    kvs(kv(T('hw.driver')), kv(T('nvp.vbios')), kv(T('nvp.cudaCores')), kv(T('hw.vram')), kv(T('nvp.maxClock')), kv(T('nvp.memClock')),
      kv(T('nvp.pcieMax')), kv(T('nvp.powerLimit')), kv(T('nvp.tempSlow')), kv(T('nvp.tempShut'))));
  fill(tc, [k.driver, k.vbios, k.cores ? F(k.cores) : '', k.vram_mb ? F(k.vram_mb / 1024) + ' GB' : '',
    k.max_clock ? F(k.max_clock) + ' MHz' : '', k.max_mem_clock ? F(k.max_mem_clock) + ' MHz' : '',
    k.pcie_gen_max ? 'Gen' + k.pcie_gen_max + ' ×' + k.pcie_width_max : '',
    k.power_limit ? F(k.power_limit) + ' W' : '', k.temp_slowdown ? k.temp_slowdown + ' °C' : '', k.temp_shutdown ? k.temp_shutdown + ' °C' : '']);
  g.append(tc);

  const tl = tile(T('nvp.live'));
  const th = E('div', 'hw-sub'); th.id = 'nvTh';
  tl.append(kvs(kv(T('hw.state'), 'nvS'), kv(T('hw.load'), 'nvL'), kv(T('hw.temp'), 'nvT'), kv(T('hw.power'), 'nvW'),
    kv(T('hw.clock'), 'nvC'), kv(T('nvp.memClock'), 'nvMC'), kv(T('hw.vram'), 'nvV'), kv(T('nvp.pcie'), 'nvP')),
    E('span', 'lbl', T('nvp.throttle')), th);
  g.append(tl);

  const tk = E('div', 'tile ctl');  // elle saat siniri
  tk.append(E('span', 'lbl', T('nvp.clock')));
  const cs = E('select'); cs.setAttribute('aria-label', T('nvp.clock'));
  cs.append(new Option(T('nvp.clockFree'), ''));
  const lo = Math.max(600, Math.ceil((k.clock_min || 600) / 100) * 100), hi = k.clock_max || 2100;
  for (let v = lo; v < hi; v += 150) cs.append(new Option(F(v) + ' MHz', v));
  cs.disabled = !nv.admin;
  cs.addEventListener('change', async () => {
    try { await api('/api/nvidia', { clock_max: cs.value ? +cs.value : null }); toast(T('nvp.clockSet', { v: cs.selectedOptions[0].text }), true); }
    catch (e) { toast(T('nvp.failed', { err: e.message })); }
  });
  tk.append(cs, E('p', 'hint', T('nvp.clockDesc')));
  g.append(tk);
  page.append(g);

  page.append(E('h3', '', T('nvp.settings')));
  if (!nv.api) page.append(E('p', 'hint', T('nvp.noApi')));
  else if (!nv.admin) page.append(E('p', 'hint', T('nvp.adminNote')));
  if (nv.error) page.append(E('p', 'hint', nv.error));
  const st = E('div', 'tiles');
  for (const x of nv.settings || []) {
    const cur = (nv.values || {})[x.id] || {};
    const box = E('div', 'tile ctl');
    const top = E('div', 'field-top'); top.append(E('span', 'lbl', x.label));
    if (cur.custom) top.append(E('span', 'tag', T('nvp.customMark')));
    const row = E('div', 'row');
    const s = E('select'); s.setAttribute('aria-label', x.label);
    for (const o of x.opts) s.append(new Option(o.t, o.v));
    if (cur.value != null) s.value = String(cur.value);
    const def = E('button', 'btn', T('nvp.default')); def.type = 'button';
    s.disabled = def.disabled = !nv.admin || !nv.api;
    def.hidden = !cur.custom;
    const send = async value => {
      s.disabled = def.disabled = true;
      try { nv = await api('/api/nvidia', { key: x.id, value }); toast(T('nvp.saved', { name: x.label }), true); }
      catch (e) { toast(T('nvp.failed', { err: e.message })); }
      buildNvidia(); liveNvidia(now);
    };
    s.addEventListener('change', () => send(+s.value));
    def.addEventListener('click', () => send(null));
    row.append(s, def);
    box.append(top, row, E('p', 'hint', x.desc));
    st.append(box);
  }
  page.append(st);
  built.nvidia = true;
}
function liveNvidia(s) {
  const awake = s.gpu_state === 'active';
  set('nvS', T(awake ? 'hw.active' : s.gpu_state === 'off' ? 'gpu.off' : 'hw.sleep'), awake ? 'ok' : '');
  set('nvL', P(s.gpu_load));
  set('nvT', s.gpu_temp ? F(s.gpu_temp) + ' °C' : '–', tempCls(s.gpu_temp, 78, 87));
  set('nvW', awake && s.gpu_power != null ? F(s.gpu_power, 1) + ' W' : '–');
  set('nvC', awake && s.gpu_clock != null ? F(s.gpu_clock) + ' MHz' : '–');
  set('nvMC', awake && s.gpu_mem_clock != null ? F(s.gpu_mem_clock) + ' MHz' : '–');
  set('nvV', awake && s.gpu_vram_total ? F(s.gpu_vram_used / 1024, 1) + ' / ' + F(s.gpu_vram_total / 1024, 1) + ' GB' : '–');
  set('nvP', awake && s.gpu_pcie ? s.gpu_pcie : '–');
  const th = s.gpu_throttle_txt;
  set('nvTh', !awake ? T('nvp.sleeping') : th && th.length ? th.join(', ') : T('nvp.throttleNone'));
}
async function loadNvidia() {
  try { nv = await api('/api/nvidia'); } catch (e) { return; }
  buildNvidia(); liveNvidia(now);
}

/* ---------- gorunurluk ve canli olcum ---------- */
const LOAD = { donanim: loadHardware, islemci: loadCpu, nvidia: loadNvidia };
const LIVE = { donanim: liveHardware, islemci: liveCpu, nvidia: liveNvidia };
let shown = null;
function onShow() {
  const v = visible();
  if (v && v !== shown) LOAD[v]();
  shown = v;
}
new MutationObserver(onShow).observe(shell, { subtree: true, attributes: true, attributeFilter: ['hidden'] });
setInterval(async () => {
  const v = visible();
  if (!v) return;
  try { now = await api('/api/now'); } catch (e) { return; }
  if (built[v]) LIVE[v](now);
}, 1000);

/* ---------- Genel bakis: cekirdek etiketlerini islemcinin gercek P/E yapisindan yaz ---------- */
let lps = null;
const cores = $('#cores');
function relabel() {
  if (!lps || !cores) return;
  [...cores.children].forEach((d, i) => {
    const x = lps[i]; if (!x) return;
    const name = x.t ? x.t + x.n : 'C' + x.n;
    const lab = d.querySelector('span'); if (lab && lab.textContent !== name) lab.textContent = name;
    d.classList.toggle('e', x.t === 'E');
  });
}
if (cores) new MutationObserver(relabel).observe(cores, { childList: true });
api('/api/cpu').then(r => { if (!cpu) cpu = r; lps = (r.cpu || {}).lps || null; relabel(); }).catch(() => {});
onShow();
})();

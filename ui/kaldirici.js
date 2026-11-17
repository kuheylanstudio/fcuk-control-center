/* FCUK Control Center - Araclar > Kaldirici.
   Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.

   Motor bu betigi index.html'in sonuna ekler; sayfa window.ccNav.add ile kurulur. Akis: uygulama sec ->
   (geri yukleme noktasi) -> uygulamanin kendi kaldiricisi -> artik taramasi -> kullanicinin sectiklerini sil.
   Hicbir sey kullanici secmeden ve ikinci bir onay almadan silinmez; motor her ogeyi silmeden once yeniden denetler. */
(() => {
'use strict';
const I = window.I18N || {};
const LOC = I.locale || 'tr-TR';
const T = (k, v) => { let s = I[k] != null ? I[k] : k; if (v) s = s.replace(/\{(\w+)\}/g, (m, n) => (n in v ? v[n] : m)); return s; };
const $ = (s, r = document) => r.querySelector(s);
const E = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
async function api(path, body) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || 'HTTP ' + r.status);
  return j;
}
function toast(text, ok) {
  const b = $('#banner'); if (!b) return;
  b.textContent = text; b.classList.toggle('info', !!ok); b.classList.remove('closed');
  clearTimeout(toast.t); if (ok) toast.t = setTimeout(() => b.classList.add('closed'), 3500);
}
const size = bytes => {
  if (bytes == null) return '';
  const u = ['B', 'KB', 'MB', 'GB']; let i = 0, v = bytes;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toLocaleString(LOC, { maximumFractionDigits: v < 10 && i ? 1 : 0 }) + ' ' + u[i];
};
const date = s => /^\d{8}$/.test(s || '') ? new Date(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8)).toLocaleDateString(LOC) : (s || '');
const errText = e => (I['un.err.' + e] != null ? T('un.err.' + e) : e);
const LEVELS = ['safe', 'moderate', 'advanced'];

/* ---------- stil: yalnizca mevcut belirtecler ---------- */
const css = E('style');
css.textContent = `
#v-kaldirici .group,#v-kaldirici .pad{grid-template-columns:minmax(0,1fr)}
.un-cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);gap:var(--s-4);align-items:start}
.un-list{display:grid;gap:2px;margin:0;padding:0 var(--s-2) var(--s-2);list-style:none;max-height:min(62vh,640px);overflow:auto}
.un-list > .hint{padding:var(--s-2)}
.un-app{display:grid;gap:3px;width:100%;padding:8px 10px;border:0;border-left:2px solid transparent;border-radius:0 var(--r-2) var(--r-2) 0;background:none;color:var(--text-2);text-align:left;cursor:pointer;transition:background var(--t-fast) var(--ease-out),color var(--t-fast) var(--ease-out)}
.un-app:hover{background:var(--surface-2);color:var(--text)}
.un-app[aria-current="true"]{background:var(--surface-2);color:var(--text-hi);border-left-color:var(--live-ink)}
.un-app .nm{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s-2);font:500 var(--fs-3)/1.25 var(--f-display);overflow-wrap:anywhere}
.un-app .sub{color:var(--text-3);font-size:var(--fs-1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.un-app .chip{padding:2px 6px;font-size:10px}
.un-name{font:600 var(--fs-5)/1.2 var(--f-display);color:var(--text-hi);overflow-wrap:anywhere}
.un-path{font:12px/1.45 Consolas,"Cascadia Mono",monospace;color:var(--text-2);overflow-wrap:anywhere}
.un-note{margin:0;padding:8px 10px;border-left:2px solid var(--warn);color:var(--text-2);font-size:var(--fs-2);line-height:1.45}
.un-note.bad{border-left-color:var(--danger)}
.un-note.ok{border-left-color:var(--live-ink)}
.un-status{min-height:1.4em;margin:0;color:var(--text-2);font-size:var(--fs-2)}
.un-status.err{color:var(--danger)}
.un-sec{display:grid;gap:2px;padding:var(--s-2) var(--s-4) var(--s-3)}
.un-sec + .un-sec{border-top:1px solid var(--line)}
.un-sec > .lbl{padding:var(--s-2) 0}
.un-item{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:var(--s-1) var(--s-3);align-items:start;padding:6px;border-radius:var(--r-2);cursor:pointer}
.un-item:hover{background:var(--surface-2)}
.un-item input{margin:3px 0 0;width:15px;height:15px;accent-color:var(--live-ink);cursor:pointer}
.un-item .meta{display:flex;flex-wrap:wrap;align-items:center;gap:4px var(--s-2);margin-top:4px;color:var(--text-3);font-size:var(--fs-1)}
.un-item .lv{font:600 10px/1 var(--f-display);letter-spacing:.1em;text-transform:uppercase;padding:2px 5px;border:1px solid var(--line-strong);border-radius:var(--r-1);color:var(--text-3)}
.un-item .lv.l2{border-color:var(--warn);color:var(--warn)}
.un-item .sz{color:var(--text-3);font-size:var(--fs-1);font-variant-numeric:tabular-nums;white-space:nowrap}
.un-foot{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:var(--s-3);padding:var(--s-3) var(--s-4);border-top:1px solid var(--line)}
.un-foot .hint{max-width:60ch;margin:0}
.un-fail{margin:0;padding-left:1.2em;color:var(--text-2);font-size:var(--fs-2)}
.un-fail li{overflow-wrap:anywhere}
@media (max-width:900px){.un-cols{grid-template-columns:minmax(0,1fr)}}
`;
document.head.append(css);

if (!window.ccNav) return;
const page = window.ccNav.add('kaldirici', 'nav.kaldirici');
const view = document.getElementById('v-kaldirici');

let apps = null, admin = true, sel = null, filter = '', mode = 'moderate', restore = true;
let busy = false, poll = 0, pollId = '', waitUntil = 0, restoreShown = false;
let scanRes = null, cleaned = null, sure = 0, sureTimer = 0;
let listNode = null, detailNode = null, resNode = null, countNode = null, statusNode = null;

/* ---------- sayfa iskeleti ---------- */
function build() {
  page.textContent = '';
  const h = E('header', 'page-head');
  h.append(E('h2', '', T('un.title')), E('p', '', T('un.intro')));
  page.append(h);
  if (!admin) page.append(E('p', 'un-note', T('un.noAdmin')));

  const cols = E('div', 'un-cols');
  const left = E('section', 'group');
  const lh = E('div', 'group-head');
  countNode = E('span', 'hint');
  const refresh = E('button', 'link-btn', T('un.refresh')); refresh.type = 'button';
  refresh.addEventListener('click', () => load());
  const lt = E('div', 'row'); lt.append(E('span', 'lbl', T('un.apps')), countNode);
  lh.append(lt, refresh);
  const sp = E('div', 'pad');
  const q = E('input'); q.type = 'text'; q.placeholder = T('un.search'); q.setAttribute('aria-label', T('un.search')); q.value = filter;
  q.addEventListener('input', () => { filter = q.value; renderList(); });
  sp.append(q);
  listNode = E('ul', 'un-list');
  left.append(lh, sp, listNode);

  detailNode = E('section', 'group');
  cols.append(left, detailNode);
  resNode = E('div', 'stack');
  page.append(cols, resNode);
  renderList(); renderDetail(); renderResults();
}

function renderList() {
  if (!listNode) return;
  listNode.textContent = '';
  if (!apps) { listNode.append(E('li', 'hint', T('un.loading'))); countNode.textContent = ''; return; }
  const f = filter.trim().toLocaleLowerCase(LOC);
  const shown = apps.filter(a => !f || (a.name + ' ' + a.publisher).toLocaleLowerCase(LOC).includes(f));
  countNode.textContent = T('un.count', { n: shown.length });
  if (!shown.length) { listNode.append(E('li', 'hint', T('un.none'))); return; }
  for (const a of shown) {
    const li = E('li');
    const b = E('button', 'un-app'); b.type = 'button';
    b.setAttribute('aria-current', sel && sel.id === a.id ? 'true' : 'false');
    const nm = E('span', 'nm', a.name);
    if (a.self) nm.append(E('span', 'chip', T('un.chipSelf')));
    else if (a.critical) nm.append(E('span', 'chip warn', T('un.chipSys')));
    b.append(nm, E('span', 'sub', [a.publisher, a.version, a.size_kb ? size(a.size_kb * 1024) : ''].filter(Boolean).join(' · ')));
    b.addEventListener('click', () => select(a));
    li.append(b); listNode.append(li);
  }
}

function select(a) {
  if (busy) return;
  stopPoll(true);
  sel = a; scanRes = null; cleaned = null; sure = 0;
  renderList(); renderDetail(); renderResults();
}

/* ---------- secili uygulama ---------- */
function setStatus(text, err) {
  if (!statusNode) return;
  statusNode.textContent = text || '';
  statusNode.classList.toggle('err', !!err);
}
function renderDetail() {
  const d = detailNode; if (!d) return;
  const keep = statusNode ? [statusNode.textContent, statusNode.classList.contains('err')] : null;
  d.textContent = ''; statusNode = null;
  const gh = E('div', 'group-head'); gh.append(E('span', 'lbl', T('un.selected'))); d.append(gh);
  const body = E('div', 'pad'); d.append(body);
  if (!sel) { body.append(E('p', 'hint', T('un.pick'))); return; }
  const a = sel;
  body.append(E('div', 'un-name', a.name));
  const kv = (k, v) => { const r = E('div', 'kv', T(k)); r.append(E('b', '', v || '–')); return r; };
  const kind = [T(a.msi ? 'un.kindMsi' : 'un.kindExe'), a.x86 ? '32 bit' : '', a.user ? T('un.kindUser') : ''].filter(Boolean).join(' · ');
  const kvs = E('div', 'kvs');
  kvs.append(kv('un.publisher', a.publisher), kv('un.version', a.version), kv('un.size', a.size_kb ? size(a.size_kb * 1024) : ''),
    kv('un.date', date(a.date)));
  body.append(kvs, kv('un.kind', kind));
  if (a.location) body.append(E('span', 'lbl', T('un.folder')), E('div', 'un-path', a.location));
  if (a.self) { body.append(E('p', 'un-note bad', T('un.self'))); return; }
  if (a.critical) body.append(E('p', 'un-note bad', T('un.critical')));

  // tarama duzeyi
  const md = E('div', 'field');
  md.append(E('span', 'lbl', T('un.mode')));
  const seg = E('div', 'seg auto'); seg.setAttribute('role', 'radiogroup'); seg.setAttribute('aria-label', T('un.mode'));
  const desc = E('p', 'hint', T('un.mode.' + mode + '.d'));
  for (const m of LEVELS) {
    const l = E('label'); const r = E('input'); r.type = 'radio'; r.name = 'unmode'; r.value = m; r.checked = m === mode; r.disabled = busy;
    r.addEventListener('change', () => { mode = m; desc.textContent = T('un.mode.' + m + '.d'); });
    l.append(r, E('span', '', T('un.mode.' + m))); seg.append(l);
  }
  md.append(seg, desc); body.append(md);

  // geri yukleme noktasi
  const rp = E('div', 'field');
  const sw = E('label', 'switch'); const cb = E('input'); cb.type = 'checkbox'; cb.checked = restore; cb.disabled = busy;
  cb.addEventListener('change', () => { restore = cb.checked; });
  const tr = E('span', 'track'); tr.setAttribute('aria-hidden', 'true');
  sw.append(cb, tr, E('span', '', T('un.restore')));
  rp.append(sw, E('p', 'hint', T('un.restore.d')));
  body.append(rp);

  const row = E('div', 'btn-row');
  const go = E('button', 'btn solid', T('un.uninstall')); go.type = 'button';
  const only = E('button', 'btn', T('un.scanOnly')); only.type = 'button';
  go.disabled = only.disabled = busy;
  go.addEventListener('click', uninstall);
  only.addEventListener('click', () => scan(false));
  row.append(go, only);
  statusNode = E('p', 'un-status');
  body.append(row, E('p', 'hint', T('un.scanOnly.d')), statusNode);
  if (keep) setStatus(keep[0], keep[1]);
}

/* ---------- kaldirma ---------- */
function restoreMsg(r) {
  if (!r || r.reused) return '';
  if (r.ok) return T('un.rp.ok');
  return T('un.rp.' + (r.reason || 'failed'), { err: r.detail || '' });
}
async function uninstall() {
  if (busy || !sel) return;
  busy = true; renderDetail(); setStatus(restore ? T('un.ph.restore') : T('un.ph.running'));
  try {
    await api('/api/uninst/run', { id: sel.id, restore });
  } catch (e) {
    busy = false; renderDetail(); setStatus(T('un.fail', { err: e.message }), true); return;
  }
  pollId = sel.id; waitUntil = 0; restoreShown = false;
  clearInterval(poll); poll = setInterval(tick, 1000); tick();
}
async function tick() {
  let st;
  try { st = await api('/api/uninst/status'); } catch (e) { return; }
  if (!poll || !sel || sel.id !== pollId || st.id !== pollId) return;
  if (st.restore && !restoreShown) {
    restoreShown = true;
    const m = restoreMsg(st.restore); if (m) toast(m, st.restore.ok);
  }
  if (st.phase === 'restore') return setStatus(T('un.ph.restore'));
  if (st.phase === 'running') return setStatus(T('un.ph.running'));
  if (st.phase === 'error') { stopPoll(); return setStatus(T('un.ph.error', { err: st.error || '' }), true); }
  if (st.phase !== 'done') return;
  if (!st.installed) { stopPoll(); setStatus(T('un.ph.done')); return scan(true); }
  // Bazi kaldiricilar (Inno Setup, NSIS) kendini gecici klasore kopyalayip hemen cikar: kayit silinene dek
  // en fazla 10 dakika beklenir; bu sirada dugmeler acik (iptal ettiysen baska bir sey yapabilirsin)
  if (!waitUntil) { waitUntil = Date.now() + 600000; busy = false; renderDetail(); }
  if (Date.now() > waitUntil) stopPoll();
  setStatus(T('un.ph.waiting'));
}
function stopPoll(quiet) {
  if (!poll) return;
  clearInterval(poll); poll = 0; pollId = '';
  if (!quiet) { busy = false; renderDetail(); }
}

/* ---------- tarama ---------- */
async function scan(auto) {
  if (!sel || (busy && !auto)) return;
  stopPoll(true);
  busy = true; cleaned = null; sure = 0; scanRes = null;
  renderDetail(); setStatus(T('un.scanning'));
  resNode.textContent = ''; resNode.append(E('p', 'hint', T('un.scanning')));
  let err = '';
  try { scanRes = await api('/api/uninst/scan', { id: sel.id, mode }); } catch (e) { err = e.message; }
  busy = false; renderDetail(); renderResults();
  if (err) setStatus(T('un.fail', { err }), true);
  else setStatus(auto ? T('un.ph.scanned') : '');
  if (auto) load();  // kaldirilan uygulama listeden dussun
}

/* ---------- sonuclar ---------- */
const GROUPS = [['un.g.files', ['dir', 'file']], ['un.g.reg', ['key', 'value']], ['un.g.sys', ['service', 'task']]];
const itemLabel = it => it.kind === 'value' ? it.path + '  →  ' + it.name : it.path;
function renderResults() {
  const r = resNode; if (!r) return;
  r.textContent = '';
  if (cleaned) return renderCleaned();
  if (!scanRes || !sel) return;
  const items = scanRes.items || [];
  const g = E('section', 'group');
  const gh = E('div', 'group-head');
  const cnt = E('span', 'hint');
  const left = E('div', 'row'); left.append(E('span', 'lbl', T('un.results')), cnt);
  const tools = E('div', 'btn-row');
  const all = E('button', 'link-btn', T('un.all')); all.type = 'button';
  const none = E('button', 'link-btn', T('un.noneSel')); none.type = 'button';
  tools.append(all, none);
  gh.append(left, tools); g.append(gh);
  if (scanRes.installed) { const p = E('div', 'pad'); p.append(E('p', 'un-note', T('un.installedWarn'))); g.append(p); }
  if (!items.length) {
    tools.hidden = true; cnt.textContent = '';
    const p = E('div', 'pad'); p.append(E('p', 'hint', T('un.empty'))); g.append(p); r.append(g);
    return;
  }
  const del = E('button', 'btn danger'); del.type = 'button';
  const update = () => {
    const n = items.filter(i => i.checked).length;
    cnt.textContent = T('un.resCount', { n: items.length, s: n });
    del.textContent = sure ? T('un.sure', { n }) : T('un.delete', { n });
    del.classList.toggle('sure', !!sure);
    del.disabled = !n || busy;
  };
  const boxes = [];
  for (const [key, kinds] of GROUPS) {
    const list = items.filter(i => kinds.includes(i.kind));
    if (!list.length) continue;
    const sec = E('div', 'un-sec'); sec.append(E('span', 'lbl', T(key) + ' · ' + list.length));
    for (const it of list) {
      const row = E('label', 'un-item');
      const cb = E('input'); cb.type = 'checkbox'; cb.checked = !!it.checked;
      cb.addEventListener('change', () => { it.checked = cb.checked; sure = 0; update(); });
      boxes.push([cb, it]);
      const main = E('div');
      main.append(E('div', 'un-path', itemLabel(it)));
      const meta = E('div', 'meta');
      meta.append(E('span', 'lv l' + it.level, T('un.mode.' + LEVELS[it.level])));
      if (it.note) meta.append(E('span', '', T('un.n.' + it.note)));
      main.append(meta);
      row.append(cb, main, E('span', 'sz', it.size ? size(it.size) : ''));
      sec.append(row);
    }
    g.append(sec);
  }
  const setAll = v => { boxes.forEach(([cb, it]) => { cb.checked = it.checked = v; }); sure = 0; update(); };
  all.addEventListener('click', () => setAll(true));
  none.addEventListener('click', () => setAll(false));
  const foot = E('div', 'un-foot');
  foot.append(E('p', 'hint', T('un.cleanNote')), del);
  g.append(foot);
  del.addEventListener('click', async () => {
    if (!sure) {  // iki adimli onay: ilk tik yalnizca sorar
      sure = 1; update();
      clearTimeout(sureTimer); sureTimer = setTimeout(() => { if (sure) { sure = 0; update(); } }, 5000);
      return;
    }
    clearTimeout(sureTimer);
    sure = 0; busy = true; del.disabled = true; del.textContent = T('un.deleting');
    renderDetail();
    let res = null;
    try {
      res = await api('/api/uninst/clean', { ids: items.filter(i => i.checked).map(i => i.id), restore });
    } catch (e) {
      busy = false; renderDetail(); update(); toast(T('un.fail', { err: e.message })); return;
    }
    busy = false; scanRes = null; cleaned = res;
    const m = restoreMsg(res.restore); if (m) toast(m, res.restore.ok);
    renderDetail(); renderResults();
  });
  update();
  r.append(g);
}
function renderCleaned() {
  const c = cleaned, g = E('section', 'group');
  const gh = E('div', 'group-head'); gh.append(E('span', 'lbl', T('un.results'))); g.append(gh);
  const p = E('div', 'pad');
  p.append(E('p', 'un-note ok', T('un.cleaned', { n: c.removed })));
  if (c.failed && c.failed.length) {
    p.append(E('p', 'un-note bad', T('un.failedN', { n: c.failed.length })));
    const ul = E('ul', 'un-fail');
    for (const f of c.failed) ul.append(E('li', '', (f.name ? f.path + ' → ' + f.name : f.path) + ' — ' + errText(f.error)));
    p.append(ul);
  }
  p.append(E('span', 'lbl', T('un.backup')), E('div', 'un-path', c.backup || ''));
  const row = E('div', 'btn-row');
  const open = E('button', 'btn', T('un.openBackup')); open.type = 'button';
  open.addEventListener('click', () => api('/api/uninst/open', {}).catch(e => toast(T('un.fail', { err: e.message }))));
  const again = E('button', 'btn', T('un.rescan')); again.type = 'button';
  again.addEventListener('click', () => scan(false));
  row.append(open, again);
  p.append(row);
  g.append(p); resNode.append(g);
}

/* ---------- yukleme ---------- */
async function load() {
  try {
    const r = await api('/api/uninst/apps');
    apps = r.apps || [];
    const wasAdmin = admin; admin = r.admin !== false;
    if (wasAdmin !== admin) build();
  } catch (e) {
    apps = apps || []; toast(T('un.fail', { err: e.message }));
  }
  if (sel) sel = apps.find(a => a.id === sel.id) || sel;
  renderList();
}
let loaded = false;
const first = () => { if (!view.hidden && !loaded) { loaded = true; build(); load(); } };
new MutationObserver(first).observe(view, { attributes: true, attributeFilter: ['hidden'] });
first();
})();

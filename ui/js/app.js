/* ════════════════════════════════════════════════════════════════════════════
   Forensic Tools — nucleo dell'interfaccia
   ════════════════════════════════════════════════════════════════════════════ */
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtInt = (n) => Number(n || 0).toLocaleString('it-IT');
const fmtEuro = (n) => '€ ' + Number(n || 0).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const icon = (name, cls = '') => `<span class="ms ${cls}">${name}</span>`;
const pct = (f) => `${Math.max(0, Math.min(100, Math.round((f || 0) * 100)))}%`;
/** Barra di avanzamento con percentuale (1%) e messaggio: usata da tutte le elaborazioni */
const progressBlock = (id, label, frac = 0, msg = '', actions = '') => `
  <div class="pblock" id="${id}">
    <div class="pblock-head"><span class="pblock-label">${esc(label)}</span><span class="pblock-pct" data-pct>${pct(frac)}</span></div>
    <div class="progress"><div data-bar style="width:${pct(frac)}"></div></div>
    <div class="pblock-foot"><span class="pblock-msg" data-msg>${esc(msg)}</span>${actions}</div>
  </div>`;
const setProgress = (el, frac, msg) => {
  if (!el) return;
  const p = pct(frac);
  const bar = el.querySelector('[data-bar]'); if (bar) bar.style.width = p;
  const t = el.querySelector('[data-pct]'); if (t) t.textContent = p;
  if (msg !== undefined) { const m = el.querySelector('[data-msg]'); if (m) m.textContent = msg; }
};

const FT = {
  fid: null,
  fascicolo: null,
  docs: [],
  model: null,
  models: [],
  area: 'pdf',
  status: {},
  listeners: { docs: [], fascicolo: [], area: [] },

  on(evt, fn) { this.listeners[evt].push(fn); },
  emit(evt, data) { (this.listeners[evt] || []).forEach(fn => { try { fn(data); } catch (e) { console.error(e); } }); },

  // ── API ─────────────────────────────────────────────────────────────────
  async api(path, opts = {}) {
    const init = { method: opts.method || (opts.body ? 'POST' : 'GET'), headers: {} };
    if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
    const res = await fetch(path, init);
    let data = {};
    try { data = await res.json(); } catch (e) { /* risposta vuota */ }
    if (!res.ok) throw new Error(data.error || `Errore ${res.status}`);
    return data;
  },

  /** Segue gli eventi di un job (SSE) con riconnessione. handlers: {type: fn}, onEnd */
  stream(jobId, handlers = {}, onEnd) {
    let cursor = 0, closed = false, es;
    const connect = () => {
      es = new EventSource(`/api/jobs/${jobId}/stream?cursor=${cursor}`);
      es.onmessage = (e) => {
        const ev = JSON.parse(e.data);
        if (ev.idx !== undefined) cursor = ev.idx + 1;
        if (ev.type === 'docs_changed') FT.refreshDocs();
        const h = handlers[ev.type] || handlers['*'];
        if (h) h(ev);
        if (ev.type === 'eos') { closed = true; es.close(); onEnd && onEnd(); }
      };
      es.onerror = () => { es.close(); if (!closed) setTimeout(connect, 1500); };
    };
    connect();
    return { cancel: () => FT.api(`/api/jobs/${jobId}/cancel`, { method: 'POST' }), close: () => { closed = true; es && es.close(); } };
  },

  native() { return (window.pywebview && window.pywebview.api) || null; },

  // ── Avvio ───────────────────────────────────────────────────────────────
  async init() {
    this.applyTheme(localStorage.getItem('ft-theme') || 'system');
    window.addEventListener('pywebviewready', () => this.syncNativeAppearance());
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (!document.documentElement.getAttribute('data-theme')) { this.syncNativeAppearance(); window.dispatchEvent(new Event('themechange')); }
    });
    $$('.area-tab').forEach(b => b.addEventListener('click', () => this.setArea(b.dataset.area)));
    $('#btn-sidebar').addEventListener('click', () => this.toggleSidebar());
    $('#btn-fascicolo').addEventListener('click', (e) => this.fascicoloMenu(e.currentTarget));
    $('#btn-model').addEventListener('click', (e) => this.modelMenu(e.currentTarget));
    $('#btn-settings').addEventListener('click', (e) => this.settingsMenu(e.currentTarget));
    $('#btn-add-files').addEventListener('click', () => this.pickAndAdd(false));
    $('#btn-add-folder').addEventListener('click', () => this.pickAndAdd(true));
    $('#activity').addEventListener('click', (e) => this.activityMenu(e.currentTarget));
    this.initDrop();
    this.initKeys();
    $('#toolbar').addEventListener('dblclick', (e) => { if (e.target.classList.contains('drag')) this.native()?.zoom(); });

    const prefs = await this.api('/api/prefs').catch(() => ({}));
    if (prefs.sidebar_hidden) this.toggleSidebar(true);
    await this.loadModels(prefs.model);
    const f = await this.api('/api/fascicoli');
    this.setFascicolo(f.corrente, false);
    this.setArea(prefs.area || 'pdf');
    this.pollJobs();
    this.api('/api/status').then(s => { this.status = s; this.emit('status', s); }).catch(() => {});
  },

  // ── Aree ────────────────────────────────────────────────────────────────
  setArea(area) {
    this.area = area;
    $$('.area-tab').forEach(b => b.classList.toggle('active', b.dataset.area === area));
    $$('.area').forEach(a => a.classList.toggle('active', a.id === `area-${area}`));
    this.api('/api/prefs', { body: { area } }).catch(() => {});
    this.emit('area', area);
  },

  toggleSidebar(force) {
    const body = $('#body');
    const hidden = force !== undefined ? force : !body.classList.contains('sidebar-hidden');
    body.classList.toggle('sidebar-hidden', hidden);
    $('#btn-sidebar .ms').textContent = hidden ? 'left_panel_open' : 'left_panel_close';
    this.api('/api/prefs', { body: { sidebar_hidden: hidden } }).catch(() => {});
    setTimeout(() => window.dispatchEvent(new Event('resize')), 50);
  },

  initKeys() {
    document.addEventListener('keydown', (e) => {
      if (!e.metaKey) return;
      if (['1', '2', '3'].includes(e.key)) { e.preventDefault(); this.setArea(['pdf', 'ricerca', 'forensic'][+e.key - 1]); }
      if (e.key.toLowerCase() === 's' && e.shiftKey) { e.preventDefault(); this.toggleSidebar(); }
      if (e.key.toLowerCase() === 'o') { e.preventDefault(); this.pickAndAdd(false); }
    });
  },

  // ── Tema ────────────────────────────────────────────────────────────────
  applyTheme(t) {
    localStorage.setItem('ft-theme', t);
    if (t === 'system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', t);
    window.dispatchEvent(new Event('themechange'));
    this.syncNativeAppearance();
  },
  syncNativeAppearance() {
    const n = this.native();
    if (n) n.set_appearance(this.isDark());
    else setTimeout(() => this.native() && this.native().set_appearance(this.isDark()), 400);
  },
  isDark() {
    const t = document.documentElement.getAttribute('data-theme');
    return t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  },

  // ── Modelli ─────────────────────────────────────────────────────────────
  async loadModels(pref) {
    try {
      const r = await this.api('/api/models');
      if (!r.models.length && (this._modelTries = (this._modelTries || 0) + 1) < 20) {
        setTimeout(() => this.loadModels(pref), 1500);      // Ollama ancora in avvio
      }
      this.models = r.models;
      this.ramGb = r.ram_gb;
      this.recommended = r.recommended;
      const ok = r.models.find(m => m.id === pref);
      this.setModel(ok ? pref : r.recommended, false);
    } catch (e) { $('#model-label').textContent = 'Modello non disponibile'; }
  },
  setModel(id, save = true) {
    this.model = id;
    const m = this.models.find(x => x.id === id);
    $('#model-label').textContent = m ? m.label : id;
    if (save) this.api('/api/prefs', { body: { model: id } }).catch(() => {});
  },
  modelMenu(anchor) {
    const items = this.models.map(m => `
      <button class="menu-item" data-id="${esc(m.id)}">
        <span class="ms ${m.id === this.model ? 'check' : ''}">${m.id === this.model ? 'check' : 'memory'}</span>
        <span class="grow"><div>${esc(m.label)}${m.id === this.recommended ? ' <span class="badge-rec">consigliato</span>' : ''}</div>
        <div class="faint" style="font-size:11.5px">${esc(m.desc || '')}</div></span>
      </button>`).join('');
    const pop = this.popover(anchor, `<div class="menu-head">Modello IA locale · ${this.ramGb || '?'} GB RAM</div>${items}
      <div class="menu-sep"></div><div style="padding:4px 10px 6px;font-size:11.5px" class="faint">Usato da Ricerca e Forensic AI. Tutto resta sul Mac.</div>`, 'right');
    $$('.menu-item', pop).forEach(b => b.addEventListener('click', () => { this.setModel(b.dataset.id); this.closePopover(); }));
  },

  async settingsMenu(anchor) {
    try { this.status = await this.api('/api/status'); } catch (e) { /* usa l'ultimo stato noto */ }
    const t = localStorage.getItem('ft-theme') || 'system';
    const s = this.status || {};
    const row = (ok, label) => `<div style="display:flex;align-items:center;gap:8px;padding:3px 10px;font-size:12px">
      <span class="ms sm ${ok ? 'st-ok' : 'st-err'}">${ok ? 'check_circle' : 'error'}</span>${label}</div>`;
    const pop = this.popover(anchor, `
      <div class="menu-head">Aspetto</div>
      <div style="padding:4px 8px 8px"><div class="segmented" id="theme-seg" style="width:100%">
        <button data-t="system" class="${t === 'system' ? 'active' : ''}" style="flex:1"><span class="ms">contrast</span>Sistema</button>
        <button data-t="light" class="${t === 'light' ? 'active' : ''}" style="flex:1"><span class="ms">light_mode</span>Chiaro</button>
        <button data-t="dark" class="${t === 'dark' ? 'active' : ''}" style="flex:1"><span class="ms">dark_mode</span>Scuro</button>
      </div></div>
      <div class="menu-sep"></div>
      <div class="menu-head">Motori offline</div>
      ${row(s.ollama, 'Motore IA (Ollama)')}
      ${row(!!s.embed_model, 'Ricerca semantica (embedding)')}
      ${row(s.tesseract_italian, 'OCR Tesseract · italiano')}
      ${row(s.ghostscript, 'Ghostscript')}
      ${row(s.pango, 'Pango (conversione documenti)')}
      <div class="menu-sep"></div>
      <div style="padding:4px 10px 8px;font-size:11.5px" class="faint">${esc(s.cpu || '')} · ${s.ram_gb || '?'} GB RAM<br>Forensic Tools funziona interamente offline.</div>`, 'right');
    $$('#theme-seg button', pop).forEach(b => b.addEventListener('click', () => {
      this.applyTheme(b.dataset.t); $$('#theme-seg button', pop).forEach(x => x.classList.toggle('active', x === b));
    }));
  },

  // ── Fascicoli ───────────────────────────────────────────────────────────
  setFascicolo(f, save = true) {
    this.fid = f.id;
    this.fascicolo = f;
    $('#f-name').textContent = f.nome;
    $('#add-fascicolo-name').textContent = `«${f.nome}»`;
    if (save) this.api(`/api/fascicoli/${f.id}`).catch(() => {});
    this.refreshDocs();
    this.emit('fascicolo', f);
  },

  async fascicoloMenu(anchor) {
    const r = await this.api('/api/fascicoli');
    const items = r.fascicoli.map(f => `
      <button class="menu-item" data-id="${f.id}">
        <span class="ms ${f.id === this.fid ? 'check' : ''}">${f.id === this.fid ? 'check' : 'folder'}</span>
        <span class="grow"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(f.nome)}</div>
        <div class="faint" style="font-size:11.5px">${f.num_documenti} documenti · ${new Date(f.aggiornato).toLocaleDateString('it-IT')}</div></span>
      </button>`).join('');
    const pop = this.popover(anchor, `<div class="menu-head">Fascicoli</div>${items}<div class="menu-sep"></div>
      <button class="menu-item" data-act="new"><span class="ms">create_new_folder</span>Nuovo fascicolo…</button>
      <button class="menu-item" data-act="rename"><span class="ms">edit</span>Rinomina «${esc(this.fascicolo.nome)}»…</button>
      <button class="menu-item danger" data-act="delete"><span class="ms">delete</span>Elimina fascicolo…</button>`);
    $$('.menu-item[data-id]', pop).forEach(b => b.addEventListener('click', async () => {
      this.closePopover();
      this.setFascicolo(await this.api(`/api/fascicoli/${b.dataset.id}`));
    }));
    $('[data-act=new]', pop).addEventListener('click', async () => {
      this.closePopover();
      const nome = await this.prompt('Nuovo fascicolo', 'Nome del fascicolo', '', 'Crea');
      if (nome) this.setFascicolo(await this.api('/api/fascicoli', { body: { nome } }));
    });
    $('[data-act=rename]', pop).addEventListener('click', async () => {
      this.closePopover();
      const nome = await this.prompt('Rinomina fascicolo', 'Nuovo nome', this.fascicolo.nome, 'Rinomina');
      if (nome) this.setFascicolo(await this.api(`/api/fascicoli/${this.fid}`, { method: 'PATCH', body: { nome } }), false);
    });
    $('[data-act=delete]', pop).addEventListener('click', async () => {
      this.closePopover();
      const ok = await this.confirm('Eliminare il fascicolo?',
        `«${this.fascicolo.nome}» verrà eliminato con tutti i documenti acquisiti, l'indice di ricerca e le analisi. I file originali sul disco non vengono toccati.`, 'Elimina', true);
      if (ok) { const r2 = await this.api(`/api/fascicoli/${this.fid}`, { method: 'DELETE' }); this.setFascicolo(r2.corrente); }
    });
  },

  // ── Documenti del fascicolo ─────────────────────────────────────────────
  async refreshDocs() {
    if (!this.fid) return;
    try {
      const r = await this.api(`/api/fascicoli/${this.fid}/documenti`);
      this.docs = r.documenti;
      this.renderDocs();
      this.emit('docs', this.docs);
    } catch (e) { /* fascicolo appena eliminato */ }
  },

  docType(ext) {
    if (ext === '.pdf') return ['t-pdf', 'picture_as_pdf'];
    if (['.doc', '.docx', '.odt', '.rtf'].includes(ext)) return ['t-word', 'article'];
    if (['.xls', '.xlsx', '.ods', '.csv'].includes(ext)) return ['t-sheet', 'table_chart'];
    if (['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff', '.webp'].includes(ext)) return ['t-image', 'image'];
    if (ext === '.p7m') return ['t-signed', 'verified'];
    if (['.xml', '.ofx', '.qfx', '.mt940', '.camt', '.bai2', '.json'].includes(ext)) return ['t-sheet', 'account_balance'];
    if (['.ppt', '.pptx', '.odp'].includes(ext)) return ['t-pdf', 'slideshow'];
    return ['t-text', 'description'];
  },

  docStateIcon(d) {
    if (['in_coda', 'elaborazione', 'indicizzazione'].includes(d.stato)) return `<span class="spinner" title="${esc(d.messaggio)}"></span>`;
    if (d.stato === 'errore') return `<span class="ms st-err" title="${esc(d.messaggio)}">error</span>`;
    if (d.stato === 'avviso') return `<span class="ms st-warn" title="${esc(d.messaggio)}">warning</span>`;
    return d.analizzato ? `<span class="ms st-ok fill" title="Indicizzato e analizzato da Forensic AI">verified</span>`
      : `<span class="ms st-ok" title="Pronto per Ricerca">check_circle</span>`;
  },

  renderDocs() {
    const list = $('#doc-list');
    const docs = this.docs;
    const tot = docs.length, pag = docs.reduce((s, d) => s + (d.pagine || 0), 0);
    $('#f-meta').textContent = tot ? `${tot} documenti · ${fmtInt(pag)} pagine` : 'Vuoto';
    if (!tot) {
      list.innerHTML = `<div class="sb-empty">${icon('folder_open', 'xxl')}
        <p style="color:var(--label-2);font-weight:500">Il fascicolo è vuoto</p>
        <p>Trascina qui file o cartelle dal Finder, oppure usa i pulsanti qui sopra. Saranno disponibili in Ricerca e Forensic AI.</p></div>`;
    } else {
      list.innerHTML = docs.map(d => {
        const [cls, ic] = this.docType(d.estensione);
        let meta;
        if (['in_coda', 'elaborazione', 'indicizzazione'].includes(d.stato)) meta = esc(d.messaggio);
        else if (d.stato === 'errore') meta = `<span class="st-err">${esc(d.messaggio)}</span>`;
        else {
          const bits = [`${d.pagine} ${d.pagine === 1 ? 'pag.' : 'pag.'}`];
          if (d.ocr) bits.push('OCR');
          if (d.firmato) bits.push('firmato');
          if ((d.pagine_senza_testo || []).length) bits.push(`${d.pagine_senza_testo.length} senza testo`);
          meta = bits.join(' · ');
        }
        return `<div class="doc-item" data-id="${d.id}" title="${esc(d.sorgente || d.nome)}">
          <div class="doc-ico ${cls}">${icon(ic)}</div>
          <div style="min-width:0"><div class="doc-name">${esc(d.nome)}</div><div class="doc-meta">${meta}</div></div>
          <div class="doc-state">${this.docStateIcon(d)}<button class="icon-btn doc-menu" style="width:24px;height:24px">${icon('more_horiz', 'sm')}</button></div>
        </div>`;
      }).join('');
      $$('.doc-item', list).forEach(el => {
        el.addEventListener('dblclick', () => this.openDoc(el.dataset.id));
        el.addEventListener('contextmenu', (e) => { e.preventDefault(); this.docMenu(el.dataset.id, el.querySelector('.doc-menu')); });
        el.querySelector('.doc-menu').addEventListener('click', (e) => { e.stopPropagation(); this.docMenu(el.dataset.id, e.currentTarget); });
      });
    }
    const working = docs.filter(d => ['in_coda', 'elaborazione', 'indicizzazione'].includes(d.stato)).length;
    const sem = docs.length && docs.every(d => d.semantico || d.stato !== 'pronto');
    $('#sb-foot').innerHTML = `
      <div class="row">${icon('lock', 'xs')}Archiviato solo su questo Mac</div>
      ${working ? `<div class="row"><span class="spinner"></span>${working} documenti in elaborazione</div>` : ''}
      ${tot && !working ? `<div class="row">${icon(sem ? 'neurology' : 'text_fields', 'xs')}${sem ? 'Ricerca per significato e parole attiva' : 'Ricerca per parole attiva'}</div>` : ''}`;
  },

  docMenu(docId, anchor) {
    const d = this.docs.find(x => x.id === docId);
    if (!d) return;
    const pop = this.popover(anchor, `
      <div class="menu-head" style="text-transform:none;letter-spacing:0">${esc(d.nome)}</div>
      <button class="menu-item" data-a="view"><span class="ms">visibility</span>Visualizza</button>
      <button class="menu-item" data-a="open"><span class="ms">open_in_new</span>Apri con Anteprima</button>
      ${d.sorgente ? `<button class="menu-item" data-a="reveal"><span class="ms">folder_open</span>Mostra originale nel Finder</button>` : ''}
      <button class="menu-item" data-a="reprocess"><span class="ms">refresh</span>Rielabora (conversione e OCR)</button>
      <div class="menu-sep"></div>
      <button class="menu-item danger" data-a="delete"><span class="ms">remove_circle</span>Rimuovi dal fascicolo</button>`);
    pop.addEventListener('click', async (e) => {
      const a = e.target.closest('[data-a]')?.dataset.a;
      if (!a) return;
      this.closePopover();
      if (a === 'view') this.openDoc(docId);
      if (a === 'open') this.api(`/api/fascicoli/${this.fid}/documenti/${docId}/apri`, { method: 'POST' });
      if (a === 'reveal') this.api('/api/reveal', { body: { path: d.sorgente } });
      if (a === 'reprocess') { const r = await this.api(`/api/fascicoli/${this.fid}/documenti/${docId}/reprocess`, { method: 'POST' }); this.stream(r.job_id, {}, () => this.refreshDocs()); this.refreshDocs(); }
      if (a === 'delete') {
        if (await this.confirm('Rimuovere il documento?', `«${d.nome}» verrà tolto dal fascicolo, dall'indice di ricerca e dall'analisi forense. Il file originale non viene toccato.`, 'Rimuovi', true)) {
          await this.api(`/api/fascicoli/${this.fid}/documenti/${docId}`, { method: 'DELETE' });
          this.refreshDocs();
        }
      }
    });
  },

  /** Visualizzatore: PDF alla pagina indicata + estratto evidenziato */
  async openDoc(docId, page = 1, excerpt = '') {
    const d = this.docs.find(x => x.id === docId) || { nome: 'Documento' };
    const r = await this.api(`/api/fascicoli/${this.fid}/documenti/${docId}/pagine`);
    const pages = r.pagine || [];
    const pg = pages.find(p => p.n === page) || pages[0] || { text: '' };
    const hl = (t) => {
      let h = esc(t);
      if (excerpt) {
        const words = excerpt.split(/\s+/).filter(w => w.length > 5).slice(0, 8);
        words.forEach(w => { const re = new RegExp(`(${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'); h = h.replace(re, '<mark>$1</mark>'); });
      }
      return h;
    };
    const hasPdf = r.meta && r.meta.pdf;
    const body = hasPdf
      ? `<div class="viewer"><iframe src="/api/fascicoli/${this.fid}/documenti/${docId}/pdf#page=${page}"></iframe>
          <div class="viewer-side"><div class="group-label">${esc(pg.label || 'Pagina ' + page)} · testo riconosciuto</div>
          <div class="excerpt">${hl(pg.text || 'Nessun testo in questa pagina.')}</div></div></div>`
      : `<div class="viewer-text">${pages.map(p => `<div class="group-label">${esc(p.label)}</div>${hl(p.text)}`).join('<div class="divider"></div>')}</div>`;
    const m = this.modal(`${icon(this.docType(d.estensione || '')[1])}<h3>${esc(d.nome)}${hasPdf ? ` · ${esc(pg.label || '')}` : ''}</h3>
      <button class="btn" data-open>${icon('open_in_new')}Apri con Anteprima</button>`, body, null, 'large');
    $('[data-open]', m).addEventListener('click', () => this.api(`/api/fascicoli/${this.fid}/documenti/${docId}/apri`, { method: 'POST' }));
  },

  async pickAndAdd(folder) {
    const n = this.native();
    if (!n) return this.toast('Funzione disponibile nell\'app', 'info');
    const paths = folder ? [await n.choose_folder('Aggiungi cartella al fascicolo')].filter(Boolean) : await n.choose_files(true);
    if (paths && paths.length) this.addPaths(paths);
  },

  async addPaths(paths) {
    try {
      const r = await this.api(`/api/fascicoli/${this.fid}/documenti`, { body: { paths } });
      this.toast(`${r.count} ${r.count === 1 ? 'documento aggiunto' : 'documenti aggiunti'} al fascicolo: conversione, OCR e indicizzazione in corso`, 'add_task');
      this.refreshDocs();
      this.stream(r.job_id, {}, () => this.refreshDocs());
    } catch (e) { this.toast(e.message, 'error'); }
  },

  // ── Drag & drop dal Finder (percorsi reali forniti dalla finestra nativa) ─
  initDrop() {
    let target = null;
    const zoneOf = (el) => el?.closest?.('[data-drop]')?.dataset.drop || (this.area === 'pdf' ? null : 'fascicolo');
    document.addEventListener('dragover', (e) => {
      e.preventDefault();
      const z = zoneOf(e.target);
      target = z;
      document.body.classList.toggle('dropping', z === 'fascicolo');
      $('#drop-zone').classList.toggle('drag-over', z === 'pdf');
    });
    document.addEventListener('dragleave', (e) => {
      if (!e.relatedTarget) { document.body.classList.remove('dropping'); $('#drop-zone').classList.remove('drag-over'); }
    });
    document.addEventListener('drop', (e) => {
      e.preventDefault();
      document.body.classList.remove('dropping');
      $('#drop-zone').classList.remove('drag-over');
      this._dropTarget = target;
    });
  },
  onNativeDrop(paths) {
    const t = this._dropTarget;
    if (t === 'pdf' && window.PDF) PDF.onNativeDrop(paths);
    else if (t === 'fascicolo') this.addPaths(paths);
  },

  // ── Attività in background ──────────────────────────────────────────────
  async pollJobs() {
    try {
      const r = await this.api(`/api/jobs/active${this.fid ? `?fid=${this.fid}` : ''}`);
      this.jobs = r.jobs;
      const act = $('#activity');
      if (r.jobs.length) {
        act.classList.remove('hidden');
        const j = r.jobs[0];
        $('#activity-txt').textContent = r.jobs.length > 1 ? `${r.jobs.length} attività in corso` : `${j.label} · ${pct(j.progress)}`;
      } else act.classList.add('hidden');
      if (r.jobs.some(j => j.kind === 'ingest' || j.kind === 'index' || j.kind === 'pdf')) this.refreshDocs();
      this.renderSidebarJobs(r.jobs.filter(j => j.kind === 'ingest' || j.kind === 'index'));
    } catch (e) { /* server in avvio */ }
    setTimeout(() => this.pollJobs(), (this.jobs && this.jobs.length) ? 1500 : 4000);
  },
  renderSidebarJobs(list) {
    const box = $('#sb-jobs');
    if (!list.length) { box.innerHTML = ''; return; }
    box.innerHTML = list.map(j => progressBlock(`sbj-${j.id}`, j.label, j.progress, j.message,
      `<span class="pblock-actions">${j.errors ? `<span class="chip c-red">${icon('error')}${j.errors}</span>` : ''}
       <button class="btn plain sm-btn" data-log="${j.id}" data-label="${esc(j.label)}">${icon('receipt_long')}Log</button>
       <button class="btn plain sm-btn danger" data-cancel="${j.id}">${icon('close')}</button></span>`)).join('');
    $$('[data-log]', box).forEach(b => b.onclick = () => this.showLog(b.dataset.log, b.dataset.label));
    $$('[data-cancel]', box).forEach(b => b.onclick = () => this.api(`/api/jobs/${b.dataset.cancel}/cancel`, { method: 'POST' }));
  },

  async activityMenu(anchor) {
    const recent = (await this.api(`/api/jobs/recent${this.fid ? `?fid=${this.fid}` : ''}`).catch(() => ({ jobs: [] }))).jobs;
    const running = recent.filter(j => j.status === 'running');
    const done = recent.filter(j => j.status !== 'running').slice(0, 6);
    const actions = (j) => `<span class="pblock-actions">${j.errors ? `<span class="chip c-red">${icon('error')}${j.errors}</span>` : ''}${j.warnings ? `<span class="chip c-orange">${icon('warning')}${j.warnings}</span>` : ''}
      <button class="btn plain sm-btn" data-log="${j.id}" data-label="${esc(j.label)}">${icon('receipt_long')}Log</button>
      ${j.status === 'running' ? `<button class="btn plain sm-btn danger" data-cancel="${j.id}">${icon('close')}</button>` : ''}</span>`;
    const pop = this.popover(anchor, `<div style="width:380px">
      <div class="menu-head">Attività in corso</div>
      ${running.length ? running.map(j => `<div style="padding:4px 8px">${progressBlock('act-' + j.id, j.label, j.progress, j.message, actions(j))}</div>`).join('') : '<div class="faint" style="padding:6px 10px 10px">Nessuna elaborazione in corso</div>'}
      ${done.length ? `<div class="menu-sep"></div><div class="menu-head">Completate di recente</div>${done.map(j => `
        <div class="pblock" style="margin:4px 8px"><div class="pblock-head"><span class="pblock-label">${esc(j.label)}</span>
        <span class="pblock-pct">${icon(j.errors ? 'error' : 'check_circle', j.errors ? 'st-err xs' : 'st-ok xs')}</span></div>
        <div class="pblock-foot"><span class="pblock-msg">${new Date(j.created_at * 1000).toLocaleTimeString('it-IT')}</span>${actions(j)}</div></div>`).join('')}` : ''}
    </div>`, 'right');
    $$('[data-log]', pop).forEach(b => b.addEventListener('click', () => { this.closePopover(); this.showLog(b.dataset.log, b.dataset.label); }));
    $$('[data-cancel]', pop).forEach(b => b.addEventListener('click', () => { this.api(`/api/jobs/${b.dataset.cancel}/cancel`, { method: 'POST' }); this.closePopover(); }));
  },

  /** Finestra di log di un'elaborazione (come il log di Pdf50), aggiornata in tempo reale */
  showLog(jobId, title = 'Elaborazione') {
    const m = this.modal(`${icon('receipt_long')}<h3>Log · ${esc(title)}</h3>
      <label class="check-row" style="font-size:12px;margin-right:6px"><span class="switch"><input type="checkbox" data-onlyerr><span></span></span>Solo errori e avvisi</label>`,
      `<div style="padding:14px 16px 0">${progressBlock('log-prog', title, 0, '')}</div>
       <div class="log-box" style="margin:12px 16px 16px"><div class="log-head"><span data-count>0 righe</span></div>
       <div class="log-panel" style="max-height:52vh;min-height:220px" data-panel></div></div>`, null);
    $('.modal', m).style.width = 'min(820px, calc(100vw - 48px))';
    const panel = $('[data-panel]', m);
    let n = 0, ne = 0, nw = 0;
    const counter = () => { $('[data-count]', m).textContent = `${n} righe${ne ? ` · ${ne} errori` : ''}${nw ? ` · ${nw} avvisi` : ''}`; };
    const add = (ev) => {
      const lvl = ev.level === 'warn' ? 'warning' : (ev.level || 'info');
      const div = document.createElement('div');
      div.className = `log-entry ${(ev.message || '').trim().startsWith('✓') ? 'success' : lvl}`;
      div.innerHTML = `<span class="log-ts">${esc(ev.ts || '')}</span><span class="log-msg">${esc(ev.message)}</span>`;
      panel.appendChild(div); n++; if (lvl === 'error') ne++; if (lvl === 'warning') nw++;
      counter(); panel.scrollTop = panel.scrollHeight;
    };
    $('[data-onlyerr]', m).addEventListener('change', (e) => panel.classList.toggle('only-issues', e.target.checked));
    const st = this.stream(jobId, {
      log: add,
      progress: (ev) => setProgress($('#log-prog', m), ev.fraction, ev.message),
      fatal_error: (ev) => add({ level: 'error', message: `ERRORE CRITICO: ${ev.message}`, ts: ev.ts }),
      done: () => setProgress($('#log-prog', m), 1, 'Completato'),
    }, () => { if (!n) add({ level: 'info', message: 'Nessuna riga di log per questa elaborazione.' }); });
    const close = m.close; m.close = () => { st.close(); close(); };
    $('[data-close]', m).addEventListener('click', () => st.close());
  },

  // ── Popover, modali, toast ──────────────────────────────────────────────
  popover(anchor, html, align = 'left') {
    this.closePopover();
    const pop = document.createElement('div');
    pop.className = 'popover';
    pop.innerHTML = html;
    document.body.appendChild(pop);
    const r = anchor.getBoundingClientRect();
    const w = pop.offsetWidth;
    let left = align === 'right' ? r.right - w : r.left;
    left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
    let top = r.bottom + 6;
    if (top + pop.offsetHeight > window.innerHeight - 8) top = Math.max(8, r.top - pop.offsetHeight - 6);
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
    setTimeout(() => {
      this._popClose = (e) => { if (!pop.contains(e.target)) this.closePopover(); };
      document.addEventListener('mousedown', this._popClose);
    });
    this._pop = pop;
    return pop;
  },
  closePopover() {
    if (this._pop) { this._pop.remove(); this._pop = null; }
    if (this._popClose) { document.removeEventListener('mousedown', this._popClose); this._popClose = null; }
  },

  modal(headHtml, bodyHtml, footHtml, size = '') {
    const bd = document.createElement('div');
    bd.className = 'modal-backdrop';
    bd.innerHTML = `<div class="modal ${size}"><div class="modal-head">${headHtml}
      <button class="icon-btn" data-close title="Chiudi (Esc)">${icon('close')}</button></div>
      <div class="modal-body" style="${size === 'large' ? 'padding:0' : ''}">${bodyHtml}</div>
      ${footHtml ? `<div class="modal-foot">${footHtml}</div>` : ''}</div>`;
    document.body.appendChild(bd);
    const close = () => { bd.remove(); document.removeEventListener('keydown', onKey); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    bd.addEventListener('mousedown', (e) => { if (e.target === bd) close(); });
    $('[data-close]', bd).addEventListener('click', close);
    bd.close = close;
    return bd;
  },
  confirm(title, text, okLabel = 'OK', danger = false) {
    return new Promise(res => {
      const m = this.modal(`<h3>${esc(title)}</h3>`, `<p style="margin:0">${esc(text)}</p>`,
        `<button class="btn lg" data-no>Annulla</button><button class="btn lg ${danger ? 'primary' : 'primary'}" data-ok style="${danger ? 'background:var(--red)' : ''}">${esc(okLabel)}</button>`);
      $('[data-no]', m).addEventListener('click', () => { m.close(); res(false); });
      $('[data-ok]', m).addEventListener('click', () => { m.close(); res(true); });
      $('[data-close]', m).addEventListener('click', () => res(false));
    });
  },
  prompt(title, label, value = '', okLabel = 'OK') {
    return new Promise(res => {
      const m = this.modal(`<h3>${esc(title)}</h3>`, `<label class="group-label">${esc(label)}</label>
        <input class="input" style="width:100%;height:32px" value="${esc(value)}" data-in>`,
        `<button class="btn lg" data-no>Annulla</button><button class="btn primary lg" data-ok>${esc(okLabel)}</button>`);
      const inp = $('[data-in]', m);
      setTimeout(() => { inp.focus(); inp.select(); }, 30);
      const ok = () => { const v = inp.value.trim(); m.close(); res(v || null); };
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); });
      $('[data-ok]', m).addEventListener('click', ok);
      $('[data-no]', m).addEventListener('click', () => { m.close(); res(null); });
    });
  },
  toast(text, ic = 'info', ms = 4200) {
    const colors = { error: 'st-err', warning: 'st-warn', check_circle: 'st-ok', add_task: 'st-work', info: 'st-work' };
    const t = document.createElement('div');
    t.className = 'toast';
    t.innerHTML = `${icon(ic, colors[ic] || 'st-work')}<span>${esc(text)}</span>`;
    $('#toasts').appendChild(t);
    setTimeout(() => { t.style.transition = 'opacity .3s'; t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, ms);
  },

  // ── Markdown sicuro ─────────────────────────────────────────────────────
  md(text) {
    const html = marked.parse(text || '', { breaks: true, gfm: true });
    return DOMPurify.sanitize(html);
  },

  async saveAs(filename, tipo) {
    const n = this.native();
    if (!n) return this.toast('Funzione disponibile nell\'app', 'info');
    const path = await n.save_file(filename);
    if (!path) return;
    try {
      await this.api(`/api/forensic/${this.fid}/export`, { body: { tipo, path } });
      this.toast(`Salvato: ${path.split('/').pop()}`, 'check_circle');
    } catch (e) { this.toast(e.message, 'error'); }
  },
};

window.FT = FT;
document.addEventListener('DOMContentLoaded', () => FT.init());

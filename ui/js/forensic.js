/* ════════════════════════════════════════════════════════════════════════════
   Area Forensic AI — analisi investigativa (motori storici dell'app)
   ════════════════════════════════════════════════════════════════════════════ */
'use strict';

const TIPO = {
  PERSONA: { ic: 'person', cls: 'c-blue', color: '#0A84FF', label: 'Persona' },
  SOCIETA: { ic: 'domain', cls: 'c-green', color: '#30B158', label: 'Società' },
  CONTO: { ic: 'account_balance', cls: 'c-orange', color: '#FF9F0A', label: 'Conto' },
  ASSET: { ic: 'real_estate_agent', cls: 'c-purple', color: '#BF5AF2', label: 'Asset' },
  ALTRO: { ic: 'radio_button_unchecked', cls: 'c-gray', color: '#8E8E93', label: 'Altro' },
};
const tipo = (t) => TIPO[(t || 'ALTRO').toUpperCase()] || TIPO.ALTRO;

const FX = {
  view: 'overview',
  job: null,
  chat: [],
  chatRunning: null,
  network: null,

  init() {
    $$('#fx-nav button').forEach(b => b.addEventListener('click', () => this.setView(b.dataset.view)));
    FT.on('fascicolo', () => { this.chat = null; this.refresh(); });
    FT.on('docs', () => { if (this.view === 'overview' && FT.area === 'forensic' && !this.job) this.debounced(); });
    FT.on('area', (a) => { if (a === 'forensic') this.refresh(); });
    const input = $('#fc-input');
    input.addEventListener('input', () => { RC.autosize(input); this.updateChatSend(); });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.sendChat(); } });
    $('#fc-send').addEventListener('click', () => this.chatRunning ? this.chatRunning.cancel() : this.sendChat());
    window.addEventListener('themechange', () => { if (this.view === 'graph') this.loadGraph(); });
  },
  debounced() { clearTimeout(this._t); this._t = setTimeout(() => this.loadOverview(), 600); },

  setView(v) {
    this.view = v;
    $$('#fx-nav button').forEach(b => b.classList.toggle('active', b.dataset.view === v));
    $$('.fx-view').forEach(el => el.classList.toggle('active', el.id === `fx-${v}`));
    this.refresh();
  },

  refresh() {
    if (FT.area !== 'forensic' || !FT.fid) return;
    $('#fx-actions').innerHTML = '';
    ({ overview: () => this.loadOverview(), chat: () => this.loadChat(), dossier: () => this.loadDossier(),
       graph: () => this.loadGraph(), patterns: () => this.loadPatterns(), timeline: () => this.loadTimeline(),
       registry: () => this.loadRegistry(), export: () => this.loadExport() })[this.view]();
  },

  emptyState(ic, cls, title, text, action = '') {
    return `<div class="empty"><div class="empty-ico ${cls}">${icon(ic, 'xxl')}</div><h3>${esc(title)}</h3><p>${text}</p>${action}</div>`;
  },
  noData() {
    return this.emptyState('hub', 'c-purple', 'Nessuna analisi ancora',
      'Avvia l\'analisi forense dei documenti del fascicolo dalla Panoramica: l\'IA locale estrae soggetti, relazioni e flussi e costruisce la rete investigativa.',
      `<button class="btn primary lg" onclick="FX.setView('overview')" style="margin-top:10px">${icon('space_dashboard')}Vai alla Panoramica</button>`);
  },

  // ── Panoramica ────────────────────────────────────────────────────────────
  async loadOverview() {
    const box = $('#fx-overview-body');
    let o;
    try { o = await FT.api(`/api/forensic/${FT.fid}/overview`); } catch (e) { box.innerHTML = ''; return; }
    this.ov = o;
    const stat = (ic, cls, label, value, note = '') => `<div class="stat"><div class="stat-top"><span class="stat-ico ${cls}">${icon(ic)}</span>${label}</div>
      <div class="stat-value">${value}</div>${note ? `<div class="stat-note">${note}</div>` : ''}</div>`;
    const jobCard = this.job ? `<div style="margin-bottom:16px">${progressBlock('fx-job', this.job.label, this.job.fraction, this.job.message || 'Avvio…',
        `<span class="pblock-actions"><button class="btn plain sm-btn" onclick="FT.showLog('${this.job.id}', 'Analisi forense')">${icon('receipt_long')}Log</button>
         <button class="btn plain sm-btn danger" onclick="FX.cancelJob()">${icon('stop_circle')}Interrompi</button></span>`)}</div>` : '';
    let action = '';
    if (!this.job) {
      if (o.documenti_da_analizzare) {
        action = `<div class="job-card"><div class="stat-ico c-purple" style="width:40px;height:40px;border-radius:10px;display:grid;place-items:center">${icon('neurology', 'lg')}</div>
          <div class="grow"><div style="font-weight:600">${o.documenti_da_analizzare} ${o.documenti_da_analizzare === 1 ? 'documento da analizzare' : 'documenti da analizzare'}</div>
          <div class="jc-msg">Estrazione di soggetti, relazioni e flussi con ${esc(FT.model || '')}, poi deduzioni incrociate con gli atti già analizzati. Può richiedere alcuni minuti per documento.</div></div>
          <button class="btn primary lg" onclick="FX.analyze()">${icon('play_arrow')}Analizza</button></div>`;
      } else if (o.documenti_in_lavorazione) {
        action = `<div class="banner info">${icon('hourglass_top')}<div>${o.documenti_in_lavorazione} documenti in preparazione (conversione/OCR). Potrai analizzarli appena pronti.</div></div>`;
      } else if (!FT.docs.length) {
        action = `<div class="banner info">${icon('info')}<div>Il fascicolo è vuoto: trascina file o cartelle nella barra laterale per iniziare.</div></div>`;
      }
    }
    const rep = o.storico.length ? o.storico.map((s, i) => `<div class="report-item ${i === 0 ? 'open' : ''}">
        <div class="report-head" onclick="this.parentElement.classList.toggle('open')">
          <span class="ms chev">chevron_right</span>
          <div class="doc-ico t-pdf" style="width:30px;height:30px">${icon('description')}</div>
          <div class="grow"><div style="font-weight:600">${esc(s.file)}</div>
          <div class="faint" style="font-size:11.5px">Analizzato il ${esc(s.timestamp)} · ${fmtInt(s.caratteri)} caratteri · ${esc(s.modello || '')}${s.secondi ? ` · ${Math.round(s.secondi / 60)} min` : ''}</div></div>
        </div><div class="report-body"><div class="md">${FT.md(s.analisi)}</div></div></div>`).join('')
      : '';
    box.innerHTML = `
      <div class="page-head"><div><h2>Panoramica dell'indagine</h2><p>Fascicolo «${esc(FT.fascicolo.nome)}» · ${o.documenti_analizzati} atti analizzati</p></div>
        ${o.documenti_analizzati ? `<button class="btn plain" onclick="FX.reset()">${icon('restart_alt')}Azzera analisi</button>` : ''}</div>
      ${jobCard}${action}
      <div class="tile-grid" style="margin-bottom:22px">
        ${stat('group', 'c-blue', 'Entità unificate', fmtInt(o.entita))}
        ${stat('share', 'c-indigo', 'Relazioni probatorie', fmtInt(o.relazioni))}
        ${stat('join_inner', 'c-teal', 'Soggetti trasversali', fmtInt(o.soggetti_trasversali), 'Presenti in 2 o più atti')}
        ${stat('euro', 'c-green', 'Volume tracciato', fmtEuro(o.volume_euro), `${fmtInt(o.transazioni)} operazioni con importo`)}
        ${stat('sync', o.flussi_circolari ? 'c-red' : 'c-gray', 'Flussi circolari', fmtInt(o.flussi_circolari))}
        ${stat('rule', o.incongruenze ? 'c-orange' : 'c-gray', 'Incongruenze', fmtInt(o.incongruenze))}
      </div>
      ${o.storico.length ? `<h3 style="margin-bottom:10px">Report per atto</h3>${rep}` : (o.documenti_analizzati ? '' : (FT.docs.length && !this.job ? '' : ''))}`;
  },

  async analyze(docIds) {
    try {
      const r = await FT.api(`/api/forensic/${FT.fid}/analyze`, { body: { model: FT.model, doc_ids: docIds } });
      this.job = { id: r.job_id, label: `Analisi forense di ${r.count} ${r.count === 1 ? 'documento' : 'documenti'}`, fraction: 0 };
      this.loadOverview();
      this.job.stream = FT.stream(r.job_id, {
        progress: (ev) => {
          this.job.fraction = ev.fraction; this.job.message = ev.message;
          setProgress($('#fx-job'), ev.fraction, ev.message);
        },
        fatal_error: (ev) => FT.toast('Analisi interrotta: ' + ev.message, 'error', 8000),
      }, () => { this.job = null; FT.refreshDocs(); this.loadOverview(); FT.toast('Analisi forense completata', 'check_circle'); });
    } catch (e) { FT.toast(e.message, 'error'); }
  },
  cancelJob() { if (this.job?.stream) this.job.stream.cancel(); },
  async reset() {
    if (!await FT.confirm('Azzerare l\'analisi forense?', 'Grafo, report per atto, chat e dossier verranno eliminati. I documenti restano nel fascicolo e potrai rianalizzarli.', 'Azzera', true)) return;
    await FT.api(`/api/forensic/${FT.fid}/reset`, { method: 'POST' });
    FT.refreshDocs(); this.loadOverview();
  },

  // ── Chat forense ──────────────────────────────────────────────────────────
  updateChatSend() {
    const btn = $('#fc-send');
    btn.classList.toggle('stop', !!this.chatRunning);
    btn.querySelector('.ms').textContent = this.chatRunning ? 'stop' : 'arrow_upward';
    btn.disabled = !this.chatRunning && !$('#fc-input').value.trim();
  },
  chatMsg(m) {
    if (m.role === 'user') return `<div class="msg user"><div class="bubble">${esc(m.content)}</div></div>`;
    const fact = m.riscontro ? `<div class="banner info" style="margin-bottom:10px">${icon('route')}<div><strong>Riscontro deterministico sul grafo</strong>
      <div class="selectable" style="white-space:pre-wrap;margin-top:4px;font-size:12px">${esc(m.riscontro)}</div></div></div>` : '';
    return `<div class="msg assistant forensic"><div class="avatar">${icon('hub')}</div><div class="answer">${fact}<div class="md">${FT.md(m.content)}</div>
      ${m.secondi ? `<div class="meta-line">${icon('memory', 'xs')}${esc(m.modello || '')} · ${String(m.secondi).replace('.', ',')} s</div>` : ''}</div></div>`;
  },
  async loadChat() {
    $('#fx-actions').innerHTML = `<button class="btn plain" onclick="FX.clearChat()">${icon('delete_sweep')}Nuova conversazione</button>`;
    if (this.chatRunning) return;
    this.chat = (await FT.api(`/api/forensic/${FT.fid}/chat`)).messaggi || [];
    const box = $('#fc-messages');
    box.innerHTML = this.chat.length ? this.chat.map(m => this.chatMsg(m)).join('')
      : `<div class="welcome"><div class="w-ico c-purple">${icon('forum', 'xxl')}</div><h2>Chat investigativa</h2>
         <p>Interroga la rete d'indagine: contatti tra soggetti e partecipazioni vengono verificati matematicamente sul grafo prima della risposta del modello.</p></div>`;
    $('#fc-scroll').scrollTop = 1e9;
  },
  async clearChat() { await FT.api(`/api/forensic/${FT.fid}/chat`, { method: 'DELETE' }); this.loadChat(); },
  async sendChat() {
    const input = $('#fc-input');
    const q = input.value.trim();
    if (!q || this.chatRunning) return;
    input.value = ''; RC.autosize(input);
    const box = $('#fc-messages');
    if (!this.chat?.length) box.innerHTML = '';
    box.insertAdjacentHTML('beforeend', this.chatMsg({ role: 'user', content: q }));
    const live = { role: 'assistant', content: '', riscontro: '' };
    box.insertAdjacentHTML('beforeend', `<div id="fc-live">${this.chatMsg(live)}</div>`);
    const el = $('#fc-live');
    $('.md', el).innerHTML = progressBlock('fc-prog', 'Chat investigativa', 0.05, 'Analisi della rete in corso…');
    let ntok = 0;
    $('#fc-scroll').scrollTop = 1e9;
    try {
      const r = await FT.api(`/api/forensic/${FT.fid}/chat`, { body: { message: q, model: FT.model } });
      this.chatRunning = FT.stream(r.job_id, {
        graph_fact: (ev) => { live.riscontro = ev.text; el.innerHTML = this.chatMsg(live); $('.md', el).innerHTML = progressBlock('fc-prog', 'Chat investigativa', 0.25, 'Riscontro sul grafo calcolato · il modello sta leggendo…'); },
        token: (ev) => {
          live.content += ev.text; ntok++;
          $('.md', el).innerHTML = progressBlock('fc-prog', 'Chat investigativa', 0.3 + 0.68 * Math.min(1, ntok / 500), `Scrittura della risposta · ${ntok} token`) + FT.md(live.content);
          $('#fc-scroll').scrollTop = 1e9;
        },
        fatal_error: (ev) => { live.content = 'Errore: ' + ev.message; },
      }, () => { this.chatRunning = null; this.updateChatSend(); this.loadChat(); });
      this.updateChatSend();
    } catch (e) { el.remove(); FT.toast(e.message, 'error'); }
  },

  // ── Dossier ───────────────────────────────────────────────────────────────
  async loadDossier() {
    const box = $('#fx-dossier-body');
    const d = await FT.api(`/api/forensic/${FT.fid}/dossier`);
    const analyzed = this.ov ? this.ov.documenti_analizzati : 1;
    $('#fx-actions').innerHTML = `
      ${d.testo ? `<button class="btn" onclick="FT.saveAs('Dossier_Forense_${new Date().toISOString().slice(0, 10)}.md','dossier')">${icon('download')}Esporta .md</button>` : ''}
      <button class="btn primary" id="btn-dossier" ${this.dossierJob || !analyzed ? 'disabled' : ''} onclick="FX.makeDossier()">${icon('gavel')}${d.testo ? 'Aggiorna dossier' : 'Compila dossier'}</button>`;
    if (this.dossierJob) return;
    if (!d.testo) {
      box.innerHTML = this.emptyState('gavel', 'c-purple', 'Dossier forense CTU',
        'Relazione peritale integrata in 7 capitoli che incrocia tutti gli atti analizzati: convergenze, cabina di regia, flussi finanziari, modus operandi, incongruenze, qualificazione giuridica, dispositivo operativo.',
        analyzed ? `<button class="btn primary lg" style="margin-top:10px" onclick="FX.makeDossier()">${icon('gavel')}Compila dossier</button>` : '<p class="faint">Analizza prima almeno un documento.</p>');
      return;
    }
    box.innerHTML = `<div class="faint" style="margin-bottom:10px;font-size:12px">${icon('schedule', 'xs')} Redatto il ${esc(d.ts)} con ${esc(d.modello || '')}</div>
      <div class="dossier-paper"><div class="md">${FT.md(d.testo)}</div></div>`;
  },
  async makeDossier() {
    try {
      const r = await FT.api(`/api/forensic/${FT.fid}/dossier`, { body: { model: FT.model } });
      this.dossierJob = r.job_id;
      $('#btn-dossier') && ($('#btn-dossier').disabled = true);
      $('#fx-dossier-body').innerHTML = progressBlock('dj', 'Redazione del dossier CTU', 0.02, 'Il modello sta leggendo il fascicolo e la rete d\'indagine…',
        `<span class="pblock-actions"><button class="btn plain sm-btn" onclick="FT.showLog('${r.job_id}', 'Dossier CTU')">${icon('receipt_long')}Log</button>
         <button class="btn plain sm-btn danger" onclick="FT.api('/api/jobs/${r.job_id}/cancel',{method:'POST'})">${icon('stop_circle')}Interrompi</button></span>`);
      FT.stream(r.job_id, {
        progress: (ev) => setProgress($('#dj'), ev.fraction, ev.message),
        fatal_error: (ev) => FT.toast('Dossier interrotto: ' + ev.message, 'error'),
      }, () => { this.dossierJob = null; if (this.view === 'dossier') this.loadDossier(); FT.toast('Dossier completato', 'check_circle'); });
    } catch (e) { FT.toast(e.message, 'error'); }
  },

  // ── Grafo ─────────────────────────────────────────────────────────────────
  async loadGraph() {
    const g = await FT.api(`/api/forensic/${FT.fid}/graph`);
    const container = $('#graph');
    if (this.network) { this.network.destroy(); this.network = null; }
    $('#graph-panel').classList.add('hidden');
    if (!g.nodi.length) { container.innerHTML = `<div style="position:absolute;inset:0;display:grid;place-items:center">${this.noData()}</div>`; return; }
    container.innerHTML = '';
    const dark = FT.isDark();
    const fg = dark ? '#F5F5F7' : '#1D1D1F', sub = dark ? 'rgba(235,235,245,.6)' : 'rgba(60,60,67,.65)';
    const inCycle = new Set((g.cicli || []).flat());
    const nodes = new vis.DataSet(g.nodi.map(n => {
      const t = tipo(n.tipo);
      return { id: n.id, label: n.label, shape: 'dot', size: n.size, raw: n,
        color: { background: t.color, border: inCycle.has(n.id) ? '#FF453A' : t.color, highlight: { background: t.color, border: fg } },
        borderWidth: inCycle.has(n.id) ? 3 : 1.5,
        font: { color: fg, size: 13, face: '-apple-system, SF Pro Text', strokeWidth: 3, strokeColor: dark ? '#1E1E20' : '#FBFBFD' } };
    }));
    const edges = new vis.DataSet(g.archi.map(e => ({ id: e.id, from: e.from, to: e.to, label: e.label, raw: e,
      arrows: { to: { enabled: true, scaleFactor: 0.6 } }, width: e.valore > 0 ? 2.2 : 1.2,
      color: { color: e.valore > 0 ? (dark ? '#30D158' : '#28A745') : (dark ? 'rgba(235,235,245,.35)' : 'rgba(60,60,67,.35)'), highlight: dark ? '#0A84FF' : '#007AFF' },
      font: { color: sub, size: 10, face: '-apple-system', strokeWidth: 3, strokeColor: dark ? '#1E1E20' : '#FBFBFD', align: 'middle' },
      smooth: { type: 'dynamic' } })));
    this.network = new vis.Network(container, { nodes, edges }, {
      physics: { solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -90, springLength: 160, springConstant: 0.06 }, stabilization: { iterations: 220 } },
      interaction: { hover: true, navigationButtons: false, keyboard: true, tooltipDelay: 150 },
    });
    this.network.on('stabilizationIterationsDone', () => this.network.setOptions({ physics: { enabled: false } }));
    this.network.on('click', (p) => {
      if (p.nodes.length) this.nodePanel(nodes.get(p.nodes[0]).raw, g);
      else $('#graph-panel').classList.add('hidden');
    });
    $('#graph-legend').innerHTML = Object.entries(TIPO).map(([k, t]) => `<span class="chip ${t.cls}">${icon(t.ic)}${t.label}</span>`).join('')
      + (inCycle.size ? `<span class="chip c-red">${icon('sync')}In flusso circolare</span>` : '');
    const search = $('#graph-search');
    search.oninput = () => {
      const q = search.value.trim().toLowerCase();
      if (!q) return;
      const hit = g.nodi.find(n => n.label.toLowerCase().includes(q));
      if (hit) { this.network.selectNodes([hit.id]); this.network.focus(hit.id, { scale: 1.2, animation: { duration: 400 } }); }
    };
    $('#fx-actions').innerHTML = `<span class="faint" style="font-size:12px;margin-right:8px">${g.nodi.length} entità · ${g.archi.length} relazioni</span>
      <button class="btn" onclick="FX.network && FX.network.fit({animation:{duration:400}})">${icon('fit_screen')}Adatta</button>
      <button class="btn" onclick="FX.network && FX.network.setOptions({physics:{enabled:true}})">${icon('scatter_plot')}Riorganizza</button>`;
  },
  nodePanel(n, g) {
    const t = tipo(n.tipo);
    const out = g.archi.filter(e => e.from === n.id), inn = g.archi.filter(e => e.to === n.id);
    const rel = (e, dir) => `<div style="padding:6px 0;border-bottom:.5px solid var(--separator);font-size:12px">
      <div style="display:flex;align-items:center;gap:4px">${icon(dir === 'out' ? 'arrow_outward' : 'call_received', 'xs')}<strong>${esc(e.label)}</strong></div>
      <div>${esc(dir === 'out' ? e.to : e.from)}</div>${e.dettagli ? `<div class="faint">${esc(e.dettagli)}</div>` : ''}
      <div class="faint" style="font-size:11px">${icon('description', 'xs')} ${esc(e.fonte)}</div></div>`;
    const p = $('#graph-panel');
    p.innerHTML = `<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px"><div class="stat-ico ${t.cls}" style="width:34px;height:34px;border-radius:9px;display:grid;place-items:center">${icon(t.ic)}</div>
      <div style="min-width:0;flex:1"><div style="font-weight:600" class="selectable">${esc(n.label)}</div><div class="faint" style="font-size:11.5px">${t.label}${n.cf_piva ? ' · ' + esc(n.cf_piva) : ''}</div></div>
      <button class="icon-btn" onclick="this.closest('.graph-panel').classList.add('hidden')">${icon('close')}</button></div>
      <div class="group-label">Atti (${n.fonti.length})</div><div style="display:flex;flex-wrap:wrap;gap:4px">${n.fonti.map(f => `<span class="chip c-gray">${esc(f)}</span>`).join('')}</div>
      ${out.length ? `<div class="group-label">Relazioni in uscita (${out.length})</div>${out.map(e => rel(e, 'out')).join('')}` : ''}
      ${inn.length ? `<div class="group-label">Relazioni in entrata (${inn.length})</div>${inn.map(e => rel(e, 'in')).join('')}` : ''}`;
    p.classList.remove('hidden');
  },

  // ── Pattern AML ───────────────────────────────────────────────────────────
  async loadPatterns() {
    const box = $('#fx-patterns-body');
    const p = await FT.api(`/api/forensic/${FT.fid}/patterns`);
    if (!p.centralita.length) { box.innerHTML = this.noData(); return; }
    const s = p.schemi;
    const chain = (arr) => `<span class="chain">${arr.map(esc).join(` ${icon('arrow_forward')} `)}</span>`;
    box.innerHTML = `
      <div class="page-head"><div><h2>Pattern AML</h2><p>Centralità NetworkX · titolari effettivi FollowTheMoney (OCCRP) · riconciliazione finanziaria DuckDB</p></div></div>
      <div class="card"><div class="card-title">${icon('crown')}<h3>Dominus e nodi ponte (betweenness centrality)</h3></div>
        <div class="table-wrap" style="box-shadow:none;max-height:none"><table class="grid">
        <thead><tr><th>Soggetto</th><th>Profilo investigativo</th><th class="num">Betweenness</th><th class="num">In</th><th class="num">Out</th><th class="num">Atti</th><th>CF / P.IVA</th></tr></thead>
        <tbody>${p.centralita.map(c => `<tr><td><strong>${esc(c.nodo)}</strong></td><td>${esc(c.profilo_forense)}</td>
          <td class="num">${Number(c.betweenness).toFixed(4)}</td><td class="num">${c.in_degree}</td><td class="num">${c.out_degree}</td><td class="num">${c.num_atti}</td><td class="mono">${esc(c.cf_piva || '')}</td></tr>`).join('')}</tbody></table></div></div>

      <div class="card"><div class="card-title">${icon('account_tree')}<h3>Titolari effettivi (UBO) e catene di controllo</h3></div>
        ${p.ubo.length ? `<div class="subject-grid">${p.ubo.map(u => `<div class="subject" style="box-shadow:none;background:var(--grouped)">
          <div class="s-head"><div class="s-ico c-green">${icon('domain')}</div><div><div class="s-name">${esc(u.azienda)}</div><div class="s-sub">${esc(u.cf_piva || '')}</div></div></div>
          ${u.titolari_effettivi.length ? `<div class="group-label">Titolari effettivi / soci</div>${u.titolari_effettivi.map(te => `<div style="font-size:12px;margin-bottom:6px">
            <strong>${esc(te.persona)}</strong> <span class="faint">${esc(te.cf || '')}</span> — ${esc(te.ruolo || '')} ${esc(te.percentuale || '')}<div>${chain(te.catena || [])}</div></div>`).join('')}` : ''}
          ${u.amministratori.length ? `<div class="group-label">Organo amministrativo</div>${u.amministratori.map(a => `<div style="font-size:12px">${esc(a.nominativo)} <span class="faint">${esc(a.cf || '')}</span> — ${esc(a.ruolo || '')}</div>`).join('')}` : ''}
        </div>`).join('')}</div>` : '<p class="faint">Nessuna compagine proprietaria multilivello rilevata.</p>'}</div>

      <div class="card"><div class="card-title">${icon('account_balance')}<h3>Matrice di riconciliazione finanziaria</h3></div>
        ${p.finanza.length ? `<div class="table-wrap" style="box-shadow:none"><table class="grid"><thead><tr><th>Soggetto</th><th>Tipo</th><th class="num">Entrate</th><th class="num">Uscite</th><th class="num">Saldo netto</th><th class="num">Op. in</th><th class="num">Op. out</th></tr></thead>
          <tbody>${p.finanza.map(f => `<tr><td><strong>${esc(f.soggetto)}</strong></td><td>${tipo(f.tipo).label}</td><td class="num">${fmtEuro(f.entrate_euro)}</td><td class="num">${fmtEuro(f.uscite_euro)}</td>
          <td class="num" style="color:${f.sbilancio_netto_euro < 0 ? 'var(--red)' : 'var(--green)'}">${fmtEuro(f.sbilancio_netto_euro)}</td><td class="num">${f.n_operazioni_in}</td><td class="num">${f.n_operazioni_out}</td></tr>`).join('')}</tbody></table></div>`
          : '<p class="faint">Nessuna movimentazione con importo numerico certo.</p>'}</div>

      <div class="pattern-grid" style="margin-top:16px">
        <div class="card" style="margin:0"><div class="card-title">${icon('sync')}<h3>Flussi circolari</h3></div>
          ${s.flussi_circolari.length ? s.flussi_circolari.map(c => `<div class="alert-item">${icon('sync', 'st-err')}${chain([...c, c[0]])}</div>`).join('') : '<p class="faint">Nessun circuito chiuso di rientro fondi.</p>'}
          ${s.scatole_cinesi.length ? `<div class="group-label">Scatole cinesi</div>${s.scatole_cinesi.map(c => `<div class="alert-item">${icon('inventory_2', 'st-warn')}${chain(c)}</div>`).join('')}` : ''}</div>
        <div class="card" style="margin:0"><div class="card-title">${icon('rule')}<h3>Incongruenze tra atti</h3></div>
          ${s.incongruenze.length ? s.incongruenze.slice(0, 12).map(i => `<div class="alert-item">${icon('warning', 'st-warn')}<div><strong>${esc(i.soggetto)}</strong> — ${esc(i.tipo)}
            <div class="faint">${esc(i.dettagli)}</div><div class="faint" style="font-size:11px">${(i.fonti || []).map(esc).join(' · ')}</div></div></div>`).join('') : '<p class="faint">Nessuna contraddizione evidente.</p>'}</div>
      </div>`;
  },

  // ── Timeline ──────────────────────────────────────────────────────────────
  async loadTimeline() {
    const box = $('#fx-timeline-body');
    const t = await FT.api(`/api/forensic/${FT.fid}/timeline`);
    if (!t.eventi.length) { box.innerHTML = this.noData(); return; }
    box.innerHTML = `<div class="page-head"><div><h2>Timeline</h2><p>${t.eventi.length} eventi ricostruiti dagli atti</p></div></div>
      <div class="timeline">${t.eventi.map(e => `<div class="tl-item"><div class="tl-card">
        <div class="tl-date">${esc(e.data)}</div>
        <div class="tl-flow">${esc(e.da)} ${icon('arrow_forward')} <span class="chip c-indigo">${esc(e.tipo)}</span> ${icon('arrow_forward')} ${esc(e.a)}
          ${e.valore ? `<span class="chip c-green">${fmtEuro(e.valore)}</span>` : ''}</div>
        ${e.dettagli ? `<div class="muted selectable" style="font-size:12.5px">${esc(e.dettagli)}</div>` : ''}
        <div class="faint" style="font-size:11px;margin-top:4px">${icon('description', 'xs')} ${esc(e.atto)}</div></div></div>`).join('')}</div>`;
  },

  // ── Anagrafiche + SQL ─────────────────────────────────────────────────────
  async loadRegistry() {
    const box = $('#fx-registry-body');
    const r = await FT.api(`/api/forensic/${FT.fid}/registry`);
    if (!r.soggetti.length) { box.innerHTML = this.noData(); return; }
    const subj = (s, extra = '') => { const t = tipo(s.tipo); return `<div class="subject"><div class="s-head"><div class="s-ico ${t.cls}">${icon(t.ic)}</div>
      <div style="min-width:0"><div class="s-name selectable">${esc(s.id || s.soggetto)}</div><div class="s-sub">${t.label} · ${esc(s.cf_piva || 'CF/P.IVA non censito')}</div></div></div>
      ${extra}<div class="s-docs">${(s.fonti || s.atti || []).map(f => `<span class="chip c-gray">${icon('description')}${esc(f)}</span>`).join('')}</div></div>`; };
    const ftm = Object.entries((r.ftm || {}).per_schema || {});
    box.innerHTML = `
      <div class="page-head"><div><h2>Anagrafiche</h2><p>${r.soggetti.length} soggetti unificati (fusione per CF/P.IVA e nome normalizzato)</p></div></div>
      ${r.trasversali.length ? `<h3 style="margin-bottom:10px">${icon('join_inner', 'sm')} Soggetti trasversali · presenti in più atti</h3>
        <div class="subject-grid" style="margin-bottom:24px">${r.trasversali.map(t => subj(t, `<div class="faint" style="font-size:11.5px;margin-top:6px">${t.grado} connessioni · ${t.num_atti} atti</div>`)).join('')}</div>` : ''}
      <h3 style="margin-bottom:10px">Registro anagrafico unificato</h3>
      <div class="subject-grid" style="margin-bottom:24px">${r.soggetti.map(s => subj(s)).join('')}</div>
      ${ftm.length ? `<h3 style="margin-bottom:10px">Entità FollowTheMoney (OCCRP)</h3><div class="tile-grid" style="margin-bottom:24px">
        ${ftm.map(([k, v]) => `<div class="stat"><div class="stat-top">${esc(k)}</div><div class="stat-value">${fmtInt(v)}</div></div>`).join('')}</div>` : ''}
      <div class="card sql-box"><div class="card-title">${icon('database')}<h3>Console SQL (DuckDB)</h3></div>
        <p class="muted" style="margin:-4px 0 10px;font-size:12px">Tabelle <code>entita</code>(id, nome, tipo, cf_piva, ftm_schema, num_fonti, fonti) e <code>relazioni</code>(sorgente, destinazione, tipo, dettagli, fonte, data_evento, valore_numerico).</p>
        <textarea class="input" id="sql-q" rows="3">SELECT nome, tipo, cf_piva, num_fonti FROM entita ORDER BY num_fonti DESC, nome LIMIT 20</textarea>
        <div style="margin:10px 0"><button class="btn primary" onclick="FX.runSql()">${icon('play_arrow')}Esegui</button></div>
        <div id="sql-out"></div></div>`;
  },
  async runSql() {
    const out = $('#sql-out');
    try {
      const r = await FT.api(`/api/forensic/${FT.fid}/sql`, { body: { query: $('#sql-q').value } });
      const rows = r.righe || [];
      if (!rows.length || rows[0].errore) { out.innerHTML = `<p class="faint">${esc(rows[0]?.errore || 'Nessun record restituito.')}</p>`; return; }
      const cols = Object.keys(rows[0]);
      out.innerHTML = `<div class="table-wrap" style="box-shadow:none"><table class="grid"><thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(rw => `<tr>${cols.map(c => `<td class="selectable">${esc(rw[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    } catch (e) { out.innerHTML = `<div class="banner err">${icon('error')}<div>${esc(e.message)}</div></div>`; }
  },

  // ── Esporta ───────────────────────────────────────────────────────────────
  loadExport() {
    const d = new Date().toISOString().slice(0, 10);
    const card = (ic, cls, title, sub, file, tipo) => `<button class="export-card" onclick="FT.saveAs('${file}','${tipo}')">
      <div class="ex-ico ${cls}">${icon(ic)}</div><div><strong>${title}</strong><span>${sub}</span></div></button>`;
    $('#fx-export-body').innerHTML = `<div class="page-head"><div><h2>Esporta</h2><p>Formati standard per perizie, strumenti investigativi e archiviazione.</p></div></div>
      <div class="export-grid">
        ${card('public', 'c-blue', 'FollowTheMoney (OCCRP)', 'JSON Lines per Aleph e strumenti FtM', `indagine_${d}.ftm.json`, 'ftm')}
        ${card('hub', 'c-indigo', 'Cytoscape', 'Grafo .relazioni.json (Pdf_Relations)', `indagine_${d}.relazioni.json`, 'cytoscape')}
        ${card('account_tree', 'c-teal', 'Mermaid · verticale', 'Diagramma per Markdown e Obsidian', `indagine_${d}_TD.mmd`, 'mermaid_td')}
        ${card('swap_horiz', 'c-teal', 'Mermaid · orizzontale', 'Diagramma da sinistra a destra', `indagine_${d}_LR.mmd`, 'mermaid_lr')}
        ${card('gavel', 'c-purple', 'Dossier CTU', 'Relazione peritale in Markdown', `Dossier_Forense_${d}.md`, 'dossier')}
        ${card('save', 'c-gray', 'Sessione completa', 'Grafo, report, chat e dossier in JSON', `sessione_forense_${d}.json`, 'sessione')}
      </div>`;
  },
};

window.FX = FX;
document.addEventListener('DOMContentLoaded', () => FX.init());

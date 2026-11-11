/* ════════════════════════════════════════════════════════════════════════════
   Area PDF — porting fedele del frontend di Pdf50 (Split PDF 50, Mattia Ianniello)
   Stessa logica e stessi flussi; cambiano solo grafica, dialoghi nativi e
   trascinamento con percorsi reali da Esplora file.
   ════════════════════════════════════════════════════════════════════════════ */
'use strict';

const PDF = {
  state: {
    sourcePath: null, folderName: null, outputPath: null, jobId: null, stream: null,
    currentStep: 0, totalFiles: 0, sourceIsTemp: false, busy: false,
    isPdfMode: false, pdfServerPath: null, pdfPages: null, resultPdfPath: null, postProcOp: null,
  },

  init() {
    $('#drop-zone').addEventListener('click', () => { if (!this.state.busy && !this.state.isPdfMode) this.selectSource(); });
    $('#btn-change-source').addEventListener('click', () => this.selectSource());
    $('#btn-output').addEventListener('click', () => this.selectOutput());
    $('#btn-start').addEventListener('click', () => this.state.isPdfMode ? this.startPdfOp() : this.startJob());
    $('#btn-cancel').addEventListener('click', () => this.cancelJob());
    $('#btn-reset').addEventListener('click', () => this.resetApp());
    $('#btn-reveal-output').addEventListener('click', () => this.state.outputPath && FT.api('/api/reveal', { body: { path: this.state.outputPath } }));
    $$('input[name="pdfop"]').forEach(r => r.addEventListener('change', () => this.updatePdfOpOptions()));
    $$('#postproc-btns [data-pp]').forEach(b => b.addEventListener('click', () => this.showPostProc(b.dataset.pp)));
    $('#btn-apply-postproc').addEventListener('click', () => this.applyPostProc());
    this.initRangeList('ranges-list');
    this.initRangeList('pp-ranges-list');
    this.updateStartButton();
    this.loadSystemInfo();
  },

  // ── Dipendenze (in Forensic Tools sono incluse: avviso solo in caso di problemi) ─
  async loadSystemInfo() {
    try {
      const info = await FT.api('/api/pdf/system-info');
      const missing = [];
      if (!info.tesseract_italian) missing.push('OCR Tesseract con lingua italiana');
      if (!info.ghostscript) missing.push('Ghostscript');
      const box = $('#deps-warning');
      if (!missing.length) { box.classList.add('hidden'); return; }
      box.className = 'banner warn';
      box.innerHTML = `${icon('warning')}<div><strong>Componenti non disponibili:</strong> ${missing.map(esc).join(', ')}.
        Alcune funzioni non saranno disponibili. Reinstalla Forensic Tools per ripristinarli.</div>`;
    } catch (e) { /* silenzioso */ }
  },

  // ── Sorgente ──────────────────────────────────────────────────────────────
  async selectSource() {
    if (this.state.sourceIsTemp && this.state.sourcePath) {
      FT.api('/api/pdf/cleanup-temp', { body: { path: this.state.sourcePath } }).catch(() => {});
      this.state.sourceIsTemp = false;
    }
    const n = FT.native();
    if (!n) return FT.toast('Funzione disponibile nell\'app', 'info');
    const path = await n.choose_folder('Seleziona la cartella da elaborare');
    if (path) await this.useFolder(path);
  },

  async useFolder(path) {
    try {
      const data = await FT.api('/api/pdf/scan', { body: { path } });
      this.state.sourcePath = data.path;
      this.state.folderName = data.folder_name;
      this.state.sourceIsTemp = false;
      this.exitPdfMode();
      this.showSourceInfo(data.file_count, data.folder_name, data.path);
      this.updateStartButton();
    } catch (e) { this.flashDrop(`Errore: ${e.message}`); }
  },

  /** File/cartelle trascinati da Esplora file (percorsi reali) */
  async onNativeDrop(paths) {
    if (this.state.busy || !paths.length) return;
    if ($('#setup-card').classList.contains('hidden')) return;
    this.state.busy = true;
    try {
      if (paths.length === 1) {
        const dir = await FT.api('/api/pdf/scan', { body: { path: paths[0] } }).catch(() => null);
        if (dir) {
          Object.assign(this.state, { sourcePath: dir.path, folderName: dir.folder_name, sourceIsTemp: false });
          this.exitPdfMode();
          this.showSourceInfo(dir.file_count, dir.folder_name, dir.path);
          this.updateStartButton();
          return;
        }
      }
      this.setDropStatus(`Preparazione di ${paths.length} file…`);
      const data = await FT.api('/api/pdf/prepare-files', { body: { paths } });
      if (data.is_pdf) this.enterPdfMode(data);
      else {
        this.state.sourcePath = data.tmp_dir;
        this.state.folderName = data.folder_name;
        this.state.sourceIsTemp = true;
        this.exitPdfMode();
        this.showSourceInfo(data.file_count, data.folder_name);
        this.updateStartButton();
      }
    } catch (e) {
      this.flashDrop(`Errore: ${e.message}`);
    } finally { this.state.busy = false; this.resetDropStatus(); }
  },

  setDropStatus(msg) {
    $('#drop-title').classList.add('hidden'); $('#drop-sub').classList.add('hidden');
    const el = $('#drop-status'); el.textContent = msg; el.classList.remove('hidden');
  },
  resetDropStatus() {
    $('#drop-title').classList.remove('hidden'); $('#drop-sub').classList.remove('hidden');
    const el = $('#drop-status'); el.textContent = ''; el.classList.add('hidden');
  },
  flashDrop(msg) { this.setDropStatus(msg); setTimeout(() => this.resetDropStatus(), 3000); },

  showSourceInfo(count, name, path) {
    $('#drop-zone').classList.add('hidden');
    $('#source-info').classList.remove('hidden');
    $('#source-icon').textContent = 'folder';
    $('#source-icon-wrap').className = 'si-ico c-blue';
    $('#source-path-display').textContent = name || path;
    $('#source-path-display').title = path || '';
    $('#source-count').textContent = `${count} file supportati trovati`;
  },

  // ── Modalità PDF diretta ──────────────────────────────────────────────────
  enterPdfMode(data) {
    Object.assign(this.state, { isPdfMode: true, pdfServerPath: data.path, pdfPages: data.pages, sourcePath: null, folderName: null, sourceIsTemp: false });
    $('#drop-zone').classList.add('hidden');
    $('#source-info').classList.remove('hidden');
    $('#source-icon').textContent = 'picture_as_pdf';
    $('#source-icon-wrap').className = 'si-ico c-red';
    $('#source-path-display').textContent = data.filename;
    $('#source-count').textContent = `${data.size_mb} MB${data.pages ? ' · ' + data.pages + ' pagine' : ''}`;
    $('#mode-section').classList.add('hidden');
    $('#pdf-ops-panel').classList.remove('hidden');
    $('#add-fascicolo-row').classList.add('hidden');
    $('#ocr-row').classList.add('hidden');
    if (data.pages) $('#range-total-label').textContent = `(totale: ${data.pages})`;
    $('#btn-start-label').textContent = 'Avvia elaborazione';
    if (!this.state.outputPath) this.setOutput(data.path.substring(0, data.path.lastIndexOf('/')));
    this.updatePdfOpOptions();
    this.updateStartButton();
  },
  exitPdfMode() {
    Object.assign(this.state, { isPdfMode: false, pdfServerPath: null, pdfPages: null });
    $('#mode-section').classList.remove('hidden');
    $('#pdf-ops-panel').classList.add('hidden');
    $('#add-fascicolo-row').classList.remove('hidden');
    $('#ocr-row').classList.remove('hidden');
    $('#btn-start-label').textContent = 'Avvia conversione';
  },

  // ── Range ─────────────────────────────────────────────────────────────────
  initRangeList(listId) { $('#' + listId).innerHTML = ''; this.addRangeRow(listId); },
  addRangeRow(listId) {
    const list = $('#' + listId);
    const row = document.createElement('div');
    row.className = 'range-row';
    row.innerHTML = `<span class="range-label"></span>
      <input type="number" class="input num range-from" placeholder="da" min="1"/>
      <span class="faint">—</span>
      <input type="number" class="input num range-to" placeholder="a" min="1"/>
      <button class="icon-btn btn-range-remove" title="Rimuovi">${icon('close', 'sm')}</button>`;
    row.querySelector('.btn-range-remove').addEventListener('click', () => { row.remove(); this.refreshRangeLabels(listId); });
    list.appendChild(row);
    this.refreshRangeLabels(listId);
  },
  refreshRangeLabels(listId) {
    const rows = $$('.range-row', $('#' + listId));
    rows.forEach((r, i) => {
      r.querySelector('.range-label').textContent = `Parte ${i + 1}`;
      r.querySelector('.btn-range-remove').style.visibility = rows.length === 1 ? 'hidden' : 'visible';
    });
  },
  collectRanges(listId) {
    const ranges = [];
    for (const row of $$('.range-row', $('#' + listId))) {
      const from = parseInt(row.querySelector('.range-from').value, 10);
      const to = parseInt(row.querySelector('.range-to').value, 10);
      if (isNaN(from) || isNaN(to) || from < 1 || to < from) return null;
      ranges.push([from, to]);
    }
    return ranges.length ? ranges : null;
  },
  collectNaming(radioName, customInputId) {
    const val = document.querySelector(`input[name="${radioName}"]:checked`)?.value || 'x_of_y';
    if (val === 'x') return { part_label: 'Parte', show_total: false };
    if (val === 'x_of_y') return { part_label: 'Parte', show_total: true };
    return { part_label: ($('#' + customInputId)?.value || '').trim() || 'Parte', show_total: true };
  },

  updatePdfOpOptions() {
    const op = document.querySelector('input[name="pdfop"]:checked')?.value || 'compress';
    $('#pdfopts-compress').classList.toggle('hidden', !(op === 'compress' || op === 'compress+split'));
    $('#pdfopts-split-size').classList.toggle('hidden', !(op === 'split-size' || op === 'compress+split'));
    $('#pdfopts-split-ranges').classList.toggle('hidden', op !== 'split-ranges');
  },

  // ── Destinazione ──────────────────────────────────────────────────────────
  async selectOutput() {
    const n = FT.native();
    if (!n) return FT.toast('Funzione disponibile nell\'app', 'info');
    const path = await n.choose_folder('Seleziona la cartella di destinazione');
    if (path) this.setOutput(path);
  },
  setOutput(path) {
    this.state.outputPath = path;
    const el = $('#output-path-display');
    el.textContent = path; el.title = path; el.classList.add('selected');
    this.updateStartButton();
  },
  updateStartButton() {
    $('#btn-start').disabled = this.state.isPdfMode ? !this.state.outputPath : !(this.state.sourcePath && this.state.outputPath);
  },

  // ── Avvio pipeline cartella ───────────────────────────────────────────────
  async startJob() {
    const mode = document.querySelector('input[name="mode"]:checked').value;
    let data;
    try {
      data = await FT.api('/api/pdf/start', { body: {
        source_path: this.state.sourcePath, output_path: this.state.outputPath, mode,
        source_is_temp: this.state.sourceIsTemp, folder_name: this.state.folderName || null,
        fid: FT.fid, add_to_fascicolo: $('#add-to-fascicolo').checked, ocr: $('#apply-ocr').checked,
      } });
    } catch (e) { return FT.toast('Impossibile avviare l\'elaborazione: ' + e.message, 'error'); }
    this.state.jobId = data.job_id;
    this.state.currentStep = 0;
    Object.assign(this.state, { overallPct: 0, folderIdx: 0, folderTotal: 0 });
    $('#progress-pct').textContent = '0%';
    $('#setup-card').classList.add('hidden');
    $('#progress-card').classList.remove('hidden');
    $('#steps-indicator').classList.remove('hidden');
    $('#btn-cancel').classList.remove('hidden');
    this.state.stream = FT.stream(data.job_id, { '*': (ev) => this.handleEvent(ev) });
  },

  // Avanzamento complessivo: peso delle 5 fasi di Pdf50 (e delle sottocartelle in modalità «Suddiviso»)
  STEP_W: { 1: [0, 0.04], 2: [0.04, 0.36], 3: [0.40, 0.48], 4: [0.88, 0.06], 5: [0.94, 0.06] },
  overall(stepFrac) {
    const st = this.state, [b, w] = this.STEP_W[st.currentStep] || [0, 0];
    const inFolder = b + w * Math.max(0, Math.min(1, stepFrac));
    const f = st.folderTotal ? ((st.folderIdx - 1) + inFolder) / st.folderTotal : inFolder;
    st.overallPct = Math.max(st.overallPct || 0, f);
    $('#progress-pct').textContent = pct(st.overallPct);
  },

  handleEvent(event) {
    switch (event.type) {
      case 'step': this.setActiveStep(event.step); $('#progress-step-label').textContent = event.label; this.overall(0); break;
      case 'scan_done': this.state.totalFiles = event.total; break;
      case 'progress': this.updateProgress(event); break;
      case 'split_progress': $('#progress-step-label').textContent = `Divisione: ${event.label || ''} (parte ${event.current} di ${event.total})`; break;
      case 'folder_start': this.state.folderIdx = event.current; this.state.folderTotal = event.total; this.state.currentStep = 2; this.overall(0); this.addLog(`── Cartella ${event.current}/${event.total}: "${event.folder}" (${event.file_count} file)`, 'info', event.ts); break;
      case 'log': this.addLog(event.message, event.level || 'info', event.ts); break;
      case 'done': this.handleDone(event); break;
      case 'fatal_error': this.handleFatalError(event); break;
    }
  },
  updateProgress(event) {
    if (event.step && event.step !== this.state.currentStep) this.setActiveStep(event.step);
    if (event.percent !== undefined) { $('#progress-bar').style.width = event.percent + '%'; this.overall(event.percent / 100); }
    if (event.file) $('#progress-current-file').textContent = `${event.operation}: ${event.file.split(/[\\/]/).pop()}`;
    if (event.current && event.total) $('#progress-count').textContent = `${event.current} / ${event.total}`;
  },
  setActiveStep(n) {
    for (let i = 1; i <= 5; i++) {
      const el = $(`#step-${i}`);
      el.classList.remove('active', 'done');
      if (i < n) el.classList.add('done'); else if (i === n) el.classList.add('active');
    }
    $$('.step-line').forEach((l, i) => l.classList.toggle('done', i < n - 1));
    this.state.currentStep = n;
  },
  addLog(message, level = 'info', ts = null) {
    if (!message || !message.trim()) return;
    const panel = $('#log-panel');
    const lvl = (message.startsWith('✓') || message.startsWith('✔')) ? 'success' : ({ warn: 'warning' }[level] || level);
    const entry = document.createElement('div');
    entry.className = `log-entry ${lvl}`;
    entry.innerHTML = `<span class="log-ts">${esc(ts || new Date().toLocaleTimeString('it-IT'))}</span><span class="log-msg">${esc(message)}</span>`;
    panel.appendChild(entry);
    panel.scrollTop = panel.scrollHeight;
  },
  clearLog() { $('#log-panel').innerHTML = ''; },

  handleDone(event) {
    this.state.overallPct = 1; $('#progress-pct').textContent = '100%';
    this.setActiveStep(6);
    $('#progress-bar').style.width = '100%';
    $('#progress-step-label').textContent = 'Completato';
    this.addLog('Elaborazione completata con successo.', 'success');
    $('#btn-cancel').classList.add('hidden');
    FT.refreshDocs();
    setTimeout(() => this.showResult(event), 700);
  },

  resultHead(ic, cls, title, sub) {
    return `<div class="result-head"><div class="rh-ico ${cls}">${icon(ic)}</div>
      <div><div class="result-title">${esc(title)}</div><div class="result-sub">${esc(sub)}</div></div></div>`;
  },
  stats(items) {
    return `<div class="result-stats">${items.map(([v, l]) => `<div class="rs"><div class="rs-v">${esc(v)}</div><div class="rs-l">${esc(l)}</div></div>`).join('')}</div>`;
  },
  partsList(parts, label = 'File creati') {
    return `<div class="group-label">${esc(label)}</div><div class="parts-list">${parts.map((p, i) => `
      <div class="part-item"><div class="part-num">${i + 1}</div><div><div class="part-name">${esc(p.name)}</div>
      <div class="part-meta">${p.size_mb} MB · ${p.num_pages} pagine (${esc(p.pages)})</div></div></div>`).join('')}</div>`;
  },
  errors(errors) {
    return `<div class="error-box"><div class="error-box-title">File non elaborati (${errors.length})</div>
      ${errors.slice(0, 20).map(e => `<div>• ${esc(e.file)}: ${esc(e.error)}</div>`).join('')}
      ${errors.length > 20 ? `<div>… e altri ${errors.length - 20} file</div>` : ''}</div>`;
  },

  showResult(event) {
    $('#progress-card').classList.add('hidden');
    $('#result-card').classList.remove('hidden');
    let html;
    if (event.mode === 'unified') {
      const isSplit = event.result_type === 'split';
      html = this.resultHead(isSplit ? 'content_cut' : 'check_circle', 'c-green',
        isSplit ? 'PDF creato e suddiviso' : 'PDF creato con successo', `Cartella di output: ${event.output_path}`)
        + this.stats([[`${event.size_mb} MB`, 'Dimensione totale'], [event.total_pages || '—', 'Pagine totali'],
          [isSplit ? event.total_parts : 1, isSplit ? 'Parti create' : 'File creato']]);
      if (isSplit && event.parts?.length) html += this.partsList(event.parts);
    } else {
      const results = event.results || [];
      const totalParts = results.reduce((s, r) => s + (r.result_type === 'split' ? r.total_parts : 1), 0);
      html = this.resultHead('check_circle', 'c-green', `${results.length} PDF creati`, `Cartella di output: ${event.output_path}`)
        + this.stats([[results.length, 'Sottocartelle'], [totalParts, 'File PDF totali'], [(event.errors || []).length, 'File saltati']]);
      if (results.length) html += `<div class="group-label">Riepilogo per cartella</div><div class="parts-list">${results.map((r, i) => `
        <div class="part-item"><div class="part-num">${i + 1}</div><div><div class="part-name">${esc(r.folder)}</div>
        <div class="part-meta">${r.size_mb} MB · ${r.total_pages || '—'} pagine${r.result_type === 'split' ? ' · ' + r.total_parts + ' parti' : ''}</div></div></div>`).join('')}</div>`;
    }
    if ((event.errors || []).length) html += this.errors(event.errors);
    if ($('#add-to-fascicolo').checked && FT.fid) {
      html += `<div class="banner info" style="margin-top:14px">${icon('folder_open')}<div>I documenti convertiti sono stati aggiunti al fascicolo
        <strong>«${esc(FT.fascicolo?.nome || '')}»</strong> e sono in indicizzazione per Ricerca e Forensic AI.</div></div>`;
    }
    $('#result-content').innerHTML = html;
    if (event.mode === 'unified' && event.result_type === 'single' && event.file) {
      this.state.resultPdfPath = event.file;
      $('#postproc-section').classList.remove('hidden');
      this.setupPostProcBtns(null);
    } else $('#postproc-section').classList.add('hidden');
    this.attachLogToResult();
  },

  attachLogToResult() {
    const panel = $('#log-panel'), section = $('#result-log-section');
    const total = $$('.log-entry', panel).length;
    if (!total) return;
    const issues = $$('.log-entry.error, .log-entry.warning', panel).length;
    section.innerHTML = `<div class="banner ${issues ? 'warn' : 'info'}" style="margin-top:16px;margin-bottom:0;align-items:center">
      ${icon(issues ? 'warning' : 'task_alt')}<div style="flex:1">${issues ? `${issues} ${issues === 1 ? 'segnalazione' : 'segnalazioni'} durante l'elaborazione` : 'Elaborazione completata senza avvisi'}</div>
      <button class="btn plain" data-toggle>Mostra log</button></div>`;
    const clone = panel.cloneNode(true);
    clone.removeAttribute('id');
    clone.classList.add('hidden');
    clone.style.cssText = 'margin-top:6px;border-radius:10px;box-shadow:inset 0 0 0 .5px var(--separator-strong)';
    section.appendChild(clone);
    $('[data-toggle]', section).addEventListener('click', (e) => {
      const hidden = clone.classList.toggle('hidden');
      e.currentTarget.textContent = hidden ? 'Mostra log' : 'Nascondi log';
    });
  },

  handleFatalError(event) {
    this.addLog(`ERRORE CRITICO: ${event.message}`, 'error');
    $('#progress-step-label').textContent = 'Errore';
    $('#btn-cancel').classList.add('hidden');
    $('#result-content').innerHTML = this.resultHead('error', 'c-red', 'Errore durante l\'elaborazione', event.message)
      + (event.detail ? `<pre class="mono selectable" style="overflow:auto;max-height:200px;background:var(--grouped);padding:12px;border-radius:8px">${esc(event.detail)}</pre>` : '');
    setTimeout(() => { $('#progress-card').classList.add('hidden'); $('#result-card').classList.remove('hidden'); }, 800);
  },

  async cancelJob() {
    if (!this.state.jobId) return;
    if (!await FT.confirm('Annullare l\'elaborazione?', 'I file già elaborati non verranno salvati.', 'Annulla elaborazione', true)) return;
    FT.api(`/api/jobs/${this.state.jobId}/cancel`, { method: 'POST' }).catch(() => {});
    this.addLog('Annullamento richiesto…', 'warning');
  },

  // ── Operazioni PDF dirette ────────────────────────────────────────────────
  async startPdfOp() {
    const op = document.querySelector('input[name="pdfop"]:checked')?.value;
    const pdfPath = this.state.pdfServerPath, outputDir = this.state.outputPath;
    let ranges;
    if (op === 'split-ranges') {
      ranges = this.collectRanges('ranges-list');
      if (!ranges) return FT.toast('Inserisci range validi (es. da 1 a 80)', 'warning');
    }
    $('#setup-card').classList.add('hidden');
    $('#steps-indicator').classList.add('hidden');
    $('#progress-card').classList.remove('hidden');
    $('#btn-cancel').classList.add('hidden');
    const bar = $('#progress-bar'), label = $('#progress-step-label');
    const pctEl = $('#progress-pct');
    new MutationObserver(() => { pctEl.textContent = bar.style.width || '0%'; }).observe(bar, { attributes: true, attributeFilter: ['style'] });
    bar.style.width = '5%'; label.textContent = 'Elaborazione in corso…';
    try {
      let result, workingPdf = pdfPath;
      if (op === 'compress' || op === 'compress+split') {
        const quality = document.querySelector('input[name="quality"]:checked')?.value || 'ebook';
        label.textContent = 'Compressione con Ghostscript…'; bar.style.width = '40%';
        const data = await FT.api('/api/pdf/post/compress', { body: { pdf_path: pdfPath, quality, output_dir: outputDir } });
        if (!data.ok) throw new Error(data.error || 'Errore compressione');
        if (op === 'compress') result = { type: 'compress', ...data }; else workingPdf = data.output_path;
      }
      if (op === 'split-size' || op === 'compress+split') {
        const mbVal = document.querySelector('input[name="split-mb"]:checked')?.value || '50';
        const target = mbVal === 'custom' ? (parseFloat($('#custom-mb').value) || 50) : parseFloat(mbVal);
        label.textContent = 'Divisione per dimensione…'; bar.style.width = '70%';
        const data = await FT.api('/api/pdf/post/split-size', { body: { pdf_path: workingPdf, target_mb: target, output_dir: outputDir, ...this.collectNaming('naming-ss', 'custom-naming-ss') } });
        if (!data.ok) throw new Error(data.error || 'Errore divisione');
        result = { type: 'split', ...data };
      }
      if (op === 'extract-text') {
        label.textContent = 'Estrazione testo…'; bar.style.width = '60%';
        const data = await FT.api('/api/pdf/post/extract-text', { body: { pdf_path: pdfPath, output_dir: outputDir } });
        if (!data.ok) throw new Error(data.error || 'Errore estrazione testo');
        result = { type: 'extract-text', ...data };
      }
      if (op === 'split-ranges') {
        label.textContent = 'Divisione per range…'; bar.style.width = '70%';
        const data = await FT.api('/api/pdf/post/split-ranges', { body: { pdf_path: workingPdf, ranges, output_dir: outputDir, ...this.collectNaming('naming-sr', 'custom-naming-sr') } });
        if (!data.ok) throw new Error(data.error || 'Errore divisione');
        result = { type: 'split-ranges', ...data };
      }
      bar.style.width = '100%'; label.textContent = 'Completato';
      setTimeout(() => this.showPdfOpResult(result), 500);
    } catch (e) {
      label.textContent = 'Errore: ' + e.message; bar.style.width = '0%';
      FT.toast(e.message, 'error');
      setTimeout(() => {
        $('#progress-card').classList.add('hidden');
        $('#setup-card').classList.remove('hidden');
        $('#steps-indicator').classList.remove('hidden');
      }, 2000);
    }
  },

  showPdfOpResult(result) {
    $('#progress-card').classList.add('hidden');
    $('#result-card').classList.remove('hidden');
    let html;
    if (result.type === 'extract-text') {
      html = this.resultHead('notes', 'c-blue', 'Testo estratto con successo', result.filename)
        + this.stats([[`${result.size_kb} KB`, 'Dimensione .txt'], [fmtInt(result.chars), 'Caratteri'],
          [`${result.pages_with_text}/${result.pages}`, result.pages_with_text < result.pages ? `Pagine con testo (${result.pages - result.pages_with_text} senza testo saltate)` : 'Pagine con testo']]);
    } else if (result.type === 'compress') {
      html = this.resultHead('compress', 'c-green', 'PDF compresso con successo', result.filename)
        + this.stats([[`${result.orig_mb} MB`, 'Dimensione originale'], [`${result.size_mb} MB`, 'Dopo compressione'], [`−${result.reduction_pct}%`, 'Riduzione']]);
      this.state.resultPdfPath = result.output_path;
      $('#postproc-section').classList.remove('hidden');
      this.setupPostProcBtns(['split-size', 'split-ranges']);
    } else {
      const parts = result.parts || [];
      html = this.resultHead('content_cut', 'c-green', `${result.type === 'split-ranges' ? 'Divisione per range' : 'Divisione per dimensione'} completata`,
        `Cartella: ${result.split_dir || this.state.outputPath}`)
        + this.stats([[parts.length, 'Parti create'], [`${Math.max(...parts.map(p => p.size_mb)).toFixed(1)} MB`, 'Parte più grande'],
          [parts.reduce((s, p) => s + p.num_pages, 0), 'Pagine totali']])
        + this.partsList(parts);
    }
    $('#result-content').innerHTML = html;
  },

  // ── Post-elaborazione inline ──────────────────────────────────────────────
  setupPostProcBtns(allowed) {
    $$('#postproc-btns [data-pp]').forEach(b => b.classList.toggle('hidden', !!allowed && !allowed.includes(b.dataset.pp)));
  },
  showPostProc(op) {
    this.state.postProcOp = op;
    $('#postproc-inline').classList.remove('hidden');
    $('#ppopt-compress').classList.toggle('hidden', !(op === 'compress' || op === 'compress+split'));
    $('#ppopt-split-size').classList.toggle('hidden', !(op === 'split-size' || op === 'compress+split'));
    $('#ppopt-split-ranges').classList.toggle('hidden', op !== 'split-ranges');
    $$('#postproc-btns [data-pp]').forEach(b => b.classList.toggle('primary', b.dataset.pp === op));
    if (op === 'split-ranges' && this.state.resultPdfPath) {
      FT.api('/api/pdf/post/page-count', { body: { pdf_path: this.state.resultPdfPath } })
        .then(d => { if (d.ok) $('#pp-range-total-label').textContent = `(totale: ${d.pages})`; }).catch(() => {});
      this.initRangeList('pp-ranges-list');
    }
    $('#postproc-result').classList.add('hidden');
    const btn = $('#btn-apply-postproc');
    btn.disabled = false; btn.lastElementChild.textContent = 'Applica';
  },
  async applyPostProc() {
    const op = this.state.postProcOp;
    if (!op || !this.state.resultPdfPath || !this.state.outputPath) return;
    const btn = $('#btn-apply-postproc'), out = $('#postproc-result');
    btn.disabled = true; btn.lastElementChild.textContent = 'Elaborazione…';
    out.classList.add('hidden');
    try {
      let working = this.state.resultPdfPath, comp = null;
      if (op === 'compress' || op === 'compress+split') {
        const quality = document.querySelector('input[name="pp-quality"]:checked')?.value || 'ebook';
        const d = await FT.api('/api/pdf/post/compress', { body: { pdf_path: this.state.resultPdfPath, quality, output_dir: this.state.outputPath } });
        if (!d.ok) throw new Error(d.error);
        comp = d; working = d.output_path;
      }
      const compNote = comp ? `<div class="banner info">${icon('compress')}<div>Compresso: <strong>${esc(comp.filename)}</strong> — ${comp.orig_mb} MB → <strong>${comp.size_mb} MB</strong> (−${comp.reduction_pct}%)</div></div>` : '';
      if (op === 'split-size' || op === 'compress+split') {
        const mbVal = document.querySelector('input[name="pp-split-mb"]:checked')?.value || '50';
        const target = mbVal === 'custom' ? (parseFloat($('#pp-custom-mb').value) || 50) : parseFloat(mbVal);
        const d = await FT.api('/api/pdf/post/split-size', { body: { pdf_path: working, target_mb: target, output_dir: this.state.outputPath, ...this.collectNaming('pp-naming-ss', 'pp-custom-naming-ss') } });
        if (!d.ok) throw new Error(d.error);
        out.innerHTML = compNote + this.partsList(d.parts, `Parti create (${d.parts.length})`);
      } else if (op === 'split-ranges') {
        const ranges = this.collectRanges('pp-ranges-list');
        if (!ranges) { FT.toast('Inserisci range validi', 'warning'); btn.disabled = false; btn.lastElementChild.textContent = 'Applica'; return; }
        const d = await FT.api('/api/pdf/post/split-ranges', { body: { pdf_path: working, ranges, output_dir: this.state.outputPath, ...this.collectNaming('pp-naming-sr', 'pp-custom-naming-sr') } });
        if (!d.ok) throw new Error(d.error);
        out.innerHTML = compNote + this.partsList(d.parts, `Parti create (${d.parts.length})`);
      } else out.innerHTML = compNote;
      out.classList.remove('hidden');
      btn.lastElementChild.textContent = 'Applicato';
    } catch (e) {
      out.innerHTML = `<div class="banner err">${icon('error')}<div>Errore: ${esc(e.message)}</div></div>`;
      out.classList.remove('hidden');
      btn.disabled = false; btn.lastElementChild.textContent = 'Applica';
    }
  },

  // ── Reset ─────────────────────────────────────────────────────────────────
  resetApp() {
    if (this.state.stream) this.state.stream.close();
    if (this.state.sourceIsTemp && this.state.sourcePath && !this.state.jobId) {
      FT.api('/api/pdf/cleanup-temp', { body: { path: this.state.sourcePath } }).catch(() => {});
    }
    const keepOutput = this.state.outputPath;
    Object.assign(this.state, { sourcePath: null, folderName: null, jobId: null, stream: null, currentStep: 0, totalFiles: 0,
      sourceIsTemp: false, busy: false, isPdfMode: false, pdfServerPath: null, pdfPages: null, resultPdfPath: null, postProcOp: null });
    this.state.outputPath = keepOutput;
    this.resetDropStatus();
    $('#drop-zone').classList.remove('hidden');
    $('#source-info').classList.add('hidden');
    $('#progress-bar').style.width = '0%';
    $('#progress-pct').textContent = '0%';
    Object.assign(this.state, { overallPct: 0, folderIdx: 0, folderTotal: 0 });
    $('#progress-current-file').textContent = '';
    $('#progress-count').textContent = '';
    $('#progress-step-label').textContent = 'Elaborazione in corso…';
    $('#log-panel').innerHTML = '';
    $('#result-log-section').innerHTML = '';
    $('#postproc-section').classList.add('hidden');
    $('#postproc-inline').classList.add('hidden');
    $('#postproc-result').classList.add('hidden');
    $$('#postproc-btns [data-pp]').forEach(b => b.classList.remove('primary'));
    this.exitPdfMode();
    this.setActiveStep(0);
    $('#result-card').classList.add('hidden');
    $('#progress-card').classList.add('hidden');
    $('#setup-card').classList.remove('hidden');
    $('#mode-unified').checked = true;
    this.initRangeList('ranges-list');
    this.initRangeList('pp-ranges-list');
    this.updateStartButton();
  },
};

window.PDF = PDF;
document.addEventListener('DOMContentLoaded', () => PDF.init());

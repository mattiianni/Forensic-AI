/* ════════════════════════════════════════════════════════════════════════════
   Area Ricerca — risposte testuali precise dai soli documenti del fascicolo.
   Ogni dato riporta «File …, pagina …» (cliccabile: apre il documento alla pagina).
   ════════════════════════════════════════════════════════════════════════════ */
'use strict';

const RC = {
  messages: [],
  running: null,

  init() {
    const input = $('#rc-input');
    input.addEventListener('input', () => { this.autosize(input); this.updateSend(); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.send(); }
    });
    $('#rc-send').addEventListener('click', () => this.running ? this.stop() : this.send());
    $('#rc-clear').addEventListener('click', () => this.clear());
    $('#rc-messages').addEventListener('click', (e) => this.onClick(e));
    FT.on('fascicolo', () => this.load());
    FT.on('docs', () => this.renderScope());
    FT.on('area', (a) => { if (a === 'ricerca') setTimeout(() => input.focus(), 50); });
  },

  autosize(t) { t.style.height = 'auto'; t.style.height = Math.min(200, t.scrollHeight) + 'px'; },
  updateSend() {
    const btn = $('#rc-send');
    btn.classList.toggle('stop', !!this.running);
    btn.querySelector('.ms').textContent = this.running ? 'stop' : 'arrow_upward';
    btn.disabled = !this.running && !$('#rc-input').value.trim();
  },

  ready() { return FT.docs.filter(d => d.indicizzato); },

  renderScope() {
    const docs = FT.docs, ready = this.ready();
    const working = docs.filter(d => ['in_coda', 'elaborazione', 'indicizzazione'].includes(d.stato)).length;
    let html = `${icon('folder_open', 'sm')}<span>Ricerca in <strong>${ready.length}</strong> ${ready.length === 1 ? 'documento' : 'documenti'} del fascicolo «${esc(FT.fascicolo?.nome || '')}»</span>`;
    if (working) html += `<span class="chip c-blue"><span class="spinner" style="width:11px;height:11px;border-width:1.5px"></span>${working} in preparazione</span>`;
    $('#rc-scope').innerHTML = html;
    if (!this.messages.length) this.render();
  },

  async load() {
    if (!FT.fid) return;
    try { this.messages = (await FT.api(`/api/ricerca/${FT.fid}`)).messaggi || []; } catch (e) { this.messages = []; }
    this.render();
    this.renderScope();
  },

  // ── Rendering ─────────────────────────────────────────────────────────────
  welcome() {
    const ready = this.ready().length;
    const sugg = [
      ['person_search', 'Chi sono gli amministratori delle società citate?'],
      ['payments', 'Quali bonifici superiori a 10.000 € risultano e tra quali soggetti?'],
      ['badge', 'Quali codici fiscali e partite IVA compaiono nei documenti?'],
      ['event', 'Quali date e scadenze sono indicate negli atti?'],
    ];
    return `<div class="welcome">
      <div class="w-ico c-blue">${icon('manage_search', 'xxl')}</div>
      <h2>Cerca nei documenti</h2>
      <p>${ready ? `Fai una domanda: la risposta contiene solo ciò che è scritto nei ${ready} documenti del fascicolo, con file e pagina per ogni dato.`
        : 'Aggiungi documenti al fascicolo trascinandoli nella barra laterale. Dopo l\'indicizzazione potrai fare domande e ottenere risposte con file e pagina per ogni dato.'}</p>
      ${ready ? `<div class="suggestions">${sugg.map(([i, t]) => `<button class="suggestion" data-sugg="${esc(t)}">${icon(i)}<span>${esc(t)}</span></button>`).join('')}</div>` : ''}
    </div>`;
  },

  /** Testo della risposta → HTML con riferimenti cliccabili */
  formatAnswer(text, fonti) {
    fonti = fonti || [];
    const chip = (label, f) => {
      const attrs = f ? `data-doc="${esc(f.doc_id)}" data-page="${f.pagina}" data-chunk="${f.chunk_id}"` : '';
      return `<span class="ref" ${attrs}>${icon('description')}${esc(label)}</span>`;
    };
    // durante lo streaming il modello scrive [n]: li mostro già come «File …, pagina …»
    let t = text.replace(/(?:\[\s*\d+(?:\s*[,;]\s*\d+)*\s*\])+/g, (m) => {
      const nums = [...new Set((m.match(/\d+/g) || []).map(Number))];
      return ' ' + nums.map(n => fonti[n - 1] ? `@@REF${n}@@` : '').join(' ');
    });
    // risposta finale: (File X, pagina N; File Y, foglio «Z»)
    t = t.replace(/\((File [^()]+?)\)/g, (m, inner) => inner.split(/;\s*/).map(part => {
      const mm = part.match(/^File (.+), (pagina|foglio|sezione|testo)\s*(.*)$/i);
      if (!mm) return `@@TXT${encodeURIComponent(part)}@@`;
      const [, nome, kind, where] = mm;
      const f = fonti.find(x => x.documento === nome && (kind.toLowerCase() !== 'pagina' || String(x.pagina) === where.trim()))
        || fonti.find(x => x.documento === nome);
      return f ? `@@SRC${fonti.indexOf(f)}|${encodeURIComponent(part)}@@` : `@@TXT${encodeURIComponent(part)}@@`;
    }).join(' '));
    let html = FT.md(t);
    html = html.replace(/@@REF(\d+)@@/g, (m, n) => {
      const f = fonti[n - 1];
      return chip(`File ${f.documento}, ${this.where(f)}`, f);
    });
    html = html.replace(/@@SRC(\d+)\|([^@]+)@@/g, (m, i, lab) => chip(decodeURIComponent(lab), fonti[+i]));
    html = html.replace(/@@TXT([^@]+)@@/g, (m, lab) => chip(decodeURIComponent(lab), null));
    return html;
  },
  where(f) {
    const l = f.label || '';
    if (l.startsWith('Pag. ')) return `pagina ${l.slice(5)}`;
    if (l.startsWith('Foglio')) return 'foglio ' + l.slice(7);
    return l.charAt(0).toLowerCase() + l.slice(1);
  },

  sourcesHtml(fonti, open = false) {
    if (!fonti || !fonti.length) return '';
    return `<div class="sources">
      <button class="sources-toggle" data-toggle-src>${icon(open ? 'expand_less' : 'expand_more', 'sm')}Fonti consultate (${fonti.length})</button>
      <div class="${open ? '' : 'hidden'}" data-src-list style="display:flex;flex-direction:column;gap:6px">
      ${fonti.map((f, i) => `<div class="source" data-doc="${esc(f.doc_id)}" data-page="${f.pagina}" data-chunk="${f.chunk_id}">
        <div class="src-n">${i + 1}</div>
        <div style="min-width:0"><div class="src-doc">${icon(FT.docType((FT.docs.find(d => d.id === f.doc_id) || {}).estensione || '.pdf')[1], 'xs')}
          File ${esc(f.documento)} · ${esc(this.where(f))}</div>
        <div class="src-text">${esc(f.testo)}</div></div></div>`).join('')}
      </div></div>`;
  },

  msgHtml(m, idx) {
    if (m.role === 'user') return `<div class="msg user"><div class="bubble">${esc(m.content)}</div></div>`;
    const meta = m.secondi ? `<div class="meta-line">${icon('memory', 'xs')}${esc(m.modello || '')} · ${String(m.secondi).replace('.', ',')} s
      <button class="icon-btn" data-copy="${idx}" title="Copia risposta" style="width:24px;height:24px">${icon('content_copy', 'xs')}</button></div>` : '';
    return `<div class="msg assistant"><div class="avatar">${icon('manage_search')}</div>
      <div class="answer"><div class="md">${this.formatAnswer(m.content, m.fonti)}</div>${this.sourcesHtml(m.fonti)}${meta}</div></div>`;
  },

  render() {
    const box = $('#rc-messages');
    box.innerHTML = this.messages.length ? this.messages.map((m, i) => this.msgHtml(m, i)).join('') : this.welcome();
    this.scrollEnd();
  },
  scrollEnd() { const s = $('#rc-scroll'); s.scrollTop = s.scrollHeight; },

  onClick(e) {
    const sugg = e.target.closest('[data-sugg]');
    if (sugg) { $('#rc-input').value = sugg.dataset.sugg; this.send(); return; }
    const ref = e.target.closest('.ref[data-doc], .source[data-doc]');
    if (ref) {
      const msgEl = ref.closest('.msg');
      const idx = $$('.msg', $('#rc-messages')).indexOf(msgEl);
      const m = this.messages[idx] || this.live;
      const f = (m?.fonti || []).find(x => String(x.chunk_id) === ref.dataset.chunk);
      FT.openDoc(ref.dataset.doc, +ref.dataset.page || 1, f ? f.testo : '');
      return;
    }
    const tog = e.target.closest('[data-toggle-src]');
    if (tog) {
      const list = tog.parentElement.querySelector('[data-src-list]');
      const hidden = list.classList.toggle('hidden');
      tog.querySelector('.ms').textContent = hidden ? 'expand_more' : 'expand_less';
      return;
    }
    const cp = e.target.closest('[data-copy]');
    if (cp) {
      navigator.clipboard.writeText(this.messages[+cp.dataset.copy]?.content || '');
      FT.toast('Risposta copiata', 'check_circle', 1800);
    }
  },

  // ── Invio ─────────────────────────────────────────────────────────────────
  async send() {
    const input = $('#rc-input');
    const q = input.value.trim();
    if (!q || this.running) return;
    if (!this.ready().length) return FT.toast('Nessun documento indicizzato nel fascicolo', 'warning');
    input.value = ''; this.autosize(input);
    if (!this.messages.length) $('#rc-messages').innerHTML = '';
    this.messages.push({ role: 'user', content: q });
    $('#rc-messages').insertAdjacentHTML('beforeend', this.msgHtml(this.messages[this.messages.length - 1]));
    const live = { role: 'assistant', content: '', fonti: [] };
    this.live = live;
    $('#rc-messages').insertAdjacentHTML('beforeend', `<div class="msg assistant" id="rc-live"><div class="avatar">${icon('manage_search')}</div>
      <div class="answer"><div class="rc-prog">${progressBlock('rc-prog', 'Ricerca nei documenti', 0.02, 'Cerco nei documenti…')}</div><div class="md hidden"></div><div data-srcs></div></div></div>`);
    this.scrollEnd();
    const el = $('#rc-live');
    const t0 = Date.now();
    const prog = () => $('#rc-prog', el);
    let ntok = 0;
    try {
      const r = await FT.api(`/api/ricerca/${FT.fid}/ask`, { body: { question: q, model: FT.model } });
      this.running = FT.stream(r.job_id, {
        progress: (ev) => setProgress(prog(), Math.min(0.24, ev.fraction), ev.message),
        sources: (ev) => {
          live.fonti = ev.sources;
          setProgress(prog(), 0.25, ev.sources.length ? `Trovati ${ev.sources.length} passaggi pertinenti · il modello sta leggendo…` : 'Nessun passaggio pertinente');
        },
        token: (ev) => {
          live.content += ev.text;
          ntok++;
          setProgress(prog(), 0.3 + 0.68 * Math.min(1, ntok / 350), `Scrittura della risposta · ${ntok} token`);
          const md = $('.md', el); md.classList.remove('hidden');
          md.innerHTML = this.formatAnswer(live.content, live.fonti);
          this.scrollEnd();
        },
        done: (ev) => {
          setProgress(prog(), 1, 'Completata');
          if (ev.text) live.content = ev.text;
          live.secondi = ev.elapsed || Math.round((Date.now() - t0) / 100) / 10;
          live.modello = FT.model;
        },
        fatal_error: (ev) => { live.content = `Si è verificato un errore: ${ev.message}`; },
      }, () => {
        this.running = null; this.live = null;
        this.messages.push(live);
        el.outerHTML = this.msgHtml(live, this.messages.length - 1);
        this.updateSend(); this.scrollEnd();
      });
      this.updateSend();
    } catch (e) {
      el.remove(); this.messages.pop();
      FT.toast(e.message, 'error');
    }
  },

  stop() { if (this.running) this.running.cancel(); },

  async clear() {
    if (!this.messages.length) return;
    await FT.api(`/api/ricerca/${FT.fid}`, { method: 'DELETE' });
    this.messages = [];
    this.render();
  },
};

window.RC = RC;
document.addEventListener('DOMContentLoaded', () => RC.init());

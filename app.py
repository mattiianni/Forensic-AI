import json
import time
import datetime
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from logger import log, leggi_ultimi_log
from parser import analizza_ed_estrai, MAX_CARATTERI_CONSIGLIATI
from ai_engine import (
    get_active_model,
    estrai_entita_e_relazioni_avanzato,
    genera_dossier_forense_globale,
    BEST_MODEL,
    FAST_MODEL,
)
from graph_manager import GestoreGrafo

st.set_page_config(
    page_title="Forensic AI Offline",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

log.debug("Streamlit script evaluation avviata")

# ==============================================================================
# APPLE MATERIAL HUMAN INTERFACE GUIDELINES (macOS Dark Theme)
# ==============================================================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=SF+Pro+Display:wght@400;500;600;700&display=swap');

    :root {
        --apple-bg: #0d1117;
        --apple-card: rgba(22, 27, 34, 0.75);
        --apple-border: rgba(255, 255, 255, 0.08);
        --apple-blue: #0A84FF;
        --apple-blue-hover: #0071E3;
        --apple-green: #30D158;
        --apple-orange: #FF9F0A;
        --apple-red: #FF453A;
        --apple-purple: #BF5AF2;
        --apple-text-primary: #F5F5F7;
        --apple-text-secondary: #86868B;
        --apple-text-tertiary: #6E6E73;
    }

    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif !important;
        color: var(--apple-text-primary);
        letter-spacing: -0.01em;
    }

    [data-testid="stSidebar"] {
        background-color: #0b0e14 !important;
        border-right: 1px solid var(--apple-border) !important;
        min-width: 320px !important;
        max-width: 360px !important;
    }

    [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
        font-size: 0.85rem !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em !important;
        color: var(--apple-text-tertiary) !important;
        font-weight: 600 !important;
        margin-top: 1.2rem !important;
        margin-bottom: 0.5rem !important;
    }

    .apple-header {
        display: flex;
        align-items: center;
        gap: 16px;
        margin-bottom: 8px;
        padding-bottom: 12px;
        border-bottom: 1px solid var(--apple-border);
    }
    .apple-header-title {
        font-size: 1.85rem;
        font-weight: 700;
        letter-spacing: -0.025em;
        color: #ffffff;
        margin: 0;
    }
    .apple-header-subtitle {
        font-size: 0.92rem;
        color: var(--apple-text-secondary);
        margin: 0;
        line-height: 1.4;
    }

    .apple-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 600;
        white-space: nowrap;
    }
    .pill-blue {
        background: rgba(10, 132, 255, 0.15);
        color: #58a6ff;
        border: 1px solid rgba(10, 132, 255, 0.3);
    }
    .pill-green {
        background: rgba(48, 209, 88, 0.15);
        color: #3fb950;
        border: 1px solid rgba(48, 209, 88, 0.3);
    }
    .pill-orange {
        background: rgba(255, 159, 10, 0.15);
        color: #d29922;
        border: 1px solid rgba(255, 159, 10, 0.3);
    }
    .pill-red {
        background: rgba(255, 69, 58, 0.15);
        color: #f85149;
        border: 1px solid rgba(255, 69, 58, 0.3);
    }
    .pill-purple {
        background: rgba(191, 90, 242, 0.15);
        color: #d2a8ff;
        border: 1px solid rgba(191, 90, 242, 0.3);
    }

    .apple-card {
        background: var(--apple-card);
        border: 1px solid var(--apple-border);
        border-radius: 14px;
        padding: 16px 20px;
        margin-bottom: 14px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
    }

    .status-card {
        background: rgba(10, 132, 255, 0.08);
        border: 1px solid rgba(10, 132, 255, 0.35);
        border-radius: 12px;
        padding: 14px 18px;
        margin-bottom: 14px;
    }

    .metric-row {
        display: flex;
        gap: 12px;
        margin-bottom: 14px;
    }
    .metric-box {
        flex: 1;
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid var(--apple-border);
        border-radius: 12px;
        padding: 12px 14px;
        text-align: center;
    }
    .metric-val {
        font-size: 1.55rem;
        font-weight: 700;
        color: #ffffff;
        font-variant-numeric: tabular-nums;
        line-height: 1.1;
    }
    .metric-lbl {
        font-size: 0.72rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--apple-text-secondary);
        margin-top: 4px;
        white-space: nowrap;
    }

    .stButton > button {
        background: linear-gradient(180deg, #1f6feb 0%, #1158c7 100%) !important;
        color: #ffffff !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        font-size: 0.92rem !important;
        padding: 10px 20px !important;
        transition: all 0.18s ease !important;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3) !important;
    }
    .stButton > button:hover {
        background: linear-gradient(180deg, #388bfd 0%, #1f6feb 100%) !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 14px rgba(10, 132, 255, 0.4) !important;
    }

    .stDownloadButton > button {
        background: rgba(255, 255, 255, 0.06) !important;
        color: var(--apple-text-primary) !important;
        border: 1px solid var(--apple-border) !important;
        border-radius: 10px !important;
        font-weight: 500 !important;
        font-size: 0.85rem !important;
        width: 100% !important;
        margin-top: 4px !important;
    }

    div[role="radiogroup"] {
        background: rgba(0, 0, 0, 0.25);
        border: 1px solid var(--apple-border);
        border-radius: 10px;
        padding: 4px;
        gap: 4px;
    }

    [data-testid="stFileUploader"] {
        background: rgba(255, 255, 255, 0.02) !important;
        border: 1px dashed rgba(10, 132, 255, 0.4) !important;
        border-radius: 14px !important;
        padding: 16px !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(255, 255, 255, 0.04);
        padding: 4px;
        border-radius: 12px;
        border: 1px solid var(--apple-border);
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px !important;
        padding: 8px 18px !important;
        font-size: 0.88rem !important;
        font-weight: 600 !important;
        color: var(--apple-text-secondary) !important;
        border: none !important;
        background: transparent !important;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(255, 255, 255, 0.12) !important;
        color: #ffffff !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3) !important;
    }
    .log-box {
        font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
        font-size: 0.76rem;
        background-color: #07090d;
        color: #38bdf8;
        padding: 10px 12px;
        border-radius: 8px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        height: 220px;
        overflow-y: auto;
        white-space: pre-wrap;
    }
    .dossier-box {
        background: rgba(22, 27, 34, 0.65);
        border: 1px solid var(--apple-border);
        border-radius: 14px;
        padding: 24px 30px;
        line-height: 1.65;
    }
    .timeline-item {
        border-left: 2px solid var(--apple-blue);
        padding-left: 16px;
        margin-left: 8px;
        margin-bottom: 16px;
        position: relative;
    }
    .timeline-dot {
        width: 10px;
        height: 10px;
        background: var(--apple-blue);
        border-radius: 50%;
        position: absolute;
        left: -6px;
        top: 4px;
    }
</style>
""", unsafe_allow_html=True)

# Inizializzazione Session State
if "gestore_grafo" not in st.session_state:
    st.session_state.gestore_grafo = GestoreGrafo()
if "dossier_globale" not in st.session_state:
    st.session_state.dossier_globale = None
if "documenti_acquisiti" not in st.session_state:
    st.session_state.documenti_acquisiti = {}
if "timestamp_analisi" not in st.session_state:
    st.session_state.timestamp_analisi = None

# SIDEBAR: Configurazione e Sessione
with st.sidebar:
    st.markdown("### Configurazione Motore")

    profilo = st.radio(
        "Modalità Analitica:",
        options=[
            "🏆 Massima Precisione (Qwen 2.5 7B)",
            "⚡ Scansione Rapida (Llama 3.2 3B)",
        ],
        index=0,
        label_visibility="collapsed",
    )
    modello_selezionato = BEST_MODEL if "Qwen" in profilo else FAST_MODEL

    st.markdown("""
    <div style="margin-top: 6px; margin-bottom: 12px;">
        <span class="apple-pill pill-blue">🔒 100% Offline (Metal ARM64)</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### Modalità Operativa")
    abilita_grafo = st.toggle(
        "Genera Grafo & Entity Resolution",
        value=True,
        help="Attivo: deduplica persone e aziende per CF/PIVA, rileva cicli e disegna il grafo. Disattivo: genera solo il dossier testuale.",
    )

    st.markdown("### Metriche Fascicolo")
    num_nodi = len(st.session_state.gestore_grafo.grafo.nodes)
    num_archi = len(st.session_state.gestore_grafo.grafo.edges)
    num_doc = len(st.session_state.documenti_acquisiti)

    st.markdown(f"""
    <div class="metric-row">
        <div class="metric-box">
            <div class="metric-val">{num_doc}</div>
            <div class="metric-lbl">Atti</div>
        </div>
        <div class="metric-box">
            <div class="metric-val">{num_nodi}</div>
            <div class="metric-lbl">Soggetti</div>
        </div>
        <div class="metric-box">
            <div class="metric-val">{num_archi}</div>
            <div class="metric-lbl">Relazioni</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Rilevamento pattern investigativi stile Belkasoft / Cellebrite
    schemi = st.session_state.gestore_grafo.rileva_schemi_investigativi_topologici() if abilita_grafo else {}
    cicli = schemi.get("flussi_circolari", [])
    if cicli:
        st.markdown(f"""
        <div class="apple-pill pill-red" style="width: 100%; justify-content: center; margin-bottom: 8px;">
            🚨 {len(cicli)} Flussi Circolari (Ring)
        </div>
        """, unsafe_allow_html=True)

    hubs = schemi.get("hub_dominus", [])
    if hubs:
        st.markdown(f"""
        <div class="apple-pill pill-orange" style="width: 100%; justify-content: center; margin-bottom: 8px;">
            🌟 {len(hubs)} Nodi Hub / Dominus (Star)
        </div>
        """, unsafe_allow_html=True)

    scatole = schemi.get("scatole_cinesi", [])
    if scatole:
        st.markdown(f"""
        <div class="apple-pill pill-purple" style="width: 100%; justify-content: center; margin-bottom: 8px;">
            🏢 {len(scatole)} Catene di Controllo (Chain)
        </div>
        """, unsafe_allow_html=True)

    st.markdown("### Gestione Sessione")
    c_s1, c_s2 = st.columns(2)
    with c_s1:
        stato_completo = {
            "grafo_dati": st.session_state.gestore_grafo.esporta_stato(),
            "dossier_globale": st.session_state.dossier_globale,
            "documenti_acquisiti": {
                k: {"caratteri": v["caratteri"], "num_blocchi": v["num_blocchi"]}
                for k, v in st.session_state.documenti_acquisiti.items()
            },
            "timestamp_analisi": st.session_state.timestamp_analisi,
        }
        st.download_button(
            label="💾 Salva",
            data=json.dumps(stato_completo, indent=2, ensure_ascii=False),
            file_name="indagine_forense.json",
            mime="application/json",
            help="Scarica il file sessione .json per continuare in seguito",
        )
    with c_s2:
        if st.button("🗑️ Svuota", help="Azzera il fascicolo, il grafo e il dossier"):
            log.info("Reset fascicolo richiesto dall'utente: azzeramento totale")
            st.session_state.gestore_grafo = GestoreGrafo()
            st.session_state.dossier_globale = None
            st.session_state.documenti_acquisiti = {}
            st.session_state.timestamp_analisi = None
            st.rerun()

    file_stato = st.file_uploader("Ripristina sessione (.json):", type=["json"], key="loader_sessione", label_visibility="collapsed")
    if file_stato is not None:
        if st.button("📥 Ricarica Sessione"):
            try:
                log.info(f"Caricamento file sessione: {file_stato.name}")
                dati = json.loads(file_stato.read().decode("utf-8"))
                st.session_state.gestore_grafo.importa_stato(dati.get("grafo_dati", {}))
                st.session_state.dossier_globale = dati.get("dossier_globale")
                st.session_state.timestamp_analisi = dati.get("timestamp_analisi")
                st.success("Sessione ripristinata!")
                st.rerun()
            except Exception as e:
                log.error(f"Errore caricamento stato: {e}", exc_info=True)
                st.error(f"Errore: {e}")

    if num_nodi > 0:
        st.markdown("### Export Forense Multi-Standard")
        progetto_pdf_rel = st.session_state.gestore_grafo.esporta_progetto_pdf_relations()
        st.download_button(
            label="🔗 Esporta Cytoscape (.relazioni.json)",
            data=json.dumps(progetto_pdf_rel, indent=2, ensure_ascii=False),
            file_name="indagine_forense.relazioni.json",
            mime="application/json",
            help="File compatibile per l'apertura e modifica con Cytoscape in Pdf_Relations",
            use_container_width=True,
        )

        dati_ftm = st.session_state.gestore_grafo.esporta_followthemoney_jsonl()
        st.download_button(
            label="🌐 Esporta FollowTheMoney (.ftm.json)",
            data=dati_ftm,
            file_name="indagine_forense.ftm.json",
            mime="application/x-jsonlines",
            help="Standard internazionale OCCRP Aleph per antiriciclaggio e link analysis",
            use_container_width=True,
        )

        codice_mmd = st.session_state.gestore_grafo.esporta_mermaid(orientamento="TD")
        st.download_button(
            label="🧜 Esporta Diagramma Mermaid (.mmd)",
            data=codice_mmd,
            file_name="indagine_forense.mmd",
            mime="text/vnd.mermaid",
            help="File sorgente Mermaid per relazioni peritali, Markdown e Obsidian",
            use_container_width=True,
        )

    st.markdown("### 📋 Log Giornaliero Sistema")
    with st.expander("Visualizza Log Attivo", expanded=False):
        testo_log = leggi_ultimi_log(max_righe=80)
        st.markdown(f'<div class="log-box">{testo_log}</div>', unsafe_allow_html=True)
        if st.button("🔄 Aggiorna Log"):
            st.rerun()

    st.markdown("---")
    st.markdown("### ⚙️ Controllo Server")
    if st.button("🛑 Arresta Server & Chiudi", help="Termina il server Streamlit e rilascia la porta di rete", use_container_width=True):
        import os, signal
        st.warning("Arresto del server in corso... Puoi chiudere questa scheda del browser.")
        log.info("Richiesta chiusura server Streamlit da interfaccia utente.")
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)

# INTESTAZIONE PRINCIPALE
st.markdown("""
<div class="apple-header">
    <div style="font-size: 2.2rem;">⚖️</div>
    <div>
        <h1 class="apple-header-title">Forensic AI Offline</h1>
        <p class="apple-header-subtitle">Analisi Forense Multi-Documento, Link Analysis e Rilevamento Pattern (Cellebrite / Magnet / Belkasoft Architecture).</p>
    </div>
</div>
""", unsafe_allow_html=True)

# DROPZONE MULTI-DOCUMENTO
with st.container():
    files = st.file_uploader(
        "Carica tutti gli atti del fascicolo (PDF, Word DOCX, Excel XLSX/CSV, TXT, XML)",
        type=["pdf", "docx", "xlsx", "xls", "csv", "txt", "xml"],
        accept_multiple_files=True,
        help="Supporta contemporaneamente Visure CCIAA, SOS, Bilanci, Estratti Conto, Rogiti, Contratti e Perizie CTU.",
    )

    c_info, c_action = st.columns([2, 1], gap="medium")
    with c_info:
        tot_file = len(files) if files else 0
        if tot_file > 0:
            st.markdown(f"**Atti nel Fascicolo ({tot_file})**: {', '.join([f.name for f in files])}")
        else:
            st.markdown("<span style='color: var(--apple-text-secondary);'>Nessun documento inserito nel fascicolo d'indagine.</span>", unsafe_allow_html=True)

    with c_action:
        bottone_attivo = (tot_file > 0)
        testo_bottone = f"🚀 Avvia Analisi Forense Incrociata ({tot_file} Atti)" if tot_file > 0 else "Trascina file nel box sopra per iniziare"
        avvia_analisi = st.button(testo_bottone, disabled=not bottone_attivo, use_container_width=True)

    # ESECUZIONE DELL'ANALISI GLOBALE INCROCIATA
    if avvia_analisi and files:
        progress_container = st.container()
        with progress_container:
            prog_bar = st.progress(0.01)
            status_text = st.empty()

        t_global_start = time.time()

        def update_progress(perc: float, msg: str, tokens: int = 0, elapsed: float = 0.0):
            p_val = round(min(max(perc, 0.01), 1.0), 2)
            prog_bar.progress(p_val)
            
            tot_sec = int(time.time() - t_global_start)
            minuti = tot_sec // 60
            secondi = tot_sec % 60
            timer_str = f"{minuti:02d}:{secondi:02d}s"

            info_extra = []
            info_extra.append(f"⏱️ Tempo: {timer_str}")
            if tokens > 0:
                info_extra.append(f"⚡ Token: {tokens:,}")
            info_extra.append("🟢 Metal GPU Attivo")
            extra_str = " &nbsp;|&nbsp; ".join(info_extra)

            status_text.markdown(f"""
            <div class="status-card" style="border: 1px solid rgba(10, 132, 255, 0.4); background: rgba(10, 132, 255, 0.06);">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 600; color: #58a6ff; font-size: 0.95rem;">{msg}</span>
                    <span class="apple-pill pill-blue" style="font-size: 0.85rem; font-weight: 700;">{int(p_val * 100)}%</span>
                </div>
                <div style="margin-top: 6px; font-size: 0.80rem; color: #86868b; display: flex; justify-content: space-between;">
                    <span>{extra_str}</span>
                    <span style="color: #30D158; font-weight: 600;">● In elaborazione</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        t_global_start = time.time()
        log.info(f"Avvio indagine integrata globale su {len(files)} documenti")

        # FASE 1: Ingestione e Parsing diagnostico
        update_progress(0.05, f"📄 [Fase 1/4] Ingestione e parsing diagnostico di {len(files)} documenti...")
        documenti_estratti = {}
        st.session_state.gestore_grafo = GestoreGrafo()

        for idx, f in enumerate(files, start=1):
            diag = analizza_ed_estrai(f)
            documenti_estratti[f.name] = diag
            st.session_state.documenti_acquisiti[f.name] = {
                "testo": diag["testo"],
                "caratteri": diag["num_caratteri"],
                "num_blocchi": diag["num_blocchi"],
                "pagine": diag["totale_pagine"],
                "manca_ocr": diag["manca_ocr"],
                "estensione": diag["estensione"],
            }
            perc_fase1 = 0.05 + (0.15 * (idx / len(files)))
            update_progress(perc_fase1, f"📄 Letto documento {idx}/{len(files)}: '{f.name}' ({diag['num_caratteri']:,} caratteri)")

        # FASE 2 & 3: Estrazione Entità e Risoluzione Identità su Grafo Unificato
        n_tot = len(files)
        for idx, (nome_file, diag) in enumerate(documenti_estratti.items(), start=1):
            if abilita_grafo:
                base_p = 0.20 + (0.45 * ((idx - 1) / n_tot))
                peso_p = 0.45 * (1 / n_tot)
                dati_json = estrai_entita_e_relazioni_avanzato(
                    blocchi_testo=diag["blocchi"],
                    nome_file=nome_file,
                    model=modello_selezionato,
                    callback_progresso=update_progress,
                    base_perc=base_p,
                    peso_perc=peso_p,
                )
                st.session_state.gestore_grafo.aggiungi_dati(dati_json, nome_file)

        update_progress(0.70, "🕸️ [Fase 3/4] Entity Resolution globale, Master Timeline e Link Analysis...")

        # FASE 4: Generazione Dossier Forense Globale Unificato
        update_progress(0.75, f"🧠 [Fase 4/4] Sintesi Dossier Forense Globale con {modello_selezionato}...")
        testi_sintetici = {k: v["testo"] for k, v in documenti_estratti.items()}

        dossier_unificato = genera_dossier_forense_globale(
            gestore_grafo=st.session_state.gestore_grafo,
            estratti_documenti=testi_sintetici,
            model=modello_selezionato,
            ha_grafo=abilita_grafo,
            callback_progresso=update_progress,
        )

        t_elapsed = round(time.time() - t_global_start, 1)
        st.session_state.dossier_globale = dossier_unificato
        st.session_state.timestamp_analisi = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

        update_progress(1.0, f"✅ Fascicolo analizzato e dossier integrato completato in {t_elapsed}s!")
        log.info(f"Dossier globale completato in {t_elapsed}s per {len(files)} documenti")
        time.sleep(0.4)
        st.rerun()

st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)

# TABS PRINCIPALI
tab_dossier, tab_mappa, tab_schemi, tab_timeline, tab_convergenze, tab_documenti = st.tabs([
    "⚖️ Dossier Forense Globale",
    "🕸️ Link Analysis & Grafo",
    "🎯 Schemi & Pattern (Cellebrite/Belka)",
    "⏱️ Master Timeline Eventi",
    "🔗 Convergenze & Anagrafiche",
    "📂 Fascicolo Atti",
])

# TAB 1: DOSSIER FORENSE COMPLESSIVO UNIFICATO
with tab_dossier:
    if not st.session_state.dossier_globale:
        st.markdown("""
        <div class="apple-card" style="text-align: center; padding: 45px 20px;">
            <div style="font-size: 2.3rem; margin-bottom: 12px;">⚖️</div>
            <h3 style="margin: 0; color: #ffffff; font-size: 1.2rem;">Nessun Dossier Ancora Generato</h3>
            <p style="color: #86868b; margin-top: 8px; font-size: 0.92rem; max-width: 650px; margin-left: auto; margin-right: auto;">
                Carica gli atti del caso (Visure, SOS, Contratti, Perizie, Estratti Conto) e clicca su <strong>"Analizza Fascicolo"</strong>.
                Il sistema estrarrà <strong>un'unica relazione forense integrata</strong> che incrocia tutti i documenti insieme.
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
            <div>
                <span class="apple-pill pill-green">✅ Relazione Forense Unificata</span>
                <span style="color: #86868b; font-size: 0.85rem; margin-left: 10px;">Elaborata il {st.session_state.timestamp_analisi} su {len(st.session_state.documenti_acquisiti)} atti</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        try:
            res_fin = st.session_state.gestore_grafo.db.execute("SELECT SUM(valore_numerico), COUNT(*) FROM relazioni WHERE valore_numerico > 0").fetchall()
            tot_val = res_fin[0][0] or 0.0
            n_trans = res_fin[0][1] or 0
        except Exception:
            tot_val, n_trans = 0.0, 0

        st.markdown(f"""
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px;">
            <div class="apple-card" style="padding: 12px 16px;">
                <div style="font-size: 0.78rem; color: #86868b; text-transform: uppercase; font-weight: 600;">Volume Finanziario Tracciato</div>
                <div style="font-size: 1.4rem; font-weight: 700; color: #30D158; margin-top: 4px;">€ {tot_val:,.2f}</div>
            </div>
            <div class="apple-card" style="padding: 12px 16px;">
                <div style="font-size: 0.78rem; color: #86868b; text-transform: uppercase; font-weight: 600;">Operazioni Rilevate</div>
                <div style="font-size: 1.4rem; font-weight: 700; color: #0A84FF; margin-top: 4px;">{n_trans} movimenti</div>
            </div>
            <div class="apple-card" style="padding: 12px 16px;">
                <div style="font-size: 0.78rem; color: #86868b; text-transform: uppercase; font-weight: 600;">Soggetti Censiti</div>
                <div style="font-size: 1.4rem; font-weight: 700; color: #BF5AF2; margin-top: 4px;">{len(st.session_state.gestore_grafo.grafo.nodes)} entità</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"""
        <div class="dossier-box">
        """, unsafe_allow_html=True)
        st.markdown(st.session_state.dossier_globale)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)
        st.download_button(
            label="📄 Scarica Relazione Forense Unificata (.md)",
            data=st.session_state.dossier_globale,
            file_name=f"Dossier_Forense_Integrato_{datetime.date.today().strftime('%Y%m%d')}.md",
            mime="text/markdown",
        )

# TAB 2: LINK ANALYSIS & GRAFO RELAZIONALE
with tab_mappa:
    if not abilita_grafo:
        st.markdown("""
        <div class="apple-card" style="text-align: center; padding: 30px 20px;">
            <div class="apple-pill pill-orange" style="margin-bottom: 10px;">⚡ Modalità Solo Testo</div>
            <p style="color: #86868b; margin: 0; font-size: 0.9rem;">
                Il grafo relazionale è disattivato. Attiva lo switch nella sidebar per abilitare la mappa visuale.
            </p>
        </div>
        """, unsafe_allow_html=True)
    elif len(st.session_state.gestore_grafo.grafo.nodes) == 0:
        st.info("In attesa di eseguire l'analisi per generare la rete relazionale complessiva.")
    else:
        cicli_rilevati = st.session_state.gestore_grafo.trova_cicli()
        if cicli_rilevati:
            st.markdown("""
            <div class="apple-card" style="border-left: 4px solid var(--apple-red); margin-bottom: 16px;">
                <h4 style="margin: 0 0 8px 0; color: var(--apple-red);">🚨 Flussi Circolari e Triangolazioni Rilevate Matematicamente</h4>
            """, unsafe_allow_html=True)
            for c in cicli_rilevati:
                percorso = " ➔ ".join(c) + f" ➔ <strong>{c[0]}</strong>"
                st.markdown(f"- {percorso}", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        col_ctl1, col_ctl2 = st.columns([3, 1])
        with col_ctl1:
            st.markdown(f"**Mappa di Link Analysis**: {len(st.session_state.gestore_grafo.grafo.nodes)} entità unificate, {len(st.session_state.gestore_grafo.grafo.edges)} relazioni probatorie.")
        with col_ctl2:
            scelta_dim = st.selectbox("Altezza Grafo:", options=["Ampio (800px)", "Extra Large (1000px)", "Full View (1200px)"], index=0, label_visibility="collapsed")
            alt_map = {"Ampio (800px)": 800, "Extra Large (1000px)": 1000, "Full View (1200px)": 1200}
            alt_scelta = alt_map.get(scelta_dim, 800)

        html_path = st.session_state.gestore_grafo.genera_html_mappa(altezza=f"{alt_scelta}px")
        with open(html_path, "r", encoding="utf-8") as f:
            components.html(f.read(), height=alt_scelta + 10)

        # SEZIONE MERMAID INTEGRATA
        st.markdown("---")
        st.markdown("#### 🧜 Esportazione & Integrazione Mermaid")
        st.markdown("<p style='color: #86868b; font-size: 0.85rem;'>Genera ed esporta il diagramma dell'indagine in formato Mermaid (compatibile con Markdown, Obsidian, GitHub e perizie):</p>", unsafe_allow_html=True)

        c_m1, c_m2 = st.columns([2, 1])
        with c_m1:
            orientamento = st.radio("Orientamento Diagramma:", options=["Dall'alto al basso (TD)", "Da sinistra a destra (LR)"], horizontal=True, label_visibility="collapsed")
            orient_code = "LR" if "sinistra" in orientamento else "TD"
            codice_mermaid = st.session_state.gestore_grafo.esporta_mermaid(orientamento=orient_code)

        with c_m2:
            st.download_button(
                label="📥 Scarica File Mermaid (.mmd)",
                data=codice_mermaid,
                file_name=f"indagine_grafo_mermaid_{datetime.date.today().strftime('%Y%m%d')}.mmd",
                mime="text/vnd.mermaid",
                help="Scarica il file .mmd compatibile con visualizzatori Mermaid e Obsidian",
                use_container_width=True,
            )

        with st.expander("Visualizza Codice Sorgente Mermaid", expanded=False):
            st.code(codice_mermaid, language="mermaid")

# TAB 3: SCHEMI & PATTERN TOPOLOGICI (BELKASOFT / CELLEBRITE PATTERN)
with tab_schemi:
    schemi = st.session_state.gestore_grafo.rileva_schemi_investigativi_topologici() if abilita_grafo else {}
    if not schemi or (not schemi.get("flussi_circolari") and not schemi.get("hub_dominus") and not schemi.get("scatole_cinesi")):
        st.info("Nessuno schema o anomalia topologica individuata finora. Carica e analizza il fascicolo.")
    else:
        col_p1, col_p2, col_p3 = st.columns(3)
        with col_p1:
            st.markdown("#### 🚨 Flussi Circolari (Ring)")
            flussi = schemi.get("flussi_circolari", [])
            if not flussi:
                st.markdown("<p style='color: #86868b; font-size: 0.85rem;'>Nessun circuito chiuso rilevato.</p>", unsafe_allow_html=True)
            else:
                for f in flussi:
                    st.markdown(f"""
                    <div class="apple-card" style="border-left: 3px solid var(--apple-red); padding: 10px 14px;">
                        <span style="font-weight: 700; color: var(--apple-red); font-size: 0.85rem;">Circuito Chiuso:</span><br/>
                        <span style="font-size: 0.82rem; color: #f0f6fc;">{' ➔ '.join(f)} ➔ {f[0]}</span>
                    </div>
                    """, unsafe_allow_html=True)

        with col_p2:
            st.markdown("#### 🌟 Hub / Prestanome (Star)")
            hubs = schemi.get("hub_dominus", [])
            if not hubs:
                st.markdown("<p style='color: #86868b; font-size: 0.85rem;'>Nessun nodo hub anomalo.</p>", unsafe_allow_html=True)
            else:
                for h in hubs:
                    st.markdown(f"""
                    <div class="apple-card" style="border-left: 3px solid var(--apple-orange); padding: 10px 14px;">
                        <span style="font-weight: 700; color: var(--apple-orange); font-size: 0.9rem;">{h['nodo']}</span>
                        <div style="font-size: 0.8rem; color: #86868b; margin-top: 4px;">
                            <strong>Connessioni:</strong> {h['connessioni']} | <strong>Tipo:</strong> {h['tipo']}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

        with col_p3:
            st.markdown("#### 🏢 Scatole Cinesi (Chain)")
            catene_grezze = schemi.get("scatole_cinesi", [])
            catene_uniche = []
            viste = set()
            for c in catene_grezze:
                tup = tuple(c)
                if tup not in viste:
                    viste.add(tup)
                    catene_uniche.append(c)

            if not catene_uniche:
                st.markdown("<p style='color: #86868b; font-size: 0.85rem;'>Nessuna holding a cascata rilevata.</p>", unsafe_allow_html=True)
            else:
                for c in catene_uniche[:8]:
                    percorso_str = " ➔ ".join(c)
                    st.markdown(f"""
                    <div class="apple-card" style="border-left: 3px solid var(--apple-purple); padding: 10px 14px; margin-bottom: 8px;">
                        <span style="font-weight: 600; color: #BF5AF2; font-size: 0.85rem;">Catena di Controllo:</span><br/>
                        <span style="font-size: 0.85rem; color: #f0f6fc;">{percorso_str}</span>
                    </div>
                    """, unsafe_allow_html=True)

        incongruenze = schemi.get("incongruenze", [])
        if incongruenze:
            st.markdown("---")
            st.markdown("#### ⚠️ Incongruenze & Contraddizioni tra Atti (DocETL Resolve)")
            st.markdown("<p style='color: #86868b; font-size: 0.85rem;'>Divergenze di cariche, quote societarie o dati contrastanti rilevati tra documenti diversi:</p>", unsafe_allow_html=True)
            for inc in incongruenze:
                fonti_str = ", ".join(inc.get("fonti", []))
                st.markdown(f"""
                <div class="apple-card" style="border-left: 3px solid #FFD60A; padding: 12px 16px; margin-bottom: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 700; color: #FFD60A; font-size: 0.9rem;">{inc['soggetto']}</span>
                        <span class="apple-pill pill-orange">{inc['tipo']}</span>
                    </div>
                    <div style="font-size: 0.84rem; color: #e6edf3; margin-top: 6px;">
                        {inc['dettagli']}
                    </div>
                    <div style="font-size: 0.76rem; color: #86868b; margin-top: 4px;">
                        <em>Atti a confronto: {fonti_str}</em>
                    </div>
                </div>
                """, unsafe_allow_html=True)

# TAB 4: MASTER TIMELINE DEGLI EVENTI (MAGNET AXIOM CHRONOLOGY)
with tab_timeline:
    timeline_events = st.session_state.gestore_grafo.eventi_timeline
    if not timeline_events:
        st.info("Nessun evento cronologico estratto finora.")
    else:
        st.markdown("#### ⏱️ Cronologia Unificata di Eventi, Bonifici e Atti")
        st.markdown("<p style='color: #86868b; font-size: 0.85rem;'>Eventi ordinati cronologicamente estratti da tutti i documenti del fascicolo:</p>", unsafe_allow_html=True)

        for ev in timeline_events:
            st.markdown(f"""
            <div class="timeline-item">
                <div class="timeline-dot"></div>
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 700; color: #58a6ff; font-size: 0.92rem;">{ev['data']}</span>
                    <span class="apple-pill pill-blue">{ev['tipo']}</span>
                </div>
                <div style="font-size: 0.9rem; color: #ffffff; margin-top: 4px;">
                    <strong>{ev['da']}</strong> ➔ <strong>{ev['a']}</strong>
                </div>
                <div style="font-size: 0.82rem; color: #c9d1d9; margin-top: 4px;">
                    {ev['dettagli']}
                </div>
                <div style="font-size: 0.76rem; color: #86868b; margin-top: 2px;">
                    <em>Fonte Atto: {ev['atto']}</em>
                </div>
            </div>
            """, unsafe_allow_html=True)

# TAB 5: CONVERGENZE E ANAGRAFICHE DEDUPLICATE
with tab_convergenze:
    if len(st.session_state.gestore_grafo.grafo.nodes) == 0:
        st.info("In attesa dell'analisi del fascicolo.")
    else:
        snodi = st.session_state.gestore_grafo.trova_convergenze_e_snodi()
        soggetti_multi = [s for s in snodi if s["num_atti"] > 1]

        if soggetti_multi:
            st.markdown(f"#### 🔗 Punti di Convergenza Inter-Documentale ({len(soggetti_multi)} Soggetti Chiave)")
            st.markdown("<p style='color: #86868b; font-size: 0.88rem;'>Soggetti che compaiono contemporaneamente in più documenti diversi fungendo da snodo:</p>", unsafe_allow_html=True)

            col_s1, col_s2 = st.columns(2)
            for idx, s in enumerate(soggetti_multi):
                target_c = col_s1 if idx % 2 == 0 else col_s2
                tipo = s["tipo"]
                pill_c = "pill-blue" if tipo == "PERSONA" else ("pill-orange" if tipo == "SOCIETA" else "pill-green")
                with target_c:
                    st.markdown(f"""
                    <div class="apple-card" style="border: 1px solid rgba(10, 132, 255, 0.35); padding: 14px 18px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-weight: 700; color: #58a6ff; font-size: 1.05rem;">{s['id']}</span>
                            <span class="apple-pill {pill_c}">{tipo}</span>
                        </div>
                        <div style="margin-top: 6px; font-size: 0.85rem; color: var(--apple-blue);">
                            <strong>{s.get('ruolo_topologico', '')}</strong>
                        </div>
                        <div style="margin-top: 6px; font-size: 0.85rem; color: #c9d1d9;">
                            <strong>Cod. Fiscale / P.IVA:</strong> {s['cf_piva'] or 'Non indicato'}
                        </div>
                        <div style="margin-top: 4px; font-size: 0.82rem; color: #86868b;">
                            <strong>Presente in {s['num_atti']} atti:</strong> {', '.join(s['atti'])}
                        </div>
                        <div style="margin-top: 6px; font-size: 0.80rem; color: #38bdf8;">
                            <strong>Legami:</strong> {s['in_entrata']} flussi in entrata | {s['in_uscita']} in uscita
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown("---")

        st.markdown(f"#### 📋 Registro Anagrafico Unificato ({len(st.session_state.gestore_grafo.grafo.nodes)} Soggetti Totali)")
        col_e1, col_e2 = st.columns(2)
        nodi_ordinati = sorted(st.session_state.gestore_grafo.grafo.nodes(data=True), key=lambda x: x[0])
        for idx, (nodo_id, data) in enumerate(nodi_ordinati):
            target_col = col_e1 if idx % 2 == 0 else col_e2
            meta = st.session_state.gestore_grafo.dati_nodi.get(nodo_id, {})
            tipo = meta.get("tipo") or data.get("tipo", "ALTRO")
            cf_piva = meta.get("cf_piva") or data.get("cf_piva", "")
            fonti = meta.get("fonti") or {data.get("fonte", "N/D")}

            pill_class = "pill-blue" if tipo == "PERSONA" else ("pill-orange" if tipo == "SOCIETA" else "pill-green")

            with target_col:
                st.markdown(f"""
                <div class="apple-card" style="padding: 12px 16px; margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 700; color: #ffffff; font-size: 0.95rem;">{nodo_id}</span>
                        <span class="apple-pill {pill_class}">{tipo}</span>
                    </div>
                    <div style="font-size: 0.8rem; color: #86868b; margin-top: 6px;">
                        <strong>Fiscale:</strong> {cf_piva or 'Non censito'} &nbsp;|&nbsp; <strong>Atti:</strong> {', '.join(sorted(list(fonti)))}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("#### 🌐 Motore Dati FollowTheMoney (OCCRP) & Analytics DuckDB")
        st.markdown("<p style='color: #86868b; font-size: 0.85rem;'>Dati strutturati conformi all'ontologia investigativa internazionale FollowTheMoney:</p>", unsafe_allow_html=True)

        ftm_stats = st.session_state.gestore_grafo.statistiche_ftm()
        schemi_ftm = ftm_stats.get("per_schema", {})

        col_ftm = st.columns(max(1, len(schemi_ftm)))
        for idx, (schema_name, conteggio) in enumerate(schemi_ftm.items()):
            with col_ftm[idx]:
                st.markdown(f"""
                <div class="apple-card" style="text-align: center; padding: 10px;">
                    <div style="font-size: 1.2rem; font-weight: 700; color: #0A84FF;">{conteggio}</div>
                    <div style="font-size: 0.78rem; color: #86868b; margin-top: 2px;">{schema_name}</div>
                </div>
                """, unsafe_allow_html=True)

        with st.expander("🦆 Console SQL Forense (DuckDB In-Memory)", expanded=False):
            st.markdown("<p style='color: #86868b; font-size: 0.82rem;'>Interroga istantaneamente le tabelle <code>entita</code> e <code>relazioni</code> con query SQL standard:</p>", unsafe_allow_html=True)
            query_default = "SELECT nome, tipo, cf_piva, num_fonti FROM entita ORDER BY num_fonti DESC, nome ASC LIMIT 20"
            sql_input = st.text_area("Query SQL:", value=query_default, height=75)
            if st.button("⚡ Esegui Query SQL"):
                res_sql = st.session_state.gestore_grafo.esegui_query_sql(sql_input)
                if res_sql:
                    st.dataframe(pd.DataFrame(res_sql), use_container_width=True)
                else:
                    st.info("Nessun record restituito dalla query.")

# TAB 6: FASCICOLO ATTI ACQUISITI
with tab_documenti:
    if not st.session_state.documenti_acquisiti:
        st.info("Nessun documento inserito nel fascicolo.")
    else:
        for nome_doc, info in st.session_state.documenti_acquisiti.items():
            st.markdown(f"""
            <div class="apple-card" style="padding: 14px 18px; margin-bottom: 10px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 700; color: #ffffff; font-size: 1rem;">📄 {nome_doc}</span>
                    <span class="apple-pill pill-blue">{info.get('estensione', 'DOC').upper()}</span>
                </div>
                <div style="margin-top: 6px; font-size: 0.85rem; color: #86868b;">
                    <strong>Dimensioni:</strong> {info.get('caratteri', 0):,} caratteri | <strong>Pagine:</strong> {info.get('pagine', 1)} | <strong>Blocchi:</strong> {info.get('num_blocchi', 1)}
                </div>
            </div>
            """, unsafe_allow_html=True)

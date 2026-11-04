import json
import time
import datetime
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import ollama

from logger import log, leggi_ultimi_log
from parser import analizza_ed_estrai, MAX_CARATTERI_CONSIGLIATI
from ai_engine import (
    get_active_model,
    estrai_entita_e_relazioni_avanzato,
    genera_deduzioni,
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
        font-size: 1.45rem;
        font-weight: 700;
        color: #ffffff;
        letter-spacing: -0.02em;
    }
    .metric-lbl {
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--apple-text-tertiary);
        margin-top: 2px;
    }

    .stButton>button {
        background: var(--apple-blue) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 8px 18px !important;
        font-weight: 600 !important;
        font-size: 0.90rem !important;
        transition: all 0.2s ease !important;
    }
    .stButton>button:hover {
        background: var(--apple-blue-hover) !important;
        box-shadow: 0 0 15px rgba(10, 132, 255, 0.4) !important;
        transform: translateY(-1px);
    }

    .stDownloadButton>button {
        background: rgba(255, 255, 255, 0.06) !important;
        color: #ffffff !important;
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
</style>
""", unsafe_allow_html=True)

# Inizializzazione Session State
if "gestore_grafo" not in st.session_state:
    st.session_state.gestore_grafo = GestoreGrafo()
if "dossier_globale" not in st.session_state:
    st.session_state.dossier_globale = None
if "documenti_acquisiti" not in st.session_state:
    st.session_state.documenti_acquisiti = {}
if "file_letti" not in st.session_state:
    st.session_state.file_letti = set()
if "storico" not in st.session_state:
    st.session_state.storico = []
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []
if "file_forzati" not in st.session_state:
    st.session_state.file_forzati = set()
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
        <span class="apple-pill pill-blue">🔒 100% Offline (Metal M1 Pro)</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### Metriche Fascicolo Accumulato")
    num_nodi = len(st.session_state.gestore_grafo.grafo.nodes)
    num_archi = len(st.session_state.gestore_grafo.grafo.edges)
    num_doc = len(st.session_state.file_letti)

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
    schemi = st.session_state.gestore_grafo.rileva_schemi_investigativi_topologici()
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
                k: {"caratteri": v.get("num_caratteri", v.get("caratteri", 0)), "num_blocchi": v.get("num_blocchi", 1), "estensione": v.get("estensione", "")}
                for k, v in st.session_state.documenti_acquisiti.items()
            },
            "file_letti": list(st.session_state.file_letti),
            "storico": st.session_state.storico,
            "chat_messages": st.session_state.chat_messages,
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
        if st.button("🗑️ Reset", help="Azzera il fascicolo, il grafo, lo storico e la chat"):
            log.info("Reset indagine richiesto dall'utente: azzeramento totale")
            st.session_state.gestore_grafo = GestoreGrafo()
            st.session_state.dossier_globale = None
            st.session_state.documenti_acquisiti = {}
            st.session_state.file_letti = set()
            st.session_state.storico = []
            st.session_state.chat_messages = []
            st.session_state.file_forzati = set()
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
                st.session_state.documenti_acquisiti = dati.get("documenti_acquisiti", {})
                st.session_state.file_letti = set(dati.get("file_letti", []))
                st.session_state.storico = dati.get("storico", [])
                st.session_state.chat_messages = dati.get("chat_messages", [])
                st.session_state.timestamp_analisi = dati.get("timestamp_analisi")
                st.success("Sessione ripristinata con successo!")
                st.rerun()
            except Exception as e:
                log.error(f"Errore caricamento stato: {e}", exc_info=True)
                st.error(f"Errore ripristino: {e}")

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
        <p class="apple-header-subtitle">Analisi Forense Incrementale, Link Analysis Deterministica e Ragionamento Ibrido (M1 Pro / Metal Architecture).</p>
    </div>
</div>
""", unsafe_allow_html=True)

# DROPZONE INCREMENTALE MULTI-DOCUMENTO
with st.container():
    files = st.file_uploader(
        "Trascina qui SOS, Visure CCIAA, Bilanci, Estratti Conto (PDF, DOCX, XLSX, CSV, XML, TXT)",
        type=["pdf", "docx", "xlsx", "xls", "csv", "txt", "xml"],
        accept_multiple_files=True,
        help="Supporta acquisizione progressiva cumulativa: ogni nuovo documento arricchisce la memoria del grafo esistente senza sovrascriverla.",
    )

    if files:
        for f in files:
            if f.name not in st.session_state.file_letti:
                diag = analizza_ed_estrai(f)
                ok = True

                # 1. Alert Diagnostico OCR
                if diag["manca_ocr"]:
                    if diag.get("perc_senza_ocr", 0) > 0.5:
                        st.error(f"🛑 **{f.name}**: Documento scansionato privo di testo selezionabile ({len(diag['pagine_senza_ocr'])}/{diag['totale_pagine']} pagine cieche: {diag['pagine_senza_ocr']}). Applicare un software di OCR prima di acquisire l'atto.")
                        ok = False
                    else:
                        st.warning(f"⚠️ **{f.name}**: Pagine {diag['pagine_senza_ocr']} prive di testo leggibile.")

                # 2. Alert Volume Documentale con Bypass
                if diag["troppo_lungo"] and ok:
                    if f.name not in st.session_state.file_forzati:
                        st.warning(f"✂️ **{f.name}**: File di {diag['num_caratteri']:,} caratteri (supera la soglia ottimale di {MAX_CARATTERI_CONSIGLIATI:,}).")
                        if st.button(f"Forza lettura per {f.name}", key=f"force_{f.name}"):
                            st.session_state.file_forzati.add(f.name)
                            st.rerun()
                        ok = False

                # 3. Ingestione Incrementale & Entity Resolution
                if ok:
                    with st.spinner(f"🔍 [Entity Resolution & Unione della Conoscenza] Analisi incrementale di '{f.name}'..."):
                        # Estrazione entità e relazioni dal documento
                        dati_json = estrai_entita_e_relazioni_avanzato(
                            blocchi_testo=diag["blocchi"],
                            nome_file=f.name,
                            model=modello_selezionato,
                        )
                        # Fusione istantanea su grafo condiviso esistente
                        st.session_state.gestore_grafo.aggiungi_dati(dati_json, f.name)

                        # Generazione deduzioni cross-documentali immediate
                        riassunto_rete = st.session_state.gestore_grafo.ottieni_riassunto()
                        deduzione = genera_deduzioni(
                            riassunto_grafo=riassunto_rete,
                            testo_nuovo_documento=diag["testo"],
                            nome_documento=f.name,
                            model=modello_selezionato,
                        )

                        # Archiviazione nello storico analitico
                        st.session_state.storico.insert(0, {
                            "file": f.name,
                            "analisi": deduzione,
                            "caratteri": diag["num_caratteri"],
                            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                        })
                        st.session_state.file_letti.add(f.name)
                        st.session_state.documenti_acquisiti[f.name] = diag
                        st.session_state.timestamp_analisi = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
                        st.success(f"✅ Acquisito e fuso nel grafo condiviso: {f.name}")
                        time.sleep(0.5)
                        st.rerun()

st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)

# TABS PRINCIPALI (Chat Investigativa Deterministica + Dossier + Grafo + Report Atti + Schemi)
tab_chat, tab_dossier, tab_mappa, tab_report_atti, tab_schemi, tab_timeline, tab_convergenze = st.tabs([
    "💬 Chat Investigativa Forense",
    "⚖️ Dossier Forense Globale CTU",
    "🕸️ Link Analysis & Grafo",
    "📑 Report Atti & Deduzioni",
    "🎯 Schemi & Pattern AML",
    "⏱️ Master Timeline Eventi",
    "🔗 Convergenze & Anagrafiche",
])

# ==============================================================================
# TAB 1: CHAT INVESTIGATIVA CON RISOLUZIONE DETERMINISTICA IBRIDA
# ==============================================================================
with tab_chat:
    st.markdown("""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <div>
            <h3 style="margin: 0; font-size: 1.25rem;">💬 Chat Investigativa Deterministica</h3>
            <p style="margin: 4px 0 0 0; color: #86868b; font-size: 0.85rem;">
                Interroga il fascicolo con <strong>risoluzione ibrida</strong>: i quesiti su legami tra persone e quote vengono risolti matematicamente da <code>NetworkX</code> prima della risposta di Ollama.
            </p>
        </div>
        <div>
            <span class="apple-pill pill-blue">⚡ Shortest Path + Ollama (M1 Pro)</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Visualizzazione dello storico conversazionale
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat Input Interattivo
    if query := st.chat_input("Es: 'MARIO ROSSI ha contatti con ALFA SRL?' oppure 'Cosa detiene MARIO ROSSI?'"):
        with st.chat_message("user"):
            st.markdown(query)
        st.session_state.chat_messages.append({"role": "user", "content": query})

        # RISOLUZIONE DETERMINISTICA IBRIDA
        info_matematica = ""
        q_lower = query.lower()

        # Individua soggetti citati tra i nodi censiti
        nodi_censiti = list(st.session_state.gestore_grafo.grafo.nodes)
        soggetti_trovati = []
        for n in nodi_censiti:
            norm_q = query.upper().replace(" ", "_")
            norm_n = st.session_state.gestore_grafo.normalizza_nome(n)
            if n.lower() in q_lower or (len(norm_n) > 4 and norm_n in norm_q):
                soggetti_trovati.append(n)

        # Fallback di risoluzione token
        if len(soggetti_trovati) < 2:
            parole = [p for p in query.split() if len(p) >= 3 and p.lower() not in {"chi", "che", "cosa", "con", "tra", "del", "della", "delle", "dei", "negli", "nella", "ha", "hanno", "avuto", "contatti", "legami", "quote", "detiene", "partecipazioni", "società", "conto", "iban"}]
            for p in parole:
                ris = st.session_state.gestore_grafo._risolvi_nome_per_ricerca(p)
                if ris and ris not in soggetti_trovati:
                    soggetti_trovati.append(ris)

        # 1. Domanda su Contatti / Collegamenti / Shortest Path
        if any(k in q_lower for k in ["contatt", "collegat", "legam", "rapport", "passaggi", "conness"]) and len(soggetti_trovati) >= 2:
            info_matematica = st.session_state.gestore_grafo.analizza_contatti(soggetti_trovati[0], soggetti_trovati[1])
        # 2. Domanda su Quote / Partecipazioni / Cariche
        elif any(k in q_lower for k in ["detiene", "partecip", "possied", "quot", "carich", "amministra", "ruol"]) and len(soggetti_trovati) >= 1:
            info_matematica = st.session_state.gestore_grafo.calcola_partecipazioni(soggetti_trovati[0])

        with st.chat_message("assistant"):
            with st.spinner("Elaborazione investigativa con riscontro matematico..."):
                contesto_generale = st.session_state.gestore_grafo.ottieni_riassunto()
                prompt_sistema = f"""
Sei un Perito Forense Antiriciclaggio (AML) e Investigatore della Guardia di Finanza.
Rispondi alla domanda dell'utente con massimo rigore, chiarezza motivazionale e citando le fonti degli atti.

RISCONTRI MATEMATICI DETERMINISTICI (PREVALENZA ASSOLUTA - NON CONTRADDIRE QUESTI FATTI):
{info_matematica if info_matematica else "Nessun vincolo di cammino matematico puntuale applicabile."}

QUADRO COMPLESSIVO DELLA RETE D'INDAGINE:
{contesto_generale}
"""
                messaggi_ollama = [{"role": "system", "content": prompt_sistema}]
                messaggi_ollama.extend(st.session_state.chat_messages[-6:])

                try:
                    res = ollama.chat(
                        model=modello_selezionato,
                        messages=messaggi_ollama,
                        options={"temperature": 0.1, "num_ctx": 8192},
                    )
                    testo_risposta = res["message"]["content"]
                except Exception as e:
                    testo_risposta = f"Errore durante l'interrogazione del modello locale: {e}"

                st.markdown(testo_risposta)
                st.session_state.chat_messages.append({"role": "assistant", "content": testo_risposta})

# ==============================================================================
# TAB 2: DOSSIER FORENSE COMPLESSIVO UNIFICATO (RELAZIONE CTU 7 CAPITOLI)
# ==============================================================================
with tab_dossier:
    c_btn1, c_btn2 = st.columns([2, 1])
    with c_btn1:
        st.markdown(f"**Fascicolo Attivo**: {len(st.session_state.file_letti)} atti acquisiti ({len(st.session_state.gestore_grafo.grafo.nodes)} entità unificate, {len(st.session_state.gestore_grafo.grafo.edges)} relazioni probatorie).")
    with c_btn2:
        bottone_dossier = st.button(
            "🚀 Compila / Aggiorna Dossier Globale CTU",
            disabled=(len(st.session_state.file_letti) == 0),
            use_container_width=True,
            help="Redige la perizia integrata strutturata su 7 capitoli giudiziari incrociando tutti i documenti caricati finora.",
        )

    if bottone_dossier and st.session_state.documenti_acquisiti:
        with st.spinner("Redazione della perizia forense unificata su tutti gli atti del fascicolo..."):
            testi_per_dossier = {k: v["testo"] for k, v in st.session_state.documenti_acquisiti.items()}
            dossier_unificato = genera_dossier_forense_globale(
                gestore_grafo=st.session_state.gestore_grafo,
                estratti_documenti=testi_per_dossier,
                model=modello_selezionato,
                ha_grafo=True,
            )
            st.session_state.dossier_globale = dossier_unificato
            st.session_state.timestamp_analisi = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
            st.rerun()

    if not st.session_state.dossier_globale:
        st.markdown("""
        <div class="apple-card" style="text-align: center; padding: 45px 20px;">
            <div style="font-size: 2.3rem; margin-bottom: 12px;">⚖️</div>
            <h3 style="margin: 0; color: #ffffff; font-size: 1.2rem;">Nessun Dossier Globale Ancora Generato</h3>
            <p style="color: #86868b; margin-top: 8px; font-size: 0.92rem; max-width: 650px; margin-left: auto; margin-right: auto;">
                Clicca su <strong>"Compila / Aggiorna Dossier Globale CTU"</strong> in alto a destra per redigere la perizia peritale giudiziaria di 7 capitoli che incrocia analiticamente tutti i documenti finora acquisiti.
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
            <div>
                <span class="apple-pill pill-green">✅ Relazione Peritale Integrata</span>
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

        st.markdown('<div class="dossier-box">', unsafe_allow_html=True)
        st.markdown(st.session_state.dossier_globale)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)
        st.download_button(
            label="📄 Scarica Relazione Forense Unificata (.md)",
            data=st.session_state.dossier_globale,
            file_name=f"Dossier_Forense_Integrato_{datetime.date.today().strftime('%Y%m%d')}.md",
            mime="text/markdown",
        )

# ==============================================================================
# TAB 3: LINK ANALYSIS & GRAFO RELAZIONALE VIS.JS + MERMAID
# ==============================================================================
with tab_mappa:
    if len(st.session_state.gestore_grafo.grafo.nodes) == 0:
        st.info("In attesa di acquisire i primi documenti per generare la mappa relazionale.")
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

# ==============================================================================
# TAB 4: REPORT ATTI & DEDUZIONI CUMULATIVE
# ==============================================================================
with tab_report_atti:
    st.markdown("### 📑 Deduzioni e Punti Salienti per Singolo Atto Acquisito")
    if not st.session_state.storico:
        st.info("Nessun atto analizzato finora. Carica uno o più documenti nella dropzone in alto per visualizzare le deduzioni incrementali.")
    else:
        for idx, item in enumerate(st.session_state.storico):
            with st.expander(f"📄 Atto: {item['file']} (Acquisito alle {item.get('timestamp', 'N/D')} - {item.get('caratteri', 0):,} caratteri)", expanded=(idx == 0)):
                st.markdown(item["analisi"])

# ==============================================================================
# TAB 5: SCHEMI & PATTERN TOPOLOGICI (BELKASOFT / CELLEBRITE PATTERN)
# ==============================================================================
with tab_schemi:
    schemi = st.session_state.gestore_grafo.rileva_schemi_investigativi_topologici()
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
                        <span style="font-weight: 700; color: var(--apple-orange); font-size: 0.88rem;">{h['nodo']}</span><br/>
                        <span style="font-size: 0.80rem; color: #86868b;">Grado: {h['connessioni']} | Atti: {h['atti_coinvolti']} | {h['tipo']}</span>
                    </div>
                    """, unsafe_allow_html=True)

        with col_p3:
            st.markdown("#### 🏢 Scatole Cinesi (Chain)")
            catene_raw = schemi.get("scatole_cinesi", [])
            catene = []
            viste_c = set()
            for c in catene_raw:
                tup_c = tuple(c)
                if tup_c not in viste_c:
                    viste_c.add(tup_c)
                    catene.append(c)

            if not catene:
                st.markdown("<p style='color: #86868b; font-size: 0.85rem;'>Nessuna catena societaria multilivello.</p>", unsafe_allow_html=True)
            else:
                for c in catene[:8]:
                    st.markdown(f"""
                    <div class="apple-card" style="border-left: 3px solid var(--apple-purple); padding: 10px 14px;">
                        <span style="font-weight: 700; color: var(--apple-purple); font-size: 0.85rem;">Catena di Controllo:</span><br/>
                        <span style="font-size: 0.82rem; color: #f0f6fc;">{' ➔ '.join(c)}</span>
                    </div>
                    """, unsafe_allow_html=True)

# ==============================================================================
# TAB 6: MASTER TIMELINE CRONOLOGICA DEGLI EVENTI
# ==============================================================================
with tab_timeline:
    timeline_ev = st.session_state.gestore_grafo.ottieni_timeline_forense()
    if not timeline_ev:
        st.info("Nessun evento datato rilevato negli atti acquisiti.")
    else:
        st.markdown(f"**Cronologia Giudiziaria Forense**: {len(timeline_ev)} eventi ricostruiti temporalmente.")
        for ev in timeline_ev:
            st.markdown(f"""
            <div class="apple-card" style="padding: 12px 18px; margin-bottom: 8px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 700; color: #0A84FF; font-size: 0.95rem;">📅 {ev.get('data', 'Data non specificata')}</span>
                    <span class="apple-pill pill-blue">{ev.get('fonte', 'Atto')}</span>
                </div>
                <div style="font-size: 0.88rem; color: #f0f6fc; margin-top: 6px;">
                    <strong>{ev.get('soggetto_da', '')}</strong> ➔ <i>{ev.get('tipo', 'OPERAZIONE')}</i> ➔ <strong>{ev.get('soggetto_a', '')}</strong>
                </div>
                <div style="font-size: 0.82rem; color: #86868b; margin-top: 4px;">
                    {ev.get('dettagli', '')}
                </div>
            </div>
            """, unsafe_allow_html=True)

# ==============================================================================
# TAB 7: CONVERGENZE, ANAGRAFICHE & ANALYTICS DUCKDB
# ==============================================================================
with tab_convergenze:
    snodi = st.session_state.gestore_grafo.trova_convergenze_e_snodi()
    if not snodi:
        st.info("Nessun soggetto censito al momento.")
    else:
        st.markdown(f"#### 🌟 Snodi Chiave e Soggetti Ricorrenti ({len(snodi)} soggetti)")
        col_s1, col_s2 = st.columns(2)
        for idx, s in enumerate(snodi[:10]):
            target_c = col_s1 if idx % 2 == 0 else col_s2
            tipo = s.get("tipo", "ALTRO")
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

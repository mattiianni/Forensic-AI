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

# Inizializzazione Session State
if "tema" not in st.session_state:
    st.session_state.tema = "dark"
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

# ==============================================================================
# APPLE MATERIAL THEME DEFINITIONS (Dark vs Light Mode)
# ==============================================================================
is_light = (st.session_state.tema == "light")

if is_light:
    c_bg = "#F5F5F7"
    c_sidebar = "#E8E8ED"
    c_card = "#FFFFFF"
    c_card_inner = "#F9F9FA"
    c_border = "rgba(0, 0, 0, 0.08)"
    c_border_hover = "rgba(0, 113, 227, 0.3)"
    c_text_primary = "#1D1D1F"
    c_text_secondary = "#515154"
    c_text_tertiary = "#86868B"
    c_blue = "#0071E3"
    c_blue_hover = "#0077ED"
    c_blue_bg = "rgba(0, 113, 227, 0.10)"
    c_tab_bg = "rgba(0, 0, 0, 0.05)"
    c_tab_active_bg = "#FFFFFF"
    c_tab_active_text = "#0071E3"
    c_shadow = "0 2px 14px rgba(0, 0, 0, 0.05)"
    c_code_bg = "#F0F0F2"
    c_terminal_bg = "#1E2024"
    c_terminal_text = "#38BDF8"
else:
    c_bg = "#0D1117"
    c_sidebar = "#080B10"
    c_card = "rgba(22, 27, 34, 0.85)"
    c_card_inner = "rgba(255, 255, 255, 0.025)"
    c_border = "rgba(255, 255, 255, 0.08)"
    c_border_hover = "rgba(10, 132, 255, 0.4)"
    c_text_primary = "#F5F5F7"
    c_text_secondary = "#8B949E"
    c_text_tertiary = "#6E6E73"
    c_blue = "#0A84FF"
    c_blue_hover = "#0071E3"
    c_blue_bg = "rgba(10, 132, 255, 0.15)"
    c_tab_bg = "rgba(255, 255, 255, 0.04)"
    c_tab_active_bg = "rgba(255, 255, 255, 0.15)"
    c_tab_active_text = "#FFFFFF"
    c_shadow = "0 4px 20px rgba(0, 0, 0, 0.35)"
    c_code_bg = "#161B22"
    c_terminal_bg = "#07090D"
    c_terminal_text = "#38BDF8"

st.markdown(f"""
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" />
<style>
    @import url('https://fonts.googleapis.com/css2?family=SF+Pro+Display:wght@400;500;600;700&display=swap');

    /* 1. NASCONDI IL TASTO DEPLOY, FOOTER E CHROME STREAMLIT */
    .stDeployButton, [data-testid="stDeployButton"], .stAppDeployButton {{
        display: none !important;
        visibility: hidden !important;
    }}
    #MainMenu {{
        visibility: hidden !important;
    }}
    header[data-testid="stHeader"] {{
        background: transparent !important;
        height: 2.5rem !important;
    }}
    footer {{
        display: none !important;
    }}

    /* 2. COLORI E FONT GLOBALI */
    html, body, [class*="css"], [data-testid="stAppViewContainer"] {{
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif !important;
        background-color: {c_bg} !important;
        color: {c_text_primary} !important;
        letter-spacing: -0.01em;
    }}

    .material-symbols-outlined {{
        font-family: 'Material Symbols Outlined' !important;
        font-weight: normal;
        font-style: normal;
        font-size: 20px;
        line-height: 1;
        letter-spacing: normal;
        text-transform: none;
        display: inline-block;
        white-space: nowrap;
        word-wrap: normal;
        direction: ltr;
        vertical-align: middle;
        -webkit-font-feature-settings: 'liga';
        -webkit-font-smoothing: antialiased;
    }}

    /* 3. SIDEBAR MAC OS SEQUOIA STYLE */
    [data-testid="stSidebar"] {{
        background-color: {c_sidebar} !important;
        border-right: 1px solid {c_border} !important;
        min-width: 330px !important;
        max-width: 370px !important;
        padding-top: 1rem !important;
    }}

    .sidebar-section-title {{
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.76rem !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em !important;
        color: {c_text_tertiary} !important;
        font-weight: 700 !important;
        margin-top: 0.8rem !important;
        margin-bottom: 0.4rem !important;
    }}

    .apple-card {{
        background: {c_card};
        border: 1px solid {c_border};
        border-radius: 12px;
        padding: 14px 16px;
        margin-bottom: 12px;
        box-shadow: {c_shadow};
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        transition: border-color 0.2s ease;
    }}
    .apple-card:hover {{
        border-color: {c_border_hover};
    }}

    .apple-header {{
        display: flex;
        align-items: center;
        gap: 16px;
        margin-bottom: 16px;
        padding-bottom: 16px;
        border-bottom: 1px solid {c_border};
    }}
    .apple-header-icon {{
        width: 48px;
        height: 48px;
        border-radius: 12px;
        background: linear-gradient(135deg, {c_blue}, #5856D6);
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        box-shadow: 0 4px 14px rgba(0, 113, 227, 0.3);
    }}
    .apple-header-title {{
        font-size: 1.85rem;
        font-weight: 700;
        letter-spacing: -0.025em;
        color: {c_text_primary};
        margin: 0;
        line-height: 1.2;
    }}
    .apple-header-subtitle {{
        font-size: 0.90rem;
        color: {c_text_secondary};
        margin: 4px 0 0 0;
        line-height: 1.4;
    }}

    .apple-pill {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 600;
        white-space: nowrap;
    }}
    .pill-blue {{
        background: {c_blue_bg};
        color: {c_blue};
        border: 1px solid {c_blue_bg};
    }}
    .pill-green {{
        background: rgba(48, 209, 88, 0.15);
        color: #30D158;
        border: 1px solid rgba(48, 209, 88, 0.3);
    }}
    .pill-orange {{
        background: rgba(255, 159, 10, 0.15);
        color: #FF9F0A;
        border: 1px solid rgba(255, 159, 10, 0.3);
    }}
    .pill-red {{
        background: rgba(255, 69, 58, 0.15);
        color: #FF453A;
        border: 1px solid rgba(255, 69, 58, 0.3);
    }}
    .pill-purple {{
        background: rgba(191, 90, 242, 0.15);
        color: #BF5AF2;
        border: 1px solid rgba(191, 90, 242, 0.3);
    }}

    /* 4. METRICHE IN GRIGLIA PULITA */
    .metric-row {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 8px;
        margin-top: 4px;
        margin-bottom: 8px;
    }}
    .metric-box {{
        background: {c_card_inner};
        border: 1px solid {c_border};
        border-radius: 10px;
        padding: 10px 6px;
        text-align: center;
    }}
    .metric-val {{
        font-size: 1.35rem;
        font-weight: 700;
        color: {c_text_primary};
        letter-spacing: -0.02em;
        line-height: 1;
    }}
    .metric-lbl {{
        font-size: 0.68rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: {c_text_tertiary};
        margin-top: 4px;
        font-weight: 600;
    }}

    /* 5. TABS DI NAVIGAZIONE A SEGMENTI (NESSUNA SOVRAPPOSIZIONE) */
    .stTabs [data-baseweb="tab-list"] {{
        display: flex !important;
        flex-wrap: wrap !important;
        gap: 6px !important;
        background: {c_tab_bg} !important;
        padding: 6px !important;
        border-radius: 12px !important;
        border: 1px solid {c_border} !important;
        width: 100% !important;
        margin-bottom: 14px !important;
    }}
    .stTabs [data-baseweb="tab"] {{
        height: 38px !important;
        padding: 0 16px !important;
        border-radius: 8px !important;
        font-size: 0.86rem !important;
        font-weight: 500 !important;
        color: {c_text_secondary} !important;
        border: 1px solid transparent !important;
        background: transparent !important;
        white-space: nowrap !important;
        transition: all 0.15s ease-in-out !important;
    }}
    .stTabs [data-baseweb="tab"]:hover {{
        color: {c_text_primary} !important;
        background: rgba(128, 128, 128, 0.08) !important;
    }}
    .stTabs [aria-selected="true"] {{
        background: {c_tab_active_bg} !important;
        color: {c_tab_active_text} !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15) !important;
        border: 1px solid {c_border} !important;
        font-weight: 600 !important;
    }}

    /* 6. BOTTONI APPLE STYLE */
    .stButton>button {{
        background: {c_blue} !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 7px 16px !important;
        font-weight: 600 !important;
        font-size: 0.88rem !important;
        transition: all 0.18s ease-in-out !important;
        box-shadow: 0 2px 6px rgba(0, 113, 227, 0.25) !important;
    }}
    .stButton>button:hover {{
        background: {c_blue_hover} !important;
        box-shadow: 0 4px 12px rgba(0, 113, 227, 0.35) !important;
        transform: translateY(-1px);
    }}

    .stDownloadButton>button {{
        background: {c_card_inner} !important;
        color: {c_text_primary} !important;
        border: 1px solid {c_border} !important;
        border-radius: 10px !important;
        font-weight: 500 !important;
        font-size: 0.84rem !important;
        width: 100% !important;
        transition: all 0.15s ease-in-out !important;
    }}
    .stDownloadButton>button:hover {{
        border-color: {c_blue} !important;
        color: {c_blue} !important;
    }}

    /* 7. DROPZONE UPLOAD */
    [data-testid="stFileUploader"] {{
        background: {c_card_inner} !important;
        border: 1.5px dashed {c_blue} !important;
        border-radius: 12px !important;
        padding: 14px !important;
    }}

    .log-box {{
        font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
        font-size: 0.74rem;
        background-color: {c_terminal_bg};
        color: {c_terminal_text};
        padding: 10px 12px;
        border-radius: 8px;
        border: 1px solid {c_border};
        height: 200px;
        overflow-y: auto;
        white-space: pre-wrap;
    }}

    .dossier-box {{
        background: {c_card};
        border: 1px solid {c_border};
        border-radius: 14px;
        padding: 24px 28px;
        line-height: 1.65;
        box-shadow: {c_shadow};
    }}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# SIDEBAR MODULARE: 5 CARD ORDINATE
# ==============================================================================
with st.sidebar:
    # CARD 1: TEMA & MOTORE IA
    st.markdown('<div class="sidebar-section-title"><span class="material-symbols-outlined" style="font-size:16px;">settings</span> Configurazione Sistema</div>', unsafe_allow_html=True)
    st.markdown('<div class="apple-card">', unsafe_allow_html=True)

    # Toggle Tema Chiaro / Scuro
    col_t1, col_t2 = st.columns([1, 1.2])
    with col_t1:
        st.markdown(f"<span style='font-size: 0.85rem; font-weight: 600; color:{c_text_primary};'>Interfaccia</span>", unsafe_allow_html=True)
    with col_t2:
        tema_scelto = st.toggle("☀️ Tema Chiaro" if not is_light else "🌙 Tema Scuro", value=is_light, key="switch_tema_app")
        if tema_scelto != is_light:
            st.session_state.tema = "light" if tema_scelto else "dark"
            st.rerun()

    st.markdown(f"<hr style='margin: 8px 0; border: none; border-top: 1px solid {c_border};'/>", unsafe_allow_html=True)

    profilo = st.radio(
        "Modello di Ragionamento:",
        options=[
            "Massima Precisione (Qwen 2.5 7B)",
            "Scansione Rapida (Llama 3.2 3B)",
        ],
        index=0,
        label_visibility="visible",
    )
    modello_selezionato = BEST_MODEL if "Qwen" in profilo else FAST_MODEL

    st.markdown(f"""
    <div style="margin-top: 8px;">
        <span class="apple-pill pill-blue"><span class="material-symbols-outlined" style="font-size:14px;">bolt</span> Apple Silicon Metal M1 Pro</span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # CARD 2: METRICHE FASCICOLO ACCUMULATO
    st.markdown('<div class="sidebar-section-title"><span class="material-symbols-outlined" style="font-size:16px;">analytics</span> Metriche Fascicolo</div>', unsafe_allow_html=True)
    st.markdown('<div class="apple-card">', unsafe_allow_html=True)
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

    # Pattern Alert Pills
    schemi = st.session_state.gestore_grafo.rileva_schemi_investigativi_topologici()
    cicli = schemi.get("flussi_circolari", [])
    if cicli:
        st.markdown(f"""
        <div class="apple-pill pill-red" style="width: 100%; justify-content: center; margin-top: 6px;">
            <span class="material-symbols-outlined" style="font-size:14px;">sync_problem</span> {len(cicli)} Flussi Circolari (Ring)
        </div>
        """, unsafe_allow_html=True)

    hubs = schemi.get("hub_dominus", [])
    if hubs:
        st.markdown(f"""
        <div class="apple-pill pill-orange" style="width: 100%; justify-content: center; margin-top: 6px;">
            <span class="material-symbols-outlined" style="font-size:14px;">hub</span> {len(hubs)} Hub / Dominus (Star)
        </div>
        """, unsafe_allow_html=True)

    scatole = schemi.get("scatole_cinesi", [])
    if scatole:
        st.markdown(f"""
        <div class="apple-pill pill-purple" style="width: 100%; justify-content: center; margin-top: 6px;">
            <span class="material-symbols-outlined" style="font-size:14px;">account_tree</span> {len(scatole)} Catene di Controllo (Chain)
        </div>
        """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # CARD 3: GESTIONE INDAGINE & BACKUP
    st.markdown('<div class="sidebar-section-title"><span class="material-symbols-outlined" style="font-size:16px;">folder_managed</span> Gestione Indagine</div>', unsafe_allow_html=True)
    st.markdown('<div class="apple-card">', unsafe_allow_html=True)

    col_btn_a, col_btn_b = st.columns(2)
    with col_btn_a:
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
            use_container_width=True,
        )
    with col_btn_b:
        if st.button("🗑️ Reset", help="Azzera fascicolo, grafo e chat", use_container_width=True):
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

    with st.expander("📥 Ripristina Backup JSON", expanded=False):
        file_stato = st.file_uploader("Carica file sessione:", type=["json"], key="loader_sessione", label_visibility="collapsed")
        if file_stato is not None:
            if st.button("Conferma Ripristino", use_container_width=True):
                try:
                    dati = json.loads(file_stato.read().decode("utf-8"))
                    st.session_state.gestore_grafo.importa_stato(dati.get("grafo_dati", {}))
                    st.session_state.dossier_globale = dati.get("dossier_globale")
                    st.session_state.documenti_acquisiti = dati.get("documenti_acquisiti", {})
                    st.session_state.file_letti = set(dati.get("file_letti", []))
                    st.session_state.storico = dati.get("storico", [])
                    st.session_state.chat_messages = dati.get("chat_messages", [])
                    st.session_state.timestamp_analisi = dati.get("timestamp_analisi")
                    st.success("Sessione ripristinata!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")

    if num_nodi > 0:
        st.markdown(f"<div style='font-size:0.75rem; font-weight:700; color:{c_text_tertiary}; margin: 8px 0 4px 0; text-transform:uppercase;'>Esportazioni Forensi</div>", unsafe_allow_html=True)
        progetto_pdf_rel = st.session_state.gestore_grafo.esporta_progetto_pdf_relations()
        st.download_button(
            label="🔗 Cytoscape (.relazioni.json)",
            data=json.dumps(progetto_pdf_rel, indent=2, ensure_ascii=False),
            file_name="indagine_forense.relazioni.json",
            mime="application/json",
            use_container_width=True,
        )

        dati_ftm = st.session_state.gestore_grafo.esporta_followthemoney_jsonl()
        st.download_button(
            label="🌐 FollowTheMoney OCCRP (.ftm.json)",
            data=dati_ftm,
            file_name="indagine_forense.ftm.json",
            mime="application/x-jsonlines",
            use_container_width=True,
        )

        codice_mmd = st.session_state.gestore_grafo.esporta_mermaid(orientamento="TD")
        st.download_button(
            label="🧜 Diagramma Mermaid (.mmd)",
            data=codice_mmd,
            file_name="indagine_forense.mmd",
            mime="text/vnd.mermaid",
            use_container_width=True,
        )

    st.markdown('</div>', unsafe_allow_html=True)

    # CARD 4: LOG ATTIVO
    st.markdown('<div class="sidebar-section-title"><span class="material-symbols-outlined" style="font-size:16px;">terminal</span> Diagnostica & Log</div>', unsafe_allow_html=True)
    st.markdown('<div class="apple-card">', unsafe_allow_html=True)
    with st.expander("Visualizza Log Recente", expanded=False):
        testo_log = leggi_ultimi_log(max_righe=60)
        st.markdown(f'<div class="log-box">{testo_log}</div>', unsafe_allow_html=True)
        if st.button("Aggiorna Log", use_container_width=True):
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # CARD 5: CONTROLLO SERVER
    st.markdown('<div class="sidebar-section-title"><span class="material-symbols-outlined" style="font-size:16px;">power_settings_new</span> Sessione Server</div>', unsafe_allow_html=True)
    st.markdown('<div class="apple-card">', unsafe_allow_html=True)
    if st.button("Arresta Server Locale", help="Termina il server Streamlit e rilascia la porta", use_container_width=True):
        import os, signal
        st.warning("Arresto del server in corso...")
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)
    st.markdown('</div>', unsafe_allow_html=True)

# ==============================================================================
# INTESTAZIONE PRINCIPALE APPLICAZIONE (Apple Desktop Header)
# ==============================================================================
st.markdown(f"""
<div class="apple-header">
    <div class="apple-header-icon">
        <span class="material-symbols-outlined" style="font-size: 28px;">balance</span>
    </div>
    <div style="flex: 1;">
        <div style="display: flex; align-items: center; gap: 10px;">
            <h1 class="apple-header-title">Forensic AI Offline</h1>
            <span class="apple-pill pill-blue"><span class="material-symbols-outlined" style="font-size:13px;">verified_user</span> 100% Locale</span>
        </div>
        <p class="apple-header-subtitle">Analisi Forense Incrementale, Link Analysis Deterministica e Ragionamento Ibrido su Fascicoli Societari e Bancari.</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ==============================================================================
# DROPZONE MULTI-DOCUMENTO INCREMENTALE
# ==============================================================================
with st.container():
    files = st.file_uploader(
        "Trascina qui SOS, Visure CCIAA, Bilanci, Estratti Conto (PDF, DOCX, XLSX, CSV, XML, TXT)",
        type=["pdf", "docx", "xlsx", "xls", "csv", "txt", "xml"],
        accept_multiple_files=True,
        help="Supporta acquisizione progressiva: ogni nuovo documento arricchisce la memoria del grafo condiviso.",
    )

    if files:
        for f in files:
            if f.name not in st.session_state.file_letti:
                diag = analizza_ed_estrai(f)
                ok = True

                # Alert OCR
                if diag["manca_ocr"]:
                    if diag.get("perc_senza_ocr", 0) > 0.5:
                        st.error(f"🛑 **{f.name}**: Documento scansionato privo di testo selezionabile ({len(diag['pagine_senza_ocr'])}/{diag['totale_pagine']} pagine cieche: {diag['pagine_senza_ocr']}). Applicare OCR prima di ricaricare.")
                        ok = False
                    else:
                        st.warning(f"⚠️ **{f.name}**: Pagine {diag['pagine_senza_ocr']} prive di testo leggibile.")

                # Alert Lunghezza con Bypass
                if diag["troppo_lungo"] and ok:
                    if f.name not in st.session_state.file_forzati:
                        st.warning(f"✂️ **{f.name}**: File di {diag['num_caratteri']:,} caratteri (supera la soglia di {MAX_CARATTERI_CONSIGLIATI:,}).")
                        if st.button(f"Forza lettura per {f.name}", key=f"force_{f.name}"):
                            st.session_state.file_forzati.add(f.name)
                            st.rerun()
                        ok = False

                # Ingestione & Entity Resolution
                if ok:
                    with st.spinner(f"🔍 [Entity Resolution & Unione della Conoscenza] Analisi incrementale di '{f.name}'..."):
                        dati_json = estrai_entita_e_relazioni_avanzato(
                            blocchi_testo=diag["blocchi"],
                            nome_file=f.name,
                            model=modello_selezionato,
                        )
                        st.session_state.gestore_grafo.aggiungi_dati(dati_json, f.name)

                        riassunto_rete = st.session_state.gestore_grafo.ottieni_riassunto()
                        deduzione = genera_deduzioni(
                            riassunto_grafo=riassunto_rete,
                            testo_nuovo_documento=diag["testo"],
                            nome_documento=f.name,
                            model=modello_selezionato,
                        )

                        st.session_state.storico.insert(0, {
                            "file": f.name,
                            "analisi": deduzione,
                            "caratteri": diag["num_caratteri"],
                            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                        })
                        st.session_state.file_letti.add(f.name)
                        st.session_state.documenti_acquisiti[f.name] = diag
                        st.session_state.timestamp_analisi = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
                        st.success(f"✅ Acquisito e integrato nel grafo: {f.name}")
                        time.sleep(0.4)
                        st.rerun()

st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)

# ==============================================================================
# TABS PRINCIPALI: PULITI, FLESSIBILI E SENZA SOVRAPPOSIZIONI
# ==============================================================================
tab_chat, tab_dossier, tab_mappa, tab_report_atti, tab_schemi, tab_timeline, tab_convergenze = st.tabs([
    "💬 Chat Forense",
    "📑 Dossier CTU",
    "🕸️ Link Analysis",
    "📄 Report Atti",
    "🎯 Pattern AML",
    "⏱️ Timeline",
    "👥 Anagrafiche",
])

# ------------------------------------------------------------------------------
# TAB 1: CHAT INVESTIGATIVA DETERMINISTICA IBRIDA
# ------------------------------------------------------------------------------
with tab_chat:
    st.markdown(f"""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <div>
            <h3 style="margin: 0; font-size: 1.15rem; color:{c_text_primary};">💬 Assistente Investigativo con Risoluzione Ibrida</h3>
            <p style="margin: 3px 0 0 0; color: {c_text_secondary}; font-size: 0.85rem;">
                I quesiti su contatti tra soggetti e partecipazioni sono risolti <strong>matematicamente</strong> da NetworkX prima della risposta di Ollama.
            </p>
        </div>
        <div>
            <span class="apple-pill pill-blue"><span class="material-symbols-outlined" style="font-size:14px;">route</span> Shortest Path + LLM</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Messaggi
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if query := st.chat_input("Es: 'MARIO ROSSI ha contatti con ALFA SRL?' oppure 'Cosa detiene MARIO ROSSI?'"):
        with st.chat_message("user"):
            st.markdown(query)
        st.session_state.chat_messages.append({"role": "user", "content": query})

        info_matematica = ""
        q_lower = query.lower()

        nodi_censiti = list(st.session_state.gestore_grafo.grafo.nodes)
        soggetti_trovati = []
        for n in nodi_censiti:
            norm_q = query.upper().replace(" ", "_")
            norm_n = st.session_state.gestore_grafo.normalizza_nome(n)
            if n.lower() in q_lower or (len(norm_n) > 4 and norm_n in norm_q):
                soggetti_trovati.append(n)

        if len(soggetti_trovati) < 2:
            parole = [p for p in query.split() if len(p) >= 3 and p.lower() not in {"chi", "che", "cosa", "con", "tra", "del", "della", "delle", "dei", "negli", "nella", "ha", "hanno", "avuto", "contatti", "legami", "quote", "detiene", "partecipazioni", "società", "conto", "iban"}]
            for p in parole:
                ris = st.session_state.gestore_grafo._risolvi_nome_per_ricerca(p)
                if ris and ris not in soggetti_trovati:
                    soggetti_trovati.append(ris)

        if any(k in q_lower for k in ["contatt", "collegat", "legam", "rapport", "passaggi", "conness"]) and len(soggetti_trovati) >= 2:
            info_matematica = st.session_state.gestore_grafo.analizza_contatti(soggetti_trovati[0], soggetti_trovati[1])
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

# ------------------------------------------------------------------------------
# TAB 2: DOSSIER FORENSE GLOBALE CTU (7 CAPITOLI GIUDIZIARI)
# ------------------------------------------------------------------------------
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
        st.markdown(f"""
        <div class="apple-card" style="text-align: center; padding: 40px 20px;">
            <div style="font-size: 2.2rem; margin-bottom: 8px;">⚖️</div>
            <h3 style="margin: 0; color: {c_text_primary}; font-size: 1.15rem;">Nessun Dossier Globale Generato</h3>
            <p style="color: {c_text_secondary}; margin-top: 8px; font-size: 0.90rem; max-width: 600px; margin-left: auto; margin-right: auto;">
                Clicca su <strong>"Compila / Aggiorna Dossier Globale CTU"</strong> in alto a destra per comporre la perizia giudiziaria di 7 capitoli che incrocia analiticamente tutti i documenti acquisiti.
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <div>
                <span class="apple-pill pill-green">Relazione Peritale Integrata</span>
                <span style="color: {c_text_secondary}; font-size: 0.85rem; margin-left: 10px;">Elaborata il {st.session_state.timestamp_analisi} su {len(st.session_state.documenti_acquisiti)} atti</span>
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
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 14px;">
            <div class="apple-card" style="padding: 12px 14px;">
                <div style="font-size: 0.72rem; color: {c_text_tertiary}; text-transform: uppercase; font-weight: 700;">Volume Finanziario Tracciato</div>
                <div style="font-size: 1.3rem; font-weight: 700; color: #30D158; margin-top: 4px;">€ {tot_val:,.2f}</div>
            </div>
            <div class="apple-card" style="padding: 12px 14px;">
                <div style="font-size: 0.72rem; color: {c_text_tertiary}; text-transform: uppercase; font-weight: 700;">Operazioni Rilevate</div>
                <div style="font-size: 1.3rem; font-weight: 700; color: {c_blue}; margin-top: 4px;">{n_trans} movimenti</div>
            </div>
            <div class="apple-card" style="padding: 12px 14px;">
                <div style="font-size: 0.72rem; color: {c_text_tertiary}; text-transform: uppercase; font-weight: 700;">Soggetti Censiti</div>
                <div style="font-size: 1.3rem; font-weight: 700; color: #BF5AF2; margin-top: 4px;">{len(st.session_state.gestore_grafo.grafo.nodes)} entità</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="dossier-box">', unsafe_allow_html=True)
        st.markdown(st.session_state.dossier_globale)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)
        st.download_button(
            label="📄 Scarica Relazione Forense Unificata (.md)",
            data=st.session_state.dossier_globale,
            file_name=f"Dossier_Forense_Integrato_{datetime.date.today().strftime('%Y%m%d')}.md",
            mime="text/markdown",
        )

# ------------------------------------------------------------------------------
# TAB 3: LINK ANALYSIS & GRAFO RELAZIONALE
# ------------------------------------------------------------------------------
with tab_mappa:
    if len(st.session_state.gestore_grafo.grafo.nodes) == 0:
        st.info("In attesa di acquisire i primi documenti per generare la mappa relazionale.")
    else:
        cicli_rilevati = st.session_state.gestore_grafo.trova_cicli()
        if cicli_rilevati:
            st.markdown(f"""
            <div class="apple-card" style="border-left: 4px solid #FF453A; margin-bottom: 14px;">
                <h4 style="margin: 0 0 6px 0; color: #FF453A;">🚨 Flussi Circolari e Triangolazioni Rilevate</h4>
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

        st.markdown(f"<hr style='margin: 16px 0; border: none; border-top: 1px solid {c_border};'/>", unsafe_allow_html=True)
        st.markdown(f"<h4 style='color:{c_text_primary}; margin-bottom: 4px;'>🧜 Esportazione Diagramma Mermaid</h4>", unsafe_allow_html=True)
        st.markdown(f"<p style='color: {c_text_secondary}; font-size: 0.85rem;'>Esporta la topologia in formato Mermaid compatibile con perizie giudiziarie, Markdown e Obsidian:</p>", unsafe_allow_html=True)

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
                use_container_width=True,
            )

        with st.expander("Visualizza Codice Sorgente Mermaid", expanded=False):
            st.code(codice_mermaid, language="mermaid")

# ------------------------------------------------------------------------------
# TAB 4: REPORT ATTI & DEDUZIONI INCREMENTALI
# ------------------------------------------------------------------------------
with tab_report_atti:
    st.markdown(f"<h3 style='margin: 0 0 10px 0; font-size: 1.15rem; color:{c_text_primary};'>📑 Deduzioni e Punti Salienti per Singolo Atto</h3>", unsafe_allow_html=True)
    if not st.session_state.storico:
        st.info("Nessun atto analizzato finora. Carica uno o più documenti nella dropzone in alto.")
    else:
        for idx, item in enumerate(st.session_state.storico):
            with st.expander(f"📄 Atto: {item['file']} (Acquisito alle {item.get('timestamp', 'N/D')} - {item.get('caratteri', 0):,} caratteri)", expanded=(idx == 0)):
                st.markdown(item["analisi"])

# ------------------------------------------------------------------------------
# TAB 5: PATTERN & SCHEMI TOPOLOGICI AML
# ------------------------------------------------------------------------------
with tab_schemi:
    schemi = st.session_state.gestore_grafo.rileva_schemi_investigativi_topologici()
    if not schemi or (not schemi.get("flussi_circolari") and not schemi.get("hub_dominus") and not schemi.get("scatole_cinesi")):
        st.info("Nessuno schema o anomalia individuata finora. Carica e analizza il fascicolo.")
    else:
        col_p1, col_p2, col_p3 = st.columns(3)
        with col_p1:
            st.markdown(f"<h4 style='color:{c_text_primary};'>🚨 Flussi Circolari (Ring)</h4>", unsafe_allow_html=True)
            flussi = schemi.get("flussi_circolari", [])
            if not flussi:
                st.markdown(f"<p style='color: {c_text_tertiary}; font-size: 0.85rem;'>Nessun circuito chiuso rilevato.</p>", unsafe_allow_html=True)
            else:
                for f in flussi:
                    st.markdown(f"""
                    <div class="apple-card" style="border-left: 3px solid #FF453A; padding: 10px 14px;">
                        <span style="font-weight: 700; color: #FF453A; font-size: 0.85rem;">Circuito Chiuso:</span><br/>
                        <span style="font-size: 0.82rem; color: {c_text_primary};">{' ➔ '.join(f)} ➔ {f[0]}</span>
                    </div>
                    """, unsafe_allow_html=True)

        with col_p2:
            st.markdown(f"<h4 style='color:{c_text_primary};'>🌟 Hub / Prestanome (Star)</h4>", unsafe_allow_html=True)
            hubs = schemi.get("hub_dominus", [])
            if not hubs:
                st.markdown(f"<p style='color: {c_text_tertiary}; font-size: 0.85rem;'>Nessun nodo hub anomalo.</p>", unsafe_allow_html=True)
            else:
                for h in hubs:
                    st.markdown(f"""
                    <div class="apple-card" style="border-left: 3px solid #FF9F0A; padding: 10px 14px;">
                        <span style="font-weight: 700; color: #FF9F0A; font-size: 0.88rem;">{h['nodo']}</span><br/>
                        <span style="font-size: 0.80rem; color: {c_text_secondary};">Grado: {h['connessioni']} | Atti: {h['atti_coinvolti']} | {h['tipo']}</span>
                    </div>
                    """, unsafe_allow_html=True)

        with col_p3:
            st.markdown(f"<h4 style='color:{c_text_primary};'>🏢 Catene di Controllo (Chain)</h4>", unsafe_allow_html=True)
            catene_raw = schemi.get("scatole_cinesi", [])
            catene = []
            viste_c = set()
            for c in catene_raw:
                tup_c = tuple(c)
                if tup_c not in viste_c:
                    viste_c.add(tup_c)
                    catene.append(c)

            if not catene:
                st.markdown(f"<p style='color: {c_text_tertiary}; font-size: 0.85rem;'>Nessuna catena societaria multilivello.</p>", unsafe_allow_html=True)
            else:
                for c in catene[:8]:
                    st.markdown(f"""
                    <div class="apple-card" style="border-left: 3px solid #BF5AF2; padding: 10px 14px;">
                        <span style="font-weight: 700; color: #BF5AF2; font-size: 0.85rem;">Catena di Controllo:</span><br/>
                        <span style="font-size: 0.82rem; color: {c_text_primary};">{' ➔ '.join(c)}</span>
                    </div>
                    """, unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# TAB 6: MASTER TIMELINE CRONOLOGICA DEGLI EVENTI
# ------------------------------------------------------------------------------
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
                    <span style="font-weight: 700; color: {c_blue}; font-size: 0.95rem;">📅 {ev.get('data', 'Data non specificata')}</span>
                    <span class="apple-pill pill-blue">{ev.get('fonte', 'Atto')}</span>
                </div>
                <div style="font-size: 0.88rem; color: {c_text_primary}; margin-top: 6px;">
                    <strong>{ev.get('soggetto_da', '')}</strong> ➔ <i>{ev.get('tipo', 'OPERAZIONE')}</i> ➔ <strong>{ev.get('soggetto_a', '')}</strong>
                </div>
                <div style="font-size: 0.82rem; color: {c_text_secondary}; margin-top: 4px;">
                    {ev.get('dettagli', '')}
                </div>
            </div>
            """, unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# TAB 7: ANAGRAFICHE, CONVERGENZE & SQL DUCKDB
# ------------------------------------------------------------------------------
with tab_convergenze:
    snodi = st.session_state.gestore_grafo.trova_convergenze_e_snodi()
    if not snodi:
        st.info("Nessun soggetto censito al momento.")
    else:
        st.markdown(f"<h4 style='color:{c_text_primary};'>🌟 Snodi Chiave e Soggetti Ricorrenti ({len(snodi)} soggetti)</h4>", unsafe_allow_html=True)
        col_s1, col_s2 = st.columns(2)
        for idx, s in enumerate(snodi[:10]):
            target_c = col_s1 if idx % 2 == 0 else col_s2
            tipo = s.get("tipo", "ALTRO")
            pill_c = "pill-blue" if tipo == "PERSONA" else ("pill-orange" if tipo == "SOCIETA" else "pill-green")
            with target_c:
                st.markdown(f"""
                <div class="apple-card" style="border: 1px solid {c_blue_bg}; padding: 14px 18px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 700; color: {c_blue}; font-size: 1.05rem;">{s['id']}</span>
                        <span class="apple-pill {pill_c}">{tipo}</span>
                    </div>
                    <div style="margin-top: 6px; font-size: 0.85rem; color: {c_blue};">
                        <strong>{s.get('ruolo_topologico', '')}</strong>
                    </div>
                    <div style="margin-top: 6px; font-size: 0.85rem; color: {c_text_primary};">
                        <strong>Cod. Fiscale / P.IVA:</strong> {s['cf_piva'] or 'Non indicato'}
                    </div>
                    <div style="margin-top: 4px; font-size: 0.82rem; color: {c_text_secondary};">
                        <strong>Presente in {s['num_atti']} atti:</strong> {', '.join(s['atti'])}
                    </div>
                    <div style="margin-top: 6px; font-size: 0.80rem; color: {c_text_tertiary};">
                        <strong>Legami:</strong> {s['in_entrata']} flussi in entrata | {s['in_uscita']} in uscita
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown(f"<hr style='margin: 16px 0; border: none; border-top: 1px solid {c_border};'/>", unsafe_allow_html=True)
        st.markdown(f"<h4 style='color:{c_text_primary};'>📋 Registro Anagrafico Unificato ({len(st.session_state.gestore_grafo.grafo.nodes)} Soggetti Totali)</h4>", unsafe_allow_html=True)
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
                <div class="apple-card" style="padding: 12px 16px; margin-bottom: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 700; color: {c_text_primary}; font-size: 0.95rem;">{nodo_id}</span>
                        <span class="apple-pill {pill_class}">{tipo}</span>
                    </div>
                    <div style="font-size: 0.8rem; color: {c_text_secondary}; margin-top: 6px;">
                        <strong>Fiscale:</strong> {cf_piva or 'Non censito'} &nbsp;|&nbsp; <strong>Atti:</strong> {', '.join(sorted(list(fonti)))}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown(f"<hr style='margin: 16px 0; border: none; border-top: 1px solid {c_border};'/>", unsafe_allow_html=True)
        st.markdown(f"<h4 style='color:{c_text_primary};'>🌐 Analytics FollowTheMoney OCCRP & DuckDB</h4>", unsafe_allow_html=True)

        ftm_stats = st.session_state.gestore_grafo.statistiche_ftm()
        schemi_ftm = ftm_stats.get("per_schema", {})

        col_ftm = st.columns(max(1, len(schemi_ftm)))
        for idx, (schema_name, conteggio) in enumerate(schemi_ftm.items()):
            with col_ftm[idx]:
                st.markdown(f"""
                <div class="apple-card" style="text-align: center; padding: 10px;">
                    <div style="font-size: 1.2rem; font-weight: 700; color: {c_blue};">{conteggio}</div>
                    <div style="font-size: 0.76rem; color: {c_text_secondary}; margin-top: 2px;">{schema_name}</div>
                </div>
                """, unsafe_allow_html=True)

        with st.expander("🦆 Console SQL Forense (DuckDB In-Memory)", expanded=False):
            st.markdown(f"<p style='color: {c_text_secondary}; font-size: 0.82rem;'>Interroga istantaneamente le tabelle <code>entita</code> e <code>relazioni</code> con query SQL standard:</p>", unsafe_allow_html=True)
            query_default = "SELECT nome, tipo, cf_piva, num_fonti FROM entita ORDER BY num_fonti DESC, nome ASC LIMIT 20"
            sql_input = st.text_area("Query SQL:", value=query_default, height=75)
            if st.button("⚡ Esegui Query SQL"):
                res_sql = st.session_state.gestore_grafo.esegui_query_sql(sql_input)
                if res_sql:
                    st.dataframe(pd.DataFrame(res_sql), use_container_width=True)
                else:
                    st.info("Nessun record restituito dalla query.")

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
    get_available_models,
    estrai_entita_e_relazioni_avanzato,
    genera_deduzioni,
    genera_dossier_forense_globale,
    ULTRA_MODEL,
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
    c_bg = "#F5F6F8"
    c_sidebar = "#ECEEF2"
    c_card = "#FFFFFF"
    c_card_inner = "#F8F9FA"
    c_border = "rgba(0, 0, 0, 0.09)"
    c_border_hover = "rgba(0, 113, 227, 0.4)"
    c_text_primary = "#111827"
    c_text_secondary = "#374151"
    c_text_tertiary = "#6B7280"
    c_blue = "#0071E3"
    c_blue_hover = "#005BB5"
    c_blue_bg = "rgba(0, 113, 227, 0.08)"
    c_tab_bg = "rgba(0, 0, 0, 0.05)"
    c_tab_text = "#374151"
    c_tab_active_bg = "#0071E3"
    c_tab_active_text = "#FFFFFF"
    c_shadow = "0 2px 10px rgba(0, 0, 0, 0.04)"
    c_btn_bg = "#FFFFFF"
    c_btn_text = "#111827"
    c_btn_border = "rgba(0, 0, 0, 0.14)"
    c_btn_hover_bg = "#F3F4F6"
    c_input_bg = "#FFFFFF"
    c_dropzone_bg = "#FFFFFF"
    c_code_bg = "#F3F4F6"
    c_terminal_bg = "#1E2024"
    c_terminal_text = "#38BDF8"
    # Pills
    c_pill_green_txt = "#15803D"
    c_pill_green_bg = "rgba(34, 197, 94, 0.14)"
    c_pill_green_bdr = "rgba(34, 197, 94, 0.3)"
    c_pill_orange_txt = "#C2410C"
    c_pill_orange_bg = "rgba(249, 115, 22, 0.14)"
    c_pill_orange_bdr = "rgba(249, 115, 22, 0.3)"
    c_pill_red_txt = "#DC2626"
    c_pill_red_bg = "rgba(239, 68, 68, 0.14)"
    c_pill_red_bdr = "rgba(239, 68, 68, 0.3)"
    c_pill_purple_txt = "#7E22CE"
    c_pill_purple_bg = "rgba(168, 85, 247, 0.14)"
    c_pill_purple_bdr = "rgba(168, 85, 247, 0.3)"
else:
    # DARK MODE: Apple Obsidian / High Contrast Dark
    c_bg = "#0D1117"
    c_sidebar = "#11151C"
    c_card = "#161B22"
    c_card_inner = "#21262D"
    c_border = "rgba(255, 255, 255, 0.14)"
    c_border_hover = "rgba(10, 132, 255, 0.6)"
    c_text_primary = "#FFFFFF"
    c_text_secondary = "#D1D5DB"
    c_text_tertiary = "#9CA3AF"
    c_blue = "#0A84FF"
    c_blue_hover = "#388BFD"
    c_blue_bg = "rgba(10, 132, 255, 0.20)"
    c_tab_bg = "#161B22"
    c_tab_text = "#D1D5DB"
    c_tab_active_bg = "#0A84FF"
    c_tab_active_text = "#FFFFFF"
    c_shadow = "0 4px 20px rgba(0, 0, 0, 0.50)"
    c_btn_bg = "#21262D"
    c_btn_text = "#FFFFFF"
    c_btn_border = "rgba(255, 255, 255, 0.18)"
    c_btn_hover_bg = "#30363D"
    c_input_bg = "#161B22"
    c_dropzone_bg = "#161B22"
    c_code_bg = "#161B22"
    c_terminal_bg = "#07090D"
    c_terminal_text = "#38BDF8"
    # Pills
    c_pill_green_txt = "#30D158"
    c_pill_green_bg = "rgba(48, 209, 88, 0.20)"
    c_pill_green_bdr = "rgba(48, 209, 88, 0.4)"
    c_pill_orange_txt = "#FF9F0A"
    c_pill_orange_bg = "rgba(255, 159, 10, 0.20)"
    c_pill_orange_bdr = "rgba(255, 159, 10, 0.4)"
    c_pill_red_txt = "#FF453A"
    c_pill_red_bg = "rgba(255, 69, 58, 0.20)"
    c_pill_red_bdr = "rgba(255, 69, 58, 0.4)"
    c_pill_purple_txt = "#BF5AF2"
    c_pill_purple_bg = "rgba(191, 90, 242, 0.20)"
    c_pill_purple_bdr = "rgba(191, 90, 242, 0.4)"

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
    html, body, [class*="css"], [data-testid="stAppViewContainer"], .main {{
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
        font-size: 0.74rem !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em !important;
        color: {c_text_tertiary} !important;
        font-weight: 700 !important;
        margin-top: 0.8rem !important;
        margin-bottom: 0.35rem !important;
    }}

    /* VERO CARD CONTAINER SIDEBAR STREAMLIT */
    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {{
        background-color: {c_card} !important;
        border: 1px solid {c_border} !important;
        border-radius: 12px !important;
        box-shadow: {c_shadow} !important;
        padding: 4px 6px !important;
        margin-bottom: 12px !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    }}
    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:hover {{
        border-color: {c_border_hover} !important;
    }}

    /* RADIO BUTTONS ED ETICHETTE CONTROLLI */
    div[data-testid="stRadio"] label p,
    div[data-testid="stRadio"] span {{
        color: {c_text_primary} !important;
        font-size: 0.84rem !important;
        font-weight: 500 !important;
    }}
    div[data-testid="stRadio"] [data-testid="stWidgetLabel"] p {{
        color: {c_text_secondary} !important;
        font-weight: 600 !important;
        font-size: 0.82rem !important;
        margin-bottom: 4px !important;
    }}
    div[data-testid="stRadio"] label > div:first-child {{
        background-color: {c_card_inner} !important;
        border-color: {c_border} !important;
    }}

    /* EXPANDERS IN SIDEBAR E MAIN */
    [data-testid="stExpander"] {{
        background-color: {c_card} !important;
        border: 1px solid {c_border} !important;
        border-radius: 10px !important;
        box-shadow: {c_shadow} !important;
        margin-bottom: 8px !important;
        overflow: hidden !important;
    }}
    [data-testid="stExpander"] details summary {{
        background-color: transparent !important;
        padding: 8px 12px !important;
        border-radius: 10px !important;
    }}
    [data-testid="stExpander"] details summary p {{
        color: {c_text_primary} !important;
        font-weight: 600 !important;
        font-size: 0.84rem !important;
    }}
    [data-testid="stExpander"] details summary svg {{
        color: {c_text_secondary} !important;
    }}
    [data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
        border-top: 1px solid {c_border} !important;
        background-color: {c_card_inner} !important;
        padding: 10px 12px !important;
    }}

    .apple-card {{
        background-color: {c_card};
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
        background-color: {c_blue_bg};
        color: {c_blue};
        border: 1px solid {c_blue_bg};
    }}
    .pill-green {{
        background-color: {c_pill_green_bg};
        color: {c_pill_green_txt};
        border: 1px solid {c_pill_green_bdr};
    }}
    .pill-orange {{
        background-color: {c_pill_orange_bg};
        color: {c_pill_orange_txt};
        border: 1px solid {c_pill_orange_bdr};
    }}
    .pill-red {{
        background-color: {c_pill_red_bg};
        color: {c_pill_red_txt};
        border: 1px solid {c_pill_red_bdr};
    }}
    .pill-purple {{
        background-color: {c_pill_purple_bg};
        color: {c_pill_purple_txt};
        border: 1px solid {c_pill_purple_bdr};
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
        background-color: {c_card_inner};
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

    /* 5. TABS DI NAVIGAZIONE AD ALTA LEGGIBILITÀ (NESSUNA LINEA ROSSA) */
    [data-baseweb="tab-highlight"],
    [data-baseweb="tab-border"] {{
        display: none !important;
    }}
    .stTabs [data-baseweb="tab-list"] {{
        display: flex !important;
        flex-wrap: wrap !important;
        gap: 6px !important;
        background-color: {c_tab_bg} !important;
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
        border: 1px solid transparent !important;
        background-color: transparent !important;
        white-space: nowrap !important;
        transition: all 0.15s ease-in-out !important;
    }}
    .stTabs [data-baseweb="tab"] p,
    .stTabs [data-baseweb="tab"] span,
    .stTabs [data-baseweb="tab"] div {{
        color: {c_tab_text} !important;
        font-weight: 600 !important;
    }}
    .stTabs [data-baseweb="tab"]:hover {{
        background-color: rgba(128, 128, 128, 0.15) !important;
    }}
    .stTabs [data-baseweb="tab"]:hover p,
    .stTabs [data-baseweb="tab"]:hover span {{
        color: {c_text_primary} !important;
    }}
    .stTabs [aria-selected="true"] {{
        background-color: {c_tab_active_bg} !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25) !important;
        border: 1px solid {c_border} !important;
    }}
    .stTabs [aria-selected="true"] p,
    .stTabs [aria-selected="true"] span,
    .stTabs [aria-selected="true"] div {{
        color: {c_tab_active_text} !important;
        font-weight: 700 !important;
    }}

    /* 6. BOTTONI APPLE STYLE (OVERRIDE TOTALE) */
    button[data-testid="baseButton-secondary"],
    button[data-testid="baseButton-primary"],
    [data-testid="stBaseButton-secondary"],
    [data-testid="stBaseButton-primary"],
    [data-testid="stButton"] > button,
    [data-testid="stDownloadButton"] > button,
    .stButton > button,
    .stDownloadButton > button {{
        background-color: {c_btn_bg} !important;
        color: {c_btn_text} !important;
        border: 1px solid {c_btn_border} !important;
        border-radius: 10px !important;
        padding: 7px 16px !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        transition: all 0.18s ease-in-out !important;
        box-shadow: {c_shadow} !important;
    }}
    button[data-testid="baseButton-secondary"]:hover,
    button[data-testid="baseButton-primary"]:hover,
    [data-testid="stBaseButton-secondary"]:hover,
    [data-testid="stBaseButton-primary"]:hover,
    [data-testid="stButton"] > button:hover,
    [data-testid="stDownloadButton"] > button:hover,
    .stButton > button:hover,
    .stDownloadButton > button:hover {{
        background-color: {c_btn_hover_bg} !important;
        border-color: {c_blue} !important;
        color: {c_blue} !important;
        transform: translateY(-1px);
    }}
    /* Pulsante primario (es. Avvia / Compila) */
    [data-testid="stButton"] > button[kind="primary"],
    button[kind="primary"] {{
        background-color: {c_blue} !important;
        color: #FFFFFF !important;
        border: none !important;
        font-weight: 600 !important;
    }}

    /* 7. DROPZONE UPLOAD STILIZZATA PULITA & CHIP FILE */
    [data-testid="stFileUploader"] {{
        background-color: transparent !important;
        border: none !important;
        padding: 0 !important;
    }}
    [data-testid="stFileUploaderDropzone"],
    [data-testid="stFileUploader"] section,
    section[data-testid="stFileUploaderDropzone"] {{
        background-color: {c_dropzone_bg} !important;
        border: 1.5px dashed {c_blue} !important;
        border-radius: 12px !important;
        padding: 16px 20px !important;
        transition: all 0.2s ease !important;
        box-shadow: {c_shadow} !important;
    }}
    [data-testid="stFileUploaderDropzone"]:hover,
    [data-testid="stFileUploader"] section:hover {{
        border-color: {c_blue_hover} !important;
        background-color: {c_card_inner} !important;
    }}
    [data-testid="stFileUploaderDropzone"] div,
    [data-testid="stFileUploaderDropzone"] span,
    [data-testid="stFileUploaderDropzone"] p,
    [data-testid="stFileUploaderDropzone"] small,
    [data-testid="stFileUploader"] section * {{
        color: {c_text_secondary} !important;
    }}
    [data-testid="stFileUploaderDropzone"] button,
    [data-testid="stFileUploader"] section button {{
        background-color: {c_blue_bg} !important;
        color: {c_blue} !important;
        border: 1px solid {c_border} !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
    }}

    /* CHIP FILE CARICATI DENTRO LA DROPZONE (MAI BIANCHI IN DARK MODE) */
    [data-testid="stFileChip"],
    [data-testid="stFileChips"] > div {{
        background-color: {c_card_inner} !important;
        border: 1px solid {c_border} !important;
        color: {c_text_primary} !important;
        border-radius: 8px !important;
    }}
    [data-testid="stFileChip"] span,
    [data-testid="stFileChip"] div,
    [data-testid="stFileChip"] p,
    [data-testid="stFileChip"] small {{
        color: {c_text_primary} !important;
    }}
    [data-testid="stFileChipDeleteBtn"] svg,
    [data-testid="stFileChipDeleteBtn"] button {{
        color: {c_text_secondary} !important;
    }}

    /* 8. BARRA CHAT INPUT & MESSAGGI COERENTI */
    [data-testid="stChatInput"],
    [data-testid="stChatInput"] > div,
    div[data-testid="stChatInputContainer"] {{
        background-color: {c_input_bg} !important;
        border: 1px solid {c_border} !important;
        border-radius: 14px !important;
        box-shadow: {c_shadow} !important;
        padding: 3px !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    }}
    [data-testid="stChatInput"]:focus-within,
    [data-testid="stChatInput"] > div:focus-within {{
        border-color: {c_blue} !important;
        box-shadow: 0 0 0 2px {c_blue_bg} !important;
    }}
    [data-testid="stChatInput"] textarea,
    [data-testid="stChatInputTextArea"] {{
        background: transparent !important;
        color: {c_text_primary} !important;
        font-size: 0.90rem !important;
    }}
    [data-testid="stChatInput"] textarea::placeholder,
    [data-testid="stChatInputTextArea"]::placeholder {{
        color: {c_text_tertiary} !important;
    }}
    [data-testid="stChatInputSubmitButton"],
    [data-testid="stChatInput"] button {{
        background-color: {c_blue} !important;
        color: #FFFFFF !important;
        border-radius: 8px !important;
        border: none !important;
    }}
    [data-testid="stChatInput"] button:disabled {{
        background-color: {c_border} !important;
        color: {c_text_tertiary} !important;
    }}

    [data-testid="stChatMessage"] {{
        background-color: {c_card} !important;
        border: 1px solid {c_border} !important;
        border-radius: 12px !important;
        padding: 12px 16px !important;
        box-shadow: {c_shadow} !important;
        margin-bottom: 8px !important;
        color: {c_text_primary} !important;
    }}
    [data-testid="stChatMessage"] p {{
        color: {c_text_primary} !important;
    }}

    /* 9. CONTROLLI INPUT AGGIUNTIVI (TEXT AREA, SELECTBOX, TOGGLE, SPINNER) */
    [data-testid="stTextArea"] textarea {{
        background-color: {c_card_inner} !important;
        color: {c_text_primary} !important;
        border: 1px solid {c_border} !important;
        border-radius: 10px !important;
    }}
    [data-testid="stSelectbox"] div[data-baseweb="select"] > div {{
        background-color: {c_card} !important;
        border: 1px solid {c_border} !important;
        border-radius: 10px !important;
        color: {c_text_primary} !important;
    }}
    [data-testid="stSelectbox"] span {{
        color: {c_text_primary} !important;
    }}
    [data-testid="stToggle"] label p {{
        color: {c_text_primary} !important;
        font-weight: 600 !important;
    }}
    div[data-testid="stSpinner"],
    div[data-testid="stSpinner"] > div,
    div[data-testid="stSpinner"] p,
    div[data-testid="stSpinner"] span {{
        color: {c_text_primary} !important;
        font-weight: 600 !important;
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
        background-color: {c_card};
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
    with st.container(border=True):
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

        disp_modelli = get_available_models()
        ha_14b = disp_modelli["has_14b"]

        opzioni_modello = []
        if ha_14b:
            opzioni_modello.append("🚀 Ultra-Potenza (Qwen 2.5 14B)")
        opzioni_modello.append("⚖️ Massima Precisione (Qwen 2.5 7B)")
        opzioni_modello.append("⚡ Scansione Rapida (Llama 3.2 3B)")

        profilo = st.radio(
            "Modello di Ragionamento:",
            options=opzioni_modello,
            index=0,
            label_visibility="visible",
        )

        if "14B" in profilo:
            modello_selezionato = disp_modelli.get("name_14b", ULTRA_MODEL)
        elif "7B" in profilo:
            modello_selezionato = disp_modelli.get("name_7b", BEST_MODEL)
        else:
            modello_selezionato = disp_modelli.get("name_3b", FAST_MODEL)

        if not ha_14b:
            with st.expander("💡 Vuoi attivare Qwen 2.5 14B?", expanded=False):
                st.markdown(f"""
                <div style="font-size: 0.78rem; color: {c_text_secondary};">
                    Per installare il modello forense heavyweight (14B, ~8.9GB RAM):<br/>
                    <code style="display:block; margin: 4px 0; padding: 4px; background: rgba(128,128,128,0.2); border-radius: 4px;">ollama pull qwen2.5:14b</code>
                    <em>Una volta completato, apparirà automaticamente tra i modelli disponibili.</em>
                </div>
                """, unsafe_allow_html=True)

        st.markdown(f"""
        <div style="margin-top: 8px;">
            <span class="apple-pill pill-blue"><span class="material-symbols-outlined" style="font-size:14px;">bolt</span> Apple Silicon Metal M1 Pro (8P+16GPU)</span>
        </div>
        """, unsafe_allow_html=True)

    # CARD 2: METRICHE FASCICOLO ACCUMULATO
    st.markdown('<div class="sidebar-section-title"><span class="material-symbols-outlined" style="font-size:16px;">analytics</span> Metriche Fascicolo</div>', unsafe_allow_html=True)
    with st.container(border=True):
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

    # CARD 3: GESTIONE INDAGINE & BACKUP
    st.markdown('<div class="sidebar-section-title"><span class="material-symbols-outlined" style="font-size:16px;">folder_managed</span> Gestione Indagine</div>', unsafe_allow_html=True)
    with st.container(border=True):
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

    # CARD 4: LOG ATTIVO
    st.markdown('<div class="sidebar-section-title"><span class="material-symbols-outlined" style="font-size:16px;">terminal</span> Diagnostica & Log</div>', unsafe_allow_html=True)
    with st.container(border=True):
        with st.expander("Visualizza Log Recente", expanded=False):
            testo_log = leggi_ultimi_log(max_righe=60)
            st.markdown(f'<div class="log-box">{testo_log}</div>', unsafe_allow_html=True)
            if st.button("Aggiorna Log", use_container_width=True):
                st.rerun()

    # CARD 5: CONTROLLO SERVER
    st.markdown('<div class="sidebar-section-title"><span class="material-symbols-outlined" style="font-size:16px;">power_settings_new</span> Sessione Server</div>', unsafe_allow_html=True)
    with st.container(border=True):
        if st.button("Arresta Server Locale", help="Termina il server Streamlit e rilascia la porta", use_container_width=True):
            import os, signal
            st.warning("Arresto del server in corso...")
            time.sleep(1)
            os.kill(os.getpid(), signal.SIGTERM)

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

                # Avviso non bloccante per atti estesi (es. Visure CCIAA multi-blocco)
                if diag["num_blocchi"] > 1 and ok:
                    st.info(f"ℹ️ **{f.name}**: Atto esteso di {diag['num_caratteri']:,} caratteri ({diag['num_blocchi']} blocchi) — analisi sequenziale senza perdita di dettaglio.")

                # Ingestione & Entity Resolution con Progresso Incrementale e Token Live
                if ok:
                    progress_box = st.container()
                    with progress_box:
                        prog_bar = st.progress(0.01)
                        status_text = st.empty()

                    t_start_acq = time.time()

                    def update_progress(perc: float, msg: str, tokens: int = 0, elapsed: float = 0.0):
                        p_val = round(min(max(perc, 0.01), 1.0), 2)
                        prog_bar.progress(p_val)

                        tot_sec = int(time.time() - t_start_acq)
                        minuti = tot_sec // 60
                        secondi = tot_sec % 60
                        timer_str = f"{minuti:02d}:{secondi:02d}s"

                        info_extra = [f"⏱️ Tempo: {timer_str}"]
                        if tokens > 0:
                            info_extra.append(f"⚡ Token: {tokens:,}")
                        info_extra.append("🟢 Apple Silicon Metal M1 Pro")
                        extra_str = " &nbsp;|&nbsp; ".join(info_extra)

                        status_text.markdown(f"""
                        <div style="border: 1px solid rgba(10, 132, 255, 0.4); background: {c_card}; border-radius: 12px; padding: 12px 16px; margin: 10px 0; box-shadow: {c_shadow};">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="font-weight: 600; color: {c_blue}; font-size: 0.95rem;">{msg}</span>
                                <span class="apple-pill pill-blue" style="font-size: 0.85rem; font-weight: 700;">{int(p_val * 100)}%</span>
                            </div>
                            <div style="margin-top: 6px; font-size: 0.80rem; color: {c_text_secondary}; display: flex; justify-content: space-between;">
                                <span>{extra_str}</span>
                                <span style="color: #30D158; font-weight: 600;">● In elaborazione</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                    update_progress(0.05, f"📄 [Fase 1/3] Parsing e analisi diagnostica di '{f.name}'...")
                    dati_json = estrai_entita_e_relazioni_avanzato(
                        blocchi_testo=diag["blocchi"],
                        nome_file=f.name,
                        model=modello_selezionato,
                        callback_progresso=update_progress,
                        base_perc=0.10,
                        peso_perc=0.60,
                    )
                    st.session_state.gestore_grafo.aggiungi_dati(dati_json, f.name)

                    update_progress(0.72, f"🕸️ [Fase 2/3] Fusione e aggiornamento della rete investigativa...")
                    riassunto_rete = st.session_state.gestore_grafo.ottieni_riassunto()

                    update_progress(0.75, f"🧠 [Fase 3/3] Deduzioni cross-documentali con {modello_selezionato}...")
                    deduzione = genera_deduzioni(
                        riassunto_grafo=riassunto_rete,
                        testo_nuovo_documento=diag["testo"],
                        nome_documento=f.name,
                        model=modello_selezionato,
                        callback_progresso=update_progress,
                        base_perc=0.75,
                        peso_perc=0.24,
                    )

                    t_elapsed = round(time.time() - t_start_acq, 1)
                    update_progress(1.0, f"✅ Acquisito e integrato nel grafo: {f.name} ({t_elapsed}s)")

                    st.session_state.storico.insert(0, {
                        "file": f.name,
                        "analisi": deduzione,
                        "caratteri": diag["num_caratteri"],
                        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                    })
                    st.session_state.file_letti.add(f.name)
                    st.session_state.documenti_acquisiti[f.name] = diag
                    st.session_state.timestamp_analisi = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
                    time.sleep(0.5)
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
        progress_dossier = st.container()
        with progress_dossier:
            prog_bar_d = st.progress(0.01)
            status_text_d = st.empty()

        t_start_d = time.time()
        def update_progress_d(perc: float, msg: str, tokens: int = 0, elapsed: float = 0.0):
            p_val = round(min(max(perc, 0.01), 1.0), 2)
            prog_bar_d.progress(p_val)
            tot_sec = int(time.time() - t_start_d)
            minuti = tot_sec // 60
            secondi = tot_sec % 60
            timer_str = f"{minuti:02d}:{secondi:02d}s"

            info_extra = [f"⏱️ Tempo: {timer_str}"]
            if tokens > 0:
                info_extra.append(f"⚡ Token: {tokens:,}")
            info_extra.append("🟢 Apple Silicon Metal M1 Pro")
            extra_str = " &nbsp;|&nbsp; ".join(info_extra)

            status_text_d.markdown(f"""
            <div style="border: 1px solid rgba(10, 132, 255, 0.4); background: {c_card}; border-radius: 12px; padding: 12px 16px; margin: 10px 0; box-shadow: {c_shadow};">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 600; color: {c_blue}; font-size: 0.95rem;">{msg}</span>
                    <span class="apple-pill pill-blue" style="font-size: 0.85rem; font-weight: 700;">{int(p_val * 100)}%</span>
                </div>
                <div style="margin-top: 6px; font-size: 0.80rem; color: {c_text_secondary}; display: flex; justify-content: space-between;">
                    <span>{extra_str}</span>
                    <span style="color: #30D158; font-weight: 600;">● In elaborazione</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        testi_per_dossier = {k: v["testo"] for k, v in st.session_state.documenti_acquisiti.items()}
        dossier_unificato = genera_dossier_forense_globale(
            gestore_grafo=st.session_state.gestore_grafo,
            estratti_documenti=testi_per_dossier,
            model=modello_selezionato,
            ha_grafo=True,
            callback_progresso=update_progress_d,
        )
        st.session_state.dossier_globale = dossier_unificato
        st.session_state.timestamp_analisi = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        time.sleep(0.5)
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

        sogg_ponte = st.session_state.gestore_grafo.trova_soggetti_trasversali()
        n_ponte = len(sogg_ponte)

        st.markdown(f"""
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px;">
            <div class="apple-card" style="padding: 12px 14px;">
                <div style="font-size: 0.70rem; color: {c_text_tertiary}; text-transform: uppercase; font-weight: 700;">Volume Tracciato</div>
                <div style="font-size: 1.25rem; font-weight: 700; color: #30D158; margin-top: 4px;">€ {tot_val:,.2f}</div>
            </div>
            <div class="apple-card" style="padding: 12px 14px;">
                <div style="font-size: 0.70rem; color: {c_text_tertiary}; text-transform: uppercase; font-weight: 700;">Operazioni Rilevate</div>
                <div style="font-size: 1.25rem; font-weight: 700; color: {c_blue}; margin-top: 4px;">{n_trans} movimenti</div>
            </div>
            <div class="apple-card" style="padding: 12px 14px;">
                <div style="font-size: 0.70rem; color: {c_text_tertiary}; text-transform: uppercase; font-weight: 700;">Soggetti Ponte Multi-Atto</div>
                <div style="font-size: 1.25rem; font-weight: 700; color: #FF9F0A; margin-top: 4px;">{n_ponte} soggetti</div>
            </div>
            <div class="apple-card" style="padding: 12px 14px;">
                <div style="font-size: 0.70rem; color: {c_text_tertiary}; text-transform: uppercase; font-weight: 700;">Entità Censite</div>
                <div style="font-size: 1.25rem; font-weight: 700; color: #BF5AF2; margin-top: 4px;">{len(st.session_state.gestore_grafo.grafo.nodes)} totali</div>
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

        html_path = st.session_state.gestore_grafo.genera_html_mappa(altezza=f"{alt_scelta}px", tema=st.session_state.tema)
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
# TAB 5: PATTERN AML & MOTORI INVESTIGATIVI CORE (NETWORKX + OCCRP FtM + DUCKDB)
# ------------------------------------------------------------------------------
with tab_schemi:
    st.markdown(f"""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
        <div>
            <h3 style="margin: 0; font-size: 1.15rem; color:{c_text_primary};">🎯 Motori Investigativi di Link Analysis & AML</h3>
            <p style="margin: 3px 0 0 0; color: {c_text_secondary}; font-size: 0.85rem;">
                Integrazione algoritmica di <strong>NetworkX Centrality</strong> (Dominus & Hub), <strong>OCCRP FollowTheMoney</strong> (Titolare Effettivo UBO) e <strong>DuckDB OLAP</strong> (Riconciliazione Partite).
            </p>
        </div>
        <div>
            <span class="apple-pill pill-blue">OCCRP + NetworkX + DuckDB</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if len(st.session_state.gestore_grafo.grafo.nodes) == 0:
        st.info("Nessun dato investigativo da elaborare. Carica gli atti del fascicolo per avviare i motori forensi.")
    else:
        # SEZIONE 1: ANALISI TOPOLOGICA DOMINUS & CENTRALITÀ (NETWORKX)
        st.markdown(f"<h4 style='color:{c_text_primary}; margin-bottom: 8px;'>👑 1. Analisi Topologica Dominus & Centralità (NetworkX Betweenness)</h4>", unsafe_allow_html=True)
        st.markdown(f"<p style='color: {c_text_secondary}; font-size: 0.82rem;'>L'algoritmo di Betweenness Centrality identifica matematicamente i soggetti che controllano il flusso relazionale o fungono da ponte tra società apparentemente distinte:</p>", unsafe_allow_html=True)
        
        centralita_dati = st.session_state.gestore_grafo.calcola_metriche_centralita_forense()
        if centralita_dati:
            df_cent = []
            for c in centralita_dati[:12]:
                df_cent.append({
                    "Soggetto": c["nodo"],
                    "Profilo Investigativo": c["profilo_forense"],
                    "Betweenness": f"{c['betweenness']:.4f}",
                    "Flussi In": c["in_degree"],
                    "Flussi Out": c["out_degree"],
                    "Atti Coinvolti": c["num_atti"],
                    "CF / P.IVA": c["cf_piva"],
                })
            st.dataframe(pd.DataFrame(df_cent), use_container_width=True, hide_index=True)

        st.markdown(f"<hr style='margin: 16px 0; border: none; border-top: 1px solid {c_border};'/>", unsafe_allow_html=True)

        # SEZIONE 2: TITOLARE EFFETTIVO (UBO) E CATENE DI CONTROLLO (OCCRP FOLLOWTHEMONEY)
        st.markdown(f"<h4 style='color:{c_text_primary}; margin-bottom: 8px;'>🏢 2. Titolari Effettivi (UBO) e Catene di Partecipazione (FollowTheMoney OCCRP)</h4>", unsafe_allow_html=True)
        st.markdown(f"<p style='color: {c_text_secondary}; font-size: 0.82rem;'>Disvelamento delle strutture societarie e delle holding: individua le persone fisiche al vertice del controllo sostanziale:</p>", unsafe_allow_html=True)

        try:
            ubos = st.session_state.gestore_grafo.ftm_dataset.risolvi_titolari_effettivi()
            ubos_rilevanti = [u for u in ubos if u["titolari_effettivi"] or u["amministratori"]]
            if not ubos_rilevanti:
                st.markdown(f"<p style='color: {c_text_tertiary}; font-size: 0.85rem;'>Nessuna compagine proprietaria multilivello rilevata.</p>", unsafe_allow_html=True)
            else:
                col_u1, col_u2 = st.columns(2)
                for idx, u in enumerate(ubos_rilevanti):
                    target_u = col_u1 if idx % 2 == 0 else col_u2
                    with target_u:
                        st.markdown(f"""
                        <div class="apple-card" style="border-left: 3px solid #30D158; padding: 12px 16px; margin-bottom: 10px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="font-weight: 700; color: #30D158; font-size: 0.95rem;">🏢 {u['azienda']}</span>
                                <span class="apple-pill pill-green">CF: {u['cf_piva']}</span>
                            </div>
                        """, unsafe_allow_html=True)

                        if u["titolari_effettivi"]:
                            st.markdown("<div style='margin-top: 6px; font-size: 0.82rem;'><strong>👑 Titolari Effettivi / Soci:</strong></div>", unsafe_allow_html=True)
                            for te in u["titolari_effettivi"]:
                                cat_str = " ➔ ".join(te["catena"])
                                st.markdown(f"<div style='font-size: 0.80rem; color: {c_text_primary}; margin-left: 8px;'>• <strong>{te['persona']}</strong> ({te['cf']}) — {te['ruolo']} {te['percentuale']}<br/><span style='color:{c_text_secondary}; font-size: 0.76rem;'>Catena: {cat_str}</span></div>", unsafe_allow_html=True)

                        if u["amministratori"]:
                            st.markdown("<div style='margin-top: 6px; font-size: 0.82rem;'><strong>👔 Organo Amministrativo:</strong></div>", unsafe_allow_html=True)
                            for am in u["amministratori"]:
                                st.markdown(f"<div style='font-size: 0.80rem; color: {c_text_secondary}; margin-left: 8px;'>• {am['nominativo']} ({am['cf']}) — {am['ruolo']}</div>", unsafe_allow_html=True)

                        st.markdown("</div>", unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Errore calcolo UBO FollowTheMoney: {e}")

        st.markdown(f"<hr style='margin: 16px 0; border: none; border-top: 1px solid {c_border};'/>", unsafe_allow_html=True)

        # SEZIONE 3: RICONCILIAZIONE FINANZIARIA OLAP (DUCKDB)
        st.markdown(f"<h4 style='color:{c_text_primary}; margin-bottom: 8px;'>🦆 3. Matrice di Riconciliazione Finanziaria e Sbilanci (DuckDB OLAP)</h4>", unsafe_allow_html=True)
        st.markdown(f"<p style='color: {c_text_secondary}; font-size: 0.82rem;'>Incrocio deterministico tra provviste erogate, bonifici incassati e saldi netti per ciascun soggetto:</p>", unsafe_allow_html=True)

        matrice_fin = st.session_state.gestore_grafo.calcola_matrice_riconciliazione_finanziaria()
        if matrice_fin:
            df_fin = []
            for mf in matrice_fin:
                if mf["entrate_euro"] > 0 or mf["uscite_euro"] > 0:
                    df_fin.append({
                        "Soggetto": mf["soggetto"],
                        "Tipo": mf["tipo"],
                        "Fondi Entrati (€)": f"€ {mf['entrate_euro']:,.2f}",
                        "Fondi Usciti (€)": f"€ {mf['uscite_euro']:,.2f}",
                        "Saldo Netto (€)": f"€ {mf['sbilancio_netto_euro']:,.2f}",
                        "N. Operazioni In": mf["n_operazioni_in"],
                        "N. Operazioni Out": mf["n_operazioni_out"],
                        "CF / P.IVA": mf["cf_piva"],
                    })
            if df_fin:
                st.dataframe(pd.DataFrame(df_fin), use_container_width=True, hide_index=True)
            else:
                st.markdown(f"<p style='color: {c_text_tertiary}; font-size: 0.85rem;'>Nessuna movimentazione con importo numerico certo registrata.</p>", unsafe_allow_html=True)

        st.markdown(f"<hr style='margin: 16px 0; border: none; border-top: 1px solid {c_border};'/>", unsafe_allow_html=True)

        # SEZIONE 4: SCHEMI TOPOLOGICI E INCONGRUENZE
        col_sch1, col_sch2 = st.columns(2)
        schemi = st.session_state.gestore_grafo.rileva_schemi_investigativi_topologici()

        with col_sch1:
            st.markdown(f"<h4 style='color:{c_text_primary}; margin-bottom: 8px;'>🚨 Flussi Circolari (Ring)</h4>", unsafe_allow_html=True)
            flussi = schemi.get("flussi_circolari", [])
            if not flussi:
                st.markdown(f"<p style='color: {c_text_tertiary}; font-size: 0.85rem;'>Nessun circuito chiuso di rientro fondi rilevato.</p>", unsafe_allow_html=True)
            else:
                for f in flussi:
                    st.markdown(f"""
                    <div class="apple-card" style="border-left: 3px solid #FF453A; padding: 10px 14px; margin-bottom: 8px;">
                        <span style="font-weight: 700; color: #FF453A; font-size: 0.85rem;">Circuito Chiuso Rilevato:</span><br/>
                        <span style="font-size: 0.82rem; color: {c_text_primary};">{' ➔ '.join(f)} ➔ <strong>{f[0]}</strong></span>
                    </div>
                    """, unsafe_allow_html=True)

        with col_sch2:
            st.markdown(f"<h4 style='color:{c_text_primary}; margin-bottom: 8px;'>⚠️ Contraddizioni e Incongruenze Inter-Atti</h4>", unsafe_allow_html=True)
            incongruenze = schemi.get("incongruenze", [])
            if not incongruenze:
                st.markdown(f"<p style='color: {c_text_tertiary}; font-size: 0.85rem;'>Nessuna contraddizione documentale evidente tra le cariche.</p>", unsafe_allow_html=True)
            else:
                for inc in incongruenze[:6]:
                    st.markdown(f"""
                    <div class="apple-card" style="border-left: 3px solid #FF9F0A; padding: 10px 14px; margin-bottom: 8px;">
                        <span style="font-weight: 700; color: #FF9F0A; font-size: 0.85rem;">[{inc['tipo']}] {inc['soggetto']}</span><br/>
                        <span style="font-size: 0.80rem; color: {c_text_secondary};">{inc['dettagli']}</span><br/>
                        <span style="font-size: 0.74rem; color: {c_text_tertiary};">Fonti: {', '.join(inc['fonti'])}</span>
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
# TAB 7: ANAGRAFICHE, MATRICE CONVERGENZA & SQL DUCKDB
# ------------------------------------------------------------------------------
with tab_convergenze:
    # 1. MATRICE DI CONVERGENZA MULTI-ATTO (SOGGETTI TRASVERSALI)
    sogg_trasv = st.session_state.gestore_grafo.trova_soggetti_trasversali()
    if sogg_trasv:
        st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <div>
                <h4 style="margin: 0; color:{c_text_primary};">🔗 Matrice di Convergenza Inter-Documentale ({len(sogg_trasv)} soggetti trasversali)</h4>
                <p style="margin: 3px 0 0 0; color: {c_text_secondary}; font-size: 0.82rem;">
                    Soggetti fisici e giuridici censiti contemporaneamente in <strong>2 o più atti distinti</strong> (il collante probatorio dell'inchiesta):
                </p>
            </div>
            <div>
                <span class="apple-pill pill-orange">Multi-Atto Overlap</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_t1, col_t2 = st.columns(2)
        for idx, t in enumerate(sogg_trasv):
            target_t = col_t1 if idx % 2 == 0 else col_t2
            tipo_t = t.get("tipo", "ALTRO")
            pill_t = "pill-blue" if tipo_t == "PERSONA" else ("pill-orange" if tipo_t == "SOCIETA" else "pill-green")
            with target_t:
                st.markdown(f"""
                <div class="apple-card" style="border-left: 3px solid #FF9F0A; padding: 12px 16px; margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 700; color: {c_text_primary}; font-size: 0.98rem;">{t['soggetto']}</span>
                        <span class="apple-pill {pill_t}">{tipo_t}</span>
                    </div>
                    <div style="margin-top: 5px; font-size: 0.82rem; color: {c_text_secondary};">
                        <strong>Cod. Fiscale / P.IVA:</strong> {t['cf_piva']} &nbsp;|&nbsp; <strong>Grado:</strong> {t['grado']} connessioni
                    </div>
                    <div style="margin-top: 6px; font-size: 0.80rem; color: #FF9F0A; font-weight: 600;">
                        Presente in {t['num_atti']} atti: {', '.join(t['atti'])}
                    </div>
                """, unsafe_allow_html=True)

                if t["ruoli_dettaglio"]:
                    st.markdown("<div style='margin-top: 6px; font-size: 0.78rem; color: {c_text_secondary};'>", unsafe_allow_html=True)
                    for f_name, r_list in t["ruoli_dettaglio"].items():
                        st.markdown(f"• <strong>{f_name}</strong>: {'; '.join(r_list[:2])}")
                    st.markdown("</div>", unsafe_allow_html=True)

                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown(f"<hr style='margin: 16px 0; border: none; border-top: 1px solid {c_border};'/>", unsafe_allow_html=True)

    # 2. REGISTRO ANAGRAFICO UNIFICATO
    st.markdown(f"<h4 style='color:{c_text_primary};'>📋 Registro Anagrafico Unificato ({len(st.session_state.gestore_grafo.grafo.nodes)} Soggetti Totali)</h4>", unsafe_allow_html=True)
    if len(st.session_state.gestore_grafo.grafo.nodes) == 0:
        st.info("Nessun soggetto censito al momento.")
    else:
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

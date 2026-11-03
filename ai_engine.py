import json
import os
import re
import time
import ollama
from logger import log

BEST_MODEL = "qwen2.5:7b"
FAST_MODEL = "llama3.2:3b"


def get_active_model() -> str:
    try:
        response = ollama.list()
        nomi = []
        if isinstance(response, dict) and "models" in response:
            nomi = [m.get("name") or m.get("model") for m in response["models"]]
        elif hasattr(response, "models"):
            nomi = [getattr(m, "model", None) or getattr(m, "name", None) for m in response.models]

        for n in nomi:
            if n and "qwen2.5" in n.lower():
                return n

        for n in nomi:
            if n and "llama3" in n.lower():
                return n

        if nomi and nomi[0]:
            return nomi[0]
    except Exception as e:
        log.warning(f"Impossibile elencare i modelli da Ollama ({e}). Fallback su {BEST_MODEL}")

    return BEST_MODEL


def estrai_entita_e_relazioni_singolo_blocco(
    testo_blocco: str,
    nome_file: str,
    blocco_num: int = 1,
    totale_blocchi: int = 1,
    model: str = None,
    callback_stream=None,
) -> dict:
    if not model:
        model = get_active_model()

    prompt = f"""
Sei un analista forense, investigatore tributario ed esperto antiriciclaggio (AML).
Analizza il seguente estratto del documento "{nome_file}" (Parte {blocco_num} di {totale_blocchi}).

Compito:
Estrai TUTTE le entità rilevanti:
- PERSONE FISICHE (soci, amministratori, firmatari, fiduciari, prestanome, beneficiari effettivi, delegati, professionisti).
- SOCIETÀ ED ENTI (aziende, fiduciarie, trust, holding, consorzi, enti esteri).
- CONTI BANCARI ED ASSET (IBAN, rapporti bancari, immobili o rami d'azienda ceduti).

Estrai TUTTE le relazioni giuridiche, commerciali ed economiche:
- Partecipazioni, cariche societarie (SOCIO, AMMINISTRATORE, LIQUIDATORE, SINDACO).
- Flussi finanziari e transazioni (BONIFICO, PAGAMENTO, PRESTITO, FATTURA, COMPENSO, PRELIEVO).
- Poteri e deleghe (PROCURATORE, DELEGA_FIRMA, GARANTE, BENEFICIARIO_EFFETTIVO, CEDENTE, CESSIONARIO).
- Operazioni sospette (SOSPETTO, INTERPOSTO, TRIANGOLAZIONE).

Restituisci ESCLUSIVAMENTE un JSON valido con questa struttura esatta:
{{
  "entita": [
    {{
      "id": "NOME_O_DENOMINAZIONE_COMPLETA",
      "tipo": "PERSONA|SOCIETA|CONTO|ASSET",
      "cf_piva": "Codice Fiscale o P.IVA se presente, altrimenti N/D"
    }}
  ],
  "relazioni": [
    {{
      "sorgente": "ID_SORGENTE",
      "destinazione": "ID_DESTINAZIONE",
      "tipo": "SOCIO|AMMINISTRATORE|BONIFICO|PROCURATORE|GARANTE|BENEFICIARIO_EFFETTIVO|FATTURA|SOSPETTO",
      "dettagli": "descrizione sintetica e importi/quote (es. Quota 50%, Bonifico 75.000€ del 14/03, Amministratore Unico)",
      "valore_numerico": 0
    }}
  ]
}}

Testo del documento:
{testo_blocco}
"""

    contenuto = ""
    try:
        t0 = time.time()
        stream = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            stream=True,
            options={
                "temperature": 0.1,
                "num_ctx": 8192,
            },
        )

        parti = []
        tokens = 0
        ultimo_update = 0

        for chunk in stream:
            frammento = chunk.get("message", {}).get("content", "")
            parti.append(frammento)
            tokens += 1
            ora = time.time()
            if callback_stream and (ora - ultimo_update > 0.35 or tokens % 10 == 0):
                ultimo_update = ora
                callback_stream(tokens, ora - t0, frammento)

        contenuto = "".join(parti)
        return json.loads(contenuto)
    except json.JSONDecodeError:
        pulito = re.sub(r"^```json\s*", "", contenuto.strip(), flags=re.MULTILINE)
        pulito = re.sub(r"\s*```$", "", pulito.strip(), flags=re.MULTILINE)
        try:
            return json.loads(pulito)
        except Exception:
            return {"entita": [], "relazioni": []}
    except Exception as e:
        log.error(f"Errore estrazione Ollama su '{nome_file}' (blocco {blocco_num}): {e}", exc_info=True)
        return {"entita": [], "relazioni": []}


def estrai_entita_e_relazioni_avanzato(
    blocchi_testo: list[str],
    nome_file: str,
    model: str = None,
    callback_progresso=None,
    base_perc: float = 0.2,
    peso_perc: float = 0.4,
) -> dict:
    totale = len(blocchi_testo)
    tutte_entita = []
    tutte_relazioni = []
    peso_per_blocco = peso_perc / max(1, totale)

    for i, blocco in enumerate(blocchi_testo, start=1):
        blocco_base = base_perc + (peso_per_blocco * (i - 1))
        blocco_max = base_perc + (peso_per_blocco * i)

        def cb_stream_blocco(tokens: int, elapsed: float, chunk: str):
            if callback_progresso:
                frazione_blocco = min(0.90, tokens / max(150, tokens + 40))
                perc_corrente = blocco_base + (frazione_blocco * peso_per_blocco)
                msg = f"🔍 [Fase 2/4] Parsing Blocco {i}/{totale} di '{nome_file}'"
                callback_progresso(perc_corrente, msg, tokens=tokens, elapsed=elapsed)

        dati_blocco = estrai_entita_e_relazioni_singolo_blocco(
            testo_blocco=blocco,
            nome_file=nome_file,
            blocco_num=i,
            totale_blocchi=totale,
            model=model,
            callback_stream=cb_stream_blocco,
        )
        tutte_entita.extend(dati_blocco.get("entita", []))
        tutte_relazioni.extend(dati_blocco.get("relazioni", []))

        if callback_progresso:
            callback_progresso(blocco_max, f"✅ Completato Blocco {i}/{totale} di '{nome_file}'")

    return {
        "entita": tutte_entita,
        "relazioni": tutte_relazioni,
    }


def genera_dossier_forense_globale(
    gestore_grafo,
    estratti_documenti: dict[str, str],
    model: str = None,
    ha_grafo: bool = True,
    callback_progresso=None,
) -> str:
    """
    Genera l'ANALISI FORENSE COMPLESSIVA ED INCROCIATA DI TUTTI I DOCUMENTI CARICATI.
    Incrocia obbligatoriamente ogni singolo documento del fascicolo evidenziando
    convergenze di soggetti, triangolazioni finanziarie, incongruenze e accertamenti bancari.
    """
    if not model:
        model = get_active_model()

    num_documenti = len(estratti_documenti)
    nomi_documenti = list(estratti_documenti.keys())
    log.info(f"Avvio redazione Dossier Forense Globale Incrociato su {num_documenti} documenti: {nomi_documenti}")

    if callback_progresso:
        callback_progresso(0.72, f"🧠 Integrazione delle risultanze di tutti i {num_documenti} atti...")

    t0 = time.time()

    # 1. Quadro topologico del grafo integrato
    quadro_grafo = ""
    if ha_grafo:
        quadro_grafo = gestore_grafo.costruisci_quadro_globale_per_llm()
    else:
        quadro_grafo = "Modalità 'Solo Analisi Rapida' (Grafo non elaborato)."

    # 2. Elenco analitico di TUTTI i documenti del fascicolo
    schede_documenti = []
    for idx, (nome_doc, testo) in enumerate(estratti_documenti.items(), start=1):
        estratto_saliente = testo[:7500] if len(testo) > 7500 else testo
        schede_documenti.append(f"""
======================================================================
[FASCICOLO ATTO #{idx} DI {num_documenti}: {nome_doc}]
======================================================================
{estratto_saliente}
""")

    blocco_documenti = "\n".join(schede_documenti)
    lista_puntata_docs = "\n".join([f"  {i}. {nome}" for i, nome in enumerate(nomi_documenti, start=1)])

    prompt = f"""
Sei un Perito Forense Antiriciclaggio (AML), Ufficiale Superiore della Guardia di Finanza (Nucleo PEF) e Consulente Tecnico d'Ufficio (CTU) per la Procura della Repubblica.
Hai davanti a te il FASCICOLO D'INDAGINE COMPLETO formato da esattamente {num_documenti} ATTI DOCUMENTALI:
{lista_puntata_docs}

======================================================================
REQUISITO IMPERATIVO E VINCOLANTE DI QUALITÀ PERITALE:
NON PRODURRE UN COMPITINO TELEGRAFICO O ELENCHI PUNTATI GENERICI.
DEVI REDIGERE UNA VERA RELAZIONE TECNICO-GIUDIZIARIA APPROFONDITA ED ESTESA,
SVILUPPATA PARAGRAFO PER PARAGRAFO CON RIGORE MOTIVAZIONALE, CIFRE ESATTE AL CENTESIMO,
DATE PRECISE, NUMERI DI CONTO/IBAN, ANALISI CRITICA DEI PRESTANOME E ARTICOLI DEL CODICE PENALE.
TUTTI E {num_documenti} GLI ATTI DEVONO ESSERE INCROCIATI E CONFRONTATI ANALITICAMENTE.
======================================================================

RISULTANZE DELLA RETE COMPUTAZIONALE D'INDAGINE (FOLLOWTHEMONEY & DUCKDB):
{quadro_grafo}

TESTO DEGLI ATTI DEL FASCICOLO:
{blocco_documenti}

======================================================================
SCHEMA OBBLIGATORIO DELLA RELAZIONE PERITALE FORENSE INTEGRATA:
======================================================================

# ⚖️ RELAZIONE PERITALE FORENSE INTEGRATA ({num_documenti} ATTI INCROCIATI)

## I. INQUADRAMENTO GENERALE DEL FASCICOLO E NATURA GIURIDICA DEGLI ATTI
(Esamina analiticamente ciascuno dei {num_documenti} documenti. Per ogni atto specifica:
- Protocollo/identificativo dell'atto e data;
- Soggetto segnalante o rogante;
- Soggetti fisici e giuridici censiti;
- Oggetto delle operazioni segnalate e rilevanza probatoria nell'impianto accusatorio complessivo).

## II. LA STRUTTURA SOGGETTIVA E LA CABINA DI REGIA: DOMINUS vs INTERPOSTE PERSONE
(Distingui con precisione la figura del dominus/regista occulto da quella delle teste di legno/prestanome.
Analizza nel dettaglio:
- Chi è l'amministratore di fatto che gestisce le trattative e le risorse finanziarie;
- Chi è la figura interposta (es. prestanome privi di reddito o con cariche societarie multiple fittizie);
- Eventuali legami professionali, mandati fiduciari o conflitti di interesse palesi tra avvocati, amministratori e società).

## III. RICOSTRUZIONE ANALITICA DEI FLUSSI FINANZIARI E DELLE OPERAZIONI BANCARIE
(Traccia nel dettaglio i percorsi del denaro emersi dai {num_documenti} atti:
- Importi esatti movimentati (cifre in euro, bonifici in entrata e uscita);
- Conti correnti, istituti di credito e IBAN utilizzati;
- Meccanismi di provvista, giustificativi contabili e causali commerciali fittizie o generiche;
- Triangolazioni, giroconti esteri o circuiti chiusi di rientro delle somme).

## IV. MODUS OPERANDI: OPERAZIONI STRAORDINARIE, CESSIONI CREDITI E GARANZIE FITTIZIE
(Approfondisci i meccanismi economici utilizzati per drenare risorse o simulare solidità patrimoniale:
- Cessioni di crediti fiscali o commerciali (es. Superbonus, ecobonus, crediti IVA);
- Richieste di garanzie o coperture assicurative a enti pubblici o parabancari (es. Simest, SACE, fondi di garanzia);
- Contratti di finanziamento e asseverazioni con documentazione carente o artefatta).

## V. INCONGRUENZE, DISCREPANZE E CONTRADDIZIONI INTER-DOCUMENTALI
(Metti a confronto diretto i diversi atti evidenziando le contraddizioni palesi:
- Differenze tra dimensioni aziendali effettive (fatturati reali in calo) e importi milionari richiesti o movimentati;
- Omissioni documentali nelle due diligence;
- Incompatibilità temporali tra cariche societarie, delibere e firme su contratti o bonifici).

## VI. QUALIFICAZIONE GIURIDICO-PENALE DELLE FATTISPECIE CRIMINOSE
(Formula un'accurata qualificazione giuridica dei fatti con richiamo alle norme violate:
- Art. 648-bis c.p. (Riciclaggio) e Art. 648-ter.1 c.p. (Autoriciclaggio);
- Art. 512-bis c.p. (Trasferimento fraudolento di valori / Intestazione fittizia di beni);
- D.Lgs. 74/2000 (Reati tributari per emissione/utilizzo di fatture per operazioni inesistenti o indebite compensazioni);
- Art. 216 e 223 R.D. 267/1942 / Codice della Crisi (Bancarotta fraudolenta per distrazione patrimoniale o documentale)).

## VII. PIANO OPERATIVO D'INDAGINE: ACCERTAMENTI BANCARI E MISURE CAUTELARI
(Elenco schematico e operativo per gli inquirenti:
- **Accertamenti bancari mirati**: specifica i singoli IBAN, i conti correnti e gli istituti da sottoporre ad acquisizione integrale degli estratti conto e dei contratti di firma/delega;
- **Misure cautelari reali raccomandate**: proposta di sequestro preventivo, anche per equivalente ex art. 321 c.p.p., quantificando l'importo da sottoporre a vincolo;
- **Atti istruttori urgenti**: perquisizioni locali/informatiche, escussione a sommarie informazioni testimoniali dei prestanome e rogatorie internazionali).

Redigi la relazione con prosa autorevole, peritale, analitica ed esaustiva, evitando sintesi frettolose.
"""

    contenuto = ""
    try:
        stream = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            options={
                "temperature": 0.25,
                "top_p": 0.9,
                "num_ctx": 24576,
            },
        )

        parti = []
        tokens = 0
        ultimo_update = 0

        for chunk in stream:
            frammento = chunk.get("message", {}).get("content", "")
            parti.append(frammento)
            tokens += 1
            ora = time.time()

            if callback_progresso and (ora - ultimo_update > 0.35 or tokens % 12 == 0):
                ultimo_update = ora
                frazione = min(0.95, tokens / max(500, tokens + 100))
                perc_dossier = 0.72 + (frazione * 0.26)
                elapsed = ora - t0
                callback_progresso(
                    perc_dossier,
                    f"🧠 [Fase 4/4] Redazione Dossier Forense Unificato ({num_documenti} atti)...",
                    tokens=tokens,
                    elapsed=elapsed,
                )

        dossier_testo = "".join(parti)
        durata = round(time.time() - t0, 2)
        log.info(f"Dossier globale unificato generato in {durata}s ({tokens} token) per {num_documenti} documenti")
        
        # Salva copia di sicurezza su disco
        try:
            os.makedirs("logs", exist_ok=True)
            with open("logs/ultimo_dossier_unificato.md", "w", encoding="utf-8") as f:
                f.write(dossier_testo)
        except Exception as e:
            log.debug(f"Impossibile salvare copia dossier su disco: {e}")

        if callback_progresso:
            callback_progresso(1.0, f"✅ Dossier completato con successo ({durata}s, {tokens} token)!")
        return dossier_testo or "Nessuna deduzione prodotta."
    except Exception as e:
        log.error(f"Errore generazione dossier globale: {e}", exc_info=True)
        return f"Errore durante l'elaborazione del dossier: {e}"

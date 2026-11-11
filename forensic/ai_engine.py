import json
import os
import re
import time
from forensic.logger import log
from server import runtime

ULTRA_MODEL = "qwen2.5:14b"
BEST_MODEL = "qwen2.5:7b"
FAST_MODEL = "llama3.2:3b"



def _opzioni(model: str, **extra) -> dict:
    """Opzioni Ollama calibrate su RAM e modello (evita lo swap su Mac da 16 GB)."""
    opts = {"num_ctx": runtime.context_budget(model)}
    threads = runtime.cpu_threads()
    if threads:
        opts["num_thread"] = threads
    opts.update(extra)
    return opts


def caratteri_per_contesto(model: str, riserva_token: int) -> int:
    """Quanti caratteri di testo entrano nel contesto lasciando riserva_token liberi."""
    return max(4000, int((runtime.context_budget(model) - riserva_token) * 2.6))


def _client():
    return runtime.client()


def get_available_models() -> dict:
    """
    Rileva quali modelli sono installati localmente in Ollama.
    Restituisce un dizionario con la disponibilità di 14B, 7B e 3B.
    """
    try:
        nomi = runtime.installed_models()
        nomi_puliti = [str(n).lower() for n in nomi if n]

        ha_14b = any("14b" in n for n in nomi_puliti)
        ha_7b = any("7b" in n for n in nomi_puliti)
        ha_3b = any("3b" in n for n in nomi_puliti)

        nome_14b = next((n for n in nomi if "14b" in str(n).lower()), ULTRA_MODEL)
        nome_7b = next((n for n in nomi if "7b" in str(n).lower()), BEST_MODEL)
        nome_3b = next((n for n in nomi if "3b" in str(n).lower()), FAST_MODEL)

        return {
            "has_14b": ha_14b,
            "has_7b": ha_7b,
            "has_3b": ha_3b,
            "name_14b": nome_14b,
            "name_7b": nome_7b,
            "name_3b": nome_3b,
            "all_models": nomi,
        }
    except Exception as e:
        log.warning(f"Errore lettura modelli Ollama: {e}")
        return {
            "has_14b": False,
            "has_7b": True,
            "has_3b": True,
            "name_14b": ULTRA_MODEL,
            "name_7b": BEST_MODEL,
            "name_3b": FAST_MODEL,
            "all_models": [],
        }


def get_active_model() -> str:
    try:
        disponibili = get_available_models()
        if disponibili["has_14b"]:
            return disponibili["name_14b"]
        if disponibili["has_7b"]:
            return disponibili["name_7b"]
        if disponibili["has_3b"]:
            return disponibili["name_3b"]
        if disponibili["all_models"] and disponibili["all_models"][0]:
            return disponibili["all_models"][0]
    except Exception as e:
        log.warning(f"Impossibile elencare i modelli da Ollama ({e}). Fallback su {BEST_MODEL}")

    return BEST_MODEL


def _chiudi_e_ripara_json(testo: str) -> dict:
    """Riparatore resiliente per JSON interrotti o malformati prodotti da LLM locali."""
    testo = testo.strip()
    try:
        return json.loads(testo)
    except Exception:
        pass

    pulito = re.sub(r"^```json\s*", "", testo, flags=re.MULTILINE)
    pulito = re.sub(r"\s*```$", "", pulito, flags=re.MULTILINE).strip()
    try:
        return json.loads(pulito)
    except Exception:
        pass

    # Tentativi euristici di chiusura parentesi
    for chiusura in ["]}", "\"}]}", "}]}", "\"}}", "}}", "]", "}"]:
        try:
            return json.loads(pulito + chiusura)
        except Exception:
            continue

    # Fallback tramite espressioni regolari per estrarre tutti gli oggetti validi
    entita = []
    relazioni = []
    try:
        m_ent = re.search(r'"entita"\s*:\s*\[(.*?)(?:\]|\Z)', pulito, re.DOTALL)
        if m_ent:
            for o in re.findall(r'\{[^{}]*\}', m_ent.group(1)):
                try:
                    entita.append(json.loads(o))
                except Exception:
                    pass
        m_rel = re.search(r'"relazioni"\s*:\s*\[(.*?)(?:\]|\Z)', pulito, re.DOTALL)
        if m_rel:
            for o in re.findall(r'\{[^{}]*\}', m_rel.group(1)):
                try:
                    relazioni.append(json.loads(o))
                except Exception:
                    pass
    except Exception:
        pass

    return {"entita": entita, "relazioni": relazioni}


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
Estrai con sintesi e accuratezza (massimo 25 entità e 30 relazioni principali, senza ripetizioni ad anello):
- PERSONE FISICHE (soci, amministratori, fiduciari, prestanome, beneficiari effettivi, professionisti).
- SOCIETÀ ED ENTI (aziende, fiduciarie, holding, consorzi).
- CONTI BANCARI ED ASSET (IBAN, rapporti bancari, immobili).

Estrai le relazioni giuridiche ed economiche salienti:
- Partecipazioni e cariche societarie (SOCIO, AMMINISTRATORE, LIQUIDATORE).
- Flussi finanziari e transazioni (BONIFICO, PAGAMENTO, PRESTITO, FATTURA).
- Deleghe e garanzie (PROCURATORE, GARANTE, BENEFICIARIO_EFFETTIVO).

Restituisci ESCLUSIVAMENTE un JSON valido e termina subito dopo con la parentesi chiusa '}}':
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
      "tipo": "SOCIO|AMMINISTRATORE|BONIFICO|PROCURATORE|GARANTE|BENEFICIARIO_EFFETTIVO|FATTURA",
      "dettagli": "descrizione sintetica e importi (es. Quota 50%, Bonifico 75.000€, Amministratore)",
      "valore_numerico": 0
    }}
  ]
}}

Testo del documento:
{testo_blocco}
"""

    contenuto = ""
    MAX_TOKENS_BLOCCO = 2500
    MAX_SECONDI_BLOCCO = 240

    try:
        t0 = time.time()
        stream = _client().chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            stream=True,
            options=_opzioni(model, temperature=0.1, num_predict=MAX_TOKENS_BLOCCO, repeat_penalty=1.15),
        )

        parti = []
        t_primo = None  # il timer di sicurezza parte dal primo token, non dal prefill
        tokens = 0
        ultimo_update = 0

        for chunk in stream:
            frammento = chunk.get("message", {}).get("content", "")
            parti.append(frammento)
            tokens += 1
            ora = time.time()
            if t_primo is None and frammento:
                t_primo = ora
            elapsed = ora - t0

            if callback_stream and (ora - ultimo_update > 0.35 or tokens % 10 == 0):
                ultimo_update = ora
                callback_stream(tokens, elapsed, frammento)

            # Circuit breaker di salvaguardia per bloccare loop infiniti locali
            if tokens >= MAX_TOKENS_BLOCCO or (ora - (t_primo or ora)) >= MAX_SECONDI_BLOCCO:
                log.warning(f"Circuit breaker attivato su '{nome_file}' (blocco {blocco_num}): {tokens} token generati in {round(elapsed, 1)}s. Interruzione forzata dello stream.")
                break

        contenuto = "".join(parti)
        return _chiudi_e_ripara_json(contenuto)
    except Exception as e:
        log.error(f"Errore estrazione Ollama su '{nome_file}' (blocco {blocco_num}): {e}", exc_info=True)
        if contenuto:
            return _chiudi_e_ripara_json(contenuto)
        return {"entita": [], "relazioni": []}


def estrai_entita_e_relazioni_avanzato(
    blocchi_testo: list[str],
    nome_file: str,
    model: str = None,
    callback_progresso=None,
    base_perc: float = 0.2,
    peso_perc: float = 0.4,
) -> dict:
    # Ricalibra i blocchi sul contesto reale del modello (riserva: risposta + prompt)
    if not model:
        model = get_active_model()
    max_chars = caratteri_per_contesto(model, 2500 + 900)
    testo_intero = "\n".join(blocchi_testo)
    if any(len(b) > max_chars for b in blocchi_testo):
        sovrapp = 1200
        blocchi_testo = [testo_intero[i:i + max_chars] for i in range(0, len(testo_intero), max_chars - sovrapp)]
    totale = len(blocchi_testo)
    tutte_entita = []
    tutte_relazioni = []
    peso_per_blocco = peso_perc / max(1, totale)

    for i, blocco in enumerate(blocchi_testo, start=1):
        blocco_base = base_perc + (peso_per_blocco * (i - 1))
        blocco_max = base_perc + (peso_per_blocco * i)

        def cb_stream_blocco(tokens: int, elapsed: float, chunk: str):
            if callback_progresso:
                frazione_blocco = min(0.95, tokens / 1000.0)
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
    if not model:
        model = get_active_model()
    budget = caratteri_per_contesto(model, 5000 + 2200 + int(len(quadro_grafo) / 2.6))
    per_doc = max(1500, budget // max(1, num_documenti))
    for idx, (nome_doc, testo) in enumerate(estratti_documenti.items(), start=1):
        estratto_saliente = testo[:per_doc]
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
1. DIVIETO CATEGORICO DI ANALISI SEPARATA ATTO PER ATTO:
   NON creare MAI sezioni o sottosezioni come "Atto 1", "Atto 2", "UF...", o riassunti documento per documento.
   I singoli atti sono GIÀ analizzati singolarmente nella sezione "Report Atti".
   Questa perizia è ESCLUSIVAMENTE l'ANALISI FORENSE INCROCIATA COMPLESSIVA:
   deve collegare tutti i fili dell'inchiesta, dimostrando l'unitarietà del disegno criminoso,
   la cabina di regia e la circolazione delle risorse finanziarie.
2. CITAZIONI INCROCIATE OBBLIGATORIE:
   In ogni paragrafo devi incrociare almeno 2 o più atti citandoli tra parentesi (es. "[UF... e UF...]").
   Evidenzia chiaramente le persone fisiche che compaiono in più atti (soggetti ponte).
3. RIGORE E PROFONDITÀ:
   Nessun compitino telegrafico o "Non evidenti". Formula deduzioni motivate su ogni capitolo.
======================================================================

RISULTANZE DELLA RETE COMPUTAZIONALE D'INDAGINE (NETWORKX, FOLLOWTHEMONEY OCCRP & DUCKDB OLAP):
{quadro_grafo}

TESTO DEGLI ATTI DEL FASCICOLO (FONTI PROBATORIE):
{blocco_documenti}

======================================================================
SCHEMA OBBLIGATORIO DELLA RELAZIONE PERITALE FORENSE INTEGRATA:
======================================================================

# ⚖️ RELAZIONE PERITALE FORENSE INTEGRATA (ANALISI INCROCIATA SU {num_documenti} ATTI)

## I. SCHEMA UNITARIO DELL'INCHIESTA E MATRICE DELLE CONVERGENZE MULTI-ATTO
(Non elencare gli atti uno per uno. Spiega come i {num_documenti} atti compongono un unico mosaico investigativo.
Delinea la matrice dei soggetti trasversali presenti in 2 o più atti distinti, spiegando come fungano da raccordo tra le diverse vicende societarie e le segnalazioni bancarie).

## II. LA CABINA DI REGIA: DOMINUS OCCULTO, TITOLARI EFFETTIVI E RETE DI PRESTANOME
(Sulla base dei calcoli di centralità NetworkX e delle catene di controllo FollowTheMoney:
- Individua con precisione il DOMINUS / REGISTA EFFETTIVO delle operazioni e chi ne detiene il controllo sostanziale (UBO);
- Identifica le INTERPOSTE PERSONE / TESTE DI LEGNO (amministratori formali, soggetti privi di patrimonio o con cariche seriali);
- Evidenzia il ruolo di professionisti, avvocati o fiduciari e i conflitti di interesse tra le società coinvolte).

## III. RICOSTRUZIONE ANALITICA DEI FLUSSI FINANZIARI E RICONCILIAZIONE PARTITE (DUCKDB LEDGER)
(Incrocia i flussi finanziari risultanti dai diversi documenti:
- Confronta gli importi milionari richiesti o dichiarati (es. garanzie, finanziamenti, commesse) con i bonifici effettivamente eseguiti e i saldi tracciati;
- Traccia i movimenti di denaro tra le società del gruppo (giroconti, bonifici con causali generiche o fittizie);
- Specifica istituti di credito, conti correnti e IBAN utilizzati per la dispersione della provvista).

## IV. MODUS OPERANDI: OPERAZIONI STRAORDINARIE, SCATOLE CINESI E DRENAGGIO RISORSE
(Spiega le tecniche fraudolente emerse dall'incrocio degli atti:
- Catene partecipative a schermo (holding fittizie, partecipazioni incrociate o a cascata);
- Utilizzo distorto di garanzie pubbliche o parabancarie (Simest, SACE, CDP) e contratti d'appalto/subappalto;
- Meccanismi di svuotamento societario e distrazione di liquidità verso veicoli terzi).

## V. MATRICE DELLE INCONGRUENZE, DISCREPANZE E CONTRADDIZIONI INTER-DOCUMENTALI
(Metti a confronto diretto e dialettico le risultanze dei diversi atti:
- Discrepanze palesi tra la consistenza aziendale reale (fatturato, dipendenti) e i volumi finanziari movimentati o richiesti;
- Contraddizioni tra quanto dichiarato nelle due diligence o asseverazioni e quanto riscontrato nei controlli bancari;
- Sovrapposizioni temporali e cariche societarie incompatibili tra atti diversi).

## VI. QUALIFICAZIONE GIURIDICO-PENALE DELLE FATTISPECIE CRIMINOSE
(Formula un inquadramento penalistico organico delle condotte:
- Art. 648-bis c.p. (Riciclaggio) e Art. 648-ter.1 c.p. (Autoriciclaggio);
- Art. 512-bis c.p. (Trasferimento fraudolento di valori / Intestazione fittizia di beni);
- D.Lgs. 74/2000 (Reati tributari per fatture per operazioni inesistenti o indebite compensazioni);
- R.D. 267/1942 e Codice della Crisi (Bancarotta fraudolenta distrattiva e documentale)).

## VII. DISPOSITIVO OPERATIVO PER L'AUTORITÀ GIUDIZIARIA E RICHIESTE CAUTELARI
(Fornisci indicazioni peritali operative e concrete per gli inquirenti:
- **Sequestro preventivo ex art. 321 c.p.p.**: quantifica l'importo esatto da sottoporre a vincolo reale, anche per equivalente;
- **Accertamenti bancari puntuali**: specifica conti, IBAN e istituti su cui richiedere i tabulati integrali e la documentazione di accensione/firma;
- **Atti istruttori urgenti**: perquisizioni locali/informatiche presso le sedi legali e studi professionali, audizione testimoniale delegata dei prestanome).

Redigi la relazione con prosa autorevole, peritale, analitica ed esaustiva, evitando sintesi frettolose.
"""

    contenuto = ""
    MAX_TOKENS_DOSSIER = 5000
    MAX_SECONDI_DOSSIER = 900

    try:
        stream = _client().chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            options=_opzioni(model, temperature=0.2, top_p=0.9, num_predict=MAX_TOKENS_DOSSIER, repeat_penalty=1.15),
        )

        parti = []
        t_primo = None  # il timer di sicurezza parte dal primo token, non dal prefill
        tokens = 0
        ultimo_update = 0

        for chunk in stream:
            frammento = chunk.get("message", {}).get("content", "")
            parti.append(frammento)
            tokens += 1
            ora = time.time()
            if t_primo is None and frammento:
                t_primo = ora
            elapsed = ora - t0

            if callback_progresso and (ora - ultimo_update > 0.35 or tokens % 12 == 0):
                ultimo_update = ora
                frazione = min(0.95, tokens / max(500, tokens + 100))
                perc_dossier = 0.72 + (frazione * 0.26)
                callback_progresso(
                    perc_dossier,
                    f"🧠 [Fase 4/4] Redazione Dossier Forense Unificato ({num_documenti} atti)...",
                    tokens=tokens,
                    elapsed=elapsed,
                )

            # Circuit breaker di sicurezza
            if tokens >= MAX_TOKENS_DOSSIER or (ora - (t_primo or ora)) >= MAX_SECONDI_DOSSIER:
                log.warning(f"Circuit breaker attivato su Dossier Globale: {tokens} token in {round(elapsed, 1)}s. Conclusione output.")
                break

        dossier_testo = "".join(parti)
        durata = round(time.time() - t0, 2)
        log.info(f"Dossier globale unificato generato in {durata}s ({tokens} token) per {num_documenti} documenti")
        

        if callback_progresso:
            callback_progresso(1.0, f"✅ Dossier completato con successo ({durata}s, {tokens} token)!")
        return dossier_testo or "Nessuna deduzione prodotta."
    except Exception as e:
        log.error(f"Errore generazione dossier globale: {e}", exc_info=True)
        return f"Errore durante l'elaborazione del dossier: {e}"


def genera_deduzioni(
    riassunto_grafo: str,
    testo_nuovo_documento: str,
    nome_documento: str = "",
    model: str = None,
    callback_progresso=None,
    base_perc: float = 0.75,
    peso_perc: float = 0.24,
) -> str:
    """
    Analisi Cross-Documentale Incrementale:
    Riceve il riassunto cumulativo del grafo preesistente + il testo del nuovo documento acquisito.
    Identifica punti salienti, connessioni e sovrapposizioni con atti precedenti e deduzioni investigative AML.
    """
    if not model:
        model = get_active_model()

    rif_doc = f"'{nome_documento}'" if nome_documento else "nuovo documento acquisito"

    prompt = f"""
Sei un analista ed investigatore forense antiriciclaggio (AML).
È appena stato inserito un nuovo documento ({rif_doc}) nel fascicolo d'indagine.

======================================================================
STATO CUMULATIVO DEL DATABASE D'INDAGINE (RETE DI RELAZIONI GIÀ ACQUISITE):
======================================================================
{riassunto_grafo}

======================================================================
ESTRATTO DEL NUOVO DOCUMENTO ACQUISITO ({rif_doc}):
======================================================================
{testo_nuovo_documento[:caratteri_per_contesto(model, 2000 + 1200 + int(len(riassunto_grafo) / 2.6))]}

======================================================================
COMPITO INVESTIGATIVO - ANALISI CROSS-DOCUMENTALE:
======================================================================
1. **Punti Salienti del Documento**: sintetizza gli elementi chiave dell'atto appena acquisito (soggetti fisici/giuridici, importi, date, causali, ruoli).
2. **Collegamenti e Sovrapposizioni Cross-Documentali**: evidenzia TUTTI i punti di contatto, persone, società, conti bancari o intermediari che compaiono sia nel nuovo documento sia negli atti preesistenti già registrati nel grafo.
3. **Deduzioni Investigative Forensi**: formula ipotesi investigative concrete (es. società schermo, prestanome/teste di legno, passaggi anomali o triangolazioni di denaro, conflitti di interesse, anomalie antiriciclaggio).

Sii rigoroso, cita espressamente le fonti e i collegamenti tra documenti diversi.
"""
    MAX_TOKENS_DEDUZIONE = 2000
    MAX_SECONDI_DEDUZIONE = 300

    try:
        t0 = time.time()
        stream = _client().chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            options=_opzioni(model, temperature=0.1, num_predict=MAX_TOKENS_DEDUZIONE, repeat_penalty=1.15),
        )
        parti = []
        t_primo = None  # il timer di sicurezza parte dal primo token, non dal prefill
        tokens = 0
        ultimo_update = 0
        for chunk in stream:
            frammento = chunk.get("message", {}).get("content", "")
            parti.append(frammento)
            tokens += 1
            ora = time.time()
            if t_primo is None and frammento:
                t_primo = ora
            elapsed = ora - t0

            if callback_progresso and (ora - ultimo_update > 0.3 or tokens % 8 == 0):
                ultimo_update = ora
                frazione = min(0.95, tokens / max(250, tokens + 40))
                perc = base_perc + (frazione * peso_perc)
                callback_progresso(
                    perc,
                    f"🧠 Deduzioni cross-documentali per '{nome_documento}' ({tokens} token)...",
                    tokens=tokens,
                    elapsed=elapsed,
                )

            # Circuit breaker di sicurezza
            if tokens >= MAX_TOKENS_DEDUZIONE or (ora - (t_primo or ora)) >= MAX_SECONDI_DEDUZIONE:
                log.warning(f"Circuit breaker attivato su Deduzioni per '{nome_documento}': {tokens} token in {round(elapsed, 1)}s. Conclusione output.")
                break
        return "".join(parti)
    except Exception as e:
        log.error(f"Errore deduzioni cross-documentali: {e}", exc_info=True)
        return f"Errore durante l'elaborazione delle deduzioni: {e}"

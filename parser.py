import os
import io
import fitz  # PyMuPDF
import docx
import pandas as pd
import pdfplumber
import bankstatementparser as bsp
from logger import log

# SOGLIE CONFIGURABILI
MAX_CARATTERI_CONSIGLIATI = 25000  # Soglia per blocco singolo
MIN_CARATTERI_PER_PAGINA = 40      # Soglia sotto la quale la pagina è priva di testo selezionabile


def suddividi_in_blocchi(testo: str, dimensione_blocco: int = 22000, sovrapposizione: int = 2000) -> list[str]:
    """
    Suddivide documenti complessi e lunghi (perizie, rogiti, bilanci estesi, fascicoli processuali)
    in blocchi sovrapposti (sliding window) per garantire che l'LLM non perda dettagli cruciali.
    """
    if len(testo) <= dimensione_blocco:
        return [testo]

    blocchi = []
    inizio = 0
    while inizio < len(testo):
        fine = inizio + dimensione_blocco
        blocco = testo[inizio:fine]
        blocchi.append(blocco)
        inizio += (dimensione_blocco - sovrapposizione)

    log.info(f"Documento esteso ({len(testo)} caratteri) suddiviso in {len(blocchi)} blocchi di analisi consecutivi")
    return blocchi


def estrai_tabelle_contabili_pdf(file_bytes: bytes) -> str:
    """
    Utilizza pdfplumber per estrarre prospetti tabellari contabili, bilanci ed estratti conto bancari,
    preservando la geometria delle colonne e delle celle.
    """
    tabelle_estratte = []
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for num_p, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables()
                for t_idx, table in enumerate(tables):
                    if not table or len(table) < 2:
                        continue
                    righe_pulite = []
                    for row in table:
                        if any(cell and str(cell).strip() for cell in row):
                            riga = [str(c).replace("\n", " ").strip() if c else "" for c in row]
                            righe_pulite.append(" | ".join(riga))
                    if righe_pulite:
                        tabelle_estratte.append(f"\n[TABELLA CONTABILE PAG. {num_p} - prospetto #{t_idx+1}]\n" + "\n".join(righe_pulite))
    except Exception as e:
        log.debug(f"Estrazione tabelle pdfplumber non applicata: {e}")
    
    return "\n".join(tabelle_estratte)


def estrai_tracciato_bancario_digitale(file_bytes: bytes, nome_file: str) -> str:
    """
    Utilizza bankstatementparser per analizzare tracciati bancari digitali internazionali:
    - CAMT.053 / CAMT.054 (ISO 20022 XML)
    - MT940 / MT942 (Standard SWIFT)
    - OFX / QFX (Open Financial Exchange)
    - BAI2 e CSV bancari
    """
    try:
        import tempfile
        est = os.path.splitext(nome_file)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=est) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            if hasattr(bsp, "create_parser"):
                parser = bsp.create_parser(tmp_path)
                res = parser.parse()
                os.unlink(tmp_path)
                return f"\n=== TRACCIATO BANCARIO DIGITALE RICONCILIATO ({nome_file}) ===\n{res}\n"
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    except Exception as e:
        log.debug(f"Parsing tracciato bancario con bankstatementparser su '{nome_file}': {e}")
    return ""


def analizza_ed_estrai(file_caricato) -> dict:
    """
    Parser polivalente potenziato per documenti forensi:
    - PDF (Visure CCIAA, SOS, Contratti, Perizie CTU, Rogiti, Estratti Conto, Bilanci)
      -> Utilizza PyMuPDF per il flusso testuale e pdfplumber per le tabelle contabili
    - DOCX (Relazioni, Verbali, Note di perizia)
    - XLSX / XLS / CSV (Estratti conto, movimentazioni bancarie, tabulati)
    - TXT (Appunti investigativi, deposizioni, email)
    - XML (Fatture elettroniche SDI, tracciati bancari CAMT / SEPA)
    """
    nome_file = file_caricato.name
    estensione = os.path.splitext(nome_file)[1].lower()
    log.info(f"Avvio parsing diagnostico per '{nome_file}' (tipo: {estensione})")

    testo_completo = ""
    pagine_senza_ocr = []
    totale_pagine = 1

    try:
        # 1. DOCUMENTI PDF
        if estensione == ".pdf":
            file_bytes = file_caricato.read()
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            totale_pagine = len(doc)
            log.debug(f"PDF aperto con PyMuPDF: {totale_pagine} pagine")

            for num_pagina, pagina in enumerate(doc, start=1):
                testo_pagina = pagina.get_text("text").strip()

                if len(testo_pagina) < MIN_CARATTERI_PER_PAGINA:
                    pagine_senza_ocr.append(num_pagina)

                testo_completo += f"\n--- Pagina {num_pagina} ---\n" + testo_pagina

            # Estrazione supplementare tabelle contabili con pdfplumber se presenti
            tabelle_strutturate = estrai_tabelle_contabili_pdf(file_bytes)
            if tabelle_strutturate:
                testo_completo += "\n\n=== ESTRATTI E PROSPETTI TABELLARI CONTABILI RILEVATI ===\n" + tabelle_strutturate
                log.info(f"Tabelle contabili estratte con successo da '{nome_file}' tramite motore tabellare")

        # 2. DOCUMENTI WORD DOCX
        elif estensione == ".docx":
            doc = docx.Document(file_caricato)
            for para in doc.paragraphs:
                if para.text.strip():
                    testo_completo += para.text + "\n"

            for tabella in doc.tables:
                for riga in tabella.rows:
                    riga_testo = " | ".join([c.text.strip() for c in riga.cells if c.text.strip()])
                    if riga_testo:
                        testo_completo += riga_testo + "\n"

        # 3. FOGLI DI CALCOLO EXCEL (XLSX, XLS)
        elif estensione in [".xlsx", ".xls"]:
            excel_data = pd.read_excel(file_caricato, sheet_name=None)
            for nome_foglio, df in excel_data.items():
                testo_completo += f"\n--- Foglio Excel: {nome_foglio} ---\n"
                testo_completo += df.fillna("").to_string(index=False) + "\n"
            totale_pagine = len(excel_data)

        # 4. FILE TABELLARI CSV
        elif estensione == ".csv":
            try:
                df = pd.read_csv(file_caricato, sep=None, engine="python")
            except Exception:
                file_caricato.seek(0)
                df = pd.read_csv(file_caricato)
            testo_completo += "--- Tabella CSV (Movimenti / Transazioni) ---\n"
            testo_completo += df.fillna("").to_string(index=False) + "\n"

        # 5. TRACCIATI BANCARI DIGITALI (CAMT, MT940, OFX, QFX, BAI2)
        elif estensione in [".ofx", ".qfx", ".mt940", ".camt", ".bai2"]:
            file_bytes = file_caricato.read()
            tracciato = estrai_tracciato_bancario_digitale(file_bytes, nome_file)
            testo_completo = tracciato if tracciato else file_bytes.decode("utf-8", errors="replace")
            log.info(f"Tracciato bancario processato con bankstatementparser: '{nome_file}'")

        # 5. TESTO SEMPLICE / EMAIL / APPUNTI TXT
        elif estensione in [".txt", ".rtf", ".log"]:
            testo_completo = file_caricato.read().decode("utf-8", errors="replace")

        # 6. FATTURE E TRACCIATI XML (es. Fattura Elettronica SDI PA/B2B, CAMT.053)
        elif estensione == ".xml":
            raw_xml = file_caricato.read().decode("utf-8", errors="replace")
            import re
            # Estrai eventuali tag fattura o bancari significativi
            cedente = re.findall(r"<CedentePrestatore>[\s\S]*?<Denominazione>([^<]+)</Denominazione>", raw_xml)
            cessionario = re.findall(r"<CessionarioCommittente>[\s\S]*?<Denominazione>([^<]+)</Denominazione>", raw_xml)
            importi = re.findall(r"<ImportoTotaleDocumento>([^<]+)</ImportoTotaleDocumento>", raw_xml)
            
            testo_pulito = re.sub(r"<[^>]+>", " ", raw_xml)
            testo_completo = "--- Documento XML Strutturato (SDI / Bancario) ---\n"
            if cedente or cessionario or importi:
                testo_completo += f"CEDENTE RILEVATO: {cedente}\nCESSIONARIO RILEVATO: {cessionario}\nIMPORTO DOCUMENTO: {importi}\n"
            testo_completo += " ".join(testo_pulito.split())

        else:
            log.warning(f"Formato '{estensione}' non convenzionale, tentativo lettura testuale generica")
            testo_completo = file_caricato.read().decode("utf-8", errors="replace")

    except Exception as e:
        log.error(f"Errore critico durante la lettura del file '{nome_file}': {e}", exc_info=True)
        raise e

    perc_senza_ocr = len(pagine_senza_ocr) / max(1, totale_pagine)
    num_caratteri = len(testo_completo)

    if pagine_senza_ocr:
        log.warning(f"File '{nome_file}': {len(pagine_senza_ocr)}/{totale_pagine} pagine senza testo selezionabile")

    blocchi = suddividi_in_blocchi(testo_completo, dimensione_blocco=22000, sovrapposizione=2000)

    diagnostica = {
        "testo": testo_completo.strip(),
        "blocchi": blocchi,
        "num_blocchi": len(blocchi),
        "num_caratteri": num_caratteri,
        "totale_pagine": totale_pagine,
        "pagine_senza_ocr": pagine_senza_ocr,
        "manca_ocr": len(pagine_senza_ocr) > 0,
        "perc_senza_ocr": perc_senza_ocr,
        "troppo_lungo": num_caratteri > MAX_CARATTERI_CONSIGLIATI,
        "estensione": estensione,
    }

    log.info(f"Parsing completato con successo: '{nome_file}', {num_caratteri} caratteri in {len(blocchi)} blocchi")
    return diagnostica

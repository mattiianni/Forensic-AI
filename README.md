# Forensic AI Offline — Sistema Avanzato di Analisi Forense & Investigativa

Applicazione forense autonoma per l'analisi incrociata di atti societari e finanziari: **Segnalazioni Operazioni Sospette (SOS), Visure Camerali CCIAA, Bilanci d'Esercizio, Note Integrative, Estratti Conto Bancari (CAMT.053, MT940, OFX) e Fatture Elettroniche XML SDI**.

L'applicazione gira al **100% in locale offline** sul tuo Mac (ottimizzata nativamente per Apple Silicon M1/M2/M3/M4 arm64 e compatibile x86_64) sfruttando **Ollama** per l'intelligenza deduttiva, l'estrazione delle entità e la stesura di perizie giudiziarie / CTU.

---

## 🏛️ Architettura e Motori di Analisi

1. **Motore Grafi e Topologia (NetworkX & PyVis)**:
   - Grafo direzionato ponderato per relazioni societarie e flussi finanziari.
   - Algoritmo di rilevamento matematico di **scatole cinesi** e **flussi circolari** ($A \rightarrow B \rightarrow C \rightarrow A$).
   - Layout fisici con controlli interattivi (zoom, stabilizzazione fisica, reset visuale).

2. **Standard Investigativo OCCRP FollowTheMoney (FtM v3)**:
   - Generazione di entità secondo lo standard internazionale anti-corruzione (OCCRP Aleph / FollowTheMoney): `Person`, `Company`, `BankAccount`, `Ownership`, `Directorship`, `Payment`, `Family`.
   - Esportazione istantanea in formato JSON-Lines (`.jsonl`).

3. **Motore Finanziario OLAP In-Memory (DuckDB)**:
   - Querying SQL ultra-veloce su flussi di pagamento, bonifici e bilanci.
   - Calcolo automatico della matrice finanziaria forense (volumi totali in/out, aggregazioni per causale e soggetto, rilevamento prestanome vs dominus).

4. **Parser Specialistici Multi-Formato**:
   - **PDF & Bilanci**: PyMuPDF con fallback a `pdfplumber` per estrazione tabelle contabili e note integrative.
   - **Estratti Conto Bancari**: Supporto nativo via `bankstatementparser` per CAMT.053, MT940 e OFX.
   - **Fatturazione Elettronica**: Parser per XML SDI (FatturaPA).
   - **Office & Dati**: DOCX, XLSX, CSV.

5. **Entity Resolution Forense a 2 Livelli (Anti-Duplicati)**:
   - **Livello 1 - Chiave Univoca Fiscale**: Fusione automatica immediata su corrispondenza di Codice Fiscale o Partita IVA.
   - **Livello 2 - Normalizzazione & Inversione Nome/Cognome**: Risolve automaticamente inversioni (es. `ROSSI MARIO` == `MARIO ROSSI`) ordinando alfabeticamente i token del nome.

6. **Dossier Forense CTU Multi-Documento**:
   - Generazione di una relazione peritale completa strutturata su 7 capitoli giudiziari.
   - Streaming in tempo reale token-per-token con contatore parole e tempo di elaborazione.
   - Finestra di contesto estesa a 24.576 token (`num_ctx`) per elaborare interi fascicoli simultaneamente.

7. **Esportazione & Integrazione**:
   - **Mermaid.js**: Esportazione diagrammi di flusso relazionali pronti per GitHub, Obsidian o relazioni peritali.
   - **Cytoscape**: Compatibilità diretta con `Pdf_Relations` (`.relazioni.json`).
   - **FtM Aleph**: Export `.jsonl` standard OCCRP.
   - **Dossier Markdown**: Download immediato del dossier peritale.

---

## 🚀 Avvio Rapido

### Metodo 1: Doppio Click (App Nativa macOS)
Fai doppio click su:
```
Forensic AI Offline.app
```
oppure su `Avvia Forensic AI.command`. Il launcher verificherà l'avvio di Ollama, attiverà l'ambiente virtuale nativo arm64 ed aprirà l'interfaccia nel browser predefinito.

### Metodo 2: Da Terminale
```bash
./start.sh
```

---

## 🧠 Modelli Consigliati in Ollama

Puoi selezionare o cambiare il modello direttamente dall'interfaccia:
- **`qwen2.5:7b`** *(Raccomandato su Mac M1/M2/M3/M4)*: Massima precisione nella sintassi legale, societaria e bancaria italiana.
- **`llama3.2:3b`** *(Ultra-veloce)*: Basso consumo di memoria (ideale con 8GB di RAM) e risposte istantanee.
- **`llama3.1:8b`**: Modello bilanciato e versatile per analisi complesse.

Per scaricare un modello:
```bash
ollama pull qwen2.5:7b
```

---

## 🔒 Sicurezza & Privacy

- **100% Offline**: Nessun dato, documento, codice fiscale o transazione bancaria lascia mai la memoria del computer.
- Nessuna chiamata API esterna, nessun tracking, zero dipendenze cloud.

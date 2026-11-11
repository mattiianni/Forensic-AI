import datetime
import json
import re
import duckdb
import networkx as nx

from forensic.logger import log
from forensic.ftm_engine import FollowTheMoneyDataset


class GestoreGrafo:
    """
    Motore Forense Relazionale avanzato integrato con:
    1. Motore Analitico In-Memory DuckDB per query SQL ultra-veloci e fuzzy entity linkage.
    2. Modello Dati conforme all'ontologia FollowTheMoney (OCCRP Aleph standard).
    3. Riconoscimento pattern di riciclaggio (Ring/Star/Chain) e Incongruenze Cross-Documentali (DocETL).
    4. Master Timeline Cronologica forense in stile Google Timesketch.
    5. Esportazione multi-formato: Cytoscape (.relazioni.json), OCCRP Aleph (.ftm.json) e DuckDB Parquet/Excel.
    """

    def __init__(self):
        self.grafo = nx.MultiDiGraph()
        self.mappa_identita = {}  # CF/PIVA o Nome Normalizzato -> ID effettivo
        self.dati_nodi = {}       # ID effettivo -> {tipo, cf_piva, fonti: set(), ruoli: set()}
        self.eventi_timeline = [] # Lista di eventi cronologici con data, soggetti, atto, importo
        self.file_fonti = set()
        
        # Motore formale FollowTheMoney (OCCRP standard)
        self.ftm_dataset = FollowTheMoneyDataset()

        # Connessione analitica DuckDB in-memory
        self.db = duckdb.connect(":memory:")
        self._inizializza_tabelle_duckdb()
        log.debug("GestoreGrafo Forense (FollowTheMoney + DuckDB Analytics) inizializzato")

    def _inizializza_tabelle_duckdb(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS entita (
                id VARCHAR PRIMARY KEY,
                nome VARCHAR,
                tipo VARCHAR,
                cf_piva VARCHAR,
                ftm_schema VARCHAR,
                num_fonti INTEGER,
                fonti VARCHAR
            );
            CREATE TABLE IF NOT EXISTS relazioni (
                id VARCHAR,
                sorgente VARCHAR,
                destinazione VARCHAR,
                tipo VARCHAR,
                ftm_schema VARCHAR,
                dettagli VARCHAR,
                fonte VARCHAR,
                data_evento VARCHAR,
                valore_numerico DOUBLE
            );
        """)

    def normalizza_nome(self, nome: str) -> str:
        pulito = "".join(c if c.isalnum() or c.isspace() else " " for c in (nome or "").strip().upper())
        parole = sorted(pulito.split())
        return "_".join(parole) if parole else (nome or "").strip().upper()

    def risolvi_nodo_effettivo(self, id_estratto: str, cf_piva: str) -> str:
        cf_piva = str(cf_piva).strip().upper() if cf_piva and str(cf_piva).strip().upper() not in {"N/D", "NONE", "NULL"} else ""
        id_estratto = str(id_estratto).strip().upper()
        if not id_estratto:
            return "SCONOSCIUTO"

        # Livello 1: Risoluzione tramite Identificativo Fiscale Univoco (CF o P.IVA)
        if cf_piva:
            if cf_piva in self.mappa_identita:
                id_esistente = self.mappa_identita[cf_piva]
                nome_norm = self.normalizza_nome(id_estratto)
                self.mappa_identita[nome_norm] = id_esistente
                log.info(f"Entity Resolution [CF/PIVA]: unificato '{id_estratto}' -> '{id_esistente}' (CF: {cf_piva})")
                return id_esistente

            nome_norm = self.normalizza_nome(id_estratto)
            if nome_norm in self.mappa_identita:
                id_esistente = self.mappa_identita[nome_norm]
                self.mappa_identita[cf_piva] = id_esistente
                log.info(f"Entity Resolution [Nome su CF]: collegato CF '{cf_piva}' a '{id_esistente}'")
                return id_esistente

            self.mappa_identita[cf_piva] = id_estratto

        # Livello 2: Risoluzione per token ordinati (inversioni "Mario Rossi" == "Rossi Mario")
        nome_norm = self.normalizza_nome(id_estratto)
        if nome_norm in self.mappa_identita:
            id_esistente = self.mappa_identita[nome_norm]
            if cf_piva:
                self.mappa_identita[cf_piva] = id_esistente
            return id_esistente

        self.mappa_identita[nome_norm] = id_estratto
        return id_estratto

    def estrai_data_da_stringa(self, testo: str) -> str:
        if not testo:
            return ""
        # Match data italiana gg/mm/aaaa o gg-mm-aaaa o aaaa-mm-gg
        pattern = r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b"
        trovati = re.findall(pattern, testo)
        return trovati[0] if trovati else ""

    def estrai_valore_da_stringa(self, testo: str) -> float:
        if not testo:
            return 0.0
        pattern = r"(?:€|EUR|\bEURO\b)\s*([\d\.,]+)|([\d\.,]+)\s*(?:€|EUR|\bEURO\b)"
        m = re.search(pattern, testo, re.IGNORECASE)
        if m:
            val_str = m.group(1) or m.group(2)
            try:
                val_clean = val_str.replace(".", "").replace(",", ".")
                return float(val_clean)
            except Exception:
                return 0.0
        return 0.0

    def determina_schema_ftm(self, tipo_entita: str) -> str:
        """Mappa i tipi nell'ontologia OCCRP FollowTheMoney"""
        t = (tipo_entita or "").upper()
        if "PERS" in t or "FISIC" in t:
            return "Person"
        elif "SOC" in t or "AZIEN" in t or "DITT" in t or "SRL" in t or "SPA" in t:
            return "Company"
        elif "CONT" in t or "IBAN" in t or "BANC" in t:
            return "BankAccount"
        elif "IMMOB" in t or "TERR" in t or "FABBR" in t:
            return "RealEstate"
        return "LegalEntity"

    def determina_schema_relazione_ftm(self, tipo_relazione: str) -> str:
        r = (tipo_relazione or "").upper()
        if "SOC" in r or "QUOT" in r or "PARTECIP" in r:
            return "Ownership"
        elif "AMM" in r or "DIR" in r or "RAPPR" in r or "CARIC" in r:
            return "Directorship"
        elif "PAGAM" in r or "BONIF" in r or "TRASFER" in r or "FLUSS" in r:
            return "Payment"
        elif "PARENT" in r or "CONIUG" in r or "FIGLI" in r:
            return "Family"
        return "UnknownLink"

    def aggiungi_dati(self, dati_estratti: dict, fonte_file: str):
        if not dati_estratti:
            return

        self.file_fonti.add(fonte_file)
        nodi = dati_estratti.get("entita", [])
        relazioni = dati_estratti.get("relazioni", [])

        colori_tipo = {
            "PERSONA": "#0A84FF",      # Apple Blue
            "SOCIETA": "#30D158",      # Apple Green
            "CONTO": "#FF9F0A",        # Apple Orange
            "ASSET": "#BF5AF2",        # Apple Purple
            "ALTRO": "#8E8E93",        # Apple Gray
        }

        mappa_loc_to_eff = {}

        for n in nodi:
            id_raw = n.get("id")
            if not id_raw:
                continue

            tipo = str(n.get("tipo", "ALTRO")).strip().upper()
            cf_piva = str(n.get("cf_piva", "")).strip().upper()
            id_effettivo = self.risolvi_nodo_effettivo(id_raw, cf_piva)
            mappa_loc_to_eff[id_raw] = id_effettivo

            ftm_schema = self.determina_schema_ftm(tipo)

            if id_effettivo not in self.dati_nodi:
                self.dati_nodi[id_effettivo] = {
                    "tipo": tipo,
                    "cf_piva": cf_piva,
                    "ftm_schema": ftm_schema,
                    "fonti": {fonte_file},
                    "ruoli": set(),
                }
            else:
                self.dati_nodi[id_effettivo]["fonti"].add(fonte_file)
                if not self.dati_nodi[id_effettivo]["cf_piva"] and cf_piva:
                    self.dati_nodi[id_effettivo]["cf_piva"] = cf_piva

            if not self.grafo.has_node(id_effettivo):
                colore = colori_tipo.get(tipo, "#8E8E93")
                tooltip = f"<b>{id_effettivo}</b><br>Tipo: {tipo}<br>CF/P.IVA: {cf_piva or 'N/D'}<br>Fonte: {fonte_file}"
                self.grafo.add_node(
                    id_effettivo,
                    label=id_effettivo,
                    title=tooltip,
                    color=colore,
                    tipo=tipo,
                    cf_piva=cf_piva,
                    ftm_schema=ftm_schema,
                    fonte=fonte_file,
                    font={"color": "white", "face": "SF Pro Display, -apple-system, sans-serif"},
                )

            # Popolamento motore nativo FollowTheMoney (OCCRP)
            if ftm_schema == "Person":
                self.ftm_dataset.aggiungi_persona(id_effettivo, cf=cf_piva, fonte=fonte_file)
            elif ftm_schema == "Company":
                self.ftm_dataset.aggiungi_azienda(id_effettivo, piva_cf=cf_piva, fonte=fonte_file)
            elif ftm_schema == "BankAccount":
                self.ftm_dataset.aggiungi_conto_bancario(id_effettivo, fonte=fonte_file)
            else:
                ent_ftm = self.ftm_dataset.crea_o_aggiorna_entita(id_effettivo, ftm_schema, fonte=fonte_file)
                ent_ftm.add("name", id_effettivo)
                if cf_piva:
                    ent_ftm.add("taxNumber", cf_piva)

        archi_inseriti = 0
        for rel in relazioni:
            src_estratto = rel.get("sorgente")
            dst_estratto = rel.get("destinazione")
            if not src_estratto or not dst_estratto:
                continue

            src = mappa_loc_to_eff.get(src_estratto, self.risolvi_nodo_effettivo(src_estratto, ""))
            dst = mappa_loc_to_eff.get(dst_estratto, self.risolvi_nodo_effettivo(dst_estratto, ""))

            tipo_rel = str(rel.get("tipo", "LEGAME")).strip().upper()
            dettagli = str(rel.get("dettagli", "")).strip()
            data_evento = self.estrai_data_da_stringa(dettagli)
            valore_num = rel.get("valore_numerico") or self.estrai_valore_da_stringa(dettagli)
            ftm_rel_schema = self.determina_schema_relazione_ftm(tipo_rel)

            if src in self.dati_nodi:
                self.dati_nodi[src]["ruoli"].add(f"{tipo_rel} -> {dst}")
            if dst in self.dati_nodi:
                self.dati_nodi[dst]["ruoli"].add(f"<- {tipo_rel} da {src}")

            if not self.grafo.has_node(src):
                self.grafo.add_node(src, label=src, tipo="ALTRO", color="#8E8E93", font={"color": "white"})
            if not self.grafo.has_node(dst):
                self.grafo.add_node(dst, label=dst, tipo="ALTRO", color="#8E8E93", font={"color": "white"})

            self.grafo.add_edge(
                src,
                dst,
                label=tipo_rel,
                title=f"{tipo_rel}: {dettagli}\nFonte: {fonte_file}",
                dettagli=dettagli,
                fonte=fonte_file,
                data_evento=data_evento,
                valore_numerico=valore_num,
                ftm_schema=ftm_rel_schema,
            )
            archi_inseriti += 1

            self.eventi_timeline.append({
                "data": data_evento or "Data non specificata",
                "tipo": tipo_rel,
                "da": src,
                "a": dst,
                "dettagli": dettagli,
                "atto": fonte_file,
                "valore": valore_num,
            })

            # Popolamento relazioni nel motore FollowTheMoney
            if ftm_rel_schema == "Ownership":
                self.ftm_dataset.aggiungi_ownership(src, dst, ruolo=tipo_rel, fonte=fonte_file, dettagli=dettagli)
            elif ftm_rel_schema == "Directorship":
                self.ftm_dataset.aggiungi_directorship(src, dst, ruolo=tipo_rel, data_inizio=data_evento, fonte=fonte_file, dettagli=dettagli)
            elif ftm_rel_schema == "Payment":
                self.ftm_dataset.aggiungi_payment(src, dst, importo=str(valore_num) if valore_num else "", data_operazione=data_evento, causale=dettagli, fonte=fonte_file)
            else:
                rel_ftm = self.ftm_dataset.crea_o_aggiorna_entita(f"rel_{src}_{dst}", "UnknownLink", fonte=fonte_file)
                rel_ftm.add("summary", f"{tipo_rel}: {dettagli}")

        self._sincronizza_duckdb()
        log.info(f"Grafo unificato con '{fonte_file}': {len(self.grafo.nodes)} entità, {len(self.grafo.edges)} relazioni")

    def _sincronizza_duckdb(self):
        """Rigenera le tabelle in-memory DuckDB per query analitiche e audit forense"""
        try:
            self.db.execute("DELETE FROM entita; DELETE FROM relazioni;")
            
            ent_rows = []
            for n_id, data in self.grafo.nodes(data=True):
                meta = self.dati_nodi.get(n_id, {})
                fonti_str = ", ".join(meta.get("fonti", set()))
                ent_rows.append((
                    n_id,
                    data.get("label", n_id),
                    meta.get("tipo", data.get("tipo", "ALTRO")),
                    meta.get("cf_piva", data.get("cf_piva", "")),
                    meta.get("ftm_schema", "LegalEntity"),
                    len(meta.get("fonti", set())),
                    fonti_str
                ))
            if ent_rows:
                self.db.executemany("INSERT INTO entita VALUES (?, ?, ?, ?, ?, ?, ?)", ent_rows)

            rel_rows = []
            e_idx = 1
            for u, v, data in self.grafo.edges(data=True):
                rel_rows.append((
                    f"e_{e_idx}",
                    u,
                    v,
                    data.get("label", "LEGAME"),
                    data.get("ftm_schema", "UnknownLink"),
                    data.get("dettagli", ""),
                    data.get("fonte", ""),
                    data.get("data_evento", ""),
                    float(data.get("valore_numerico", 0.0))
                ))
                e_idx += 1
            if rel_rows:
                self.db.executemany("INSERT INTO relazioni VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rel_rows)
        except Exception as e:
            log.error(f"Errore sincronizzazione DuckDB: {e}", exc_info=True)

    def esegui_query_sql(self, sql_query: str) -> list[dict]:
        """Esegue query SQL arbitrarie sul database in-memory DuckDB per analisi forense avanzata"""
        try:
            res = self.db.execute(sql_query).fetchdf()
            return res.to_dict(orient="records")
        except Exception as e:
            log.error(f"Errore query SQL DuckDB: {e}", exc_info=True)
            return [{"errore": str(e)}]

    def trova_incongruenze_cross_documentali(self) -> list[dict]:
        """
        Rilevamento discrepanze (ispirato a DocETL Resolve):
        Identifica contraddizioni di cariche, quote societarie o dati contrastanti tra documenti diversi.
        """
        incongruenze = []
        try:
            # 1. Soggetti presenti in più atti con qualifiche o ruoli contrastanti
            for nodo, meta in self.dati_nodi.items():
                fonti = meta.get("fonti", set())
                if len(fonti) > 1:
                    ruoli = list(meta.get("ruoli", set()))
                    # Verifica ruoli incompatibili (es. amministratore e contemporaneamente liquidatore o fornitore)
                    ha_amm = any("AMM" in r or "DIRETT" in r for r in ruoli)
                    ha_liq = any("LIQUID" in r or "FALLIM" in r for r in ruoli)
                    if ha_amm and ha_liq:
                        incongruenze.append({
                            "soggetto": nodo,
                            "tipo": "Ruolo Incompatibile / Sospetto",
                            "dettagli": f"Presente sia con cariche di amministrazione che in contesti di liquidazione/crisi su {len(fonti)} atti distinti.",
                            "fonti": list(fonti)
                        })

            # 2. Relazioni duplicate o confliggenti con percentuali o quote discordanti
            coppie_rel = {}
            for u, v, data in self.grafo.edges(data=True):
                chiave = (u, v)
                if chiave not in coppie_rel:
                    coppie_rel[chiave] = []
                coppie_rel[chiave].append(data)

            for (u, v), lista in coppie_rel.items():
                if len(lista) > 1:
                    fonti_distinte = {item.get("fonte") for item in lista}
                    if len(fonti_distinte) > 1:
                        dettagli_confronto = " vs ".join([f"[{it.get('fonte')}]: {it.get('dettagli')}" for it in lista])
                        incongruenze.append({
                            "soggetto": f"{u} -> {v}",
                            "tipo": "Convergenza Multi-Atto / Possibile Discrepanza Quote",
                            "dettagli": f"Relazione attestata in molteplici documenti con formulazioni differenti: {dettagli_confronto}",
                            "fonti": list(fonti_distinte)
                        })
        except Exception as e:
            log.error(f"Errore calcolo incongruenze: {e}", exc_info=True)

        return incongruenze

    def trova_cicli(self) -> list[list[str]]:
        try:
            grafo_semplice = nx.DiGraph(self.grafo)
            cicli = list(nx.simple_cycles(grafo_semplice))
            return [c for c in cicli if len(c) > 1]
        except Exception as e:
            log.error(f"Errore calcolo cicli: {e}", exc_info=True)
            return []

    def rileva_schemi_investigativi_topologici(self) -> dict:
        """
        Riconoscimento automatico dei pattern topologici investigativi AML:
        1. Flussi Circolari (Ring / Round-Tripping)
        2. Hub & Dominus (Star / Nodi Cerniera)
        3. Catene di Controllo (Chain / Scatole Cinesi)
        4. Incongruenze Cross-Documentali (DocETL Resolve)
        """
        risultati = {
            "flussi_circolari": [],
            "hub_dominus": [],
            "scatole_cinesi": [],
            "incongruenze": self.trova_incongruenze_cross_documentali(),
        }

        if len(self.grafo.nodes) == 0:
            return risultati

        # 1. Rilevamento Cicli
        risultati["flussi_circolari"] = self.trova_cicli()

        # 2. Rilevamento Hub / Dominus
        degree_map = dict(self.grafo.degree())
        out_deg_map = dict(self.grafo.out_degree())
        in_deg_map = dict(self.grafo.in_degree())

        for nodo in self.grafo.nodes():
            deg = degree_map.get(nodo, 0)
            meta = self.dati_nodi.get(nodo, {})
            n_fonti = len(meta.get("fonti", set()))
            if deg >= 4 or (deg >= 3 and n_fonti >= 2):
                risultati["hub_dominus"].append({
                    "nodo": nodo,
                    "connessioni": deg,
                    "grado_totale": deg,
                    "flussi_uscenti": out_deg_map.get(nodo, 0),
                    "flussi_entranti": in_deg_map.get(nodo, 0),
                    "atti_coinvolti": n_fonti,
                    "tipo": meta.get("tipo", "ALTRO"),
                    "cf_piva": meta.get("cf_piva", "N/D"),
                })

        # 3. Rilevamento Catene Societarie (Chain)
        try:
            for nodo in self.grafo.nodes():
                succ = list(self.grafo.successors(nodo))
                for s in succ:
                    succ2 = list(self.grafo.successors(s))
                    for s2 in succ2:
                        if s2 != nodo:
                            risultati["scatole_cinesi"].append([nodo, s, s2])
        except Exception:
            pass

        return risultati

    def _risolvi_nome_per_ricerca(self, testo: str) -> str:
        """Risolve un nominativo o CF immesso dall'utente nel nodo effettivo del grafo."""
        if not testo:
            return ""
        testo_pulito = testo.strip()
        if self.grafo.has_node(testo_pulito):
            return testo_pulito
        if self.grafo.has_node(testo_pulito.upper()):
            return testo_pulito.upper()

        norm = self.normalizza_nome(testo_pulito)
        if norm in self.mappa_identita:
            return self.mappa_identita[norm]

        # Cerca corrispondenza su CF/PIVA
        for nodo, meta in self.dati_nodi.items():
            if meta.get("cf_piva") and meta.get("cf_piva").upper() == testo_pulito.upper():
                return nodo

        # Corrispondenza parziale / inclusione token
        up = testo_pulito.upper()
        for nodo in self.grafo.nodes():
            if up in nodo.upper() or nodo.upper() in up:
                return nodo

        parti_input = set(norm.split("_"))
        for nodo in self.grafo.nodes():
            parti_nodo = set(self.normalizza_nome(nodo).split("_"))
            if parti_input and len(parti_input) >= 2 and parti_input.issubset(parti_nodo):
                return nodo

        return ""

    def analizza_contatti(self, nome1: str, nome2: str) -> str:
        """
        Risolve deterministicamente il cammino minimo (shortest path) tra due soggetti
        all'interno della rete relazionale accumulata, specificando nodi e archi intermedi.
        """
        n1 = self._risolvi_nome_per_ricerca(nome1)
        n2 = self._risolvi_nome_per_ricerca(nome2)
        if not n1 or not n2:
            non_trovati = []
            if not n1:
                non_trovati.append(f"'{nome1}'")
            if not n2:
                non_trovati.append(f"'{nome2}'")
            return f"Verifica non possibile: {', '.join(non_trovati)} non risultano censiti nel fascicolo."

        try:
            cammino = nx.shortest_path(self.grafo.to_undirected(), source=n1, target=n2)
            etichette = [self.grafo.nodes[nodo].get("label", nodo) for nodo in cammino]
            risultato = [f"COLLEGAMENTO DETERMINISTICO RILEVATO: {' ➔ '.join(etichette)} (Distanza: {len(cammino)-1} gradi di separazione)"]

            for i in range(len(cammino) - 1):
                u, v = cammino[i], cammino[i + 1]
                data_uv = self.grafo.get_edge_data(u, v) or {}
                data_vu = self.grafo.get_edge_data(v, u) or {}

                dettagli_archi = []
                for _, e_data in data_uv.items():
                    val = e_data.get("valore_numerico", 0)
                    val_str = f" [€ {val:,.2f}]" if val else ""
                    fnt = e_data.get("fonte", "N/D")
                    lbl = e_data.get("label", "LEGAME")
                    det = e_data.get("dettagli", "")
                    dettagli_archi.append(f"{u} ➔ {lbl}{val_str} ➔ {v} ({det} | Fonte: {fnt})")

                for _, e_data in data_vu.items():
                    val = e_data.get("valore_numerico", 0)
                    val_str = f" [€ {val:,.2f}]" if val else ""
                    fnt = e_data.get("fonte", "N/D")
                    lbl = e_data.get("label", "LEGAME")
                    det = e_data.get("dettagli", "")
                    dettagli_archi.append(f"{v} ➔ {lbl}{val_str} ➔ {u} ({det} | Fonte: {fnt})")

                info_arco = "; ".join(dettagli_archi) if dettagli_archi else "Legame registrato"
                risultato.append(f"- Connessione tra '{u}' e '{v}': {info_arco}")

            return "\n".join(risultato)
        except nx.NetworkXNoPath:
            return f"Nessun contatto o collegamento (diretto o indiretto) riscontrato tra '{nome1}' e '{nome2}' negli atti analizzati."
        except Exception as e:
            return f"Errore durante l'analisi del cammino minimo: {e}"

    def calcola_partecipazioni(self, soggetto: str) -> str:
        """
        Calcola deterministicamente quote, partecipazioni, cariche sociali e legami
        in entrata e in uscita per il soggetto specificato.
        """
        s_id = self._risolvi_nome_per_ricerca(soggetto)
        if not s_id:
            return f"Soggetto '{soggetto}' non censito nel fascicolo."

        meta = self.dati_nodi.get(s_id, {})
        cf = meta.get("cf_piva", "N/D")
        tipo = meta.get("tipo", "ALTRO")

        risultato = [f"PARTECIPAZIONI, CARICHE E OPERAZIONI RILEVATE PER: {s_id} (Tipo: {tipo}, CF/PIVA: {cf}):"]
        trovato = False

        for _, dest, data in self.grafo.out_edges(s_id, data=True):
            tipo_rel = data.get("label", "LEGAME")
            dettagli = data.get("dettagli", "")
            valore = data.get("valore_numerico", 0)
            val_str = f" [€ {valore:,.2f}]" if valore else ""
            fonte = data.get("fonte", "N/D")
            azienda = self.grafo.nodes[dest].get("label", dest)
            risultato.append(f"- Incarico/Flusso: {tipo_rel} verso '{azienda}'{val_str} | Dettagli: {dettagli} (Fonte: {fonte})")
            trovato = True

        for src, _, data in self.grafo.in_edges(s_id, data=True):
            tipo_rel = data.get("label", "LEGAME")
            dettagli = data.get("dettagli", "")
            valore = data.get("valore_numerico", 0)
            val_str = f" [€ {valore:,.2f}]" if valore else ""
            fonte = data.get("fonte", "N/D")
            azienda = self.grafo.nodes[src].get("label", src)
            risultato.append(f"- Ricevuto da '{azienda}' come {tipo_rel}{val_str} | Dettagli: {dettagli} (Fonte: {fonte})")
            trovato = True

        return "\n".join(risultato) if trovato else f"Nessuna quota, incarico o transazione associata direttamente a '{soggetto}'."

    def ottieni_riassunto(self) -> str:
        """
        Genera un riassunto testuale sintetico e deterministico di tutte le relazioni censite nel grafo.
        """
        if len(self.grafo.edges) == 0:
            return "Nessuna relazione registrata nella rete."

        linee = ["--- RELAZIONI E RAPPORTI REGISTRATI NELLA RETE ---"]
        for u, v, data in self.grafo.edges(data=True):
            lu = self.grafo.nodes[u].get("label", u)
            lv = self.grafo.nodes[v].get("label", v)
            lbl = data.get("label", "LEGAME")
            det = data.get("dettagli", "")
            val = data.get("valore_numerico", 0)
            val_str = f" (€ {val:,.2f})" if val else ""
            fnt = data.get("fonte", "N/D")
            linee.append(f"{lu} ➔ [{lbl}{val_str}: {det}] ➔ {lv} (Fonte: {fnt})")

        return "\n".join(linee)

    def trova_convergenze_e_snodi(self) -> list[dict]:
        if len(self.grafo.nodes) == 0:
            return []

        snodi = []
        try:
            degree_map = dict(self.grafo.degree())
            in_degree_map = dict(self.grafo.in_degree())
            out_degree_map = dict(self.grafo.out_degree())

            for nodo in self.grafo.nodes():
                meta = self.dati_nodi.get(nodo, {})
                fonti = meta.get("fonti", set())
                ruoli = meta.get("ruoli", set())
                n_fonti = len(fonti)
                deg = degree_map.get(nodo, 0)
                in_deg = in_degree_map.get(nodo, 0)
                out_deg = out_degree_map.get(nodo, 0)

                ruolo_topologico = "Nodo Periferico"
                if n_fonti > 1 and deg >= 3:
                    ruolo_topologico = "🌟 Snodo Chiave (Dominus / Ponte Multi-Atto)"
                elif deg >= 4 and out_deg >= 3:
                    ruolo_topologico = "📤 Sorgente Principale di Flussi / Quote"
                elif deg >= 4 and in_deg >= 3:
                    ruolo_topologico = "📥 Terminale di Convergenza Finanziaria"
                elif n_fonti > 1:
                    ruolo_topologico = "🔗 Soggetto Ricorrente su Più Atti"

                snodi.append({
                    "id": nodo,
                    "soggetto": nodo,
                    "tipo": meta.get("tipo", "ALTRO"),
                    "cf_piva": meta.get("cf_piva") or "N/D",
                    "grado": deg,
                    "in_degree": in_deg,
                    "in_entrata": in_deg,
                    "out_degree": out_deg,
                    "in_uscita": out_deg,
                    "num_atti": n_fonti,
                    "atti_coinvolti": n_fonti,
                    "ruolo_topologico": ruolo_topologico,
                    "ruolo_investigativo": ruolo_topologico,
                    "atti": list(fonti),
                    "fonti": list(fonti),
                    "ruoli_rilevati": list(ruoli),
                })

            snodi.sort(key=lambda x: (x["atti_coinvolti"], x["grado"]), reverse=True)
        except Exception as e:
            log.error(f"Errore calcolo convergenze: {e}", exc_info=True)

        return snodi

    def ottieni_timeline_forense(self) -> list[dict]:
        """Restituisce la timeline ordinata cronologicamente (Timesketch-inspired)"""
        eventi_con_data = []
        eventi_senza_data = []

        for ev in self.eventi_timeline:
            d_str = ev.get("data", "")
            if d_str and d_str != "Data non specificata":
                eventi_con_data.append(ev)
            else:
                eventi_senza_data.append(ev)

        # Ordina gli eventi con data
        def chiave_data(ev):
            m = re.search(r"(\d{4})", ev.get("data", ""))
            return int(m.group(1)) if m else 0

        eventi_con_data.sort(key=chiave_data, reverse=True)
        return eventi_con_data + eventi_senza_data

    def dati_vis(self) -> dict:
        """Nodi e archi per vis-network (disegnati dall'interfaccia, nessuna risorsa esterna)."""
        nodi, archi = [], []
        for node_id, data in self.grafo.nodes(data=True):
            meta = self.dati_nodi.get(node_id, {})
            ha_cf = bool(meta.get("cf_piva"))
            n_fonti = len(meta.get("fonti", set()))
            nodi.append({
                "id": node_id,
                "label": data.get("label", node_id),
                "tipo": meta.get("tipo") or data.get("tipo", "ALTRO"),
                "cf_piva": meta.get("cf_piva") or data.get("cf_piva", ""),
                "fonti": sorted(meta.get("fonti", set())),
                "size": 30 if (ha_cf and n_fonti > 1) else (24 if ha_cf else 18),
            })
        for i, (u, v, data) in enumerate(self.grafo.edges(data=True)):
            val = data.get("valore_numerico") or 0
            try:
                val = float(val)
            except (TypeError, ValueError):
                val = 0.0
            archi.append({
                "id": i, "from": u, "to": v,
                "label": data.get("label", "LEGAME") + (f" · €{val:,.0f}".replace(",", ".") if val else ""),
                "dettagli": data.get("dettagli", ""), "fonte": data.get("fonte", ""),
                "valore": val,
            })
        return {"nodi": nodi, "archi": archi}

    def esporta_mermaid(self, orientamento: str = "TD") -> str:
        """
        Esporta l'intera rete investigativa in un diagramma Mermaid formattato e pronto all'uso.
        Supporta orientamento 'TD' (verticale) o 'LR' (orizzontale).
        """
        if len(self.grafo.nodes) == 0:
            return f"flowchart {orientamento}\n    empty[\"Nessuna entità censita nel fascicolo\"]"

        linee = [f"flowchart {orientamento}"]

        # Mappa ID univoci sicuri per sintassi Mermaid
        mappa_id = {}
        for idx, (nodo_id, _) in enumerate(self.grafo.nodes(data=True), start=1):
            mappa_id[nodo_id] = f"n{idx}"

        # 1. Raggruppamento per Sottografi Ontologici
        gruppi = {
            "PERSONA": ("Persone Fisiche", []),
            "SOCIETA": ("Società ed Enti", []),
            "CONTO": ("Rapporti Bancari / IBAN", []),
            "ASSET": ("Asset e Beni Patrimoniali", []),
            "ALTRO": ("Altre Entità", []),
        }

        for nodo_id, data in self.grafo.nodes(data=True):
            meta = self.dati_nodi.get(nodo_id, {})
            tipo = meta.get("tipo") or data.get("tipo", "ALTRO")
            cf_piva = meta.get("cf_piva") or data.get("cf_piva", "")
            m_id = mappa_id[nodo_id]

            label_san = nodo_id.replace('"', "'").replace("\n", " ")
            cf_str = f"<br/><i>CF: {cf_piva}</i>" if cf_piva else ""
            nodo_def = f'{m_id}["{label_san}{cf_str}"]'

            categoria = tipo if tipo in gruppi else "ALTRO"
            gruppi[categoria][1].append(nodo_def)

        for cat, (titolo, nodi_def) in gruppi.items():
            if nodi_def:
                linee.append(f"\n    subgraph sub_{cat} [\"{titolo}\"]")
                for nd in nodi_def:
                    linee.append(f"        {nd}")
                linee.append("    end")

        # 2. Archi e Flussi di denaro
        linee.append("\n    %% Relazioni, partecipazioni e flussi finanziari")
        for u, v, data in self.grafo.edges(data=True):
            src_id = mappa_id.get(u)
            dst_id = mappa_id.get(v)
            if not src_id or not dst_id:
                continue

            tipo_rel = data.get("label", "LEGAME").replace('"', "'")
            valore = data.get("valore_numerico", 0)
            data_ev = data.get("data_evento", "")

            extra = []
            if valore:
                extra.append(f"€{valore:,.0f}")
            if data_ev:
                extra.append(data_ev)

            extra_str = f" ({', '.join(extra)})" if extra else ""
            linee.append(f'    {src_id} -->|"{tipo_rel}{extra_str}"| {dst_id}')

        # 3. Stili Visuali Apple Material Dark
        linee.append("\n    %% Stili grafici per categoria")
        linee.append("    classDef persona fill:#0A84FF,stroke:#0051A8,color:#FFFFFF,stroke-width:2px;")
        linee.append("    classDef societa fill:#30D158,stroke:#1C8237,color:#FFFFFF,stroke-width:2px;")
        linee.append("    classDef conto fill:#FF9F0A,stroke:#B26200,color:#FFFFFF,stroke-width:2px;")
        linee.append("    classDef asset fill:#BF5AF2,stroke:#7726A5,color:#FFFFFF,stroke-width:2px;")
        linee.append("    classDef altro fill:#8E8E93,stroke:#555558,color:#FFFFFF,stroke-width:1px;")

        for nodo_id, data in self.grafo.nodes(data=True):
            meta = self.dati_nodi.get(nodo_id, {})
            tipo = meta.get("tipo") or data.get("tipo", "ALTRO")
            m_id = mappa_id[nodo_id]
            classe = {
                "PERSONA": "persona",
                "SOCIETA": "societa",
                "CONTO": "conto",
                "ASSET": "asset",
            }.get(tipo, "altro")
            linee.append(f"    class {m_id} {classe};")

        return "\n".join(linee)

    def calcola_metriche_centralita_forense(self) -> list[dict]:
        """
        Algoritmo di Centralità Topologica NetworkX (ispirato ai motori di link analysis tipo Maltego/Palantir):
        - Betweenness Centrality: identifica i nodi "ponte" strategici o i Dominus occulti che collegano cluster altrimenti separati.
        - In-Degree / Out-Degree: distingue le cartiere (outflow massivo) dalle casseforti patrimoniali (inflow massivo).
        - PageRank: misura l'autorevolezza e l'influenza relazionale nella rete.
        """
        if len(self.grafo.nodes) == 0:
            return []

        try:
            grafo_semplice = nx.DiGraph(self.grafo)
            betweenness = nx.betweenness_centrality(grafo_semplice, normalized=True)
            degree = dict(self.grafo.degree())
            in_deg = dict(self.grafo.in_degree())
            out_deg = dict(self.grafo.out_degree())
            try:
                pagerank = nx.pagerank(grafo_semplice, alpha=0.85, max_iter=200)
            except Exception:
                pagerank = {n: 0.0 for n in self.grafo.nodes}

            risultati = []
            for n in self.grafo.nodes():
                meta = self.dati_nodi.get(n, {})
                tipo = meta.get("tipo", "ALTRO")
                cf = meta.get("cf_piva", "N/D")
                fonti = meta.get("fonti", set())
                bw = betweenness.get(n, 0.0)
                pr = pagerank.get(n, 0.0)
                tot_d = degree.get(n, 0)
                i_d = in_deg.get(n, 0)
                o_d = out_deg.get(n, 0)

                # Classificazione Forense
                if bw >= 0.15 or (tot_d >= 5 and len(fonti) >= 2):
                    profilo = "👑 DOMINUS / SNODO STRATEGICO"
                elif o_d >= 3 and i_d <= 1:
                    profilo = "📤 CARTIERA / ORIGINATORE FLUSSI"
                elif i_d >= 3 and o_d <= 1:
                    profilo = "📥 CASSAFORTE / TERMINALE"
                elif len(fonti) >= 2 and tot_d >= 2:
                    profilo = "🔗 INTERPOSTO / CONNETTORE MULTI-ATTO"
                else:
                    profilo = "SOGGETTO OPERATIVO"

                risultati.append({
                    "nodo": n,
                    "tipo": tipo,
                    "cf_piva": cf,
                    "betweenness": bw,
                    "pagerank": pr,
                    "grado_totale": tot_d,
                    "in_degree": i_d,
                    "out_degree": o_d,
                    "num_atti": len(fonti),
                    "fonti": sorted(list(fonti)),
                    "profilo_forense": profilo,
                })

            risultati.sort(key=lambda x: (x["betweenness"], x["grado_totale"], x["num_atti"]), reverse=True)
            return risultati
        except Exception as e:
            log.error(f"Errore calcolo centralità forense: {e}", exc_info=True)
            return []

    def calcola_matrice_riconciliazione_finanziaria(self) -> list[dict]:
        """
        Motore di Riconciliazione Finanziaria OLAP in DuckDB:
        Calcola per ciascun soggetto il totale dei fondi in entrata (ricevuti),
        il totale dei fondi in uscita (bonificati/ceduti), il saldo netto tracciato,
        il numero di operazioni e gli atti di riferimento.
        """
        try:
            query = """
            WITH entrate AS (
                SELECT destinazione as soggetto, SUM(valore_numerico) as tot_entrata, COUNT(*) as num_in
                FROM relazioni
                WHERE valore_numerico > 0
                GROUP BY destinazione
            ),
            uscite AS (
                SELECT sorgente as soggetto, SUM(valore_numerico) as tot_uscita, COUNT(*) as num_out
                FROM relazioni
                WHERE valore_numerico > 0
                GROUP BY sorgente
            ),
            unione AS (
                SELECT soggetto FROM entrate
                UNION
                SELECT soggetto FROM uscite
            )
            SELECT 
                u.soggetto,
                COALESCE(e.tot_entrata, 0.0) as entrate_euro,
                COALESCE(s.tot_uscita, 0.0) as uscite_euro,
                (COALESCE(e.tot_entrata, 0.0) - COALESCE(s.tot_uscita, 0.0)) as sbilancio_netto_euro,
                COALESCE(e.num_in, 0) as n_operazioni_in,
                COALESCE(s.num_out, 0) as n_operazioni_out
            FROM unione u
            LEFT JOIN entrate e ON u.soggetto = e.soggetto
            LEFT JOIN uscite s ON u.soggetto = s.soggetto
            ORDER BY (COALESCE(e.tot_entrata, 0.0) + COALESCE(s.tot_uscita, 0.0)) DESC
            """
            df = self.db.execute(query).fetchdf()
            records = df.to_dict(orient="records")
            for r in records:
                s_id = r["soggetto"]
                meta = self.dati_nodi.get(s_id, {})
                r["tipo"] = meta.get("tipo", "ALTRO")
                r["cf_piva"] = meta.get("cf_piva", "N/D")
                r["fonti"] = sorted(list(meta.get("fonti", set())))
            return records
        except Exception as e:
            log.error(f"Errore riconciliazione finanziaria DuckDB: {e}", exc_info=True)
            return []

    def trova_soggetti_trasversali(self) -> list[dict]:
        """
        Identifica i soggetti presenti in 2 o più atti documentali distinti.
        Rappresentano la matrice di convergenza probatoria e il collante dell'inchiesta.
        """
        trasversali = []
        for n, meta in self.dati_nodi.items():
            fonti = meta.get("fonti", set())
            if len(fonti) >= 2:
                ruoli_per_atto = {}
                for u, v, data in self.grafo.edges(data=True):
                    fnt = data.get("fonte", "")
                    if u == n:
                        ruoli_per_atto.setdefault(fnt, []).append(f"Dispone {data.get('label')} verso {v}")
                    if v == n:
                        ruoli_per_atto.setdefault(fnt, []).append(f"Riceve {data.get('label')} da {u}")

                trasversali.append({
                    "soggetto": n,
                    "tipo": meta.get("tipo", "ALTRO"),
                    "cf_piva": meta.get("cf_piva", "N/D"),
                    "num_atti": len(fonti),
                    "atti": sorted(list(fonti)),
                    "ruoli_dettaglio": ruoli_per_atto,
                    "grado": self.grafo.degree(n),
                })
        trasversali.sort(key=lambda x: (x["num_atti"], x["grado"]), reverse=True)
        return trasversali

    def costruisci_quadro_globale_per_llm(self) -> str:
        """
        Genera una Matrice Computazionale Forense approfondita per l'LLM,
        estraendo da DuckDB, NetworkX e FollowTheMoney tutte le metriche,
        le anagrafiche trasversali, i titolari effettivi, i flussi di denaro e le incongruenze.
        """
        if len(self.grafo.nodes) == 0:
            return "Nessuna entità o relazione rilevata nel fascicolo."

        righe = []
        tot_nodi = len(self.grafo.nodes)
        tot_archi = len(self.grafo.edges)
        righe.append(f"METRICHE COMPUTAZIONALI DEL FASCICOLO: {tot_nodi} Entità Univoche, {tot_archi} Relazioni/Transazioni, {len(self.file_fonti)} Atti Acquisiti.")

        # 1. Volume Finanziario Complessivo tracciato con DuckDB
        try:
            res_vol = self.db.execute("SELECT SUM(valore_numerico) as tot_euro, COUNT(*) as n_trans FROM relazioni WHERE valore_numerico > 0").fetchall()
            if res_vol and res_vol[0][0]:
                tot_euro = res_vol[0][0]
                n_tr = res_vol[0][1]
                righe.append(f"VOLUME FINANZIARIO COMPLESSIVO TRACCIATO: € {tot_euro:,.2f} (in {n_tr} operazioni con importo documentato).")
        except Exception:
            pass

        # 2. Matrice Soggetti Trasversali (presenti in più atti)
        trasversali = self.trova_soggetti_trasversali()
        if trasversali:
            righe.append(f"\n=======================================================")
            righe.append(f"MATRICE DI CONVERGENZA MULTI-ATTO (Soggetti presenti in 2 o più atti distinti):")
            righe.append(f"=======================================================")
            for t in trasversali[:12]:
                f_list = ", ".join(t["atti"])
                righe.append(f"• {t['soggetto']} ({t['tipo']}, CF: {t['cf_piva']}) — CENSITO IN {t['num_atti']} ATTI: [{f_list}] (Grado connessione: {t['grado']})")
                for f_name, r_list in t["ruoli_dettaglio"].items():
                    righe.append(f"    - In atto '{f_name}': {'; '.join(r_list[:3])}")

        # 3. Risultanze Algoritmo Centralità NetworkX (Dominus vs Cartiere vs Terminali)
        centralita = self.calcola_metriche_centralita_forense()
        top_dominus = [c for c in centralita if "DOMINUS" in c["profilo_forense"] or c["betweenness"] > 0.05]
        if top_dominus:
            righe.append(f"\n=======================================================")
            righe.append(f"ANALISI TOPOLOGICA DOMINUS & SNODI STRATEGICI (NetworkX Betweenness Centrality):")
            righe.append(f"=======================================================")
            for d in top_dominus[:8]:
                righe.append(f"• {d['nodo']} ({d['tipo']}, CF: {d['cf_piva']}): Classificazione = {d['profilo_forense']} (Betweenness: {d['betweenness']:.3f}, Flussi In: {d['in_degree']}, Flussi Out: {d['out_degree']}, Presente in {d['num_atti']} atti)")

        # 4. Titolari Effettivi (UBO) e Assetti di Controllo (FollowTheMoney OCCRP)
        try:
            ubos = self.ftm_dataset.risolvi_titolari_effettivi()
            aziende_con_dati = [u for u in ubos if u["titolari_effettivi"] or u["amministratori"]]
            if aziende_con_dati:
                righe.append(f"\n=======================================================")
                righe.append(f"TITOLARI EFFETTIVI E ASSETTO DI CONTROLLO SOCIETARIO (FollowTheMoney OCCRP):")
                righe.append(f"=======================================================")
                for u in aziende_con_dati[:8]:
                    righe.append(f"• Società: {u['azienda']} (P.IVA/CF: {u['cf_piva']}):")
                    for te in u["titolari_effettivi"]:
                        catena_str = " -> ".join(te["catena"])
                        righe.append(f"    - Titolare Effettivo / Socio: {te['persona']} (CF: {te['cf']}) | {te['ruolo']} {te['percentuale']} [Catena: {catena_str}]")
                    for am in u["amministratori"]:
                        righe.append(f"    - Rappresentanza / Governance: {am['nominativo']} (CF: {am['cf']}) | Ruolo: {am['ruolo']}")
        except Exception as e:
            log.debug(f"Errore UBO per LLM: {e}")

        # 5. Riconciliazione Partite e Flussi Finanziari (DuckDB Ledger)
        matrice_fin = self.calcola_matrice_riconciliazione_finanziaria()
        if matrice_fin:
            righe.append(f"\n=======================================================")
            righe.append(f"MATRICE RICONCILIAZIONE FINANZIARIA PER SOGGETTO (DuckDB OLAP):")
            righe.append(f"=======================================================")
            for mf in matrice_fin[:12]:
                if mf['entrate_euro'] > 0 or mf['uscite_euro'] > 0:
                    righe.append(f"• {mf['soggetto']} ({mf['tipo']}): Ricevuti € {mf['entrate_euro']:,.2f} ({mf['n_operazioni_in']} op.) | Disposti € {mf['uscite_euro']:,.2f} ({mf['n_operazioni_out']} op.) | Saldo Netto Tracciato: € {mf['sbilancio_netto_euro']:,.2f}")

        # 6. Flussi Circolari e Pattern di Riciclaggio
        schemi = self.rileva_schemi_investigativi_topologici()
        if schemi["flussi_circolari"]:
            righe.append(f"\n=======================================================")
            righe.append(f"🚨 ALLERTA RICICLAGGIO: RILEVATI {len(schemi['flussi_circolari'])} FLUSSI CIRCOLARI (ROUND-TRIPPING):")
            righe.append(f"=======================================================")
            for c in schemi["flussi_circolari"]:
                righe.append(f"  * {' ➔ '.join(c)} ➔ {c[0]}")

        if schemi["scatole_cinesi"]:
            catene_uniche = []
            viste = set()
            for c in schemi["scatole_cinesi"]:
                tup = tuple(c)
                if tup not in viste:
                    viste.add(tup)
                    catene_uniche.append(c)
            righe.append(f"\n🏢 CATENE SOCIETARIE A SCHERMO / SCATOLE CINESI: {len(catene_uniche)} livelli rilevati:")
            for cat in catene_uniche[:8]:
                righe.append(f"  * {' ➔ '.join(cat)}")

        # 7. Incongruenze e Contraddizioni tra Atti Diversi
        if schemi["incongruenze"]:
            righe.append(f"\n=======================================================")
            righe.append(f"⚠️ CONTRADDIZIONI E DISCREPANZE RILEVATE TRA ATTI DIVERSI:")
            righe.append(f"=======================================================")
            for inc in schemi["incongruenze"][:10]:
                righe.append(f"  * [{inc['tipo']}] {inc['soggetto']}: {inc['dettagli']} (Fonti: {', '.join(inc['fonti'])})")

        # 8. Transazioni e Movimentazioni Bancarie Puntuali (DuckDB)
        try:
            res_rel = self.db.execute("""
                SELECT sorgente, tipo, destinazione, valore_numerico, data_evento, dettagli, fonte
                FROM relazioni
                ORDER BY valore_numerico DESC, id ASC
                LIMIT 40
            """).fetchall()

            if res_rel:
                righe.append(f"\n=======================================================")
                righe.append(f"REGISTRO MOVIMENTAZIONI E TRANSAZIONI DOCUMENTATE (DuckDB):")
                righe.append(f"=======================================================")
                for r in res_rel:
                    src, tip, dst, val, data_ev, dett, fnt = r
                    val_str = f" [€ {val:,.2f}]" if val and val > 0 else ""
                    dt_str = f" in data {data_ev}" if data_ev else ""
                    righe.append(f"- {src} --[{tip}{val_str}{dt_str}]--> {dst} | Note: {dett} (Fonte: {fnt})")
        except Exception as e:
            log.debug(f"Errore query relazioni per LLM: {e}")

        return "\n".join(righe)

    def esporta_followthemoney_jsonl(self) -> str:
        """
        Esporta l'intero grafo forense nello standard internazionale FollowTheMoney (OCCRP Aleph).
        Formato: JSON-Lines con 'id', 'schema' e 'properties'.
        """
        if self.ftm_dataset and len(self.ftm_dataset.entita) > 0:
            return self.ftm_dataset.esporta_json_lines()

        # Fallback di serializzazione se il dataset nativo non fosse popolato
        linee = []
        for node_id, data in self.grafo.nodes(data=True):
            meta = self.dati_nodi.get(node_id, {})
            ftm_schema = meta.get("ftm_schema", "LegalEntity")
            cf_piva = meta.get("cf_piva", "")
            ent_ftm = {
                "id": f"ftm_{re.sub(r'[^a-zA-Z0-9_]', '_', node_id)}",
                "schema": ftm_schema,
                "caption": node_id,
                "properties": {"name": [node_id]}
            }
            if cf_piva:
                ent_ftm["properties"]["taxNumber"] = [cf_piva]
            linee.append(json.dumps(ent_ftm, ensure_ascii=False))
        return "\n".join(linee)

    def statistiche_ftm(self) -> dict:
        return self.ftm_dataset.statistiche()

    def esporta_progetto_pdf_relations(self) -> dict:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        map_tipo = {
            "PERSONA": "PERSON",
            "SOCIETA": "COMPANY",
            "CONTO": "ACCOUNT",
            "ASSET": "OTHER",
            "ALTRO": "OTHER",
        }

        nodes_list = []
        for node_id, data in self.grafo.nodes(data=True):
            meta = self.dati_nodi.get(node_id, {})
            tipo_orig = meta.get("tipo") or data.get("tipo", "ALTRO")
            tipo_pdf = map_tipo.get(tipo_orig, "OTHER")
            cf_piva = meta.get("cf_piva") or data.get("cf_piva", "")
            fonti = meta.get("fonti") or {data.get("fonte", "")}

            nodes_list.append({
                "id": node_id,
                "label": node_id,
                "type": tipo_pdf,
                "normalized_label": node_id.lower(),
                "identifiers": {
                    "cf": cf_piva if len(cf_piva) == 16 else "",
                    "piva": cf_piva if len(cf_piva) == 11 else "",
                    "raw": cf_piva,
                },
                "sources": list(fonti) if fonti else list(self.file_fonti),
                "confidence": 0.98,
            })

        edges_list = []
        edge_idx = 1
        for u, v, data in self.grafo.edges(data=True):
            tipo_rel = data.get("label", "LEGAME")
            dettagli = data.get("dettagli", "")
            fonte = data.get("fonte", "")

            edges_list.append({
                "id": f"e_{edge_idx}",
                "source": u,
                "target": v,
                "relation_type": tipo_rel,
                "label": tipo_rel,
                "fact_level": "FACT",
                "confidence": 0.98,
                "evidence": [
                    {
                        "document_id": fonte,
                        "file_name": fonte,
                        "page": 1,
                        "quote": dettagli,
                        "extractor": "Forensic AI Offline Suite",
                    }
                ],
            })
            edge_idx += 1

        return {
            "app": "Relazioni PDF",
            "version": 1,
            "savedAt": now,
            "data": {
                "sessionId": f"forensic_{int(datetime.datetime.now().timestamp())}",
                "nodes": nodes_list,
                "edges": edges_list,
                "stats": {
                    "nodes": len(nodes_list),
                    "edges": len(edges_list),
                },
                "mermaid": "",
                "debug": {
                    "origin": "Forensics AI Offline Advanced Multi-Document Suite",
                    "sources": list(self.file_fonti),
                },
            },
        }

    def esporta_stato(self) -> dict:
        return {
            "file_fonti": list(self.file_fonti),
            "mappa_identita": self.mappa_identita,
            "dati_nodi": {
                k: {
                    "tipo": v.get("tipo"),
                    "cf_piva": v.get("cf_piva"),
                    "ftm_schema": v.get("ftm_schema"),
                    "fonti": list(v.get("fonti", [])),
                    "ruoli": list(v.get("ruoli", [])),
                }
                for k, v in self.dati_nodi.items()
            },
            "eventi_timeline": self.eventi_timeline,
            "nodi": [
                {"id": n, "data": d}
                for n, d in self.grafo.nodes(data=True)
            ],
            "archi": [
                {"sorgente": u, "destinazione": v, "data": d}
                for u, v, d in self.grafo.edges(data=True)
            ],
        }

    def importa_stato(self, dati_stato: dict):
        self.grafo.clear()
        self.file_fonti = set(dati_stato.get("file_fonti", []))
        self.mappa_identita = dati_stato.get("mappa_identita", {})
        self.eventi_timeline = dati_stato.get("eventi_timeline", [])
        self.dati_nodi = {}

        for k, v in dati_stato.get("dati_nodi", {}).items():
            self.dati_nodi[k] = {
                "tipo": v.get("tipo"),
                "cf_piva": v.get("cf_piva"),
                "ftm_schema": v.get("ftm_schema", "LegalEntity"),
                "fonti": set(v.get("fonti", [])),
                "ruoli": set(v.get("ruoli", [])),
            }

        for n in dati_stato.get("nodi", []):
            self.grafo.add_node(n["id"], **n.get("data", {}))

        for e in dati_stato.get("archi", []):
            self.grafo.add_edge(e["sorgente"], e["destinazione"], **e.get("data", {}))

        self._sincronizza_duckdb()

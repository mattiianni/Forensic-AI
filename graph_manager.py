import datetime
import json
import re
import duckdb
import networkx as nx
from pyvis.network import Network
from logger import log
from ftm_engine import FollowTheMoneyDataset


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

    def genera_html_mappa(self, file_path: str = "grafo.html", altezza: str = "850px") -> str:
        return self.esporta_grafo_html(file_path, altezza=altezza)

    def esporta_grafo_html(self, file_path: str = "grafo.html", altezza: str = "850px") -> str:
        net = Network(height=altezza, width="100%", bgcolor="#0d1117", font_color="#FFFFFF", directed=True)
        net.force_atlas_2based(
            gravity=-120,
            central_gravity=0.015,
            spring_length=240,
            spring_strength=0.07,
            damping=0.5,
        )

        for node_id, data in self.grafo.nodes(data=True):
            meta = self.dati_nodi.get(node_id, {})
            ha_cf = bool(meta.get("cf_piva"))
            n_fonti = len(meta.get("fonti", set()))
            
            # Dimensione proporzionale all'importanza
            nodo_size = 36 if (ha_cf and n_fonti > 1) else (30 if ha_cf else 22)
            
            net.add_node(
                node_id,
                label=data.get("label", node_id),
                title=data.get("title", node_id),
                color=data.get("color", "#8E8E93"),
                size=nodo_size,
                font={"color": "#FFFFFF", "size": 15, "face": "SF Pro Display, -apple-system, sans-serif"},
                borderWidth=2,
            )

        for u, v, data in self.grafo.edges(data=True):
            val = data.get("valore_numerico", 0)
            val_label = f" [€{val:,.0f}]" if val else ""
            label_arco = f"{data.get('label', 'LEGAME')}{val_label}"
            
            net.add_edge(
                u,
                v,
                label=label_arco,
                title=data.get("title", ""),
                color={"color": "#58a6ff", "highlight": "#38bdf8"},
                arrows={"to": {"enabled": True, "scaleFactor": 1.2}},
                font={"color": "#8b949e", "size": 11, "align": "middle"},
                width=2 if val > 0 else 1,
            )

        # Attiva pulsanti di navigazione Vis.js (Zoom +, Zoom -, Reset, Frecce)
        net.set_options("""
        var options = {
            "interaction": {
                "navigationButtons": true,
                "keyboard": true,
                "zoomView": true,
                "hover": true
            },
            "physics": {
                "stabilization": {
                    "enabled": true,
                    "iterations": 180
                }
            }
        }
        """)

        net.save_graph(file_path)
        return file_path

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

    def costruisci_quadro_globale_per_llm(self) -> str:
        """
        Genera una Matrice Computazionale Forense approfondita per l'LLM,
        estraendo da DuckDB e NetworkX tutte le cifre, le anagrafiche, i flussi di denaro e le incongruenze.
        """
        if len(self.grafo.nodes) == 0:
            return "Nessuna entità o relazione rilevata nel fascicolo."

        righe = []
        tot_nodi = len(self.grafo.nodes)
        tot_archi = len(self.grafo.edges)
        righe.append(f"METRICHE GRAFO: {tot_nodi} Entità Univoche, {tot_archi} Relazioni/Transazioni, {len(self.file_fonti)} Atti Documentali Acquisiti.")

        # 1. Calcolo Volume Finanziario Complessivo tracciato con DuckDB
        try:
            res_vol = self.db.execute("SELECT SUM(valore_numerico) as tot_euro, COUNT(*) as n_trans FROM relazioni WHERE valore_numerico > 0").fetchall()
            if res_vol and res_vol[0][0]:
                tot_euro = res_vol[0][0]
                n_tr = res_vol[0][1]
                righe.append(f"VOLUME FINANZIARIO COMPLESSIVO TRACCIATO: € {tot_euro:,.2f} (in {n_tr} operazioni con importo certo).")
        except Exception:
            pass

        # 2. Soggetti Chiave, Dominus e Prestanome (Ordinati per grado e trasversalità)
        snodi = self.trova_convergenze_e_snodi()
        if snodi:
            righe.append("\nSOGGETTI CHIAVE E RUOLI STRATEGICI TRA GLI ATTI:")
            for s in snodi[:12]:
                fonti_str = ", ".join(s["fonti"])
                ruoli_str = "; ".join(s.get("ruoli_rilevati", []))[:120]
                righe.append(f"- {s['soggetto']} (Tipo: {s['tipo']}, CF/PIVA: {s['cf_piva']}): {s['ruolo_topologico']}. Presente in {s['atti_coinvolti']} atti distinti ({fonti_str}). Ruoli emersi: [{ruoli_str}].")

        # 3. Flussi Circolari e Pattern di Riciclaggio
        schemi = self.rileva_schemi_investigativi_topologici()
        if schemi["flussi_circolari"]:
            righe.append(f"\n🚨 ALLERTA AML: RILEVATI {len(schemi['flussi_circolari'])} FLUSSI CIRCOLARI / ROUND-TRIPPING (RING):")
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
            righe.append(f"\n🏢 HOLDING E SCATOLE CINESI (CHAIN): {len(catene_uniche)} catene di controllo a più livelli:")
            for cat in catene_uniche[:8]:
                righe.append(f"  * {' ➔ '.join(cat)}")

        # 4. Incongruenze e Contraddizioni Probatone
        if schemi["incongruenze"]:
            righe.append(f"\n⚠️ INCONGRUENZE E CONFLITTI DI RUOLO RILEVATI TRA ATTI DIVERSI:")
            for inc in schemi["incongruenze"][:8]:
                righe.append(f"  * [{inc['tipo']}] {inc['soggetto']}: {inc['dettagli']} (Fonti: {', '.join(inc['fonti'])})")

        # 5. Tabella Completa Transazioni e Rapporti Economici estratti con DuckDB
        try:
            res_rel = self.db.execute("""
                SELECT sorgente, tipo, destinazione, valore_numerico, data_evento, dettagli, fonte
                FROM relazioni
                ORDER BY valore_numerico DESC, id ASC
                LIMIT 40
            """).fetchall()

            if res_rel:
                righe.append("\nTRANSAZIONI, BONIFICI E RAPPORTI GIURIDICI SALIENTI (Rilevati dai documenti):")
                for r in res_rel:
                    src, tip, dst, val, data_ev, dett, fnt = r
                    val_str = f" [€ {val:,.2f}]" if val and val > 0 else ""
                    dt_str = f" in data {data_ev}" if data_ev else ""
                    righe.append(f"- {src} --[{tip}{val_str}{dt_str}]--> {dst} | Rif: {dett} (Fonte: {fnt})")
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

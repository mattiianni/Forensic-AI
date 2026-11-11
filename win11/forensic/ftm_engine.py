import hashlib
import json
import re
from typing import Any, Dict, List, Optional
from forensic.logger import log


class FtMEntity:
    """
    Rappresenta un'entità conforme allo standard OCCRP FollowTheMoney (FtM).
    Ogni entità ha un identificatore univoco, uno schema ontologico e una mappa di proprietà.
    """

    def __init__(self, entity_id: str, schema: str):
        self.id = self._sanitizza_id(entity_id)
        self.schema = schema
        self.properties: Dict[str, List[str]] = {}
        self.fonti: List[str] = []

    def _sanitizza_id(self, raw_id: str) -> str:
        pulito = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", str(raw_id).strip())
        return pulito or f"ftm_{hashlib.md5(str(raw_id).encode()).hexdigest()[:12]}"

    def add(self, prop_name: str, value: Any):
        if value is None:
            return
        val_str = str(value).strip()
        if not val_str or val_str.upper() in {"N/D", "NONE", "NULL"}:
            return

        if prop_name not in self.properties:
            self.properties[prop_name] = []
        if val_str not in self.properties[prop_name]:
            self.properties[prop_name].append(val_str)

    def get_first(self, prop_name: str, default: str = "") -> str:
        vals = self.properties.get(prop_name, [])
        return vals[0] if vals else default

    def to_dict(self) -> dict:
        caption = (
            self.get_first("name")
            or self.get_first("accountNumber")
            or self.get_first("role")
            or self.id
        )
        data = {
            "id": self.id,
            "schema": self.schema,
            "caption": caption,
            "properties": self.properties,
        }
        if self.fonti:
            data["fonti"] = list(set(self.fonti))
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class FollowTheMoneyDataset:
    """
    Motore Dati ed Investigativo conforme all'ontologia OCCRP FollowTheMoney (FtM).
    Gestisce la creazione, validazione, tracciabilità e interrogazione delle entità
    e delle relazioni finanziarie (Ownership, Directorship, Payment, Family).
    """

    SCHEMI_SUPPORTATI = {
        # Entità Principali
        "Person": "Persona Fisica (socio, amministratore, beneficiario, prestanome)",
        "Company": "Società / Ente Giuridico (SRL, SPA, estera, fiduciaria)",
        "BankAccount": "Rapporto Bancario / Conto Corrente / IBAN",
        "RealEstate": "Bene Immobile / Asset Patrimoniale",
        "LegalEntity": "Soggetto Giuridico Generico",
        # Relazioni FtM
        "Ownership": "Partecipazione Societaria / Quote / Azioni",
        "Directorship": "Carica Direttiva / Amministrazione / Rappresentanza",
        "Payment": "Flusso Finanziario / Bonifico / Pagamento",
        "Family": "Legame di Parentela / Coniugio",
        "UnknownLink": "Legame o Relazione Generica",
    }

    def __init__(self, nome_dataset: str = "Indagine Forense"):
        self.nome_dataset = nome_dataset
        self.entita: Dict[str, FtMEntity] = {}
        self.alias_to_id: Dict[str, str] = {}
        self._contatore_relazioni = 1
        log.info(f"Motore FollowTheMoney (OCCRP standard) attivato per '{nome_dataset}'")

    def genera_id(self, prefisso: str, *componenti: str) -> str:
        raw = "_".join(str(c).strip().upper() for c in componenti if c)
        slug = re.sub(r"[^A-Za-z0-9_]", "_", raw)
        if len(slug) > 60:
            slug = hashlib.md5(slug.encode("utf-8")).hexdigest()[:16]
        return f"{prefisso}_{slug}" if slug else f"{prefisso}_{self._contatore_relazioni}"

    def crea_o_aggiorna_entita(self, entity_id: str, schema: str, fonte: str = "") -> FtMEntity:
        entity_id_san = FtMEntity(entity_id, schema).id
        if entity_id_san not in self.entita:
            self.entita[entity_id_san] = FtMEntity(entity_id_san, schema)
        ent = self.entita[entity_id_san]
        if fonte and fonte not in ent.fonti:
            ent.fonti.append(fonte)
        self.alias_to_id[entity_id_san.upper()] = entity_id_san
        return ent

    # --- FACTORY ENTITÀ OCCRP ---

    def aggiungi_persona(
        self,
        nome: str,
        cf: str = "",
        ruoli: List[str] = None,
        fonte: str = "",
    ) -> FtMEntity:
        key = cf if cf and len(cf) >= 11 else nome
        ent_id = self.genera_id("person", key)
        p = self.crea_o_aggiorna_entita(ent_id, "Person", fonte=fonte)
        p.add("name", nome)
        self.alias_to_id[nome.strip().upper()] = ent_id
        if cf:
            p.add("taxNumber", cf.upper())
            p.add("idNumber", cf.upper())
            self.alias_to_id[cf.strip().upper()] = ent_id
        if ruoli:
            for r in ruoli:
                p.add("position", r)
        return p

    def aggiungi_azienda(
        self,
        denominazione: str,
        piva_cf: str = "",
        giurisdizione: str = "it",
        fonte: str = "",
    ) -> FtMEntity:
        key = piva_cf if piva_cf and len(piva_cf) >= 8 else denominazione
        ent_id = self.genera_id("company", key)
        c = self.crea_o_aggiorna_entita(ent_id, "Company", fonte=fonte)
        c.add("name", denominazione)
        self.alias_to_id[denominazione.strip().upper()] = ent_id
        if piva_cf:
            c.add("taxNumber", piva_cf.upper())
            c.add("registrationNumber", piva_cf.upper())
            self.alias_to_id[piva_cf.strip().upper()] = ent_id
        if giurisdizione:
            c.add("jurisdiction", giurisdizione.lower())
        return c

    def aggiungi_conto_bancario(
        self,
        iban: str,
        banca: str = "",
        titolare_id: str = "",
        fonte: str = "",
    ) -> FtMEntity:
        ent_id = self.genera_id("acc", iban)
        b = self.crea_o_aggiorna_entita(ent_id, "BankAccount", fonte=fonte)
        b.add("accountNumber", iban)
        b.add("iban", iban)
        self.alias_to_id[iban.strip().upper()] = ent_id
        if banca:
            b.add("bank", banca)
        if titolare_id:
            t_id = self.alias_to_id.get(str(titolare_id).strip().upper(), titolare_id)
            b.add("holder", t_id)
        return b

    # --- FACTORY RELAZIONI OCCRP ---

    def aggiungi_ownership(
        self,
        proprietario_id: str,
        societa_id: str,
        percentuale: str = "",
        valore_quote: str = "",
        ruolo: str = "Socio",
        fonte: str = "",
        dettagli: str = "",
    ) -> FtMEntity:
        rel_id = f"own_{self._contatore_relazioni}"
        self._contatore_relazioni += 1
        p_id = self.alias_to_id.get(str(proprietario_id).strip().upper(), proprietario_id)
        s_id = self.alias_to_id.get(str(societa_id).strip().upper(), societa_id)

        rel = self.crea_o_aggiorna_entita(rel_id, "Ownership", fonte=fonte)
        rel.add("owner", p_id)
        rel.add("asset", s_id)
        rel.add("role", ruolo)
        if percentuale:
            rel.add("percentage", str(percentuale))
        if valore_quote:
            rel.add("sharesValue", str(valore_quote))
            rel.add("currency", "EUR")
        if dettagli:
            rel.add("summary", dettagli)
        return rel

    def aggiungi_directorship(
        self,
        direttore_id: str,
        societa_id: str,
        ruolo: str = "Amministratore",
        data_inizio: str = "",
        data_fine: str = "",
        fonte: str = "",
        dettagli: str = "",
    ) -> FtMEntity:
        rel_id = f"dir_{self._contatore_relazioni}"
        self._contatore_relazioni += 1
        d_id = self.alias_to_id.get(str(direttore_id).strip().upper(), direttore_id)
        s_id = self.alias_to_id.get(str(societa_id).strip().upper(), societa_id)

        rel = self.crea_o_aggiorna_entita(rel_id, "Directorship", fonte=fonte)
        rel.add("director", d_id)
        rel.add("organization", s_id)
        rel.add("role", ruolo)
        if data_inizio:
            rel.add("startDate", str(data_inizio))
        if data_fine:
            rel.add("endDate", str(data_fine))
        if dettagli:
            rel.add("summary", dettagli)
        return rel

    def aggiungi_payment(
        self,
        pagatore_id: str,
        beneficiario_id: str,
        importo: str = "",
        valuta: str = "EUR",
        data_operazione: str = "",
        causale: str = "",
        fonte: str = "",
    ) -> FtMEntity:
        rel_id = f"pay_{self._contatore_relazioni}"
        self._contatore_relazioni += 1
        p_id = self.alias_to_id.get(str(pagatore_id).strip().upper(), pagatore_id)
        b_id = self.alias_to_id.get(str(beneficiario_id).strip().upper(), beneficiario_id)

        rel = self.crea_o_aggiorna_entita(rel_id, "Payment", fonte=fonte)
        rel.add("payer", p_id)
        rel.add("beneficiary", b_id)
        if importo:
            rel.add("amount", str(importo))
            rel.add("currency", valuta)
        if data_operazione:
            rel.add("date", str(data_operazione))
        if causale:
            rel.add("summary", causale)
        return rel

    # --- SERIALIZZAZIONE E IMPORT/EXPORT ---

    def esporta_json_lines(self) -> str:
        """
        Esporta il dataset in formato JSON-Lines (.ftm.json) compatibile al 100%
        con le specifiche ufficiali OCCRP FollowTheMoney e il visualizzatore Aleph.
        """
        linee = [ent.to_json() for ent in self.entita.values()]
        return "\n".join(linee)

    def statistiche(self) -> dict:
        conteggi = {}
        for ent in self.entita.values():
            s = ent.schema
            conteggi[s] = conteggi.get(s, 0) + 1
        return {
            "totale_entita": len(self.entita),
            "per_schema": conteggi,
        }

    # --- ALGORITMI FORENSI OCCRP (UBO & GOVERNANCE ANOMALIES) ---

    def risolvi_titolari_effettivi(self) -> List[dict]:
        """
        Algoritmo OCCRP FollowTheMoney per l'individuazione del Titolare Effettivo (UBO):
        Traccia a ritroso le catene di Ownership e Directorship di ciascuna società censita,
        risalendo attraverso eventuali holding o scatole cinesi fino a identificare
        le persone fisiche (Person) al vertice del controllo.
        """
        aziende = [e for e in self.entita.values() if e.schema in {"Company", "LegalEntity"}]
        ownerships = [e for e in self.entita.values() if e.schema == "Ownership"]
        directorships = [e for e in self.entita.values() if e.schema == "Directorship"]

        mappa_proprietari = {}
        for o in ownerships:
            soc_id = o.get_first("asset")
            owner_id = o.get_first("owner")
            ruolo = o.get_first("role", "Socio")
            perc = o.get_first("percentage", "")
            if soc_id and owner_id:
                if soc_id not in mappa_proprietari:
                    mappa_proprietari[soc_id] = []
                mappa_proprietari[soc_id].append({
                    "owner_id": owner_id,
                    "ruolo": ruolo,
                    "percentuale": perc,
                    "fonte": o.get_first("fonte", ""),
                })

        mappa_amministratori = {}
        for d in directorships:
            org_id = d.get_first("organization")
            dir_id = d.get_first("director")
            ruolo = d.get_first("role", "Amministratore")
            if org_id and dir_id:
                if org_id not in mappa_amministratori:
                    mappa_amministratori[org_id] = []
                mappa_amministratori[org_id].append({
                    "director_id": dir_id,
                    "ruolo": ruolo,
                    "fonte": d.get_first("fonte", ""),
                })

        risultati = []

        for az in aziende:
            nome_az = az.get_first("name") or az.id
            cf_az = az.get_first("taxNumber", "N/D")

            titolari_trovati = []
            catena_controllo = []

            # Funzione ricorsiva per risalire la proprietà
            def risali_proprieta(target_id, visited=None, path=None):
                if visited is None:
                    visited = set()
                if path is None:
                    path = []

                if target_id in visited:
                    return
                visited.add(target_id)

                props = mappa_proprietari.get(target_id, [])
                target_ent = self.entita.get(target_id)
                target_name = (target_ent.get_first("name") if target_ent else "") or target_id
                current_path = path + [target_name]

                for p in props:
                    o_id = p["owner_id"]
                    o_ent = self.entita.get(o_id)

                    if o_ent and o_ent.schema == "Person":
                        nome_p = o_ent.get_first("name") or o_id
                        cf_p = o_ent.get_first("taxNumber", "N/D")
                        titolari_trovati.append({
                            "persona": nome_p,
                            "cf": cf_p,
                            "tipo_controllo": "Proprietà Diretta / Indiretta",
                            "ruolo": p["ruolo"],
                            "percentuale": p["percentuale"],
                            "catena": current_path + [nome_p],
                        })
                    elif o_ent and o_ent.schema in {"Company", "LegalEntity"}:
                        risali_proprieta(o_id, visited.copy(), current_path)

            risali_proprieta(az.id)

            # Aggiungi anche gli amministratori se non sono già emersi come soci
            amms = mappa_amministratori.get(az.id, [])
            amministratori_info = []
            for a in amms:
                d_id = a["director_id"]
                d_ent = self.entita.get(d_id)
                nome_d = (d_ent.get_first("name") if d_ent else "") or d_id
                cf_d = d_ent.get_first("taxNumber", "N/D") if d_ent else "N/D"
                amministratori_info.append({
                    "nominativo": nome_d,
                    "cf": cf_d,
                    "ruolo": a["ruolo"],
                })

            risultati.append({
                "azienda": nome_az,
                "azienda_id": az.id,
                "cf_piva": cf_az,
                "titolari_effettivi": titolari_trovati,
                "amministratori": amministratori_info,
                "fonti": az.fonti,
            })

        return risultati

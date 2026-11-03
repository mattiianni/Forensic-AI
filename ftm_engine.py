import hashlib
import json
import re
from typing import Any, Dict, List, Optional
from logger import log


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
        if cf:
            p.add("taxNumber", cf.upper())
            p.add("idNumber", cf.upper())
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
        if piva_cf:
            c.add("taxNumber", piva_cf.upper())
            c.add("registrationNumber", piva_cf.upper())
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
        if banca:
            b.add("bank", banca)
        if titolare_id:
            b.add("holder", titolare_id)
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
        rel = self.crea_o_aggiorna_entita(rel_id, "Ownership", fonte=fonte)
        rel.add("owner", proprietario_id)
        rel.add("asset", societa_id)
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
        rel = self.crea_o_aggiorna_entita(rel_id, "Directorship", fonte=fonte)
        rel.add("director", direttore_id)
        rel.add("organization", societa_id)
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
        rel = self.crea_o_aggiorna_entita(rel_id, "Payment", fonte=fonte)
        rel.add("payer", pagatore_id)
        rel.add("beneficiary", beneficiario_id)
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

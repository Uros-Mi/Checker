import re
from typing import List, Optional

from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


class MethodChapterExistsRule(Rule):
    """
    Check 19: Eigenes Methodenkapitel vorhanden
    """
    id = "METH-019"
    category = "Methode"
    severity = "error"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        if "methode" in doc.sections:
            sec = doc.sections["methode"]
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Methodenkapitel gefunden.",
                evidence=f"Titel: {sec.title}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="error",
            message="Kein Methodenkapitel erkannt.",
            evidence="Tipp: Überschrift 'Methode' / 'Methodik' verwenden oder nummerieren (z.B. '3 Methode')."
        )]


class MethodDetailSufficientRule(Rule):
    """
    Check 20: Methodenteil ausreichend detailliert
    V1-Heuristik:
    - Mindestwortanzahl in Methode
    - typische Methodik-Signale (Stichwörter)
    """
    id = "METH-020"
    category = "Methode"
    severity = "warn"

    KEYWORDS = [
        "stichprobe", "sample", "teilnehmer", "participants",
        "daten", "datenerhebung", "fragebogen", "interview", "beobachtung",
        "analyse", "auswertung", "statistik", "verfahren", "methode",
        "operationalisierung", "hypothese", "messung", "instrument",
        "validität", "reliabilität",
    ]

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        sec = doc.sections.get("methode")
        if sec is None:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Methodenkapitel nicht erkannt – Detail-Check nicht möglich.",
                evidence=None
            )]

        wc = sec.word_count
        text = sec.text.lower()

        hits = [k for k in self.KEYWORDS if k in text]

        # Schwellenwerte (kannst du später fein-tunen)
        min_words = 300
        min_hits = 3

        if wc < min_words and len(hits) < min_hits:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Methodenteil wirkt sehr kurz und wenig detailliert (heuristisch).",
                evidence=f"Wörter: {wc} | Keyword-Treffer: {len(hits)} ({', '.join(hits) or 'keine'})"
            )]

        if wc < min_words:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Methodenteil wirkt eher kurz (heuristisch).",
                evidence=f"Wörter: {wc} | Keyword-Treffer: {len(hits)}"
            )]

        if len(hits) < min_hits:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Methodenteil enthält wenige typische Methodik-Signale (heuristisch).",
                evidence=f"Wörter: {wc} | Keyword-Treffer: {len(hits)} ({', '.join(hits) or 'keine'})"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Methodenteil wirkt ausreichend detailliert (heuristisch).",
            evidence=f"Wörter: {wc} | Keyword-Treffer: {len(hits)}"
        )]


class ResultsDiscussionSeparationRule(Rule):
    """
    Check 25: Trennung Ergebnis / Diskussion eingehalten
    V1-Heuristik:
    - In 'Ergebnisse' sollten weniger interpretierende Wörter vorkommen
    - In 'Diskussion' dürfen/sollen sie vorkommen
    """
    id = "RES-025"
    category = "Ergebnisse"
    severity = "warn"

    INTERPRETATION_CUES = [
        "bedeutet", "impliziert", "daraus folgt", "somit", "folglich",
        "interpretiert", "interpretation", "diskutieren", "diskussion",
        "limitation", "einschränkung", "kritisch",
        "verglichen", "vergleich", "literatur", "studien zeigen",
    ]

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        res = doc.sections.get("ergebnisse")
        disc = doc.sections.get("diskussion")

        if res is None or disc is None:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Ergebnisse oder Diskussion nicht erkannt – Trennungs-Check nicht möglich.",
                evidence=f"Erkannt: {', '.join(sorted(doc.sections.keys()))}"
            )]

        res_text = res.text.lower()
        disc_text = disc.text.lower()

        res_hits = [k for k in self.INTERPRETATION_CUES if k in res_text]
        disc_hits = [k for k in self.INTERPRETATION_CUES if k in disc_text]

        # Heuristik: wenn Ergebnisse sehr viele Interpretationssignale hat, warn
        if len(res_hits) >= 4 and len(disc_hits) >= 2:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Ergebnisteil enthält viele interpretierende Formulierungen – Trennung zu Diskussion evtl. unsauber (heuristisch).",
                evidence=f"Ergebnisse-Hits: {len(res_hits)} ({', '.join(res_hits)}) | Diskussion-Hits: {len(disc_hits)}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Trennung Ergebnis/Diskussion wirkt ok (heuristisch).",
            evidence=f"Ergebnisse-Hits: {len(res_hits)} | Diskussion-Hits: {len(disc_hits)}"
        )]

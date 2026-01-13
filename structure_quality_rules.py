from typing import List, Optional

from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


EXPECTED_ORDER = ["einleitung", "theorie", "methode", "ergebnisse", "diskussion", "fazit", "literatur"]


class ChapterOrderPlausibleRule(Rule):
    """
    Check 8: Kapitelreihenfolge plausibel
    Heuristik: Wenn mehrere Pflichtkapitel erkannt werden, prüfen wir,
    ob ihre Reihenfolge grob der erwarteten Reihenfolge entspricht.
    """
    id = "STRUCT-008"
    category = "Struktur"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        # Wir approximieren die Reihenfolge über die Reihenfolge in EXPECTED_ORDER,
        # eingeschränkt auf die Kapitel, die erkannt wurden.
        present = [k for k in EXPECTED_ORDER if k in doc.sections]

        # Wenn wir kaum Kapitel erkannt haben, macht Order-Check keinen Sinn.
        if len(present) < 3:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Zu wenige Kapitel erkannt – Kapitelreihenfolge kann nicht sinnvoll geprüft werden.",
                evidence=f"Erkannt: {', '.join(sorted(doc.sections.keys())) or 'keine'}"
            )]

        # V1: Wir können (noch) nicht sauber die echte Reihenfolge im Dokument bestimmen,
        # weil unsere Section-Segmentierung noch Full-Text setzt.
        # Deshalb geben wir hier erstmal einen 'info', wenn alles präsent ist,
        # und 'warn', wenn ein typisches Kapitel fehlt (z.B. Methode nach Ergebnissen etc.).
        # (Verbessern wir später, wenn Sections echte Startpositionen haben.)
        missing_in_between = []
        for key in EXPECTED_ORDER:
            if key not in doc.sections:
                # nur "wichtige" Kapitel in der Mitte hervorheben
                if key in {"theorie", "methode", "ergebnisse", "diskussion"}:
                    missing_in_between.append(key)

        if missing_in_between:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Kapitelreihenfolge/Struktur evtl. unplausibel, da zentrale Kapitel fehlen (heuristisch).",
                evidence=f"Fehlend: {', '.join(missing_in_between)} | Erkannt: {', '.join(sorted(doc.sections.keys()))}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Kapitelstruktur wirkt plausibel (V1 heuristisch, Reihenfolge wird später exakter).",
            evidence=f"Erkannt (Pflicht-Reihenfolge): {', '.join(present)}"
        )]


class ChapterLengthBalancedRule(Rule):
    """
    Check 11: Kapitelumfang ausgewogen
    Heuristik: vergleicht (grob) Wortanzahlen pro Kapitel.
    V1: Wir nutzen doc.sections[key].word_count. (Bei uns aktuell Full-Text => später verbessern.)
    """
    id = "STRUCT-011"
    category = "Struktur"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        # Nur Kapitel betrachten, die wir haben
        keys = [k for k in EXPECTED_ORDER if k in doc.sections]
        if len(keys) < 3:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Zu wenige Kapitel erkannt – Kapitelumfang kann nicht sinnvoll geprüft werden.",
                evidence=None
            )]

        counts = {k: doc.sections[k].word_count for k in keys}
        max_k = max(counts, key=counts.get)
        min_k = min(counts, key=counts.get)

        max_v = counts[max_k]
        min_v = counts[min_k]

        # Heuristik: wenn größtes Kapitel > 3x so groß wie kleinstes -> warn
        if min_v > 0 and max_v / min_v >= 3.0:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Kapitelumfang wirkt unausgewogen (heuristisch).",
                evidence=f"Größtes: {max_k} ({max_v} Wörter) | Kleinstes: {min_k} ({min_v} Wörter)"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Kapitelumfang wirkt grob ausgewogen (heuristisch).",
            evidence=" | ".join([f"{k}:{v}" for k, v in counts.items()])[:350]
        )]

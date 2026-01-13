from typing import List, Optional
from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


class FiguresTablesReferencedRule(Rule):
    """
    Check 26: Tabellen & Abbildungen im Text referenziert
    V1 heuristisch:
      - Wenn es doc.tables gibt, erwarten wir "Tabelle <n>" irgendwo im Text
      - Für Abbildungen: Wir erkennen nur Textreferenzen ("Abbildung <n>").
        (Echte Bilder in docx tracken wir später.)
    """
    id = "RES-026"
    category = "Ergebnisse"
    severity = "error"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        findings: List[Finding] = []

        # Tabellen: wenn Tabellen existieren, aber keine "Tabelle n" Referenzen
        if doc.tables_count > 0 and len(doc.table_refs) == 0:
            findings.append(Finding(
                rule_id=self.id,
                category=self.category,
                severity="error",
                message="Dokument enthält Tabellen, aber keine 'Tabelle <n>'-Referenzen im Text gefunden.",
                evidence=f"Tabellen im DOCX: {doc.tables_count}"
            ))

        # Abbildungen: wir haben (noch) keine echte Bildanzahl,
        # aber wir können warnen, wenn Abbildungsreferenzen erwartet werden.
        # V1: nur Info, wenn gar keine Abbildungsreferenzen existieren.
        if len(doc.figure_refs) == 0:
            findings.append(Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Keine 'Abbildung <n>'-Referenzen im Text gefunden (heuristisch).",
                evidence=None
            ))

        if not findings:
            findings.append(Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Tabellen/Abbildungen scheinen im Text referenziert zu sein (heuristisch).",
                evidence=f"Tabellen-Refs: {len(doc.table_refs)} | Abbildungs-Refs: {len(doc.figure_refs)}"
            ))

        return findings

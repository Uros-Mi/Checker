import re
from typing import List, Optional

from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


CAPTION_FIG_RE = re.compile(r"(?mi)^\s*abbildung\s+\d+\s*[:\.\-–—]\s*\S+")
CAPTION_TAB_RE = re.compile(r"(?mi)^\s*tabelle\s+\d+\s*[:\.\-–—]\s*\S+")

# auch ohne ":" z.B. "Abbildung 1 Beispiel"
CAPTION_FIG_RE2 = re.compile(r"(?mi)^\s*abbildung\s+\d+\b\s+\S+")
CAPTION_TAB_RE2 = re.compile(r"(?mi)^\s*tabelle\s+\d+\b\s+\S+")


class CaptionsPresentRule(Rule):
    """
    FORM-038: Abbildungs-/Tabellenbeschriftungen vorhanden (heuristisch)
    """
    id = "FORM-038"
    category = "Formales"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        text = "\n".join([p for p in doc.paragraphs if p and p.strip()])

        fig_caps = set(CAPTION_FIG_RE.findall(text)) | set(CAPTION_FIG_RE2.findall(text))
        tab_caps = set(CAPTION_TAB_RE.findall(text)) | set(CAPTION_TAB_RE2.findall(text))

        # Wenn es gar keine Fig/Table-Refs gibt, ist Caption-Check weniger relevant
        has_refs = (len(getattr(doc, "figure_refs", [])) + len(getattr(doc, "table_refs", []))) > 0
        if not has_refs and not fig_caps and not tab_caps:
            return [Finding(self.id, self.category, "info",
                            "Keine Abbildungs-/Tabellenhinweise gefunden – Caption-Check nicht relevant (heuristisch).",
                            None)]

        # wenn Referenzen existieren aber keine Captions -> warn
        if has_refs and (len(fig_caps) + len(tab_caps) == 0):
            return [Finding(self.id, self.category, "warn",
                            "Abbildungen/Tabellen werden erwähnt, aber keine klaren Beschriftungen erkannt (heuristisch).",
                            "Erwartet Muster wie 'Abbildung 1: ...' oder 'Tabelle 2 – ...'.")]

        return [Finding(self.id, self.category, "info",
                        "Beschriftungen für Abbildungen/Tabellen scheinen vorhanden zu sein (heuristisch).",
                        f"Captions: Abbildungen={len(fig_caps)} | Tabellen={len(tab_caps)}")]

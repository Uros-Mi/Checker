import re
from typing import List, Optional

from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


def _get_literature_text(doc: DocumentModel) -> str:
    sec = doc.sections.get("literatur")
    if sec and sec.text and sec.text.strip():
        return sec.text
    return "\n".join([p for p in doc.paragraphs if p])


class CitationDensityRule(Rule):
    """
    LIT-036: Zitierdichte (heuristisch)
    """
    id = "LIT-036"
    category = "Literatur"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        words = max(1, doc.word_count_total)
        # aus CitationSignals: numeric_count zählt Blöcke wie [1], [1-3], [1,4]
        cite_blocks = getattr(doc.citations, "numeric_count", 0) + getattr(doc.citations, "author_year_count", 0)
        ratio = cite_blocks / words  # cites per word

        # grobe Schwellen (kannst du später pro Fach anpassen)
        if words < 1500:
            return [Finding(self.id, self.category, "info",
                            "Dokument ist sehr kurz – Zitierdichte wird nicht streng bewertet (heuristisch).",
                            f"Wörter: {words} | Zitat-Blöcke: {cite_blocks}")]

        if cite_blocks == 0:
            return [Finding(self.id, self.category, "warn",
                            "Keine erkennbaren Zitate im Text gefunden (heuristisch).",
                            f"Wörter: {words}")]

        # z.B. 1 Zitatblock pro 300 Wörter -> 0.0033
        if ratio < (1 / 600):
            return [Finding(self.id, self.category, "warn",
                            "Zitierdichte wirkt eher niedrig (heuristisch).",
                            f"Wörter: {words} | Zitat-Blöcke: {cite_blocks} | ca. 1 pro {int(words / cite_blocks)} Wörter")]

        return [Finding(self.id, self.category, "info",
                        "Zitierdichte wirkt plausibel (heuristisch).",
                        f"Wörter: {words} | Zitat-Blöcke: {cite_blocks} | ca. 1 pro {int(words / cite_blocks)} Wörter")]


class ReferenceYearsRule(Rule):
    """
    LIT-037: Quellenjahre-Statistik (heuristisch)
    """
    id = "LIT-037"
    category = "Literatur"
    severity = "info"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        lit_text = _get_literature_text(doc)
        years = re.findall(r"\b(?:19|20)\d{2}\b", lit_text)
        if not years:
            return [Finding(self.id, self.category, "info",
                            "Keine Jahreszahlen in der Literatur erkannt (heuristisch).",
                            "Bei manchen Stilen stehen Jahre nicht im Eintrag oder werden anders formatiert.")]

        yrs = sorted({int(y) for y in years})
        newest = max(yrs)
        oldest = min(yrs)

        # "Aktualität" grob bewerten
        # (du kannst das später konfigurierbar machen)
        if newest <= 2016:
            return [Finding(self.id, self.category, "warn",
                            "Literatur wirkt eher älter (heuristisch).",
                            f"Jahre: {oldest}–{newest} | distinct: {len(yrs)}")]

        return [Finding(self.id, self.category, "info",
                        "Literaturjahre erkannt (heuristisch).",
                        f"Jahre: {oldest}–{newest} | distinct: {len(yrs)}")]

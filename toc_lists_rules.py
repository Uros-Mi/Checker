import re
import unicodedata
from typing import List, Optional

from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _looks_like_toc_line(p: str) -> bool:
    # Leaderpunkte
    t = _norm(p)
    if not t:
        return False
    if "...." in t or re.search(r"\.{3,}", t):
        return True

    # "1.Einleitung1" oder "4.2GAN17" (Nummer + Text + Seitenzahl angehängt)
    if re.match(r"^\d+(\.\d+)*[a-zäöüß].*\d{1,4}$", t):
        return True

    # "6. Ergebnisse 24" / "Ergebnisse 24"
    if re.match(r"^\d+(\.\d+)*\s+.+\s+\d{1,4}$", t):
        return True
    if re.match(r"^[a-zäöüß].+\s+\d{1,4}$", t):
        return True

    return False


def _find_heading_like_line(paragraphs: List[str], variants: List[str]) -> Optional[int]:
    wanted = {_norm(v) for v in variants}
    for i, p in enumerate(paragraphs):
        if _norm(p) in wanted:
            return i
    return None


class TableOfContentsExistsRule(Rule):
    """
    STRUCT-015: Inhaltsverzeichnis vorhanden + (heuristisch) enthält echte TOC-Zeilen.
    """
    id = "STRUCT-015"
    category = "Struktur"
    severity = "error"

    TOC_TITLES = ["inhaltsverzeichnis", "table of contents", "contents"]

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        idx = _find_heading_like_line(doc.paragraphs, self.TOC_TITLES)
        if idx is None:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="error",
                message="Kein Inhaltsverzeichnis erkannt.",
                evidence="Tipp: Überschrift 'Inhaltsverzeichnis' verwenden."
            )]

        # Heuristik: nach der Überschrift sollten einige TOC-Zeilen folgen
        window = doc.paragraphs[idx + 1: idx + 40]
        toc_like = sum(1 for p in window if _looks_like_toc_line(p))
        if toc_like >= 3:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Inhaltsverzeichnis erkannt.",
                evidence=f"Position: Absatz {idx} | TOC-Zeilen (heuristisch): {toc_like}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="warn",
            message="Inhaltsverzeichnis-Überschrift gefunden, aber Inhalt wirkt unklar (heuristisch).",
            evidence=f"Position: Absatz {idx} | TOC-Zeilen (heuristisch): {toc_like}"
        )]


class ListOfFiguresExistsRule(Rule):
    """
    FORM-039: Abbildungsverzeichnis vorhanden, wenn Abbildungen existieren.
    """
    id = "FORM-039"
    category = "Formales"
    severity = "error"

    FIG_TITLES = [
        "abbildungsverzeichnis",
        "verzeichnis der abbildungen",
        "list of figures",
        "figures",
    ]

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        # Wenn keine Abbildungen referenziert werden -> Info (nicht erforderlich)
        if not doc.figure_refs or len(doc.figure_refs) == 0:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Keine Abbildungs-Referenzen erkannt – Abbildungsverzeichnis nicht erforderlich (heuristisch).",
                evidence=None
            )]

        idx = _find_heading_like_line(doc.paragraphs, self.FIG_TITLES)
        if idx is None:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="error",
                message="Abbildungsverzeichnis fehlt (Pflicht, da Abbildungen vorhanden sind).",
                evidence=f"Erkannte Abbildungs-Refs: {len(doc.figure_refs)}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Abbildungsverzeichnis erkannt.",
            evidence=f"Position: Absatz {idx} | Abbildungs-Refs im Text: {len(doc.figure_refs)}"
        )]


class ListOfTablesExistsRule(Rule):
    """
    FORM-040: Tabellenverzeichnis vorhanden, wenn Tabellen existieren.
    """
    id = "FORM-040"
    category = "Formales"
    severity = "error"

    TAB_TITLES = [
        "tabellenverzeichnis",
        "verzeichnis der tabellen",
        "list of tables",
        "tables",
    ]

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        # tables_count kommt aus python-docx (physische Tabellen)
        if not doc.tables_count or doc.tables_count <= 0:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Keine Tabellen erkannt – Tabellenverzeichnis nicht erforderlich.",
                evidence=None
            )]

        idx = _find_heading_like_line(doc.paragraphs, self.TAB_TITLES)
        if idx is None:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="error",
                message="Tabellenverzeichnis fehlt (Pflicht, da Tabellen vorhanden sind).",
                evidence=f"Tabellen im Dokument: {doc.tables_count}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Tabellenverzeichnis erkannt.",
            evidence=f"Position: Absatz {idx} | Tabellen im Dokument: {doc.tables_count}"
        )]

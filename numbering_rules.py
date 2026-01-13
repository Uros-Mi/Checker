import re
from typing import List, Optional, Tuple

from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


# -----------------------------
# Helpers
# -----------------------------

def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _parse_num(num_str: str) -> Optional[Tuple[int, ...]]:
    """
    "1" -> (1,)
    "1.2" -> (1,2)
    """
    s = (num_str or "").strip()
    if not s:
        return None
    if not re.match(r"^\d+(?:\.\d+)*$", s):
        return None
    try:
        return tuple(int(x) for x in s.split("."))
    except Exception:
        return None


def _get_heading_number_str(h) -> str:
    """
    Bevorzugt: h.number (kommt aus deinem Extractor, inkl. auto-numbering).
    Fallback: Nummer am Anfang von h.text.
    """
    n = (getattr(h, "number", "") or "").strip()
    if n:
        n = n.rstrip(".")
        return n

    txt = (getattr(h, "text", "") or "").strip()
    m = re.match(r"^\s*(\d+(?:\.\d+)*)(?:\.)?\s+", txt)
    if m:
        return m.group(1).rstrip(".")
    return ""


def _is_level1(h) -> bool:
    return int(getattr(h, "level", 0) or 0) == 1


def _is_level2(h) -> bool:
    return int(getattr(h, "level", 0) or 0) == 2


FRONTMATTER_OK = {
    "kurzfassung",
    "abstract",
    "danksagung",
    "vorwort",
    "abkürzungsverzeichnis",
    "abkuerzungsverzeichnis",
    "abkürzungen",
    "abkuerzungen",
    "inhaltsverzeichnis",
    "abbildungsverzeichnis",
    "tabellenverzeichnis",
    "verzeichnis der abbildungen",
    "verzeichnis der tabellen",
}


def _is_frontmatter_heading(h) -> bool:
    t = _norm(getattr(h, "text", ""))
    return t in FRONTMATTER_OK


def _find_first_chapter1_idx(headings) -> Optional[int]:
    """
    Findet die erste Level-1 Überschrift mit Nummer 1.
    """
    for i, h in enumerate(headings):
        if not _is_level1(h):
            continue
        n = _get_heading_number_str(h)
        parts = _parse_num(n)
        if parts and parts[0] == 1:
            return i
    return None


# -----------------------------
# FORM-041a
# -----------------------------

class HeadingsMustBeNumberedRule(Rule):
    """
    FORM-041a:
    - Frontmatter darf unnummeriert sein (Kurzfassung, Abkürzungen, TOC etc.)
    - AB Kapitel 1 müssen alle Hauptüberschriften (Level 1) nummeriert sein.
    """
    id = "FORM-041a"
    category = "Formales"
    severity = "error"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        hs = getattr(doc, "headings", []) or []
        if not hs:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="error",
                message="Keine Überschriften erkannt – kann Nummerierung nicht prüfen.",
                evidence=None
            )]

        first_ch1 = _find_first_chapter1_idx(hs)
        if first_ch1 is None:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="error",
                message="Kapitel 1 (erste nummerierte Hauptüberschrift) nicht erkannt – kann Pflicht-Nummerierung nicht sauber prüfen.",
                evidence="Tipp: Kapitel 1 muss als Überschrift (Heading/Überschrift 1) formatiert sein."
            )]

        front = hs[:first_ch1]
        body = hs[first_ch1:]

        # Frontmatter: wenn unnummeriert und NICHT frontmatter-typisch => warn (nicht error)
        illegal_front = [
            h for h in front
            if _is_level1(h)
            and (_parse_num(_get_heading_number_str(h)) is None)
            and (not _is_frontmatter_heading(h))
        ]
        if illegal_front:
            examples = ", ".join((getattr(h, "text", "") or "").strip() for h in illegal_front[:8])
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Unnummerierte Überschriften im Frontmatter gefunden (vor Kapitel 1).",
                evidence=f"Beispiele: {examples}"
            )]

        # Body: Level-1 müssen nummeriert sein
        unnumbered_body = [
            h for h in body
            if _is_level1(h) and (_parse_num(_get_heading_number_str(h)) is None)
        ]
        if unnumbered_body:
            examples = ", ".join((getattr(h, "text", "") or "").strip() for h in unnumbered_body[:8])
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="error",
                message="Einige Hauptüberschriften sind nicht nummeriert (Pflicht).",
                evidence=f"Beispiele: {examples}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Nummerierte Hauptüberschriften erkannt (Pflicht erfüllt).",
            evidence=None
        )]


# -----------------------------
# FORM-041b
# -----------------------------

class HeadingNumberingNoGapsRule(Rule):
    """
    FORM-041b:
    Prüft, ob Level-1 Nummerierung 1,2,3... ohne Sprünge ist,
    und ob Level-2 Nummerierung pro Kapitel 1.1, 1.2, ... ohne Sprünge ist.
    """
    id = "FORM-041b"
    category = "Formales"
    severity = "error"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        hs = getattr(doc, "headings", []) or []
        if not hs:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="error",
                message="Keine Überschriften erkannt – kann Nummerierungs-Sprünge nicht prüfen.",
                evidence=None
            )]

        # Sammle nummerierte Level 1 & 2
        lvl1 = []
        lvl2 = []

        for h in hs:
            n = _parse_num(_get_heading_number_str(h))
            if not n:
                continue
            if _is_level1(h):
                lvl1.append((n, h))
            elif _is_level2(h):
                lvl2.append((n, h))

        if not lvl1 and not lvl2:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="error",
                message="Keine nummerierten Überschriften gefunden – kann Nummerierungs-Sprünge nicht prüfen.",
                evidence=None
            )]

        problems: List[str] = []

        # Level 1: erwartet 1,2,3...
        lvl1_sorted = sorted(lvl1, key=lambda x: x[0])
        expected = 1
        for num, h in lvl1_sorted:
            if len(num) < 1:
                continue
            if num[0] != expected:
                problems.append(f"Level1 erwartet {expected}, gefunden {num[0]} ('{getattr(h,'text','')[:40]}')")
                expected = num[0] + 1
            else:
                expected += 1

        # Level 2: pro Kapitel X erwartet X.1, X.2, ...
        per_chapter = {}
        for num, h in lvl2:
            if len(num) >= 2:
                ch = num[0]
                per_chapter.setdefault(ch, []).append((num, h))

        for ch, items in per_chapter.items():
            items_sorted = sorted(items, key=lambda x: x[0])
            exp = 1
            for num, h in items_sorted:
                if num[0] != ch:
                    continue
                if num[1] != exp:
                    problems.append(f"Level2 in Kapitel {ch} erwartet {ch}.{exp}, gefunden {ch}.{num[1]} ('{getattr(h,'text','')[:40]}')")
                    exp = num[1] + 1
                else:
                    exp += 1

        if problems:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="error",
                message="Nummerierung der Überschriften hat Sprünge/Lücken (Pflicht).",
                evidence=" | ".join(problems[:6]) + (" ..." if len(problems) > 6 else "")
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Nummerierung der Überschriften wirkt lückenlos (Level 1 & 2).",
            evidence=None
        )]

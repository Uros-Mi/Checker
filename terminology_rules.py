import re
from typing import List, Optional

from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


ABBREV_SECTION_ALIASES = [
    "abkürzungsverzeichnis",
    "abkuerzungsverzeichnis",
    "abkürzungen",
    "abkuerzungen",
    "list of abbreviations",
    "abbreviations",
]

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^\s*\d+(?:\.\d+)*\s*[\.\)]?\s*", "", s)
    s = re.sub(r"[\s:;.\-–—]+$", "", s).strip()
    return s

def _has_section(doc: DocumentModel, aliases: List[str]) -> Optional[str]:
    aliases_n = {_norm(a) for a in aliases}
    for sec in doc.sections.values():
        t = _norm(sec.title)
        if t in aliases_n or any(a in t for a in aliases_n):
            return sec.title
    return None

def _detect_abbrev_list_in_text(text: str) -> int:
    """
    erkennt typische Abkürzungsverzeichnis-Zeilen:
      MRT – Magnetresonanztomographie
      MRT: Magnetresonanztomographie
      MRT = Magnetresonanztomographie
    und auch Langform -> (ABK) als Liste ist seltener, aber möglich.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # ABK vorne (2-10 Großbuchstaben/Zahlen) + Separator + Erklärung
    pat = re.compile(r"^[A-ZÄÖÜ0-9]{2,10}\s*(?:[:=\-–—])\s*\S+")
    hits = sum(1 for ln in lines if pat.search(ln))
    return hits

class AbbreviationsListExistsRule(Rule):
    """
    TERM-015: Abkürzungsverzeichnis vorhanden (heuristisch)
    Robust:
      - erkennt Section-Titel
      - fallback: scannt Volltext nach "ABK – Langform" Listenmustern
    """
    id = "TERM-015"
    category = "Terminologie"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        found_title = _has_section(doc, ABBREV_SECTION_ALIASES)
        if found_title:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Abkürzungsverzeichnis erkannt.",
                evidence=f"Titel: {found_title}"
            )]

        full_text = "\n".join([p for p in doc.paragraphs if p])
        # 1) direkt "Abkürzungsverzeichnis" irgendwo (auch ohne Section)
        if re.search(r"\b(abkürzungsverzeichnis|abkuerzungsverzeichnis|list of abbreviations)\b",
                     full_text, flags=re.IGNORECASE):
            hits = _detect_abbrev_list_in_text(full_text)
            sev = "info" if hits >= 5 else "warn"
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity=sev,
                message="Abkürzungsverzeichnis wirkt vorhanden (heuristisch, im Text gefunden).",
                evidence=f"Listen-Zeilen (ABK – Langform) erkannt: {hits}"
            )]

        # 2) reines Listenmuster ohne Überschrift (z.B. nur die Liste)
        hits = _detect_abbrev_list_in_text(full_text)
        if hits >= 6:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Abkürzungsverzeichnis wirkt vorhanden (heuristisch, Listenmuster erkannt).",
                evidence=f"Listen-Zeilen (ABK – Langform): {hits}"
            )]

        # 3) wenn nur wenige Akronyme insgesamt, dann nur info
        acronyms = re.findall(r"\b[A-ZÄÖÜ]{2,6}\b", full_text)
        acronyms = [a for a in acronyms if a not in {"UND", "ODER"}]
        unique = sorted(set(acronyms))
        if len(unique) < 12:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Kein Abkürzungsverzeichnis erkannt (heuristisch), aber nur wenige Abkürzungen gefunden.",
                evidence=f"Unique Akronyme: {len(unique)}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="warn",
            message="Kein Abkürzungsverzeichnis erkannt (heuristisch).",
            evidence=f"Unique Akronyme im Text: {len(unique)} (z.B. {', '.join(unique[:10])}{'...' if len(unique) > 10 else ''})"
        )]


class DefinitionsPresentRule(Rule):
    """
    TERM-016: Begriffe werden definiert (heuristisch)
    Erkennt:
      - klassische Definitionen ("Unter X versteht man ...", "ist definiert als ...")
      - Abkürzungseinführungen ("Magnetresonanztomographie (MRT)")
    """
    id = "TERM-016"
    category = "Terminologie"
    severity = "info"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        text = "\n".join([p for p in doc.paragraphs if p])

        # 1) Klassische Definitionen
        classic_patterns = [
            r"\bunter\s+([A-Za-zÄÖÜäöüß\- ]{3,40})\s+versteht\s+man\b",
            r"\bist\s+definiert\s+als\b",
            r"\bwird\s+als\b\s+.*\bdefiniert\b",
            r"\bdefinition\b",
            r"\bbezeichnet\b",
        ]
        classic_hits = 0
        for pat in classic_patterns:
            if re.search(pat, text, flags=re.IGNORECASE):
                classic_hits += 1

        # 2) Abkürzungseinführungen: Langform (ABK)
        # Beispiel: "Magnetresonanztomographie (MRT)" / "deep learning (DL)"
        abbr_intro = re.findall(
            r"\b([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\- ]{3,80})\s*\(\s*([A-ZÄÖÜ]{2,10})\s*\)",
            text
        )
        # Filter: Langform soll mindestens 2 Wörter haben (vermeidet "siehe (Abb.)" etc.)
        abbr_intro = [(lf.strip(), abk.strip()) for (lf, abk) in abbr_intro if len(lf.strip().split()) >= 2]

        # Unique zählen
        abbr_unique = {}
        for lf, abk in abbr_intro:
            if abk not in abbr_unique:
                abbr_unique[abk] = lf

        # Bewertung
        if classic_hits > 0 or len(abbr_unique) >= 5:
            ev = []
            if classic_hits > 0:
                ev.append(f"Definition-Muster: {classic_hits}")
            if len(abbr_unique) > 0:
                sample = list(abbr_unique.items())[:6]
                ev.append("ABK-Einführungen: " + ", ".join([f"{k}={v}" for k, v in sample]))
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Definitions-/Begriffs-Erklärungen scheinen vorhanden zu sein (heuristisch).",
                evidence=" | ".join(ev)[:350]
            )]

        # Wenn es ein Abkürzungsverzeichnis gibt/zugeben scheint, aber keine Einführungen:
        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="warn",
            message="Keine klaren Definitions-/Einführungsstellen erkannt (heuristisch).",
            evidence="Weder typische Definitionen noch Langform(ABK)-Einführungen gefunden."
        )]

import re
from typing import List, Optional, Tuple

from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


# -----------------------------
# Helper: Zitationsmuster (heuristisch)
# -----------------------------

# erkennt normale [] Zitate: [1], [1-4], [1, 3-5]
BRACKET_BLOCK_RE = re.compile(r"\[([^\]]*?\d[^\]]*?)\]")
AUTHOR_YEAR_RE = re.compile(r"\(([A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+),\s*(\d{4})\)")  # (Müller, 2020)
ETAL_RE = re.compile(r"\bet\s+al\.", flags=re.IGNORECASE)


def _expand_numeric_block(block: str) -> List[str]:
    """
    block Beispiele:
      "1" -> ["1"]
      "1-4" / "1–4" / "1—4" -> ["1","2","3","4"]
      "1, 3-5" -> ["1","3","4","5"]
      "1, 4–6, 9" -> ["1","4","5","6","9"]
    """
    block = block.replace("–", "-").replace("—", "-")
    block = re.sub(r"[^0-9,\-\s]", " ", block)
    block = re.sub(r"\s+", " ", block).strip()

    if not block:
        return []

    parts = [p.strip() for p in block.split(",") if p.strip()]
    out: List[str] = []

    for p in parts:
        if "-" in p:
            a, b = [x.strip() for x in p.split("-", 1)]
            if a.isdigit() and b.isdigit():
                start = int(a)
                end = int(b)
                if start <= end and (end - start) <= 200:  # Sicherheitslimit
                    out.extend([str(i) for i in range(start, end + 1)])
                else:
                    out.extend([a, b])
            else:
                out.extend(re.findall(r"\d+", p))
        else:
            out.extend(re.findall(r"\d+", p))

    # unique aber Reihenfolge stabil
    seen = set()
    result: List[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


def _extract_citations_from_text(text: str) -> Tuple[List[str], List[str]]:
    """
    Returns:
      - numeric cites like ["1","2","3"]
      - author-year keys like ["Müller-2020", "Smith-2019"]
    """
    numeric: List[str] = []
    for m in BRACKET_BLOCK_RE.finditer(text):
        numeric.extend(_expand_numeric_block(m.group(1)))

    author_year = [f"{m.group(1)}-{m.group(2)}" for m in AUTHOR_YEAR_RE.finditer(text)]
    return numeric, author_year


# -----------------------------
# Fallback: Literaturverzeichnis auch ohne Section finden
# -----------------------------

# erkennt Literatur-Items: [1] ...   oder 1. ...  oder 1) ...
REF_ITEM_LINE_RE = re.compile(r"^\s*(\[\s*\d+\s*\]|\d+\s*[\.\)])\s+")


def _detect_reference_block(text: str, min_items: int = 3) -> Tuple[bool, str, int]:
    """
    Sucht nach typischen Literatur-Einträgen im Volltext.
    Returns: (found, evidence, count)
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hits = [ln for ln in lines if REF_ITEM_LINE_RE.search(ln)]
    if len(hits) >= min_items:
        examples = " | ".join(hits[:3])
        evidence = f"Einträge: {len(hits)} | Beispiele: {examples[:260]}"
        return True, evidence, len(hits)
    return False, "", len(hits)


def _get_literature_text(doc: DocumentModel) -> Tuple[Optional[str], str]:
    """
    Liefert (literature_text, source_label)
      - source_label: "section" oder "fallback"
    """
    sec = doc.sections.get("literatur")
    if sec and sec.text and sec.text.strip():
        return sec.text, "section"

    full_text = "\n".join(doc.paragraphs)
    found, _, _ = _detect_reference_block(full_text, min_items=3)
    if found:
        # Wir nehmen hier den Volltext als Grundlage für ref-extraction.
        # Optional später: ab Literatur-Überschrift slicen.
        return full_text, "fallback"

    return None, "none"


# -----------------------------
# References aus Literaturtext extrahieren
# -----------------------------

def _extract_reference_candidates_from_literature(text: str) -> Tuple[List[str], List[str]]:
    """
    Very rough:
    - numeric ref list: lines starting with [n] or n. or n)
    - author-year: lines that contain a 4-digit year, and a leading surname-ish token
    """
    numeric_refs: List[str] = []
    author_year_refs: List[str] = []

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        # [12] ...
        m = re.match(r"^\[\s*(\d+)\s*\]", ln)
        if m:
            numeric_refs.append(m.group(1))
        else:
            # 12. ... / 12) ...
            m_alt = re.match(r"^\s*(\d+)\s*[\.\)]\s+", ln)
            if m_alt:
                numeric_refs.append(m_alt.group(1))

        # author-year: try to capture first surname + year
        my = re.search(r"\b(19|20)\d{2}\b", ln)
        if my:
            m2 = re.match(r"^([A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+)\b", ln)
            if m2:
                author_year_refs.append(f"{m2.group(1)}-{my.group(0)}")

    # unique
    numeric_refs = list(dict.fromkeys(numeric_refs))
    author_year_refs = list(dict.fromkeys(author_year_refs))
    return numeric_refs, author_year_refs


# -----------------------------
# Rules
# -----------------------------

class LiteratureExistsRule(Rule):
    """
    Check 32: Literaturverzeichnis vorhanden
    """
    id = "LIT-032"
    category = "Literatur"
    severity = "error"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        sec = doc.sections.get("literatur")
        if sec and sec.text.strip():
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Literaturverzeichnis erkannt.",
                evidence=f"Titel: {sec.title} | Wörter: {sec.word_count}"
            )]

        full_text = "\n".join(doc.paragraphs)
        found, evidence, _ = _detect_reference_block(full_text, min_items=3)
        if found:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Literaturverzeichnis erkannt, aber nicht als Kapitelüberschrift (Heading) segmentiert.",
                evidence=evidence
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="error",
            message="Kein Literaturverzeichnis erkannt.",
            evidence="Tipp: Überschrift 'Literatur' / 'Literaturverzeichnis' verwenden oder nummerieren."
        )]


class AllCitationsInReferenceListRule(Rule):
    """
    Check 33: Alle Zitate im Text im Literaturverzeichnis
    V1 heuristisch:
      - erkennt [n] Zitate oder (Autor, 2020)
      - versucht im Literaturteil passende Einträge zu finden
    """
    id = "LIT-033"
    category = "Literatur"
    severity = "error"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        lit_text, source = _get_literature_text(doc)
        if not lit_text:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="error",
                message="Literaturverzeichnis fehlt – kann nicht prüfen ob alle Zitate enthalten sind.",
                evidence=None
            )]

        full_text = "\n".join(doc.paragraphs)
        cited_num, cited_ay = _extract_citations_from_text(full_text)

        ref_num, ref_ay = _extract_reference_candidates_from_literature(lit_text)

        cited_num_set = set(cited_num)
        cited_ay_set = set(cited_ay)
        ref_num_set = set(ref_num)
        ref_ay_set = set(ref_ay)

        missing_num = sorted(cited_num_set - ref_num_set)
        missing_ay = sorted(cited_ay_set - ref_ay_set)

        # Wenn es gar keine erkennbaren Zitate gibt, dann nur Info
        if not cited_num_set and not cited_ay_set:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Keine erkennbaren Zitate im Text gefunden (heuristisch).",
                evidence="(z.B. [1] oder (Müller, 2020))"
            )]

        if missing_num or missing_ay:
            pieces = []
            if missing_num:
                pieces.append(f"Fehlende [n]: {', '.join(missing_num[:25])}{'...' if len(missing_num) > 25 else ''}")
            if missing_ay:
                pieces.append(f"Fehlende (Autor-Jahr): {', '.join(missing_ay[:25])}{'...' if len(missing_ay) > 25 else ''}")

            sev = "error" if source == "section" else "warn"
            msg = "Einige Zitate wurden nicht im Literaturverzeichnis gefunden (heuristisch)."
            if source == "fallback":
                msg = "Zitate vs. Literatur: mögliche Lücken erkannt (Literatur nicht als Kapitel segmentiert; heuristisch)."

            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity=sev,
                message=msg,
                evidence=" | ".join(pieces)[:350]
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Erkannte Zitate scheinen im Literaturverzeichnis enthalten zu sein (heuristisch).",
            evidence=f"Quelle: {source} | Zitate: [n]={len(cited_num_set)} | (Autor,Jahr)={len(cited_ay_set)}"
        )]


class NoUncitedReferencesRule(Rule):
    """
    Check 34: Keine unzitierten Quellen im Verzeichnis
    V1 heuristisch:
      - wenn Literatur [n]-Einträge hat, prüfen ob alle [n] auch im Text zitiert werden
      - same for (Autor-Jahr)
    """
    id = "LIT-034"
    category = "Literatur"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        lit_text, source = _get_literature_text(doc)
        if not lit_text:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Literaturverzeichnis fehlt – kann nicht prüfen ob unzitierte Quellen enthalten sind.",
                evidence=None
            )]

        full_text = "\n".join(doc.paragraphs)
        cited_num, cited_ay = _extract_citations_from_text(full_text)
        ref_num, ref_ay = _extract_reference_candidates_from_literature(lit_text)

        cited_num_set = set(cited_num)
        cited_ay_set = set(cited_ay)
        ref_num_set = set(ref_num)
        ref_ay_set = set(ref_ay)

        # Wenn im Literaturverzeichnis nichts erkennbar, nur Info
        if not ref_num_set and not ref_ay_set:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Konnte keine strukturierte Referenzliste erkennen (heuristisch).",
                evidence="Falls du APA/Harvard nutzt, ist das ok – V1 erkennt nicht alles."
            )]

        uncited_num = sorted(ref_num_set - cited_num_set)
        uncited_ay = sorted(ref_ay_set - cited_ay_set)

        if uncited_num or uncited_ay:
            pieces = []
            if uncited_num:
                pieces.append(
                    f"Unzitiert [n]: {', '.join(uncited_num[:10])}{'...' if len(uncited_num) > 10 else ''}"
                )
            if uncited_ay:
                pieces.append(
                    f"Unzitiert (Autor-Jahr): {', '.join(uncited_ay[:10])}{'...' if len(uncited_ay) > 10 else ''}"
                )

            # Wenn Literatur nur per Fallback gefunden wurde, ist die Aussage schwächer
            sev = "warn" if source == "section" else "info"
            msg = "Möglicherweise unzitierte Einträge im Literaturverzeichnis (heuristisch)."
            if source == "fallback":
                msg = "Möglicherweise unzitierte Einträge (Literatur nicht als Kapitel segmentiert; heuristisch)."

            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity=sev,
                message=msg,
                evidence=" | ".join(pieces)[:350]
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Keine offensichtlichen unzitierten Einträge erkannt (heuristisch).",
            evidence=f"Quelle: {source} | Referenzen: [n]={len(ref_num_set)} | (Autor,Jahr)={len(ref_ay_set)}"
        )]


class CitationStyleConsistentRule(Rule):
    """
    Check 35: Zitierstil konsistent
    V1 heuristisch:
      - Mischformat erkennen: sowohl [n] als auch (Autor, 2020)
    """
    id = "LIT-035"
    category = "Literatur"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        full_text = "\n".join(doc.paragraphs)
        cited_num, cited_ay = _extract_citations_from_text(full_text)

        num_count = len(set(cited_num))
        ay_count = len(set(cited_ay))

        if num_count == 0 and ay_count == 0:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Keine erkennbaren Zitatmuster gefunden (heuristisch).",
                evidence=None
            )]

        if num_count > 0 and ay_count > 0:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Mischung aus numerischen und Autor-Jahr Zitaten erkannt – Zitierstil evtl. inkonsistent.",
                evidence=f"[n]-Zitate: {num_count} | (Autor,Jahr): {ay_count}"
            )]

        style = "numerisch ([n])" if num_count > 0 else "Autor-Jahr (Harvard/APA)"
        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message=f"Zitierstil wirkt konsistent (heuristisch): {style}.",
            evidence=None
        )]

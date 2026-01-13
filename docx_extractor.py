from pathlib import Path
from typing import List, Dict, Optional, Tuple, Iterator
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

from docx import Document

from ..models.document_model import DocumentModel, Heading, Section, CitationSignals


SECTION_KEYWORDS: Dict[str, List[str]] = {
    "abstract": ["abstract", "kurzfassung", "executive summary"],
    "abkuerzungen": [
        "abkürzungsverzeichnis",
        "abkuerzungsverzeichnis",
        "abkürzungen",
        "abkuerzungen",
        "list of abbreviations",
        "abbreviations",
    ],
    "einleitung": ["einleitung", "introduction"],
    "theorie": [
        "theorie",
        "grundlagen",
        "theoretische grundlagen",
        "theoretischer hintergrund",
        "stand der forschung",
        "forschungsstand",
        "background",
        "theoretical background",
    ],
    "methode": ["methode", "methodik", "methods", "methodology"],
    "ergebnisse": ["ergebnisse", "results"],
    "diskussion": ["diskussion", "discussion"],
    "fazit": [
        "fazit",
        "schluss",
        "schlussfolgerung",
        "schlussfolgerungen",
        "zusammenfassung",
        "conclusion",
        "conclusions",
        "summary",
        "ausblick",
    ],
    "literatur": [
        "literaturverzeichnis",
        "references",
        "bibliography",
        "quellenverzeichnis",
        "quellen",
    ],
}

# erkennt: "1 Titel", "1. Titel", "1.2 Titel", "1.2.3 Titel"
NUMBERING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)(?:\.)?\s+(.+)$")

STRICT_ONLY_KEYS = {"literatur", "ergebnisse", "diskussion", "abstract", "abkuerzungen"}
PREFIX_OK_KEYS = {"einleitung", "theorie", "methode", "fazit"}

_W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def _normalize_simple(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _normalize_title(title: str) -> str:
    t = title or ""
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("\u00A0", " ")
    t = t.strip().lower()

    # führende Nummern entfernen: "9. Literaturverzeichnis", "9) Literaturverzeichnis", "9 Literaturverzeichnis"
    t = re.sub(r"^\s*\d+(?:\.\d+)*\s*[\.\)]?\s*", "", t)

    # trailing punctuation entfernen (z.B. ":" am Ende)
    t = re.sub(r"[\s:;.\-–—]+$", "", t).strip()

    # whitespace normalisieren
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _looks_like_toc_line(p: str) -> bool:
    """
    Robustere TOC-Heuristik (dein TOC hat oft keine Spaces: "1.Einleitung1")
    """
    t = _normalize_simple(p)
    if not t:
        return False

    if "...." in t or re.search(r"\.{3,}", t):
        return True

    # "1.Einleitung1" / "4.2GAN17" (Nummer + Text + Seitenzahl direkt angehängt)
    if re.match(r"^\d+(\.\d+)*[a-zäöüß].*\d{1,4}$", t):
        return True

    # "6. Ergebnisse 24" / "Ergebnisse 24"
    if re.match(r"^\d+(\.\d+)*\s+.+\s+\d{1,4}$", t):
        return True
    if re.match(r"^[a-zäöüß].+\s+\d{1,4}$", t):
        return True

    return False


def _find_toc_range(paragraphs: List[str]) -> Optional[Tuple[int, int]]:
    """
    Findet TOC als (start_idx, end_idx), end_idx = erster Absatz NACH dem TOC.
    """
    toc_start = None
    for i, p in enumerate(paragraphs):
        if _normalize_simple(p) == "inhaltsverzeichnis":
            toc_start = i
            break
    if toc_start is None:
        return None

    max_scan = min(len(paragraphs), toc_start + 500)

    for j in range(toc_start + 1, max_scan):
        window = [x for x in paragraphs[j: min(max_scan, j + 8)] if _normalize_simple(x)]
        if not window:
            continue
        non_toc = sum(1 for x in window if not _looks_like_toc_line(x))
        if non_toc >= 5:
            return (toc_start, j)

    return (toc_start, min(len(paragraphs), toc_start + 250))


def _find_section_key(title: str, *, level: Optional[int] = None, number: Optional[str] = None) -> Optional[str]:
    t = _normalize_title(title)
    if not t:
        return None

    if re.search(r"\bliteraturrecherche\b", t):
        return None

    is_top_level = False
    if level is not None and level == 1:
        is_top_level = True
    if number and number.isdigit():
        is_top_level = True

    # 1) STRICT-only Keys: exakt matchen
    for key in STRICT_ONLY_KEYS:
        for kw in SECTION_KEYWORDS.get(key, []):
            if t == _normalize_title(kw):
                return key

    # 2) Restliche Keys: exakt matchen
    for key, kws in SECTION_KEYWORDS.items():
        if key in STRICT_ONLY_KEYS:
            continue
        for kw in kws:
            if t == _normalize_title(kw):
                return key

    # 3) Prefix-Match nur für bestimmte Keys und nur top-level
    if is_top_level:
        for key in PREFIX_OK_KEYS:
            for kw in SECTION_KEYWORDS.get(key, []):
                kw_n = _normalize_title(kw)
                if kw_n and t.startswith(kw_n + " "):
                    return key

    # 4) Speziell für Theorie: viele Arbeiten nennen das Kapitel "Theoretische Grundlagen" / "Stand der Forschung"
    if is_top_level:
        if re.search(r"\b(theorie|grundlagen|theoretisch|forschungsstand|stand der forschung|background)\b", t):
            return "theorie"

    return None


# -----------------------------
# XML-basierte Extraktion (Citavi/SDT robust) + TABLE-AWARE WALK
# -----------------------------

def _read_document_xml(path: Path) -> ET.Element:
    with zipfile.ZipFile(str(path)) as z:
        xml_bytes = z.read("word/document.xml")
    return ET.fromstring(xml_bytes)


def _p_text(p: ET.Element) -> str:
    parts = []
    for t in p.findall(".//w:t", _W_NS):
        if t.text:
            parts.append(t.text)
    txt = "".join(parts)
    txt = unicodedata.normalize("NFKC", txt).replace("\u00A0", " ").strip()
    return txt


def _p_style(p: ET.Element) -> str:
    """
    Word Style-ID auslesen: w:pPr/w:pStyle/@w:val
    """
    ppr = p.find("./w:pPr", _W_NS)
    if ppr is None:
        return ""
    ps = ppr.find("./w:pStyle", _W_NS)
    if ps is None:
        return ""
    val = ps.attrib.get(f"{{{_W_NS['w']}}}val", "")
    return (val or "").strip().lower()


def _p_ilvl(p: ET.Element) -> Optional[int]:
    """
    Liest Word-Nummerierungs-Level aus: w:pPr/w:numPr/w:ilvl/@w:val
    ilvl 0 => Level 1, ilvl 1 => Level 2, ...
    """
    ppr = p.find("./w:pPr", _W_NS)
    if ppr is None:
        return None
    numpr = ppr.find("./w:numPr", _W_NS)
    if numpr is None:
        return None
    ilvl = numpr.find("./w:ilvl", _W_NS)
    if ilvl is None:
        return None
    val = ilvl.attrib.get(f"{{{_W_NS['w']}}}val", "")
    try:
        return int(val)
    except Exception:
        return None


def _heading_level_from_style(style_id: str) -> Optional[int]:
    """
    Extrahiert Heading-Level aus Word Style-ID.
    Robust für:
      - heading1 / heading 1
      - überschrift1 / überschrift 1
      - berschrift1 (kommt oft in DE-Templates vor, ohne Ü)
    """
    s = (style_id or "").strip().lower()
    if not s:
        return None

    m = re.search(r"(heading|überschrift|berschrift)\s*([1-9])", s)
    if m:
        try:
            return int(m.group(2))
        except Exception:
            return None

    m2 = re.search(r"(heading|überschrift|berschrift)([1-9])", s)
    if m2:
        try:
            return int(m2.group(2))
        except Exception:
            return None

    if "heading" in s or "überschrift" in s or "berschrift" in s:
        return 1

    return None


def _walk_body_paragraphs(body: ET.Element) -> Iterator[Tuple[ET.Element, bool]]:
    """
    Walkt den XML-Body in Dokument-Reihenfolge und yieldet (paragraph, in_table).
    Damit können wir Headings aus Tabellen konsequent ignorieren.
    """
    def walk(node: ET.Element, in_table: bool) -> Iterator[Tuple[ET.Element, bool]]:
        for child in list(node):
            tag = child.tag.split("}")[-1]  # localname
            if tag == "tbl":
                yield from walk(child, True)
            elif tag == "p":
                yield (child, in_table)
            else:
                yield from walk(child, in_table)

    yield from walk(body, False)


def _extract_paragraphs_and_headings_from_xml(path: Path) -> Tuple[List[str], List[Heading]]:
    root = _read_document_xml(path)
    body = root.find(".//w:body", _W_NS)
    if body is None:
        return [], []

    paragraphs: List[str] = []
    headings: List[Heading] = []

    # Zähler für Auto-Nummerierung (aus numPr/ilvl)
    auto_counts = [0] * 10  # 1..9 genutzt

    for idx, (p, in_table) in enumerate(_walk_body_paragraphs(body)):
        text = _p_text(p)
        if not text:
            paragraphs.append("")
            continue

        paragraphs.append(text)

        # Headings nur außerhalb von Tabellen
        if in_table:
            continue

        style = _p_style(p)
        level_from_style = _heading_level_from_style(style)
        is_heading_style = level_from_style is not None

        ilvl = _p_ilvl(p)

        number: Optional[str] = None
        title = text
        m = NUMBERING_RE.match(text)
        if m:
            number = m.group(1)
            title = m.group(2).strip()

        # Auto-Nummerierung aus Word numPr/ilvl => Nummern selbst hochzählen
        if number is None and is_heading_style and ilvl is not None:
            lvl = max(1, min(9, ilvl + 1))  # ilvl 0->1, 1->2, ...
            auto_counts[lvl] += 1
            for k in range(lvl + 1, 10):
                auto_counts[k] = 0
            if lvl > 1 and auto_counts[1] == 0:
                auto_counts[1] = 1
            number = ".".join(str(auto_counts[k]) for k in range(1, lvl + 1))

        looks_like_known_section = (
            _find_section_key(
                title,
                level=level_from_style if level_from_style is not None else (number.count(".") + 1 if number else None),
                number=number,
            )
            is not None
        )

        if is_heading_style or (number and len(text) <= 120) or (looks_like_known_section and len(title) <= 60):
            if number:
                level = number.count(".") + 1
            elif level_from_style is not None:
                level = level_from_style
            else:
                level = 1

            headings.append(Heading(text=title, level=level, number=number, para_index=idx))

    # Inhaltsverzeichnis finden und Headings darin ignorieren
    toc = _find_toc_range(paragraphs)
    if toc:
        toc_start, toc_end = toc
        filtered: List[Heading] = []
        for h in headings:
            if toc_start <= h.para_index < toc_end and _looks_like_toc_line(paragraphs[h.para_index]):
                continue
            filtered.append(h)
        headings = filtered

    return paragraphs, headings


def _build_sections(paragraphs: List[str], headings: List[Heading]) -> Dict[str, Section]:
    sections: Dict[str, Section] = {}
    hs = sorted(headings, key=lambda x: x.para_index)

    sec_keys: List[Optional[str]] = [
        _find_section_key(h.text, level=h.level, number=h.number) for h in hs
    ]

    for i, h in enumerate(hs):
        key = sec_keys[i]
        if not key:
            continue
        if key in sections:
            continue

        start = h.para_index + 1

        end = len(paragraphs)
        for j in range(i + 1, len(hs)):
            if sec_keys[j]:
                end = hs[j].para_index
                break

        slice_paras = [p for p in paragraphs[start:end] if p and p.strip()]
        section_text = "\n".join(slice_paras).strip()

        sections[key] = Section(
            key=key,
            title=h.text,
            start_para=start,
            end_para=max(start, end - 1),
            text=section_text,
            word_count=_word_count(section_text),
        )

    return sections


def _extract_references(paragraphs: List[str]) -> Tuple[List[str], List[str]]:
    text = "\n".join([p for p in paragraphs if p])
    fig = re.findall(r"\bAbbildung\s+\d+\b", text, flags=re.IGNORECASE)
    tab = re.findall(r"\bTabelle\s+\d+\b", text, flags=re.IGNORECASE)
    fig = [f.title() for f in fig]
    tab = [t.title() for t in tab]
    return sorted(set(fig)), sorted(set(tab))


def _extract_citation_signals(paragraphs: List[str]) -> CitationSignals:
    text = "\n".join([p for p in paragraphs if p])
    blocks = re.findall(r"\[([^\]]*?\d[^\]]*?)\]", text)

    numeric_count = 0
    for b in blocks:
        b = b.replace("–", "-").replace("—", "-")
        if re.findall(r"\d+", b):
            numeric_count += 1

    author_year = len(re.findall(r"\([A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+,\s*\d{4}\)", text))
    etal = len(re.findall(r"\bet\s+al\.", text, flags=re.IGNORECASE))
    return CitationSignals(numeric_count=numeric_count, author_year_count=author_year, etal_count=etal)


def extract_docx(path: Path) -> DocumentModel:
    doc = Document(str(path))

    paragraphs, headings = _extract_paragraphs_and_headings_from_xml(path)
    sections = _build_sections(paragraphs, headings)

    figures, tables = _extract_references(paragraphs)
    citations = _extract_citation_signals(paragraphs)

    full_text = "\n".join([p for p in paragraphs if p])

    return DocumentModel(
        filename=path.name,
        paragraphs=paragraphs,
        headings=headings,
        sections=sections,
        word_count_total=_word_count(full_text),
        tables_count=len(doc.tables),
        figure_refs=figures,
        table_refs=tables,
        citations=citations,
    )

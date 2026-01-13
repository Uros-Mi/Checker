import re
from typing import List, Optional

from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


# Aliase für Schluss-Kapitel
CONCLUSION_ALIASES = [
    "fazit",
    "schluss",
    "schlussfolgerung",
    "schlussfolgerungen",
    "zusammenfassung",
    "conclusion",
    "conclusions",
    "summary",
    "fazit und ausblick",
    "schluss und ausblick",
    "zusammenfassung und ausblick",
    "ausblick",  # je nach Institut kann Ausblick eigenes Kapitel sein
]

ABSTRACT_ALIASES = [
    "abstract",
    "kurzfassung",
    "zusammenfassung",  # vorsicht: kann auch Fazit sein -> wird über Position/Heuristik abgefedert
    "executive summary",
]

# Einleitung: typische "Aufbau der Arbeit" Marker
INTRO_STRUCTURE_MARKERS = [
    "aufbau der arbeit",
    "gliederung der arbeit",
    "struktur der arbeit",
    "im folgenden kapitel",
    "diese arbeit ist wie folgt aufgebaut",
    "this thesis is structured",
    "this thesis is organized",
]


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    # führende Nummern killen: "9. Fazit"
    s = re.sub(r"^\s*\d+(?:\.\d+)*\s*[\.\)]?\s*", "", s)
    # trailing punctuation
    s = re.sub(r"[\s:;.\-–—]+$", "", s).strip()
    return s


def _find_section_by_aliases(doc: DocumentModel, aliases: List[str]) -> Optional[str]:
    """
    Gibt den Section-Key zurück (z.B. 'fazit'), wenn einer der Section-Titel Aliase matcht.
    """
    aliases_n = {_norm(a) for a in aliases}
    for key, sec in doc.sections.items():
        t = _norm(sec.title)
        if t in aliases_n:
            return key
        # contains-match für Dinge wie "Fazit und Ausblick"
        if any(a in t for a in aliases_n):
            return key
    return None


class ConclusionChapterExistsRule(Rule):
    """
    STRUCT-012: Fazit/Schluss vorhanden (Existenz)
    Akzeptiert auch 'Zusammenfassung', 'Schlussfolgerungen', 'Conclusion' etc.
    """
    id = "STRUCT-012"
    category = "Struktur"
    severity = "error"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        # Falls dein Parser schon eine 'fazit'-Section liefert, ist es ok
        if doc.sections.get("fazit") and doc.sections["fazit"].text.strip():
            sec = doc.sections["fazit"]
            return [Finding(self.id, self.category, "info",
                            "Fazit/Schluss-Kapitel erkannt.",
                            f"Titel: {sec.title} | Wörter: {sec.word_count}")]

        # Sonst: Alias match auf beliebigem Section-Titel
        found_key = _find_section_by_aliases(doc, CONCLUSION_ALIASES)
        if found_key:
            sec = doc.sections[found_key]
            return [Finding(self.id, self.category, "info",
                            "Fazit/Schluss-Kapitel erkannt (Alias-Match).",
                            f"Titel: {sec.title} | Wörter: {sec.word_count}")]

        # Fallback: im Volltext nach "Fazit" etc. als Überschrift-like Zeile suchen
        full_text = "\n".join([p for p in doc.paragraphs if p])
        if re.search(r"(?m)^\s*\d*(?:\.\d+)*\s*(fazit|schluss|conclusion|zusammenfassung)\s*$",
                     full_text, flags=re.IGNORECASE):
            return [Finding(self.id, self.category, "warn",
                            "Fazit/Schluss scheint vorhanden zu sein, wurde aber nicht als Section segmentiert.",
                            "Hinweis: Überschrift als Word-Heading formatieren (Heading/Überschrift).")]

        return [Finding(self.id, self.category, "error",
                        "Kein Fazit/Schluss-Kapitel erkannt.",
                        "Erwartet z.B. 'Fazit', 'Schluss', 'Zusammenfassung', 'Conclusion'.")]


class AbstractExistsRule(Rule):
    """
    STRUCT-013: Abstract/Kurzfassung vorhanden (Existenz)
    Viele Richtlinien verlangen das; wenn du es nicht brauchst, setz severity später auf info/warn.
    """
    id = "STRUCT-013"
    category = "Struktur"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        # 1) Section-Detection
        found_key = _find_section_by_aliases(doc, ABSTRACT_ALIASES)
        if found_key:
            sec = doc.sections[found_key]
            sev = "info" if sec.word_count <= 600 else "warn"
            msg = "Abstract/Kurzfassung erkannt."
            if sec.word_count > 600:
                msg = "Abstract/Kurzfassung erkannt, wirkt aber sehr lang (heuristisch)."
            return [Finding(self.id, self.category, sev, msg,
                            f"Titel: {sec.title} | Wörter: {sec.word_count}")]

        paras = [p.strip() for p in doc.paragraphs if p and p.strip()]
        if not paras:
            return [Finding(self.id, self.category, "warn",
                            "Konnte Abstract nicht prüfen (kein Text erkannt).", None)]
       # 2) Keyword im Dokumentanfang (starkes Signal)
        head = "\n".join(paras[: max(30, int(len(paras) * 0.12))])
        if re.search(r"\b(abstract|kurzfassung|executive summary)\b", head, flags=re.IGNORECASE):
            return [Finding(self.id, self.category, "info",
                            "Abstract/Kurzfassung wirkt vorhanden (heuristisch, im Dokumentanfang gefunden).",
                            "Hinweis: Überschrift als Heading formatieren, dann wird es als Section erkannt.")]

        # 3) Abstract-Block Heuristik:
        # Nimm Text vor der Einleitung (falls Einleitung erkannt) und schau ob dort ein kompakter Block steht.
        intro = doc.sections.get("einleitung")
        if intro:
            # Paragraphen bis zur Einleitung (start_para ist Index in paragraphs)
            start_idx = max(0, intro.start_para - 1)
            pre = [p.strip() for p in doc.paragraphs[:start_idx] if p and p.strip()]

            # Häufig: Titel + evtl. 1-2 Metazeilen, dann Abstract-Block.
         # Wir suchen einen Block mit z.B. 80–350 Wörtern in den letzten paar Paragraphen vor der Einleitung.
            pre_tail = pre[-12:]  # nur den relevanten “Top-Teil”
            pre_text = "\n".join(pre_tail)
            words = len(re.findall(r"\w+", pre_text, flags=re.UNICODE))

            if 80 <= words <= 450:
                # Zusätzliche Signale: typische Abstract-Wörter
                if re.search(r"\b(ziel|zielsetzung|method|methode|ergebnis|results|this thesis|diese arbeit)\b",
                             pre_text, flags=re.IGNORECASE):
                    return [Finding(self.id, self.category, "info",
                                    "Abstract/Kurzfassung wirkt vorhanden (heuristisch als Block vor der Einleitung).",
                                    f"Block vor Einleitung: ca. {words} Wörter")]

        return [Finding(self.id, self.category, "warn",
                        "Kein Abstract/Kurzfassung erkannt (heuristisch).",
                        "Falls deine Richtlinien kein Abstract verlangen, kannst du diese Warnung ignorieren.")]


class IntroHasStructureOverviewRule(Rule):
    """
    STRUCT-014: Einleitung enthält Aufbau/Gliederungs-Überblick (heuristisch)
    """
    id = "STRUCT-014"
    category = "Struktur"
    severity = "info"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        intro = doc.sections.get("einleitung")
        if not intro or not intro.text.strip():
            return [Finding(self.id, self.category, "warn",
                            "Einleitung nicht erkannt – kann Strukturhinweis in Einleitung nicht prüfen.",
                            "Keine 'Einleitung'-Section gefunden.")]

        t = _norm(intro.text)
        hits = [m for m in INTRO_STRUCTURE_MARKERS if m in t]

        if hits:
            return [Finding(self.id, self.category, "info",
                            "Aufbau/Gliederungs-Überblick in der Einleitung erkannt (heuristisch).",
                            f"Treffer: {', '.join(hits[:4])}")]

        return [Finding(self.id, self.category, "warn",
                        "Kein klarer Aufbau/Gliederungs-Überblick in der Einleitung erkannt (heuristisch).",
                        "Typisch wäre z.B. ein Absatz 'Die Arbeit ist wie folgt aufgebaut ...'.")]

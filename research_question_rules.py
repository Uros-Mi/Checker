import re
import unicodedata
from collections import Counter
from typing import List, Optional

from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


# -----------------------------
# Konfiguration / Patterns
# -----------------------------

STOPWORDS_DE = {
    "der", "die", "das", "ein", "eine", "einer", "eines", "einem", "einen",
    "und", "oder", "aber", "sowie", "als", "wie", "wenn", "dann", "dass", "daß",
    "ist", "sind", "war", "waren", "wird", "werden", "wurde",
    "in", "im", "auf", "an", "am", "aus", "bei", "mit", "ohne", "für", "von", "zu", "zum", "zur",
    "des", "den", "dem", "durch", "über", "unter", "zwischen", "gegen", "um",
    "diese", "dieser", "dieses", "diesem", "diesen",
    "arbeit", "bachelorarbeit", "studie", "untersuchung", "analyse",
    "frage", "forschungsfrage", "ziel", "zielsetzung",
}

# Heuristische Muster für Forschungsfrage / Zielsetzung
RQ_PATTERNS = [
    r"\bforschungsfrage\b",
    r"\bfragestellung\b",
    r"\bziel dieser arbeit\b",
    r"\bzielsetzung\b",
    r"\bdiese arbeit untersucht\b",
    r"\bdiese arbeit analysiert\b",
    r"\bdiese arbeit geht der frage nach\b",
    r"\bfolgende frage\b",
    r"\bim rahmen dieser arbeit\b.*\bfrage\b",
]


# -----------------------------
# Helper-Funktionen
# -----------------------------

def _contains_research_question(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in RQ_PATTERNS)


def _normalize(s: str) -> str:
    s = s.lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    # verschiedene Bindestriche -> "-"
    s = re.sub(r"[\u2010\u2011\u2012\u2013\u2014]", "-", s)
    s = re.sub(r"[^a-z0-9äöüß\- ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokenize(text: str) -> List[str]:
    t = _normalize(text)
    return re.findall(r"[a-zäöüß0-9\-]{2,}", t)


def _extract_candidate_terms(rq_text: str, max_terms: int = 8) -> List[str]:
    """
    V1: Kandidaten aus der Forschungsfrage:
    - Tokenize
    - Stopwords raus
    - Häufigkeit / Länge als Signal
    """
    tokens = [t for t in _tokenize(rq_text) if t not in STOPWORDS_DE and len(t) >= 3]
    if not tokens:
        return []

    counts = Counter(tokens)

    def score(tok: str) -> float:
        # häufig + länger = wichtiger (heuristisch)
        return counts[tok] * 2 + min(len(tok), 12) / 4

    ranked = sorted(counts.keys(), key=lambda x: score(x), reverse=True)
    return ranked[:max_terms]


def _find_variants(text_tokens: List[str], term: str) -> List[str]:
    """
    Findet "ähnliche" Varianten:
    - gleiche Basis ohne '-' (e.g. "data-driven" vs "datadriven")
    - simple singular/plural Heuristik
    """
    base_term = term.replace("-", "")

    variants = set()
    for t in text_tokens:
        if t == term:
            continue

        if t.replace("-", "") == base_term:
            variants.add(t)

        # simple plural/singular heuristics
        if t.startswith(term) or term.startswith(t):
            if abs(len(t) - len(term)) <= 3:
                variants.add(t)

    return sorted(variants)[:8]


# -----------------------------
# Rules
# -----------------------------

class ResearchQuestionExistsRule(Rule):
    """
    Check Nr. 1: Forschungsfrage explizit vorhanden
    """
    id = "RQ-001"
    category = "Fragestellung"
    severity = "error"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        full_text = "\n".join(doc.paragraphs)

        if _contains_research_question(full_text):
            # Evidence: erste passende Zeile
            for p in doc.paragraphs:
                if _contains_research_question(p):
                    return [Finding(
                        rule_id=self.id,
                        category=self.category,
                        severity="info",
                        message="Hinweis auf Forschungsfrage/Zielsetzung gefunden.",
                        evidence=p[:220]
                    )]

            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Hinweis auf Forschungsfrage/Zielsetzung gefunden.",
                evidence=None
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="error",
            message="Keine explizite Forschungsfrage/Zielsetzung gefunden (heuristisch).",
            evidence="Gesucht wurden Muster wie: 'Forschungsfrage', 'Ziel dieser Arbeit', 'Diese Arbeit untersucht ...'"
        )]


class ResearchQuestionInIntroRule(Rule):
    """
    Check Nr. 2: Forschungsfrage steht in der Einleitung
    V1-Heuristik: Wenn wir eine 'einleitung' Section haben, prüfen wir darin.
    """
    id = "RQ-002"
    category = "Fragestellung"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        intro = doc.sections.get("einleitung")

        if intro is None:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Einleitung nicht erkannt – Check 'RQ in Einleitung' kann nicht sauber geprüft werden.",
                evidence="Tipp: Überschrift 'Einleitung' als echte Überschrift formatieren oder nummerieren (z.B. '1 Einleitung')."
            )]

        if _contains_research_question(intro.text):
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Hinweis auf Forschungsfrage/Zielsetzung in der Einleitung gefunden (heuristisch).",
                evidence=f"Section: {intro.title}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="warn",
            message="Kein Hinweis auf Forschungsfrage/Zielsetzung in der Einleitung gefunden (heuristisch).",
            evidence=f"Section: {intro.title}"
        )]


class ResearchKeyTermsConsistencyRule(Rule):
    """
    Check Nr. 3: Zentrale Begriffe der Forschungsfrage konsistent verwendet (V1 heuristisch)

    Vorgehen:
    - RQ/Ziel-Passage bestimmen (oder später ai.research_question)
    - Key Terms daraus extrahieren
    - prüfen ob Terms im Dokument vorkommen
    - prüfen ob auffällige Varianten existieren (Bindestrich / sehr ähnlich)
    """
    id = "RQ-003"
    category = "Fragestellung"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        full_text = "\n".join(doc.paragraphs)
        tokens = _tokenize(full_text)

        # 1) RQ-Quelle bestimmen
        rq_source = None

        # später: KI kann das direkt liefern
        if ai and ai.research_question:
            rq_source = ai.research_question
        else:
            for p in doc.paragraphs:
                if _contains_research_question(p):
                    rq_source = p
                    break

        if not rq_source:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Keine Forschungsfrage/Ziel-Passage gefunden – zentrale Begriffe können nicht extrahiert werden.",
                evidence="Tipp: Formuliere einen Satz wie „Die Forschungsfrage lautet: …“ oder „Ziel dieser Arbeit ist …“"
            )]

        terms = _extract_candidate_terms(rq_source, max_terms=8)
        if not terms:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Konnte keine zentralen Begriffe aus der Forschungsfrage ableiten (heuristisch).",
                evidence=f"RQ-Text: {rq_source[:200]}"
            )]

        # 2) Vorkommen prüfen
        missing = [t for t in terms if t not in tokens]
        if missing:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message=f"Einige zentrale Begriffe aus der Forschungsfrage tauchen im Text nicht auf: {', '.join(missing)}",
                evidence=f"Extrahierte Begriffe: {', '.join(terms)}"
            )]

        # 3) Varianten prüfen
        variants_map = {}
        for t in terms:
            vars_ = _find_variants(tokens, t)
            if vars_:
                variants_map[t] = vars_

        if variants_map:
            parts = [f"{k} → {', '.join(v)}" for k, v in variants_map.items()]
            evidence = " | ".join(parts)[:350]
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Mögliche inkonsistente Schreibweisen zentraler Begriffe gefunden (heuristisch).",
                evidence=evidence
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Zentrale Begriffe aus der Forschungsfrage erscheinen konsistent (heuristisch).",
            evidence=f"Begriffe: {', '.join(terms)}"
    
        )]
class ResearchQuestionReferencedInResultsRule(Rule):
    """
    Check Nr. 4: Forschungsfrage wird im Ergebnisteil referenziert (heuristisch)
    V1: Keywords aus RQ-Quelle extrahieren und in 'ergebnisse' Section suchen.
    """
    id = "RQ-004"
    category = "Fragestellung"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        results = doc.sections.get("ergebnisse")
        if results is None:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Ergebnisse-Kapitel nicht erkannt – Check RQ-004 kann nicht sauber geprüft werden.",
                evidence="Tipp: Überschrift als 'Ergebnisse' oder '4 Ergebnisse' formatieren/nummerieren."
            )]

        # RQ-Quelle bestimmen (wie in RQ-003)
        rq_source = ai.research_question if (ai and ai.research_question) else None
        if not rq_source:
            for p in doc.paragraphs:
                if _contains_research_question(p):
                    rq_source = p
                    break

        if not rq_source:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Keine Forschungsfrage/Ziel-Passage gefunden – kann Rückbezug in Ergebnissen nicht prüfen.",
                evidence=None
            )]

        terms = _extract_candidate_terms(rq_source, max_terms=8)
        if not terms:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Keine zentralen Begriffe aus der Forschungsfrage ableitbar – Check RQ-004 übersprungen.",
                evidence=f"RQ-Text: {rq_source[:200]}"
            )]

        results_tokens = set(_tokenize(results.text))
        hits = [t for t in terms if t in results_tokens]

        # Heuristik: mindestens 2 Treffer oder mindestens 35% der Terms
        needed = max(2, int(len(terms) * 0.35))
        if len(hits) >= needed:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Rückbezug auf zentrale Begriffe der Forschungsfrage im Ergebnisteil gefunden (heuristisch).",
                evidence=f"Treffer: {', '.join(hits)}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="warn",
            message="Wenig/kein Rückbezug auf zentrale Begriffe der Forschungsfrage im Ergebnisteil (heuristisch).",
            evidence=f"Treffer: {', '.join(hits) or 'keine'} | Begriffe: {', '.join(terms)}"
        )]


class ResearchQuestionReferencedInDiscussionRule(Rule):
    """
    Check Nr. 5: Forschungsfrage wird in der Diskussion referenziert (heuristisch)
    V1: Keywords aus RQ-Quelle extrahieren und in 'diskussion' Section suchen.
    """
    id = "RQ-005"
    category = "Fragestellung"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        discussion = doc.sections.get("diskussion")
        if discussion is None:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Diskussion-Kapitel nicht erkannt – Check RQ-005 kann nicht sauber geprüft werden.",
                evidence="Tipp: Überschrift als 'Diskussion' oder '5 Diskussion' formatieren/nummerieren."
            )]

        rq_source = ai.research_question if (ai and ai.research_question) else None
        if not rq_source:
            for p in doc.paragraphs:
                if _contains_research_question(p):
                    rq_source = p
                    break

        if not rq_source:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Keine Forschungsfrage/Ziel-Passage gefunden – kann Rückbezug in Diskussion nicht prüfen.",
                evidence=None
            )]

        terms = _extract_candidate_terms(rq_source, max_terms=8)
        if not terms:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="warn",
                message="Keine zentralen Begriffe aus der Forschungsfrage ableitbar – Check RQ-005 übersprungen.",
                evidence=f"RQ-Text: {rq_source[:200]}"
            )]

        disc_tokens = set(_tokenize(discussion.text))
        hits = [t for t in terms if t in disc_tokens]

        needed = max(2, int(len(terms) * 0.35))
        if len(hits) >= needed:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Rückbezug auf zentrale Begriffe der Forschungsfrage in der Diskussion gefunden (heuristisch).",
                evidence=f"Treffer: {', '.join(hits)}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="warn",
            message="Wenig/kein Rückbezug auf zentrale Begriffe der Forschungsfrage in der Diskussion (heuristisch).",
            evidence=f"Treffer: {', '.join(hits) or 'keine'} | Begriffe: {', '.join(terms)}"
        )]

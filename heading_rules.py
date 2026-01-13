from typing import List, Optional
from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


def _parse_number(num: str) -> List[int]:
    return [int(x) for x in num.split(".") if x.strip().isdigit()]


class HeadingHierarchyRule(Rule):
    """
    Check 9: Überschriftenhierarchie korrekt (1 → 1.1 → 1.1.1)
    Heuristik: Keine unlogischen Sprünge & Level passt zur Nummer.
    """
    id = "STRUCT-009"
    category = "Struktur"
    severity = "warn"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        numbered = [h for h in doc.headings if h.number]

        # Wenn gar keine nummerierten Überschriften: Info (nicht zwingend falsch)
        if len(numbered) == 0:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Keine nummerierten Überschriften gefunden (Check 9 übersprungen).",
                evidence=None
            )]

        findings: List[Finding] = []
        prev_parts: Optional[List[int]] = None

        for h in numbered:
            parts = _parse_number(h.number)

            # Level-Check: 1.2.3 -> level 3
            expected_level = len(parts)
            if h.level != expected_level:
                findings.append(Finding(
                    rule_id=self.id,
                    category=self.category,
                    severity="warn",
                    message=f"Überschriftenlevel passt evtl. nicht zur Nummerierung: '{h.number} {h.text}'",
                    evidence=f"Erwarteter Level: {expected_level}, erkannt: {h.level}"
                ))

            # Sprung-Check (sehr einfache Heuristik):
            # - Neue Nummer darf nicht um mehr als 1 am Ende springen.
            if prev_parts is not None and len(parts) == len(prev_parts):
                if parts[:-1] == prev_parts[:-1] and parts[-1] > prev_parts[-1] + 1:
                    findings.append(Finding(
                        rule_id=self.id,
                        category=self.category,
                        severity="warn",
                        message=f"Möglicher Nummerierungssprung: vorher {'.'.join(map(str, prev_parts))}, jetzt {h.number}",
                        evidence=f"Überschrift: {h.number} {h.text}"
                    ))

            prev_parts = parts

        if not findings:
            findings.append(Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Überschriftenhierarchie wirkt konsistent (heuristisch).",
                evidence=f"Nummerierte Überschriften: {len(numbered)}"
            ))

        return findings


class HeadingDepthRule(Rule):
    """
    Check 10: Gliederungstiefe nicht übermäßig (>4 Ebenen)
    """
    id = "STRUCT-010"
    category = "Struktur"
    severity = "info"

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        numbered = [h for h in doc.headings if h.number]
        if not numbered:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message="Keine nummerierten Überschriften gefunden (Check 10 übersprungen).",
                evidence=None
            )]

        max_depth = 0
        deepest = None
        for h in numbered:
            depth = len(_parse_number(h.number))
            if depth > max_depth:
                max_depth = depth
                deepest = h

        if max_depth > 4 and deepest:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity="info",
                message=f"Gliederungstiefe ist hoch: {max_depth} Ebenen (>4).",
                evidence=f"Tiefstes Beispiel: {deepest.number} {deepest.text}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message=f"Maximale Gliederungstiefe: {max_depth} Ebenen.",
            evidence=None
        )]

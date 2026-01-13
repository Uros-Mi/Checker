from typing import List, Optional

from .base import Rule
from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


class RequiredChaptersRule(Rule):
    """
    Check Nr. 7: Pflichtkapitel vorhanden
    """
    id = "STRUCT-007"
    category = "Struktur"
    severity = "error"

    REQUIRED = ["einleitung", "theorie", "methode", "ergebnisse", "diskussion", "fazit", "literatur"]

    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        present = set(doc.sections.keys())
        missing = [k for k in self.REQUIRED if k not in present]

        if missing:
            return [Finding(
                rule_id=self.id,
                category=self.category,
                severity=self.severity,
                message=f"Fehlende Pflichtkapitel: {', '.join(missing)}",
                evidence=f"Gefunden: {', '.join(sorted(present)) or 'keine'}"
            )]

        return [Finding(
            rule_id=self.id,
            category=self.category,
            severity="info",
            message="Alle Pflichtkapitel wurden gefunden.",
            evidence=f"Kapitel: {', '.join(sorted(present))}"
        )]

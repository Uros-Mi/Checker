from abc import ABC, abstractmethod
from typing import List, Optional

from ..models.document_model import DocumentModel, AIAnnotations
from ..models.findings import Finding


class Rule(ABC):
    id: str
    category: str
    severity: str  # "info" | "warn" | "error"
    needs_ai: bool = False

    @abstractmethod
    def run(self, doc: DocumentModel, ai: Optional[AIAnnotations] = None) -> List[Finding]:
        ...

from __future__ import annotations

from dataclasses import dataclass

from core.entities.conclusion import CoreConclusion
from core.verbalization.template_verbalizer import TemplateVerbalizer


@dataclass(slots=True)
class Verbalizer:
    template_verbalizer: TemplateVerbalizer | None = None

    def __post_init__(self) -> None:
        if self.template_verbalizer is None:
            self.template_verbalizer = TemplateVerbalizer()

    def verbalize(self, conclusion: CoreConclusion) -> str:
        return self.template_verbalizer.verbalize(conclusion)

"""What the pipeline needs from a model backend."""

from dataclasses import dataclass
from typing import Protocol


class AIError(RuntimeError):
    pass


@dataclass
class AIResult:
    markdown: str
    confidence: str  # high | medium | low
    notes: str
    cost_usd: float
    model: str
    input_tokens: int = 0  # incl. prompt-cache reads and writes
    output_tokens: int = 0


class Backend(Protocol):
    def run(
        self,
        *,
        model: str,
        effort: str,
        system: str,
        prompt: str,
        image: bytes | None = None,
        budget_usd: float | None = None,
    ) -> AIResult: ...

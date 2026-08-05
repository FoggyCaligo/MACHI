from __future__ import annotations

from abc import ABC, abstractmethod


class Repository(ABC):
    @abstractmethod
    def ping(self) -> None:
        """Cheap health check used by tests and bootstrap code."""

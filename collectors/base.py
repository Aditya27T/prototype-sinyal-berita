"""Base collector — milik Person 1."""
from abc import ABC, abstractmethod

from core.schemas import Post


class BaseCollector(ABC):
    platform: str = "unknown"

    @abstractmethod
    def collect(self, query: str, limit: int = 20) -> list[Post]:
        """Kumpulkan posting publik untuk satu query. Jangan bypass login/CAPTCHA."""
        raise NotImplementedError

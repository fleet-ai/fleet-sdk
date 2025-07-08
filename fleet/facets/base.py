"""Fleet SDK Base Facet Classes."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Facet(ABC):
    def __init__(self, scheme: str):
        self.scheme = scheme

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(scheme='{self.scheme}')"

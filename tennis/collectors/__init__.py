"""수집기 등록소. 새 수집기는 Collector를 상속하고 @register 로 등록한다."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..net import PoliteClient
from ..models import Facility, Slot


class Collector(ABC):
    name: str = "base"
    city: str = ""

    def __init__(self, client: PoliteClient):
        self.client = client
        self.errors: list[dict] = []   # 일부 실패는 여기에 쌓고 계속 진행

    @abstractmethod
    def collect(self, start: date, end: date) -> tuple[list[Facility], list[Slot]]:
        """start~end(포함) 기간의 시설 목록과 시간대별 예약현황."""


REGISTRY: dict[str, type[Collector]] = {}


def register(cls: type[Collector]) -> type[Collector]:
    REGISTRY[cls.name] = cls
    return cls


# 수집기 모듈을 불러와 등록시킨다.
from . import hwaseong, yongin  # noqa: E402,F401

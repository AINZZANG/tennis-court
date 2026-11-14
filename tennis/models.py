"""공통 데이터 형식. 모든 수집기는 이 형식으로 결과를 돌려준다."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum


class Status(str, Enum):
    AVAILABLE = "available"   # 예약 가능 (빈 코트)
    BOOKED = "booked"         # 예약됨
    CLOSED = "closed"         # 마감/운영 안 함
    PREOPEN = "preopen"       # 비어 있지만 아직 접수 시작 전 (용인 다음 달분 등)
    UNKNOWN = "unknown"


@dataclass
class Facility:
    id: str                    # "<source>:<원본 시설ID>"
    name: str
    city: str                  # "화성" | "용인"
    district: str = ""         # 동네/구 (동탄, 기흥, 수지 ...)
    address: str = ""
    source: str = ""           # 수집기 이름
    booking_url: str = ""
    courts: int | None = None
    indoor: bool | None = None
    lat: float | None = None
    lng: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class Slot:
    facility_id: str
    court: str                 # 코트명/번호 (없으면 "")
    date: str                  # YYYY-MM-DD
    start: str                 # HH:MM
    end: str                   # HH:MM
    status: Status
    price: int | None = None
    booking_url: str = ""
    checked_at: str = ""      # 이 칸을 실제로 확인한 시각 (돌아가며 갱신하는 사이트용)


@dataclass
class Snapshot:
    collected_at: str
    facilities: list[Facility]
    slots: list[Slot]
    errors: list[dict] = field(default_factory=list)

    @staticmethod
    def now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def to_dict(self) -> dict:
        return asdict(self)

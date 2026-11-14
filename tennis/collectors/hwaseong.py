"""화성특례시 통합예약시스템 (https://yeyak.hscity.go.kr) 테니스장 수집기.

- 목록: GET /1053/3026/stadiumList.do?searchKeyword=테니스  → 코트(stadiumIdx) 목록
- 현황: POST /stadium/stadiumReserveUseList.do  (stadiumIdx, searchYear, searchMonth)
        → 해당 코트의 한 달 치 시간대별 상태 JSON. 로그인 불필요. robots.txt: Allow /
- 응답에 예약자 이름(applicantNm)이 들어 있지만 저장하지 않는다.
"""
from __future__ import annotations

import html
import json
import re
import time
from datetime import date
from pathlib import Path

from . import Collector, register
from ..models import Facility, Slot, Status

BASE = "https://yeyak.hscity.go.kr"
LIST_URL = BASE + "/1053/3026/stadiumList.do"
USE_URL = BASE + "/stadium/stadiumReserveUseList.do"
DETAIL_URL = BASE + "/1053/3026/stadiumDetail.do?stadiumIdx={idx}"

CARD_RE = re.compile(
    r"fnDetail\('(\d+)'\); return false;\" class=\"sub-card-info-title-link\">(.*?)</a>"
    r"(.*?)(?=sub-card-btn-box)", re.S)
FIELD_RE = re.compile(
    r'sub-card-desc-title">(.*?)</dt>\s*<dd class="sub-card-desc-txt[^"]*">(.*?)</dd>', re.S)
COURT_RE = re.compile(r"\s*(\d+)\s*번\s*코트")
LATLNG_RE = re.compile(r"LatLng\(\s*'?(3[3-8]\.\d+)'?\s*,\s*'?(12[4-9]\.\d+)'?\s*\)")
GEO_CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "hwaseong_geo.json"
GEO_TTL = 7 * 24 * 3600


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def split_name(title: str) -> tuple[str, str, str]:
    """'[1부] 중동 테니스장 2번 코트(평일 오후)' → ('중동 테니스장', '2번 코트', '평일 오후')"""
    t = re.sub(r"^\[[^\]]*\]\s*", "", title)
    note = ""
    m = re.search(r"\(([^)]*)\)\s*$", t)
    if m:
        note, t = m.group(1), t[: m.start()].strip()
    m = COURT_RE.search(t)
    if m:
        return t[: m.start()].strip(), f"{m.group(1)}번 코트", note
    return t.strip(), "", note


def map_status(item: dict) -> Status:
    code = item.get("applyStatusCd")
    if code is None:
        return Status.AVAILABLE
    if code == "CLOSE":
        return Status.CLOSED
    # AP(승인/결제대기·완료), DE(보류), RC(의미 불확실) → 예약됨으로 취급
    return Status.BOOKED


@register
class HwaseongCollector(Collector):
    name = "hwaseong"
    city = "화성"

    def courts(self) -> list[dict]:
        page = self.client.get(LIST_URL, params={
            "searchKeyword": "테니스", "searchCondition": "stadiumNm", "searchYn": "Y",
            "searchTab": "all", "currentPageNo": 1, "recordCountPerPage": 300,
        })
        out = []
        for idx, title, body in CARD_RE.findall(page):
            title = _clean(title)
            if "테니스" not in title:
                continue
            fields = {_clean(k): _clean(v) for k, v in FIELD_RE.findall(body)}
            out.append({"idx": idx, "title": title, "fields": fields})
        return out

    def month(self, idx: str, year: int, month: int) -> list[dict]:
        raw = self.client.post(USE_URL, data={
            "stadiumIdx": idx, "searchYear": str(year), "searchMonth": f"{month:02d}"})
        return json.loads(raw).get("useCntList") or []

    def fill_coords(self, facilities: list[Facility]) -> None:
        """상세 페이지의 카카오맵 중심좌표로 시설 위치를 채운다 (시설당 1건, 7일 캐시)."""
        try:
            cache = json.loads(GEO_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
        now = time.time()
        for fac in facilities:
            ent = cache.get(fac.id)
            if not ent or now - ent.get("_at", 0) > GEO_TTL:
                idx = next(iter(fac.extra.get("court_ids", {}).values()), None)
                if not idx:
                    continue
                try:
                    m = LATLNG_RE.search(self.client.get(DETAIL_URL.format(idx=idx)))
                    ent = {"lat": float(m.group(1)), "lng": float(m.group(2))} if m else {}
                    ent["_at"] = now
                    cache[fac.id] = ent
                except Exception as e:
                    self.errors.append({"source": self.name, "facility": fac.id, "stage": "coords", "error": repr(e)})
                    continue
            fac.lat, fac.lng = ent.get("lat"), ent.get("lng")
        GEO_CACHE.parent.mkdir(parents=True, exist_ok=True)
        GEO_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    def collect(self, start: date, end: date):
        months, (y, m) = [], (start.year, start.month)
        while (y, m) <= (end.year, end.month):
            months.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        facilities: dict[str, Facility] = {}
        slots: list[Slot] = []
        for c in self.courts():
            fac_name, court, note = split_name(c["title"])
            fid = f"{self.name}:{fac_name}"
            fac = facilities.get(fid)
            if fac is None:
                fac = facilities[fid] = Facility(
                    id=fid, name=fac_name, city=self.city, source=self.name,
                    booking_url=LIST_URL, courts=0,
                    extra={"operator": c["fields"].get("기관", ""),
                           "fee": c["fields"].get("비용", ""),
                           "open_local": c["fields"].get("관내", ""),
                           "open_outside": c["fields"].get("관외", ""),
                           "court_ids": {}})
            fac.courts += 1
            court_label = court + (f" ({note})" if note else "")
            fac.extra["court_ids"][court_label] = c["idx"]
            url = DETAIL_URL.format(idx=c["idx"])
            for y, m in months:
                try:
                    items = self.month(c["idx"], y, m)
                except Exception as e:
                    self.errors.append({"source": self.name, "court": c["title"],
                                        "month": f"{y}-{m:02d}", "error": repr(e)})
                    continue
                for it in items:
                    d = it.get("sorDate") or ""
                    if not (start.isoformat() <= d <= end.isoformat()):
                        continue
                    slots.append(Slot(
                        facility_id=fid, court=court_label, date=d,
                        start=it.get("stadiumBeginHm") or "", end=it.get("stadiumEndHm") or "",
                        status=map_status(it), booking_url=url))
        self.fill_coords(list(facilities.values()))
        return list(facilities.values()), slots

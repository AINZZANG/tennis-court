"""용인특례시 공공체육시설 통합예약 (https://publicsports.yongin.go.kr) 테니스장 수집기.

- 목록: 예약 항목(코트×월×예약구분)별 접수 상태, 이용기간, 접수기간  (6시간마다)
- 상세: 운영시간, 사용료, 예약 오픈 일정                              (하루 1번)
- 시간표: POST selectRegistTimeByChosenDateFcltyRceptResveApply.do (resveId, dateVal=YYYYMMDD)
          → 로그인 없이 그날 예약 가능 시간(resveTmList)과 예약 완료 시간(fcltRceptRsvctmTime)

주의: 용인 사이트는 짧은 시간에 요청이 몰리면 IP를 차단한다고 알려져 있다.
그래서 요청 간격 5초(net.py), 한 번 실행에 시간표 요청 최대 SLOT_BUDGET 건,
가까운 날짜·주말을 먼저 갱신하고 나머지는 돌아가며 갱신, 이상 응답이 오면 1시간 쉰다.
"""
from __future__ import annotations

import html
import os
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import Collector, register
from ..models import Facility, Slot, Status

BASE = "https://publicsports.yongin.go.kr/publicsports/sports"
LIST_URL = BASE + "/selectFcltyRceptResveListU.do"
DETAIL_URL = BASE + "/selectFcltyRceptResveViewU.do?key=4236&resveId={rid}"
SLOT_URL = BASE + "/selectRegistTimeByChosenDateFcltyRceptResveApply.do"
PAGE_UNIT = 8          # 사이트가 페이지당 8개로 고정
MAX_PAGES = 60         # 안전장치
DETAIL_TTL = 24 * 3600
ITEMS_TTL = 6 * 3600
# 한 번 실행에 보내는 시간표 요청 상한. PC 기본값은 보수적으로, GitHub Actions 에서는 env 로 올린다.
SLOT_BUDGET = int(os.environ.get("YONGIN_SLOT_BUDGET", "150"))
TTL_NEAR = 50 * 60     # 매시간 갱신 (빈자리가 있거나, 3일 이내, 주말)
TTL_FAR = int(os.environ.get("YONGIN_TTL_FAR_MIN", "170")) * 60   # 4일 이후 평일
TTL_FULL_FAR = 170 * 60  # 4일 이후인데 꽉 찼거나 마감인 날: 빈자리가 다시 생길 일이 드물어 약 3시간마다
BLOCK_SEC = 3600       # 이상 응답 시 쉬는 시간
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
CACHE = CACHE_DIR / "yongin_detail.json"
ITEMS_CACHE = CACHE_DIR / "yongin_items.json"
SLOTS_CACHE = CACHE_DIR / "yongin_slots.json"
BLOCK_FILE = CACHE_DIR / "yongin_block.json"


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _hm(s: str) -> str:
    """'8:00' → '08:00'"""
    s = s.strip()
    h, _, m = s.partition(":")
    return f"{int(h):02d}:{(m or '00')[:2]}" if h.isdigit() else s


def parse_slots(js: dict) -> dict:
    """시간표 응답 → {"a": [[start,end],...], "b": [[start,end],...], "closed": bool}

    - resveTmList: 지금 예약 가능한 시간
    - fcltRceptRsvctmTime: rsvctmId > 0 인 것만 실제 예약. rsvctmId == 0 인 기록은 0~24시를
      1시간 간격으로 채운 자리표시(그날 예약을 받지 않음)라서 예약으로 치지 않는다.
    예약자 정보는 저장하지 않는다.
    """
    avail, booked, placeholder = [], [], False
    for t in js.get("resveTmList") or []:
        a, _, b = (t.get("timeContent") or "").partition("~")
        if a.strip():
            avail.append([_hm(a), _hm(b)])
    for t in js.get("fcltRceptRsvctmTime") or []:
        if not t.get("rsvctmId"):
            placeholder = True
            continue
        if t.get("rsvctmStts") and "CANCL" in t["rsvctmStts"]:
            continue
        a, _, b = (t.get("useTm") or "").partition("~")
        if a.strip():
            booked.append([_hm(a), _hm(b)])
    avail = sorted({tuple(x) for x in avail})
    taken = {tuple(x) for x in booked} - set(avail)
    return {"a": [list(x) for x in avail], "b": [list(x) for x in sorted(taken)],
            "closed": placeholder and not avail and not taken}

ITEM_SPLIT = 'class="reserve_box_item"'


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_list(page: str) -> list[dict]:
    rows = []
    for it in page.split(ITEM_SPLIT)[1:]:
        rid = re.search(r"resveId=(\d+)", it)
        title = re.search(r'class="reserve_title">\s*(.*?)<div class="reserve_position">\s*(.*?)</div>',
                          it, re.S)
        if not (rid and title):
            continue
        state = re.search(r'class="reserve_state[^"]*"[^>]*>(.*?)<', it, re.S)
        kind = re.search(r'class="above_item">(.*?)<', it)
        li = {k: _clean(v) for k, v in re.findall(r"<li>(\S+?)\s*:\s*(.*?)</li>", it, re.S)}
        rows.append({
            "resve_id": rid.group(1),
            "title": _clean(title.group(1)),
            "area": _clean(title.group(2)),            # "수지구, 풍덕천1동"
            "state": _clean(state.group(1)) if state else "",
            "kind": _clean(kind.group(1)) if kind else "",   # 일반예약/시민우선/구민우선
            "use_period": li.get("이용기간", ""),
            "accept_period": li.get("접수기간", ""),
        })
    return rows


def split_title(title: str) -> tuple[str, str]:
    """'[유료]기흥 테니스장(A코트)_11월' → ('기흥 테니스장', 'A코트')"""
    t = re.sub(r"^\s*[\[(]\s*(유료|무료)\s*[\])]\s*", "", title)
    t = re.sub(r"_\s*\d+\s*월.*$", "", t).strip()
    court = ""
    m = re.search(r"\(([^)]*코트[^)]*)\)\s*$", t)
    if m:
        court, t = m.group(1), t[: m.start()].strip()
    else:
        m = re.search(r"\s*([A-Za-z0-9]+\s*코트)\s*$", t)
        if m:
            court, t = m.group(1).replace(" ", ""), t[: m.start()].strip()
    m = re.search(r"(테니스장)\s*([A-Za-z가-힣0-9]+존)$", t)   # '포곡대교하부 테니스장B존'
    if m:
        court = f"{m.group(2)} {court}".strip()
        t = t[: m.start(2)].strip()
    return re.sub(r"\s+", " ", t.replace("테니스장", " 테니스장")).strip(), court


def parse_detail(page: str) -> dict:
    body = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", "", page)
    text = _clean(body)
    # 시설별 자유 서술 영역만 잘라낸다 (메뉴/푸터 제외)
    i = text.find("찾아오시는 길")
    j = text.find("목록 콘텐츠 만족도")
    info = text[i + len("찾아오시는 길"): j if j > i else None].strip() if i >= 0 else ""

    def grab(src: str, pattern: str, n: int = 160) -> str:
        m = re.search(pattern, src)
        return re.sub(r"\s+", " ", m.group(1)).strip(" -")[:n] if m else ""

    return {
        "address": grab(text, r"장소\s+(.*?)\s+접수기간", 80),
        "hours": grab(info, r"(?:운영시간|사용시간|이용시간)\s*[:：]\s*(.*?)(?=○|※|▶|◆|$)"),
        "fee": grab(info, r"(?:사용료|이용료|이용요금|요금)[^:：]{0,12}[:：]\s*(.*?)(?=○|▶|◆|$)", 200),
        "schedule": grab(info, r"(?:운영방식|예약일시|예약일정)\s*[:：]?\s*(.*?)(?=※|○|▶|◆|$)", 200),
        "contact": grab(text, r"문의전화\s+(.*?)\s+예약하기", 80),
        "same_day": "당일 예약 불가" in info or "당일예약 불가" in info,
        "info": info[:2000],
    }


@register
class YonginCollector(Collector):
    name = "yongin"
    city = "용인"

    def _load_cache(self) -> dict:
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_cache(self, cache: dict) -> None:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    def items(self) -> list[dict]:
        cached = _read_json(ITEMS_CACHE, {})
        if cached.get("rows") and time.time() - cached.get("_at", 0) < ITEMS_TTL:
            return cached["rows"]
        rows = self._fetch_items()
        if rows:
            _write_json(ITEMS_CACHE, {"_at": time.time(), "rows": rows})
        return rows or cached.get("rows", [])

    # ---- 시간표 ----
    def _blocked(self) -> bool:
        return time.time() < _read_json(BLOCK_FILE, {}).get("until", 0)

    def _fetch_slot(self, rid: str, day: date) -> dict:
        raw = self.client.post(SLOT_URL, data={"dateVal": day.strftime("%Y%m%d"), "resveId": rid},
                               headers={"X-Requested-With": "XMLHttpRequest"})
        js = json.loads(raw)   # JSON 이 아니면 예외 → 차단/오류로 간주
        if not isinstance(js, dict) or ("resveTmList" not in js and "fcltRceptRsvctmTime" not in js):
            raise ValueError("unexpected response")
        return parse_slots(js)

    def refresh_slots(self, tasks: list[tuple[str, date]]) -> dict:
        """우선순위대로 정렬된 (resveId, 날짜) 목록을 예산 안에서 갱신. 캐시를 돌려준다."""
        cache = _read_json(SLOTS_CACHE, {})
        today = date.today()
        # 지난 날짜 캐시 정리
        cache = {k: v for k, v in cache.items() if k.split("|")[1] >= today.isoformat()}
        if self._blocked():
            self.errors.append({"source": self.name, "error": "IP 차단 의심으로 쉬는 중 — 시간표 갱신 건너뜀"})
            return cache
        now = time.time()

        def due(rid: str, d: date) -> float:
            ent = cache.get(f"{rid}|{d.isoformat()}")
            ahead = (d - today).days
            ttl = TTL_NEAR if ahead <= 3 or d.weekday() >= 5 else TTL_FAR
            if ent and ahead > 3 and not ent.get("a"):
                ttl = max(ttl, TTL_FULL_FAR)
            age = now - ent["_at"] if ent else 10 ** 9
            return age - ttl          # > 0 이면 갱신 필요

        todo = [(rid, d) for rid, d in tasks if due(rid, d) > 0]
        todo.sort(key=lambda t: ((t[1] - today).days > 3 and t[1].weekday() < 5, (t[1] - today).days))
        fails = done = 0
        for rid, d in todo[:SLOT_BUDGET]:
            try:
                cache[f"{rid}|{d.isoformat()}"] = {**self._fetch_slot(rid, d), "_at": time.time()}
                fails = 0
                done += 1
            except Exception as e:
                fails += 1
                self.errors.append({"source": self.name, "court": rid, "date": d.isoformat(), "error": repr(e)[:200]})
                if fails == 1:      # 첫 실패 → 30초 쉬고 간격을 두 배로 늘려 계속
                    host = "publicsports.yongin.go.kr"
                    cur = self.client.HOST_INTERVALS.get(host, 5.0)
                    self.client.HOST_INTERVALS = {**self.client.HOST_INTERVALS, host: max(cur * 2, 5.0)}
                    time.sleep(30)
                if fails >= 2:      # 연속 실패 → 차단 의심, 즉시 멈추고 쉰다
                    _write_json(BLOCK_FILE, {"until": time.time() + BLOCK_SEC, "reason": repr(e)[:200]})
                    self.errors.append({"source": self.name, "error": f"연속 실패로 {BLOCK_SEC // 60}분간 중단"})
                    break
            if done and done % 50 == 0:
                _write_json(SLOTS_CACHE, cache)   # 중간 저장
        _write_json(SLOTS_CACHE, cache)
        self.stats = {"due": len(todo), "fetched": done}
        return cache

    def _fetch_items(self) -> list[dict]:
        rows, seen = [], set()
        for page_no in range(1, MAX_PAGES + 1):
            page = self.client.get(LIST_URL, params={
                "key": 4236, "pageUnit": PAGE_UNIT, "pageIndex": page_no,
                "checkSearchMonthNow": "false", "searchFcltyFieldNm": "ITEM_01"})
            got = [r for r in parse_list(page) if r["resve_id"] not in seen]
            if not got:
                break
            seen.update(r["resve_id"] for r in got)
            rows.extend(got)
        return rows

    def collect(self, start: date, end: date):
        rows = self.items()
        cache = self._load_cache()
        now = time.time()
        facilities: dict[str, Facility] = {}
        for r in rows:
            if "테니스" not in r["title"]:
                continue
            # 이미 끝난 기간(마감 + 이용기간 종료)은 버린다
            use_end = r["use_period"].split("~")[-1].strip()
            if use_end and use_end < start.isoformat():
                continue
            name, court = split_title(r["title"])
            fid = f"{self.name}:{name}"
            gu, _, dong = r["area"].partition(",")
            fac = facilities.get(fid)
            if fac is None:
                fac = facilities[fid] = Facility(
                    id=fid, name=name, city=self.city, district=f"{gu.strip()} {dong.strip()}".strip(),
                    source=self.name, booking_url=DETAIL_URL.format(rid=r["resve_id"]),
                    extra={"items": [], "paid": "유료" in r["title"]})
            url = DETAIL_URL.format(rid=r["resve_id"])
            fac.extra["items"].append({**r, "court": court, "url": url})

        # 상세정보: 시설당 대표 항목 1개만, 하루 1번
        for fac in facilities.values():
            items = fac.extra["items"]
            rep = next((i for i in items if i["state"] == "접수중"), items[0])
            fac.booking_url = rep["url"]
            c = cache.get(rep["resve_id"])
            if not c or now - c.get("_at", 0) > DETAIL_TTL:
                try:
                    c = {**parse_detail(self.client.get(rep["url"])), "_at": now}
                    cache[rep["resve_id"]] = c
                except Exception as e:
                    self.errors.append({"source": self.name, "facility": fac.id, "error": repr(e)})
                    c = c or {}
            fac.address = c.get("address", "")
            fac.extra.update({k: c.get(k) for k in ("hours", "fee", "schedule", "contact", "same_day")})
            fac.courts = len({i["court"] for i in items}) or None
        self._save_cache(cache)

        # ---- 시간표: 날짜별로 "접수중인 일반예약" 항목을 찾아 조회 ----
        first = max(start, date.today() + timedelta(days=1))   # 당일 예약 불가 → 내일부터
        days = [first + timedelta(days=i) for i in range((end - first).days + 1)]
        tasks: list[tuple[str, date]] = []
        meta: dict[str, tuple[str, str, str]] = {}            # rid -> (fid, court, url)
        for fac in facilities.values():
            for it in fac.extra["items"]:
                if it["kind"] != "일반예약" or it["state"] != "접수중":
                    continue
                a, _, b = (x.strip() for x in it["use_period"].partition("~"))
                meta[it["resve_id"]] = (fac.id, it["court"] or "단독", it["url"])
                tasks += [(it["resve_id"], d) for d in days if a <= d.isoformat() <= b]
        slot_cache = self.refresh_slots(tasks)

        slots: list[Slot] = []
        for rid, d in tasks:
            ent = slot_cache.get(f"{rid}|{d.isoformat()}")
            if not ent:
                continue
            fid, court, url = meta[rid]
            checked = datetime.fromtimestamp(ent["_at"]).astimezone().isoformat(timespec="minutes")
            if ent.get("closed"):
                fac = facilities[fid]
                fac.extra.setdefault("closed_days", {}).setdefault(court, []).append(d.isoformat())
                continue
            for code, status in (("a", Status.AVAILABLE), ("b", Status.BOOKED)):
                for s_, e_ in ent.get(code, []):
                    slots.append(Slot(facility_id=fid, court=court, date=d.isoformat(), start=s_, end=e_,
                                      status=status, booking_url=url, checked_at=checked))
        return list(facilities.values()), slots

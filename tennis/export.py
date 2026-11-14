"""data/snapshot.json → web/data.json (모바일용 압축 형식).

형식:
{
  "collected_at": "...",
  "facilities": [{id, name, city, district, address, courts, booking_url, extra}],
  "courts": [[facility_index, court_label, booking_url], ...],
  "slots": [[court_index, "MM-DD", "HH:MM", "HH:MM", "a|b|c|u"], ...]   # 연도는 date_year
  "date_year": {"MM-DD": "YYYY"},
  "errors": n
}
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = {"available": "a", "booked": "b", "closed": "c", "unknown": "u"}


def export(src: Path = ROOT / "data" / "snapshot.json", dst: Path = ROOT / "web" / "data.json") -> int:
    snap = json.loads(src.read_text(encoding="utf-8"))
    facs = snap["facilities"]
    fidx = {f["id"]: i for i, f in enumerate(facs)}
    for f in facs:                      # 웹에서 안 쓰는 큰 필드 제거
        f["extra"].pop("court_ids", None)
        f["extra"].pop("info", None)
        for it in f["extra"].get("items", []):
            for k in ("title", "area"):
                it.pop(k, None)
    courts, cidx, slots, years, checked = [], {}, [], {}, {}
    for s in snap["slots"]:
        key = (s["facility_id"], s["court"])
        if key not in cidx:
            cidx[key] = len(courts)
            courts.append([fidx[s["facility_id"]], s["court"], s["booking_url"]])
        y, md = s["date"][:4], s["date"][5:]
        years[md] = y
        slots.append([cidx[key], md, s["start"], s["end"], CODE.get(s["status"], "u")])
        if s.get("checked_at"):           # 코트×날짜별 확인 시각 (돌아가며 갱신하는 용인)
            checked[f"{cidx[key]}|{md}"] = s["checked_at"]
    for f in facs:                        # 예약 마감일의 연도도 기록
        for days in f["extra"].get("closed_days", {}).values():
            for iso in days:
                years[iso[5:]] = iso[:4]
    out = {"collected_at": snap["collected_at"], "facilities": facs, "courts": courts,
           "slots": slots, "date_year": years, "checked": checked,
           "errors": len(snap.get("errors", []))}
    dst.parent.mkdir(exist_ok=True)
    tmp = dst.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(dst)
    return dst.stat().st_size


if __name__ == "__main__":
    print(f"web/data.json {export() / 1024:.0f} KB")

"""수집 결과(snapshot) → 웹용 data.json (모바일용 압축 형식).

사용:
  python -m tennis.export                                   # data/snapshot.json → web/data.json
  python -m tennis.export --merge a.json b.json --out x.json  # 도시별 snapshot 여러 개를 합쳐서

형식:
{
  "collected_at": "...",                 # 가장 최근 수집 시각
  "collected": {"화성": "...", "용인": "..."},   # 도시별 수집 시각
  "facilities": [{id, name, city, district, address, courts, booking_url, extra}],
  "courts": [[facility_index, court_label, booking_url], ...],
  "slots": [[court_index, "MM-DD", "HH:MM", "HH:MM", "a|b|c|p|u"], ...],  # p = 접수 시작 전, 연도는 date_year
  "date_year": {"MM-DD": "YYYY"},
  "checked": {"court_index|MM-DD": "iso"},
  "errors": n
}
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = {"available": "a", "booked": "b", "closed": "c", "preopen": "p", "unknown": "u"}


def build(snaps: list[dict]) -> dict:
    facs, slots_in, errors, collected = [], [], 0, {}
    for snap in snaps:
        facs += snap["facilities"]
        slots_in += snap["slots"]
        errors += len(snap.get("errors", []))
        for city in {f["city"] for f in snap["facilities"]}:
            collected[city] = snap["collected_at"]
    fidx = {f["id"]: i for i, f in enumerate(facs)}
    for f in facs:                      # 웹에서 안 쓰는 큰 필드 제거
        f["extra"].pop("court_ids", None)
        f["extra"].pop("info", None)
        for it in f["extra"].get("items", []):
            for k in ("title", "area"):
                it.pop(k, None)
    courts, cidx, slots, years, checked = [], {}, [], {}, {}
    for s in slots_in:
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
    return {"collected_at": max(collected.values(), default=""), "collected": collected,
            "facilities": facs, "courts": courts, "slots": slots, "date_year": years,
            "checked": checked, "errors": errors}


def write(out: dict, dst: Path) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(dst)
    return dst.stat().st_size


def export(src: Path = ROOT / "data" / "snapshot.json", dst: Path = ROOT / "web" / "data.json") -> int:
    return write(build([json.loads(src.read_text(encoding="utf-8"))]), dst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", nargs="*", help="합칠 snapshot 파일들 (없는 파일은 건너뜀)")
    ap.add_argument("--out", default=str(ROOT / "web" / "data.json"))
    args = ap.parse_args()
    if args.merge is None:
        size = export(dst=Path(args.out))
    else:
        snaps = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.merge if Path(p).exists()]
        size = write(build(snaps), Path(args.out))
    print(f"{args.out} {size / 1024:.0f} KB")


if __name__ == "__main__":
    main()

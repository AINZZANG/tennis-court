"""모든 수집기를 돌려 data/snapshot.json 을 만든다.

사용: python3 -m tennis.collect [--days 14] [--only hwaseong]
"""
from __future__ import annotations

import argparse
import json
import traceback
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from . import collectors as C
from .net import PoliteClient
from .models import Snapshot, Status

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def run(days: int, only: set[str] | None) -> Snapshot:
    client = PoliteClient()
    snap = Snapshot(collected_at=Snapshot.now(), facilities=[], slots=[])
    start = date.today()
    end = start + timedelta(days=days - 1)
    for name, cls in C.REGISTRY.items():
        if only and name not in only:
            continue
        col = cls(client)
        try:
            facs, slots = col.collect(start, end)
            snap.facilities.extend(facs)
            snap.slots.extend(slots)
        except Exception as e:  # 한 사이트 실패가 전체를 막지 않게
            snap.errors.append({"source": name, "error": repr(e),
                                "trace": traceback.format_exc(limit=3)})
        snap.errors.extend(col.errors)
    return snap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None

    snap = run(args.days, only)
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "snapshot.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(snap), ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(out)  # 대시보드가 반쯤 쓴 파일을 읽지 않도록
    avail = sum(1 for s in snap.slots if s.status == Status.AVAILABLE)
    print(f"시설 {len(snap.facilities)}곳, 슬롯 {len(snap.slots)}개 (빈 슬롯 {avail}), "
          f"오류 {len(snap.errors)}건 → {out}")
    for e in snap.errors[:5]:
        print("  오류:", e.get("source"), e.get("court", ""), e.get("error"))


if __name__ == "__main__":
    main()

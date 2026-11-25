import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "archive" / "R8"))
from fetch_contract import master_calendar  # noqa: E402

cal = set(master_calendar())
for ex in sys.argv[1:]:
    p = ROOT / "archive" / "R8" / "raw_contract" / f"MANIFEST_{ex}.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    ok = {d for d, v in m.items() if v.get("status") == "ok"}
    years = sorted({d[:4] for d in m})
    for y in years:
        cy = {d for d in cal if d[:4] == y}
        my = {d for d in m if d[:4] == y}
        print(ex, y, "master", len(cy), "ok", len({d for d in ok if d[:4] == y}), "ok&master", len({d for d in ok if d[:4] == y} & cy),
              "master-not-ok", len(cy - ok), "ok-not-master", len({d for d in ok if d[:4] == y} - cal))
        miss = sorted(cy - ok)
        if miss and len(miss) <= 60:
            print("   master-not-ok:", miss)
        extra = sorted({d for d in ok if d[:4] == y} - cal)
        if extra:
            print("   ok-not-in-master:", extra)

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
d = json.loads((ROOT / "archive/R8/long_coverage_probe2.json").read_text(encoding="utf-8"))
print("member:", json.dumps(d["member_txt_by_exchange"], ensure_ascii=False))
print("dce_dl files:", d["member_dce_dl_files"])
print("earliest contract first bar:", {k: v["first_bar"] for k, v in d["earliest_contract_first_bar"].items()})
for sub in ("sina", "akshare", "warehouse"):
    base = ROOT / ".cache" / sub
    dirs = sorted(p.name for p in base.iterdir() if p.is_dir())
    files = sorted(p.name for p in base.iterdir() if p.is_file())
    print(sub, "subdirs:", dirs[:12], "files:", files[:6])
    if dirs:
        s = base / dirs[0]
        print("  sample in", dirs[0], [p.name for p in list(s.iterdir())[:6]])

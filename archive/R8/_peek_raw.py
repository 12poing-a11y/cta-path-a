import gzip
import json
from pathlib import Path

RAW = Path(__file__).resolve().parent / "raw_contract"
j = json.loads(gzip.decompress((RAW / "shfe" / "20240102.gz").read_bytes()))
print("shfe top keys:", list(j.keys()))
rows = j["o_curinstrument"]
print(len(rows))
for r in rows[:2]:
    print(r)
print([ (r["PRODUCTID"].strip(), r["DELIVERYMONTH"]) for r in rows if r["PRODUCTGROUPID"].strip() in ("ag","sp","ss")][:12])
print("non _f / odd products:", sorted({r["PRODUCTID"].strip() for r in rows if not r["PRODUCTID"].strip().endswith("_f")})[:15])
print("odd delivery months:", sorted({r["DELIVERYMONTH"] for r in rows if not str(r["DELIVERYMONTH"]).isdigit()})[:10])
j16 = json.loads(gzip.decompress((RAW / "shfe" / "20160104.gz").read_bytes()))
print("2016 sample:", j16["o_curinstrument"][0])
print("2016 fields same:", set(j16["o_curinstrument"][0]) == set(rows[0]))
for d in ("20160104", "20220104"):
    t = gzip.decompress((RAW / "czce" / f"{d}.gz").read_bytes())
    try:
        s = t.decode("utf-8")
    except UnicodeDecodeError:
        s = t.decode("gbk", "ignore")
    lines = s.splitlines()
    print(d, lines[0][:60].strip(), "|", lines[1][:120])
    print([l[:130] for l in lines if l.strip().startswith(("SR", "SA"))][:3])
    print("tail:", [l[:100] for l in lines[-3:]])
d = json.loads(gzip.decompress((RAW / "dce" / "20240102.gz").read_bytes()))
print("dce:", d["cols"], d["rows"][:2], len(d["rows"]))

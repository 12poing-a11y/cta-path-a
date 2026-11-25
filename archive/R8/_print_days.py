import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_contract import master_calendar  # noqa: E402

cal = master_calendar()
for y in range(2017, 2026):
    print(y, ",".join(d[5:7] + d[8:10] for d in cal if d[:4] == str(y)))

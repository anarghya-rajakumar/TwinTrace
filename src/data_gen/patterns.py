"""Parser for IBM's HI-Small_Patterns.txt (BEGIN/END LAUNDERING ATTEMPT blocks)."""
from __future__ import annotations

from pathlib import Path


def parse_ibm_patterns(path) -> list[dict]:
    """Return [{typology, rows:[{ts, src, dst, amt}]}]. Rows are the raw CSV lines inside each block:
    Timestamp,FromBank,Account,ToBank,Account,AmtReceived,RecvCur,AmtPaid,PayCur,Format,IsLaundering."""
    attempts: list[dict] = []
    cur = None
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("BEGIN LAUNDERING ATTEMPT"):
            typ = line.split("-", 1)[1].strip() if "-" in line else "UNKNOWN"
            typ = typ.split(":")[0].strip()
            cur = dict(typology=typ, rows=[])
        elif line.startswith("END LAUNDERING ATTEMPT"):
            if cur and cur["rows"]:
                attempts.append(cur)
            cur = None
        elif cur is not None:
            p = line.split(",")
            if len(p) >= 9:
                cur["rows"].append(dict(ts=p[0], src=f"{p[1]}|{p[2]}", dst=f"{p[3]}|{p[4]}", amt=float(p[7])))
    return attempts

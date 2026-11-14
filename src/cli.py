"""Command line entry point: python -m src.cli {setup,data,run,test,web,demo}.  The Makefile wraps these."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

from .config import ROOT, artifacts_dir, processed_dir


def cmd_setup(_):
    return subprocess.call([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])


def cmd_data(_):
    from .data_gen.build import build
    build()
    return 0


def cmd_run(_):
    if not (processed_dir() / "transactions.parquet").exists():
        cmd_data(_)
    from .pipeline import run_pipeline
    run_pipeline()
    print((artifacts_dir() / "results.md").read_text(encoding="utf-8").split("## Every method")[0])
    return 0


def cmd_test(_):
    return subprocess.call([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests")])


def cmd_web(args):
    """The interactive investigation board (FastAPI + the prebuilt React app in web/dist)."""
    import threading
    import webbrowser

    import uvicorn
    if not (artifacts_dir() / "alerts_all.json").exists():
        print("[web] no artifacts yet: generating them once (about a minute)")
        cmd_run(args)
    if not (ROOT / "web" / "dist" / "index.html").exists():
        print("[web] web/dist is missing. Build it once with: cd web && npm install && npm run build")
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"[web] TwinTrace board at {url}  (Ctrl+C to stop)")
    uvicorn.run("src.server:app", host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def cmd_demo(args):
    """Offline demo from the precomputed artifacts. --check starts the API in-process and exercises every endpoint."""
    if not args.check:
        return cmd_web(args)
    t = time.time()
    if not (artifacts_dir() / "alerts_all.json").exists():
        print("[demo] no precomputed artifacts yet: generating them once (about a minute)")
        cmd_run(args)
    from fastapi.testclient import TestClient

    from .server import create_app
    with TestClient(create_app()) as c:
        b = c.get("/api/board").json()
        a = b["alerts"][0]["id"]
        acc = b["nodes"][b["alerts"][0]["acc"][0]]["id"]
        checks = {"board": bool(b["nodes"]), "case": c.get(f"/api/alert/{a}").status_code == 200,
                  "trace": c.get("/api/trace", params=dict(account=acc)).status_code == 200,
                  "whatif": c.get("/api/whatif").status_code == 200}
        r = c.post("/api/plant", json=dict(typology="round_trip", stealth=0.5))
        checks["plant"] = r.status_code == 200
        c.post("/api/reset")
    ok = all(checks.values())
    print(f"[demo] {'passed' if ok else 'FAILED'} {checks} in {time.time() - t:.1f}s")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="twintrace")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("setup", cmd_setup), ("data", cmd_data), ("run", cmd_run), ("test", cmd_test)]:
        sub.add_parser(name).set_defaults(fn=fn)
    w = sub.add_parser("web")
    w.add_argument("--port", type=int, default=8000)
    w.add_argument("--no-browser", action="store_true")
    w.set_defaults(fn=cmd_web)
    d = sub.add_parser("demo")
    d.add_argument("--port", type=int, default=8000)
    d.add_argument("--no-browser", action="store_true")
    d.add_argument("--check", action="store_true", help="exercise every API endpoint in-process and exit")
    d.set_defaults(fn=cmd_demo)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

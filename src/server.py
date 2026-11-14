"""TwinTrace web server: JSON API + the built front end. Run: python -m src.cli web"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT
from .web import board as board_mod, inject, trace as trace_mod, whatif
from .web.state import get_state

WEB_DIST = ROOT / "web" / "dist"


class PlantReq(BaseModel):
    typology: str
    stealth: float = 0.6
    size: int | None = None
    start_day: float | None = None


def create_app() -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app):
        st = get_state()                       # warm up: load data, model and the first board payload before any request
        with st.lock:
            cache["key"], cache["val"] = (len(st.injected), len(st.alerts)), board_mod.build_board(st)
        yield

    cache: dict = {}
    app = FastAPI(title="TwinTrace", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        st = get_state()
        return dict(ok=True, alerts=len(st.alerts), injected=len(st.injected))

    @app.get("/api/board")
    def board():
        st = get_state()
        with st.lock:
            key = (len(st.injected), len(st.alerts))
            if cache.get("key") != key:
                cache["key"], cache["val"] = key, board_mod.build_board(st)
            return cache["val"]

    @app.get("/api/alert/{alert_id}")
    def alert(alert_id: str):
        st = get_state()
        a = st.alert_by_id.get(alert_id)
        if a is None:
            raise HTTPException(404, "unknown alert")
        from .explain.flow import alert_flow
        flow = alert_flow(a, st.data.tx, st.data.trades, st.data.owner_of)
        tx = st.data.tx
        events = []
        if a["tx_ids"]:
            sub = tx[tx["tx_id"].isin(a["tx_ids"])].sort_values("t")
            events += [dict(t=round(r.t / 86400, 4), src=r.sender, dst=r.receiver, amt=float(r.amount), kind="money") for r in sub.itertuples()]
        if a["trade_ids"]:
            sub = st.data.trades[st.data.trades["trade_id"].isin(a["trade_ids"])].sort_values("t")
            events += [dict(t=round(r.t / 86400, 4), src=r.seller, dst=r.buyer, amt=float(r.notional), kind="trade",
                            price=float(r.price), ref=float(r.ref_price), qty=int(r.qty)) for r in sub.itertuples()]
        events.sort(key=lambda e: e["t"])
        return dict(alert=a, flow=dict(pos={k: list(v) for k, v in flow["pos"].items()}, role=flow["role"], edges=flow["edges"]),
                    events=events)

    @app.get("/api/trace")
    def trace(account: str, depth: int = 3, per_node: int = 5, direction: str = "both"):
        st = get_state()
        try:
            return trace_mod.trace(st, account, min(depth, 5), min(per_node, 12), direction)
        except KeyError:
            raise HTTPException(404, "unknown account")

    @app.get("/api/whatif")
    def what_if(money: float | None = None, trade: float | None = None, split: str = "test"):
        st = get_state()
        with st.lock:
            return whatif.metrics_at(st, money, trade, split)

    @app.get("/api/search")
    def search(q: str, limit: int = 8):
        st = get_state()
        q = q.strip().upper()
        out = [dict(type="alert", id=a["alert_id"], label=f"{a['alert_id']} · {a['typology_name']}") for a in st.alerts
               if q in a["alert_id"].upper()][:limit]
        if len(q) >= 3:
            out += [dict(type="account", id=k, label=k) for k in st.data.owner_of if q in k][: limit - len(out)]
        return out

    @app.get("/api/typologies")
    def typologies():
        return inject.TYPOLOGIES

    @app.post("/api/plant")
    def plant(req: PlantReq):
        st = get_state()
        try:
            return inject.plant(st, req.typology, req.stealth, req.size, req.start_day)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/reset")
    def reset():
        st = get_state()
        st.reset()
        cache.clear()
        return dict(ok=True)

    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            f = WEB_DIST / path
            if path and f.is_file():
                return FileResponse(f)
            return FileResponse(WEB_DIST / "index.html")
    return app


app = create_app()

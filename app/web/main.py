"""Web panel — har bir biznes faqat o'z ma'lumotini ko'radi.

Muallif: Ulug'bek Bekbergenov — NM GROUP
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from app.config import AUTHOR, COMPANY, VERSION, settings
from app.db import SessionMaker, init_db
from app.models import (
    Customer, Invite, LedgerType, Ledger, Order, OrderStatus, Product, Role, Sale,
    Shop, Supplier, Unit, User, UserStatus,
)
from app.services import (
    apply_balance, belongs_to, create_invite, find_login, invite_link, money,
    parse_amount, verify_password,
)
from app.web.api import router as api_router

BASE_DIR = Path(__file__).parent
MEDIA_DIR = Path(settings.media_dir)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Savdo tizimi — NM GROUP")
app.add_middleware(SessionMiddleware, secret_key=settings.web_secret)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.include_router(api_router)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["money"] = money
templates.env.globals.update(AUTHOR=AUTHOR, COMPANY=COMPANY, VERSION=VERSION)

@app.get("/app", response_class=HTMLResponse)
@app.get("/webapp", response_class=HTMLResponse)
async def mini_app(request: Request):
    """Telegram Mini App — botdagi barcha amallar shu yerda bajariladi."""
    return templates.TemplateResponse(request, "webapp.html", {})


@app.get("/sw.js")
async def service_worker():
    """Service worker ildizdan berilishi shart — shunda scope butun saytni qamraydi."""
    return FileResponse(BASE_DIR / "static" / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(BASE_DIR / "static" / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/health")
async def health():
    return {"ok": True, "app": "nm-savdo", "version": VERSION}


@app.on_event("startup")
async def on_startup():
    await init_db()


# ------------------------- Kirish -------------------------

@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
@app.get("/panel", response_class=HTMLResponse)
async def root():
    """Brauzerdan kirilsa ham xuddi shu ilova ochiladi — bitta interfeys."""
    return RedirectResponse("/app", status_code=307)


def run():
    import uvicorn
    uvicorn.run("app.web.main:app", host=settings.web_host, port=settings.port)


if __name__ == "__main__":
    run()

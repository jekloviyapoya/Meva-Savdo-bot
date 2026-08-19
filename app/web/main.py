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

LOGIN_REDIRECT = RedirectResponse("/login", status_code=303)


async def get_session() -> AsyncSession:
    async with SessionMaker() as session:
        yield session


class Ctx:
    """Joriy sessiya: qaysi foydalanuvchi, qaysi biznes."""

    def __init__(self, shop: Shop, user: User):
        self.shop = shop
        self.user = user


async def current(request: Request, session: AsyncSession) -> Ctx | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = await session.get(User, user_id)
    if not user or user.status != UserStatus.APPROVED:
        return None
    shop = await session.get(Shop, user.shop_id)
    if not shop:
        return None
    return Ctx(shop, user)


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


def render(request: Request, template: str, ctx: Ctx | None = None, **data) -> HTMLResponse:
    data.setdefault("active", "")
    if ctx:
        data.setdefault("shop", ctx.shop)
        data.setdefault("me", ctx.user)
    return templates.TemplateResponse(request, template, data)


# ------------------------- Kirish -------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render(request, "login.html", error=None, choices=None)


@app.post("/login")
async def login(request: Request, login: str = Form(...), password: str = Form(...),
                session: AsyncSession = Depends(get_session)):
    candidates = await find_login(session, login)
    matched = [u for u in candidates if verify_password(password, u.password_hash)]
    if not matched:
        return render(request, "login.html",
                      error="Login yoki parol noto'g'ri.", choices=None)

    if len(matched) == 1:
        request.session["user_id"] = matched[0].id
        return RedirectResponse("/", status_code=303)

    choices = []
    for user in matched:
        shop = await session.get(Shop, user.shop_id)
        choices.append({"user_id": user.id, "shop": shop.name, "role": user.role.value})
    request.session["allowed_ids"] = [c["user_id"] for c in choices]
    return render(request, "login.html", error=None, choices=choices)


@app.post("/login/choose")
async def login_choose(request: Request, user_id: int = Form(...)):
    if user_id not in request.session.get("allowed_ids", []):
        return LOGIN_REDIRECT
    request.session["user_id"] = user_id
    request.session.pop("allowed_ids", None)
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ------------------------- Bosh sahifa -------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    shop = ctx.shop
    now = datetime.now(timezone.utc)

    async def totals(since):
        row = await session.execute(
            select(func.coalesce(func.sum(Sale.total), 0), func.count(Sale.id))
            .where(Sale.shop_id == shop.id, Sale.created_at >= since)
        )
        return row.one()

    day_total, day_count = await totals(now - timedelta(days=1))
    month_total, month_count = await totals(now - timedelta(days=30))

    debtors = list(await session.scalars(
        select(Customer).where(Customer.shop_id == shop.id, Customer.balance > 0)
        .order_by(Customer.balance.desc()).limit(12)
    ))
    debt_sum = sum(Decimal(c.balance) for c in debtors)
    ribbon = [
        {"name": c.name, "value": Decimal(c.balance),
         "pct": float(Decimal(c.balance) / debt_sum * 100)}
        for c in debtors
    ] if debt_sum else []

    open_orders = list(await session.scalars(
        select(Order).where(
            Order.shop_id == shop.id,
            Order.status.in_([OrderStatus.NEW, OrderStatus.PRICED,
                              OrderStatus.CONFIRMED, OrderStatus.SCHEDULED]),
        ).order_by(Order.created_at.desc()).limit(8)
    ))
    recent_sales = list(await session.scalars(
        select(Sale).where(Sale.shop_id == shop.id)
        .order_by(Sale.created_at.desc()).limit(8)
    ))
    product_count = await session.scalar(
        select(func.count()).select_from(Product)
        .where(Product.shop_id == shop.id, Product.is_active.is_(True))
    )
    return render(request, "dashboard.html", ctx, active="dash",
                  day_total=day_total, day_count=day_count,
                  month_total=month_total, month_count=month_count,
                  debt_total=debt_sum, ribbon=ribbon, open_orders=open_orders,
                  recent_sales=recent_sales, product_count=product_count)


# ------------------------- Mahsulotlar -------------------------

@app.get("/products", response_class=HTMLResponse)
async def products(request: Request, q: str = "",
                   session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    stmt = select(Product).where(Product.shop_id == ctx.shop.id, Product.is_active.is_(True))
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q}%"))
    items = list(await session.scalars(stmt.order_by(Product.name).limit(200)))
    suppliers = list(await session.scalars(
        select(Supplier).where(Supplier.shop_id == ctx.shop.id, Supplier.is_active.is_(True))
    ))
    return render(request, "products.html", ctx, active="products", products=items,
                  suppliers=suppliers, q=q, units=[u.value for u in Unit])


@app.post("/products/add")
async def product_add(request: Request, name: str = Form(...), price: str = Form(""),
                      unit: str = Form("dona"), supplier_id: str = Form(""),
                      session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    sup_id = int(supplier_id) if supplier_id else None
    if sup_id and not belongs_to(await session.get(Supplier, sup_id), ctx.shop):
        sup_id = None
    session.add(Product(
        shop_id=ctx.shop.id, name=name.strip(),
        price=parse_amount(price) if price.strip() else None,
        unit=Unit(unit), supplier_id=sup_id,
    ))
    await session.commit()
    return RedirectResponse("/products", status_code=303)


@app.post("/products/{product_id}/price")
async def product_price(request: Request, product_id: int, price: str = Form(...),
                        session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    product = await session.get(Product, product_id)
    if belongs_to(product, ctx.shop):
        product.price = parse_amount(price)
        await session.commit()
    return RedirectResponse("/products", status_code=303)


@app.post("/products/{product_id}/delete")
async def product_delete(request: Request, product_id: int,
                         session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    product = await session.get(Product, product_id)
    if belongs_to(product, ctx.shop):
        product.is_active = False
        await session.commit()
    return RedirectResponse("/products", status_code=303)


# ------------------------- Mijozlar -------------------------

@app.get("/customers", response_class=HTMLResponse)
async def customers(request: Request, q: str = "",
                    session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    stmt = select(Customer).where(Customer.shop_id == ctx.shop.id,
                                  Customer.is_active.is_(True))
    if q:
        stmt = stmt.where(Customer.name.ilike(f"%{q}%"))
    items = list(await session.scalars(stmt.order_by(Customer.balance.desc()).limit(200)))
    return render(request, "customers.html", ctx, active="customers",
                  customers=items, q=q)


@app.post("/customers/add")
async def customer_add(request: Request, name: str = Form(...), phone: str = Form(""),
                       address: str = Form(""), balance: str = Form("0"),
                       session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    customer = Customer(shop_id=ctx.shop.id, name=name.strip(),
                        phone=phone.strip() or None, address=address.strip() or None)
    session.add(customer)
    await session.flush()
    start = parse_amount(balance) or Decimal(0)
    if start:
        await apply_balance(session, customer, start, LedgerType.INITIAL,
                            "Boshlang'ich balans (web)")
    await session.commit()
    return RedirectResponse("/customers", status_code=303)


@app.get("/customers/{customer_id}", response_class=HTMLResponse)
async def customer_detail(request: Request, customer_id: int,
                          session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    customer = await session.get(Customer, customer_id)
    if not belongs_to(customer, ctx.shop):
        return RedirectResponse("/customers", status_code=303)
    entries = list(await session.scalars(
        select(Ledger).where(Ledger.customer_id == customer_id)
        .order_by(Ledger.created_at.desc()).limit(60)
    ))
    sales = list(await session.scalars(
        select(Sale).where(Sale.customer_id == customer_id)
        .order_by(Sale.created_at.desc()).limit(30)
    ))
    return render(request, "customer_detail.html", ctx, active="customers",
                  customer=customer, entries=entries, sales=sales)


@app.post("/customers/{customer_id}/balance")
async def customer_balance(request: Request, customer_id: int, action: str = Form(...),
                           amount: str = Form(...), comment: str = Form(""),
                           session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    customer = await session.get(Customer, customer_id)
    value = parse_amount(amount) or Decimal(0)
    if belongs_to(customer, ctx.shop) and value:
        if action == "payment":
            await apply_balance(session, customer, -value, LedgerType.PAYMENT,
                                comment or "To'lov (web)", ctx.user.tg_id)
        else:
            await apply_balance(session, customer, value, LedgerType.CORRECTION,
                                comment or "Qarz qo'shildi (web)", ctx.user.tg_id)
        await session.commit()
    return RedirectResponse(f"/customers/{customer_id}", status_code=303)


# ------------------------- Buyurtma va savdo -------------------------

@app.get("/orders", response_class=HTMLResponse)
async def orders(request: Request, session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    items = list(await session.scalars(
        select(Order).where(Order.shop_id == ctx.shop.id)
        .order_by(Order.created_at.desc()).limit(100)
    ))
    return render(request, "orders.html", ctx, active="orders", orders=items)


@app.get("/sales", response_class=HTMLResponse)
async def sales(request: Request, session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    items = list(await session.scalars(
        select(Sale).where(Sale.shop_id == ctx.shop.id)
        .order_by(Sale.created_at.desc()).limit(100)
    ))
    return render(request, "sales.html", ctx, active="sales", sales=items)


# ------------------------- Hodimlar -------------------------

@app.get("/staff", response_class=HTMLResponse)
async def staff(request: Request, session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    users = list(await session.scalars(
        select(User).where(User.shop_id == ctx.shop.id).order_by(User.role)
    ))
    suppliers = list(await session.scalars(
        select(Supplier).where(Supplier.shop_id == ctx.shop.id,
                               Supplier.is_active.is_(True))
    ))
    invites = list(await session.scalars(
        select(Invite).where(Invite.shop_id == ctx.shop.id, Invite.is_active.is_(True))
        .order_by(Invite.created_at.desc()).limit(10)
    ))
    return render(request, "staff.html", ctx, active="staff", users=users,
                  suppliers=suppliers, roles=[r.value for r in Role],
                  invites=[{"role": i.role.value, "link": invite_link(i.token),
                            "uses": i.uses} for i in invites])


@app.post("/staff/{user_id}/role")
async def staff_role(request: Request, user_id: int, role: str = Form(...),
                     session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx or not ctx.user.is_manager:
        return LOGIN_REDIRECT
    user = await session.get(User, user_id)
    if belongs_to(user, ctx.shop):
        user.role = Role(role)
        user.status = UserStatus.APPROVED
        await session.commit()
    return RedirectResponse("/staff", status_code=303)


@app.post("/staff/invite")
async def staff_invite(request: Request, role: str = Form("seller"),
                       session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx or not ctx.user.is_manager:
        return LOGIN_REDIRECT
    await create_invite(session, ctx.shop.id, Role(role), ctx.user.tg_id or 0)
    await session.commit()
    return RedirectResponse("/staff", status_code=303)


@app.post("/suppliers/add")
async def supplier_add(request: Request, name: str = Form(...), phone: str = Form(""),
                       session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    session.add(Supplier(shop_id=ctx.shop.id, name=name.strip(),
                         phone=phone.strip() or None))
    await session.commit()
    return RedirectResponse("/staff", status_code=303)


# ------------------------- Obuna -------------------------

@app.get("/license", response_class=HTMLResponse)
async def license_page(request: Request, session: AsyncSession = Depends(get_session)):
    ctx = await current(request, session)
    if not ctx:
        return LOGIN_REDIRECT
    return render(request, "license.html", ctx, active="license",
                  price=settings.license_monthly_price, card=settings.license_card)


def run():
    import uvicorn
    uvicorn.run("app.web.main:app", host=settings.web_host, port=settings.port)


if __name__ == "__main__":
    run()

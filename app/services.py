from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    Account, Customer, Invite, Ledger, LedgerType, PaymentMethod, Role, Shop, User,
    UserStatus,
)

DEFAULT_PAYMENT_METHODS = ["Naqd", "Karta", "Bank o'tkazmasi", "Qarzga"]
TRIAL_DAYS = 14


# ------------------------- Formatlash -------------------------

def money(value) -> str:
    try:
        return f"{Decimal(value or 0):,.0f}".replace(",", " ")
    except (InvalidOperation, TypeError):
        return "0"


def qty_fmt(value) -> str:
    d = Decimal(value or 0)
    return str(d.normalize()) if d != d.to_integral_value() else str(int(d))


def parse_amount(text: str) -> Decimal | None:
    if text is None:
        return None
    cleaned = text.strip().replace(" ", "").replace("'", "").replace("\u2019", "")
    cleaned = cleaned.replace(",", ".")
    if cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def normalize_phone(text: str | None) -> str | None:
    """+998 90 123 45 67 -> +998901234567. Login shu ko'rinishda saqlanadi."""
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if digits.startswith("998") and len(digits) == 12:
        return "+" + digits
    if len(digits) == 9:
        return "+998" + digits
    if digits.startswith("8") and len(digits) == 10:
        return "+998" + digits[1:]
    return "+" + digits


# ------------------------- Parol -------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or stored.count("$") != 2:
        return False
    _, salt, digest = stored.split("$")
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return hmac.compare_digest(check.hex(), digest)


def generate_password(length: int = 8) -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_token(length: int = 10) -> str:
    return secrets.token_hex(5)


def generate_shop_code(name: str) -> str:
    base = re.sub(r"[^a-z0-9]", "", name.lower())[:10] or "shop"
    return f"{base}{secrets.token_hex(2)}"


# ------------------------- Biznes (tenant) -------------------------

async def create_shop(
    session: AsyncSession,
    name: str,
    owner_full_name: str,
    owner_phone: str,
    trial_days: int = TRIAL_DAYS,
) -> tuple[Shop, User, str]:
    """Yangi biznes + egasining logini. Qaytaradi: (do'kon, egasi, parol)."""
    phone = normalize_phone(owner_phone)
    shop = Shop(
        code=generate_shop_code(name),
        name=name.strip(),
        owner_phone=phone,
        license_until=date.today() + timedelta(days=trial_days),
    )
    session.add(shop)
    await session.flush()

    for method in DEFAULT_PAYMENT_METHODS:
        session.add(PaymentMethod(shop_id=shop.id, name=method))

    password = generate_password()
    owner = User(
        shop_id=shop.id,
        full_name=owner_full_name.strip(),
        phone=phone,
        password_hash=hash_password(password),
        role=Role.OWNER,
        status=UserStatus.APPROVED,
    )
    session.add(owner)
    await session.flush()
    return shop, owner, password


async def find_login(session: AsyncSession, phone: str) -> list[User]:
    """Telefon (login) bo'yicha barcha bizneslardagi hisoblarni topadi."""
    normalized = normalize_phone(phone)
    if not normalized:
        return []
    return list(await session.scalars(
        select(User).where(User.phone == normalized, User.status != UserStatus.BLOCKED)
    ))


async def get_account(session: AsyncSession, tg_id: int) -> Account:
    account = await session.get(Account, tg_id)
    if account is None:
        account = Account(tg_id=tg_id)
        session.add(account)
        await session.flush()
    return account


async def memberships(session: AsyncSession, tg_id: int) -> list[User]:
    """Shu Telegram akkaunt biriktirilgan barcha bizneslar."""
    return list(await session.scalars(
        select(User).where(User.tg_id == tg_id, User.status != UserStatus.BLOCKED)
    ))


async def all_memberships(session: AsyncSession, tg_id: int) -> list[User]:
    """Holatidan qat'i nazar barcha yozuvlar — bloklanganini ham ko'rsatadi."""
    return list(await session.scalars(select(User).where(User.tg_id == tg_id)))


async def is_blocked_everywhere(session: AsyncSession, tg_id: int) -> bool:
    """Foydalanuvchi qayerdadir bor, lekin hamma joyda rad etilganmi?"""
    rows = await all_memberships(session, tg_id)
    return bool(rows) and all(u.status == UserStatus.BLOCKED for u in rows)


async def resolve_context(
    session: AsyncSession, tg_id: int
) -> tuple[Shop | None, User | None]:
    """Faol biznes va undagi foydalanuvchini aniqlaydi."""
    account = await get_account(session, tg_id)
    links = await memberships(session, tg_id)
    if not links:
        return None, None

    user = next((u for u in links if u.shop_id == account.active_shop_id), None)
    if user is None:
        user = links[0]
        account.active_shop_id = user.shop_id
        await session.flush()
    shop = await session.get(Shop, user.shop_id)
    return shop, user


async def switch_shop(session: AsyncSession, tg_id: int, shop_id: int) -> bool:
    link = await session.scalar(
        select(User).where(User.tg_id == tg_id, User.shop_id == shop_id)
    )
    if not link:
        return False
    account = await get_account(session, tg_id)
    account.active_shop_id = shop_id
    await session.flush()
    return True


# ------------------------- Taklif havolalari -------------------------

async def create_invite(
    session: AsyncSession, shop_id: int, role: Role, created_by: int,
    auto_approve: bool = False, max_uses: int = 0,
) -> Invite:
    invite = Invite(
        shop_id=shop_id, token=generate_token(), role=role,
        created_by=created_by, auto_approve=auto_approve, max_uses=max_uses,
    )
    session.add(invite)
    await session.flush()
    return invite


def invite_link(token: str) -> str:
    username = settings.bot_username.lstrip("@") or "your_bot"
    return f"https://t.me/{username}?start=inv{token}"


async def get_invite(session: AsyncSession, token: str) -> Invite | None:
    invite = await session.scalar(select(Invite).where(Invite.token == token))
    return invite if invite and invite.usable else None


# ------------------------- Foydalanuvchilar -------------------------

async def get_user(session: AsyncSession, tg_id: int, shop_id: int) -> User | None:
    return await session.scalar(
        select(User).where(User.tg_id == tg_id, User.shop_id == shop_id)
    )


async def managers(session: AsyncSession, shop_id: int) -> list[User]:
    return list(await session.scalars(
        select(User).where(
            User.shop_id == shop_id,
            User.status == UserStatus.APPROVED,
            User.tg_id.is_not(None),
            User.role.in_([Role.OWNER, Role.ADMIN]),
        )
    ))


async def staff_members(session: AsyncSession, shop_id: int) -> list[User]:
    return list(await session.scalars(
        select(User).where(
            User.shop_id == shop_id,
            User.status == UserStatus.APPROVED,
            User.tg_id.is_not(None),
            User.role.in_([Role.OWNER, Role.ADMIN, Role.SELLER]),
        )
    ))


# ------------------------- Balans -------------------------

async def apply_balance(
    session: AsyncSession,
    customer: Customer,
    amount: Decimal,
    ltype: LedgerType,
    comment: str | None = None,
    created_by: int | None = None,
    sale_id: int | None = None,
) -> Ledger:
    """amount > 0 — qarz oshadi, amount < 0 — qarz kamayadi (pul berdi)."""
    customer.balance = Decimal(customer.balance or 0) + Decimal(amount)
    entry = Ledger(
        shop_id=customer.shop_id,
        customer_id=customer.id,
        type=ltype,
        amount=Decimal(amount),
        balance_after=customer.balance,
        comment=comment,
        created_by=created_by,
        sale_id=sale_id,
    )
    session.add(entry)
    await session.flush()
    return entry


async def set_balance(
    session: AsyncSession, customer: Customer, new_balance: Decimal,
    comment: str | None, created_by: int | None,
    ltype: LedgerType = LedgerType.CORRECTION,
) -> Ledger:
    diff = Decimal(new_balance) - Decimal(customer.balance or 0)
    return await apply_balance(session, customer, diff, ltype, comment, created_by)


# ------------------------- Litsenziya -------------------------

async def extend_license(session: AsyncSession, shop: Shop, months: int = 1) -> date:
    base = shop.license_until if shop.license_until and shop.license_until > date.today() else date.today()
    shop.license_until = base + timedelta(days=30 * months)
    shop.is_active = True
    await session.flush()
    return shop.license_until


def belongs_to(obj, shop: Shop) -> bool:
    """Ma'lumot shu biznesga tegishlimi — bizneslar aralashmasligi uchun tekshiruv."""
    return obj is not None and getattr(obj, "shop_id", None) == shop.id

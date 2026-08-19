"""Autentifikatsiya — ikki yo'l bilan.

1. **Telegram Mini App** — har bir so'rovda `initData` keladi, uni bot tokeni
   bilan imzolangan HMAC orqali tekshiramiz.
2. **Mustaqil mobil ilova (PWA) yoki brauzer** — telefon + parol bilan kiriladi,
   javobda imzolangan token beriladi va keyingi so'rovlarda `X-App-Token`
   sarlavhasida yuboriladi.

Ikkala holatda ham natija bir xil: `AppContext` — kim, qaysi biznesda, qaysi rol.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Role, Shop, User, UserStatus
from app.services import resolve_context

MAX_AGE = 24 * 60 * 60          # initData 24 soatdan keyin eskiradi
TOKEN_MAX_AGE = 60 * 60 * 24 * 60  # ilova tokeni 60 kun amal qiladi


def parse_init_data(init_data: str, bot_token: str) -> dict:
    """initData ni tekshiradi va ichidagi ma'lumotni qaytaradi."""
    if not init_data:
        raise HTTPException(401, "initData yo'q")
    if not bot_token:
        raise HTTPException(500, "BOT_TOKEN sozlanmagan")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "imzo yo'q")

    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise HTTPException(401, "imzo noto'g'ri")

    auth_date = int(pairs.get("auth_date", 0))
    if auth_date and time.time() - auth_date > MAX_AGE:
        raise HTTPException(401, "sessiya eskirgan, ilovani qayta oching")

    user_raw = pairs.get("user")
    if not user_raw:
        raise HTTPException(401, "foydalanuvchi ma'lumoti yo'q")
    return json.loads(user_raw)


def make_token(user_id: int) -> str:
    """Parol bilan kirgan foydalanuvchiga imzolangan token beradi."""
    return _serializer().dumps({"uid": user_id})


def read_token(token: str) -> int | None:
    """Tokenni tekshiradi. Buzilgan yoki eskirgan bo'lsa None qaytaradi."""
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except Exception:
        return None
    uid = data.get("uid")
    return int(uid) if uid else None


def _serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(settings.web_secret, salt="app-token")


class TgContext:
    """So'rov konteksti: foydalanuvchi, faol biznes va roli."""

    def __init__(self, tg: dict | None, shop: Shop | None, user: User | None):
        self.tg = tg or {}
        # Parol bilan kirgan foydalanuvchida Telegram ID bo'lmasligi mumkin
        self.tg_id: int | None = int(self.tg["id"]) if self.tg.get("id") else (
            user.tg_id if user else None
        )
        self.shop = shop
        self.user = user

    @property
    def linked(self) -> bool:
        return self.user is not None and self.user.status == UserStatus.APPROVED

    @property
    def is_staff(self) -> bool:
        return self.linked and self.user.is_staff

    @property
    def is_manager(self) -> bool:
        return self.linked and self.user.is_manager

    def require_staff(self) -> None:
        if not self.is_staff:
            raise HTTPException(403, "Bu amal uchun ruxsat yo'q")

    def require_manager(self) -> None:
        if not self.is_manager:
            raise HTTPException(403, "Bu amal faqat admin uchun")

    def require_shop(self) -> Shop:
        if not self.linked or self.shop is None:
            raise HTTPException(403, "Avval biznesga ulaning")
        return self.shop

    def owns(self, obj) -> bool:
        return obj is not None and getattr(obj, "shop_id", None) == (
            self.shop.id if self.shop else None
        )

    def guard(self, obj):
        """Boshqa biznesning yozuviga urinish — darhol rad etiladi."""
        if not self.owns(obj):
            raise HTTPException(404, "Topilmadi")
        return obj


async def get_context(
    request: Request,
    session: AsyncSession,
    init_data: str | None,
) -> TgContext:
    # 1-yo'l: mustaqil ilova tokeni
    token = request.headers.get("x-app-token", "")
    if token:
        user_id = read_token(token)
        if not user_id:
            raise HTTPException(401, "Sessiya eskirgan, qaytadan kiring")
        user = await session.get(User, user_id)
        if user is None or user.status != UserStatus.APPROVED:
            raise HTTPException(401, "Hisob faol emas")
        shop = await session.get(Shop, user.shop_id)
        return TgContext(None, shop, user)

    # 2-yo'l: Telegram Mini App
    raw = init_data or request.headers.get("x-init-data", "")
    tg = parse_init_data(raw, settings.bot_token)
    shop, user = await resolve_context(session, int(tg["id"]))
    return TgContext(tg, shop, user)

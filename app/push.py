"""Web Push — PWA ga push bildirishnoma yuborish.

Kalitlar (VAPID) birinchi ishga tushishda avtomatik yaratiladi va bazada
saqlanadi, ya'ni qo'lda sozlash shart emas. Kalitlar o'zgarsa, eski obunalar
ishlamay qoladi — shuning uchun ular bir marta yaratilib, o'zgartirilmaydi.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import KeyValue, PushSubscription, User

log = logging.getLogger("push")

PUBLIC_KEY = "vapid_public"
PRIVATE_KEY = "vapid_private"

_cache: dict[str, str] = {}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _export(key) -> tuple[str, str]:
    """EC kalitidan (ochiq kalit, yopiq kalit) — ikkalasi ham xom base64url.

    py_vapid yopiq kalitni aynan xom 32 baytlik ko'rinishda kutadi; PEM
    berilsa o'qiy olmaydi va push umuman yuborilmaydi.
    """
    from cryptography.hazmat.primitives import serialization

    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return _b64(public_raw), _b64(private_raw)


def _generate_keys() -> tuple[str, str]:
    """Yangi EC P-256 juftligi."""
    from cryptography.hazmat.primitives.asymmetric import ec

    return _export(ec.generate_private_key(ec.SECP256R1()))


def _migrate_pem(pem: str) -> str:
    """Eski PEM ko'rinishidagi kalitni xom formatga o'giradi.

    Ochiq kalit o'zgarmaydi — shuning uchun mavjud obunalar ishlayveradi.
    """
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(pem.encode(), password=None)
    return _export(key)[1]


async def get_keys(session: AsyncSession) -> tuple[str, str]:
    """Kalitlarni qaytaradi, kerak bo'lsa yaratadi."""
    if _cache.get(PUBLIC_KEY) and _cache.get(PRIVATE_KEY):
        return _cache[PUBLIC_KEY], _cache[PRIVATE_KEY]

    rows = {r.key: r.value for r in await session.scalars(
        select(KeyValue).where(KeyValue.key.in_([PUBLIC_KEY, PRIVATE_KEY]))
    )}
    # Eski o'rnatishlarda kalit PEM ko'rinishida saqlangan — o'giramiz
    if rows.get(PRIVATE_KEY, "").lstrip().startswith("-----BEGIN"):
        raw = _migrate_pem(rows[PRIVATE_KEY])
        row = await session.get(KeyValue, PRIVATE_KEY)
        row.value = raw
        await session.commit()
        rows[PRIVATE_KEY] = raw
        log.info("Push yopiq kaliti xom formatga o'girildi")

    if PUBLIC_KEY not in rows or PRIVATE_KEY not in rows:
        public_b64, private_pem = _generate_keys()
        session.add(KeyValue(key=PUBLIC_KEY, value=public_b64))
        session.add(KeyValue(key=PRIVATE_KEY, value=private_pem))
        await session.commit()
        rows = {PUBLIC_KEY: public_b64, PRIVATE_KEY: private_pem}
        log.info("Push kalitlari yaratildi")

    _cache.update(rows)
    return rows[PUBLIC_KEY], rows[PRIVATE_KEY]


async def save_subscription(session: AsyncSession, user: User, sub: dict) -> None:
    endpoint = sub.get("endpoint")
    keys = sub.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("Obuna ma'lumoti to'liq emas")

    existing = await session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    if existing:
        existing.user_id = user.id
        existing.shop_id = user.shop_id
        existing.p256dh = keys["p256dh"]
        existing.auth = keys["auth"]
    else:
        session.add(PushSubscription(
            user_id=user.id, shop_id=user.shop_id, endpoint=endpoint,
            p256dh=keys["p256dh"], auth=keys["auth"],
        ))
    await session.commit()


async def drop_subscription(session: AsyncSession, endpoint: str) -> None:
    await session.execute(
        delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    await session.commit()


def _send_one(sub_info: dict, payload: str, private_key: str, claims: dict) -> int:
    """Bitta qurilmaga yuboradi. Bloklovchi chaqiruv — alohida oqimda ishlaydi."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(subscription_info=sub_info, data=payload,
                vapid_private_key=private_key, vapid_claims=dict(claims), ttl=86400)
        return 200
    except WebPushException as exc:
        code = getattr(exc.response, "status_code", 0) if exc.response is not None else 0
        if code not in (404, 410):
            log.warning("Push yuborilmadi (%s): %s", code, exc)
        return code
    except Exception as exc:
        log.error("Push xatosi: %s: %s", type(exc).__name__, exc)
        return 0


async def send_to_users(
    session: AsyncSession,
    user_ids: list[int],
    title: str,
    body: str,
    url: str = "/app",
    tag: str | None = None,
) -> int:
    """Ko'rsatilgan foydalanuvchilarning barcha qurilmalariga xabar yuboradi."""
    user_ids = [uid for uid in user_ids if uid]
    if not user_ids:
        return 0

    subs = list(await session.scalars(
        select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))
    ))
    if not subs:
        return 0

    _, private_key = await get_keys(session)
    origin = (settings.webapp_url or "").rstrip("/")
    claims = {"sub": f"mailto:admin@{(origin or 'https://example.com').split('//')[-1]}"}
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag or "nm"})

    dead: list[str] = []
    sent = 0
    for sub in subs:
        info = {"endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
        code = await asyncio.to_thread(_send_one, info, payload, private_key, claims)
        if code in (404, 410):
            dead.append(sub.endpoint)   # obuna eskirgan — tozalaymiz
        elif code == 200:
            sent += 1

    log.info("Push: %s ta qurilmadan %s tasiga yetdi", len(subs), sent)
    if dead:
        await session.execute(
            delete(PushSubscription).where(PushSubscription.endpoint.in_(dead))
        )
        await session.commit()
    return sent

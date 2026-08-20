from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, LargeBinary, Numeric,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _fmt(value) -> str:
    """Summani 1 234 567 ko'rinishida chiqaradi."""
    return f"{Decimal(value or 0):,.0f}".replace(",", " ")


# ------------------------- Enumlar -------------------------

class Role(str, enum.Enum):
    OWNER = "owner"        # do'kon egasi
    ADMIN = "admin"
    SELLER = "seller"      # sotuvchi
    CUSTOMER = "customer"  # mijoz


class UserStatus(str, enum.Enum):
    PENDING = "pending"    # tasdiq kutmoqda
    APPROVED = "approved"
    BLOCKED = "blocked"


class Unit(str, enum.Enum):
    DONA = "dona"
    KG = "kg"
    LITR = "litr"
    METR = "metr"
    QUTI = "quti"


class LedgerType(str, enum.Enum):
    INITIAL = "initial"        # boshlang'ich (oldingi) balans
    CORRECTION = "correction"  # qo'lda to'g'rilash
    SALE = "sale"              # savdo -> qarz oshadi
    PAYMENT = "payment"        # pul berdi -> qarz kamayadi (minus)
    ORDER = "order"


class OrderStatus(str, enum.Enum):
    NEW = "new"                    # mijoz yubordi
    PRICED = "priced"              # do'kon narxladi, mijoz tasdig'i kutilmoqda
    CONFIRMED = "confirmed"        # mijoz tasdiqladi
    SCHEDULED = "scheduled"        # yetkazish vaqti belgilandi
    DONE = "done"
    CANCELLED = "cancelled"


class DeliveryType(str, enum.Enum):
    PICKUP = "pickup"            # o'zi olib ketadi
    OWN_DRIVER = "own_driver"    # mijozning o'z haydovchisi
    SHOP_TAXI = "shop_taxi"      # do'konning taxi xizmati


# ------------------------- Do'kon / litsenziya -------------------------

class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    owner_tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    owner_phone: Mapped[str | None] = mapped_column(String(32), index=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    license_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def license_ok(self) -> bool:
        return bool(self.is_active and self.license_until and self.license_until >= date.today())

    @property
    def days_left(self) -> int:
        if not self.license_until:
            return 0
        return (self.license_until - date.today()).days


class LicensePayment(Base):
    __tablename__ = "license_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    months: Mapped[int] = mapped_column(default=1)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ------------------------- Foydalanuvchilar -------------------------

class User(Base):
    """Bitta biznesdagi bitta foydalanuvchi. Login — telefon raqami."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("shop_id", "phone", name="uq_user_shop_phone"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    # Telegram akkaunt biriktirilgunga qadar bo'sh bo'ladi (admin bot login yaratganda)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    photo_file_id: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.CUSTOMER)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.PENDING)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    customer: Mapped["Customer | None"] = relationship(foreign_keys=[customer_id], lazy="selectin")

    @property
    def is_staff(self) -> bool:
        return self.role in (Role.OWNER, Role.ADMIN, Role.SELLER)

    @property
    def is_manager(self) -> bool:
        return self.role in (Role.OWNER, Role.ADMIN)


class Account(Base):
    """Telegram akkaunti qaysi biznesda ishlayotganini eslab qoladi."""

    __tablename__ = "accounts"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    active_shop_id: Mapped[int | None] = mapped_column(
        ForeignKey("shops.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invite(Base):
    """Biznes egasi tarqatadigan taklif havolasi."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.SELLER)
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    uses: Mapped[int] = mapped_column(default=0)
    max_uses: Mapped[int] = mapped_column(default=0)  # 0 = cheksiz
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def usable(self) -> bool:
        return self.is_active and (self.max_uses == 0 or self.uses < self.max_uses)


class MediaFile(Base):
    """Yuklangan rasmlar bazada saqlanadi.

    Konteyner diski vaqtinchalik — har qayta joylashda tozalanadi va rasmlar
    yo'qoladi. Shu sabab rasm baytlari shu jadvalda turadi.
    """

    __tablename__ = "media_files"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    shop_id: Mapped[int | None] = mapped_column(
        ForeignKey("shops.id", ondelete="CASCADE"), nullable=True, index=True
    )
    mime: Mapped[str] = mapped_column(String(64), default="image/jpeg")
    data: Mapped[bytes] = mapped_column(LargeBinary)
    size: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KeyValue(Base):
    """Kichik sozlamalar (masalan, push kalitlari) shu yerda saqlanadi."""

    __tablename__ = "settings_kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class PushSubscription(Base):
    """Brauzer/PWA ning push manzili. Har bir qurilma uchun alohida yozuv."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    shop_id: Mapped[int | None] = mapped_column(
        ForeignKey("shops.id", ondelete="CASCADE"), nullable=True, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ------------------------- Katalog -------------------------

class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), index=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)  # ixtiyoriy
    unit: Mapped[Unit] = mapped_column(Enum(Unit), default=Unit.DONA)
    photo_file_id: Mapped[str | None] = mapped_column(String(255))
    photo_url: Mapped[str | None] = mapped_column(String(500))  # web app orqali yuklangan rasm
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    supplier: Mapped["Supplier | None"] = relationship(lazy="selectin")

    @property
    def price_label(self) -> str:
        return f"{_fmt(self.price)} so'm" if self.price is not None else "narx belgilanmagan"


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))   # Naqd, Karta, O'tkazma, Qarz...
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# ------------------------- Mijozlar -------------------------

class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    photo_file_id: Mapped[str | None] = mapped_column(String(255))
    photo_url: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(Text)
    # balans > 0  => mijoz qarzdor;  balans < 0 => oldindan to'lagan
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def balance_label(self) -> str:
        b = Decimal(self.balance or 0)
        if b > 0:
            return f"qarz: {_fmt(b)} so'm"
        if b < 0:
            return f"haqdor: {_fmt(abs(b))} so'm"
        return "qarz yo'q"


class Ledger(Base):
    """Mijozning har bir kirim-chiqimi shu yerda saqlanadi."""
    __tablename__ = "ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    type: Mapped[LedgerType] = mapped_column(Enum(LedgerType))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # + qarz oshdi, - qarz kamaydi
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    comment: Mapped[str | None] = mapped_column(Text)
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ------------------------- Savdo -------------------------

class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    seller_tg_id: Mapped[int | None] = mapped_column(BigInteger)
    seller_name: Mapped[str | None] = mapped_column(String(255))
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id", ondelete="SET NULL"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    debt: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["SaleItem"]] = relationship(
        back_populates="sale", cascade="all, delete-orphan", lazy="selectin"
    )
    customer: Mapped["Customer | None"] = relationship(lazy="selectin")
    payment_method: Mapped["PaymentMethod | None"] = relationship(lazy="selectin")


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255))
    unit: Mapped[Unit] = mapped_column(Enum(Unit), default=Unit.DONA)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=1)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)

    sale: Mapped["Sale"] = relationship(back_populates="items")


# ------------------------- Buyurtma (mijozdan) -------------------------

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.NEW)
    delivery_type: Mapped[DeliveryType] = mapped_column(Enum(DeliveryType), default=DeliveryType.PICKUP)
    needed_at: Mapped[str | None] = mapped_column(String(64))       # mijoz "qachonga kerak" deb yozgani
    delivery_time: Mapped[str | None] = mapped_column(String(128))  # kelishilgan vaqt
    driver_note: Mapped[str | None] = mapped_column(String(255))    # haydovchi haqida izoh
    address: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )
    customer: Mapped["Customer"] = relationship(lazy="selectin")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255))
    unit: Mapped[Unit] = mapped_column(Enum(Unit), default=Unit.DONA)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=1)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)

    order: Mapped["Order"] = relationship(back_populates="items")

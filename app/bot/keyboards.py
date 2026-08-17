from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from app.models import Role

BACK = "⬅️ Orqaga"
SWITCH = "🔄 Biznesni almashtirish"
CANCEL = "❌ Bekor qilish"
SKIP = "⏭ O'tkazib yuborish"
DONE = "✅ Tayyor"

remove = ReplyKeyboardRemove()


def cancel_kb(extra: list[str] | None = None) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    for text in extra or []:
        kb.button(text=text)
    kb.button(text=CANCEL)
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)


def main_menu(role: Role, multi: bool = False) -> ReplyKeyboardMarkup:
    """multi=True bo'lsa foydalanuvchi bir nechta biznesda ishlaydi."""
    kb = ReplyKeyboardBuilder()
    if role in (Role.OWNER, Role.ADMIN):
        kb.button(text="🛒 Savdo")
        kb.button(text="📥 Buyurtmalar")
        kb.button(text="📦 Mahsulotlar")
        kb.button(text="👥 Mijozlar")
        kb.button(text="🚚 Yetkazib beruvchilar")
        kb.button(text="💳 To'lov turlari")
        kb.button(text="👤 Hodimlar")
        kb.button(text="🔗 Taklif havolasi")
        kb.button(text="📊 Hisobot")
        kb.button(text="🔐 Litsenziya")
        kb.button(text="ℹ️ Bot haqida")
        if multi:
            kb.button(text=SWITCH)
        kb.adjust(2, 2, 2, 2, 2, 2)
    elif role == Role.SELLER:
        kb.button(text="🛒 Savdo")
        kb.button(text="📥 Buyurtmalar")
        kb.button(text="📦 Mahsulotlar")
        kb.button(text="👥 Mijozlar")
        kb.button(text="ℹ️ Bot haqida")
        if multi:
            kb.button(text=SWITCH)
        kb.adjust(2, 2, 2)
    else:
        kb.button(text="🛒 Buyurtma berish")
        kb.button(text="📦 Buyurtmalarim")
        kb.button(text="🧾 Xaridlarim")
        kb.button(text="💰 Balansim")
        kb.button(text="ℹ️ Bot haqida")
        if multi:
            kb.button(text=SWITCH)
        kb.adjust(2, 2, 2)
    return kb.as_markup(resize_keyboard=True)


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
    )


def approve_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=f"appr:ok:{user_id}")
    kb.button(text="🚫 Rad etish", callback_data=f"appr:no:{user_id}")
    return kb.as_markup()


def products_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="➕ Mahsulot qo'shish")
    kb.button(text="📃 Mahsulotlar ro'yxati")
    kb.button(text="🔎 Mahsulot qidirish")
    kb.button(text=BACK)
    kb.adjust(2, 2)
    return kb.as_markup(resize_keyboard=True)


def customers_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="➕ Mijoz qo'shish")
    kb.button(text="📃 Mijozlar ro'yxati")
    kb.button(text="🔎 Mijoz qidirish")
    kb.button(text="💸 Qarzdorlar")
    kb.button(text=BACK)
    kb.adjust(2, 2, 1)
    return kb.as_markup(resize_keyboard=True)


def suppliers_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="➕ Yetkazib beruvchi qo'shish")
    kb.button(text="📃 Yetkazib beruvchilar")
    kb.button(text=BACK)
    kb.adjust(1, 2)
    return kb.as_markup(resize_keyboard=True)


def product_card_kb(product_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💵 Narxni o'zgartirish", callback_data=f"prod:price:{product_id}")
    kb.button(text="🖼 Rasmni almashtirish", callback_data=f"prod:photo:{product_id}")
    kb.button(text="✏️ Nomini o'zgartirish", callback_data=f"prod:name:{product_id}")
    kb.button(text="🗑 O'chirish", callback_data=f"prod:del:{product_id}")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


def customer_card_kb(customer_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Balansni to'g'rilash", callback_data=f"cust:setbal:{customer_id}")
    kb.button(text="➖ Pul oldim (to'lov)", callback_data=f"cust:pay:{customer_id}")
    kb.button(text="➕ Qarz qo'shish", callback_data=f"cust:debt:{customer_id}")
    kb.button(text="🧾 Xaridlari", callback_data=f"cust:sales:{customer_id}")
    kb.button(text="📊 Kirim-chiqim", callback_data=f"cust:ledger:{customer_id}")
    kb.button(text="🖼 Rasm qo'shish", callback_data=f"cust:photo:{customer_id}")
    kb.adjust(1, 2, 2, 1)
    return kb.as_markup()


def delivery_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚚 Dostavka xizmati", callback_data="ord:delivery")
    kb.button(text="🏬 O'zim olib ketaman", callback_data="ord:pickup")
    kb.adjust(1)
    return kb.as_markup()


def delivery_choice_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚗 O'zimning haydovchim bor", callback_data="ord:own_driver")
    kb.button(text="🚕 Sizning taxi xizmatingiz orqali", callback_data="ord:shop_taxi")
    kb.adjust(1)
    return kb.as_markup()


def order_staff_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Qabul qilib narxlash", callback_data=f"ordm:price:{order_id}")
    kb.button(text="✏️ Narxlarni qo'lda kiritish", callback_data=f"ordm:manual:{order_id}")
    kb.button(text="🚫 Bekor qilish", callback_data=f"ordm:cancel:{order_id}")
    kb.adjust(1)
    return kb.as_markup()


def order_customer_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlayman", callback_data=f"ordc:ok:{order_id}")
    kb.button(text="🚫 Bekor qilaman", callback_data=f"ordc:no:{order_id}")
    kb.adjust(2)
    return kb.as_markup()


def order_finish_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Yetkazildi (savdoga o'tkazish)", callback_data=f"ordm:done:{order_id}")
    return kb.as_markup()


def role_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👑 Admin", callback_data=f"role:admin:{user_id}")
    kb.button(text="🧑‍💼 Sotuvchi", callback_data=f"role:seller:{user_id}")
    kb.button(text="🙍 Mijoz", callback_data=f"role:customer:{user_id}")
    kb.button(text="🚫 Bloklash", callback_data=f"role:block:{user_id}")
    kb.adjust(2, 2)
    return kb.as_markup()


def inline_list(prefix: str, items: list[tuple[int, str]], per_row: int = 1) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for item_id, title in items:
        kb.button(text=title, callback_data=f"{prefix}:{item_id}")
    kb.adjust(per_row)
    return kb.as_markup()


def invite_role_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧑‍💼 Sotuvchi uchun havola", callback_data="inv:seller")
    kb.button(text="👑 Admin uchun havola", callback_data="inv:admin")
    kb.button(text="🙍 Mijoz uchun havola", callback_data="inv:customer")
    kb.adjust(1)
    return kb.as_markup()


def login_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Login raqamimni yuborish", request_contact=True)]],
        resize_keyboard=True,
    )

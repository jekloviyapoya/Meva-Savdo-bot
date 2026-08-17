# Savdo tizimi — ko'p biznesli (multi-tenant)

Bitta bot **bir nechta biznesga** xizmat qiladi. Har bir biznes o'z mahsulotlari,
mijozlari, hodimlari va hisob-kitobi bilan **butunlay alohida** ishlaydi —
bir biznes ikkinchisining birorta yozuvini ko'ra olmaydi.

Tarkibi: savdo boti (hodimlar va mijozlar uchun), web panel va admin bot
(bizneslarni ro'yxatga olish + oylik obuna).

**Dasturchi: Ulug'bek Bekbergenov — NM GROUP**

---

## Nimalar bor

**Mahsulotlar**
- Nom bilan yaratiladi, narx yaratish paytida **ixtiyoriy**
- Narxni keyin «Mahsulotlar» bo'limidan yoki web paneldan o'zgartirasiz
- Rasm, o'lchov birligi (dona/kg/litr/metr/quti), yetkazib beruvchi, qoldiq

**Yetkazib beruvchilar** — nomi va telefon raqami.

**To'lov turlari** — Naqd, Karta, Bank o'tkazmasi, Qarzga. Yangisini qo'shsa bo'ladi
(Click, Payme va h.k.).

**Mijozlar**
- Ism, telefon, manzil, **rasm**
- Oldingi (eski) balansni kiritish
- Balansni to'g'rilash, qarz qo'shish, pul olganda minus qilish
- Har bir harakat kirim-chiqim jurnaliga yoziladi

**Savdo** — mijoz tanlanadi → mahsulotlar savatga qo'shiladi → to'lov turi →
to'langan summa. Qolgan qarz avtomatik mijoz balansiga qo'shiladi.

**Kirish tartibi**
1. Siz (super admin) **admin bot**da «🏢 Yangi biznes» ni bosasiz: biznes nomi,
   egasining ismi va telefon raqami. Tizim login yaratadi —
   **login = telefon raqami**, parol avtomatik generatsiya qilinadi.
2. Biznes egasi savdo botiga `/start` yuboradi va shu raqamni kiritadi —
   o'z biznesiga kiradi. Web panelga ham shu login + parol bilan kiradi.
3. Egasi «🔗 Taklif havolasi» dan sotuvchi / admin / mijoz uchun havola oladi.
   Havola orqali kirgan odam **faqat o'sha biznesga** qo'shiladi va egasi
   tasdiqlagach ishlay boshlaydi.
4. Egasi hodimga to'g'ridan-to'g'ri login ham yaratishi mumkin («👤 Hodimlar»).

**Bizneslar aralashmaydi**
- Har bir jadvalda `shop_id` bor, barcha so'rovlar shu bo'yicha filtrlanadi
- Har bosishda `belongs_to()` tekshiruvi — begona ID bilan urinish rad etiladi
- Web panelda sessiya foydalanuvchiga bog'langan, u faqat o'z biznesini ko'radi
- Bir odam bir nechta biznesda ishlashi mumkin — «🔄 Biznesni almashtirish»
  (yoki `/biznes`) orqali o'tadi

**Rollar** — egasi, admin, sotuvchi, mijoz.

**Mijoz boti** — mahsulot tanlash, miqdor va «qachonga kerak»ligini yozish,
buyurtma berish, o'z xaridlari va balansini istalgan vaqtda ko'rish.

**Buyurtma va dostavka oqimi**
1. Mijoz buyurtma yuboradi va yetkazib berish turini tanlaydi:
   «🚗 O'zimning haydovchim bor» yoki «🚕 Sizning taxi xizmatingiz orqali»
2. Do'kon qabul qilib narxlaydi — mijozga nechа kg / dona va har birining narxi yuboriladi
3. Mijoz tasdiqlaydi
4. O'z haydovchisi bo'lsa — mijoz haydovchi qachon borishini yozadi
   Do'kon yetkazsa — do'kon egasi taxminiy vaqtni belgilaydi va mijozga yuboriladi
5. Yetkazilgach buyurtma savdoga aylanadi va balansga tushadi

**Obuna (litsenziya)** — har bir biznes alohida obunada. Muddat tugasa faqat
o'sha biznes to'xtaydi, qolganlari ishlayveradi. Super admin admin botdan turib
istalgan biznesni 1 / 3 / 12 oyga uzaytiradi, to'xtatadi yoki egasining parolini
yangilaydi. Yangi biznes 14 kunlik sinov muddati bilan ochiladi.

---

## O'rnatish

```bash
git clone <repo> && cd nm-savdo-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # tokenlar va baza manzilini yozing
```

PostgreSQL bazasini yarating:

```bash
createdb nm_savdo
```

`.env` da eng muhimi:

| O'zgaruvchi | Nima uchun |
|---|---|
| `BOT_TOKEN` | savdo boti tokeni (@BotFather) |
| `BOT_USERNAME` | savdo botining useri — taklif havolalari shundan yasaladi |
| `LICENSE_BOT_TOKEN` | admin bot tokeni |
| `SUPER_ADMIN_IDS` | bizneslarni ro'yxatga oladigan Telegram ID lar, vergul bilan |
| `DATABASE_URL` | `postgresql+asyncpg://user:parol@host:5432/nm_savdo` |
| `WEB_SECRET` | sessiya kaliti — uzun tasodifiy satr |

## Ishga tushirish

Uchta jarayon alohida ishlaydi:

```bash
python run_bot.py          # savdo boti
python run_license_bot.py  # litsenziya boti
python run_web.py          # web panel -> http://localhost:8000
```

Jadvallar birinchi ishga tushishda avtomatik yaratiladi.

### Birinchi qadamlar
1. Admin botga `/start` yuboring — u sizning Telegram ID ingizni ko'rsatadi,
   uni `SUPER_ADMIN_IDS` ga yozib botni qayta ishga tushiring
2. «🏢 Yangi biznes» — nom, egasining ismi va telefoni. Login va parol chiqadi
3. Login va parolni biznes egasiga bering
4. Egasi savdo botiga `/start` yuborib login raqamini kiritadi
5. Egasi mahsulot, mijoz qo'shadi va hodimlarga taklif havolasini tarqatadi

## Server (systemd)

```ini
[Unit]
Description=Savdo boti
After=network.target postgresql.service

[Service]
WorkingDirectory=/opt/nm-savdo-bot
ExecStart=/opt/nm-savdo-bot/.venv/bin/python run_bot.py
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

`run_license_bot.py` va `run_web.py` uchun ham xuddi shunday fayl yarating.

## Tuzilishi

```
app/
  config.py        sozlamalar (.env)
  db.py            baza ulanishi
  models.py        jadvallar
  services.py      login, parol, taklif havolasi, balans, obuna
  bot/             savdo boti (handlers/ ichida bo'limlar)
  license_bot/     admin bot: biznes ro'yxati va obuna
  web/             FastAPI panel (templates/, static/)
```

---

© NM GROUP · Ulug'bek Bekbergenov

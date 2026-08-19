/* Savdo Mini App — NM GROUP (Ulug'bek Bekbergenov) */
(() => {
"use strict";

const tg = window.Telegram && window.Telegram.WebApp;
const view = document.getElementById("view");
const tabbar = document.getElementById("tabbar");
const topbar = document.getElementById("topbar");
const sheetEl = document.getElementById("sheet");
const backdrop = document.getElementById("backdrop");

let ME = null;
let TAB = "home";

/* Telegramdan tashqarida (mobil ilova, brauzer) sessiya shu tokenda saqlanadi. */
const TOKEN_KEY = "nm_app_token";
const getToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; } };
const setToken = (v) => { try { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); } catch (e) {} };
const standalone = !tg || !tg.initData;
let CART = [];          // savdo/buyurtma savati
let LAST = {};          // ekranlar uchun vaqtinchalik ma'lumot

/* ---------------- Yordamchilar ---------------- */

const money = (v) => (Math.round(Number(v) || 0)).toLocaleString("ru-RU").replace(/\u00a0/g, " ");
const qty = (v) => { const n = Number(v) || 0; return Number.isInteger(n) ? String(n) : String(n); };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (m) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const dateFmt = (iso) => {
  const d = new Date(iso);
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) + " " +
         d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
};

/* Xatoni ekranda ko'rsatish — telefonda konsol yo'q, shuning uchun shart. */
function showFatal(msg) {
  const bar = document.getElementById("errbar") || (() => {
    const el = document.createElement("div");
    el.id = "errbar";
    el.className = "errbar";
    el.onclick = () => { try { navigator.clipboard.writeText(el.textContent); } catch (e) {} };
    document.body.appendChild(el);
    return el;
  })();
  bar.textContent = "⚠️ " + msg;
  bar.hidden = false;
}
window.addEventListener("error", (e) => showFatal(e.message + " @ " + (e.lineno || "?")));
window.addEventListener("unhandledrejection", (e) =>
  showFatal(String((e.reason && e.reason.message) || e.reason)));

function haptic(kind = "light") {
  try { tg.HapticFeedback.impactOccurred(kind); } catch (e) { /* ignore */ }
}

function toast(msg, isError) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " err" : "");
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.hidden = true; }, 2600);
}

async function api(path, options = {}) {
  const res = await fetch("/api" + path, {
    method: options.method || "GET",
    headers: Object.assign(
      { "X-Init-Data": (tg && tg.initData) || "", "X-App-Token": getToken() },
      options.body instanceof FormData ? {} : { "Content-Type": "application/json" }
    ),
    body: options.body instanceof FormData ? options.body
        : options.body ? JSON.stringify(options.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) throw new Error((data && data.detail) || "Xatolik yuz berdi");
  return data;
}

function render(html) { view.innerHTML = html; view.scrollTop = 0; window.scrollTo(0, 0); }
function loading() { render('<div class="loading"><div class="spinner"></div></div>'); }

function sheet(html) {
  sheetEl.innerHTML = html;
  sheetEl.hidden = false;
  backdrop.hidden = false;
}
function closeSheet() { sheetEl.hidden = true; backdrop.hidden = true; sheetEl.innerHTML = ""; }
backdrop.addEventListener("click", closeSheet);

async function guard(fn) {
  try { await fn(); }
  catch (err) { toast(err.message, true); }
}

/* ---------------- Kirish ---------------- */

async function boot() {
  if (tg) {
    tg.ready(); tg.expand();
    tg.setHeaderColor && tg.setHeaderColor("secondary_bg_color");
    const fit = () => {
      const h = tg.viewportStableHeight || tg.viewportHeight;
      if (h) document.documentElement.style.setProperty("--vh", h + "px");
    };
    fit();
    tg.onEvent && tg.onEvent("viewportChanged", fit);
  }
  registerServiceWorker();
  loading();
  if (standalone && !getToken()) return screenPassword();
  try {
    ME = await api("/me");
  } catch (err) {
    if (standalone) { setToken(""); return screenPassword(err.message); }
    render(`<div class="center-screen">
      <div class="logo">🔒</div><h2>Kirish imkonsiz</h2>
      <p class="hint" style="color:var(--muted)">${esc(err.message)}</p>
      <p class="hint" style="color:var(--muted)">Ilovani Telegram bot orqali oching.</p>
    </div>`);
    return;
  }
  if (!ME.linked) return ME.pending ? screenPending() : screenLogin();
  startApp();
}

/* Telegramdan tashqarida: telefon + parol bilan kirish. */
function screenPassword(errMsg, options) {
  topbar.hidden = true; tabbar.hidden = true;
  render(`<div class="center-screen">
    <div class="logo">🏪</div>
    <h2>Savdo tizimi</h2>
    <p style="color:var(--muted);margin:8px 0 18px">
      Login — telefon raqamingiz. Parolni biznes egangiz yoki admin bergan.</p>
    <div class="card" style="text-align:left">
      ${options && options.length ? `
        <label>Qaysi biznesga kiramiz?</label>
        <select id="which">${options.map((o) =>
          `<option value="${o.user_id}">${esc(o.shop)} · ${esc(o.role)}</option>`).join("")}</select>
        <div style="height:12px"></div>` : `
        <label for="phone">Telefon raqam</label>
        <input id="phone" type="tel" inputmode="tel" autocomplete="username"
               placeholder="+998 90 123 45 67" value="${esc(LAST.loginPhone || "")}">
        <label for="pwd">Parol</label>
        <input id="pwd" type="password" autocomplete="current-password" placeholder="••••••••">
        <div style="height:12px"></div>`}
      ${errMsg ? `<p class="err-text">${esc(errMsg)}</p>` : ""}
      <button class="btn" id="pwdBtn">Kirish</button>
    </div>
    <div id="installBox"></div>
    <p style="color:var(--muted);font-size:.82rem;margin-top:14px">
      Telegram orqali kirsangiz parol kerak emas — botdagi «Ilovani ochish» tugmasini bosing.</p>
    <p class="credit">Ulug'bek Bekbergenov — NM GROUP</p>
  </div>`);
  showInstallHint();

  $("#pwdBtn").onclick = () => guard(async () => {
    const body = options && options.length
      ? { phone: LAST.loginPhone, password: LAST.loginPwd, user_id: Number($("#which").value) }
      : { phone: $("#phone").value.trim(), password: $("#pwd").value };
    if (!body.phone || !body.password) return toast("Telefon va parolni kiriting", true);
    LAST.loginPhone = body.phone; LAST.loginPwd = body.password;
    let res;
    try {
      res = await api("/auth/password", { method: "POST", body });
    } catch (e) {
      return screenPassword(e.message);
    }
    if (res.choose) return screenPassword(null, res.choose);
    setToken(res.token);
    LAST.loginPwd = null;
    haptic("medium");
    ME = await api("/me");
    startApp();
  });
}

function logout() {
  setToken("");
  ME = null;
  LAST = {}; CART = [];
  screenPassword();
}

/* PWA: ilovani telefon ekraniga o'rnatish taklifi */
let installEvent = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault(); installEvent = e; showInstallHint();
});

function showInstallHint() {
  const box = document.getElementById("installBox");
  if (!box) return;
  const mm = window.matchMedia && window.matchMedia("(display-mode: standalone)");
  if (mm && mm.matches) return;   // allaqachon ilova sifatida ochilgan
  if (installEvent) {
    box.innerHTML = '<button class="btn line" id="installBtn" style="margin-top:12px">📲 Ilovani o\'rnatish</button>';
    $("#installBtn").onclick = async () => {
      installEvent.prompt();
      await installEvent.userChoice;
      installEvent = null;
      box.innerHTML = "";
    };
  } else if (/iPhone|iPad|iPod/.test(navigator.userAgent)) {
    box.innerHTML = '<p style="color:var(--muted);font-size:.8rem;margin-top:12px">' +
      'Ilova sifatida o\'rnatish: pastdagi <b>Ulashish</b> → <b>«Bosh ekranga qo\'shish»</b></p>';
  }
}

function registerServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

function screenLogin() {
  topbar.hidden = true; tabbar.hidden = true;
  render(`<div class="center-screen">
    <div class="logo">🏪</div>
    <h2>Savdo tizimi</h2>
    <p style="color:var(--muted);margin:8px 0 18px">
      Login — telefon raqamingiz. Uni biznes egangiz yoki admin bergan.</p>
    <div class="card" style="text-align:left">
      <label for="phone">Telefon raqam</label>
      <input id="phone" type="tel" inputmode="tel" placeholder="+998 90 123 45 67">
      <div style="height:12px"></div>
      <button class="btn" id="loginBtn">Kirish</button>
    </div>
    <p style="color:var(--muted);font-size:.82rem;margin-top:14px">
      Login yo'qmi? Biznes egangizdan taklif havolasini so'rang — havola orqali kirsangiz
      ariza yuboriladi.</p>
    <p class="credit">${esc(ME.about.author)} — ${esc(ME.about.company)}</p>
  </div>`);
  $("#loginBtn").onclick = () => guard(async () => {
    const phone = $("#phone").value.trim();
    if (!phone) return toast("Raqamni kiriting", true);
    await api("/login", { method: "POST", body: { phone } });
    haptic("medium");
    ME = await api("/me");
    if (!ME.linked) return screenPending();
    startApp();
  });
}

function screenPending() {
  topbar.hidden = true; tabbar.hidden = true;
  render(`<div class="center-screen">
    <div class="logo">⏳</div>
    <h2>Ariza yuborildi</h2>
    <p style="color:var(--muted);margin-top:8px">
      Biznes egasi yoki admin tasdiqlagach ilova ochiladi. Tasdiqlangach xabar keladi.</p>
    <div style="height:16px"></div>
    <button class="btn ghost" onclick="location.reload()">Yangilash</button>
  </div>`);
}

/* ---------------- Karkas ---------------- */

const TABS_STAFF = [
  { id: "home", icon: "🏠", label: "Bosh" },
  { id: "sale", icon: "🛒", label: "Savdo" },
  { id: "orders", icon: "📥", label: "Buyurtma" },
  { id: "customers", icon: "👥", label: "Mijoz" },
  { id: "more", icon: "⋯", label: "Yana" },
];
const TABS_CUSTOMER = [
  { id: "catalog", icon: "🛍", label: "Katalog" },
  { id: "myorders", icon: "📦", label: "Buyurtma" },
  { id: "balance", icon: "💰", label: "Balans" },
  { id: "more", icon: "⋯", label: "Yana" },
];

function startApp() {
  topbar.hidden = false;
  tabbar.hidden = false;
  $("#shopName").textContent = ME.shop ? ME.shop.name : "Savdo";
  $("#shopSub").textContent = `${ME.user.name} · ${roleLabel(ME.user.role)}` +
    (ME.shop && !ME.shop.license_ok ? " · ⛔️ obuna tugagan" : "");
  const sw = $("#shopSwitch");
  sw.hidden = ME.shops.length < 2;
  sw.onclick = sheetShops;

  const tabs = ME.user.is_staff ? TABS_STAFF : TABS_CUSTOMER;
  TAB = tabs[0].id;
  tabbar.innerHTML = tabs.map((t) =>
    `<button class="tab" data-tab="${t.id}"><i>${t.icon}</i>${t.label}</button>`).join("");
  go(TAB);
}

/* Bosishlar hujjat darajasida ushlanadi — bu eng ishonchli usul: ekran qayta
   chizilganda ham, tugma qayerda bo'lishidan qat'i nazar ishlaydi. */
document.addEventListener("click", (e) => {
  const tab = e.target.closest("[data-tab]");
  if (tab) { haptic(); go(tab.dataset.tab); }
}, true);

function roleLabel(role) {
  return { owner: "egasi", admin: "admin", seller: "sotuvchi", customer: "mijoz" }[role] || role;
}

function go(tab) {
  TAB = tab;
  $$(".tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  const screens = {
    home: screenHome, sale: screenSale, orders: screenOrders,
    customers: screenCustomers, more: screenMore,
    catalog: screenCatalog, myorders: screenMyOrders, balance: screenBalance,
  };
  (screens[tab] || screenHome)();
}

/* ---------------- Bosh sahifa (hodim) ---------------- */

async function screenHome() {
  loading();
  await guard(async () => {
    const [rep, orders] = await Promise.all([api("/report"), api("/orders")]);
    const open = orders.filter((o) => !["done", "cancelled"].includes(o.status));
    render(`
      <div class="metrics">
        <div class="metric"><div class="metric-label">Bugungi aylanma</div>
          <div class="num-lg">${money(rep.day.total)}</div>
          <div class="row-sub">${rep.day.count} ta savdo</div></div>
        <div class="metric"><div class="metric-label">30 kunlik</div>
          <div class="num-lg">${money(rep.month.total)}</div>
          <div class="row-sub">${rep.month.count} ta savdo</div></div>
        <div class="metric"><div class="metric-label">Qarzdorlik</div>
          <div class="num-lg debt">${money(rep.debt_total)}</div>
          <div class="row-sub">jami mijozlarda</div></div>
        <div class="metric"><div class="metric-label">Ochiq buyurtma</div>
          <div class="num-lg">${rep.open_orders}</div>
          <div class="row-sub">${rep.products} ta mahsulot</div></div>
      </div>

      <div class="quick">
        <button data-go="sale"><i>🛒</i>Savdo</button>
        <button data-act="newProduct"><i>➕</i>Mahsulot</button>
        <button data-act="newCustomer"><i>👤</i>Mijoz</button>
        <button data-go="orders"><i>📥</i>Buyurtma</button>
      </div>

      <div class="section-title">Ochiq buyurtmalar</div>
      <div class="card tight">${open.length ? open.slice(0, 6).map(orderRow).join("")
        : '<div class="empty"><i>📭</i>Ochiq buyurtma yo\'q</div>'}</div>

      <div class="section-title">Eng ko'p sotilgan (30 kun)</div>
      <div class="card tight">${rep.top.length ? rep.top.map((t) => `
        <div class="row" style="cursor:default">
          <div class="row-main"><div class="row-title">${esc(t.name)}</div></div>
          <div class="row-end num">${money(t.total)}</div>
        </div>`).join("") : '<div class="empty"><i>📊</i>Ma\'lumot yo\'q</div>'}</div>
    `);
    view.onclick = (e) => {
      const g = e.target.closest("[data-go]");
      if (g) return go(g.dataset.go);
      const a = e.target.closest("[data-act]");
      if (a && a.dataset.act === "newProduct") return sheetProduct();
      if (a && a.dataset.act === "newCustomer") return sheetCustomer();
      const row = e.target.closest("[data-order]");
      if (row) return sheetOrder(Number(row.dataset.order));
    };
  });
}

/* ---------------- Savdo ---------------- */

const STATUS = {
  new: ["🆕 Yangi", "warn"], priced: ["💵 Narxlandi", "warn"],
  confirmed: ["✅ Tasdiqlandi", "ok"], scheduled: ["🚚 Vaqt belgilandi", "ok"],
  done: ["📦 Yetkazildi", "ok"], cancelled: ["🚫 Bekor", "debt"],
};
const DELIVERY = {
  pickup: "🏬 O'zi olib ketadi",
  own_driver: "🚗 Mijozning haydovchisi",
  shop_taxi: "🚕 Do'kon yetkazadi",
};

async function screenSale() {
  CART = [];
  LAST.saleCustomer = null;
  LAST.saleProducts = null;
  LAST.saleTerm = "";
  await drawSale();
}

/* Mahsulotlar bir marta yuklanadi va keshda turadi — savatga qo'shgach
   ro'yxat joyida qoladi, qayta yuklanmaydi. */
async function saleProducts() {
  if (!LAST.saleProducts) {
    try { LAST.saleProducts = await api("/products"); }
    catch (e) { LAST.saleProducts = []; toast(e.message, true); }
  }
  return LAST.saleProducts;
}

async function drawSale() {
  const all = await saleProducts();
  const term = (LAST.saleTerm || "").toLowerCase();
  const list = term ? all.filter((p) => p.name.toLowerCase().includes(term)) : all;
  render(`
    <div class="card" id="custCard">
      <div class="row" data-act="pickCustomer" style="border:0;padding:4px 0">
        <div class="thumb">👤</div>
        <div class="row-main">
          <div class="row-title">${LAST.saleCustomer ? esc(LAST.saleCustomer.name) : "Mijozni tanlang"}</div>
          <div class="row-sub">${LAST.saleCustomer ? esc(LAST.saleCustomer.balance_label) : "yoki tezkor savdo"}</div>
        </div>
        <div class="row-end">›</div>
      </div>
    </div>

    <div class="section-title">Savat</div>
    <div class="card tight" id="cartBox">${cartRows()}</div>
    ${CART.length ? `<button class="btn" data-act="finish">Yakunlash · ${money(cartTotal())} so'm</button>
      <div style="height:14px"></div>` : ""}

    <div class="section-title">Mahsulotlar</div>
    <div class="search"><input id="q" placeholder="🔎 Qidirish" value="${esc(LAST.saleTerm || "")}"></div>
    <div class="pgrid" id="pgrid">${list.map(productTile).join("") ||
      `<div class="empty wide"><i>📦</i>${term ? "Topilmadi" : "Mahsulot yo'q"}</div>`}</div>
    ${ME.user.is_manager ? '<button class="btn ghost" data-act="newProduct">➕ Yangi mahsulot</button>' : ""}
  `);

  const q = $("#q");
  if (q) {
    q.oninput = (e) => {
      LAST.saleTerm = e.target.value;
      const term2 = LAST.saleTerm.toLowerCase();
      const found = term2 ? all.filter((p) => p.name.toLowerCase().includes(term2)) : all;
      $("#pgrid").innerHTML = found.map(productTile).join("") ||
        '<div class="empty wide"><i>📦</i>Topilmadi</div>';
    };
  }

  view.onclick = (e) => {
    const tile = e.target.closest("[data-prod]");
    if (tile) {
      const p = all.find((x) => x.id === Number(tile.dataset.prod));
      if (p) { haptic(); return sheetCartItem(p); }
    }
    const a = e.target.closest("[data-act]");
    if (!a) return;
    if (a.dataset.act === "pickCustomer") return pickCustomer((c) => { LAST.saleCustomer = c; drawSale(); }, true);
    if (a.dataset.act === "finish") return sheetCheckout();
    if (a.dataset.act === "del") { CART.splice(Number(a.dataset.i), 1); drawSale(); }
    if (a.dataset.act === "edit") { sheetCartItem(null, Number(a.dataset.i)); }
    if (a.dataset.act === "newProduct") return sheetProduct(null, async () => {
      LAST.saleProducts = null; await drawSale();
    });
  };
}

/* Rasmli mahsulot kartochkasi. Savatdagi miqdor kartochkada ko'rinib turadi. */
function productTile(p) {
  const inCart = CART.filter((i) => i.product_id === p.id)
                     .reduce((s, i) => s + Number(i.qty), 0);
  const media = p.photo
    ? `<img src="${esc(p.photo)}" alt="" loading="lazy">`
    : `<span class="ph">${p.unit === "kg" ? "⚖️" : "📦"}</span>`;
  return `
    <button class="ptile${inCart ? " picked" : ""}" data-prod="${p.id}">
      <div class="ptile-img">${media}${inCart ? `<span class="badge-qty">${qty(inCart)} ${esc(p.unit)}</span>` : ""}</div>
      <div class="ptile-name">${esc(p.name)}</div>
      <div class="ptile-price">${p.price != null ? money(p.price) + " so'm" : "narx yo'q"}</div>
    </button>`;
}

const cartTotal = () => CART.reduce((s, i) => s + i.qty * i.price, 0);

function cartRows() {
  if (!CART.length) return '<div class="empty"><i>🧺</i>Savat bo\'sh</div>';
  return CART.map((i, idx) => `
    <div class="row">
      <div class="row-main" data-act="edit" data-i="${idx}">
        <div class="row-title">${esc(i.name)}</div>
        <div class="row-sub">${qty(i.qty)} ${esc(i.unit)} × ${money(i.price)}</div>
      </div>
      <div class="row-end num">${money(i.qty * i.price)}</div>
      <button class="btn danger sm" data-act="del" data-i="${idx}">✕</button>
    </div>`).join("");
}

function sheetCartItem(product, index) {
  const item = index != null ? CART[index] : {
    product_id: product.id, name: product.name, unit: product.unit,
    qty: 1, price: product.price || 0,
  };
  sheet(`
    <h2>${esc(item.name)}</h2>
    <p class="hint">${esc(item.unit)} · ${product && product.price ? money(product.price) + " so'm" : "narx belgilanmagan"}</p>
    <label>Miqdor (${esc(item.unit)})</label>
    <div class="stepper">
      <button data-step="-1">−</button>
      <input id="qty" type="number" inputmode="decimal" step="any" value="${item.qty}">
      <button data-step="1">+</button>
    </div>
    <label>Sotish narxi (1 ${esc(item.unit)})</label>
    <input id="price" type="number" inputmode="decimal" step="any" value="${item.price}">
    <div class="btn-row">
      <button class="btn line" data-close>Bekor</button>
      <button class="btn" id="save">Savatga</button>
    </div>
  `);
  sheetEl.onclick = (e) => {
    const step = e.target.closest("[data-step]");
    if (step) {
      const inp = $("#qty", sheetEl);
      inp.value = Math.max(0, (Number(inp.value) || 0) + Number(step.dataset.step));
    }
    if (e.target.closest("[data-close]")) closeSheet();
  };
  $("#save", sheetEl).onclick = () => {
    const q = Number($("#qty", sheetEl).value), p = Number($("#price", sheetEl).value);
    if (!(q > 0)) return toast("Miqdorni kiriting", true);
    if (!(p >= 0)) return toast("Narxni kiriting", true);
    const next = Object.assign({}, item, { qty: q, price: p });
    if (index != null) CART[index] = next; else CART.push(next);
    closeSheet(); haptic();
    if (TAB === "sale") drawSale(); else if (TAB === "catalog") screenCatalog();
  };
}

async function sheetCheckout() {
  const methods = await api("/payment-methods");
  const total = cartTotal();
  sheet(`
    <h2>To'lov</h2>
    <p class="hint">Jami: <b>${money(total)} so'm</b>${LAST.saleCustomer ? " · " + esc(LAST.saleCustomer.name) : ""}</p>
    <label>To'lov turi</label>
    <select id="method">${methods.map((m) => `<option value="${m.id}">${esc(m.name)}</option>`).join("")}</select>
    <label>To'langan summa</label>
    <input id="paid" type="number" inputmode="decimal" step="any" value="${total}">
    <div class="btn-row">
      <button class="btn line" id="full">To'liq</button>
      <button class="btn line" id="none">To'lamadi</button>
    </div>
    <label>Izoh</label>
    <input id="comment" placeholder="ixtiyoriy">
    <div style="height:14px"></div>
    <button class="btn" id="save">Savdoni saqlash</button>
  `);
  $("#full", sheetEl).onclick = () => { $("#paid", sheetEl).value = total; };
  $("#none", sheetEl).onclick = () => { $("#paid", sheetEl).value = 0; };
  $("#save", sheetEl).onclick = () => guard(async () => {
    const sale = await api("/sales", { method: "POST", body: {
      customer_id: LAST.saleCustomer ? LAST.saleCustomer.id : null,
      payment_method_id: Number($("#method", sheetEl).value) || null,
      paid: Number($("#paid", sheetEl).value) || 0,
      comment: $("#comment", sheetEl).value,
      items: CART.map((i) => ({ product_id: i.product_id, qty: i.qty, price: i.price })),
    }});
    closeSheet(); haptic("medium");
    toast(`Savdo #${sale.id} saqlandi · qarz ${money(sale.debt)}`);
    CART = []; LAST.saleCustomer = null; drawSale();
  });
}

/* ---------------- Tanlagichlar ---------------- */

async function pickCustomer(onPick, allowQuick) {
  const list = await api("/customers");
  sheet(`
    <h2>Mijoz tanlang</h2>
    <input id="q" placeholder="Ism yoki telefon bo'yicha qidirish">
    <div class="btn-row">
      ${allowQuick ? '<button class="btn line" data-quick>🚶 Tezkor savdo</button>' : ""}
      <button class="btn ghost" data-new>➕ Yangi mijoz</button>
    </div>
    <div class="card tight" id="list" style="margin-top:10px">${list.map(customerRow).join("") ||
      '<div class="empty"><i>👥</i>Mijoz yo\'q</div>'}</div>
  `);
  const draw = (items) => { $("#list", sheetEl).innerHTML = items.map(customerRow).join("") ||
    '<div class="empty">Topilmadi</div>'; };
  $("#q", sheetEl).oninput = (e) => {
    const term = e.target.value.toLowerCase();
    draw(list.filter((c) => c.name.toLowerCase().includes(term) ||
                            (c.phone || "").includes(term)));
  };
  sheetEl.onclick = (e) => {
    if (e.target.closest("[data-quick]")) { closeSheet(); return onPick(null); }
    if (e.target.closest("[data-new]")) return sheetCustomer((c) => { closeSheet(); onPick(c); });
    const row = e.target.closest("[data-customer]");
    if (row) {
      const picked = list.find((c) => c.id === Number(row.dataset.customer));
      closeSheet(); haptic(); onPick(picked);
    }
  };
}

function customerRow(c) {
  return `<div class="row" data-customer="${c.id}">
    ${c.photo ? `<img class="thumb" src="${esc(c.photo)}" alt="">` : '<div class="thumb">👤</div>'}
    <div class="row-main"><div class="row-title">${esc(c.name)}</div>
      <div class="row-sub">${esc(c.phone || "telefon yo'q")}</div></div>
    <div class="row-end">${c.balance > 0
      ? `<span class="badge debt">${money(c.balance)}</span>`
      : c.balance < 0 ? `<span class="badge ok">+${money(-c.balance)}</span>`
      : '<span class="badge">0</span>'}</div>
  </div>`;
}

async function pickProduct(onPick) {
  const list = await api("/products");
  sheet(`
    <h2>Mahsulot tanlang</h2>
    <input id="q" placeholder="Nomi bo'yicha qidirish">
    <div class="card tight" id="list" style="margin-top:10px">${list.map(productRow).join("") ||
      '<div class="empty"><i>📦</i>Mahsulot yo\'q</div>'}</div>
  `);
  $("#q", sheetEl).oninput = (e) => {
    const term = e.target.value.toLowerCase();
    $("#list", sheetEl).innerHTML =
      list.filter((p) => p.name.toLowerCase().includes(term)).map(productRow).join("") ||
      '<div class="empty">Topilmadi</div>';
  };
  sheetEl.onclick = (e) => {
    const row = e.target.closest("[data-product]");
    if (!row) return;
    const picked = list.find((p) => p.id === Number(row.dataset.product));
    closeSheet(); haptic(); onPick(picked);
  };
}

function productRow(p) {
  return `<div class="row" data-product="${p.id}">
    ${p.photo ? `<img class="thumb" src="${esc(p.photo)}" alt="">` : '<div class="thumb">📦</div>'}
    <div class="row-main"><div class="row-title">${esc(p.name)}</div>
      <div class="row-sub">${esc(p.price_label)} · ${esc(p.unit)}</div></div>
    <div class="row-end num">${qty(p.stock)}</div>
  </div>`;
}

/* ---------------- Mahsulotlar ---------------- */

async function screenProducts() {
  loading();
  await guard(async () => {
    const list = await api("/products");
    render(`
      <div class="search"><input id="q" placeholder="🔎 Mahsulot qidirish"></div>
      ${ME.user.is_manager ? '<button class="btn ghost" data-act="new">➕ Yangi mahsulot</button><div style="height:10px"></div>' : ""}
      <div class="card tight" id="list">${list.map(productRow).join("") ||
        '<div class="empty"><i>📦</i>Hali mahsulot qo\'shilmagan</div>'}</div>
    `);
    $("#q").oninput = (e) => {
      const term = e.target.value.toLowerCase();
      $("#list").innerHTML = list.filter((p) => p.name.toLowerCase().includes(term))
        .map(productRow).join("") || '<div class="empty">Topilmadi</div>';
    };
    view.onclick = (e) => {
      if (e.target.closest('[data-act="new"]')) return sheetProduct();
      const row = e.target.closest("[data-product]");
      if (row) sheetProduct(list.find((p) => p.id === Number(row.dataset.product)));
    };
  });
}

async function sheetProduct(product, after) {
  const suppliers = await api("/suppliers").catch(() => []);
  const editing = Boolean(product);
  sheet(`
    <h2>${editing ? esc(product.name) : "Yangi mahsulot"}</h2>
    <p class="hint">Narx majburiy emas — keyin ham qo'yish mumkin.</p>
    <label>Nomi</label>
    <input id="name" value="${editing ? esc(product.name) : ""}" placeholder="Masalan: Guruch">
    <div class="field-grid">
      <div><label>Narxi</label>
        <input id="price" type="number" inputmode="decimal" step="any"
               value="${editing && product.price != null ? product.price : ""}" placeholder="ixtiyoriy"></div>
      <div><label>Birlik</label>
        <select id="unit">${["dona", "kg", "litr", "metr", "quti"].map((u) =>
          `<option value="${u}" ${editing && product.unit === u ? "selected" : ""}>${u}</option>`).join("")}</select></div>
    </div>
    <label>Yetkazib beruvchi</label>
    <select id="supplier"><option value="">— tanlanmagan —</option>
      ${suppliers.map((s) => `<option value="${s.id}" ${editing && product.supplier_id === s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select>
    ${editing ? `<label>Qoldiq</label><input id="stock" type="number" step="any" value="${product.stock}">` : ""}
    <label>Rasm</label>
    <input id="photo" type="file" accept="image/*">
    <div id="photoPreview">${editing && product.photo ? `<img src="${esc(product.photo)}" style="width:100%;max-height:180px;object-fit:cover;border-radius:14px;margin-top:8px">` : ""}</div>
    <div style="height:14px"></div>
    <button class="btn" id="save">${editing ? "Saqlash" : "Qo'shish"}</button>
    ${editing ? '<div style="height:8px"></div><button class="btn danger" id="del">🗑 O\'chirish</button>' : ""}
  `);

  let photoUrl = editing ? product.photo : null;
  $("#photo", sheetEl).onchange = (e) => guard(async () => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    toast("Rasm yuklanmoqda…");
    const res = await api("/upload", { method: "POST", body: fd });
    photoUrl = res.url;
    $("#photoPreview", sheetEl).innerHTML =
      `<img src="${esc(photoUrl)}" style="width:100%;max-height:180px;object-fit:cover;border-radius:14px;margin-top:8px">`;
    toast("Rasm yuklandi");
  });

  $("#save", sheetEl).onclick = () => guard(async () => {
    const body = {
      name: $("#name", sheetEl).value.trim(),
      price: $("#price", sheetEl).value,
      unit: $("#unit", sheetEl).value,
      supplier_id: $("#supplier", sheetEl).value || null,
      photo: photoUrl,
    };
    if (editing && $("#stock", sheetEl)) body.stock = $("#stock", sheetEl).value;
    if (!body.name) return toast("Nomini kiriting", true);
    if (editing) await api("/products/" + product.id, { method: "PATCH", body });
    else await api("/products", { method: "POST", body });
    closeSheet(); haptic("medium"); toast("Saqlandi");
    after ? after() : (TAB === "products" ? screenProducts() : go(TAB));
  });

  if (editing) $("#del", sheetEl).onclick = () => guard(async () => {
    await api("/products/" + product.id, { method: "DELETE" });
    closeSheet(); toast("O'chirildi"); screenProducts();
  });
}

/* ---------------- Mijozlar ---------------- */

async function screenCustomers() {
  loading();
  await guard(async () => {
    const list = await api("/customers");
    const debt = list.filter((c) => c.balance > 0).reduce((s, c) => s + c.balance, 0);
    render(`
      <div class="metric" style="margin-bottom:12px">
        <div class="metric-label">Umumiy qarzdorlik</div>
        <div class="num-lg debt">${money(debt)}</div>
        <div class="row-sub">${list.length} ta mijoz</div>
      </div>
      <div class="search"><input id="q" placeholder="🔎 Ism yoki telefon"></div>
      <button class="btn ghost" data-act="new">➕ Yangi mijoz</button>
      <div style="height:10px"></div>
      <div class="seg"><button class="on" data-f="all">Hammasi</button>
        <button data-f="debt">Qarzdorlar</button></div>
      <div class="card tight" id="list">${list.map(customerRow).join("") ||
        '<div class="empty"><i>👥</i>Mijoz yo\'q</div>'}</div>
    `);
    let filter = "all", term = "";
    const draw = () => {
      const items = list.filter((c) =>
        (filter === "all" || c.balance > 0) &&
        (c.name.toLowerCase().includes(term) || (c.phone || "").includes(term)));
      $("#list").innerHTML = items.map(customerRow).join("") || '<div class="empty">Topilmadi</div>';
    };
    $("#q").oninput = (e) => { term = e.target.value.toLowerCase(); draw(); };
    view.onclick = (e) => {
      const f = e.target.closest("[data-f]");
      if (f) { filter = f.dataset.f; $$("[data-f]").forEach((b) => b.classList.toggle("on", b === f)); return draw(); }
      if (e.target.closest('[data-act="new"]')) return sheetCustomer();
      const row = e.target.closest("[data-customer]");
      if (row) sheetCustomerDetail(Number(row.dataset.customer));
    };
  });
}

function sheetCustomer(after) {
  sheet(`
    <h2>Yangi mijoz</h2>
    <label>Ismi</label><input id="name" placeholder="Masalan: Alisher aka">
    <label>Telefon</label><input id="phone" type="tel" inputmode="tel" placeholder="+998 90 123 45 67">
    <label>Manzil</label><input id="address" placeholder="ixtiyoriy">
    <label>Oldingi qarzi</label>
    <input id="balance" type="number" inputmode="decimal" step="any" value="0">
    <p class="hint">Qarzi bo'lmasa 0 qoldiring.</p>
    <label>Rasm</label><input id="photo" type="file" accept="image/*">
    <div id="pv"></div>
    <div style="height:14px"></div>
    <button class="btn" id="save">Qo'shish</button>
  `);
  let photoUrl = null;
  $("#photo", sheetEl).onchange = (e) => guard(async () => {
    const file = e.target.files[0]; if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    const res = await api("/upload", { method: "POST", body: fd });
    photoUrl = res.url;
    $("#pv", sheetEl).innerHTML = `<img src="${esc(photoUrl)}" style="width:96px;height:96px;object-fit:cover;border-radius:14px;margin-top:8px">`;
  });
  $("#save", sheetEl).onclick = () => guard(async () => {
    const body = {
      name: $("#name", sheetEl).value.trim(),
      phone: $("#phone", sheetEl).value,
      address: $("#address", sheetEl).value,
      balance: $("#balance", sheetEl).value || 0,
      photo: photoUrl,
    };
    if (!body.name) return toast("Ismini kiriting", true);
    const created = await api("/customers", { method: "POST", body });
    closeSheet(); haptic("medium"); toast("Mijoz qo'shildi");
    after ? after(created) : (TAB === "customers" ? screenCustomers() : null);
  });
}

async function sheetCustomerDetail(id) {
  const data = await api("/customers/" + id);
  const c = data.customer;
  sheet(`
    <h2>${esc(c.name)}</h2>
    <p class="hint">${esc(c.phone || "telefon yo'q")} · ${esc(c.address || "manzil yo'q")}</p>
    <div class="metric" style="margin:10px 0">
      <div class="metric-label">Balans</div>
      <div class="num-lg ${c.balance > 0 ? "debt" : "ok"}">${money(c.balance)}</div>
      <div class="row-sub">${esc(c.balance_label)}</div>
    </div>
    <div class="btn-row">
      <button class="btn" data-op="payment">➖ Pul oldim</button>
      <button class="btn line" data-op="debt">➕ Qarz</button>
      <button class="btn line" data-op="set">✏️ To'g'rilash</button>
    </div>
    <div class="seg" style="margin-top:14px">
      <button class="on" data-v="ledger">Kirim-chiqim</button>
      <button data-v="sales">Xaridlari</button>
    </div>
    <div class="card tight" id="tabc">${ledgerList(data.ledger)}</div>
  `);
  sheetEl.onclick = (e) => {
    const op = e.target.closest("[data-op]");
    if (op) return sheetBalanceOp(c, op.dataset.op);
    const v = e.target.closest("[data-v]");
    if (v) {
      $$("[data-v]", sheetEl).forEach((b) => b.classList.toggle("on", b === v));
      $("#tabc", sheetEl).innerHTML = v.dataset.v === "ledger"
        ? ledgerList(data.ledger) : salesList(data.sales);
    }
  };
}

function ledgerList(items) {
  if (!items.length) return '<div class="empty"><i>📊</i>Yozuvlar yo\'q</div>';
  const label = { initial: "Boshlang'ich", correction: "To'g'rilash", sale: "Savdo",
                  payment: "To'lov", order: "Buyurtma" };
  return items.map((e) => `<div class="row" style="cursor:default">
    <div class="row-main"><div class="row-title">${label[e.type] || e.type}</div>
      <div class="row-sub">${dateFmt(e.date)}${e.comment ? " · " + esc(e.comment) : ""}</div></div>
    <div class="row-end num" style="color:${e.amount > 0 ? "var(--danger)" : "var(--ok)"}">
      ${e.amount > 0 ? "+" : "−"}${money(Math.abs(e.amount))}</div>
  </div>`).join("");
}

function salesList(items) {
  if (!items.length) return '<div class="empty"><i>🧾</i>Xaridlar yo\'q</div>';
  return items.map((s) => `<div class="row" style="cursor:default">
    <div class="row-main"><div class="row-title">#${s.id} · ${money(s.total)} so'm</div>
      <div class="row-sub">${dateFmt(s.date)} · ${esc(s.items.map((i) => i.name).join(", "))}</div></div>
    <div class="row-end">${s.debt > 0 ? `<span class="badge debt">${money(s.debt)}</span>` : '<span class="badge ok">to\'liq</span>'}</div>
  </div>`).join("");
}

function sheetBalanceOp(customer, op) {
  const titles = { payment: "Pul qabul qilish", debt: "Qarz qo'shish", set: "Balansni to'g'rilash" };
  sheet(`
    <h2>${titles[op]}</h2>
    <p class="hint">${esc(customer.name)} · hozir: ${esc(customer.balance_label)}</p>
    <label>Summa</label>
    <input id="amount" type="number" inputmode="decimal" step="any" autofocus
           value="${op === "set" ? customer.balance : ""}">
    ${op === "set" ? '<p class="hint">Qarzdor bo\'lsa musbat, haqdor bo\'lsa manfiy son.</p>' : ""}
    <label>Izoh</label><input id="comment" placeholder="ixtiyoriy">
    <div style="height:14px"></div>
    <button class="btn" id="save">Saqlash</button>
  `);
  $("#save", sheetEl).onclick = () => guard(async () => {
    const updated = await api(`/customers/${customer.id}/balance`, { method: "POST", body: {
      action: op, amount: $("#amount", sheetEl).value,
      comment: $("#comment", sheetEl).value,
    }});
    closeSheet(); haptic("medium");
    toast(`${updated.name}: ${updated.balance_label}`);
    if (TAB === "customers") screenCustomers();
  });
}

/* ---------------- Buyurtmalar (hodim) ---------------- */

function orderRow(o) {
  const [label, cls] = STATUS[o.status] || [o.status, ""];
  return `<div class="row" data-order="${o.id}">
    <div class="thumb">🧾</div>
    <div class="row-main"><div class="row-title">#${o.id} · ${esc(o.customer)}</div>
      <div class="row-sub">${esc(o.needed_at || dateFmt(o.date))} · ${DELIVERY[o.delivery]}</div></div>
    <div class="row-end"><span class="badge ${cls}">${label}</span><br>
      <span class="num" style="font-size:.8rem">${money(o.total)}</span></div>
  </div>`;
}

async function screenOrders() {
  loading();
  await guard(async () => {
    const all = await api("/orders");
    LAST.orders = all;
    const open = all.filter((o) => !["done", "cancelled"].includes(o.status));
    render(`
      <div class="seg"><button class="on" data-f="open">Ochiq (${open.length})</button>
        <button data-f="all">Hammasi (${all.length})</button></div>
      <div class="card tight" id="list">${open.map(orderRow).join("") ||
        '<div class="empty"><i>📭</i>Ochiq buyurtma yo\'q</div>'}</div>
    `);
    view.onclick = (e) => {
      const f = e.target.closest("[data-f]");
      if (f) {
        $$("[data-f]").forEach((b) => b.classList.toggle("on", b === f));
        const items = f.dataset.f === "open" ? open : all;
        $("#list").innerHTML = items.map(orderRow).join("") || '<div class="empty">Bo\'sh</div>';
        return;
      }
      const row = e.target.closest("[data-order]");
      if (row) sheetOrder(Number(row.dataset.order));
    };
  });
}

function sheetOrder(id) {
  const o = (LAST.orders || []).find((x) => x.id === id);
  if (!o) return guard(async () => { LAST.orders = await api("/orders"); sheetOrder(id); });
  const [label, cls] = STATUS[o.status] || [o.status, ""];
  const staff = ME.user.is_staff;

  const itemRows = o.items.map((i) => `
    <div class="row" style="cursor:default">
      <div class="row-main"><div class="row-title">${esc(i.name)}</div>
        <div class="row-sub">${qty(i.qty)} ${esc(i.unit)} × ${money(i.price)}</div></div>
      <div class="row-end num">${money(i.amount)}</div>
    </div>`).join("");

  let actions = "";
  if (staff) {
    if (o.status === "new") actions = `<button class="btn" data-op="price">💵 Narxlash va yuborish</button>`;
    else if (o.status === "priced") actions = `<button class="btn line" data-op="price">✏️ Narxni o'zgartirish</button>`;
    else if (o.status === "confirmed") actions = `<button class="btn" data-op="schedule">⏰ Yetkazish vaqtini belgilash</button>`;
    else if (o.status === "scheduled") actions = `<button class="btn" data-op="done">📦 Yetkazildi</button>`;
    if (!["done", "cancelled"].includes(o.status))
      actions += `<div style="height:8px"></div><button class="btn danger" data-op="cancel">Bekor qilish</button>`;
  }

  sheet(`
    <h2>Buyurtma #${o.id}</h2>
    <p class="hint">${esc(o.customer)} · ${esc(o.customer_phone || "—")}</p>
    <div class="card tight" style="margin-top:10px">
      <div class="row" style="cursor:default"><div class="row-main">
        <div class="row-sub">Holati</div></div><div class="row-end"><span class="badge ${cls}">${label}</span></div></div>
      <div class="row" style="cursor:default"><div class="row-main">
        <div class="row-sub">Yetkazish</div></div><div class="row-end">${DELIVERY[o.delivery]}</div></div>
      <div class="row" style="cursor:default"><div class="row-main">
        <div class="row-sub">Qachonga</div></div><div class="row-end">${esc(o.needed_at || "—")}</div></div>
      <div class="row" style="cursor:default"><div class="row-main">
        <div class="row-sub">Kelishilgan vaqt</div></div><div class="row-end">${esc(o.delivery_time || "—")}</div></div>
      ${o.address ? `<div class="row" style="cursor:default"><div class="row-main">
        <div class="row-sub">Manzil</div></div><div class="row-end">${esc(o.address)}</div></div>` : ""}
    </div>
    <div class="section-title">Mahsulotlar</div>
    <div class="card tight">${itemRows}</div>
    <div class="metric" style="margin:10px 0"><div class="metric-label">Jami</div>
      <div class="num-lg">${money(o.total)}</div></div>
    ${actions}
  `);

  sheetEl.onclick = (e) => {
    const op = e.target.closest("[data-op]");
    if (!op) return;
    if (op.dataset.op === "price") return sheetOrderPrice(o);
    if (op.dataset.op === "schedule") return sheetSchedule(o);
    if (op.dataset.op === "done") return guard(async () => {
      await api(`/orders/${o.id}/done`, { method: "POST" });
      closeSheet(); haptic("medium"); toast("Yetkazildi, savdoga yozildi"); screenOrders();
    });
    if (op.dataset.op === "cancel") return guard(async () => {
      await api(`/orders/${o.id}/cancel`, { method: "POST" });
      closeSheet(); toast("Bekor qilindi");
      ME.user.is_staff ? screenOrders() : screenMyOrders();
    });
  };
}

function sheetOrderPrice(o) {
  sheet(`
    <h2>Narxlash · #${o.id}</h2>
    <p class="hint">Miqdor va narxni aniqlang — mijozga shu ko'rinishda yuboriladi.</p>
    ${o.items.map((i) => `
      <div class="card" style="margin-top:10px">
        <div class="row-title">${esc(i.name)}</div>
        <div class="field-grid">
          <div><label>Miqdor (${esc(i.unit)})</label>
            <input class="q" data-id="${i.id}" type="number" inputmode="decimal" step="any" value="${i.qty}"></div>
          <div><label>1 ${esc(i.unit)} narxi</label>
            <input class="p" data-id="${i.id}" type="number" inputmode="decimal" step="any" value="${i.price}"></div>
        </div>
      </div>`).join("")}
    <div style="height:14px"></div>
    <button class="btn" id="send">Mijozga yuborish</button>
  `);
  $("#send", sheetEl).onclick = () => guard(async () => {
    const prices = {}, quantities = {};
    $$(".p", sheetEl).forEach((el) => { prices[el.dataset.id] = el.value || 0; });
    $$(".q", sheetEl).forEach((el) => { quantities[el.dataset.id] = el.value || 0; });
    await api(`/orders/${o.id}/price`, { method: "POST", body: { prices, quantities } });
    closeSheet(); haptic("medium"); toast("Mijozga yuborildi"); screenOrders();
  });
}

function sheetSchedule(o) {
  sheet(`
    <h2>Yetkazish vaqti</h2>
    <p class="hint">Taxminiy vaqtni yozing — mijozga xabar boradi.</p>
    <label>Vaqt</label>
    <input id="time" placeholder="Masalan: bugun 16:00 — 17:00">
    <div style="height:14px"></div>
    <button class="btn" id="save">Yuborish</button>
  `);
  $("#save", sheetEl).onclick = () => guard(async () => {
    await api(`/orders/${o.id}/schedule`, { method: "POST", body: {
      delivery_time: $("#time", sheetEl).value }});
    closeSheet(); haptic("medium"); toast("Vaqt yuborildi"); screenOrders();
  });
}

/* ---------------- Mijoz: katalog va buyurtma ---------------- */

async function screenCatalog() {
  loading();
  await guard(async () => {
    const list = await api("/products");
    render(`
      <div class="search"><input id="q" placeholder="🔎 Mahsulot qidirish"></div>
      <div class="pgrid" id="pgrid">${list.map(productTile).join("") ||
        '<div class="empty wide"><i>🛍</i>Katalog bo\'sh</div>'}</div>
      ${cartBar()}
    `);
    $("#q").oninput = (e) => {
      const term = e.target.value.toLowerCase();
      $("#pgrid").innerHTML = list.filter((p) => p.name.toLowerCase().includes(term))
        .map(productTile).join("") || '<div class="empty wide">Topilmadi</div>';
    };
    view.onclick = (e) => {
      if (e.target.closest("#cartBar")) return sheetOrderCheckout();
      const tile = e.target.closest("[data-prod]");
      if (tile) sheetCartItem(list.find((p) => p.id === Number(tile.dataset.prod)));
    };
  });
}

function cartBar() {
  if (!CART.length) return "";
  return `<button class="cart-bar" id="cartBar">
    <span class="count">${CART.length}</span> Buyurtmani rasmiylashtirish
    <span class="sum">${money(cartTotal())}</span></button>`;
}

function sheetOrderCheckout() {
  sheet(`
    <h2>Buyurtma</h2>
    <div class="card tight">${CART.map((i, idx) => `
      <div class="row">
        <div class="row-main"><div class="row-title">${esc(i.name)}</div>
          <div class="row-sub">${qty(i.qty)} ${esc(i.unit)}</div></div>
        <button class="btn danger sm" data-del="${idx}">✕</button>
      </div>`).join("")}</div>
    <label>Qachonga kerak?</label>
    <input id="needed" placeholder="Masalan: ertaga ertalab">
    <label>Yetkazib berish</label>
    <select id="delivery">
      <option value="pickup">🏬 O'zim olib ketaman</option>
      <option value="own_driver">🚗 O'zimning haydovchim bor</option>
      <option value="shop_taxi">🚕 Sizning taxi xizmatingiz orqali</option>
    </select>
    <div id="addrBox" hidden><label>Manzil</label><input id="address" placeholder="Yetkazish manzili"></div>
    <label>Izoh</label><input id="comment" placeholder="ixtiyoriy">
    <div style="height:14px"></div>
    <button class="btn" id="send">Buyurtmani yuborish</button>
    <p class="hint" style="margin-top:10px">Do'kon narxlarni aniqlab sizga yuboradi — keyin tasdiqlaysiz.</p>
  `);
  const delivery = $("#delivery", sheetEl);
  const toggle = () => { $("#addrBox", sheetEl).hidden = delivery.value === "pickup"; };
  delivery.onchange = toggle; toggle();

  sheetEl.onclick = (e) => {
    const del = e.target.closest("[data-del]");
    if (del) { CART.splice(Number(del.dataset.del), 1); closeSheet(); screenCatalog(); }
  };
  $("#send", sheetEl).onclick = () => guard(async () => {
    if (!CART.length) return toast("Savat bo'sh", true);
    const order = await api("/orders", { method: "POST", body: {
      items: CART.map((i) => ({ product_id: i.product_id, qty: i.qty })),
      needed_at: $("#needed", sheetEl).value,
      delivery: delivery.value,
      address: $("#address", sheetEl) ? $("#address", sheetEl).value : "",
      comment: $("#comment", sheetEl).value,
    }});
    CART = []; closeSheet(); haptic("medium");
    toast(`Buyurtma #${order.id} yuborildi`);
    go("myorders");
  });
}

async function screenMyOrders() {
  loading();
  await guard(async () => {
    const list = await api("/orders?scope=mine");
    LAST.orders = list;
    render(`<div class="card tight">${list.map(myOrderRow).join("") ||
      '<div class="empty"><i>📦</i>Hali buyurtma bermagansiz</div>'}</div>`);
    view.onclick = (e) => {
      const row = e.target.closest("[data-order]");
      if (row) sheetMyOrder(Number(row.dataset.order));
    };
  });
}

function myOrderRow(o) {
  const [label, cls] = STATUS[o.status] || [o.status, ""];
  return `<div class="row" data-order="${o.id}">
    <div class="thumb">${o.status === "priced" ? "❗️" : "🧾"}</div>
    <div class="row-main"><div class="row-title">#${o.id} · ${money(o.total)} so'm</div>
      <div class="row-sub">${dateFmt(o.date)} · ${o.items.length} ta mahsulot</div></div>
    <div class="row-end"><span class="badge ${cls}">${label}</span></div>
  </div>`;
}

function sheetMyOrder(id) {
  const o = (LAST.orders || []).find((x) => x.id === id);
  if (!o) return;
  const [label, cls] = STATUS[o.status] || [o.status, ""];
  const needDriverTime = o.status === "priced" && o.delivery === "own_driver";

  sheet(`
    <h2>Buyurtma #${o.id}</h2>
    <p class="hint"><span class="badge ${cls}">${label}</span> · ${DELIVERY[o.delivery]}</p>
    <div class="card tight" style="margin-top:10px">${o.items.map((i) => `
      <div class="row" style="cursor:default">
        <div class="row-main"><div class="row-title">${esc(i.name)}</div>
          <div class="row-sub">${qty(i.qty)} ${esc(i.unit)} × ${money(i.price)}</div></div>
        <div class="row-end num">${money(i.amount)}</div></div>`).join("")}</div>
    <div class="metric" style="margin:10px 0"><div class="metric-label">Jami</div>
      <div class="num-lg">${money(o.total)}</div></div>
    ${o.delivery_time ? `<p class="hint">⏰ Kelishilgan vaqt: <b>${esc(o.delivery_time)}</b></p>` : ""}
    ${needDriverTime ? `<label>Haydovchingiz qachon boradi?</label>
      <input id="driver" placeholder="Masalan: ertaga soat 9:00">` : ""}
    ${o.status === "priced" ? `<div style="height:12px"></div>
      <button class="btn" data-op="confirm">✅ Tasdiqlayman</button>
      <div style="height:8px"></div>
      <button class="btn danger" data-op="cancel">Bekor qilaman</button>` : ""}
    ${["new"].includes(o.status) ? `<div style="height:12px"></div>
      <button class="btn danger" data-op="cancel">Bekor qilish</button>` : ""}
  `);

  sheetEl.onclick = (e) => {
    const op = e.target.closest("[data-op]");
    if (!op) return;
    if (op.dataset.op === "confirm") return guard(async () => {
      const driverInput = $("#driver", sheetEl);
      if (needDriverTime && !driverInput.value.trim())
        return toast("Haydovchi vaqtini yozing", true);
      await api(`/orders/${o.id}/confirm`, { method: "POST", body: {
        driver_time: driverInput ? driverInput.value : "" }});
      closeSheet(); haptic("medium"); toast("Tasdiqlandi"); screenMyOrders();
    });
    if (op.dataset.op === "cancel") return guard(async () => {
      await api(`/orders/${o.id}/cancel`, { method: "POST" });
      closeSheet(); toast("Bekor qilindi"); screenMyOrders();
    });
  };
}

async function screenBalance() {
  loading();
  await guard(async () => {
    const data = await api("/my/summary");
    render(`
      <div class="metric" style="margin-bottom:12px">
        <div class="metric-label">Balansingiz</div>
        <div class="num-lg ${data.balance > 0 ? "debt" : "ok"}">${money(data.balance)}</div>
        <div class="row-sub">${esc(data.balance_label)}</div>
      </div>
      <div class="seg"><button class="on" data-v="ledger">Kirim-chiqim</button>
        <button data-v="sales">Xaridlarim</button></div>
      <div class="card tight" id="box">${ledgerList(data.ledger)}</div>
    `);
    view.onclick = (e) => {
      const v = e.target.closest("[data-v]");
      if (!v) return;
      $$("[data-v]").forEach((b) => b.classList.toggle("on", b === v));
      $("#box").innerHTML = v.dataset.v === "ledger" ? ledgerList(data.ledger) : salesList(data.sales);
    };
  });
}

/* ---------------- Yana ---------------- */

function screenMore() {
  const staff = ME.user.is_staff;
  const manager = ME.user.is_manager;
  render(`
    <div class="card tight">
      ${staff ? `
      <div class="row" data-go2="products"><div class="thumb">📦</div>
        <div class="row-main"><div class="row-title">Mahsulotlar</div>
          <div class="row-sub">narx, rasm, qoldiq</div></div><div class="row-end">›</div></div>
      <div class="row" data-go2="sales"><div class="thumb">🧾</div>
        <div class="row-main"><div class="row-title">Savdolar tarixi</div>
          <div class="row-sub">barcha yopilgan savdolar</div></div><div class="row-end">›</div></div>` : ""}
      ${manager ? `
      <div class="row" data-go2="suppliers"><div class="thumb">🚚</div>
        <div class="row-main"><div class="row-title">Yetkazib beruvchilar</div>
          <div class="row-sub">nomi va telefoni</div></div><div class="row-end">›</div></div>
      <div class="row" data-go2="methods"><div class="thumb">💳</div>
        <div class="row-main"><div class="row-title">To'lov turlari</div>
          <div class="row-sub">naqd, karta, o'tkazma…</div></div><div class="row-end">›</div></div>
      <div class="row" data-go2="staff"><div class="thumb">👤</div>
        <div class="row-main"><div class="row-title">Hodimlar va takliflar</div>
          <div class="row-sub">login yaratish, havola</div></div><div class="row-end">›</div></div>
      <div class="row" data-go2="license"><div class="thumb">🔐</div>
        <div class="row-main"><div class="row-title">Obuna</div>
          <div class="row-sub">${ME.shop.license_ok ? ME.shop.days_left + " kun qoldi" : "muddati tugagan"}</div></div>
        <div class="row-end">›</div></div>` : ""}
      ${ME.shops.length > 1 ? `
      <div class="row" data-go2="shops"><div class="thumb">🏬</div>
        <div class="row-main"><div class="row-title">Biznesni almashtirish</div>
          <div class="row-sub">${ME.shops.length} ta biznes</div></div><div class="row-end">›</div></div>` : ""}
      <div class="row" data-go2="about"><div class="thumb">ℹ️</div>
        <div class="row-main"><div class="row-title">Dastur haqida</div>
          <div class="row-sub">v${esc(ME.about.version)}</div></div><div class="row-end">›</div></div>
      ${standalone ? `
      <div class="row" data-go2="logout"><div class="thumb">🚪</div>
        <div class="row-main"><div class="row-title">Chiqish</div>
          <div class="row-sub">${esc(ME.user.phone || "")}</div></div><div class="row-end">›</div></div>` : ""}
    </div>
    <div id="installBox"></div>
    <p class="credit">${esc(ME.about.author)} — ${esc(ME.about.company)}</p>
  `);
  showInstallHint();
  view.onclick = (e) => {
    const r = e.target.closest("[data-go2]");
    if (!r) return;
    haptic();
    ({ products: screenProducts, sales: screenSales, suppliers: sheetSuppliers,
       methods: sheetMethods, staff: screenStaff, license: sheetLicense,
       shops: sheetShops, about: sheetAbout, logout: logout })[r.dataset.go2]();
  };
}

async function screenSales() {
  loading();
  await guard(async () => {
    const list = await api("/sales");
    render(`<div class="card tight">${salesList(list)}</div>`);
  });
}

async function sheetSuppliers() {
  const list = await api("/suppliers");
  sheet(`
    <h2>Yetkazib beruvchilar</h2>
    <div class="card tight">${list.map((s) => `
      <div class="row" style="cursor:default">
        <div class="thumb">🚚</div>
        <div class="row-main"><div class="row-title">${esc(s.name)}</div>
          <div class="row-sub">${esc(s.phone || "telefon yo'q")}</div></div>
        <button class="btn danger sm" data-del="${s.id}">✕</button>
      </div>`).join("") || '<div class="empty"><i>🚚</i>Ro\'yxat bo\'sh</div>'}</div>
    <label>Nomi</label><input id="name" placeholder="Masalan: Agro Savdo">
    <label>Telefon</label><input id="phone" type="tel" placeholder="+998 90 123 45 67">
    <div style="height:12px"></div>
    <button class="btn" id="add">Qo'shish</button>
  `);
  $("#add", sheetEl).onclick = () => guard(async () => {
    await api("/suppliers", { method: "POST", body: {
      name: $("#name", sheetEl).value, phone: $("#phone", sheetEl).value }});
    toast("Qo'shildi"); sheetSuppliers();
  });
  sheetEl.onclick = (e) => {
    const del = e.target.closest("[data-del]");
    if (del) guard(async () => {
      await api("/suppliers/" + del.dataset.del, { method: "DELETE" });
      sheetSuppliers();
    });
  };
}

async function sheetMethods() {
  const list = await api("/payment-methods");
  sheet(`
    <h2>To'lov turlari</h2>
    <div class="card tight">${list.map((m) => `
      <div class="row" style="cursor:default">
        <div class="thumb">💳</div>
        <div class="row-main"><div class="row-title">${esc(m.name)}</div></div>
        <button class="btn danger sm" data-del="${m.id}">✕</button>
      </div>`).join("")}</div>
    <label>Yangi tur</label><input id="name" placeholder="Masalan: Click, Payme">
    <div style="height:12px"></div>
    <button class="btn" id="add">Qo'shish</button>
  `);
  $("#add", sheetEl).onclick = () => guard(async () => {
    await api("/payment-methods", { method: "POST", body: { name: $("#name", sheetEl).value }});
    sheetMethods();
  });
  sheetEl.onclick = (e) => {
    const del = e.target.closest("[data-del]");
    if (del) guard(async () => {
      await api("/payment-methods/" + del.dataset.del, { method: "DELETE" });
      sheetMethods();
    });
  };
}

async function screenStaff() {
  loading();
  await guard(async () => {
    const data = await api("/staff");
    render(`
      <div class="section-title">Foydalanuvchilar</div>
      <div class="card tight">${data.users.map((u) => `
        <div class="row" data-user="${u.id}">
          <div class="thumb">${u.role === "customer" ? "🙍" : "🧑‍💼"}</div>
          <div class="row-main"><div class="row-title">${esc(u.name)}</div>
            <div class="row-sub">${esc(u.phone || "login yo'q")} · ${roleLabel(u.role)}</div></div>
          <div class="row-end">${u.status === "pending"
            ? '<span class="badge warn">kutilmoqda</span>'
            : u.status === "blocked" ? '<span class="badge debt">bloklangan</span>'
            : u.in_bot ? '<span class="badge ok">faol</span>' : '<span class="badge">kirmagan</span>'}</div>
        </div>`).join("")}</div>
      <button class="btn ghost" data-act="newStaff">➕ Hodimga login yaratish</button>

      <div class="section-title">Taklif havolalari</div>
      <div class="card tight">${data.invites.map((i) => `
        <div class="row" data-copy="${esc(i.link)}">
          <div class="thumb">🔗</div>
          <div class="row-main"><div class="row-title">${roleLabel(i.role)} uchun</div>
            <div class="row-sub" style="word-break:break-all">${esc(i.link)}</div></div>
          <div class="row-end">${i.uses} ta</div>
        </div>`).join("") || '<div class="empty"><i>🔗</i>Havola yaratilmagan</div>'}</div>
      <div class="btn-row">
        <button class="btn line" data-inv="seller">Sotuvchi</button>
        <button class="btn line" data-inv="admin">Admin</button>
        <button class="btn line" data-inv="customer">Mijoz</button>
      </div>
      <p class="hint" style="color:var(--muted);font-size:.8rem;margin-top:8px">
        Havola faqat shu biznesga qo'shadi. Har bir ariza sizga tasdiqlashga keladi.</p>
    `);
    view.onclick = (e) => {
      const inv = e.target.closest("[data-inv]");
      if (inv) return guard(async () => {
        await api("/invites", { method: "POST", body: { role: inv.dataset.inv }});
        toast("Havola yaratildi"); screenStaff();
      });
      const copy = e.target.closest("[data-copy]");
      if (copy) {
        navigator.clipboard.writeText(copy.dataset.copy).then(() => toast("Havola nusxalandi"));
        return;
      }
      if (e.target.closest('[data-act="newStaff"]')) return sheetNewStaff();
      const row = e.target.closest("[data-user]");
      if (row) sheetUser(data.users.find((u) => u.id === Number(row.dataset.user)));
    };
  });
}

function sheetNewStaff() {
  sheet(`
    <h2>Hodimga login yaratish</h2>
    <p class="hint">Login — telefon raqami. Hodim ilovaga shu raqam bilan kiradi.</p>
    <label>Ism-familiya</label><input id="name" placeholder="Masalan: Aziz Karimov">
    <label>Telefon (login)</label><input id="phone" type="tel" placeholder="+998 90 123 45 67">
    <label>Roli</label>
    <select id="role"><option value="seller">Sotuvchi</option>
      <option value="admin">Admin</option><option value="customer">Mijoz</option></select>
    <div style="height:14px"></div>
    <button class="btn" id="save">Yaratish</button>
  `);
  $("#save", sheetEl).onclick = () => guard(async () => {
    await api("/staff", { method: "POST", body: {
      name: $("#name", sheetEl).value, phone: $("#phone", sheetEl).value,
      role: $("#role", sheetEl).value }});
    closeSheet(); haptic("medium"); toast("Login yaratildi"); screenStaff();
  });
}

function sheetUser(u) {
  sheet(`
    <h2>${esc(u.name)}</h2>
    <p class="hint">${esc(u.phone || "login yo'q")} · ${roleLabel(u.role)} · ${u.status}</p>
    ${u.status === "pending" ? `<button class="btn" data-st="approved">✅ Tasdiqlash</button>
      <div style="height:8px"></div>
      <button class="btn danger" data-st="blocked">🚫 Rad etish</button>
      <div style="height:14px"></div>` : ""}
    <label>Rolini o'zgartirish</label>
    <select id="role">
      ${["owner", "admin", "seller", "customer"].map((r) =>
        `<option value="${r}" ${u.role === r ? "selected" : ""}>${roleLabel(r)}</option>`).join("")}
    </select>
    <div style="height:12px"></div>
    <button class="btn" id="save">Saqlash</button>
    ${u.status !== "blocked" ? '<div style="height:8px"></div><button class="btn danger" data-st="blocked">Bloklash</button>' : ""}
  `);
  const patch = (body) => guard(async () => {
    await api("/staff/" + u.id, { method: "PATCH", body });
    closeSheet(); haptic("medium"); toast("Saqlandi"); screenStaff();
  });
  $("#save", sheetEl).onclick = () => patch({ role: $("#role", sheetEl).value });
  sheetEl.onclick = (e) => {
    const st = e.target.closest("[data-st]");
    if (st) patch({ status: st.dataset.st });
  };
}

function sheetLicense() {
  const s = ME.shop;
  sheet(`
    <h2>Obuna</h2>
    <div class="metric" style="margin:10px 0">
      <div class="metric-label">Holati</div>
      <div class="num-lg ${s.license_ok ? "ok" : "debt"}">${s.license_ok ? "Faol" : "To'xtatilgan"}</div>
      <div class="row-sub">${s.license_until ? "Muddat: " + s.license_until : "—"} · ${s.days_left} kun qoldi</div>
    </div>
    <p class="hint">Biznes kodi: <b>${esc(s.code)}</b></p>
    <p class="hint">Muddatni uzaytirish uchun admin botga murojaat qiling — to'lov chekini yuborsangiz
    obuna faollashtiriladi.</p>
  `);
}

function sheetShops() {
  sheet(`
    <h2>Biznesni tanlang</h2>
    <div class="card tight">${ME.shops.map((s) => `
      <div class="row" data-shop="${s.id}">
        <div class="thumb">🏬</div>
        <div class="row-main"><div class="row-title">${esc(s.name)}</div>
          <div class="row-sub">${roleLabel(s.role)}</div></div>
        <div class="row-end">${s.active ? '<span class="badge ok">faol</span>' : "›"}</div>
      </div>`).join("")}</div>
  `);
  sheetEl.onclick = (e) => {
    const row = e.target.closest("[data-shop]");
    if (!row) return;
    guard(async () => {
      await api("/switch", { method: "POST", body: { shop_id: Number(row.dataset.shop) }});
      closeSheet(); haptic("medium");
      ME = await api("/me");
      CART = []; LAST = {};
      startApp();
      toast("Biznes almashtirildi");
    });
  };
}

function sheetAbout() {
  sheet(`
    <h2>Dastur haqida</h2>
    <p class="hint">Savdo, ombor, mijozlar va yetkazib berishni boshqarish tizimi.
    Har bir biznes o'z alohida bazasida ishlaydi.</p>
    <div class="card" style="margin-top:12px;text-align:center">
      <div style="font-size:2rem">👨‍💻</div>
      <div class="row-title" style="margin-top:6px">${esc(ME.about.author)}</div>
      <div class="row-sub">${esc(ME.about.company)}</div>
      <div class="row-sub">Versiya ${esc(ME.about.version)}</div>
    </div>
  `);
}

boot();
})();

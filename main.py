import asyncio
import html
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

import asyncpg
from telegram import (
    BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup,
    MenuButtonCommands, Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    Defaults, MessageHandler, filters,
)

# =========================
# الإعدادات (من Render → Environment)
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
_admin_raw = os.getenv("ADMIN_ID", "") or os.getenv("ADMIN_IDS", "")
ADMINS = {int(x) for x in _admin_raw.replace(" ", "").split(",") if x.isdigit()}

DATABASE_URL = os.getenv("DATABASE_URL", "")
STORE_NAME = os.getenv("STORE_NAME", "متجر النخبة")
SHAM_ADDRESS = os.getenv("SHAMCASH_ADDRESS", "ضع_عنوان_شام_كاش_هنا")
SHAM_ADDRESS_SYP = os.getenv("SHAMCASH_ADDRESS_SYP", "")  # اختياري: حساب الليرة إن كان مختلفاً
SHAM_NAME = os.getenv("SHAMCASH_NAME", "اسم صاحب الحساب")
MIN_TOPUP = float(os.getenv("MIN_TOPUP", "1"))  # بالدولار
SUPPORT = os.getenv("SUPPORT_USERNAME", "").lstrip("@")
TELEGRAM_LINK = os.getenv("TELEGRAM_LINK", "https://t.me/alsvdbdbdhdhdjhfh")
INSTAGRAM_LINK = os.getenv("INSTAGRAM_LINK", "https://www.instagram.com/2a3ka?hvrq=dDZhdjFsajJ1NHV6")
ORDERS_CHANNEL = os.getenv("ORDERS_CHANNEL", "")  # اختياري: يمكن ضبطه من داخل البوت

RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "10000"))
TZ = timezone(timedelta(hours=3))  # توقيت سوريا

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

pool: asyncpg.Pool

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id BIGINT PRIMARY KEY, name TEXT, username TEXT,
  balance DOUBLE PRECISION DEFAULT 0, joined BIGINT);
CREATE TABLE IF NOT EXISTS categories(
  id SERIAL PRIMARY KEY, name TEXT, emoji TEXT, label TEXT,
  parent_id INTEGER, kind TEXT DEFAULT 'text', active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS products(
  id SERIAL PRIMARY KEY, cat_id INTEGER, name TEXT,
  price DOUBLE PRECISION, active INTEGER DEFAULT 1, cur TEXT DEFAULT 'USD');
CREATE TABLE IF NOT EXISTS orders(
  id SERIAL PRIMARY KEY, user_id BIGINT, product_name TEXT,
  price DOUBLE PRECISION, target TEXT, status TEXT DEFAULT 'pending',
  created BIGINT, price_text TEXT);
CREATE TABLE IF NOT EXISTS deposits(
  id SERIAL PRIMARY KEY, user_id BIGINT, amount DOUBLE PRECISION,
  txid TEXT UNIQUE, status TEXT DEFAULT 'pending', created BIGINT,
  cur TEXT DEFAULT 'USD', amount_orig DOUBLE PRECISION, rate DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
ALTER TABLE categories ADD COLUMN IF NOT EXISTS parent_id INTEGER;
ALTER TABLE categories ADD COLUMN IF NOT EXISTS kind TEXT DEFAULT 'text';
ALTER TABLE categories ADD COLUMN IF NOT EXISTS active INTEGER DEFAULT 1;
ALTER TABLE products ADD COLUMN IF NOT EXISTS cur TEXT DEFAULT 'USD';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS price_text TEXT;
ALTER TABLE deposits ADD COLUMN IF NOT EXISTS cur TEXT DEFAULT 'USD';
ALTER TABLE deposits ADD COLUMN IF NOT EXISTS amount_orig DOUBLE PRECISION;
ALTER TABLE deposits ADD COLUMN IF NOT EXISTS rate DOUBLE PRECISION;
"""

# ⚠️ الباقات والأسعار هنا أمثلة فقط، راجعها وعدّلها بأوامر الأدمن قبل البيع الفعلي
CATALOG = [
    {"name": "شحن الألعاب", "emoji": "🎮", "children": [
        {"name": "ببجي موبايل", "emoji": "🔫", "label": "معرّف اللاعب (Player ID)",
         "products": [("60 UC", 0.99), ("325 UC", 4.99), ("660 UC", 9.99), ("1800 UC", 24.99), ("3850 UC", 49.99)]},
        {"name": "فري فاير", "emoji": "🔥", "label": "معرّف اللاعب (Player ID)",
         "products": [("100 جوهرة", 0.99), ("310 جوهرة", 2.99), ("520 جوهرة", 4.99), ("1060 جوهرة", 9.99), ("2180 جوهرة", 19.99)]},
        {"name": "جواكر", "emoji": "🃏", "label": "اسم المستخدم أو ID في جواكر",
         "products": [("10,000 توكن", 2.0), ("30,000 توكن", 5.99), ("100,000 توكن", 18.0)]},
        {"name": "كول أوف ديوتي موبايل", "emoji": "🎖", "label": "معرّف اللاعب (UID)",
         "products": [("80 CP", 0.99), ("400 CP", 4.99), ("800 CP", 9.99), ("2000 CP", 24.99)]},
        {"name": "موبايل ليجندز", "emoji": "⚔️", "label": "معرّف اللاعب (User ID) + السيرفر",
         "products": [("86 جوهرة", 1.5), ("172 جوهرة", 3.0), ("257 جوهرة", 4.5), ("706 جوهرة", 12.0)]},
        {"name": "روبلوكس", "emoji": "🧱", "label": "اسم المستخدم (Username)",
         "products": [("400 Robux", 4.99), ("800 Robux", 9.99), ("1700 Robux", 19.99)]},
        {"name": "فورتنايت", "emoji": "🪂", "label": "اسم حساب Epic",
         "products": [("1000 V-Bucks", 8.99), ("2800 V-Bucks", 22.99), ("5000 V-Bucks", 36.99)]},
        {"name": "كلاش أوف كلانس", "emoji": "🏰", "label": "وسم اللاعب (Player Tag)",
         "products": [("500 جوهرة", 4.99), ("1200 جوهرة", 9.99), ("2500 جوهرة", 19.99)]},
    ]},
    {"name": "شحن نجوم تيليجرام", "emoji": "⭐", "label": "يوزر تيليجرام المستلم (مثال: @username)",
     "products": [("50 نجمة", 1.2), ("100 نجمة", 2.3), ("250 نجمة", 5.5), ("500 نجمة", 11.0), ("1000 نجمة", 21.0)]},
    {"name": "شحن تيليجرام Premium", "emoji": "💎", "label": "يوزر الحساب المراد تفعيل Premium له (@username)",
     "products": [("3 أشهر", 14.0), ("6 أشهر", 19.0), ("12 شهر", 33.0)]},
    {"name": "رصيد الخطوط السورية", "emoji": "📞", "children": [
        {"name": "سيرياتيل", "emoji": "🔴", "label": "رقم الهاتف (مثال: 0933123456)", "kind": "phone", "cur": "SYP",
         "products": [("رصيد 5,000 ل.س", 5200), ("رصيد 10,000 ل.س", 10400), ("رصيد 25,000 ل.س", 26000), ("رصيد 50,000 ل.س", 52000)]},
        {"name": "MTN", "emoji": "🟡", "label": "رقم الهاتف (مثال: 0944123456)", "kind": "phone", "cur": "SYP",
         "products": [("رصيد 5,000 ل.س", 5200), ("رصيد 10,000 ل.س", 10400), ("رصيد 25,000 ل.س", 26000), ("رصيد 50,000 ل.س", 52000)]},
    ]},
]


# =========================
# قاعدة البيانات (Postgres على Neon)
# =========================
def _q(sql: str) -> str:
    n, out = 0, []
    for ch in sql:
        if ch == "?":
            n += 1
            out.append(f"${n}")
        else:
            out.append(ch)
    return "".join(out)


RETRY = (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, ConnectionError, OSError)


async def _retry(fn):
    for i in range(3):
        try:
            return await fn()
        except RETRY:
            if i == 2:
                raise
            await asyncio.sleep(1 + i)


async def fetch(sql, *a, one=False):
    rows = await _retry(lambda: pool.fetch(_q(sql), *a))
    return (rows[0] if rows else None) if one else rows


async def run(sql, *a) -> int:
    st = await _retry(lambda: pool.execute(_q(sql), *a))
    return int(st.split()[-1])


async def insert(sql, *a) -> int:
    return await _retry(lambda: pool.fetchval(_q(sql) + " RETURNING id", *a))


async def get_setting(k):
    r = await fetch("SELECT v FROM settings WHERE k=?", k, one=True)
    return r["v"] if r else None


async def set_setting(k, v):
    await run("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=EXCLUDED.v", k, str(v))


async def get_rate():
    """سعر الدولار بالليرة السورية (يضبطه الأدمن بـ /setrate)."""
    v = await get_setting("syp_rate")
    try:
        r = float(v) if v else float(os.getenv("SYP_RATE", "0") or 0)
    except ValueError:
        r = 0.0
    return r if r > 0 else None


async def create_order(uid, pname, usd_price, ptext, target):
    async with pool.acquire() as conn:
        async with conn.transaction():
            st = await conn.execute(
                "UPDATE users SET balance=ROUND((balance-$1)::numeric,4) "
                "WHERE id=$2 AND balance>=$1-0.00001", usd_price, uid)
            if st.endswith(" 0"):
                return None
            return await conn.fetchval(
                "INSERT INTO orders(user_id,product_name,price,price_text,target,created) "
                "VALUES($1,$2,$3,$4,$5,$6) RETURNING id",
                uid, pname, usd_price, ptext, target, int(time.time()))


async def settle(table, sid, new_status, uid=None, amount=0.0) -> bool:
    async with pool.acquire() as conn:
        async with conn.transaction():
            st = await conn.execute(
                f"UPDATE {table} SET status=$1 WHERE id=$2 AND status='pending'", new_status, sid)
            if st.endswith(" 0"):
                return False
            if uid is not None:
                await conn.execute(
                    "UPDATE users SET balance=ROUND((balance+$1)::numeric,4) WHERE id=$2", amount, uid)
            return True


async def seed_catalog():
    async def add(c, parent):
        cid = await insert(
            "INSERT INTO categories(name,emoji,label,parent_id,kind) VALUES(?,?,?,?,?)",
            c["name"], c["emoji"], c.get("label", "-"), parent, c.get("kind", "text"))
        for pn, pr in c.get("products", []):
            await run("INSERT INTO products(cat_id,name,price,cur) VALUES(?,?,?,?)",
                      cid, pn, float(pr), c.get("cur", "USD"))
        for ch in c.get("children", []):
            await add(ch, cid)
    for c in CATALOG:
        await add(c, None)


async def init_db():
    global pool
    dsn = DATABASE_URL.split("?")[0]
    pool = await asyncpg.create_pool(
        dsn, ssl="require", min_size=1, max_size=5,
        statement_cache_size=0, max_inactive_connection_lifetime=20)
    await pool.execute(SCHEMA)
    # مرة واحدة فقط: استبدال الكتالوج القديم بالتقسيم الجديد
    if not await get_setting("catalog_v2"):
        await pool.execute("DELETE FROM products; DELETE FROM categories;")
        await seed_catalog()
        await set_setting("catalog_v2", "1")


# =========================
# أدوات مساعدة
# =========================
_AR = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def norm(s) -> str:
    return (s or "").translate(_AR).replace("٬", "").replace("٫", ".").replace(" ", "").strip()


def parse_amount(text: str, cur: str):
    t = norm(text)
    t = t.replace(",", "") if cur == "SYP" else t.replace(",", ".")
    return float(t)


def norm_phone(s):
    d = re.sub(r"\D", "", norm(s))
    if d.startswith("00963"):
        d = "0" + d[5:]
    elif d.startswith("963"):
        d = "0" + d[3:]
    elif d.startswith("9") and len(d) == 9:
        d = "0" + d
    return d if re.fullmatch(r"09\d{8}", d) else None


def esc(s) -> str:
    return html.escape(str(s or ""))


def usd(x) -> str:
    return f"{float(x):.2f}$"


def syp(x) -> str:
    return f"{float(x):,.0f} ل.س"


def price_str(price, cur) -> str:
    return syp(price) if cur == "SYP" else usd(price)


def both(usd_amt, rate) -> str:
    s = usd(usd_amt)
    if rate:
        s += f" (≈ {syp(float(usd_amt) * rate)})"
    return s


def to_usd(price, cur, rate):
    if cur == "SYP":
        return round(float(price) / rate, 4) if rate else None
    return round(float(price), 4)


def mask(s) -> str:
    s = str(s or "")
    if len(s) <= 3:
        return s[:1] + "***"
    return s[:2] + "***" + s[-2:]


def B(text, data=None, url=None):
    return InlineKeyboardButton(text, callback_data=data, url=url)


def is_admin(uid) -> bool:
    return uid in ADMINS


async def get_user(u):
    row = await fetch("SELECT * FROM users WHERE id=?", u.id, one=True)
    if row is None:
        await run("INSERT INTO users(id,name,username,joined) VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING",
                  u.id, u.full_name, u.username, int(time.time()))
        row = await fetch("SELECT * FROM users WHERE id=?", u.id, one=True)
    return row


async def show(update: Update, text, markup=None):
    q = update.callback_query
    if q:
        try:
            await q.edit_message_text(text, reply_markup=markup)
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                await q.message.reply_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


async def append_status(q, extra: str):
    m = q.message
    try:
        if m.photo:
            await q.edit_message_caption(caption=(m.caption_html or "") + "\n\n" + extra)
        else:
            await q.edit_message_text((m.text_html or "") + "\n\n" + extra)
    except Exception:
        pass


async def notify_user(bot, uid, text):
    try:
        await bot.send_message(uid, text)
    except Exception as e:
        logger.warning("user notify failed %s: %s", uid, e)


async def notify_admins(bot, text, markup=None, photo=None):
    for a in ADMINS:
        try:
            if photo:
                await bot.send_photo(a, photo, caption=text, reply_markup=markup)
            else:
                await bot.send_message(a, text, reply_markup=markup)
        except Exception as e:
            logger.warning("admin notify failed %s: %s", a, e)


async def send_chunks(message, lines, limit=3800):
    buf = ""
    for ln in lines:
        if len(buf) + len(ln) + 1 > limit:
            await message.reply_text(buf)
            buf = ""
        buf += ln + "\n"
    if buf.strip():
        await message.reply_text(buf)


async def main_menu():
    cats = await fetch("SELECT * FROM categories WHERE parent_id IS NULL AND active=1 ORDER BY id")
    rows = [[B(f"{c['emoji']} {c['name']}", f"cat:{c['id']}")] for c in cats]
    rows.append([B("💰 رصيدي", "wallet"), B("➕ شحن الرصيد", "topup")])
    rows.append([B("📜 طلباتي", "orders")])
    links = []
    if TELEGRAM_LINK:
        links.append(B("📢 القناة", url=TELEGRAM_LINK))
    if INSTAGRAM_LINK:
        links.append(B("📸 إنستغرام", url=INSTAGRAM_LINK))
    if SUPPORT:
        links.append(B("🆘 الدعم", url=f"https://t.me/{SUPPORT}"))
    if links:
        rows.append(links)
    return InlineKeyboardMarkup(rows)


def back_home():
    return InlineKeyboardMarkup([[B("🏠 القائمة الرئيسية", "home")]])


# =========================
# قناة تنفيذ الطلبات
# =========================
async def channel_ref():
    ch = await get_setting("orders_channel") or ORDERS_CHANNEL
    if not ch:
        return None
    ch = ch.strip()
    return int(ch) if re.fullmatch(r"-?\d+", ch) else ch


def duration_text(created) -> str:
    mins = max(0, int((time.time() - float(created or time.time())) // 60))
    if mins < 1:
        return "أقل من دقيقة"
    if mins < 60:
        return f"{mins} دقيقة"
    return f"{mins // 60} ساعة"


async def post_to_channel(bot, o):
    """يرجع None إن لم تُربط قناة، و'' عند النجاح، أو نص الخطأ."""
    ref = await channel_ref()
    if ref is None:
        return None
    now = datetime.now(TZ).strftime("%Y-%m-%d  %H:%M")
    text = (
        "✅ <b>تم تنفيذ طلب جديد</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"🧾 رقم الطلب: <b>#{o['id']}</b>\n"
        f"📦 الخدمة: <b>{esc(o['product_name'])}</b>\n"
        f"🎯 الحساب: <code>{esc(mask(o['target']))}</code>\n"
        f"⏱ مدة التنفيذ: {duration_text(o['created'])}\n"
        f"🕐 {now}\n"
        "━━━━━━━━━━━━━━\n"
        f"⚡ {esc(STORE_NAME)}")
    markup = InlineKeyboardMarkup([[B("🛒 اطلب الآن", url=f"https://t.me/{bot.username}")]])
    try:
        await bot.send_message(ref, text, reply_markup=markup)
        return ""
    except Exception as e:
        logger.warning("channel post failed: %s", e)
        return str(e)[:120]


async def link_channel(bot, ref) -> str:
    try:
        chat = await bot.get_chat(ref)
        me = await bot.get_chat_member(chat.id, bot.id)
    except Exception as e:
        return f"❌ تعذّر الوصول للقناة: {esc(str(e)[:100])}\nتأكد أن البوت أُضيف كمشرف."
    if me.status not in ("administrator", "creator"):
        return "⚠️ البوت ليس مشرفاً في القناة. أضِفه كمشرف مع صلاحية نشر الرسائل ثم أعد المحاولة."
    if getattr(me, "can_post_messages", True) is False:
        return "⚠️ البوت مشرف لكن بدون صلاحية نشر الرسائل. فعّلها له ثم أعد المحاولة."
    await set_setting("orders_channel", str(chat.id))
    return (f"✅ تم ربط القناة <b>{esc(chat.title)}</b>\n"
            "من الآن كل طلب يُنفَّذ سيُنشر فيها تلقائياً.\nجرّب /testchannel لنشر رسالة تجريبية.")


# =========================
# المستخدم
# =========================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    u = update.effective_user
    await run(
        "INSERT INTO users(id,name,username,joined) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name, username=EXCLUDED.username",
        u.id, u.full_name, u.username, int(time.time()))
    row = await get_user(u)
    rate = await get_rate()
    text = (
        f"✨ <b>أهلاً بك في {esc(STORE_NAME)}</b> ✨\n"
        "━━━━━━━━━━━━━━\n"
        "⚡ شحن فوري: ألعاب • نجوم • Premium • رصيد سيرياتيل و MTN\n"
        "💳 الدفع عبر <b>شام كاش</b> (دولار أو ليرة سورية)\n"
        "🛡 خدمة موثوقة ودعم على مدار الساعة\n"
        "━━━━━━━━━━━━━━\n"
        f"💰 رصيدك: <b>{both(row['balance'], rate)}</b>\n\n"
        "اختر القسم المطلوب 👇")
    await show(update, text, await main_menu())


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("تم الإلغاء ✅", reply_markup=await main_menu())


async def wallet(update: Update, ctx):
    u = await get_user(update.effective_user)
    rate = await get_rate()
    extra = f"\n💱 سعر الصرف: 1$ = {syp(rate)}" if rate else ""
    markup = InlineKeyboardMarkup([[B("➕ شحن الرصيد", "topup")], [B("🏠 القائمة الرئيسية", "home")]])
    await show(update, f"💰 <b>محفظتك</b>\n\n🆔 <code>{u['id']}</code>\n"
                       f"💵 الرصيد: <b>{both(u['balance'], rate)}</b>{extra}", markup)


async def my_orders(update: Update, ctx):
    rows = await fetch("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", update.effective_user.id)
    icon = {"pending": "⏳ قيد التنفيذ", "done": "✅ تم", "failed": "❌ مرفوض (أُعيد المبلغ)"}
    if not rows:
        text = "📜 لا توجد طلبات بعد."
    else:
        text = "📜 <b>آخر طلباتك</b>\n\n" + "\n\n".join(
            f"#{o['id']} • {esc(o['product_name'])}\n💵 {esc(o['price_text'] or usd(o['price']))} • "
            f"{icon.get(o['status'], o['status'])}" for o in rows)
    await show(update, text, back_home())


async def open_cat(update: Update, ctx, cid: int):
    cat = await fetch("SELECT * FROM categories WHERE id=? AND active=1", cid, one=True)
    if not cat:
        return await show(update, "القسم غير موجود.", back_home())
    kids = await fetch("SELECT * FROM categories WHERE parent_id=? AND active=1 ORDER BY id", cid)
    prods = await fetch("SELECT * FROM products WHERE cat_id=? AND active=1 ORDER BY id", cid)
    rows, pair = [], []
    for k in kids:
        pair.append(B(f"{k['emoji']} {k['name']}", f"cat:{k['id']}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    for p in prods:
        rows.append([B(f"{p['name']} — {price_str(p['price'], p['cur'])}", f"prod:{p['id']}")])
    back = f"cat:{cat['parent_id']}" if cat["parent_id"] else "home"
    rows.append([B("⬅️ رجوع", back), B("🏠 الرئيسية", "home")])
    hint = "اختر الباقة 👇" if prods else ("اختر من القائمة 👇" if kids else "لا توجد عناصر حالياً.")
    await show(update, f"{cat['emoji']} <b>{esc(cat['name'])}</b>\n\n{hint}", InlineKeyboardMarkup(rows))


async def pick_product(update: Update, ctx, pid: int):
    p = await fetch(
        "SELECT p.id, p.name, p.price, p.cur, c.name AS cname, c.label, c.kind "
        "FROM products p JOIN categories c ON c.id=p.cat_id "
        "WHERE p.id=? AND p.active=1 AND c.active=1", pid, one=True)
    if not p:
        return await show(update, "⚠️ هذه الباقة غير متاحة.", back_home())
    rate = await get_rate()
    need = to_usd(p["price"], p["cur"], rate)
    if need is None:
        return await show(update, "⚠️ هذه الخدمة غير متاحة مؤقتاً (سعر الصرف غير محدد).", back_home())
    u = await get_user(update.effective_user)
    ptext = price_str(p["price"], p["cur"])
    if u["balance"] + 1e-9 < need:
        markup = InlineKeyboardMarkup([[B("➕ شحن الرصيد", "topup")], [B("🏠 القائمة الرئيسية", "home")]])
        return await show(update, f"⚠️ رصيدك ({both(u['balance'], rate)}) لا يكفي.\n"
                                  f"سعر الباقة: <b>{ptext}</b> ({usd(need)})", markup)
    ctx.user_data.clear()
    ctx.user_data.update(state="buy_target", need=need, kind=p["kind"],
                         full=f"{p['cname']} — {p['name']}", ptext=ptext)
    await show(update, f"📝 <b>{esc(p['cname'])} — {esc(p['name'])}</b>\n\n"
                       f"أرسل الآن: <b>{esc(p['label'])}</b>\n\n/cancel للإلغاء")


async def confirm_buy(update: Update, ctx):
    d = ctx.user_data
    if d.get("state") != "buy_confirm":
        return await show(update, "⌛ انتهت الجلسة، ابدأ الطلب من جديد.", back_home())
    full, need, ptext, target = d["full"], d["need"], d["ptext"], d["target"]
    ctx.user_data.clear()  # يمنع الضغط المزدوج
    u = update.effective_user
    oid = await create_order(u.id, full, need, ptext, target)
    if oid is None:
        return await show(update, "⚠️ الرصيد غير كافٍ.", back_home())
    await show(update, f"✅ تم استلام طلبك <b>#{oid}</b>\nسيتم التنفيذ خلال دقائق ⚡", back_home())
    markup = InlineKeyboardMarkup([[B("✅ تم التنفيذ", f"od:{oid}"), B("❌ رفض + استرجاع", f"of:{oid}")]])
    await notify_admins(
        ctx.bot,
        f"🛒 <b>طلب جديد #{oid}</b>\n👤 {esc(u.full_name)} (<code>{u.id}</code>)\n"
        f"📦 {esc(full)}\n🎯 <code>{esc(target)}</code>\n💵 {esc(ptext)} ({usd(need)})", markup)


# ---- شحن الرصيد
async def topup(update: Update, ctx):
    ctx.user_data.clear()
    rate = await get_rate()
    rows = [[B("💵 دولار (USD)", "tc:USD")]]
    if rate:
        rows.append([B("🇸🇾 ليرة سورية (SYP)", "tc:SYP")])
    rows.append([B("🏠 القائمة الرئيسية", "home")])
    await show(update, "💳 <b>شحن الرصيد عبر شام كاش</b>\n\nاختر عملة الدفع 👇", InlineKeyboardMarkup(rows))


async def topup_cur(update: Update, ctx, cur: str):
    rate = await get_rate()
    if cur == "SYP" and not rate:
        return await show(update, "⚠️ الشحن بالليرة غير متاح حالياً، اختر الدولار.", back_home())
    addr = SHAM_ADDRESS_SYP if (cur == "SYP" and SHAM_ADDRESS_SYP) else SHAM_ADDRESS
    ctx.user_data.clear()
    ctx.user_data.update(state="top_amount", cur=cur, rate=rate)
    if cur == "SYP":
        minimum, unit = syp(math.ceil(MIN_TOPUP * rate)), "بالليرة السورية"
        extra = f"💱 سعر الصرف: 1$ = {syp(rate)}\n"
    else:
        minimum, unit, extra = usd(MIN_TOPUP), "بالدولار", ""
    await show(update,
               "💳 <b>شحن الرصيد عبر شام كاش</b>\n━━━━━━━━━━━━━━\n"
               f"👤 الاسم: <b>{esc(SHAM_NAME)}</b>\n"
               f"📮 العنوان: <code>{esc(addr)}</code>\n━━━━━━━━━━━━━━\n"
               f"{extra}"
               f"1️⃣ حوّل المبلغ {unit} إلى الحساب أعلاه\n"
               f"2️⃣ أرسل هنا <b>المبلغ</b> الذي حوّلته\n"
               "3️⃣ ثم <b>رقم العملية</b> وصورة الإشعار\n\n"
               f"الحد الأدنى: {minimum}\n/cancel للإلغاء")


# =========================
# استقبال الرسائل حسب الحالة
# =========================
async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = update.message
    uid = update.effective_user.id
    state = ctx.user_data.get("state")
    text = (m.text or "").strip()

    # الأدمن يحوّل رسالة من القناة → ربط القناة تلقائياً
    fo = getattr(m, "forward_origin", None)
    if is_admin(uid) and fo is not None and getattr(fo, "type", "") == "channel":
        return await m.reply_text(await link_channel(ctx.bot, fo.chat.id))

    if state == "buy_target":
        if not text:
            return await m.reply_text("أرسل المعلومة المطلوبة كنص.")
        d = ctx.user_data
        if d["kind"] == "phone":
            target = norm_phone(text)
            if not target:
                return await m.reply_text("⚠️ أرسل رقماً صحيحاً بصيغة 0933123456")
        else:
            target = text[:200]
        d.update(state="buy_confirm", target=target)
        markup = InlineKeyboardMarkup([[B("✅ تأكيد الشراء", "confirm"), B("❌ إلغاء", "home")]])
        return await m.reply_text(
            "🧾 <b>تأكيد الطلب</b>\n━━━━━━━━━━━━━━\n"
            f"📦 {esc(d['full'])}\n🎯 {esc(target)}\n"
            f"💵 {esc(d['ptext'])} ({usd(d['need'])})\n━━━━━━━━━━━━━━\n"
            "تأكد من صحة المعلومة قبل التأكيد ⚠️",
            reply_markup=markup)

    if state == "top_amount":
        cur, rate = ctx.user_data["cur"], ctx.user_data.get("rate")
        try:
            amt = round(parse_amount(text, cur), 2)
            usd_amt = amt if cur == "USD" else round(amt / rate, 4)
            assert amt > 0 and usd_amt >= MIN_TOPUP
        except Exception:
            minimum = usd(MIN_TOPUP) if cur == "USD" else syp(math.ceil(MIN_TOPUP * (rate or 0)))
            return await m.reply_text(f"أرسل مبلغاً صحيحاً (الحد الأدنى {minimum}).")
        ctx.user_data.update(state="top_txid", amt=amt, usd_amt=usd_amt)
        conv = f"\n💱 يعادل {usd(usd_amt)}" if cur == "SYP" else ""
        return await m.reply_text(f"✅ المبلغ: {price_str(amt, cur)}{conv}\n\n"
                                  "🔢 أرسل الآن <b>رقم العملية</b> من إشعار شام كاش:")

    if state == "top_txid":
        if len(text) < 4:
            return await m.reply_text("رقم العملية غير صالح، أعد الإرسال.")
        if await fetch("SELECT 1 FROM deposits WHERE txid=?", text, one=True):
            return await m.reply_text("⚠️ رقم العملية هذا مستخدم مسبقاً.")
        ctx.user_data.update(state="top_photo", txid=text)
        return await m.reply_text("📸 أرسل <b>صورة إشعار التحويل</b>:")

    if state == "top_photo":
        if not m.photo:
            return await m.reply_text("أرسل صورة الإشعار من فضلك 📸")
        d = dict(ctx.user_data)
        ctx.user_data.clear()
        u = update.effective_user
        await get_user(u)
        try:
            did = await insert(
                "INSERT INTO deposits(user_id,amount,txid,created,cur,amount_orig,rate) VALUES(?,?,?,?,?,?,?)",
                u.id, d["usd_amt"], d["txid"], int(time.time()), d["cur"], d["amt"], d.get("rate"))
        except asyncpg.UniqueViolationError:
            return await m.reply_text("⚠️ رقم العملية مستخدم مسبقاً.", reply_markup=back_home())
        await m.reply_text(f"⏳ تم إرسال طلب الشحن <b>#{did}</b> للمراجعة.\nسيصلك إشعار فور الموافقة.",
                           reply_markup=back_home())
        if d["cur"] == "SYP":
            amt_line = (f"💵 المبلغ: {syp(d['amt'])}\n"
                        f"💱 يعادل: {usd(d['usd_amt'])} (الصرف {syp(d['rate'])})")
        else:
            amt_line = f"💵 المبلغ: {usd(d['usd_amt'])}"
        markup = InlineKeyboardMarkup([[B("✅ قبول", f"dy:{did}"), B("❌ رفض", f"dn:{did}")]])
        return await notify_admins(
            ctx.bot,
            f"💳 <b>طلب شحن #{did}</b>\n👤 {esc(u.full_name)} (<code>{u.id}</code>)\n"
            f"{amt_line}\n🔢 <code>{esc(d['txid'])}</code>",
            markup, photo=m.photo[-1].file_id)

    if m.chat.type == "private":
        await m.reply_text("اختر من القائمة 👇", reply_markup=await main_menu())


# =========================
# الأزرار
# =========================
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    data = q.data or ""
    if data == "home":
        return await start(update, ctx)
    if data == "wallet":
        return await wallet(update, ctx)
    if data == "orders":
        return await my_orders(update, ctx)
    if data == "topup":
        return await topup(update, ctx)
    if data == "confirm":
        return await confirm_buy(update, ctx)
    if data.startswith("tc:"):
        return await topup_cur(update, ctx, data.split(":")[1])
    if data.startswith("cat:"):
        return await open_cat(update, ctx, int(data.split(":")[1]))
    if data.startswith("prod:"):
        return await pick_product(update, ctx, int(data.split(":")[1]))
    if data[:3] in ("od:", "of:", "dy:", "dn:"):
        return await admin_action(update, ctx, data)


async def admin_action(update: Update, ctx, data: str):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        return await q.answer("غير مصرح", show_alert=True)
    kind, sid = data.split(":")
    sid = int(sid)
    bot = ctx.bot

    if kind in ("od", "of"):
        o = await fetch("SELECT * FROM orders WHERE id=?", sid, one=True)
        if kind == "od":
            ok = await settle("orders", sid, "done")
        else:
            ok = await settle("orders", sid, "failed", o["user_id"], o["price"])
        if not ok:
            return await q.answer("تمت معالجته مسبقاً", show_alert=True)
        if kind == "od":
            await notify_user(bot, o["user_id"],
                              f"✅ تم تنفيذ طلبك <b>#{sid}</b> ({esc(o['product_name'])}) بنجاح 🎉")
            err = await post_to_channel(bot, o)
            if err is None:
                note = "\nℹ️ لم تُربط قناة للنشر بعد."
            elif err == "":
                note = "\n📢 نُشر في القناة"
            else:
                note = f"\n⚠️ لم يُنشر في القناة: {esc(err)}"
            await append_status(q, "✅ <b>تم التنفيذ</b>" + note)
        else:
            await notify_user(bot, o["user_id"],
                              f"❌ تعذّر تنفيذ طلبك <b>#{sid}</b> وتم إرجاع {usd(o['price'])} إلى رصيدك.")
            await append_status(q, "❌ <b>مرفوض وتم الاسترجاع</b>")
    else:
        d = await fetch("SELECT * FROM deposits WHERE id=?", sid, one=True)
        if kind == "dy":
            ok = await settle("deposits", sid, "approved", d["user_id"], d["amount"])
        else:
            ok = await settle("deposits", sid, "rejected")
        if not ok:
            return await q.answer("تمت معالجته مسبقاً", show_alert=True)
        if kind == "dy":
            got = usd(d["amount"])
            if d["cur"] == "SYP":
                got += f" (مقابل {syp(d['amount_orig'])})"
            await notify_user(bot, d["user_id"],
                              f"✅ تمت الموافقة على الشحن <b>#{sid}</b>\n💰 أُضيف {got} إلى رصيدك.")
            await append_status(q, "✅ <b>تم القبول</b>")
        else:
            await notify_user(bot, d["user_id"],
                              f"❌ تم رفض طلب الشحن <b>#{sid}</b>. تواصل مع الدعم إن كان هناك خطأ.")
            await append_status(q, "❌ <b>تم الرفض</b>")


# =========================
# أوامر الأدمن
# =========================
def admin_only(fn):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            return
        return await fn(update, ctx)
    return wrapper


def arg_text(update: Update) -> str:
    parts = (update.message.text or "").split(" ", 1)
    return parts[1] if len(parts) > 1 else ""


@admin_only
async def admin_panel(update: Update, ctx):
    users = (await fetch("SELECT COUNT(*) AS c FROM users", one=True))["c"]
    pend_o = (await fetch("SELECT COUNT(*) AS c FROM orders WHERE status='pending'", one=True))["c"]
    pend_d = (await fetch("SELECT COUNT(*) AS c FROM deposits WHERE status='pending'", one=True))["c"]
    sales = (await fetch("SELECT COALESCE(SUM(price),0) AS s FROM orders WHERE status='done'", one=True))["s"]
    rate = await get_rate()
    ch = await channel_ref()
    await update.message.reply_text(
        f"🛠 <b>لوحة الأدمن</b>\n\n👥 المستخدمون: {users}\n⏳ طلبات معلّقة: {pend_o}\n"
        f"💳 شحن معلّق: {pend_d}\n💰 المبيعات: {usd(sales)}\n"
        f"💱 سعر الصرف: {('1$ = ' + syp(rate)) if rate else 'غير محدد ⚠️'}\n"
        f"📢 قناة التنفيذ: {'مربوطة ✅' if ch else 'غير مربوطة'}\n\n"
        "<b>الأوامر:</b>\n"
        "/setrate السعر — سعر الدولار بالليرة\n"
        "/setchannel المعرّف — ربط قناة التنفيذ (أو حوّل رسالة من القناة للبوت)\n"
        "/testchannel — رسالة تجريبية للقناة\n"
        "/catalog — عرض الأقسام والمنتجات\n"
        "/addcat الاسم|الإيموجي|نص الحقل|رقم_القسم_الأب|text أو phone\n"
        "/addprod رقم_القسم|الاسم|السعر|USD أو SYP\n"
        "/setprice رقم_المنتج السعر\n"
        "/delprod رقم_المنتج\n"
        "/delcat رقم_القسم\n"
        "/addbal رقم_المستخدم المبلغ_بالدولار\n"
        "/broadcast النص")


@admin_only
async def setrate(update: Update, ctx):
    if not ctx.args:
        r = await get_rate()
        return await update.message.reply_text(
            f"💱 السعر الحالي: {('1$ = ' + syp(r)) if r else 'غير محدد'}\nلتغييره: /setrate 13000")
    try:
        r = float(norm(ctx.args[0]).replace(",", ""))
        assert r > 0
    except Exception:
        return await update.message.reply_text("الصيغة: /setrate 13000")
    await set_setting("syp_rate", r)
    await update.message.reply_text(f"✅ تم ضبط سعر الصرف: 1$ = {syp(r)}")


@admin_only
async def setchannel(update: Update, ctx):
    arg = (ctx.args[0] if ctx.args else "").strip()
    if not arg:
        return await update.message.reply_text(
            "الصيغة: /setchannel @اسم_القناة أو /setchannel -100123...\n"
            "أو الأسهل: حوّل أي رسالة من القناة إلى هذا البوت.")
    ref = int(arg) if re.fullmatch(r"-?\d+", arg) else arg
    await update.message.reply_text(await link_channel(ctx.bot, ref))


@admin_only
async def testchannel(update: Update, ctx):
    sample = {"id": 0, "product_name": "ببجي موبايل — 60 UC", "target": "5123456789",
              "created": time.time() - 120}
    err = await post_to_channel(ctx.bot, sample)
    if err is None:
        await update.message.reply_text("لم تُربط قناة بعد. حوّل رسالة من القناة للبوت أو استخدم /setchannel.")
    elif err == "":
        await update.message.reply_text("✅ نُشرت رسالة تجريبية في القناة.")
    else:
        await update.message.reply_text(f"❌ فشل النشر: {esc(err)}")


@admin_only
async def catalog(update: Update, ctx):
    out = []

    async def walk(pid, depth):
        cats = await fetch(
            "SELECT * FROM categories WHERE active=1 AND parent_id IS NOT DISTINCT FROM ? ORDER BY id", pid)
        for c in cats:
            pad = "   " * depth
            out.append(f"{pad}{c['emoji']} <b>{esc(c['name'])}</b> [قسم {c['id']}]")
            for p in await fetch("SELECT * FROM products WHERE cat_id=? AND active=1 ORDER BY id", c["id"]):
                out.append(f"{pad}   • [{p['id']}] {esc(p['name'])} — {price_str(p['price'], p['cur'])}")
            await walk(c["id"], depth + 1)

    await walk(None, 0)
    await send_chunks(update.message, out or ["فارغ"])


@admin_only
async def addcat(update: Update, ctx):
    try:
        parts = [x.strip() for x in arg_text(update).split("|")]
        name, emoji, label = parts[0], parts[1], parts[2]
        parent = int(parts[3]) if len(parts) > 3 and parts[3] not in ("", "0") else None
        kind = parts[4] if len(parts) > 4 and parts[4] in ("text", "phone") else "text"
        assert name and emoji and label
    except Exception:
        return await update.message.reply_text(
            "الصيغة: /addcat الاسم|🎮|نص الحقل|رقم_القسم_الأب(اختياري)|text أو phone(اختياري)")
    cid = await insert("INSERT INTO categories(name,emoji,label,parent_id,kind) VALUES(?,?,?,?,?)",
                       name, emoji, label, parent, kind)
    await update.message.reply_text(f"✅ تمت إضافة القسم (رقمه {cid})")


@admin_only
async def addprod(update: Update, ctx):
    try:
        parts = [x.strip() for x in arg_text(update).split("|")]
        cid, name, price = int(parts[0]), parts[1], float(norm(parts[2]).replace(",", ""))
        cur = parts[3].upper() if len(parts) > 3 and parts[3].upper() in ("USD", "SYP") else "USD"
        assert name and price > 0
        await run("INSERT INTO products(cat_id,name,price,cur) VALUES(?,?,?,?)", cid, name, price, cur)
    except Exception:
        return await update.message.reply_text("الصيغة: /addprod رقم_القسم|الاسم|السعر|USD أو SYP")
    await update.message.reply_text("✅ تمت إضافة المنتج")


@admin_only
async def setprice(update: Update, ctx):
    try:
        pid, price = ctx.args
        n = await run("UPDATE products SET price=? WHERE id=?", float(norm(price).replace(",", "")), int(pid))
    except Exception:
        return await update.message.reply_text("الصيغة: /setprice رقم_المنتج السعر")
    await update.message.reply_text("✅ تم تحديث السعر" if n else "⚠️ المنتج غير موجود")


@admin_only
async def delprod(update: Update, ctx):
    try:
        await run("UPDATE products SET active=0 WHERE id=?", int(ctx.args[0]))
    except Exception:
        return await update.message.reply_text("الصيغة: /delprod رقم_المنتج")
    await update.message.reply_text("🗑 تم الحذف")


@admin_only
async def delcat(update: Update, ctx):
    try:
        await run("UPDATE categories SET active=0 WHERE id=?", int(ctx.args[0]))
    except Exception:
        return await update.message.reply_text("الصيغة: /delcat رقم_القسم")
    await update.message.reply_text("🗑 تم إخفاء القسم")


@admin_only
async def addbal(update: Update, ctx):
    try:
        uid, amt = int(ctx.args[0]), float(norm(ctx.args[1]).replace(",", "."))
        n = await run("UPDATE users SET balance=ROUND((balance+?)::numeric,4) WHERE id=?", amt, uid)
    except Exception:
        return await update.message.reply_text("الصيغة: /addbal رقم_المستخدم المبلغ_بالدولار")
    if n == 0:
        return await update.message.reply_text("⚠️ المستخدم غير موجود (يجب أن يكون ضغط /start).")
    await notify_user(ctx.bot, uid, f"💰 تمت إضافة {usd(amt)} إلى رصيدك.")
    await update.message.reply_text("✅ تم")


@admin_only
async def broadcast(update: Update, ctx):
    text = arg_text(update).strip()
    if not text:
        return await update.message.reply_text("الصيغة: /broadcast النص")
    ok = 0
    for u in await fetch("SELECT id FROM users"):
        try:
            await ctx.bot.send_message(u["id"], text, parse_mode=None)
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"📣 أُرسلت إلى {ok} مستخدم")


# =========================
# التشغيل على Render (webhook)
# =========================
def _ping(url: str):
    try:
        urlopen(Request(url, headers={"User-Agent": "keepalive"}), timeout=20).read()
    except Exception:
        pass


async def self_ping():
    if not RENDER_URL:
        return
    while True:
        await asyncio.sleep(600)
        await asyncio.to_thread(_ping, RENDER_URL)


USER_COMMANDS = [("start", "القائمة الرئيسية"), ("cancel", "إلغاء العملية الحالية")]
ADMIN_COMMANDS = USER_COMMANDS + [
    ("admin", "لوحة الإدارة"), ("setrate", "سعر الصرف"), ("setchannel", "ربط قناة التنفيذ"),
    ("testchannel", "تجربة النشر في القناة"), ("catalog", "الأقسام والمنتجات"),
    ("addcat", "إضافة قسم"), ("addprod", "إضافة منتج"), ("setprice", "تعديل سعر"),
    ("delprod", "حذف منتج"), ("delcat", "حذف قسم"), ("addbal", "إضافة رصيد"),
    ("broadcast", "رسالة للجميع"),
]


async def post_init(app: Application):
    await init_db()
    try:
        await app.bot.set_my_commands([BotCommand(c, d) for c, d in USER_COMMANDS])
        await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        for a in ADMINS:
            try:
                await app.bot.set_my_commands([BotCommand(c, d) for c, d in ADMIN_COMMANDS],
                                              scope=BotCommandScopeChat(chat_id=a))
            except Exception:
                pass
    except Exception:
        logger.exception("Could not set bot commands")
    app.bot_data["ping_task"] = asyncio.create_task(self_ping())


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN غير موجود في Environment")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL غير موجود في Environment")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .post_init(post_init)
        .build()
    )

    handlers = {
        "start": start, "cancel": cancel, "admin": admin_panel, "setrate": setrate,
        "setchannel": setchannel, "testchannel": testchannel, "catalog": catalog,
        "addcat": addcat, "addprod": addprod, "setprice": setprice, "delprod": delprod,
        "delcat": delcat, "addbal": addbal, "broadcast": broadcast,
    }
    for name, fn in handlers.items():
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(
        ((filters.TEXT & ~filters.COMMAND) | filters.PHOTO | filters.FORWARDED) & filters.ChatType.PRIVATE,
        on_message))

    if RENDER_URL:
        logger.info("Starting Telegram webhook")
        app.run_webhook(
            listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN,
            webhook_url=f"{RENDER_URL}/{BOT_TOKEN}", drop_pending_updates=False)
    else:
        logger.info("Starting Telegram polling")
        app.run_polling()


if __name__ == "__main__":
    main()

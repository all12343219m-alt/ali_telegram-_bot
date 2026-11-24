import asyncio
import html
import logging
import os
import time
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
SHAM_NAME = os.getenv("SHAMCASH_NAME", "اسم صاحب الحساب")
CUR = os.getenv("CURRENCY", "$")
MIN_TOPUP = float(os.getenv("MIN_TOPUP", "1"))
SUPPORT = os.getenv("SUPPORT_USERNAME", "").lstrip("@")
TELEGRAM_LINK = os.getenv("TELEGRAM_LINK", "https://t.me/alsvdbdbdhdhdjhfh")
INSTAGRAM_LINK = os.getenv("INSTAGRAM_LINK", "https://www.instagram.com/2a3ka?hvrq=dDZhdjFsajJ1NHV6")

RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "10000"))

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

pool: asyncpg.Pool

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id BIGINT PRIMARY KEY, name TEXT, username TEXT,
  balance DOUBLE PRECISION DEFAULT 0, joined BIGINT);
CREATE TABLE IF NOT EXISTS categories(
  id SERIAL PRIMARY KEY, name TEXT, emoji TEXT, label TEXT);
CREATE TABLE IF NOT EXISTS products(
  id SERIAL PRIMARY KEY, cat_id INTEGER, name TEXT,
  price DOUBLE PRECISION, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS orders(
  id SERIAL PRIMARY KEY, user_id BIGINT, product_name TEXT,
  price DOUBLE PRECISION, target TEXT, status TEXT DEFAULT 'pending', created BIGINT);
CREATE TABLE IF NOT EXISTS deposits(
  id SERIAL PRIMARY KEY, user_id BIGINT, amount DOUBLE PRECISION,
  txid TEXT UNIQUE, status TEXT DEFAULT 'pending', created BIGINT);
"""

# بيانات تجريبية: عدّل الأسعار والمنتجات من أوامر الأدمن
SEED = [
    ("شحن الألعاب", "🎮", "معرّف اللاعب (Player ID)", [
        ("ببجي 60 شدة", 0.99), ("ببجي 325 شدة", 4.99),
        ("فري فاير 100 جوهرة", 0.99), ("فري فاير 530 جوهرة", 4.99)]),
    ("نجوم تيليجرام", "⭐", "يوزر تيليجرام المستلم (مثال: @username)", [
        ("50 نجمة", 1.2), ("100 نجمة", 2.3), ("500 نجمة", 11.0)]),
    ("البرامج والاشتراكات", "📱", "الإيميل أو رقم الحساب", [
        ("Netflix شهر", 4.0), ("Spotify شهر", 3.0), ("ChatGPT Plus شهر", 20.0)]),
]


# =========================
# قاعدة البيانات (Postgres على Neon)
# =========================
def _q(sql: str) -> str:
    """يحوّل ? إلى $1,$2,... (صيغة Postgres)"""
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
    # قاعدة Neon المجانية تنام وتستيقظ، فنعيد المحاولة عند انقطاع الاتصال
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


async def create_order(uid, pname, price, target):
    """يخصم الرصيد وينشئ الطلب معاً. يرجع رقم الطلب أو None إن لم يكفِ الرصيد."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            st = await conn.execute(
                "UPDATE users SET balance=ROUND((balance-$1)::numeric,2) "
                "WHERE id=$2 AND balance>=$1", price, uid)
            if st.endswith(" 0"):
                return None
            return await conn.fetchval(
                "INSERT INTO orders(user_id,product_name,price,target,created) "
                "VALUES($1,$2,$3,$4,$5) RETURNING id",
                uid, pname, price, target, int(time.time()))


async def settle(table, sid, new_status, uid=None, amount=0.0) -> bool:
    """يغيّر حالة طلب/شحن معلّق مرة واحدة فقط، ويضيف رصيداً إن لزم."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            st = await conn.execute(
                f"UPDATE {table} SET status=$1 WHERE id=$2 AND status='pending'", new_status, sid)
            if st.endswith(" 0"):
                return False
            if uid is not None:
                await conn.execute(
                    "UPDATE users SET balance=ROUND((balance+$1)::numeric,2) WHERE id=$2", amount, uid)
            return True


async def init_db():
    global pool
    dsn = DATABASE_URL.split("?")[0]
    pool = await asyncpg.create_pool(
        dsn, ssl="require", min_size=1, max_size=5,
        statement_cache_size=0, max_inactive_connection_lifetime=20)
    await pool.execute(SCHEMA)
    if not await fetch("SELECT 1 FROM categories LIMIT 1", one=True):
        for name, emoji, label, prods in SEED:
            cid = await insert("INSERT INTO categories(name,emoji,label) VALUES(?,?,?)", name, emoji, label)
            for pn, pr in prods:
                await run("INSERT INTO products(cat_id,name,price) VALUES(?,?,?)", cid, pn, pr)


# =========================
# أدوات مساعدة
# =========================
def esc(s) -> str:
    return html.escape(str(s or ""))


def money(x) -> str:
    return f"{float(x):.2f}{CUR}"


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


async def main_menu():
    rows = [[B(f"{c['emoji']} {c['name']}", f"cat:{c['id']}")]
            for c in await fetch("SELECT * FROM categories ORDER BY id")]
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
    text = (
        f"✨ <b>أهلاً بك في {esc(STORE_NAME)}</b> ✨\n"
        "━━━━━━━━━━━━━━\n"
        "⚡ شحن فوري للألعاب ونجوم تيليجرام والاشتراكات\n"
        "💳 الدفع عبر <b>شام كاش</b>\n"
        "🛡 خدمة موثوقة ودعم على مدار الساعة\n"
        "━━━━━━━━━━━━━━\n"
        f"💰 رصيدك: <b>{money(row['balance'])}</b>\n\n"
        "اختر القسم المطلوب 👇")
    await show(update, text, await main_menu())


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("تم الإلغاء ✅", reply_markup=await main_menu())


async def wallet(update: Update, ctx):
    u = await get_user(update.effective_user)
    markup = InlineKeyboardMarkup([[B("➕ شحن الرصيد", "topup")], [B("🏠 القائمة الرئيسية", "home")]])
    await show(update, f"💰 <b>محفظتك</b>\n\n🆔 <code>{u['id']}</code>\n"
                       f"💵 الرصيد: <b>{money(u['balance'])}</b>", markup)


async def my_orders(update: Update, ctx):
    rows = await fetch("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", update.effective_user.id)
    icon = {"pending": "⏳ قيد التنفيذ", "done": "✅ تم", "failed": "❌ مرفوض (أُعيد المبلغ)"}
    if not rows:
        text = "📜 لا توجد طلبات بعد."
    else:
        text = "📜 <b>آخر طلباتك</b>\n\n" + "\n\n".join(
            f"#{o['id']} • {esc(o['product_name'])}\n💵 {money(o['price'])} • {icon.get(o['status'], o['status'])}"
            for o in rows)
    await show(update, text, back_home())


async def open_cat(update: Update, ctx, cid: int):
    cat = await fetch("SELECT * FROM categories WHERE id=?", cid, one=True)
    if not cat:
        return await show(update, "القسم غير موجود.", back_home())
    prods = await fetch("SELECT * FROM products WHERE cat_id=? AND active=1 ORDER BY price", cid)
    rows = [[B(f"{p['name']} — {money(p['price'])}", f"prod:{p['id']}")] for p in prods]
    rows.append([B("🏠 القائمة الرئيسية", "home")])
    await show(update, f"{cat['emoji']} <b>{esc(cat['name'])}</b>\n\nاختر الباقة 👇", InlineKeyboardMarkup(rows))


async def pick_product(update: Update, ctx, pid: int):
    p = await fetch("SELECT p.*, c.label FROM products p JOIN categories c ON c.id=p.cat_id "
                    "WHERE p.id=? AND p.active=1", pid, one=True)
    if not p:
        return await show(update, "⚠️ هذه الباقة غير متاحة.", back_home())
    u = await get_user(update.effective_user)
    if u["balance"] < p["price"]:
        markup = InlineKeyboardMarkup([[B("➕ شحن الرصيد", "topup")], [B("🏠 القائمة الرئيسية", "home")]])
        return await show(update, f"⚠️ رصيدك ({money(u['balance'])}) لا يكفي.\n"
                                  f"سعر الباقة: <b>{money(p['price'])}</b>", markup)
    ctx.user_data.clear()
    ctx.user_data.update(state="buy_target", pid=pid)
    await show(update, f"📝 <b>{esc(p['name'])}</b>\n\nأرسل الآن: <b>{esc(p['label'])}</b>\n\n/cancel للإلغاء")


async def confirm_buy(update: Update, ctx):
    d = ctx.user_data
    if d.get("state") != "buy_confirm" or "pid" not in d:
        return await show(update, "⌛ انتهت الجلسة، ابدأ الطلب من جديد.", back_home())
    pid, target = d["pid"], d["target"]
    ctx.user_data.clear()  # يمنع الضغط المزدوج
    p = await fetch("SELECT * FROM products WHERE id=?", pid, one=True)
    u = update.effective_user
    oid = await create_order(u.id, p["name"], p["price"], target)
    if oid is None:
        return await show(update, "⚠️ الرصيد غير كافٍ.", back_home())
    await show(update, f"✅ تم استلام طلبك <b>#{oid}</b>\nسيتم التنفيذ خلال دقائق ⚡", back_home())
    markup = InlineKeyboardMarkup([[B("✅ تم التنفيذ", f"od:{oid}"), B("❌ رفض + استرجاع", f"of:{oid}")]])
    await notify_admins(
        ctx.bot,
        f"🛒 <b>طلب جديد #{oid}</b>\n👤 {esc(u.full_name)} (<code>{u.id}</code>)\n"
        f"📦 {esc(p['name'])}\n🎯 <code>{esc(target)}</code>\n💵 {money(p['price'])}", markup)


async def topup(update: Update, ctx):
    ctx.user_data.clear()
    ctx.user_data["state"] = "top_amount"
    await show(update,
               "💳 <b>شحن الرصيد عبر شام كاش</b>\n━━━━━━━━━━━━━━\n"
               f"👤 الاسم: <b>{esc(SHAM_NAME)}</b>\n"
               f"📮 العنوان: <code>{esc(SHAM_ADDRESS)}</code>\n━━━━━━━━━━━━━━\n"
               "1️⃣ حوّل المبلغ إلى الحساب أعلاه\n2️⃣ أرسل هنا <b>المبلغ</b> الذي حوّلته\n"
               "3️⃣ ثم <b>رقم العملية</b> وصورة الإشعار\n\n"
               f"الحد الأدنى: {money(MIN_TOPUP)}\n/cancel للإلغاء")


# =========================
# استقبال الرسائل حسب الحالة
# =========================
async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = update.message
    state = ctx.user_data.get("state")
    text = (m.text or "").strip()

    if state == "buy_target":
        if not text:
            return await m.reply_text("أرسل المعلومة المطلوبة كنص.")
        p = await fetch("SELECT * FROM products WHERE id=?", ctx.user_data["pid"], one=True)
        ctx.user_data.update(state="buy_confirm", target=text[:200])
        markup = InlineKeyboardMarkup([[B("✅ تأكيد الشراء", "confirm"), B("❌ إلغاء", "home")]])
        return await m.reply_text(
            "🧾 <b>تأكيد الطلب</b>\n━━━━━━━━━━━━━━\n"
            f"📦 {esc(p['name'])}\n🎯 {esc(text[:200])}\n💵 {money(p['price'])}\n━━━━━━━━━━━━━━",
            reply_markup=markup)

    if state == "top_amount":
        try:
            amt = round(float(text.replace(",", ".")), 2)
            assert amt >= MIN_TOPUP
        except Exception:
            return await m.reply_text(f"أرسل مبلغاً صحيحاً (الحد الأدنى {money(MIN_TOPUP)}).")
        ctx.user_data.update(state="top_txid", amount=amt)
        return await m.reply_text("🔢 أرسل الآن <b>رقم العملية</b> من إشعار شام كاش:")

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
            did = await insert("INSERT INTO deposits(user_id,amount,txid,created) VALUES(?,?,?,?)",
                               u.id, d["amount"], d["txid"], int(time.time()))
        except asyncpg.UniqueViolationError:
            return await m.reply_text("⚠️ رقم العملية مستخدم مسبقاً.", reply_markup=back_home())
        await m.reply_text(f"⏳ تم إرسال طلب الشحن <b>#{did}</b> للمراجعة.\nسيصلك إشعار فور الموافقة.",
                           reply_markup=back_home())
        markup = InlineKeyboardMarkup([[B("✅ قبول", f"dy:{did}"), B("❌ رفض", f"dn:{did}")]])
        return await notify_admins(
            ctx.bot,
            f"💳 <b>طلب شحن #{did}</b>\n👤 {esc(u.full_name)} (<code>{u.id}</code>)\n"
            f"💵 {money(d['amount'])}\n🔢 <code>{esc(d['txid'])}</code>",
            markup, photo=m.photo[-1].file_id)

    # لا توجد عملية جارية
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
            await notify_user(bot, o["user_id"], f"✅ تم تنفيذ طلبك <b>#{sid}</b> ({esc(o['product_name'])}) بنجاح 🎉")
            await append_status(q, "✅ <b>تم التنفيذ</b>")
        else:
            await notify_user(bot, o["user_id"], f"❌ تعذّر تنفيذ طلبك <b>#{sid}</b> وتم إرجاع {money(o['price'])} إلى رصيدك.")
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
            await notify_user(bot, d["user_id"], f"✅ تمت الموافقة على الشحن <b>#{sid}</b>\n💰 أُضيف {money(d['amount'])} إلى رصيدك.")
            await append_status(q, "✅ <b>تم القبول</b>")
        else:
            await notify_user(bot, d["user_id"], f"❌ تم رفض طلب الشحن <b>#{sid}</b>. تواصل مع الدعم إن كان هناك خطأ.")
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
    await update.message.reply_text(
        f"🛠 <b>لوحة الأدمن</b>\n\n👥 المستخدمون: {users}\n⏳ طلبات معلّقة: {pend_o}\n"
        f"💳 شحن معلّق: {pend_d}\n💰 المبيعات: {money(sales)}\n\n"
        "<b>الأوامر:</b>\n"
        "/catalog — عرض الأقسام والمنتجات\n"
        "/addcat الاسم|الإيموجي|نص الحقل المطلوب\n"
        "/addprod رقم_القسم|الاسم|السعر\n"
        "/setprice رقم_المنتج السعر\n"
        "/delprod رقم_المنتج\n"
        "/addbal رقم_المستخدم المبلغ\n"
        "/broadcast النص")


@admin_only
async def catalog(update: Update, ctx):
    out = []
    for c in await fetch("SELECT * FROM categories ORDER BY id"):
        out.append(f"{c['emoji']} <b>{esc(c['name'])}</b> (قسم {c['id']})")
        for p in await fetch("SELECT * FROM products WHERE cat_id=? AND active=1 ORDER BY id", c["id"]):
            out.append(f"   • [{p['id']}] {esc(p['name'])} — {money(p['price'])}")
    await update.message.reply_text("\n".join(out) or "فارغ")


@admin_only
async def addcat(update: Update, ctx):
    try:
        name, emoji, label = [x.strip() for x in arg_text(update).split("|")]
        assert name and emoji and label
    except Exception:
        return await update.message.reply_text("الصيغة: /addcat الاسم|🎮|نص الحقل المطلوب")
    await run("INSERT INTO categories(name,emoji,label) VALUES(?,?,?)", name, emoji, label)
    await update.message.reply_text("✅ تمت إضافة القسم")


@admin_only
async def addprod(update: Update, ctx):
    try:
        cid, name, price = [x.strip() for x in arg_text(update).split("|")]
        await run("INSERT INTO products(cat_id,name,price) VALUES(?,?,?)", int(cid), name, float(price))
    except Exception:
        return await update.message.reply_text("الصيغة: /addprod رقم_القسم|الاسم|السعر")
    await update.message.reply_text("✅ تمت إضافة المنتج")


@admin_only
async def setprice(update: Update, ctx):
    try:
        pid, price = ctx.args
        await run("UPDATE products SET price=? WHERE id=?", float(price), int(pid))
    except Exception:
        return await update.message.reply_text("الصيغة: /setprice رقم_المنتج السعر")
    await update.message.reply_text("✅ تم تحديث السعر")


@admin_only
async def delprod(update: Update, ctx):
    try:
        await run("UPDATE products SET active=0 WHERE id=?", int(ctx.args[0]))
    except Exception:
        return await update.message.reply_text("الصيغة: /delprod رقم_المنتج")
    await update.message.reply_text("🗑 تم الحذف")


@admin_only
async def addbal(update: Update, ctx):
    try:
        uid, amt = int(ctx.args[0]), float(ctx.args[1])
        n = await run("UPDATE users SET balance=ROUND((balance+?)::numeric,2) WHERE id=?", amt, uid)
    except Exception:
        return await update.message.reply_text("الصيغة: /addbal رقم_المستخدم المبلغ")
    if n == 0:
        return await update.message.reply_text("⚠️ المستخدم غير موجود (يجب أن يكون ضغط /start).")
    await notify_user(ctx.bot, uid, f"💰 تمت إضافة {money(amt)} إلى رصيدك.")
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
        pass  # حتى لو رجع 404 فالطلب وصل وأبقى الخدمة مستيقظة


async def self_ping():
    if not RENDER_URL:
        return
    while True:
        await asyncio.sleep(600)
        await asyncio.to_thread(_ping, RENDER_URL)


USER_COMMANDS = [("start", "القائمة الرئيسية"), ("cancel", "إلغاء العملية الحالية")]
ADMIN_COMMANDS = USER_COMMANDS + [
    ("admin", "لوحة الإدارة"), ("catalog", "الأقسام والمنتجات"),
    ("addcat", "إضافة قسم"), ("addprod", "إضافة منتج"), ("setprice", "تعديل سعر"),
    ("delprod", "حذف منتج"), ("addbal", "إضافة رصيد"), ("broadcast", "رسالة للجميع"),
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
        "start": start, "cancel": cancel, "admin": admin_panel, "catalog": catalog,
        "addcat": addcat, "addprod": addprod, "setprice": setprice, "delprod": delprod,
        "addbal": addbal, "broadcast": broadcast,
    }
    for name, fn in handlers.items():
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(
        ((filters.TEXT & ~filters.COMMAND) | filters.PHOTO) & filters.ChatType.PRIVATE, on_message))

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

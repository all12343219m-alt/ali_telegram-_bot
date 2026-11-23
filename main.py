import os
import json
import base64
import logging
import sqlite3
import asyncio
import io
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from openai import AsyncOpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)

# =========================
# إعدادات البوت
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")

# Cloudflare Workers AI (توليد الصور)
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")

RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "bot_data.db"

TELEGRAM_LINK = "https://t.me/alsvdbdbdhdhdjhfh"
INSTAGRAM_LINK = "https://www.instagram.com/2a3ka?hvrq=dDZhdjFsajJ1NHV6"
WEBSITE_LINK = "https://astounding-seahorse-021ea5.netlify.app"

DEVELOPER_INFO = (
    "👨‍💻 معلومات المطوّر\n\n"
    "شاب سوري شغوف بالبرمجة ويسعى لإتقانها.\n\n"
    "صنع هذا البوت بكل شغف، ويطمح دائمًا لتطوير أفكار جديدة ومميزة."
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# =========================
# قاعدة البيانات
# =========================
def get_db():
    return sqlite3.connect(DB_FILE)

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                message TEXT,
                created_at TEXT
            )
        """)

def save_user(user):
    if not user:
        return
    with get_db() as db:
        db.execute("""
            INSERT OR REPLACE INTO users (user_id, username, first_name, joined_at)
            VALUES (?, ?, ?, COALESCE((SELECT joined_at FROM users WHERE user_id = ?), ?))
        """, (
            user.id, user.username or "", user.first_name or "",
            user.id, datetime.now().isoformat(),
        ))

def save_suggestion(user, message):
    with get_db() as db:
        db.execute("""
            INSERT INTO suggestions (user_id, username, message, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            user.id, user.username or "", message,
            datetime.now().isoformat(),
        ))

def get_all_users():
    with get_db() as db:
        rows = db.execute("SELECT user_id FROM users").fetchall()
    return [row[0] for row in rows]

def get_user_count():
    with get_db() as db:
        return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

def get_suggestion_count():
    with get_db() as db:
        return db.execute("SELECT COUNT(*) FROM suggestions").fetchone()[0]

# =========================
# الذكاء الاصطناعي - OpenRouter
# =========================
ai_client = None
if OPENROUTER_API_KEY:
    ai_client = AsyncOpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": WEBSITE_LINK,
            "X-Title": "Ali Telegram Bot",
        },
    )

chat_history = {}
MAX_HISTORY = 12

async def ask_ai(user_id, question):
    if not ai_client:
        return "❌ مفتاح OpenRouter غير موجود. أضف OPENROUTER_API_KEY في Render."
    history = chat_history.get(user_id, [])
    messages = [{
        "role": "system",
        "content": (
            "أنت مساعد ذكي وودود داخل بوت تيليغرام. "
            "أجب باللغة التي يستخدمها المستخدم، وكن واضحًا ومفيدًا ودقيقًا."
        ),
    }]
    messages.extend(history)
    messages.append({"role": "user", "content": question})

    try:
        response = await ai_client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=1500,
        )
        answer = response.choices[0].message.content
        if not answer:
            return "لم يصلني رد من النموذج. حاول مرة أخرى."
        history.extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ])
        chat_history[user_id] = history[-MAX_HISTORY:]
        return answer
    except Exception as error:
        logger.exception("OpenRouter error")
        error_text = str(error).lower()
        if "429" in error_text:
            return "⚠️ وصلت إلى حد الاستخدام المجاني مؤقتًا. انتظر قليلًا ثم حاول مجددًا."
        if "401" in error_text or "403" in error_text:
            return "❌ مشكلة في مفتاح OpenRouter أو صلاحياته. تحقق من المفتاح في Render."
        if "404" in error_text:
            return "❌ النموذج غير متاح حاليًا. تحقق من OPENROUTER_MODEL في Render."
        return "❌ حدث خطأ أثناء الاتصال بالذكاء الاصطناعي. حاول مرة أخرى بعد قليل."

# =========================
# توليد الصور - Cloudflare Workers AI
# =========================
def download_generated_image(prompt: str) -> bytes:
    """يولّد الصورة عبر Cloudflare Workers AI (FLUX.1-schnell)."""
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}"
        "/ai/run/@cf/black-forest-labs/flux-1-schnell"
    )
    request = Request(
        url,
        data=json.dumps({"prompt": prompt, "steps": 4}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {CF_API_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "AliTelegramBot/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode("utf-8"))
    image_b64 = (result.get("result") or {}).get("image")
    if not image_b64:
        raise RuntimeError("لم تُرجع الخدمة صورة.")
    return base64.b64decode(image_b64)

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text(
            "🎨 اكتب وصف الصورة بعد الأمر:\n\n"
            "/image قطة بيضاء على سطح القمر بأسلوب سينمائي"
        )
        return

    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        await update.message.reply_text(
            "❌ إعدادات توليد الصور غير مضبوطة.\n"
            "أضف CF_ACCOUNT_ID و CF_API_TOKEN في Render Environment."
        )
        return

    if len(prompt) > 1000:
        await update.message.reply_text("⚠️ الوصف طويل جدًا. اختصره إلى أقل من 1000 حرف.")
        return

    status = await update.message.reply_text(
        "🎨 بدأت بتوليد الصورة...\n"
        "قد يستغرق الأمر بعض الوقت، انتظر من فضلك."
    )

    try:
        image_bytes = await asyncio.to_thread(download_generated_image, prompt)
        photo = io.BytesIO(image_bytes)
        photo.name = "generated_image.jpg"
        await update.message.reply_photo(
            photo=photo,
            caption=f"✨ تم توليد الصورة\n\n📝 {prompt[:900]}",
        )
        await status.delete()

    except HTTPError as error:
        logger.warning("Cloudflare HTTP error: %s", error.code)
        if error.code in (401, 403):
            message = "🔑 التوكن أو Account ID غير صحيح. تحقق منهما في Render."
        elif error.code == 429:
            message = "⏳ نفدت الحصة اليومية أو الطلبات كثيرة. انتظر ثم جرّب."
        else:
            message = f"❌ خدمة الصور أعادت خطأ HTTP {error.code}. حاول لاحقًا."
        await status.edit_text(message)

    except (URLError, TimeoutError) as error:
        logger.warning("Cloudflare connection/timeout: %s", error)
        await status.edit_text("🌐 تعذّر الاتصال بخدمة الصور أو انتهت مهلة الطلب. حاول مجددًا.")

    except Exception:
        logger.exception("Image generation failed")
        await status.edit_text(
            "❌ لم أتمكن من توليد الصورة هذه المرة.\n"
            "تحقق من إعدادات CF_ACCOUNT_ID و CF_API_TOKEN."
        )

# =========================
# الأزرار الرئيسية
# =========================
def main_keyboard():
    keyboard = [
        [InlineKeyboardButton("🤖 الذكاء الاصطناعي", callback_data="ai_help")],
        [InlineKeyboardButton("🎨 توليد صورة", callback_data="image_help")],
        [
            InlineKeyboardButton("📢 قناة المطوّر", url=TELEGRAM_LINK),
            InlineKeyboardButton("📸 إنستغرام", url=INSTAGRAM_LINK),
        ],
        [InlineKeyboardButton("🌐 موقعي", url=WEBSITE_LINK)],
        [InlineKeyboardButton("👨‍💻 معلومات المطوّر", callback_data="developer")],
        [InlineKeyboardButton("📋 أوامر البوت", callback_data="commands")],
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats")],
        [InlineKeyboardButton("📣 طريقة الإذاعة", callback_data="admin_broadcast")],
    ])

# =========================
# الأوامر
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    text = (
        f"أهلًا {user.first_name} 👋\n\n"
        "أنا بوت المطوّر علي، جاهز لمساعدتك!\n\n"
        "🤖 للذكاء الاصطناعي اكتب:\n/ask ثم سؤالك\n\n"
        "🎨 لتوليد الصور اكتب:\n/image ثم وصف الصورة\n\nاختر ما تريد من الأزرار:"
    )
    await update.message.reply_text(text, reply_markup=main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 أوامر البوت:\n\n"
        "/start - بدء البوت\n/help - عرض المساعدة\n/info - معلومات البوت\n"
        "/ask سؤالك - سؤال الذكاء الاصطناعي\n/reset - مسح ذاكرة المحادثة\n"
        "/image وصف الصورة - توليد صورة بالذكاء الاصطناعي\n"
        "/suggest رسالتك - إرسال اقتراح أو شكوى\n\n"
        "أوامر الإدارة:\n/admin - لوحة الإدارة\n/stats - إحصائيات البوت\n/broadcast رسالتك - إرسال رسالة للجميع"
    )
    await update.message.reply_text(text)

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(DEVELOPER_INFO, reply_markup=main_keyboard())

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text("اكتب سؤالك هكذا:\n/ask كيف أتعلم البرمجة؟")
        return
    message = await update.message.reply_text("🤖 جاري التفكير...")
    answer = await ask_ai(user.id, question)
    for i in range(0, len(answer), 4000):
        part = answer[i:i + 4000]
        if i == 0:
            await message.edit_text(part)
        else:
            await update.message.reply_text(part)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_history.pop(update.effective_user.id, None)
    await update.message.reply_text("🧹 تم مسح ذاكرة المحادثة. ابدأ من جديد!")

async def suggest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    message = " ".join(context.args).strip()
    if not message:
        await update.message.reply_text("أرسل اقتراحك هكذا:\n/suggest أريد إضافة ميزة جديدة")
        return
    save_suggestion(user, message)
    await update.message.reply_text("✅ وصل اقتراحك بنجاح، شكرًا لك!")
    if ADMIN_ID:
        try:
            await context.bot.send_message(
                ADMIN_ID,
                "📩 اقتراح جديد\n\n"
                f"المستخدم: {user.first_name}\nID: {user.id}\n"
                f"Username: @{user.username or 'لا يوجد'}\n\n{message}",
            )
        except Exception:
            logger.exception("Could not notify admin")

# =========================
# الإدارة
# =========================
def is_admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر للمطوّر فقط.")
        return
    await update.message.reply_text("👑 لوحة إدارة البوت", reply_markup=admin_keyboard())

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر للمطوّر فقط.")
        return
    await update.message.reply_text(
        "📊 إحصائيات البوت\n\n"
        f"👥 عدد المستخدمين: {get_user_count()}\n"
        f"📩 عدد الاقتراحات: {get_suggestion_count()}"
    )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر للمطوّر فقط.")
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("استخدم الأمر هكذا:\n/broadcast مرحبًا بالجميع")
        return
    users = get_all_users()
    sent = failed = 0
    status = await update.message.reply_text("📣 بدأ الإرسال...")
    for user_id in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await status.edit_text(
        f"✅ انتهى الإرسال\n\nتم الإرسال: {sent}\nفشل الإرسال: {failed}"
    )

# =========================
# الأزرار
# =========================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "developer":
        await query.message.reply_text(DEVELOPER_INFO)
    elif query.data == "commands":
        await query.message.reply_text(
            "📋 الأوامر:\n\n/start\n/help\n/info\n/ask سؤالك\n/reset\n"
            "/image وصف الصورة\n/suggest رسالتك"
        )
    elif query.data == "ai_help":
        await query.message.reply_text("🤖 اسألني أي شيء!\nاكتب:\n/ask سؤالك هنا")
    elif query.data == "image_help":
        await query.message.reply_text(
            "🎨 أرسل وصف الصورة التي تريدها بهذا الشكل:\n\n"
            "/image مدينة مستقبلية تحت المطر بأسلوب سينمائي"
        )
    elif query.data == "admin_stats":
        if not is_admin(query.from_user.id):
            await query.message.reply_text("⛔ للمطوّر فقط.")
            return
        await query.message.reply_text(
            f"👥 المستخدمون: {get_user_count()}\n"
            f"📩 الاقتراحات: {get_suggestion_count()}"
        )
    elif query.data == "admin_broadcast":
        if not is_admin(query.from_user.id):
            await query.message.reply_text("⛔ للمطوّر فقط.")
            return
        await query.message.reply_text("📣 أرسل الإذاعة هكذا:\n/broadcast رسالتك")

# =========================
# تسجيل المستخدمين
# =========================
async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        save_user(update.effective_user)

# =========================
# تشغيل البوت على Render
# =========================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN غير موجود في Environment")
    init_db()
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("ask", ask_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("suggest", suggest_command))
    application.add_handler(CommandHandler("image", image_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))

    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.ALL, track_user), group=1)

    if RENDER_URL:
        webhook_url = f"{RENDER_URL}/{BOT_TOKEN}"
        logger.info("Starting Telegram webhook")
        application.run_webhook(
            listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN,
            webhook_url=webhook_url, drop_pending_updates=False,
        )
    else:
        logger.info("Starting Telegram polling")
        application.run_polling()

if __name__ == "__main__":
    main()

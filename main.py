
import os
import logging
import sqlite3
import asyncio
from datetime import datetime

from openai import AsyncOpenAI
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# إعدادات البوت
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "openrouter/free"
)

RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "10000"))

DB_FILE = "bot_data.db"

TELEGRAM_LINK = "https://t.me/alsvdbdbdhdhdjhfh"
INSTAGRAM_LINK = "https://www.instagram.com/2a3ka?hvrq=dDZhdjFsajJ1NHV6"
WEBSITE_LINK = "https://astounding-seahorse-021ea5.netlify.app"

DEVELOPER_INFO = (
    "👨‍💻 معلومات المطوّر\n\n"
    "شاب سوري شغوف بالبرمجة ويسعى لإتقانها.\n\n"
    "صنع هذا البوت بكل شغف، "
    "ويطمح دائمًا لتطوير أفكار جديدة ومميزة."
)

# =========================
# التسجيل والسجلات
# =========================

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
            INSERT OR REPLACE INTO users
            (user_id, username, first_name, joined_at)
            VALUES (
                ?,
                ?,
                ?,
                COALESCE(
                    (SELECT joined_at FROM users WHERE user_id = ?),
                    ?
                )
            )
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            user.id,
            datetime.now().isoformat(),
        ))

def save_suggestion(user, message):
    with get_db() as db:
        db.execute("""
            INSERT INTO suggestions
            (user_id, username, message, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            message,
            datetime.now().isoformat(),
        ))

def get_all_users():
    with get_db() as db:
        rows = db.execute(
            "SELECT user_id FROM users"
        ).fetchall()

    return [row[0] for row in rows]

def get_user_count():
    with get_db() as db:
        result = db.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()

    return result[0]

def get_suggestion_count():
    with get_db() as db:
        result = db.execute(
            "SELECT COUNT(*) FROM suggestions"
        ).fetchone()

    return result[0]

# =========================
# الذكاء الاصطناعي
# OpenRouter
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

# ذاكرة محادثة مؤقتة لكل مستخدم
chat_history = {}

MAX_HISTORY = 12

async def ask_ai(user_id, question):
    if not ai_client:
        return (
            "❌ مفتاح OpenRouter غير موجود.\n"
            "أضف OPENROUTER_API_KEY في Render Environment."
        )

    history = chat_history.get(user_id, [])

    messages = [
        {
            "role": "system",
            "content": (
                "أنت مساعد ذكي وودود داخل بوت تيليغرام. "
                "أجب باللغة التي يستخدمها المستخدم. "
                "كن واضحًا ومفيدًا، وقدم إجابات دقيقة."
            ),
        }
    ]

    messages.extend(history)
    messages.append({
        "role": "user",
        "content": question,
    })

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

        history.append({
            "role": "user",
            "content": question,
        })

        history.append({
            "role": "assistant",
            "content": answer,
        })

        chat_history[user_id] = history[-MAX_HISTORY:]

        return answer

    except Exception as error:
        logger.exception("OpenRouter error")

        error_text = str(error).lower()

        if "429" in error_text:
            return (
                "⚠️ وصلت إلى حد الاستخدام المجاني مؤقتًا.\n"
                "انتظر قليلًا ثم حاول مجددًا."
            )

        if "401" in error_text or "403" in error_text:
            return (
                "❌ مشكلة في مفتاح OpenRouter أو صلاحياته.\n"
                "تحقق من المفتاح في Render."
            )

        if "404" in error_text:
            return (
                "❌ النموذج غير متاح حاليًا.\n"
                "تحقق من OPENROUTER_MODEL في Render."
            )

        return (
            "❌ حدث خطأ أثناء الاتصال بالذكاء الاصطناعي.\n"
            "حاول مرة أخرى بعد قليل."
        )

# =========================
# الأزرار الرئيسية
# =========================

def main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "🤖 الذكاء الاصطناعي",
                callback_data="ai_help"
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 قناة المطوّر",
                url=TELEGRAM_LINK
            ),
            InlineKeyboardButton(
                "📸 إنستغرام",
                url=INSTAGRAM_LINK
            ),
        ],
        [
            InlineKeyboardButton(
                "🌐 موقعي",
                url=WEBSITE_LINK
            ),
        ],
        [
            InlineKeyboardButton(
                "👨‍💻 معلومات المطوّر",
                callback_data="developer"
            ),
        ],
        [
            InlineKeyboardButton(
                "📋 أوامر البوت",
                callback_data="commands"
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)

def admin_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "📊 إحصائيات",
                callback_data="admin_stats"
            ),
        ],
        [
            InlineKeyboardButton(
                "📣 طريقة الإذاعة",
                callback_data="admin_broadcast"
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)

# =========================
# الأوامر
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    text = (
        f"أهلًا {user.first_name} 👋\n\n"
        "أنا بوت المطوّر علي، جاهز لمساعدتك!\n\n"
        "🤖 يمكنك استخدام الذكاء الاصطناعي عبر:\n"
        "/ask ثم اكتب سؤالك\n\n"
        "اختر ما تريد من الأزرار:"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 أوامر البوت:\n\n"
        "/start - بدء البوت\n"
        "/help - عرض المساعدة\n"
        "/info - معلومات البوت\n"
        "/ask سؤالك - سؤال الذكاء الاصطناعي\n"
        "/reset - مسح ذاكرة المحادثة\n"
        "/suggest رسالتك - إرسال اقتراح أو شكوى\n\n"
        "أوامر الإدارة:\n"
        "/admin - لوحة الإدارة\n"
        "/stats - إحصائيات البوت\n"
        "/broadcast رسالتك - إرسال رسالة للجميع"
    )

    await update.message.reply_text(text)

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        DEVELOPER_INFO,
        reply_markup=main_keyboard()
    )

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    question = " ".join(context.args).strip()

    if not question:
        await update.message.reply_text(
            "اكتب سؤالك بهذا الشكل:\n"
            "/ask كيف أتعلم البرمجة؟"
        )
        return

    message = await update.message.reply_text(
        "🤖 جاري التفكير..."
    )

    answer = await ask_ai(user.id, question)

    # تيليغرام يسمح برسائل طويلة، نقسمها عند الحاجة
    for i in range(0, len(answer), 4000):
        part = answer[i:i + 4000]

        if i == 0:
            await message.edit_text(part)
        else:
            await update.message.reply_text(part)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    chat_history.pop(user_id, None)

    await update.message.reply_text(
        "🧹 تم مسح ذاكرة المحادثة. ابدأ من جديد!"
    )

async def suggest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    message = " ".join(context.args).strip()

    if not message:
        await update.message.reply_text(
            "أرسل اقتراحك بهذا الشكل:\n"
            "/suggest أريد إضافة ميزة جديدة"
        )
        return

    save_suggestion(user, message)

    await update.message.reply_text(
        "✅ وصل اقتراحك بنجاح، شكرًا لك!"
    )

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                ADMIN_ID,
                "📩 اقتراح جديد\n\n"
                f"المستخدم: {user.first_name}\n"
                f"ID: {user.id}\n"
                f"Username: @{user.username or 'لا يوجد'}\n\n"
                f"{message}"
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

    await update.message.reply_text(
        "👑 لوحة إدارة البوت",
        reply_markup=admin_keyboard()
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر للمطوّر فقط.")
        return

    users = get_user_count()
    suggestions = get_suggestion_count()

    await update.message.reply_text(
        "📊 إحصائيات البوت\n\n"
        f"👥 عدد المستخدمين: {users}\n"
        f"📩 عدد الاقتراحات: {suggestions}"
    )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر للمطوّر فقط.")
        return

    text = " ".join(context.args).strip()

    if not text:
        await update.message.reply_text(
            "استخدم الأمر هكذا:\n"
            "/broadcast مرحبًا بالجميع"
        )
        return

    users = get_all_users()
    sent = 0
    failed = 0

    status = await update.message.reply_text(
        "📣 بدأ الإرسال..."
    )

    for user_id in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=text
            )
            sent += 1

        except Exception:
            failed += 1

        await asyncio.sleep(0.05)

    await status.edit_text(
        "✅ انتهى الإرسال\n\n"
        f"تم الإرسال: {sent}\n"
        f"فشل الإرسال: {failed}"
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
            "📋 الأوامر:\n\n"
            "/start\n"
            "/help\n"
            "/info\n"
            "/ask سؤالك\n"
            "/reset\n"
            "/suggest رسالتك"
        )

    elif query.data == "ai_help":
        await query.message.reply_text(
            "🤖 اسألني أي شيء!\n\n"
            "اكتب:\n"
            "/ask سؤالك هنا"
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

        await query.message.reply_text(
            "📣 أرسل الإذاعة بهذا الشكل:\n"
            "/broadcast رسالتك"
        )

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
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("ask", ask_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("suggest", suggest_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    application.add_handler(
        MessageHandler(filters.ALL, track_user),
        group=1
    )

    if RENDER_URL:
        webhook_url = f"{RENDER_URL}/{BOT_TOKEN}"

        logger.info("Starting Telegram webhook")

        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=webhook_url,
            drop_pending_updates=False,
        )

    else:
        logger.info("Starting Telegram polling")
        application.run_polling()

if __name__ == "__main__":
    main()

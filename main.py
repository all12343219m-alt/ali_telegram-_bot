
import os
import json
import sqlite3
import logging
from datetime import datetime, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from google import genai
from google.genai import types


# =========================
# الإعدادات
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-pro"
).strip()

ADMIN_ID = os.getenv("ADMIN_ID", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_data.db")

TELEGRAM_LINK = "https://t.me/alsvdbdbdhdhdjhfh"
INSTAGRAM_LINK = "https://www.instagram.com/2a3ka?hvrq=dDZhdjFsajJ1NHV6"
WEBSITE_LINK = "https://astounding-seahorse-021ea5.netlify.app/"

DEVELOPER_BIO = "شاب سوري شغوف بالبرمجة ويسعى لإتقانها"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# قاعدة البيانات
# =========================

def get_db():
    return sqlite3.connect(DATABASE_PATH)


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
                suggestion TEXT,
                created_at TEXT
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                user_id INTEGER PRIMARY KEY,
                history TEXT
            )
        """)


def save_user(user):
    if not user:
        return

    with get_db() as db:
        db.execute("""
            INSERT INTO users
            (user_id, username, first_name, joined_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            datetime.now(timezone.utc).isoformat(),
        ))


def save_suggestion(user_id, suggestion):
    with get_db() as db:
        db.execute("""
            INSERT INTO suggestions
            (user_id, suggestion, created_at)
            VALUES (?, ?, ?)
        """, (
            user_id,
            suggestion,
            datetime.now(timezone.utc).isoformat(),
        ))


def get_history(user_id):
    with get_db() as db:
        row = db.execute(
            "SELECT history FROM chat_history WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if not row:
        return []

    try:
        return json.loads(row[0])
    except Exception:
        return []


def save_history(user_id, history):
    history = history[-12:]

    with get_db() as db:
        db.execute("""
            INSERT INTO chat_history (user_id, history)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                history = excluded.history
        """, (
            user_id,
            json.dumps(history, ensure_ascii=False),
        ))


def clear_history(user_id):
    with get_db() as db:
        db.execute(
            "DELETE FROM chat_history WHERE user_id = ?",
            (user_id,),
        )


# =========================
# القائمة الرئيسية
# =========================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "🧠 تحدث مع Gemini",
                callback_data="ask",
            )
        ],
        [
            InlineKeyboardButton(
                "👨‍💻 المطور",
                callback_data="developer",
            ),
            InlineKeyboardButton(
                "ℹ️ معلومات البوت",
                callback_data="info",
            ),
        ],
        [
            InlineKeyboardButton(
                "💡 اقتراح",
                callback_data="suggest",
            ),
        ],
        [
            InlineKeyboardButton(
                "📱 تيليغرام",
                url=TELEGRAM_LINK,
            ),
            InlineKeyboardButton(
                "📸 إنستغرام",
                url=INSTAGRAM_LINK,
            ),
        ],
        [
            InlineKeyboardButton(
                "🌐 الموقع",
                url=WEBSITE_LINK,
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================
# البداية والمساعدة
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    name = user.first_name or "صديقي"

    await update.effective_message.reply_text(
        f"أهلًا بك يا {name} 👋\n\n"
        "أنا مساعدك الذكي المدعوم من Google Gemini.\n\n"
        "💻 أساعدك في البرمجة والتقنية.\n"
        "📚 أجيب عن الأسئلة العامة.\n"
        "🧠 أتذكر سياق محادثتنا.\n"
        "💡 أستقبل اقتراحاتك.\n\n"
        "اختر من القائمة:",
        reply_markup=main_menu(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "📖 أوامر البوت:\n\n"
        "/start - تشغيل البوت\n"
        "/help - المساعدة\n"
        "/info - معلومات البوت\n"
        "/ask سؤالك - سؤال Gemini\n"
        "/reset - مسح ذاكرة المحادثة\n"
        "/suggest اقتراحك - إرسال اقتراح\n"
        "/admin - لوحة الإدارة\n"
        "/stats - الإحصائيات\n\n"
        "يمكنك أيضًا إرسال سؤالك مباشرة."
    )


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🤖 معلومات البوت\n\n"
        "محرك الذكاء: Google Gemini\n"
        f"النموذج: {GEMINI_MODEL}\n"
        "الاستضافة: Render\n"
        "اللغة: العربية"
    )


async def developer_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    keyboard = [
        [InlineKeyboardButton("📱 تيليغرام", url=TELEGRAM_LINK)],
        [InlineKeyboardButton("📸 إنستغرام", url=INSTAGRAM_LINK)],
        [InlineKeyboardButton("🌐 الموقع", url=WEBSITE_LINK)],
    ]

    await update.effective_message.reply_text(
        f"👨‍💻 {DEVELOPER_BIO}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================
# الاقتراحات
# =========================

async def suggest_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    save_user(user)

    suggestion = " ".join(context.args).strip()

    if not suggestion:
        await update.effective_message.reply_text(
            "اكتب اقتراحك بهذا الشكل:\n"
            "/suggest أريد إضافة ميزة جديدة"
        )
        return

    if len(suggestion) > 1500:
        await update.effective_message.reply_text(
            "الاقتراح طويل جدًا، اختصره قليلًا."
        )
        return

    save_suggestion(user.id, suggestion)

    await update.effective_message.reply_text(
        "✅ وصل اقتراحك بنجاح، شكرًا لك!"
    )


# =========================
# Gemini AI
# =========================

async def ask_gemini(update: Update, prompt: str):
    user = update.effective_user
    user_id = user.id

    if not GEMINI_API_KEY:
        await update.effective_message.reply_text(
            "⚠️ Gemini غير مفعّل.\n"
            "أضف GEMINI_API_KEY في Render."
        )
        return

    if len(prompt) > 8000:
        await update.effective_message.reply_text(
            "السؤال طويل جدًا، أرسل سؤالًا أقصر."
        )
        return

    status = await update.effective_message.reply_text(
        "✨ Gemini يفكر في إجابتك..."
    )

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)

        history = get_history(user_id)

        contents = []

        for item in history:
            role = item.get("role")
            text = item.get("content", "")

            if not text:
                continue

            if role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=text)],
                    )
                )

            elif role == "assistant":
                contents.append(
                    types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=text)],
                    )
                )

        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)],
            )
        )

        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "أنت مساعد ذكي وودود داخل بوت تيليغرام. "
                    "أجب باللغة العربية الواضحة. "
                    "ساعد في البرمجة والتقنية والأسئلة العامة. "
                    "اشرح بشكل مفيد ومنظم. "
                    "إذا لم تعرف الإجابة، قل ذلك بوضوح. "
                    "لا تدّع تنفيذ إجراءات خارج المحادثة."
                ),
                temperature=0.7,
            ),
        )

        answer = (response.text or "").strip()

        if not answer:
            answer = "لم أتمكن من إنشاء إجابة، حاول مرة أخرى."

        history.append({
            "role": "user",
            "content": prompt,
        })

        history.append({
            "role": "assistant",
            "content": answer,
        })

        save_history(user_id, history)

        try:
            await status.delete()
        except Exception:
            pass

        for i in range(0, len(answer), 4000):
            await update.effective_message.reply_text(
                answer[i:i + 4000]
            )

    except Exception:
        logger.exception("Gemini request failed")

        try:
            await status.delete()
        except Exception:
            pass

        await update.effective_message.reply_text(
            "❌ تعذر الاتصال بـ Gemini.\n\n"
            "تحقق من:\n"
            "1. صحة مفتاح Gemini.\n"
            "2. اسم النموذج.\n"
            "3. حدود الاستخدام المجاني.\n"
            "4. سجل الأخطاء في Render."
        )


async def ask_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    save_user(user)

    prompt = " ".join(context.args).strip()

    if not prompt:
        await update.effective_message.reply_text(
            "اكتب سؤالك بهذا الشكل:\n"
            "/ask اشرح لي البرمجة"
        )
        return

    await ask_gemini(update, prompt)


async def reset_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    clear_history(update.effective_user.id)

    await update.effective_message.reply_text(
        "🧹 تم مسح ذاكرة محادثتك مع Gemini."
    )


# =========================
# الإدارة
# =========================

def is_admin(user_id):
    try:
        return ADMIN_ID and int(ADMIN_ID) == int(user_id)
    except Exception:
        return False


async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(
            "⛔ هذا الأمر للإدارة فقط."
        )
        return

    await update.effective_message.reply_text(
        "👑 لوحة الإدارة\n\n"
        "/stats - إحصائيات البوت\n"
        "/broadcast رسالتك - بث رسالة"
    )


async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(
            "⛔ هذا الأمر للإدارة فقط."
        )
        return

    with get_db() as db:
        users_count = db.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        suggestions_count = db.execute(
            "SELECT COUNT(*) FROM suggestions"
        ).fetchone()[0]

    await update.effective_message.reply_text(
        "📊 إحصائيات البوت\n\n"
        f"👥 المستخدمون: {users_count}\n"
        f"💡 الاقتراحات: {suggestions_count}"
    )


async def broadcast_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(
            "⛔ هذا الأمر للإدارة فقط."
        )
        return

    message = " ".join(context.args).strip()

    if not message:
        await update.effective_message.reply_text(
            "استخدم:\n/broadcast مرحبًا بكم"
        )
        return

    with get_db() as db:
        users = db.execute(
            "SELECT user_id FROM users"
        ).fetchall()

    success = 0
    failed = 0

    await update.effective_message.reply_text(
        f"📢 بدأ البث إلى {len(users)} مستخدم."
    )

    for row in users:
        try:
            await context.bot.send_message(
                chat_id=row[0],
                text=message,
            )
            success += 1
        except Exception:
            failed += 1

    await update.effective_message.reply_text(
        f"انتهى البث.\n"
        f"نجح: {success}\n"
        f"فشل: {failed}"
    )


# =========================
# الأزرار
# =========================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    save_user(query.from_user)

    if query.data == "ask":
        await query.message.reply_text(
            "🧠 أرسل سؤالك مباشرة أو استخدم:\n"
            "/ask اشرح لي الذكاء الاصطناعي"
        )

    elif query.data == "developer":
        await developer_command(update, context)

    elif query.data == "info":
        await info_command(update, context)

    elif query.data == "suggest":
        await query.message.reply_text(
            "💡 أرسل اقتراحك بهذا الشكل:\n"
            "/suggest اقتراحي هو..."
        )


# =========================
# الرسائل العادية
# =========================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    save_user(user)

    prompt = (update.effective_message.text or "").strip()

    if prompt:
        await ask_gemini(update, prompt)


# =========================
# أوامر تيليغرام
# =========================

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "تشغيل البوت"),
        BotCommand("help", "المساعدة"),
        BotCommand("info", "معلومات البوت"),
        BotCommand("ask", "اسأل Gemini"),
        BotCommand("reset", "مسح ذاكرة المحادثة"),
        BotCommand("suggest", "إرسال اقتراح"),
        BotCommand("admin", "لوحة الإدارة"),
        BotCommand("stats", "الإحصائيات"),
    ])


# =========================
# تشغيل Render
# =========================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN غير موجود")

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
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
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    external_url = os.getenv(
        "RENDER_EXTERNAL_URL", ""
    ).strip().rstrip("/")

    port = int(os.getenv("PORT", "10000"))

    if external_url:
        import hashlib

        webhook_path = hashlib.sha256(
            BOT_TOKEN.encode()
        ).hexdigest()[:32]

        webhook_secret = hashlib.sha256(
            (BOT_TOKEN + "telegram-webhook").encode()
        ).hexdigest()[:32]

        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=webhook_path,
            webhook_url=f"{external_url}/{webhook_path}",
            secret_token=webhook_secret,
            bootstrap_retries=-1,
        )
    else:
        application.run_polling()


if __name__ == "__main__":
    main()

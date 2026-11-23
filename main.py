import os
import re
import json
import sqlite3
import logging
import hashlib
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
from openai import AsyncOpenAI


# =========================================================
# إعدادات البوت
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5").strip()

ADMIN_ID = os.environ.get("ADMIN_ID", "").strip()
DATABASE_PATH = os.environ.get("DATABASE_PATH", "bot_data.db")

TELEGRAM_LINK = "https://t.me/alsvdbdbdhdhdjhfh"
INSTAGRAM_LINK = "https://www.instagram.com/2a3ka?hvrq=dDZhdjFsajJ1NHV6"
WEBSITE_LINK = "https://astounding-seahorse-021ea5.netlify.app/"

DEVELOPER_BIO = "شاب سوري شغوف بالبرمجة ويسعى لإتقانها"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# قاعدة البيانات
# =========================================================

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
            INSERT INTO users (user_id, username, first_name, joined_at)
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
            INSERT INTO suggestions (user_id, suggestion, created_at)
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
    except (json.JSONDecodeError, TypeError):
        return []


def save_history(user_id, history):
    # الاحتفاظ بآخر 10 رسائل فقط لتقليل استهلاك API
    history = history[-10:]

    with get_db() as db:
        db.execute("""
            INSERT INTO chat_history (user_id, history)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                history = excluded.history
        """, (user_id, json.dumps(history, ensure_ascii=False)))


def clear_history(user_id):
    with get_db() as db:
        db.execute(
            "DELETE FROM chat_history WHERE user_id = ?",
            (user_id,),
        )


# =========================================================
# القوائم والأزرار
# =========================================================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "🤖 اسأل الذكاء الاصطناعي",
                callback_data="ask",
            )
        ],
        [
            InlineKeyboardButton(
                "👨‍💻 معلومات المطور",
                callback_data="developer",
            ),
            InlineKeyboardButton(
                "📊 معلومات البوت",
                callback_data="info",
            ),
        ],
        [
            InlineKeyboardButton(
                "💡 إرسال اقتراح",
                callback_data="suggest",
            ),
        ],
        [
            InlineKeyboardButton(
                "📱 تيليغرام المطور",
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


# =========================================================
# أمر البداية
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    name = user.first_name or "صديقي"

    text = (
        f"أهلًا وسهلًا بك يا {name} 👋\n\n"
        "أنا بوت مساعد ذكي، أستطيع مساعدتك في:\n\n"
        "🤖 الإجابة عن الأسئلة\n"
        "💻 البرمجة والتقنية\n"
        "📚 المعلومات العامة\n"
        "💡 استقبال اقتراحاتك\n\n"
        "اختر ما تريد من القائمة التالية:"
    )

    await update.effective_message.reply_text(
        text,
        reply_markup=main_menu(),
    )


# =========================================================
# المساعدة
# =========================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 أوامر البوت:\n\n"
        "/start - تشغيل البوت\n"
        "/help - عرض المساعدة\n"
        "/info - معلومات البوت\n"
        "/ask سؤالك - سؤال الذكاء الاصطناعي\n"
        "/reset - مسح ذاكرة المحادثة\n"
        "/suggest اقتراحك - إرسال اقتراح\n\n"
        "مثال:\n"
        "/ask كيف أتعلم البرمجة؟"
    )

    await update.effective_message.reply_text(text)


# =========================================================
# معلومات البوت
# =========================================================

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📊 معلومات البوت\n\n"
        "الاسم: المساعد الذكي\n"
        "اللغة: العربية\n"
        "الذكاء الاصطناعي: OpenAI\n"
        "الاستضافة: Render\n\n"
        "تم تطوير البوت لخدمة المستخدمين "
        "وتقديم المساعدة التقنية والمعلوماتية."
    )

    await update.effective_message.reply_text(text)


# =========================================================
# معلومات المطور
# =========================================================

async def developer_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = (
        "👨‍💻 معلومات المطور\n\n"
        f"{DEVELOPER_BIO}\n\n"
        "يمكنك التواصل مع المطور عبر الروابط التالية:"
    )

    keyboard = [
        [InlineKeyboardButton("📱 تيليغرام", url=TELEGRAM_LINK)],
        [InlineKeyboardButton("📸 إنستغرام", url=INSTAGRAM_LINK)],
        [InlineKeyboardButton("🌐 الموقع", url=WEBSITE_LINK)],
    ]

    await update.effective_message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# الاقتراحات
# =========================================================

async def suggest_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    save_user(user)

    suggestion = " ".join(context.args).strip()

    if not suggestion:
        await update.effective_message.reply_text(
            "💡 أرسل اقتراحك بهذا الشكل:\n"
            "/suggest أريد إضافة ميزة جديدة"
        )
        return

    if len(suggestion) > 1500:
        await update.effective_message.reply_text(
            "الاقتراح طويل جدًا. اختصره قليلًا."
        )
        return

    save_suggestion(user.id, suggestion)

    await update.effective_message.reply_text(
        "✅ تم استلام اقتراحك بنجاح.\n"
        "شكرًا لمساعدتنا على تطوير البوت!"
    )


# =========================================================
# الذكاء الاصطناعي
# =========================================================

async def ask_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    save_user(user)

    prompt = " ".join(context.args).strip()

    if not prompt:
        await update.effective_message.reply_text(
            "🧠 اكتب سؤالك بعد الأمر:\n\n"
            "/ask اشرح لي الذكاء الاصطناعي"
        )
        return

    if not OPENAI_API_KEY:
        await update.effective_message.reply_text(
            "⚠️ الذكاء الاصطناعي غير مفعّل حاليًا.\n"
            "يرجى إضافة OPENAI_API_KEY في إعدادات Render."
        )
        return

    if len(prompt) > 8000:
        await update.effective_message.reply_text(
            "السؤال طويل جدًا. أرسل سؤالًا أقصر."
        )
        return

    status = await update.effective_message.reply_text(
        "🧠 لحظة، أفكر في إجابتك..."
    )

    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        history = get_history(user.id)

        conversation = history + [
            {
                "role": "user",
                "content": prompt,
            }
        ]

        response = await client.responses.create(
            model=OPENAI_MODEL,
            instructions=(
                "أنت مساعد ذكي داخل بوت تيليغرام. "
                "أجب باللغة العربية الواضحة والودودة. "
                "استخدم اللهجة العربية البسيطة عند الحاجة. "
                "ساعد في البرمجة والتقنية والأسئلة العامة. "
                "إذا لم تكن متأكدًا من معلومة، وضح ذلك. "
                "لا تدّع أنك نفذت إجراءً خارج المحادثة."
            ),
            input=conversation,
        )

        answer = (response.output_text or "").strip()

        if not answer:
            answer = "لم أتمكن من إنشاء إجابة. حاول مرة أخرى."

        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": answer})
        save_history(user.id, history)

        try:
            await status.delete()
        except Exception:
            pass

        # تيليغرام يسمح برسالة نصية حتى 4096 حرفًا تقريبًا
        for i in range(0, len(answer), 4000):
            await update.effective_message.reply_text(
                answer[i:i + 4000]
            )

    except Exception:
        logger.exception("OpenAI request failed")

        try:
            await status.delete()
        except Exception:
            pass

        await update.effective_message.reply_text(
            "❌ حدث خطأ أثناء الاتصال بالذكاء الاصطناعي.\n\n"
            "تأكد من:\n"
            "1. صحة مفتاح OpenAI.\n"
            "2. وجود رصيد API.\n"
            "3. صحة اسم النموذج في OPENAI_MODEL.\n"
            "4. نجاح تشغيل البوت على Render."
        )


# =========================================================
# مسح ذاكرة المحادثة
# =========================================================

async def reset_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    clear_history(user.id)

    await update.effective_message.reply_text(
        "🧹 تم مسح ذاكرة محادثتك مع الذكاء الاصطناعي."
    )


# =========================================================
# لوحة الإدارة
# =========================================================

def is_admin(user_id):
    if not ADMIN_ID:
        return False

    try:
        return int(ADMIN_ID) == int(user_id)
    except (TypeError, ValueError):
        return False


async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user

    if not is_admin(user.id):
        await update.effective_message.reply_text(
            "⛔ هذا الأمر مخصص للإدارة."
        )
        return

    text = (
        "👑 لوحة الإدارة\n\n"
        "الأوامر المتاحة:\n"
        "/stats - إحصائيات البوت\n"
        "/broadcast رسالتك - إرسال رسالة للجميع"
    )

    await update.effective_message.reply_text(text)


# =========================================================
# إحصائيات البوت
# =========================================================

async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user

    if not is_admin(user.id):
        await update.effective_message.reply_text(
            "⛔ هذا الأمر مخصص للإدارة."
        )
        return

    with get_db() as db:
        users_count = db.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        suggestions_count = db.execute(
            "SELECT COUNT(*) FROM suggestions"
        ).fetchone()[0]

    text = (
        "📊 إحصائيات البوت\n\n"
        f"👥 عدد المستخدمين: {users_count}\n"
        f"💡 عدد الاقتراحات: {suggestions_count}"
    )

    await update.effective_message.reply_text(text)


# =========================================================
# بث رسالة لجميع المستخدمين
# =========================================================

async def broadcast_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user

    if not is_admin(user.id):
        await update.effective_message.reply_text(
            "⛔ هذا الأمر مخصص للإدارة."
        )
        return

    message = " ".join(context.args).strip()

    if not message:
        await update.effective_message.reply_text(
            "استخدم الأمر بهذا الشكل:\n"
            "/broadcast مرحبًا بكم في البوت"
        )
        return

    with get_db() as db:
        rows = db.execute(
            "SELECT user_id FROM users"
        ).fetchall()

    success = 0
    failed = 0

    await update.effective_message.reply_text(
        f"📢 بدأ إرسال الرسالة إلى {len(rows)} مستخدم."
    )

    for row in rows:
        user_id = row[0]

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=message,
            )
            success += 1

        except Exception:
            failed += 1
            logger.warning("Broadcast failed for user %s", user_id)

    await update.effective_message.reply_text(
        "✅ انتهى البث.\n\n"
        f"تم الإرسال: {success}\n"
        f"فشل الإرسال: {failed}"
    )


# =========================================================
# أزرار القائمة
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    save_user(user)

    if query.data == "ask":
        await query.message.reply_text(
            "🤖 اكتب سؤالك بهذا الشكل:\n\n"
            "/ask كيف أتعلم البرمجة؟"
        )

    elif query.data == "developer":
        await query.message.reply_text(
            f"👨‍💻 {DEVELOPER_BIO}\n\n"
            "روابط المطور:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📱 تيليغرام",
                    url=TELEGRAM_LINK,
                )],
                [InlineKeyboardButton(
                    "📸 إنستغرام",
                    url=INSTAGRAM_LINK,
                )],
                [InlineKeyboardButton(
                    "🌐 الموقع",
                    url=WEBSITE_LINK,
                )],
            ]),
        )

    elif query.data == "info":
        await query.message.reply_text(
            "📊 بوت مساعد ذكي باللغة العربية.\n"
            "يعمل باستخدام OpenAI وTelegram."
        )

    elif query.data == "suggest":
        await query.message.reply_text(
            "💡 أرسل اقتراحك بهذا الشكل:\n\n"
            "/suggest أريد إضافة ميزة جديدة"
        )


# =========================================================
# استقبال الرسائل العادية
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    save_user(user)

    await update.effective_message.reply_text(
        "وصلت رسالتك 👋\n\n"
        "للتحدث مع الذكاء الاصطناعي، استخدم:\n"
        "/ask ثم اكتب سؤالك.\n\n"
        "مثال:\n"
        "/ask اشرح لي بايثون"
    )


# =========================================================
# إعداد أوامر البوت
# =========================================================

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "تشغيل البوت"),
        BotCommand("help", "المساعدة"),
        BotCommand("info", "معلومات البوت"),
        BotCommand("ask", "اسأل الذكاء الاصطناعي"),
        BotCommand("reset", "مسح ذاكرة المحادثة"),
        BotCommand("suggest", "إرسال اقتراح"),
        BotCommand("admin", "لوحة الإدارة"),
        BotCommand("stats", "الإحصائيات"),
    ])


# =========================================================
# تشغيل البوت على Render
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN غير موجود في Environment Variables"
        )

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

    external_url = os.environ.get(
        "RENDER_EXTERNAL_URL", ""
    ).strip().rstrip("/")

    port = int(os.environ.get("PORT", "10000"))

    if external_url:
        # إنشاء مسار Webhook آمن دون كشف توكن البوت
        webhook_path = hashlib.sha256(
            BOT_TOKEN.encode()
        ).hexdigest()[:32]

        webhook_secret = hashlib.sha256(
            (BOT_TOKEN + "telegram-webhook").encode()
        ).hexdigest()[:32]

        webhook_url = (
            f"{external_url}/{webhook_path}"
        )

        logger.info("Starting Telegram webhook")

        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=webhook_path,
            webhook_url=webhook_url,
            secret_token=webhook_secret,
            bootstrap_retries=-1,
        )

    else:
        logger.info("Starting Telegram polling")
        application.run_polling()


if __name__ == "__main__":
    main()

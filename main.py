
import os
import logging
import sqlite3
from datetime import datetime, timezone

from telegram import (
    Update,
    BotCommand,
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

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)
DB_PATH = os.environ.get("DB_PATH", "bot_data.sqlite3")

TELEGRAM_LINK = "https://t.me/alsvdbdbdhdhdjhfh"
INSTAGRAM_LINK = "https://www.instagram.com/2a3ka?hvrq=dDZhdjFsajJ1NHV6"
WEBSITE_LINK = "https://astounding-seahorse-021ea5.netlify.app/"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


def db():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            created_at TEXT
        )
    """)

    return conn


def save_user(user):
    if not user:
        return

    with db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO users
            (user_id, username, first_name, joined_at)
            VALUES (
                ?, ?, ?,
                COALESCE(
                    (SELECT joined_at FROM users WHERE user_id=?),
                    ?
                )
            )
            """,
            (
                user.id,
                user.username or "",
                user.first_name or "",
                user.id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def user_count():
    with db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]


def home_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "⚡ مركز الأوامر",
                callback_data="commands",
            ),
            InlineKeyboardButton(
                "👨‍💻 المطوّر",
                callback_data="developer",
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 تيليغرام",
                url=TELEGRAM_LINK,
            ),
            InlineKeyboardButton(
                "📸 إنستغرام",
                url=INSTAGRAM_LINK,
            ),
        ],
        [
            InlineKeyboardButton(
                "🌐 موقع المطوّر",
                url=WEBSITE_LINK,
            ),
        ],
        [
            InlineKeyboardButton(
                "💡 اقتراح أو مشكلة",
                callback_data="suggest",
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def admin_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "📊 الإحصائيات",
                callback_data="admin_stats",
            ),
        ],
        [
            InlineKeyboardButton(
                "📣 طريقة الإذاعة",
                callback_data="admin_broadcast",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 الرئيسية",
                callback_data="home",
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def is_admin(user):
    return bool(
        user
        and ADMIN_ID
        and user.id == ADMIN_ID
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    save_user(update.effective_user)

    await update.effective_message.reply_text(
        "✨ أهلاً بك في مركز المطوّر الرقمي!\n\n"
        "أنا بوت شخصي قيد التطوير.\n"
        "اختر ما تريد من القائمة:",
        reply_markup=home_keyboard(),
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    save_user(update.effective_user)

    await update.effective_message.reply_text(
        "📋 أوامر البوت:\n\n"
        "/start — القائمة الرئيسية\n"
        "/help — المساعدة\n"
        "/info — معلومات البوت\n"
        "/suggest — إرسال اقتراح\n"
        "/ask — سؤال المساعد\n\n"
        "أوامر الإدارة:\n"
        "/admin — لوحة المطوّر\n"
        "/stats — إحصائيات البوت\n"
        "/broadcast — إرسال رسالة جماعية",
        reply_markup=home_keyboard(),
    )


async def info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    save_user(update.effective_user)

    await update.effective_message.reply_text(
        "🤖 ALI • DIGITAL CORE\n\n"
        "بوت شخصي لاستقبال الأوامر "
        "وتقديم أدوات مفيدة.\n"
        "يتم تطويره باستمرار.",
        reply_markup=home_keyboard(),
    )


async def developer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.effective_message.reply_text(
        "👨‍💻 معلومات المطوّر\n\n"
        "شاب سوري شغوف بالبرمجة "
        "ويسعى لإتقانها. 🇸🇾\n\n"
        "التعلّم مستمر والطموح لا يتوقف.",
        reply_markup=home_keyboard(),
    )


async def suggest(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    save_user(update.effective_user)

    message = " ".join(context.args).strip()

    if not message:
        await update.effective_message.reply_text(
            "اكتب اقتراحك بهذا الشكل:\n"
            "/suggest أضيفوا ميزة جديدة"
        )
        return

    with db() as conn:
        conn.execute(
            """
            INSERT INTO suggestions
            (user_id, message, created_at)
            VALUES (?, ?, ?)
            """,
            (
                update.effective_user.id,
                message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    if ADMIN_ID:
        user = update.effective_user

        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"💡 اقتراح جديد\n"
                f"الاسم: {user.full_name}\n"
                f"المعرف: {user.id}\n\n"
                f"{message}",
            )
        except Exception:
            log.exception(
                "Could not notify admin"
            )

    await update.effective_message.reply_text(
        "وصل اقتراحك، شكرًا لمساهمتك 💛"
    )


async def admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user):
        await update.effective_message.reply_text(
            "هذا الأمر مخصص للمطوّر فقط 🔒"
        )
        return

    await update.effective_message.reply_text(
        "🛡️ لوحة تحكم المطوّر\n"
        "اختر إحدى الأدوات:",
        reply_markup=admin_keyboard(),
    )


async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user):
        await update.effective_message.reply_text(
            "غير مصرح لك 🔒"
        )
        return

    await update.effective_message.reply_text(
        f"📊 إحصائيات البوت\n\n"
        f"👥 المستخدمون المسجلون: {user_count()}"
    )


async def broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user):
        await update.effective_message.reply_text(
            "غير مصرح لك 🔒"
        )
        return

    message = " ".join(context.args).strip()

    if not message:
        await update.effective_message.reply_text(
            "استخدم الأمر هكذا:\n"
            "/broadcast رسالتك لجميع المستخدمين"
        )
        return

    with db() as conn:
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT user_id FROM users"
            ).fetchall()
        ]

    sent = 0
    failed = 0

    status = await update.effective_message.reply_text(
        "⏳ جارٍ إرسال الرسالة..."
    )

    for user_id in ids:
        try:
            await context.bot.send_message(
                user_id,
                message,
            )
            sent += 1

        except Exception:
            failed += 1

    await status.edit_text(
        f"✅ انتهى الإرسال\n"
        f"وصلت: {sent}\n"
        f"تعذّر: {failed}"
    )


async def ask(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    save_user(update.effective_user)

    prompt = " ".join(context.args).strip()

    if not prompt:
        await update.effective_message.reply_text(
            "اكتب سؤالك بعد الأمر /ask"
        )
        return

    await update.effective_message.reply_text(
        "🧠 ميزة الذكاء الاصطناعي "
        "غير مربوطة حاليًا.\n\n"
        "سيتم تفعيلها عند إضافة "
        "خدمة الذكاء الاصطناعي."
    )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    data = query.data

    if data == "home":
        await query.message.reply_text(
            "🏠 القائمة الرئيسية:",
            reply_markup=home_keyboard(),
        )

    elif data == "commands":
        await query.message.reply_text(
            "⚡ مركز الأوامر\n\n"
            "/start — الرئيسية\n"
            "/help — المساعدة\n"
            "/info — معلومات البوت\n"
            "/suggest — إرسال اقتراح\n"
            "/ask — سؤال المساعد",
            reply_markup=home_keyboard(),
        )

    elif data == "developer":
        await developer(update, context)

    elif data == "suggest":
        await query.message.reply_text(
            "💡 لإرسال اقتراح أو مشكلة:\n"
            "/suggest ثم اكتب رسالتك"
        )

    elif data.startswith("admin_"):
        if not is_admin(query.from_user):
            await query.message.reply_text(
                "هذا القسم للمطوّر فقط 🔒"
            )
            return

        if data == "admin_stats":
            await query.message.reply_text(
                f"📊 المستخدمون المسجلون: "
                f"{user_count()}",
                reply_markup=admin_keyboard(),
            )

        elif data == "admin_broadcast":
            await query.message.reply_text(
                "📣 للإذاعة اكتب:\n"
                "/broadcast رسالتك هنا\n\n"
                "سيتم إرسالها للمستخدمين "
                "الذين بدأوا البوت.",
                reply_markup=admin_keyboard(),
            )


async def unknown(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.effective_message.reply_text(
        "لم أفهم الأمر 🤔\n"
        "اكتب /help لرؤية الأوامر."
    )


async def setup_commands(
    application: Application,
):
    await application.bot.set_my_commands([
        BotCommand("start", "القائمة الرئيسية"),
        BotCommand("help", "المساعدة والأوامر"),
        BotCommand("info", "معلومات البوت"),
        BotCommand("suggest", "إرسال اقتراح"),
        BotCommand("ask", "سؤال المساعد"),
        BotCommand("admin", "لوحة المطوّر"),
    ])


def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing"
        )

    if not RENDER_URL:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL is missing"
        )

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(setup_commands)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )
    app.add_handler(
        CommandHandler("help", help_command)
    )
    app.add_handler(
        CommandHandler("info", info)
    )
    app.add_handler(
        CommandHandler("suggest", suggest)
    )
    app.add_handler(
        CommandHandler("ask", ask)
    )
    app.add_handler(
        CommandHandler("admin", admin)
    )
    app.add_handler(
        CommandHandler("stats", stats)
    )
    app.add_handler(
        CommandHandler("broadcast", broadcast)
    )
    app.add_handler(
        CallbackQueryHandler(button_handler)
    )
    app.add_handler(
        MessageHandler(filters.COMMAND, unknown)
    )

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{RENDER_URL}/{TOKEN}",
    )


if __name__ == "__main__":
    main()
import os
import logging
import sqlite3
from datetime import datetime, timezone

from telegram import (
    Update,
    BotCommand,
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

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)
DB_PATH = os.environ.get("DB_PATH", "bot_data.sqlite3")

TELEGRAM_LINK = "https://t.me/alsvdbdbdhdhdjhfh"
INSTAGRAM_LINK = "https://www.instagram.com/2a3ka?hvrq=dDZhdjFsajJ1NHV6"
WEBSITE_LINK = "https://astounding-seahorse-021ea5.netlify.app/"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


def db():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            created_at TEXT
        )
    """)

    return conn


def save_user(user):
    if not user:
        return

    with db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO users
            (user_id, username, first_name, joined_at)
            VALUES (
                ?, ?, ?,
                COALESCE(
                    (SELECT joined_at FROM users WHERE user_id=?),
                    ?
                )
            )
            """,
            (
                user.id,
                user.username or "",
                user.first_name or "",
                user.id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def user_count():
    with db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]


def home_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "⚡ مركز الأوامر",
                callback_data="commands",
            ),
            InlineKeyboardButton(
                "👨‍💻 المطوّر",
                callback_data="developer",
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 تيليغرام",
                url=TELEGRAM_LINK,
            ),
            InlineKeyboardButton(
                "📸 إنستغرام",
                url=INSTAGRAM_LINK,
            ),
        ],
        [
            InlineKeyboardButton(
                "🌐 موقع المطوّر",
                url=WEBSITE_LINK,
            ),
        ],
        [
            InlineKeyboardButton(
                "💡 اقتراح أو مشكلة",
                callback_data="suggest",
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def admin_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "📊 الإحصائيات",
                callback_data="admin_stats",
            ),
        ],
        [
            InlineKeyboardButton(
                "📣 طريقة الإذاعة",
                callback_data="admin_broadcast",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 الرئيسية",
                callback_data="home",
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def is_admin(user):
    return bool(
        user
        and ADMIN_ID
        and user.id == ADMIN_ID
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    save_user(update.effective_user)

    await update.effective_message.reply_text(
        "✨ أهلاً بك في مركز المطوّر الرقمي!\n\n"
        "أنا بوت شخصي قيد التطوير.\n"
        "اختر ما تريد من القائمة:",
        reply_markup=home_keyboard(),
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    save_user(update.effective_user)

    await update.effective_message.reply_text(
        "📋 أوامر البوت:\n\n"
        "/start — القائمة الرئيسية\n"
        "/help — المساعدة\n"
        "/info — معلومات البوت\n"
        "/suggest — إرسال اقتراح\n"
        "/ask — سؤال المساعد\n\n"
        "أوامر الإدارة:\n"
        "/admin — لوحة المطوّر\n"
        "/stats — إحصائيات البوت\n"
        "/broadcast — إرسال رسالة جماعية",
        reply_markup=home_keyboard(),
    )


async def info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    save_user(update.effective_user)

    await update.effective_message.reply_text(
        "🤖 ALI • DIGITAL CORE\n\n"
        "بوت شخصي لاستقبال الأوامر "
        "وتقديم أدوات مفيدة.\n"
        "يتم تطويره باستمرار.",
        reply_markup=home_keyboard(),
    )


async def developer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.effective_message.reply_text(
        "👨‍💻 معلومات المطوّر\n\n"
        "شاب سوري شغوف بالبرمجة "
        "ويسعى لإتقانها. 🇸🇾\n\n"
        "التعلّم مستمر والطموح لا يتوقف.",
        reply_markup=home_keyboard(),
    )


async def suggest(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    save_user(update.effective_user)

    message = " ".join(context.args).strip()

    if not message:
        await update.effective_message.reply_text(
            "اكتب اقتراحك بهذا الشكل:\n"
            "/suggest أضيفوا ميزة جديدة"
        )
        return

    with db() as conn:
        conn.execute(
            """
            INSERT INTO suggestions
            (user_id, message, created_at)
            VALUES (?, ?, ?)
            """,
            (
                update.effective_user.id,
                message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    if ADMIN_ID:
        user = update.effective_user

        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"💡 اقتراح جديد\n"
                f"الاسم: {user.full_name}\n"
                f"المعرف: {user.id}\n\n"
                f"{message}",
            )
        except Exception:
            log.exception(
                "Could not notify admin"
            )

    await update.effective_message.reply_text(
        "وصل اقتراحك، شكرًا لمساهمتك 💛"
    )


async def admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user):
        await update.effective_message.reply_text(
            "هذا الأمر مخصص للمطوّر فقط 🔒"
        )
        return

    await update.effective_message.reply_text(
        "🛡️ لوحة تحكم المطوّر\n"
        "اختر إحدى الأدوات:",
        reply_markup=admin_keyboard(),
    )


async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user):
        await update.effective_message.reply_text(
            "غير مصرح لك 🔒"
        )
        return

    await update.effective_message.reply_text(
        f"📊 إحصائيات البوت\n\n"
        f"👥 المستخدمون المسجلون: {user_count()}"
    )


async def broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user):
        await update.effective_message.reply_text(
            "غير مصرح لك 🔒"
        )
        return

    message = " ".join(context.args).strip()

    if not message:
        await update.effective_message.reply_text(
            "استخدم الأمر هكذا:\n"
            "/broadcast رسالتك لجميع المستخدمين"
        )
        return

    with db() as conn:
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT user_id FROM users"
            ).fetchall()
        ]

    sent = 0
    failed = 0

    status = await update.effective_message.reply_text(
        "⏳ جارٍ إرسال الرسالة..."
    )

    for user_id in ids:
        try:
            await context.bot.send_message(
                user_id,
                message,
            )
            sent += 1

        except Exception:
            failed += 1

    await status.edit_text(
        f"✅ انتهى الإرسال\n"
        f"وصلت: {sent}\n"
        f"تعذّر: {failed}"
    )


async def ask(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    save_user(update.effective_user)

    prompt = " ".join(context.args).strip()

    if not prompt:
        await update.effective_message.reply_text(
            "اكتب سؤالك بعد الأمر /ask"
        )
        return

    await update.effective_message.reply_text(
        "🧠 ميزة الذكاء الاصطناعي "
        "غير مربوطة حاليًا.\n\n"
        "سيتم تفعيلها عند إضافة "
        "خدمة الذكاء الاصطناعي."
    )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    data = query.data

    if data == "home":
        await query.message.reply_text(
            "🏠 القائمة الرئيسية:",
            reply_markup=home_keyboard(),
        )

    elif data == "commands":
        await query.message.reply_text(
            "⚡ مركز الأوامر\n\n"
            "/start — الرئيسية\n"
            "/help — المساعدة\n"
            "/info — معلومات البوت\n"
            "/suggest — إرسال اقتراح\n"
            "/ask — سؤال المساعد",
            reply_markup=home_keyboard(),
        )

    elif data == "developer":
        await developer(update, context)

    elif data == "suggest":
        await query.message.reply_text(
            "💡 لإرسال اقتراح أو مشكلة:\n"
            "/suggest ثم اكتب رسالتك"
        )

    elif data.startswith("admin_"):
        if not is_admin(query.from_user):
            await query.message.reply_text(
                "هذا القسم للمطوّر فقط 🔒"
            )
            return

        if data == "admin_stats":
            await query.message.reply_text(
                f"📊 المستخدمون المسجلون: "
                f"{user_count()}",
                reply_markup=admin_keyboard(),
            )

        elif data == "admin_broadcast":
            await query.message.reply_text(
                "📣 للإذاعة اكتب:\n"
                "/broadcast رسالتك هنا\n\n"
                "سيتم إرسالها للمستخدمين "
                "الذين بدأوا البوت.",
                reply_markup=admin_keyboard(),
            )


async def unknown(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.effective_message.reply_text(
        "لم أفهم الأمر 🤔\n"
        "اكتب /help لرؤية الأوامر."
    )


async def setup_commands(
    application: Application,
):
    await application.bot.set_my_commands([
        BotCommand("start", "القائمة الرئيسية"),
        BotCommand("help", "المساعدة والأوامر"),
        BotCommand("info", "معلومات البوت"),
        BotCommand("suggest", "إرسال اقتراح"),
        BotCommand("ask", "سؤال المساعد"),
        BotCommand("admin", "لوحة المطوّر"),
    ])


def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing"
        )

    if not RENDER_URL:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL is missing"
        )

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(setup_commands)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )
    app.add_handler(
        CommandHandler("help", help_command)
    )
    app.add_handler(
        CommandHandler("info", info)
    )
    app.add_handler(
        CommandHandler("suggest", suggest)
    )
    app.add_handler(
        CommandHandler("ask", ask)
    )
    app.add_handler(
        CommandHandler("admin", admin)
    )
    app.add_handler(
        CommandHandler("stats", stats)
    )
    app.add_handler(
        CommandHandler("broadcast", broadcast)
    )
    app.add_handler(
        CallbackQueryHandler(button_handler)
    )
    app.add_handler(
        MessageHandler(filters.COMMAND, unknown)
    )

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{RENDER_URL}/{TOKEN}",
    )


if __name__ == "__main__":
    main()

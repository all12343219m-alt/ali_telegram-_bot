
import os
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ.get("BOT_TOKEN")
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "10000"))

# منصات المطور
TELEGRAM_LINK = "https://t.me/alsvdbdbdhdhdjhfh"
INSTAGRAM_LINK = "https://www.instagram.com/2a3ka?hvrq=dDZhdjFsajJ1NHV6"
WEBSITE_LINK = "https://astounding-seahorse-021ea5.netlify.app/"


def main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📢 تيليغرام المطور", url=TELEGRAM_LINK),
            InlineKeyboardButton("📸 إنستغرام", url=INSTAGRAM_LINK),
        ],
        [
            InlineKeyboardButton("🌐 موقع المطور", url=WEBSITE_LINK),
        ],
        [
            InlineKeyboardButton("👨‍💻 معلومات المطور", callback_data="developer"),
        ],
        [
            InlineKeyboardButton("📋 قائمة الأوامر", callback_data="commands"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلًا وسهلًا بك في بوت المطور 🤖\n\n"
        "بوت خاص لاستقبال الأوامر وتقديم الخدمات.\n"
        "اختر أحد الأزرار التالية للتعرف على منصاتي:",
        reply_markup=main_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 أوامر البوت:\n\n"
        "/start - تشغيل البوت\n"
        "/help - عرض الأوامر\n"
        "/info - معلومات البوت\n\n"
        "يمكنك أيضًا استخدام الأزرار الموجودة في القائمة.",
        reply_markup=main_keyboard(),
    )


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 بوت المطور\n\n"
        "بوت تجريبي يتم تطويره باستمرار.\n"
        "تابع منصات المطور لمعرفة الجديد.",
        reply_markup=main_keyboard(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "developer":
        await query.message.reply_text(
            "👨‍💻 معلومات المطور\n\n"
            "شاب سوري شغوف بالبرمجة "
            "ويسعى لإتقانها.\n\n"
            "🇸🇾 الطموح لا يتوقف، والتعلم مستمر."
        )

    elif query.data == "commands":
        await query.message.reply_text(
            "📋 قائمة الأوامر:\n\n"
            "/start - بدء البوت\n"
            "/help - المساعدة\n"
            "/info - معلومات البوت"
        )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "لم أفهم الأمر 🤔\n"
        "اكتب /help لمعرفة الأوامر."
    )


async def setup_commands(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "بدء البوت"),
        BotCommand("help", "عرض الأوامر"),
        BotCommand("info", "معلومات البوت"),
    ])


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    if not RENDER_URL:
        raise RuntimeError("RENDER_EXTERNAL_URL is missing")

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(setup_commands)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{RENDER_URL}/{TOKEN}",
    )


if __name__ == "__main__":
    main()

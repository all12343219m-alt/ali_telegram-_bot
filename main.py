import os
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ.get("BOT_TOKEN")
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "10000"))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك في بوت علي 🤖\n\n"
        "أنا بوت يستقبل الأوامر وينفذها.\n"
        "اكتب /help لمعرفة الأوامر."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 قائمة الأوامر:\n\n"
        "/start - بدء البوت\n"
        "/help - عرض المساعدة\n"
        "/info - معلومات البوت"
    )


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 بوت علي\n"
        "بوت تجريبي خاص بك.\n"
        "سيتم تطويره وإضافة أوامر جديدة إليه."
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
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{RENDER_URL}/{TOKEN}",
    )


if __name__ == "__main__":
    main()

import os
import re
import io
import json
import time
import base64
import random
import logging
import sqlite3
import asyncio
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from openai import AsyncOpenAI
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, BotCommandScopeChat, MenuButtonCommands,
)
from telegram.constants import ChatAction
from telegram.error import BadRequest
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
# نموذج تحليل الصور (يجب أن يدعم الصور). غيّره من Render إن لم يعمل.
OPENROUTER_VISION_MODEL = os.getenv("OPENROUTER_VISION_MODEL", "openrouter/free")

# Cloudflare Workers AI (توليد الصور + تحويل الصوت لنص)
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")
CF_IMAGE_MODEL = os.getenv("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
CF_STT_MODEL = os.getenv("CF_STT_MODEL", "@cf/openai/whisper-large-v3-turbo")

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

IMAGE_COOLDOWN = 15  # ثواني بين كل صورة وأخرى لنفس المستخدم

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# =========================
# قاعدة البيانات
# =========================
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

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
        """, (user.id, user.username or "", message, datetime.now().isoformat()))

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
# أدوات مساعدة عامة
# =========================
def http_get(url: str, timeout: int = 30):
    request = Request(url, headers={"User-Agent": "AliTelegramBot/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")

def cf_configured() -> bool:
    return bool(CF_ACCOUNT_ID and CF_API_TOKEN)

def cf_run(model: str, payload: dict, timeout: int = 120) -> dict:
    """استدعاء نموذج على Cloudflare Workers AI."""
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {CF_API_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "AliTelegramBot/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

async def reply_long(message, text: str, first=None):
    """يقسّم النص الطويل. إن مُرّرت first يُعدَّل بها أول جزء."""
    text = text or "..."
    parts = [text[i:i + 4000] for i in range(0, len(text), 4000)]
    for index, part in enumerate(parts):
        if index == 0 and first is not None:
            await first.edit_text(part)
        else:
            await message.reply_text(part)

def get_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """النص من الأمر، أو من الرسالة التي تم الرد عليها."""
    text = " ".join(context.args).strip()
    if not text and update.message.reply_to_message:
        reply = update.message.reply_to_message
        text = (reply.text or reply.caption or "").strip()
    return text

def has_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text))

# =========================
# الذكاء الاصطناعي - OpenRouter
# =========================
ai_client = None
if OPENROUTER_API_KEY:
    ai_client = AsyncOpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        timeout=90,
        default_headers={
            "HTTP-Referer": WEBSITE_LINK,
            "X-Title": "Ali Telegram Bot",
        },
    )

NO_KEY_MESSAGE = "❌ مفتاح OpenRouter غير موجود. أضف OPENROUTER_API_KEY في Render."

chat_history = {}
MAX_HISTORY = 12

def ai_error_message(error) -> str:
    text = str(error).lower()
    if "429" in text:
        return "⚠️ وصلت إلى حد الاستخدام المجاني مؤقتًا. انتظر قليلًا ثم حاول مجددًا."
    if "401" in text or "403" in text:
        return "❌ مشكلة في مفتاح OpenRouter أو صلاحياته. تحقق من المفتاح في Render."
    if "404" in text:
        return "❌ النموذج غير متاح حاليًا. تحقق من OPENROUTER_MODEL في Render."
    return "❌ حدث خطأ أثناء الاتصال بالذكاء الاصطناعي. حاول مرة أخرى بعد قليل."

async def ask_ai(user_id, question):
    if not ai_client:
        return NO_KEY_MESSAGE
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
        return ai_error_message(error)

async def ai_task(system: str, user_text: str, temperature: float = 0.4, max_tokens: int = 1200) -> str:
    """مهمة سريعة بدون ذاكرة محادثة (ترجمة، تلخيص، نكتة...)."""
    if not ai_client:
        return NO_KEY_MESSAGE
    try:
        response = await ai_client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        answer = (response.choices[0].message.content or "").strip()
        return answer or "لم يصلني رد من النموذج. حاول مرة أخرى."
    except Exception as error:
        logger.exception("ai_task error")
        return ai_error_message(error)

async def analyze_image(image_bytes: bytes, question: str) -> str:
    if not ai_client:
        return NO_KEY_MESSAGE
    data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
    try:
        response = await ai_client.chat.completions.create(
            model=OPENROUTER_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            max_tokens=900,
        )
        answer = (response.choices[0].message.content or "").strip()
        return answer or "لم أتمكن من تحليل الصورة. حاول مرة أخرى."
    except Exception as error:
        logger.exception("Vision error")
        return (
            ai_error_message(error)
            + "\n\n(إذا استمرت المشكلة، غيّر OPENROUTER_VISION_MODEL في Render إلى نموذج يدعم الصور)"
        )

# =========================
# أدوات النصوص: ترجمة / تلخيص / تصحيح
# =========================
LANGS = {
    "ar": "Arabic", "en": "English", "fr": "French", "de": "German",
    "es": "Spanish", "tr": "Turkish", "ru": "Russian", "it": "Italian",
}

async def run_text_tool(kind: str, text: str, target: str = "") -> str:
    if kind == "summarize":
        system = (
            "Summarize the following text concisely, in the same language as the text. "
            "Use short bullet points when helpful. Output only the summary."
        )
    elif kind == "fix":
        system = (
            "Correct the spelling, grammar and punctuation of the following text. "
            "Keep the same language and meaning. Output only the corrected text."
        )
    else:
        if not target:
            target = "English" if has_arabic(text) else "Arabic"
        system = (
            f"Translate the following text to {target}. "
            "Output only the translation, nothing else."
        )
    return await ai_task(system, text)

async def text_tool_command(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    save_user(update.effective_user)
    target = ""
    if kind == "translate" and context.args and context.args[0].lower() in LANGS:
        target = LANGS[context.args[0].lower()]
        context.args = context.args[1:]

    text = get_text_input(update, context)
    if not text:
        usage = {
            "translate": "🌐 اكتب النص بعد الأمر أو رد على رسالة:\n/translate مرحبا كيف حالك\n/translate en نص للترجمة للإنجليزية\n\nاللغات: ar en fr de es tr ru it",
            "summarize": "📝 اكتب النص بعد الأمر أو رد على رسالة طويلة بـ:\n/summarize",
            "fix": "✍️ اكتب النص بعد الأمر أو رد على رسالة بـ:\n/fix",
        }[kind]
        await update.message.reply_text(usage)
        return
    if len(text) > 6000:
        await update.message.reply_text("⚠️ النص طويل جدًا. اختصره إلى أقل من 6000 حرف.")
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    result = await run_text_tool(kind, text, target)
    await reply_long(update.message, result)

async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await text_tool_command(update, context, "translate")

async def summarize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await text_tool_command(update, context, "summarize")

async def fix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await text_tool_command(update, context, "fix")

# =========================
# التسلية
# =========================
JOKE_SYSTEM = (
    "اكتب نكتة واحدة قصيرة ونظيفة ومضحكة باللغة العربية. "
    "أخرج النكتة فقط بدون مقدمة."
)
QUOTE_SYSTEM = (
    "اكتب حكمة واحدة قصيرة وملهمة باللغة العربية، وإن عُرف قائلها فاذكره في سطر جديد. "
    "أخرج الحكمة فقط بدون مقدمة."
)

async def get_fun_text(kind: str) -> str:
    if kind == "joke":
        return "😄 " + await ai_task(JOKE_SYSTEM, f"نكتة جديدة #{random.randint(1, 99999)}", temperature=1.0, max_tokens=300)
    return "💡 " + await ai_task(QUOTE_SYSTEM, f"حكمة جديدة #{random.randint(1, 99999)}", temperature=1.0, max_tokens=300)

def again_keyboard(kind: str):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 غيرها", callback_data=f"again:{kind}")]])

async def joke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    await update.message.chat.send_action(ChatAction.TYPING)
    await update.message.reply_text(await get_fun_text("joke"), reply_markup=again_keyboard("joke"))

async def quote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    await update.message.chat.send_action(ChatAction.TYPING)
    await update.message.reply_text(await get_fun_text("quote"), reply_markup=again_keyboard("quote"))

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    await update.message.reply_dice(emoji="🎲")

async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    await update.message.reply_dice(emoji=random.choice(["🎯", "🏀", "⚽", "🎳", "🎰"]))

async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    await update.message.reply_text(random.choice(["🪙 ملك (صورة)", "🪙 كتابة (نقش)"]))

# =========================
# الأدوات: QR / اختصار / عملات
# =========================
async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    text = get_text_input(update, context)
    if not text:
        await update.message.reply_text("📱 اكتب النص أو الرابط بعد الأمر:\n/qr https://example.com")
        return
    if len(text) > 900:
        await update.message.reply_text("⚠️ النص طويل جدًا لرمز QR.")
        return
    await update.message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    url = f"https://api.qrserver.com/v1/create-qr-code/?size=600x600&margin=10&data={quote(text, safe='')}"
    try:
        data, content_type = await asyncio.to_thread(http_get, url)
        if not content_type.startswith("image/") or not data:
            raise RuntimeError("not an image")
        photo = io.BytesIO(data)
        photo.name = "qr.png"
        await update.message.reply_photo(photo=photo, caption="✅ رمز QR جاهز")
    except Exception:
        logger.exception("QR failed")
        await update.message.reply_text("❌ تعذّر إنشاء رمز QR الآن. حاول لاحقًا.")

async def short_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    link = get_text_input(update, context).split()[0] if get_text_input(update, context) else ""
    if not link:
        await update.message.reply_text("🔗 اكتب الرابط بعد الأمر:\n/short https://example.com/very/long/link")
        return
    if not link.lower().startswith(("http://", "https://")):
        link = "https://" + link
    url = f"https://is.gd/create.php?format=simple&url={quote(link, safe='')}"
    try:
        data, _ = await asyncio.to_thread(http_get, url)
        result = data.decode("utf-8", errors="ignore").strip()
        if not result.startswith("http"):
            raise RuntimeError(result)
        await update.message.reply_text(f"🔗 الرابط المختصر:\n{result}")
    except HTTPError as error:
        # is.gd يعيد خطأ 400 مع شرح عند الرابط غير الصالح
        logger.warning("Shorten HTTP error: %s", error.code)
        await update.message.reply_text("❌ الرابط غير صالح أو غير مسموح باختصاره.")
    except Exception:
        logger.exception("Shorten failed")
        await update.message.reply_text("❌ تعذّر اختصار الرابط الآن. حاول لاحقًا.")

def fetch_rate(base: str, target: str):
    data, _ = http_get(f"https://open.er-api.com/v6/latest/{quote(base, safe='')}")
    result = json.loads(data.decode("utf-8"))
    if result.get("result") != "success":
        raise RuntimeError("bad base currency")
    return (result.get("rates") or {}).get(target)

async def currency_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    usage = "💱 تحويل العملات:\n/currency 100 USD EUR\n/currency USD SAR"
    args = context.args
    try:
        if len(args) == 2:
            amount, base, target = 1.0, args[0], args[1]
        elif len(args) == 3:
            amount, base, target = float(args[0].replace(",", "")), args[1], args[2]
        else:
            await update.message.reply_text(usage)
            return
    except ValueError:
        await update.message.reply_text(usage)
        return

    base, target = base.upper(), target.upper()
    try:
        rate = await asyncio.to_thread(fetch_rate, base, target)
        if rate is None:
            await update.message.reply_text("❌ رمز العملة غير معروف. استخدم رموزًا مثل USD EUR SAR TRY.")
            return
        await update.message.reply_text(
            f"💱 {amount:,.2f} {base} = {amount * rate:,.2f} {target}\n"
            f"📈 1 {base} = {rate:,.4f} {target}\n\n"
            "الأسعار تقريبية وليست للتداول."
        )
    except Exception:
        logger.exception("Currency failed")
        await update.message.reply_text("❌ تعذّر جلب أسعار العملات الآن. تأكد من الرموز وحاول لاحقًا.")

# =========================
# توليد الصور - Cloudflare Workers AI
# =========================
async def translate_prompt(prompt: str) -> str:
    """يترجم الوصف للإنجليزية ويحسّنه لتوليد الصور."""
    if not ai_client:
        return prompt
    try:
        response = await ai_client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate the user's image description into a detailed "
                        "English prompt for an image generator. Output only the "
                        "English prompt, nothing else."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        return (response.choices[0].message.content or prompt).strip()
    except Exception:
        logger.exception("Translate failed")
        return prompt

def download_generated_image(prompt: str) -> bytes:
    result = cf_run(CF_IMAGE_MODEL, {"prompt": prompt, "steps": 8}, timeout=120)
    image_b64 = (result.get("result") or {}).get("image")
    if not image_b64:
        raise RuntimeError("لم تُرجع الخدمة صورة.")
    return base64.b64decode(image_b64)

def image_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 إعادة التوليد", callback_data="regen")]])

async def run_image_generation(message, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    if not cf_configured():
        await message.reply_text(
            "❌ إعدادات توليد الصور غير مضبوطة.\n"
            "أضف CF_ACCOUNT_ID و CF_API_TOKEN في Render Environment."
        )
        return
    if len(prompt) > 1000:
        await message.reply_text("⚠️ الوصف طويل جدًا. اختصره إلى أقل من 1000 حرف.")
        return

    last = context.user_data.get("last_image_ts")
    now = time.time()
    if last is not None and now - last < IMAGE_COOLDOWN:
        wait = int(IMAGE_COOLDOWN - (now - last)) + 1
        await message.reply_text(f"⏳ انتظر {wait} ثانية قبل طلب صورة جديدة.")
        return
    context.user_data["last_image_ts"] = now
    context.user_data["last_image_prompt"] = prompt

    status = await message.reply_text(
        "🎨 بدأت بتوليد الصورة...\n"
        "قد يستغرق الأمر بعض الوقت، انتظر من فضلك."
    )
    try:
        await message.chat.send_action(ChatAction.UPLOAD_PHOTO)
        english_prompt = await translate_prompt(prompt)
        image_bytes = await asyncio.to_thread(download_generated_image, english_prompt)
        photo = io.BytesIO(image_bytes)
        photo.name = "generated_image.jpg"
        await message.reply_photo(
            photo=photo,
            caption=f"✨ {prompt[:900]}",
            reply_markup=image_keyboard(),
        )
        await status.delete()

    except HTTPError as error:
        logger.warning("Cloudflare HTTP error: %s", error.code)
        if error.code in (401, 403):
            text = "🔑 التوكن أو Account ID غير صحيح. تحقق منهما في Render."
        elif error.code == 429:
            text = "⏳ نفدت الحصة اليومية أو الطلبات كثيرة. انتظر ثم جرّب."
        else:
            text = f"❌ خدمة الصور أعادت خطأ HTTP {error.code}. حاول لاحقًا."
        await status.edit_text(text)

    except (URLError, TimeoutError) as error:
        logger.warning("Cloudflare connection/timeout: %s", error)
        await status.edit_text("🌐 تعذّر الاتصال بخدمة الصور أو انتهت مهلة الطلب. حاول مجددًا.")

    except Exception:
        logger.exception("Image generation failed")
        await status.edit_text(
            "❌ لم أتمكن من توليد الصورة هذه المرة.\n"
            "تحقق من إعدادات CF_ACCOUNT_ID و CF_API_TOKEN."
        )

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text(
            "🎨 اكتب وصف الصورة بعد الأمر:\n\n"
            "/image قطة بيضاء على سطح القمر بأسلوب سينمائي"
        )
        return
    await run_image_generation(update.message, context, prompt)

# =========================
# الصور والصوت (تحليل الصور + تحويل الصوت لنص)
# =========================
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    save_user(update.effective_user)
    if not ai_client:
        await message.reply_text(NO_KEY_MESSAGE)
        return
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > 8 * 1024 * 1024:
        await message.reply_text("⚠️ الصورة كبيرة جدًا. أرسل صورة أصغر.")
        return

    question = (message.caption or "").strip() or "صف هذه الصورة بالتفصيل."
    status = await message.reply_text("🔍 جاري تحليل الصورة...")
    try:
        await message.chat.send_action(ChatAction.TYPING)
        file = await photo.get_file()
        image_bytes = bytes(await file.download_as_bytearray())
        answer = await analyze_image(
            image_bytes,
            question + "\n\n(أجب باللغة العربية ما لم يطلب المستخدم غير ذلك.)",
        )
        await reply_long(message, answer, first=status)
    except Exception:
        logger.exception("Photo handler failed")
        await status.edit_text("❌ تعذّر تحليل الصورة. حاول مرة أخرى.")

def transcribe_audio(audio_bytes: bytes) -> str:
    payload = {"audio": base64.b64encode(audio_bytes).decode("ascii")}
    result = cf_run(CF_STT_MODEL, payload, timeout=120)
    return ((result.get("result") or {}).get("text") or "").strip()

TRANSCRIPT_HEADER = "📝 النص المستخرج:\n\n"

def text_actions_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📝 لخّص", callback_data="act:summarize"),
        InlineKeyboardButton("🌐 ترجم", callback_data="act:translate"),
        InlineKeyboardButton("✍️ صحّح", callback_data="act:fix"),
    ]])

async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    save_user(update.effective_user)
    media = message.voice or message.audio
    if not media:
        return
    if not cf_configured():
        await message.reply_text(
            "❌ إعدادات تحويل الصوت غير مضبوطة.\n"
            "أضف CF_ACCOUNT_ID و CF_API_TOKEN في Render Environment."
        )
        return
    if media.duration and media.duration > 180:
        await message.reply_text("⚠️ التسجيل طويل. أرسل تسجيلًا أقصر من 3 دقائق.")
        return
    if media.file_size and media.file_size > 10 * 1024 * 1024:
        await message.reply_text("⚠️ الملف الصوتي كبير جدًا.")
        return

    status = await message.reply_text("🎧 جاري تحويل الصوت إلى نص...")
    try:
        await message.chat.send_action(ChatAction.TYPING)
        file = await media.get_file()
        audio_bytes = bytes(await file.download_as_bytearray())
        text = await asyncio.to_thread(transcribe_audio, audio_bytes)
        if not text:
            await status.edit_text("لم ألتقط كلامًا واضحًا في التسجيل.")
            return
        await status.edit_text(
            (TRANSCRIPT_HEADER + text)[:4000],
            reply_markup=text_actions_keyboard(),
        )
    except HTTPError as error:
        logger.warning("Whisper HTTP error: %s", error.code)
        if error.code in (401, 403):
            msg = "🔑 التوكن أو Account ID غير صحيح."
        elif error.code == 429:
            msg = "⏳ نفدت الحصة اليومية. جرّب لاحقًا."
        else:
            msg = f"❌ خدمة تحويل الصوت أعادت خطأ HTTP {error.code}."
        await status.edit_text(msg)
    except Exception:
        logger.exception("Voice handler failed")
        await status.edit_text("❌ تعذّر تحويل الصوت إلى نص. حاول مرة أخرى.")

# =========================
# القوائم والأزرار
# =========================
MENUS = {
    "ai": (
        "🤖 الذكاء الاصطناعي\n\n"
        "• اكتب أي سؤال مباشرة وسأجيبك\n"
        "• /ask سؤالك\n"
        "• أرسل صورة (مع سؤال اختياري) وسأحلّلها\n"
        "• /reset لمسح ذاكرة المحادثة"
    ),
    "image": (
        "🎨 توليد الصور\n\n"
        "• /image وصف الصورة\n"
        "• أو اكتب مباشرة: ارسم قطة على القمر\n\n"
        "يدعم العربية، وتحت كل صورة زر 🔄 لإعادة التوليد."
    ),
    "text": (
        "📝 أدوات النصوص\n\n"
        "• /translate نص — ترجمة تلقائية\n"
        "• /translate en نص — لغة محددة (ar en fr de es tr ru it)\n"
        "• /summarize نص — تلخيص\n"
        "• /fix نص — تصحيح إملائي ونحوي\n\n"
        "يمكنك الرد على أي رسالة بالأمر بدل كتابة النص.\n"
        "🎤 أرسل تسجيلًا صوتيًا وسأحوّله إلى نص."
    ),
    "tools": (
        "🛠 أدوات\n\n"
        "• /qr نص أو رابط — رمز QR\n"
        "• /short رابط — اختصار الرابط\n"
        "• /currency 100 USD EUR — تحويل العملات"
    ),
    "fun": (
        "🎲 تسلية\n\n"
        "• /joke — نكتة\n"
        "• /quote — حكمة\n"
        "• /dice — نرد\n"
        "• /game — لعبة عشوائية\n"
        "• /coin — ملك أو كتابة"
    ),
}

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤖 ذكاء اصطناعي", callback_data="menu:ai"),
            InlineKeyboardButton("🎨 الصور", callback_data="menu:image"),
        ],
        [
            InlineKeyboardButton("📝 أدوات النصوص", callback_data="menu:text"),
            InlineKeyboardButton("🛠 أدوات", callback_data="menu:tools"),
        ],
        [InlineKeyboardButton("🎲 تسلية", callback_data="menu:fun")],
        [
            InlineKeyboardButton("📢 القناة", url=TELEGRAM_LINK),
            InlineKeyboardButton("📸 إنستغرام", url=INSTAGRAM_LINK),
        ],
        [
            InlineKeyboardButton("🌐 موقعي", url=WEBSITE_LINK),
            InlineKeyboardButton("👨‍💻 المطوّر", callback_data="developer"),
        ],
    ])

def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="menu:main")]])

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats")],
        [InlineKeyboardButton("📣 طريقة الإذاعة", callback_data="admin_broadcast")],
    ])

def welcome_text(name: str) -> str:
    return (
        f"أهلًا {name} 👋\n\n"
        "أنا بوت المطوّر علي، أجمع لك الذكاء الاصطناعي والأدوات في مكان واحد.\n\n"
        "💬 اكتب لي أي سؤال مباشرة\n"
        "🎨 أو اكتب: ارسم + وصف الصورة\n"
        "🎤 أو أرسل تسجيلًا صوتيًا / 🖼 صورة\n\n"
        "اختر من القائمة:"
    )

# =========================
# الأوامر الأساسية
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    await update.message.reply_text(welcome_text(user.first_name), reply_markup=main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 أوامر البوت:\n\n"
        "🤖 /ask سؤالك — اسأل الذكاء الاصطناعي\n"
        "🧹 /reset — مسح ذاكرة المحادثة\n"
        "🎨 /image وصف — توليد صورة\n\n"
        "📝 /translate — ترجمة\n"
        "📝 /summarize — تلخيص\n"
        "✍️ /fix — تصحيح النص\n\n"
        "📱 /qr — رمز QR\n"
        "🔗 /short — اختصار رابط\n"
        "💱 /currency — تحويل العملات\n\n"
        "😄 /joke — نكتة\n"
        "💡 /quote — حكمة\n"
        "🎲 /dice — نرد\n"
        "🎯 /game — لعبة\n"
        "🪙 /coin — ملك أو كتابة\n\n"
        "📩 /suggest رسالتك — اقتراح أو شكوى\n"
        "ℹ️ /info — معلومات المطوّر\n\n"
        "🖼 أرسل صورة لتحليلها\n"
        "🎤 أرسل تسجيلًا صوتيًا لتحويله إلى نص"
    )
    if is_admin(update.effective_user.id):
        text += "\n\n👑 أوامر الإدارة:\n/admin /stats /broadcast رسالتك"
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
    await reply_long(update.message, answer, first=message)

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
# الدردشة المباشرة (بدون أوامر)
# =========================
DRAW_TRIGGERS = ("ارسم", "صمم", "ولّد صورة", "ولد صورة", "توليد صورة")

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    text = (update.message.text or "").strip()
    if not text:
        return

    for trigger in DRAW_TRIGGERS:
        if text.startswith(trigger):
            prompt = text[len(trigger):].strip()
            if prompt:
                await run_image_generation(update.message, context, prompt)
            else:
                await update.message.reply_text("🎨 اكتب وصف الصورة بعد الكلمة، مثل: ارسم قطة على القمر")
            return

    await update.message.chat.send_action(ChatAction.TYPING)
    answer = await ask_ai(user.id, text)
    await reply_long(update.message, answer)

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
# معالج الأزرار
# =========================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("menu:"):
        key = data.split(":", 1)[1]
        if key == "main":
            text, keyboard = welcome_text(query.from_user.first_name), main_keyboard()
        else:
            text, keyboard = MENUS.get(key, "قريبًا..."), back_keyboard()
        try:
            await query.edit_message_text(text, reply_markup=keyboard)
        except BadRequest:
            pass

    elif data == "developer":
        await query.message.reply_text(DEVELOPER_INFO)

    elif data == "regen":
        prompt = context.user_data.get("last_image_prompt")
        if not prompt:
            await query.message.reply_text("ما عندي وصف سابق. استخدم /image وصف الصورة.")
            return
        await run_image_generation(query.message, context, prompt)

    elif data.startswith("again:"):
        kind = data.split(":", 1)[1]
        if kind not in ("joke", "quote"):
            return
        await query.message.chat.send_action(ChatAction.TYPING)
        text = await get_fun_text(kind)
        try:
            await query.edit_message_text(text, reply_markup=again_keyboard(kind))
        except BadRequest:
            pass

    elif data.startswith("act:"):
        kind = data.split(":", 1)[1]
        text = query.message.text or ""
        if text.startswith(TRANSCRIPT_HEADER):
            text = text[len(TRANSCRIPT_HEADER):]
        text = text.strip()
        if kind not in ("summarize", "translate", "fix") or not text:
            return
        await query.message.chat.send_action(ChatAction.TYPING)
        result = await run_text_tool(kind, text)
        await reply_long(query.message, result)

    elif data == "admin_stats":
        if not is_admin(query.from_user.id):
            await query.message.reply_text("⛔ للمطوّر فقط.")
            return
        await query.message.reply_text(
            f"👥 المستخدمون: {get_user_count()}\n"
            f"📩 الاقتراحات: {get_suggestion_count()}"
        )

    elif data == "admin_broadcast":
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
# قائمة الأوامر الرسمية في تيليغرام
# =========================
USER_COMMANDS = [
    ("start", "القائمة الرئيسية"),
    ("help", "عرض كل الأوامر"),
    ("ask", "اسأل الذكاء الاصطناعي"),
    ("image", "توليد صورة من وصف"),
    ("translate", "ترجمة نص"),
    ("summarize", "تلخيص نص"),
    ("fix", "تصحيح إملائي ونحوي"),
    ("joke", "نكتة"),
    ("quote", "حكمة"),
    ("dice", "رمي النرد"),
    ("game", "لعبة عشوائية"),
    ("coin", "ملك أو كتابة"),
    ("qr", "إنشاء رمز QR"),
    ("short", "اختصار رابط"),
    ("currency", "تحويل العملات"),
    ("reset", "مسح ذاكرة المحادثة"),
    ("suggest", "إرسال اقتراح"),
    ("info", "معلومات المطوّر"),
]

async def post_init(application: Application):
    try:
        await application.bot.set_my_commands([BotCommand(c, d) for c, d in USER_COMMANDS])
        await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        if ADMIN_ID:
            admin_commands = USER_COMMANDS + [
                ("admin", "لوحة الإدارة"),
                ("stats", "إحصائيات البوت"),
                ("broadcast", "إرسال رسالة للجميع"),
            ]
            await application.bot.set_my_commands(
                [BotCommand(c, d) for c, d in admin_commands],
                scope=BotCommandScopeChat(chat_id=ADMIN_ID),
            )
    except Exception:
        logger.exception("Could not set bot commands")

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
        .post_init(post_init)
        .build()
    )

    commands = {
        "start": start,
        "help": help_command,
        "info": info_command,
        "ask": ask_command,
        "reset": reset_command,
        "suggest": suggest_command,
        "image": image_command,
        "translate": translate_command,
        "summarize": summarize_command,
        "fix": fix_command,
        "joke": joke_command,
        "quote": quote_command,
        "dice": dice_command,
        "game": game_command,
        "coin": coin_command,
        "qr": qr_command,
        "short": short_command,
        "currency": currency_command,
        "admin": admin_command,
        "stats": stats_command,
        "broadcast": broadcast_command,
    }
    for name, handler in commands.items():
        application.add_handler(CommandHandler(name, handler))

    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, photo_handler))
    application.add_handler(MessageHandler((filters.VOICE | filters.AUDIO) & filters.ChatType.PRIVATE, voice_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, chat_handler)
    )
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

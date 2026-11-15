import os
import sqlite3
import logging
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.request import HTTPXRequest

load_dotenv = lambda: None # یا از os.environ استفاده می‌کنیم
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# آدرس وب‌سایت هاست شما (بعد از ساخت در هاست، اینجا قرار می‌گیرد)
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") 

ADMIN_IDS = [6656918101] # آیدی خودتان

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = "bot_database.db"
app = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM mandatory_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    conn.close()

    not_joined_channels = []
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=channel["channel_id"], user_id=user_id)
            if member.status in ['left', 'kicked']:
                not_joined_channels.append(channel)
        except Exception:
            not_joined_channels.append(channel)
    return not_joined_channels

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, user.username))
    conn.commit()
    conn.close()

    args = context.args
    video_code = args[0] if args else None
    not_joined = await check_membership(user_id, context)

    if not_joined:
        keyboard = [[InlineKeyboardButton(f"📢 عضویت در {ch['title']}", url=ch['invite_link'])] for ch in not_joined]
        callback_data = f"verify_{video_code}" if video_code else "verify_none"
        keyboard.append([InlineKeyboardButton("✅ بررسی عضویت", callback_data=callback_data)])
        
        await update.message.reply_text(
            "سلام! 👋\n\nبرای دریافت و مشاهده این ویدیو، لطفاً ابتدا در کانال‌های زیر عضو شوید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        if video_code:
            await deliver_video(update, context, user_id, video_code)
        else:
            await update.message.reply_text("سلام به ربات تحویل ویدیو خوش آمدید! 🎉")

async def deliver_video(update_or_query, context, user_id, video_code):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM videos WHERE video_code = ? AND is_active = 1", (video_code,))
    video = cursor.fetchone()
    conn.close()

    message = update_or_query.message if hasattr(update_or_query, 'message') else update_or_query.callback_query.message

    if video:
        try:
            await context.bot.send_video(
                chat_id=user_id,
                video=video["file_id"],
                caption=f"🎬 {video['title']}\n\nاز اینکه در کانال‌های ما عضو هستید متشکریم! ❤️"
            )
        except Exception as e:
            logger.error(f"خطا در ارسال ویدیو: {e}")
            await message.reply_text("❌ خطا در ارسال ویدیو.")
    else:
        await message.reply_text("❌ ویدیوی مورد نظر یافت نشد.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("verify_"):
        video_code = data.split("_")[1]
        if video_code == "none": video_code = None
        not_joined = await check_membership(user_id, context)

        if not_joined:
            await query.edit_message_text("❌ شما هنوز در تمام کانال‌های لازم عضو نشده‌اید!")
        else:
            await query.message.delete()
            if video_code:
                await deliver_video(query, context, user_id, video_code)
            else:
                await query.message.reply_text("✅ عضویت شما تایید شد!")

# ساخت اپلیکیشن تلگرام بدون پولینگ
telegram_app = Application.builder().token(BOT_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CallbackQueryHandler(button_handler))

@app.route("/", methods=["GET"])
def home():
    return "Bot is running via Webhook!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    """دریافت آپدیت‌ها از تلگرام و پردازش آن‌ها"""
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    
    async def process():
        await telegram_app.initialize()
        await telegram_app.process_update(update)

    import asyncio
    asyncio.run(process())
    return "OK", 200

if __name__ == "__main__":
    # تنظیم خودکار وب‌هوک روی سرور
    async def setup_webhook():
        if WEBHOOK_URL:
            await telegram_app.bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
            logger.info(f"Webhook set to: {WEBHOOK_URL}/{BOT_TOKEN}")
            
    import asyncio
    asyncio.run(setup_webhook())
    
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port)

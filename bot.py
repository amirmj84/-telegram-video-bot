import os
import sqlite3
import logging
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# تنظیمات لاگینگ
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# خواندن اطلاعات از متغیرهای محیطی
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

admin_env = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(aid.strip()) for aid in admin_env.split(",") if aid.strip().isdigit()]

DB_NAME = "bot_database.db"
app = Flask(__name__)


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mandatory_channels (
            channel_id TEXT PRIMARY KEY,
            title TEXT,
            invite_link TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            video_code TEXT PRIMARY KEY,
            title TEXT,
            file_id TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()


init_db()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM mandatory_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    conn.close()

    not_joined_channels = []
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(
                chat_id=channel["channel_id"], user_id=user_id
            )
            if member.status in ["left", "kicked"]:
                not_joined_channels.append(channel)
        except Exception as e:
            logger.warning(f"خطا در بررسی عضویت کانال {channel['channel_id']}: {e}")
            not_joined_channels.append(channel)
    return not_joined_channels


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (user_id, user.username),
    )
    conn.commit()
    conn.close()

    args = context.args
    video_code = args[0] if args else None
    not_joined = await check_membership(user_id, context)

    if not_joined:
        keyboard = [
            [InlineKeyboardButton(f"📢 عضویت در {ch['title']}", url=ch["invite_link"])]
            for ch in not_joined
        ]
        callback_data = f"verify_{video_code}" if video_code else "verify_none"
        keyboard.append(
            [InlineKeyboardButton("✅ بررسی عضویت", callback_data=callback_data)]
        )

        await update.message.reply_text(
            "سلام! 👋\n\nبرای دریافت ویدیو، لطفاً ابتدا در کانال‌های زیر عضو شوید و سپس دکمه «بررسی عضویت» را بزنید:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        if video_code:
            await deliver_video(update, context, user_id, video_code)
        else:
            await update.message.reply_text("سلام! به ربات تحویل ویدیو خوش آمدید. 🎉")


async def deliver_video(update_or_query, context: ContextTypes.DEFAULT_TYPE, user_id: int, video_code: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM videos WHERE video_code = ? AND is_active = 1", (video_code,)
    )
    video = cursor.fetchone()
    conn.close()

    message = (
        update

_or_query.message
        if hasattr(update_or_query, "message") and update_or_query.message
        else update_or_query.callback_query.message
    )

    if video:
        try:
            await context.bot.send_video(
                chat_id=user_id,
                video=video["file_id"],
                caption=f"🎬 {video['title']}\n\nممنون از همراهی شما! ❤️",
            )
        except Exception as e:
            logger.error(f"خطا در ارسال ویدیو {video_code}: {e}")
            await message.reply_text("❌ خطا در ارسال ویدیو رخ داد.")
    else:
        await message.reply_text("❌ ویدیوی مورد نظر یافت نشد یا غیرفعال است.")


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ شما به پنل مدیریت دسترسی ندارید.")
        return

    context.user_data.pop("admin_action", None)

    keyboard = [
        [InlineKeyboardButton("➕ افزودن کانال اجباری", callback_data="add_channel")],
        [InlineKeyboardButton("📋 لیست کانال‌ها", callback_data="list_channels")],
        [InlineKeyboardButton("🎬 لیست ویدیوها", callback_data="list_videos")],
        [InlineKeyboardButton("❌ بستن منو", callback_data="close_admin")],
    ]
    await update.message.reply_text(
        "🛠 **پنل مدیریت ربات**\n\n"
        "• برای ثبت ویدیو جدید، کافیست **ویدیو** را با کپشن `کد | عنوان` بفرستید.\n"
        "• برای مدیریت کانال‌ها و دیدن لیست‌ها از دکمه‌های زیر استفاده کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("verify_"):
        video_code = data.split("_", 1)[1]
        if video_code == "none":
            video_code = None

        not_joined = await check_membership(user_id, context)
        if not_joined:
            keyboard = [
                [InlineKeyboardButton(f"📢 عضویت در {ch['title']}", url=ch["invite_link"])]
                for ch in not_joined
            ]
            callback_data = f"verify_{video_code}" if video_code else "verify_none"
            keyboard.append(
                [InlineKeyboardButton("✅ بررسی مجدد عضویت", callback_data=callback_data)]
            )
            await query.edit_message_text(
                "❌ هنوز در همه کانال‌های لازم عضو نشده‌اید. پس از عضویت دوباره بررسی کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            await query.message.delete()
            if video_code:
                await deliver_video(query, context, user_id, video_code)
            else:
                await query.message.reply_text("✅ عضویت شما تایید شد!")
        return

    if not is_admin(user_id):
        await query.edit_message_text("❌ دسترسی غیرمجاز.")
        return

    if data == "add_channel":
        context.user_data["admin_action"] = "awaiting_channel_info"
        await query.edit_message_text(
            "📢 **افزودن کانال عضویت اجباری**\n\n"
            "اطلاعات کانال را دقیقاً با فرمت زیر بفرستید:\n"
            "`-1001234567890 | نام کانال | https://t.me/channel_link`\n\n"
            "• آیدی عددی کانال معمولاً با `-100` شروع می‌شود.\n"
            "• ربات باید در کانال ادمین باشد.",
            parse_mode="Markdown",
        )

    elif data == "list_channels":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM mandatory_channels WHERE is_active = 1")
        channels = cursor.fetchall()
        conn.close()

        if not channels:
            text = "📭 هیچ کانال عضویت اجباری فعالی ثبت نشده است."
        else:
            lines = ["📢 **کانال‌های عضویت اجباری فعال:**\n"]
            for ch in channels:
                lines.append(f"• **{ch['title']}** (`{ch['channel_id']}`)\n  {ch['invite_link']}")
            text = "\n".join(lines)

        await query.edit_message_text(text, parse_mod

andler(MessageHandler(filters.VIDEO, handle_video_upload))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))


@app.route("/", methods=["GET"])
def home():
    return "Bot is running via Webhook!"


@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_data = request.get_json(force=True)
    update = Update.de_json(json_data, telegram_app.bot)

    async def run_update():
        await telegram_app.initialize()
        await telegram_app.process_update(update)

    try:
        asyncio.run(run_update())
    except Exception as e:
        logger.error(f"خطا در پردازش وب‌هوک: {e}")

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port)

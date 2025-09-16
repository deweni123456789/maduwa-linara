import os
import logging
import asyncio
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Please set BOT_TOKEN environment variable.")

MAX_FILE_SIZE = 45 * 1024 * 1024  # ~45MB safe limit for Telegram bots

# --- yt-dlp blocking function ---
def run_yt_dlp(url: str, output_path: str = "downloads/") -> str:
    os.makedirs(output_path, exist_ok=True)

    cookies_file = "cookies.txt"
    ydl_opts = {
        "outtmpl": f"{output_path}%(title)s.%(ext)s",
        "format": "mp4/best",
        "noplaylist": True,
        "quiet": True,
        "retries": 3,
        "socket_timeout": 30,  # ✅ timeout fix
    }
    if os.path.exists(cookies_file):
        ydl_opts["cookies"] = cookies_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)
        return filepath, info

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/deweni2")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Send me any YouTube, Facebook or Instagram link and I'll download it for you!",
        reply_markup=reply_markup
    )

# Handle links
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    status = await update.message.reply_text("⏳ Downloading... Please wait.")

    try:
        filepath, info = await asyncio.to_thread(run_yt_dlp, url)

        if not os.path.exists(filepath):
            await status.edit_text("⚠️ Could not find downloaded file.")
            return

        size = os.path.getsize(filepath)
        title = info.get("title", os.path.basename(filepath))

        if size <= MAX_FILE_SIZE:
            with open(filepath, "rb") as f:
                await update.message.reply_document(f, filename=os.path.basename(filepath))
            await status.delete()
        else:
            await status.edit_text(
                f"⚠️ File too large for Telegram upload.\n\n"
                f"Title: {title}\n"
                f"Size: {size/1024/1024:.2f} MB\n"
                f"Link: {info.get('webpage_url', url)}"
            )
    except Exception as e:
        await status.edit_text(f"❌ Download failed: {str(e)}")

# Main
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.run_polling()

if __name__ == "__main__":
    main()

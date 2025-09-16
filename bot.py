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

# --- yt-dlp blocking function ---
def run_yt_dlp(url: str, output_path: str = "downloads/") -> str:
    os.makedirs(output_path, exist_ok=True)

    cookies_file = "cookies.txt"
    ydl_opts = {
        "outtmpl": f"{output_path}%(title)s.%(ext)s",
        "format": "mp4/best",   # ✅ single stream (no ffmpeg)
        "noplaylist": True,
        "quiet": True,
    }
    if os.path.exists(cookies_file):
        ydl_opts["cookies"] = cookies_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

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
        # ✅ run yt-dlp in thread (avoid timeout in main loop)
        filepath = await asyncio.to_thread(run_yt_dlp, url)

        if os.path.exists(filepath):
            with open(filepath, "rb") as f:
                await update.message.reply_document(f, filename=os.path.basename(filepath))
            await status.delete()
        else:
            await status.edit_text("⚠️ Could not find downloaded file.")
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

#!/usr/bin/env python3
import os
import re
import asyncio
import logging
import tempfile
from pathlib import Path

from yt_dlp import YoutubeDL
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # Railway variable
if not BOT_TOKEN:
    raise RuntimeError("Please set BOT_TOKEN environment variable.")

# Limit max file size to attempt to send (bytes)
MAX_SEND_BYTES = 50 * 1024 * 1024  # 50 MB

# Regex to detect URLs
URL_RE = re.compile(r"https?://[^\s]+")

# Inline keyboard with developer button
DEV_BUTTON = InlineKeyboardMarkup.from_button(
    InlineKeyboardButton(text="👨‍💻 Developer", url="https://t.me/deweni2")
)

# yt-dlp options
YTDLP_OPTS_BASE = {
    "format": "bestvideo+bestaudio/best",
    "noplaylist": True,
    "outtmpl": "%(id)s.%(ext)s",
    "quiet": True,
    "no_warnings": True,
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a video link (YouTube, Facebook, Instagram, etc.) and I'll download it and return the file.\n\n"
        "Note: some sites require cookies or are restricted; if download fails I'll return useful error info.",
        reply_markup=DEV_BUTTON
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Usage:\n"
        "- Send a link (one per message) and I will try to download and send back.\n"
        "- If the file is big I may send as document or give the direct extract info.\n\n"
        "Developer: @deweni2",
        reply_markup=DEV_BUTTON
    )


def run_yt_dlp(url: str, outdir: str) -> dict:
    """Blocking function to run yt-dlp."""
    opts = YTDLP_OPTS_BASE.copy()
    opts["outtmpl"] = os.path.join(outdir, opts["outtmpl"])
    opts["retries"] = 2
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        return {"info": info, "file": filename}


async def handle_link_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = msg.text or msg.caption or ""
    urls = URL_RE.findall(text)

    if not urls:
        await msg.reply_text("I couldn't find a link in your message. Send a single URL.")
        return

    url = urls[0].strip()
    status_msg = await msg.reply_text("🔎 Preparing to download...\n" + url, reply_markup=DEV_BUTTON)

    with tempfile.TemporaryDirectory(prefix="tg_dl_") as tmpdir:
        try:
            info_and_file = await asyncio.to_thread(run_yt_dlp, url, tmpdir)
        except Exception as e:
            await status_msg.edit_text(
                f"❌ Download failed: {e}\n\n"
                "Possible reasons: private/restricted video, cookies required, or yt-dlp extractor issue.",
                reply_markup=DEV_BUTTON
            )
            return

        info = info_and_file.get("info")
        filepath = info_and_file.get("file")

        if not filepath or not os.path.exists(filepath):
            await status_msg.edit_text("❌ yt-dlp did not produce a file.", reply_markup=DEV_BUTTON)
            return

        title = info.get("title") or Path(filepath).name
        try:
            size = os.path.getsize(filepath)
        except OSError:
            size = None

        readable_size = f"{size/1024/1024:.2f} MB" if size else "unknown size"

        await status_msg.edit_text(
            f"⬇️ Downloaded: *{title}* ({readable_size}). Preparing to send...",
            parse_mode="Markdown",
            reply_markup=DEV_BUTTON
        )

        try:
            if size and size <= MAX_SEND_BYTES:
                with open(filepath, "rb") as f:
                    await msg.reply_video(f, caption=title, reply_markup=DEV_BUTTON)
                await status_msg.delete()
            else:
                with open(filepath, "rb") as f:
                    await msg.reply_document(f, filename=Path(filepath).name, caption=title, reply_markup=DEV_BUTTON)
                await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(
                "⚠️ I couldn't upload the file to Telegram (maybe it's too large).\n"
                f"Original link: {url}\nTitle: {title}\nSize: {readable_size}",
                reply_markup=DEV_BUTTON
            )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "I didn't understand that. Send a link and I'll try to download it.",
        reply_markup=DEV_BUTTON
    )


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link_message))
    app.add_handler(MessageHandler(filters.ALL, unknown))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()

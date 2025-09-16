#!/usr/bin/env python3
import os
import re
import asyncio
import logging
import tempfile
from pathlib import Path
from functools import partial

from yt_dlp import YoutubeDL
from telegram import __version__ as TG_VER

# python-telegram-bot v20 (async)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # required
if not BOT_TOKEN:
    raise RuntimeError("Please set BOT_TOKEN environment variable.")

# Limit max file size to attempt to send (bytes). Telegram has limits depending on bot plan;
# Using 50 MB as a conservative default. If the result is larger, the bot will attempt to send as document if allowed.
MAX_SEND_BYTES = 50 * 1024 * 1024  # 50 MB

# Regex to detect likely media URLs (simple)
URL_RE = re.compile(r"https?://[^\s]+")

# Inline keyboard with developer button (per your request)
DEV_BUTTON = InlineKeyboardMarkup.from_button(
    InlineKeyboardButton(text="👨‍💻 Developer", url="https://t.me/deweni2")
)

# --- yt-dlp options ---
YTDLP_OPTS_BASE = {
    "format": "bestvideo+bestaudio/best",
    "noplaylist": True,
    # Use a temp filename (we'll move/send afterwards)
    "outtmpl": "%(id)s.%(ext)s",
    # reduce verbose
    "quiet": True,
    "no_warnings": True,
    # writeinfojson could be useful (not necessary)
    # "writeinfojson": True,
    # avoid console progress since we run in thread
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
    """
    Blocking function to run yt-dlp and return info dict and filepath on success.
    This runs in a separate thread via asyncio.to_thread.
    """
    opts = YTDLP_OPTS_BASE.copy()
    opts["outtmpl"] = os.path.join(outdir, opts["outtmpl"])
    # Ensure retries so transient network errors less likely
    opts["retries"] = 2
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)  # blocking
        # If we downloaded, infer filename:
        # ydl.prepare_filename(info) uses outtmpl; but after download it's available
        filename = ydl.prepare_filename(info)
        return {"info": info, "file": filename}


async def handle_link_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    text = msg.text or msg.caption or ""
    urls = URL_RE.findall(text)

    if not urls:
        await msg.reply_text("I couldn't find a link in your message. Send a single URL.")
        return

    # For now process first url only
    url = urls[0].strip()
    logger.info("User %s requested download: %s", user.username or user.id, url)

    status_msg = await msg.reply_text("🔎 Preparing to download...\n" + url, reply_markup=DEV_BUTTON)

    # Create temporary directory to download into
    with tempfile.TemporaryDirectory(prefix="tg_dl_") as tmpdir:
        try:
            # Run yt-dlp in thread to avoid blocking event loop
            info_and_file = await asyncio.to_thread(run_yt_dlp, url, tmpdir)
        except Exception as e:
            logger.exception("yt-dlp failed for url %s", url)
            await status_msg.edit_text(
                f"❌ Download failed: {e}\n\n"
                "Possible reasons: private/restricted video, cookies required, or yt-dlp extractor issue.",
                reply_markup=DEV_BUTTON
            )
            return

        info = info_and_file.get("info")
        filepath = info_and_file.get("file")

        if not filepath or not os.path.exists(filepath):
            logger.warning("No file produced by yt-dlp for %s", url)
            await status_msg.edit_text(
                "❌ yt-dlp did not produce a downloadable file. Here is the info:\n"
                f"`{repr(info)}` (see logs).",
                reply_markup=DEV_BUTTON
            )
            return

        # Get human friendly title/size
        title = info.get("title") or Path(filepath).name
        try:
            size = os.path.getsize(filepath)
        except OSError:
            size = None

        readable_size = f"{size/1024/1024:.2f} MB" if size else "unknown size"

        await status_msg.edit_text(f"⬇️ Downloaded: *{title}* ({readable_size}). Preparing to send...",
                                  parse_mode="Markdown",
                                  reply_markup=DEV_BUTTON)

        # If file small enough, send as video (Telegram may transcode)
        try:
            if size and size <= MAX_SEND_BYTES:
                # Attempt to send as video first
                with open(filepath, "rb") as f:
                    await msg.reply_video(f, caption=title, reply_markup=DEV_BUTTON)
                await status_msg.delete()
                logger.info("Sent video %s to user %s", filepath, user.id)
                return
            else:
                # Too large (or unknown size): send as document
                with open(filepath, "rb") as f:
                    await msg.reply_document(f, filename=Path(filepath).name, caption=title, reply_markup=DEV_BUTTON)
                await status_msg.delete()
                logger.info("Sent document %s to user %s", filepath, user.id)
                return
        except Exception as e:
            # If sending fails (e.g., file too big for Telegram), provide fallback: send info and direct URL if available
            logger.exception("Failed to send file to Telegram: %s", e)
            # Try to send a small summary and the original URL
            meta = {
                "title": info.get("title"),
                "uploader": info.get("uploader"),
                "webpage_url": info.get("webpage_url") or url,
                "filesize": size
            }
            await status_msg.edit_text(
                "⚠️ I couldn't upload the file to Telegram (maybe it's too large for the bot). "
                "I'll send you the original link and metadata so you can download it yourself.\n\n"
                f"Title: {meta['title']}\n"
                f"Uploader: {meta['uploader']}\n"
                f"Original: {meta['webpage_url']}\n"
                f"Size (detected): {readable_size}",
                reply_markup=DEV_BUTTON
            )
            return


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("I didn't understand that. Send a link and I'll try to download it.", reply_markup=DEV_BUTTON)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    # Accept text messages that contain a URL
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link_message))
    app.add_handler(MessageHandler(filters.ALL, unknown))  # fallback

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()

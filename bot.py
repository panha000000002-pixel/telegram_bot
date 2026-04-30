import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters


def get_bot_token():
    env_token = os.getenv("BOT_TOKEN")
    if env_token:
        return env_token

    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "BOT_TOKEN":
            return value.strip().strip('"').strip("'")

    return None


BOT_TOKEN = get_bot_token()
COOKIES_FILE = Path(__file__).with_name("cookies.txt")
URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
TRAILING_URL_CHARS = ".,!?;:)]}'\""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return

    await update.message.reply_text(
        "Hello! I am your Telegram bot.\n"
        "Send one or many TikTok video links and I will download them one by one."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return

    await update.message.reply_text(
        "You can use these commands:\n"
        "/start - Start the bot\n"
        "/help - Show help\n\n"
        "Send text with one or many TikTok links and I will send back each video."
    )


def is_tiktok_url(url):
    parsed_url = urlparse(url)
    host = parsed_url.netloc.lower()
    return host == "tiktok.com" or host.endswith(".tiktok.com")


def extract_tiktok_links(text):
    links = []
    seen = set()

    for match in URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(TRAILING_URL_CHARS)
        if is_tiktok_url(url) and url not in seen:
            links.append(url)
            seen.add(url)

    return links


def has_valid_cookies_file():
    if not COOKIES_FILE.exists() or COOKIES_FILE.stat().st_size == 0:
        return False

    try:
        first_lines = COOKIES_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[:5]
    except OSError:
        return False

    return any("Netscape HTTP Cookie File" in line for line in first_lines)


def download_tiktok_video(url):
    from yt_dlp import YoutubeDL

    download_dir = Path(tempfile.mkdtemp(prefix="telegram_tiktok_"))
    output_template = str(download_dir / "%(id)s.%(ext)s")

    options = {
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
    }

    if has_valid_cookies_file():
        options["cookiefile"] = str(COOKIES_FILE)

    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        video_path = Path(downloader.prepare_filename(info))

    if not video_path.exists():
        downloaded_files = [path for path in download_dir.iterdir() if path.is_file()]
        if not downloaded_files:
            raise RuntimeError("Video download finished but no file was created.")
        video_path = downloaded_files[0]

    return download_dir, video_path


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.text is None:
        return

    user_text = update.message.text.strip()
    tiktok_links = extract_tiktok_links(user_text)

    if not tiktok_links:
        await update.message.reply_text("No TikTok links found.")
        return

    total_links = len(tiktok_links)
    status_message = await update.message.reply_text(
        f"Found {total_links} TikTok link(s). Downloading 1/{total_links}..."
    )

    for index, link in enumerate(tiktok_links, start=1):
        download_dir = None

        try:
            await status_message.edit_text(f"Downloading {index}/{total_links}...")
            download_dir, video_path = await asyncio.to_thread(download_tiktok_video, link)

            with video_path.open("rb") as video:
                await update.message.reply_video(
                    video=video,
                    caption=link,
                )
        except Exception as error:
            error_text = str(error)
            if "Log in for access" in error_text or "cookies" in error_text.lower():
                await update.message.reply_text(
                    f"Could not download {index}/{total_links}: TikTok requires login for this video. "
                    "Add a valid cookies.txt file beside bot.py, then try again.\n"
                    f"{link}"
                )
            else:
                await update.message.reply_text(
                    f"Could not download {index}/{total_links}: {error}\n{link}"
                )
        finally:
            if download_dir is not None:
                shutil.rmtree(download_dir, ignore_errors=True)

    await status_message.delete()


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add BOT_TOKEN=your_token_here to .env")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()

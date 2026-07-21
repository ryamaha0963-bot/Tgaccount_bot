import asyncio
import logging
from pyrogram import Client
from config import Config
from database import init_db
from handlers import BotHandlers
from web import app, set_bot, run_web
import threading

logging.basicConfig(level=logging.INFO)

async def main():
    await init_db()
    app_bot = Client(
        "account_bot",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN
    )
    BotHandlers(app_bot)
    set_bot(app_bot)  # For webhook to send messages

    # Start Flask web server in a separate thread
    loop = asyncio.get_running_loop()
    threading.Thread(target=run_web, args=(loop,), daemon=True).start()

    print("🤖 Bot is running... Web server on port 5000")
    await app_bot.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())

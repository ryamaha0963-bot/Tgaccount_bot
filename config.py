import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_ID = int(os.getenv("ADMIN_ID"))

    # NowPayments
    NOWPAYMENTS_API_KEY = os.getenv("NOWPAYMENTS_API_KEY")
    NOWPAYMENTS_IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET")

    # Webhook URL (Railway gives you a public URL)
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-app.railway.app")  # change later

import aiohttp
import hashlib
import hmac
import json
from config import Config

API_KEY = Config.NOWPAYMENTS_API_KEY
IPN_SECRET = Config.NOWPAYMENTS_IPN_SECRET

BASE_URL = "https://api.nowpayments.io/v1"

async def create_payment(amount, currency="usd", order_id=None):
    """Create a payment request (invoice)"""
    url = f"{BASE_URL}/payment"
    payload = {
        "price_amount": amount,
        "price_currency": currency,
        "pay_currency": "btc",  # or usdt, etc.
        "order_id": order_id,
        "order_description": "Account purchase",
        "ipn_callback_url": Config.WEBHOOK_URL + "/webhook/nowpayments",
        "success_url": Config.WEBHOOK_URL + "/success",
        "cancel_url": Config.WEBHOOK_URL + "/cancel"
    }
    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/json"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            return data

async def check_payment_status(payment_id):
    """Check status of a payment"""
    url = f"{BASE_URL}/payment/{payment_id}"
    headers = {"x-api-key": API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            return data

def verify_webhook_signature(payload, signature):
    """Verify IPN signature using HMAC-SHA256"""
    computed = hmac.new(
        IPN_SECRET.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)

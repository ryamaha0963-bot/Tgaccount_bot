from flask import Flask, request, jsonify
import logging
import json
from nowpayments import verify_webhook_signature, IPN_SECRET   # <-- YEH IMPORT ADD KIYA
from database import get_order_by_payment_id, update_order_status_by_payment_id, get_account_by_id, mark_account_sold
import asyncio
import threading

app = Flask(__name__)
logger = logging.getLogger(__name__)

# We'll set the bot instance later (circular import)
_bot = None

def set_bot(bot_client):
    global _bot
    _bot = bot_client

async def deliver_account(order):
    """Deliver the account to user"""
    acc_id = order['account_id']
    account = await get_account_by_id(acc_id)
    if not account or account['is_sold']:
        return False
    await mark_account_sold(acc_id, order['user_id'])
    creds = (
        f"🎉 **Account #{acc_id} delivered!**\n"
        f"Phone: `{account['phone']}`\n"
        f"Password: `{account['password'] or 'N/A'}`\n"
        f"OTP: `{account['otp'] or 'N/A'}`\n"
        f"Description: {account['description']}\n"
        "⚠️ Change credentials immediately!"
    )
    try:
        await _bot.send_message(order['user_id'], creds)
        return True
    except:
        return False

@app.route('/webhook/nowpayments', methods=['POST'])
def nowpayments_webhook():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    # Verify signature (optional but recommended)
    signature = request.headers.get('x-nowpayments-sig')
    if signature and IPN_SECRET:
        # verify payload
        payload = request.get_data(as_text=True)
        if not verify_webhook_signature(payload, signature):
            return jsonify({"error": "Invalid signature"}), 401

    # Process payment status
    payment_id = data.get('payment_id')
    status = data.get('payment_status')  # 'finished', 'failed', etc.
    txid = data.get('pay_amount')  # or data.get('tx_id')

    if not payment_id:
        return jsonify({"error": "No payment_id"}), 400

    # Update order status if payment is complete
    if status in ['finished', 'confirmed']:
        # Update order status to 'paid'
        asyncio.run_coroutine_threadsafe(
            update_order_status_by_payment_id(payment_id, 'paid', txid),
            loop
        )
        # Now deliver the account
        # We need to run in same event loop as bot
        # Since Flask is in a separate thread, we need to schedule on bot's loop.
        # We'll use a global loop variable set in main.py
        # For now, we'll do it inside a thread-safe way
        # We'll use asyncio.run_coroutine_threadsafe with the bot's loop
        async def deliver():
            order = await get_order_by_payment_id(payment_id)
            if order and order['status'] == 'paid':
                await deliver_account(order)
        asyncio.run_coroutine_threadsafe(deliver(), loop)
    elif status == 'failed':
        asyncio.run_coroutine_threadsafe(
            update_order_status_by_payment_id(payment_id, 'failed'),
            loop
        )

    return jsonify({"status": "ok"}), 200

# For simplicity, we'll store the event loop
loop = None

def run_web(loop_):
    global loop
    loop = loop_
    app.run(host='0.0.0.0', port=5000)

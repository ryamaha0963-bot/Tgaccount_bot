from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
import logging
import asyncio
from database import *
from config import Config
from nowpayments import create_payment
import json

logger = logging.getLogger(__name__)

# Global bot instance reference for sending OTP to buyer
_bot_instance = None

class BotHandlers:
    def __init__(self, app: Client):
        global _bot_instance
        _bot_instance = app
        self.app = app

        @app.on_message(filters.command("start"))
        async def start_cmd(client, message):
            await message.reply(
                "👋 **Welcome to Account Shop!**\n\n"
                "🛍️ Use /shop to browse available accounts.\n"
                "👤 Use /myorders to see your purchase history.\n"
                "🔐 Admin commands via /admin (admins only).\n\n"
                "💳 Payments are automatic via Crypto (BTC, USDT, etc.).\n"
                "After payment, account details will be sent instantly!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 View Shop", callback_data="view_shop")],
                    [InlineKeyboardButton("📋 My Orders", callback_data="my_orders")]
                ])
            )

        @app.on_callback_query(filters.regex(r"^view_shop$"))
        async def view_shop_cb(client, callback):
            await shop_cmd(client, callback.message)
            await callback.answer()

        @app.on_callback_query(filters.regex(r"^my_orders$"))
        async def myorders_cb(client, callback):
            await myorders_cmd(client, callback.message)
            await callback.answer()

        @app.on_message(filters.command("shop"))
        async def shop_cmd(client, message):
            accounts = await get_available_accounts()
            if not accounts:
                await message.reply("❌ No accounts available right now.")
                return

            text = "🛍️ **Available Accounts**\n\n"
            buttons = []
            for acc in accounts:
                phone = acc['phone']
                masked = phone[:4] + "****" + phone[-4:] if len(phone) > 8 else "****"
                desc = acc['description'] or "No description"
                text += f"🔹 **ID:** `{acc['id']}` | {masked}\n   💰 {acc['price']} ₹ | 📝 {desc[:30]}\n"
                buttons.append([InlineKeyboardButton(
                    f"🛒 Buy {masked} - {acc['price']}₹",
                    callback_data=f"buy_{acc['id']}"
                )])
            await message.reply(text, reply_markup=InlineKeyboardMarkup(buttons))

        @app.on_callback_query(filters.regex(r"^buy_(\d+)$"))
        async def buy_callback(client, callback: CallbackQuery):
            acc_id = int(callback.matches[0].group(1))
            account = await get_account_by_id(acc_id)
            if not account or account['is_sold']:
                await callback.answer("❌ This account is already sold!", show_alert=True)
                return

            try:
                payment_data = await create_payment(amount=account['price'], currency="usd", order_id=f"acc_{acc_id}")
                if 'payment_id' not in payment_data:
                    await callback.answer("Payment gateway error. Try again later.", show_alert=True)
                    return
                payment_id = payment_data['payment_id']
                invoice_url = payment_data['invoice_url'] if 'invoice_url' in payment_data else payment_data.get('payment_url')
            except Exception as e:
                await callback.answer(f"Error: {str(e)}", show_alert=True)
                return

            order_id = await create_order_with_payment(callback.from_user.id, acc_id, "crypto", payment_id)

            text = (
                f"💳 **Complete your purchase**\n\n"
                f"📱 **Account #{account['id']}**\n"
                f"Phone: `{account['phone']}`\n"
                f"Price: **{account['price']} ₹**\n"
                f"Description: {account['description'] or 'N/A'}\n\n"
                f"🔗 **Pay with Crypto:**\n"
                f"Click the button below to complete payment.\n"
                f"Payment will be confirmed automatically within minutes.\n\n"
                f"📌 **Order ID:** `{order_id}`\n"
                f"🆔 **Payment ID:** `{payment_id}`"
            )
            buttons = [
                [InlineKeyboardButton("💳 Pay Now", url=invoice_url)],
                [InlineKeyboardButton("✅ I've Paid (Check Status)", callback_data=f"check_{order_id}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_buy")]
            ]
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
            await callback.answer("Payment invoice created!")

        @app.on_callback_query(filters.regex(r"^check_(\d+)$"))
        async def check_order_callback(client, callback: CallbackQuery):
            order_id = int(callback.matches[0].group(1))
            order = await get_order(order_id)
            if not order:
                await callback.answer("Order not found.", show_alert=True)
                return
            if order['status'] == 'paid':
                await callback.answer("✅ Payment confirmed! Account will be delivered shortly.", show_alert=True)
            elif order['status'] == 'confirmed':
                await callback.answer("✅ Order already delivered!", show_alert=True)
            else:
                await callback.answer(f"Status: {order['status']}. Please wait or contact support.", show_alert=True)

        @app.on_callback_query(filters.regex(r"^cancel_buy$"))
        async def cancel_buy(client, callback):
            await callback.message.edit_text("❌ Purchase cancelled.")
            await callback.answer()

        # ---------- Admin Commands ----------
        @app.on_message(filters.command("admin") & filters.user(Config.ADMIN_ID))
        async def admin_cmd(client, message):
            await message.reply(
                "🔧 **Admin Panel**\n\n"
                "/addaccount <phone> <password> <otp> <session_string> <price> <description>\n"
                "/updateotp <account_id> <new_otp>\n"
                "/orders - View all orders\n"
                "/confirm <order_id> <txid> - Manual confirm (if needed)"
            )

        @app.on_message(filters.command("addaccount") & filters.user(Config.ADMIN_ID))
        async def add_account_cmd(client, message):
            parts = message.text.split(maxsplit=6)
            if len(parts) < 7:
                await message.reply("Usage: /addaccount <phone> <password> <otp> <session_string> <price> <description>")
                return
            phone, password, otp, session_str, price, desc = parts[1], parts[2], parts[3], parts[4], int(parts[5]), parts[6]
            acc_id = await add_account(phone, password, otp, session_str, price, desc)
            await message.reply(f"✅ Account #{acc_id} added successfully with session string!")

        @app.on_message(filters.command("updateotp") & filters.user(Config.ADMIN_ID))
        async def update_otp_cmd(client, message):
            parts = message.text.split()
            if len(parts) != 3:
                await message.reply("Usage: /updateotp <account_id> <new_otp>")
                return
            acc_id, new_otp = int(parts[1]), parts[2]
            await update_account_otp(acc_id, new_otp)
            await message.reply(f"✅ OTP for account #{acc_id} updated to `{new_otp}`")

        @app.on_message(filters.command("orders") & filters.user(Config.ADMIN_ID))
        async def orders_cmd(client, message):
            orders = await get_all_orders()
            if not orders:
                await message.reply("No orders yet.")
                return
            text = "📦 **All Orders**\n\n"
            for o in orders:
                status_emoji = "✅" if o['status'] == 'paid' else "⏳" if o['status'] == 'pending' else "❌"
                text += f"{status_emoji} #{o['id']} | Acc #{o['account_id']} | User {o['user_id']} | {o['status']}\n"
            await message.reply(text)

        # ---------- UPDATED CONFIRM COMMAND ----------
        @app.on_message(filters.command("confirm") & filters.user(Config.ADMIN_ID))
        async def confirm_cmd(client, message):
            parts = message.text.split()
            if len(parts) != 3:
                await message.reply("Usage: /confirm <order_id> <txid_or_proof>")
                return
            order_id, txid = int(parts[1]), parts[2]
            order = await get_order(order_id)
            if not order:
                await message.reply("Order not found.")
                return
            if order['status'] != 'pending':
                await message.reply("Order already processed.")
                return
            acc_id = order['account_id']
            account = await get_account_by_id(acc_id)
            if not account or account['is_sold']:
                await message.reply("Account already sold.")
                return

            # Mark account sold
            await mark_account_sold(acc_id, order['user_id'])
            await update_order_status(order_id, "confirmed", txid)

            # 1. Send Phone + Password + Session (Just in case)
            creds = (
                f"🎉 **Account #{acc_id} delivered!**\n"
                f"Phone: `{account['phone']}`\n"
                f"Password: `{account['password'] or 'N/A'}`\n"
                f"OTP Backup: `{account['otp'] or 'N/A'}`\n"
                f"Session String: `{account['session_string'] or 'N/A'}`\n\n"
                "📌 **How to Login:**\n"
                "1. Open Telegram official app.\n"
                "2. Enter the phone number above.\n"
                "3. Wait for the OTP. **I will forward it here automatically!**"
            )
            try:
                await client.send_message(order['user_id'], creds)
            except Exception as e:
                await message.reply(f"⚠️ Could not deliver initial message: {e}")

            # 2. 🔥 START THE OTP FORWARDER (Main Magic)
            # This runs in the background and catches the login code from Telegram's service account.
            asyncio.create_task(forward_telegram_otp(acc_id, order['user_id'], account['session_string']))

            await message.reply(f"✅ Order #{order_id} confirmed. OTP Forwarder is now active for 10 minutes.")

        @app.on_message(filters.command("myorders"))
        async def myorders_cmd(client, message):
            orders = await get_orders_by_user(message.from_user.id)
            if not orders:
                await message.reply("You have no orders.")
                return
            text = "📋 **Your Orders**\n\n"
            for o in orders:
                status_emoji = "✅" if o['status'] == 'paid' else "⏳" if o['status'] == 'pending' else "❌"
                text += f"{status_emoji} #{o['id']} | Acc #{o['account_id']} | {o['status']}\n"
            await message.reply(text)


# ---------- OTP FORWARDER FUNCTION (Heart of the feature) ----------
async def forward_telegram_otp(account_id: int, buyer_id: int, session_string: str):
    """
    Logs into the sold account using its session string,
    waits for the 'Login Code' message from Telegram service (ID: 777000),
    and forwards it to the buyer.
    """
    if not session_string or session_string == "N/A":
        logger.warning(f"No session string for account {account_id}. Cannot forward OTP.")
        return

    logger.info(f"Starting OTP listener for account {account_id} -> Buyer {buyer_id}")

    try:
        # Create a temporary user client using the account's session string
        async with Client(
            f"otp_listener_{account_id}",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=session_string,
            in_memory=True  # Don't save file, run in RAM
        ) as user_app:

            # Define the handler that catches the OTP
            @user_app.on_message(filters.text & filters.user(777000))  # 777000 = Telegram Service Account
            async def otp_handler(client, message):
                text = message.text or ""
                # Check if the message contains the login code
                if "login code" in text.lower() or "code" in text.lower():
                    logger.info(f"OTP received for account {account_id}. Forwarding to buyer {buyer_id}.")
                    
                    # Send the OTP to the buyer
                    await _bot_instance.send_message(
                        buyer_id,
                        f"🔑 **Login Code Received!**\n\n"
                        f"`{text}`\n\n"
                        f"Please enter this code in the Telegram app to login."
                    )
                    
                    # Stop listening after forwarding (so it doesn't spam if multiple codes arrive)
                    await client.stop()

            # Start the client and wait for messages
            await user_app.start()
            
            # Wait for up to 10 minutes (600 seconds) for the OTP to arrive
            await asyncio.sleep(600)
            
            # If we reach here, timeout occurred
            await _bot_instance.send_message(
                buyer_id,
                "⏰ **Timeout:** No login attempt detected in the last 10 minutes. "
                "If you tried to login, please contact support or try buying again."
            )
            logger.info(f"OTP listener timed out for account {account_id}")

    except Exception as e:
        logger.error(f"OTP Listener crashed for account {account_id}: {e}")
        try:
            await _bot_instance.send_message(
                buyer_id,
                f"❌ **Error in OTP forwarding:** `{str(e)}`\n"
                "Please use the Session String provided earlier to login via Pyrogram/Telethon, "
                "or contact support."
            )
        except:
            pass

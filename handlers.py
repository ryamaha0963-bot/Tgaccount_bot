from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
import logging
import asyncio
import json
from database import *
from config import Config
from nowpayments import create_payment

logger = logging.getLogger(__name__)

# Global reference for bot (used in OTP forwarder)
_bot_instance = None

class BotHandlers:
    def __init__(self, app: Client):
        global _bot_instance
        _bot_instance = app
        self.app = app

        # ---------- START COMMAND ----------
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

        # ---------- CALLBACKS FOR VIEW SHOP & MY ORDERS ----------
        @app.on_callback_query(filters.regex(r"^view_shop$"))
        async def view_shop_cb(client, callback):
            await shop_cmd(client, callback.message)
            await callback.answer()

        @app.on_callback_query(filters.regex(r"^my_orders$"))
        async def myorders_cb(client, callback):
            await myorders_cmd(client, callback.message)
            await callback.answer()

        # ---------- SHOP COMMAND ----------
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

        # ---------- BUY CALLBACK (THE MAIN ONE) ----------
        @app.on_callback_query(filters.regex(r"^buy_(\d+)$"))
        async def buy_callback(client, callback: CallbackQuery):
            acc_id = int(callback.matches[0].group(1))
            logger.info(f"User {callback.from_user.id} clicked buy for account {acc_id}")

            # Fetch account
            account = await get_account_by_id(acc_id)
            if not account:
                await callback.answer("❌ Account not found!", show_alert=True)
                return
            if account['is_sold']:
                await callback.answer("❌ This account is already sold!", show_alert=True)
                return

            # Try to create payment with NowPayments
            try:
                payment_data = await create_payment(
                    amount=account['price'],
                    currency="usd",
                    order_id=f"acc_{acc_id}_{callback.from_user.id}"
                )
                if 'payment_id' in payment_data:
                    payment_id = payment_data['payment_id']
                    invoice_url = payment_data.get('invoice_url') or payment_data.get('payment_url')
                else:
                    # If payment gateway fails, we'll use manual mode
                    raise Exception("No payment_id in response")
            except Exception as e:
                logger.warning(f"NowPayments failed, falling back to manual payment: {e}")
                # Create a dummy payment_id for manual order
                payment_id = f"manual_{acc_id}_{callback.from_user.id}_{int(asyncio.get_event_loop().time())}"
                invoice_url = None
                # We'll show manual payment instructions

            # Create order with payment_id (dummy or real)
            order_id = await create_order_with_payment(
                callback.from_user.id,
                acc_id,
                "crypto" if invoice_url else "manual",
                payment_id
            )

            # Prepare response message
            text = (
                f"💳 **Order #{order_id} created!**\n\n"
                f"📱 **Account #{account['id']}**\n"
                f"Phone: `{account['phone']}`\n"
                f"Price: **{account['price']} ₹**\n"
                f"Description: {account['description'] or 'N/A'}\n"
            )

            buttons = []

            if invoice_url:
                # Automatic payment available
                text += f"\n🔗 **Pay with Crypto:**\nClick below to complete payment."
                buttons.append([InlineKeyboardButton("💳 Pay Now", url=invoice_url)])
                buttons.append([InlineKeyboardButton("✅ I've Paid (Check Status)", callback_data=f"check_{order_id}")])
            else:
                # Manual payment fallback
                text += (
                    f"\n⚠️ **Automatic payment is temporarily unavailable.**\n"
                    f"Please pay **{account['price']} ₹** to this UPI: `admin@upi` (or contact admin).\n"
                    f"After payment, send screenshot to admin, or use the 'Confirm' button below.\n"
                    f"Admin will manually confirm your order."
                )
                # We can add a button to notify admin (optional)
                buttons.append([InlineKeyboardButton("✅ I have paid (Notify Admin)", callback_data=f"notify_admin_{order_id}")])

            buttons.append([InlineKeyboardButton("❌ Cancel Order", callback_data=f"cancel_order_{order_id}")])

            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
            await callback.answer("Order created! Check the instructions.")


        # ---------- CHECK ORDER STATUS ----------
        @app.on_callback_query(filters.regex(r"^check_(\d+)$"))
        async def check_order_callback(client, callback: CallbackQuery):
            order_id = int(callback.matches[0].group(1))
            order = await get_order(order_id)
            if not order:
                await callback.answer("Order not found.", show_alert=True)
                return
            if order['status'] == 'paid' or order['status'] == 'confirmed':
                await callback.answer("✅ Payment confirmed! Account delivered soon.", show_alert=True)
            else:
                await callback.answer(f"Status: {order['status']}. Please wait or contact support.", show_alert=True)

        # ---------- CANCEL ORDER ----------
        @app.on_callback_query(filters.regex(r"^cancel_order_(\d+)$"))
        async def cancel_order_callback(client, callback: CallbackQuery):
            order_id = int(callback.matches[0].group(1))
            # Optionally update order status to 'cancelled'
            await update_order_status(order_id, "cancelled")
            await callback.message.edit_text("❌ Order cancelled.")
            await callback.answer("Order cancelled.")

        # ---------- NOTIFY ADMIN (Manual Payment) ----------
        @app.on_callback_query(filters.regex(r"^notify_admin_(\d+)$"))
        async def notify_admin_callback(client, callback: CallbackQuery):
            order_id = int(callback.matches[0].group(1))
            order = await get_order(order_id)
            if not order:
                await callback.answer("Order not found.", show_alert=True)
                return
            # Send message to admin
            admin_id = Config.ADMIN_ID
            if admin_id:
                try:
                    await client.send_message(
                        admin_id,
                        f"📢 **User {callback.from_user.id} claims payment for Order #{order_id}**\n"
                        f"Account: {order['account_id']}\n"
                        f"Please verify and /confirm {order_id} <txid>"
                    )
                    await callback.answer("Admin notified! Please wait for confirmation.", show_alert=True)
                except Exception as e:
                    logger.error(f"Failed to notify admin: {e}")
                    await callback.answer("Failed to notify admin. Contact support directly.", show_alert=True)
            else:
                await callback.answer("Admin ID not set. Please contact support.", show_alert=True)

        # ---------- ADMIN COMMANDS ----------
        @app.on_message(filters.command("admin") & filters.user(Config.ADMIN_ID))
        async def admin_cmd(client, message):
            await message.reply(
                "🔧 **Admin Panel**\n\n"
                "/addaccount <phone> <password> <otp> <session_string> <price> <description>\n"
                "/updateotp <account_id> <new_otp>\n"
                "/orders - View all orders\n"
                "/confirm <order_id> <txid_or_proof> - Manual confirm\n"
                "/gensession <phone> - Generate session string"
            )

        # ---------- ADD ACCOUNT ----------
        @app.on_message(filters.command("addaccount") & filters.user(Config.ADMIN_ID))
        async def add_account_cmd(client, message):
            parts = message.text.split(maxsplit=6)
            if len(parts) < 7:
                await message.reply("Usage: /addaccount <phone> <password> <otp> <session_string> <price> <description>")
                return
            phone, password, otp, session_str, price, desc = parts[1], parts[2], parts[3], parts[4], int(parts[5]), parts[6]
            acc_id = await add_account(phone, password, otp, session_str, price, desc)
            await message.reply(f"✅ Account #{acc_id} added successfully with session string!")

        # ---------- UPDATE OTP ----------
        @app.on_message(filters.command("updateotp") & filters.user(Config.ADMIN_ID))
        async def update_otp_cmd(client, message):
            parts = message.text.split()
            if len(parts) != 3:
                await message.reply("Usage: /updateotp <account_id> <new_otp>")
                return
            acc_id, new_otp = int(parts[1]), parts[2]
            await update_account_otp(acc_id, new_otp)
            await message.reply(f"✅ OTP for account #{acc_id} updated to `{new_otp}`")

        # ---------- ORDERS LIST ----------
        @app.on_message(filters.command("orders") & filters.user(Config.ADMIN_ID))
        async def orders_cmd(client, message):
            orders = await get_all_orders()
            if not orders:
                await message.reply("No orders yet.")
                return
            text = "📦 **All Orders**\n\n"
            for o in orders:
                status_emoji = "✅" if o['status'] == 'paid' or o['status'] == 'confirmed' else "⏳" if o['status'] == 'pending' else "❌"
                text += f"{status_emoji} #{o['id']} | Acc #{o['account_id']} | User {o['user_id']} | {o['status']}\n"
            await message.reply(text)

        # ---------- CONFIRM ORDER (Manual Delivery) ----------
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
            if order['status'] == 'confirmed' or order['status'] == 'paid':
                await message.reply("Order already processed.")
                return
            acc_id = order['account_id']
            account = await get_account_by_id(acc_id)
            if not account or account['is_sold']:
                await message.reply("Account already sold or not found.")
                return

            # Mark account sold, update order
            await mark_account_sold(acc_id, order['user_id'])
            await update_order_status(order_id, "confirmed", txid)

            # Send delivery message with session string
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

            # Start OTP forwarder
            if account['session_string'] and account['session_string'] != "N/A":
                asyncio.create_task(forward_telegram_otp(acc_id, order['user_id'], account['session_string']))
                await message.reply(f"✅ Order #{order_id} confirmed. OTP Forwarder active for 10 minutes.")
            else:
                await message.reply(f"✅ Order #{order_id} confirmed. No session string available, OTP forwarding disabled.")

        # ---------- MY ORDERS ----------
        @app.on_message(filters.command("myorders"))
        async def myorders_cmd(client, message):
            orders = await get_orders_by_user(message.from_user.id)
            if not orders:
                await message.reply("You have no orders.")
                return
            text = "📋 **Your Orders**\n\n"
            for o in orders:
                status_emoji = "✅" if o['status'] == 'paid' or o['status'] == 'confirmed' else "⏳" if o['status'] == 'pending' else "❌"
                text += f"{status_emoji} #{o['id']} | Acc #{o['account_id']} | {o['status']}\n"
            await message.reply(text)

        # ---------- GENERATE SESSION (ADMIN) ----------
        # Temporary storage for session generation
        self.pending_sessions = {}

        @app.on_message(filters.command("gensession") & filters.user(Config.ADMIN_ID))
        async def gen_session_cmd(client, message):
            parts = message.text.split()
            if len(parts) != 2:
                await message.reply("Usage: `/gensession +911234567890`")
                return
            phone = parts[1]

            if message.from_user.id in self.pending_sessions:
                await message.reply("⏳ Already generating a session. Complete or wait.")
                return

            temp_client = Client(
                f"temp_{message.from_user.id}",
                api_id=Config.API_ID,
                api_hash=Config.API_HASH,
                in_memory=True
            )
            await message.reply(f"📲 Sending OTP to `{phone}`...")
            try:
                await temp_client.connect()
                sent_code = await temp_client.send_code(phone)
                self.pending_sessions[message.from_user.id] = {
                    "client": temp_client,
                    "phone": phone,
                    "phone_code_hash": sent_code.phone_code_hash,
                    "step": "awaiting_otp"
                }
                await message.reply(
                    f"✅ OTP sent to `{phone}`!\n\n"
                    "Send OTP using:\n"
                    f"`/otp {phone} <code>`"
                )
            except Exception as e:
                await message.reply(f"❌ Failed to send OTP: `{str(e)}`")
                if temp_client.is_connected:
                    await temp_client.disconnect()

        @app.on_message(filters.command("otp") & filters.user(Config.ADMIN_ID))
        async def complete_otp_cmd(client, message):
            parts = message.text.split()
            if len(parts) != 3:
                await message.reply("Usage: `/otp +911234567890 12345`")
                return
            phone, otp_code = parts[1], parts[2]

            session_data = self.pending_sessions.get(message.from_user.id)
            if not session_data:
                await message.reply("❌ No pending session. Use `/gensession` first.")
                return
            if session_data["phone"] != phone:
                await message.reply(f"❌ Phone mismatch. Expected `{session_data['phone']}`")
                return

            temp_client = session_data["client"]
            await message.reply("⏳ Signing in...")
            try:
                await temp_client.sign_in(
                    phone_number=phone,
                    code=otp_code,
                    phone_code_hash=session_data["phone_code_hash"]
                )
                session_string = await temp_client.export_session_string()
                await temp_client.disconnect()
                del self.pending_sessions[message.from_user.id]

                await message.reply(
                    f"✅ **Session Generated!**\n\n"
                    f"📱 Phone: `{phone}`\n"
                    f"🔑 Session String:\n`{session_string}`\n\n"
                    f"Use this in `/addaccount` command."
                )
            except Exception as e:
                await message.reply(f"❌ Failed: `{str(e)}`")
                try:
                    await temp_client.disconnect()
                except: pass
                if message.from_user.id in self.pending_sessions:
                    del self.pending_sessions[message.from_user.id]


# ---------- OTP FORWARDER (Standalone) ----------
async def forward_telegram_otp(account_id: int, buyer_id: int, session_string: str):
    """
    Logs into the sold account and forwards any OTP (Login Code) from Telegram Service (777000)
    to the buyer.
    """
    if not session_string or session_string == "N/A" or len(session_string) < 10:
        logger.warning(f"No valid session string for account {account_id}")
        return

    logger.info(f"Starting OTP listener for account {account_id} -> Buyer {buyer_id}")
    try:
        async with Client(
            f"otp_listener_{account_id}",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=session_string,
            in_memory=True
        ) as user_app:

            @user_app.on_message(filters.text & filters.user(777000))
            async def otp_handler(client, message):
                text = message.text or ""
                if "login code" in text.lower() or "code" in text.lower():
                    logger.info(f"OTP received for account {account_id}. Forwarding to buyer {buyer_id}")
                    try:
                        await _bot_instance.send_message(
                            buyer_id,
                            f"🔑 **Login Code Received!**\n\n`{text}`\n\nPlease enter this code in the Telegram app."
                        )
                    except Exception as e:
                        logger.error(f"Failed to forward OTP: {e}")
                    # Stop after first OTP
                    await client.stop()

            await user_app.start()
            await asyncio.sleep(600)  # 10 minutes timeout
            await _bot_instance.send_message(
                buyer_id,
                "⏰ **Timeout:** No login attempt detected in the last 10 minutes. "
                "If you tried to login, contact support."
            )
            logger.info(f"OTP listener timeout for account {account_id}")

    except Exception as e:
        logger.error(f"OTP listener crashed for account {account_id}: {e}")
        try:
            await _bot_instance.send_message(
                buyer_id,
                f"❌ OTP forwarding error: `{str(e)}`\nPlease use the session string to login via Pyrogram/Telethon."
            )
        except:
            pass

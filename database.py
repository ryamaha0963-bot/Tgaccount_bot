import aiosqlite
import os
from datetime import datetime

DB_PATH = "accounts.db"

async def init_db():
    """Initialize database with all required tables and columns"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Accounts table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                password TEXT,
                otp TEXT,
                session_string TEXT,
                price INTEGER NOT NULL,
                description TEXT,
                is_sold BOOLEAN DEFAULT 0,
                sold_to INTEGER,
                sold_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Orders table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                payment_method TEXT,
                payment_txid TEXT,
                payment_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP
            )
        """)
        
        # ✅ Add session_string column if it doesn't exist (for old databases)
        try:
            await db.execute("ALTER TABLE accounts ADD COLUMN session_string TEXT;")
        except Exception:
            pass  # Column already exists
        
        await db.commit()


# ---------- ACCOUNT FUNCTIONS ----------

async def get_account_by_id(account_id: int) -> dict | None:
    """Fetch a single account by its ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_available_accounts() -> list:
    """Fetch all unsold accounts"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM accounts WHERE is_sold = 0 ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def add_account(phone: str, password: str, otp: str, session_string: str, price: int, description: str) -> int:
    """Add a new account with session string"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO accounts (phone, password, otp, session_string, price, description) VALUES (?, ?, ?, ?, ?, ?)",
            (phone, password, otp, session_string, price, description)
        )
        await db.commit()
        return cursor.lastrowid


async def update_account_otp(account_id: int, new_otp: str):
    """Update OTP/backup code of an account"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE accounts SET otp = ? WHERE id = ?", (new_otp, account_id))
        await db.commit()


async def mark_account_sold(account_id: int, user_id: int):
    """Mark account as sold and store buyer's user_id"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET is_sold = 1, sold_to = ?, sold_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user_id, account_id)
        )
        await db.commit()


async def get_account_by_phone(phone: str) -> dict | None:
    """Fetch account by phone number (used for Twilio SMS forwarding)"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM accounts WHERE phone = ?", (phone,))
        row = await cursor.fetchone()
        return dict(row) if row else None


# ---------- ORDER FUNCTIONS ----------

async def create_order_with_payment(user_id: int, account_id: int, payment_method: str, payment_id: str) -> int:
    """Create a new order with payment ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, account_id, payment_method, payment_id, status) VALUES (?, ?, ?, ?, 'pending')",
            (user_id, account_id, payment_method, payment_id)
        )
        await db.commit()
        return cursor.lastrowid


async def get_order_by_payment_id(payment_id: str) -> dict | None:
    """Fetch order using NowPayments payment_id"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM orders WHERE payment_id = ?", (payment_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_order_status_by_payment_id(payment_id: str, status: str, txid: str = None):
    """Update order status using payment_id"""
    async with aiosqlite.connect(DB_PATH) as db:
        if txid:
            await db.execute(
                "UPDATE orders SET status = ?, payment_txid = ?, confirmed_at = CURRENT_TIMESTAMP WHERE payment_id = ?",
                (status, txid, payment_id)
            )
        else:
            await db.execute(
                "UPDATE orders SET status = ?, confirmed_at = CURRENT_TIMESTAMP WHERE payment_id = ?",
                (status, payment_id)
            )
        await db.commit()


async def get_order(order_id: int) -> dict | None:
    """Fetch order by order ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_orders() -> list:
    """Fetch all orders (admin panel)"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM orders ORDER BY id DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_orders_by_user(user_id: int) -> list:
    """Fetch all orders of a specific user"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (user_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_order_status(order_id: int, status: str, txid: str = None):
    """Update order status using order ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        if txid:
            await db.execute(
                "UPDATE orders SET status = ?, payment_txid = ?, confirmed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, txid, order_id)
            )
        else:
            await db.execute(
                "UPDATE orders SET status = ?, confirmed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, order_id)
            )
        await db.commit()

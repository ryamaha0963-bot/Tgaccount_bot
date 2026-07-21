import aiosqlite
import os

DB_PATH = "accounts.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                password TEXT,
                otp TEXT,
                price INTEGER NOT NULL,
                description TEXT,
                is_sold BOOLEAN DEFAULT 0,
                sold_to INTEGER,
                sold_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                payment_method TEXT,
                payment_txid TEXT,
                payment_id TEXT,          -- for NowPayments invoice ID
                status TEXT DEFAULT 'pending',  -- pending, paid, confirmed, cancelled
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP
            )
        """)
        await db.commit()

# (All CRUD functions same as before, but add these new ones)

async def create_order_with_payment(user_id, account_id, payment_method, payment_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, account_id, payment_method, payment_id, status) VALUES (?,?,?,?,'pending')",
            (user_id, account_id, payment_method, payment_id)
        )
        await db.commit()
        return cursor.lastrowid

async def get_order_by_payment_id(payment_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM orders WHERE payment_id=?", (payment_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def update_order_status_by_payment_id(payment_id, status, txid=None):
    async with aiosqlite.connect(DB_PATH) as db:
        if txid:
            await db.execute(
                "UPDATE orders SET status=?, payment_txid=?, confirmed_at=CURRENT_TIMESTAMP WHERE payment_id=?",
                (status, txid, payment_id)
            )
        else:
            await db.execute(
                "UPDATE orders SET status=?, confirmed_at=CURRENT_TIMESTAMP WHERE payment_id=?",
                (status, payment_id)
            )
        await db.commit()

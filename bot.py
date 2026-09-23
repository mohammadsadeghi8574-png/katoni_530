import os
import html
import sqlite3
import threading
import asyncio
import requests

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Bot,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# =========================================================
# تنظیمات اصلی
# =========================================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ZIBAL_MERCHANT = os.getenv("ZIBAL_MERCHANT", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

PORT = int(os.getenv("PORT", "8080"))

CHANNEL = "@katooni_530"
CHANNEL_LINK = "https://t.me/katooni_530"

ZIBAL_REQUEST_URL = "https://gateway.zibal.ir/v1/request"
ZIBAL_VERIFY_URL = "https://gateway.zibal.ir/v1/verify"
ZIBAL_START_URL = "https://gateway.zibal.ir/start/"

DB_FILE = "orders.db"


# =========================================================
# سایزهای ثابت فروشگاه
# =========================================================

WOMEN_SIZES = ["37", "38", "39", "40"]
MEN_SIZES = ["41", "42", "43", "44", "45"]


def allowed_sizes(category):
    if category == "women":
        return WOMEN_SIZES

    if category == "men":
        return MEN_SIZES

    return WOMEN_SIZES + MEN_SIZES


# =========================================================
# ابزارها
# =========================================================

def money(value):
    return f"{int(value):,}"


def normalize_code(value):
    value = str(value).strip()

    if not value.isdigit():
        return None

    number = int(value)

    if 1 <= number <= 999:
        return f"{number:03d}"

    return None


def is_admin(user_id):
    if not ADMIN_CHAT_ID:
        return False

    return str(user_id) == str(ADMIN_CHAT_ID)


def clear_mode(context):
    context.user_data.clear()


# =========================================================
# دیتابیس
# =========================================================

def db_connection():
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False,
    )

    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            category TEXT NOT NULL DEFAULT 'women',
            active INTEGER NOT NULL DEFAULT 1,
            photo TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            product_code TEXT NOT NULL,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (product_code, size)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            telegram_chat_id INTEGER NOT NULL,
            product_code TEXT NOT NULL,
            product_name TEXT NOT NULL,
            size TEXT NOT NULL,
            amount_toman INTEGER NOT NULL,
            amount_rial INTEGER NOT NULL,
            customer_name TEXT NOT NULL,
            mobile TEXT NOT NULL,
            address TEXT NOT NULL,
            track_id TEXT UNIQUE,
            ref_number TEXT,
            status TEXT NOT NULL DEFAULT 'waiting_payment',
            stock_reduced INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            paid_at DATETIME
        )
    """)

    try:
        cur.execute("""
            ALTER TABLE orders
            ADD COLUMN stock_reduced INTEGER NOT NULL DEFAULT 0
        """)
    except sqlite3.OperationalError:
        pass

    # محصول اولیه 005
    cur.execute("""
        INSERT OR IGNORE INTO products
        (code, name, price, category, active)
        VALUES (?, ?, ?, ?, 1)
    """, (
        "005",
        "New Balance 530 🤎",
        7250000,
        "women",
    ))

    # سایزهای اولیه مدل 005
    initial_stock = {
        "37": 4,
        "38": 4,
        "39": 4,
        "40": 0,
    }

    for size in WOMEN_SIZES:
        cur.execute("""
            INSERT OR IGNORE INTO inventory
            (product_code, size, quantity)
            VALUES (?, ?, ?)
        """, (
            "005",
            size,
            initial_stock.get(size, 0),
        ))

    conn.commit()
    conn.close()


# =========================================================
# محصولات
# =========================================================

def get_product(code):
    code = normalize_code(code)

    if not code:
        return None

    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM products
        WHERE code = ?
        AND active = 1
    """, (code,))

    row = cur.fetchone()
    conn.close()

    return row


def get_all_products():
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM products
        WHERE active = 1
        ORDER BY CAST(code AS INTEGER)
    """)

    rows = cur.fetchall()
    conn.close()

    return rows


def get_products_by_category(category):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM products
        WHERE active = 1
        AND category = ?
        ORDER BY CAST(code AS INTEGER)
    """, (category,))

    rows = cur.fetchall()
    conn.close()

    return rows


def seed_product_sizes(code, category):
    conn = db_connection()
    cur = conn.cursor()

    for size in allowed_sizes(category):
        cur.execute("""
            INSERT OR IGNORE INTO inventory
            (product_code, size, quantity)
            VALUES (?, ?, 0)
        """, (
            code,
            size,
        ))

    conn.commit()
    conn.close()


def add_product(code, name, price, category):
    code = normalize_code(code)

    if not code:
        return False

    conn = db_connection()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT code
            FROM products
            WHERE code = ?
        """, (code,))

        existing = cur.fetchone()

        if existing:
            cur.execute("""
                UPDATE products
                SET name = ?,
                    price = ?,
                    category = ?,
                    active = 1
                WHERE code = ?
            """, (
                name,
                int(price),
                category,
                code,
            ))

        else:
            cur.execute("""
                INSERT INTO products
                (code, name, price, category, active)
                VALUES (?, ?, ?, ?, 1)
            """, (
                code,
                name,
                int(price),
                category,
            ))

        conn.commit()

    except Exception as e:
        print("Add product error:", e)
        conn.rollback()
        conn.close()
        return False

    conn.close()

    seed_product_sizes(
        code,
        category,
    )

    return True


def update_product_price(code, price):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE products
        SET price = ?
        WHERE code = ?
    """, (
        int(price),
        code,
    ))

    conn.commit()
    conn.close()


def update_product_name(code, name):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE products
        SET name = ?
        WHERE code = ?
    """, (
        name,
        code,
    ))

    conn.commit()
    conn.close()


def delete_product(code):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE products
        SET active = 0
        WHERE code = ?
    """, (code,))

    conn.commit()
    conn.close()


# =========================================================
# موجودی
# =========================================================

def get_stock(code, size):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT quantity
        FROM inventory
        WHERE product_code = ?
        AND size = ?
    """, (
        code,
        str(size),
    ))

    row = cur.fetchone()
    conn.close()

    if not row:
        return 0

    return int(row["quantity"])


def set_stock(code, size, quantity):
    quantity = max(
        0,
        int(quantity)
    )

    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO inventory
        (product_code, size, quantity)
        VALUES (?, ?, ?)
        ON CONFLICT(product_code, size)
        DO UPDATE SET quantity = excluded.quantity
    """, (
        code,
        str(size),
        quantity,
    ))

    conn.commit()
    conn.close()


def change_stock(code, size, amount):
    product = get_product(code)

    if not product:
        return 0

    valid_sizes = allowed_sizes(
        product["category"]
    )

    if str(size) not in valid_sizes:
        return 0

    conn = db_connection()

    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")

        cur.execute("""
            SELECT quantity
            FROM inventory
            WHERE product_code = ?
            AND size = ?
        """, (
            code,
            str(size),
        ))

        row = cur.fetchone()

        if row:
            current = int(
                row["quantity"]
            )

        else:
            current = 0

            cur.execute("""
                INSERT INTO inventory
                (product_code, size, quantity)
                VALUES (?, ?, 0)
            """, (
                code,
                str(size),
            ))

        new_quantity = max(
            0,
            current + int(amount)
        )

        cur.execute("""
            UPDATE inventory
            SET quantity = ?
            WHERE product_code = ?
            AND size = ?
        """, (
            new_quantity,
            code,
            str(size),
        ))

        conn.commit()

        return new_quantity

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# سفارش‌ها
# =========================================================

def create_order(
    telegram_user_id,
    telegram_chat_id,
    product_code,
    product_name,
    size,
    amount_toman,
    customer_name,
    mobile,
    address,
):
    amount_rial = int(
        amount_toman
    ) * 10

    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orders (
            telegram_user_id,
            telegram_chat_id,
            product_code,
            product_name,
            size,
            amount_toman,
            amount_rial,
            customer_name,
            mobile,
            address,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'waiting_payment')
    """, (
        telegram_user_id,
        telegram_chat_id,
        product_code,
        product_name,
        size,
        amount_toman,
        amount_rial,
        customer_name,
        mobile,
        address,
    ))

    order_id = cur.lastrowid

    conn.commit()
    conn.close()

    return order_id


def get_order(order_id):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM orders
        WHERE id = ?
    """, (
        order_id,
    ))

    row = cur.fetchone()
    conn.close()

    return row


def get_user_order(
    order_id,
    user_id,
):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM orders
        WHERE id = ?
        AND telegram_user_id = ?
    """, (
        order_id,
        user_id,
    ))

    row = cur.fetchone()
    conn.close()

    return row


def get_order_by_track_id(
    track_id
):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM orders
        WHERE track_id = ?
    """, (
        str(track_id),
    ))

    row = cur.fetchone()
    conn.close()

    return row


def set_track_id(
    order_id,
    track_id
):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE orders
        SET track_id = ?
        WHERE id = ?
    """, (
        str(track_id),
        order_id,
    ))

    conn.commit()
    conn.close()


def mark_order_paid(
    order_id,
    ref_number
):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE orders
        SET status = 'paid',
            ref_number = ?,
            paid_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        str(ref_number),
        order_id,
    ))

    conn.commit()
    conn.close()


def mark_order_failed(
    order_id
):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE orders
        SET status = 'payment_failed'
        WHERE id = ?
        AND status != 'paid'
    """, (
        order_id,
    ))

    conn.commit()
    conn.close()


def reduce_stock_after_payment(
    order_id
):
    conn = db_connection()

    try:
        cur

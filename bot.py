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
BOT_USERNAME = "katoni_530_bot"

ZIBAL_REQUEST_URL = "https://gateway.zibal.ir/v1/request"
ZIBAL_VERIFY_URL = "https://gateway.zibal.ir/v1/verify"
ZIBAL_START_URL = "https://gateway.zibal.ir/start/"

DB_FILE = "orders.db"


# =========================================================
# ابزارها
# =========================================================

def money(value):
    return f"{int(value):,}"


def normalize_code(value):
    value = str(value).strip()

    if value.isdigit():
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
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connection()
    cur = conn.cursor()

    # محصولات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            category TEXT NOT NULL DEFAULT 'all',
            active INTEGER NOT NULL DEFAULT 1,
            photo TEXT
        )
    """)

    # موجودی سایزها
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            product_code TEXT NOT NULL,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (product_code, size)
        )
    """)

    # سفارش‌ها
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

    # سازگاری با دیتابیس قبلی
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
        7_250_000,
        "women",
    ))

    initial_stock = {
        "37": 4,
        "38": 4,
        "39": 4,
        "40": 0,
    }

    for size, quantity in initial_stock.items():
        cur.execute("""
            INSERT OR IGNORE INTO inventory
            (product_code, size, quantity)
            VALUES (?, ?, ?)
        """, (
            "005",
            size,
            quantity,
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


def add_product(code, name, price, category="all"):
    code = normalize_code(code)

    if not code:
        return False

    conn = db_connection()

    try:
        cur = conn.cursor()

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
        return True

    except sqlite3.IntegrityError:
        return False

    finally:
        conn.close()


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

def get_inventory(code):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT size, quantity
        FROM inventory
        WHERE product_code = ?
        ORDER BY
            CASE
                WHEN size GLOB '[0-9]*'
                THEN CAST(size AS REAL)
                ELSE 9999
            END,
            size
    """, (code,))

    rows = cur.fetchall()
    conn.close()

    return rows


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
    quantity = max(0, int(quantity))

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

        if not row:
            current = 0

            cur.execute("""
                INSERT INTO inventory
                (product_code, size, quantity)
                VALUES (?, ?, 0)
            """, (
                code,
                str(size),
            ))

        else:
            current = int(row["quantity"])

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


def add_size(code, size, quantity=0):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO inventory
        (product_code, size, quantity)
        VALUES (?, ?, ?)
    """, (
        code,
        str(size),
        max(0, int(quantity)),
    ))

    conn.commit()
    conn.close()


def remove_size(code, size):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM inventory
        WHERE product_code = ?
        AND size = ?
    """, (
        code,
        str(size),
    ))

    conn.commit()
    conn.close()


# =========================================================
# سفارش
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
    amount_rial = int(amount_toman) * 10

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
    """, (order_id,))

    row = cur.fetchone()
    conn.close()

    return row


def get_user_order(order_id, user_id):
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


def get_order_by_track_id(track_id):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM orders
        WHERE track_id = ?
    """, (str(track_id),))

    row = cur.fetchone()
    conn.close()

    return row


def set_track_id(order_id, track_id):
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


def mark_order_paid(order_id, ref_number=""):
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


def mark_order_failed(order_id):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE orders
        SET status = 'payment_failed'
        WHERE id = ?
        AND status != 'paid'
    """, (order_id,))

    conn.commit()
    conn.close()


def reduce_stock_after_payment(order_id):
    conn = db_connection()

    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")

        cur.execute("""
            SELECT *
            FROM orders
            WHERE id = ?
        """, (order_id,))

        order = cur.fetchone()

        if not order:
            conn.rollback()
            return False

        if int(order["stock_reduced"] or 0) == 1:
            conn.rollback()
            return True

        cur.execute("""
            UPDATE inventory
            SET quantity = quantity - 1
            WHERE product_code = ?
            AND size = ?
            AND quantity > 0
        """, (
            order["product_code"],
            order["size"],
        ))

        if cur.rowcount != 1:
            conn.rollback()
            return False

        cur.execute("""
            UPDATE orders
            SET stock_reduced = 1
            WHERE id = ?
        """, (order_id,))

        conn.commit()
        return True

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# منوها
# =========================================================

def main_keyboard(user_id=None):
    buttons = [
        ["🔥 جدیدترین مدل‌ها"],
        ["👟 کفش زنانه", "👟 کفش مردانه"],
        ["🔎 جستجو با کد محصول"],
        ["🛒 ثبت سفارش", "📦 پیگیری سفارش"],
        ["💰 قیمت و موجودی", "📏 راهنمای سایز"],
        ["💳 پرداخت و مشکلات پرداخت"],
        ["👨‍💬 پشتیبانی", "📣 کانال تلگرام"],
    ]

    if user_id and is_admin(user_id):
        buttons.append(
            ["🔐 مدیریت فروشگاه"]
        )

    return ReplyKeyboardMarkup(
        buttons,
        resize_keyboard=True,
    )


def cancel_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["❌ لغو عملیات"],
            ["🏠 بازگشت به منوی اصلی"],
        ],
        resize_keyboard=True,
    )


def support_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🛍 راهنمای خرید", "📦 پیگیری سفارش"],
            ["💳 مشکل پرداخت", "🔄 تعویض / مشکل سفارش"],
            ["📏 راهنمای انتخاب سایز", "💰 استعلام قیمت و موجودی"],
            ["👨‍💼 ارتباط مستقیم با پشتیبان"],
            ["🏠 بازگشت به منوی اصلی"],
        ],
        resize_keyboard=True,
    )


# =========================================================
# عضویت کانال
# =========================================================

async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(
            CHANNEL,
            user_id
        )

        return member.status in (
            "member",
            "administrator",
            "creator",
        )

    except Exception as e:
        print("Membership error:", e)
        return True


async def show_join_message(update):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📣 عضویت در کانال",
                url=CHANNEL_LINK,
            )
        ],
        [
            InlineKeyboardButton(
                "✅ عضو شدم",
                callback_data="check_membership",
            )
        ],
    ])

    await update.effective_message.reply_text(
        "سلام 👋\n\n"
        "برای استفاده از فروشگاه کتونی 530 ابتدا عضو کانال شوید 👇\n\n"
        "بعد از عضویت روی «✅ عضو شدم» بزنید.",
        reply_markup=keyboard,
    )


# =========================================================
# نمایش محصول
# =========================================================

async def send_product(message, code):
    code = normalize_code(code)

    if not code:
        await message.reply_text(
            "❌ کد باید بین 001 تا 999 باشد."
        )
        return

    product = get_product(code)

    if not product:
        await message.reply_text(
            f"❌ محصول با کد {code} هنوز در فروشگاه ثبت نشده است."
        )
        return

    inventory = get_inventory(code)

    available = []

    for row in inventory:
        if int(row["quantity"]) > 0:
            available.append(str(row["size"]))

    if available:
        size_text = " - ".join(available)

        stock_text = (
            f"📏 سایزهای موجود: {size_text}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🛒 خرید این مدل",
                    callback_data=f"buy:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    "📣 کانال کتونی 530",
                    url=CHANNEL_LINK,
                )
            ],
        ])

    else:
        stock_text = "❌ فعلاً ناموجود"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ ناموجود",
                    callback_data="nothing",
                )
            ],
            [
                InlineKeyboardButton(
                    "📣 کانال کتونی 530",
                    url=CHANNEL_LINK,
                )
            ],
        ])

    caption = (
        f"👟 {product['name']}\n\n"
        f"🏷 کد محصول: {code}\n"
        f"{stock_text}\n"
        f"💰 قیمت: {money(product['price'])} تومان"
    )

    if product["photo"]:
        try:
            await message.reply_photo(
                photo=product["photo"],
                caption=caption,
                reply_markup=keyboard,
            )
            return
        except Exception as e:
            print("Photo error:", e)

    await message.reply_text(
        caption,
        reply_markup=keyboard,
    )


async def show_latest_products(message):
    products = get_all_products()

    if not products:
        await message.reply_text(
            "فعلاً محصولی ثبت نشده است."
        )
        return

    await message.reply_text(
        "🔥 جدیدترین مدل‌های کتونی 530\n\n"
        "مدل موردنظر را انتخاب کنید 👇"
    )

    # آخرین محصولات
    for product in products[-10:]:
        await send_product(
            message,
            product["code"]
        )


async def show_category(message, category):
    products = get_products_by_category(category)

    if not products:
        await message.reply_text(
            "فعلاً مدلی در این بخش ثبت نشده است."
        )
        return

    for product in products:
        await send_product(
            message,
            product["code"]
        )


# =========================================================
# پنل مدیریت فروشگاه
# =========================================================

async def show_admin_panel(message):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📦 مدیریت محصولات و موجودی",
                callback_data="admin_products",
            )
        ],
        [
            InlineKeyboardButton(
                "➕ افزودن محصول جدید",
                callback_data="admin_add_product",
            )
        ],
    ])

    await message.reply_text(
        "🔐 مدیریت فروشگاه کتونی 530\n\n"
        "از این قسمت می‌توانید محصولات، سایزها و موجودی را مدیریت کنید.",
        reply_markup=keyboard,
    )


async def show_admin_products(message):
    products = get_all_products()

    buttons = []

    for product in products:
        buttons.append([
            InlineKeyboardButton(
                f"👟 {product['code']} | {product['name']}",
                callback_data=f"admin_product:{product['code']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "➕ افزودن محصول جدید",
            callback_data="admin_add_product",
        )
    ])

    await message.reply_text(
        "📦 محصولات فروشگاه\n\n"
        "محصول موردنظر را انتخاب کنید 👇",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_admin_inventory(message, code):
    product = get_product(code)

    if not product:
        await message.reply_text(
            "❌ محصول پیدا نشد."
        )
        return

    inventory = get_inventory(code)

    text = (
        "📦 مدیریت محصول\n\n"
        f"👟 {product['name']}\n"
        f"🏷 کد: {product['code']}\n"
        f"💰 قیمت: {money(product['price'])} تومان\n\n"
        "📏 موجودی سایزها:\n"
    )

    buttons = []

    if inventory:
        for row in inventory:
            size = str(row["size"])
            qty = int(row["quantity"])

            text += (
                f"سایز {size} = {qty} جفت\n"
            )

            buttons.append([
                InlineKeyboardButton(
                    "➖",
                    callback_data=f"stock_minus:{code}:{size}",
                ),
                InlineKeyboardButton(
                    f"سایز {size} | {qty}",
                    callback_data="nothing",
                ),
                InlineKeyboardButton(
                    "➕",
                    callback_data=f"stock_plus:{code}:{size}",
                ),
            ])
    else:
        text += "هنوز سایزی ثبت نشده است.\n"

    buttons.append([
        InlineKeyboardButton(
            "➕ افزودن سایز",
            callback_data=f"admin_add_size:{code}",
        ),
        InlineKeyboardButton(
            "🗑 حذف سایز",
            callback_data=f"admin_remove_size:{code}",
        ),
    ])

    buttons.append([
        InlineKeyboardButton(
            "💰 تغییر قیمت",
            callback_data=f"admin_price:{code}",
        ),
        InlineKeyboardButton(
            "✏️ تغییر نام",
            callback_data=f"admin_name:{code}",
        ),
    ])

    buttons.append([
        InlineKeyboardButton(
            "🗑 حذف محصول",
            callback_data=f"admin_delete_product:{code}",
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ برگشت",
            callback_data="admin_products",
        )
    ])

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =========================================================
# شروع
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    clear_mode(context)

    user_id = update.effective_user.id

    if not await is_member(
        context.bot,
        user_id
    ):
        if context.args:
            code = normalize_code(
                context.args[0]
            )

            if code:
                context.user_data[
                    "pending_product"
                ] = code

        await show_join_message(update)
        return

    # لینک مستقیم محصول
    if context.args:
        code = normalize_code(
            context.args[0]
        )

        if code:
            await update.message.reply_text(
                "👋 به فروشگاه کتونی 530 خوش آمدید.",
                reply_markup=main_keyboard(user_id),
            )

            await send_product(
                update.message,
                code
            )
            return

    await update.message.reply_text(
        "👟 به فروشگاه کتونی 530 خوش آمدید\n\n"
        "🔥 جدیدترین مدل‌ها را ببینید 👇",
        reply_markup=main_keyboard(user_id),
    )

    await show_latest_products(
        update.message
    )


# =========================================================
# دکمه‌ها
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    await query.answer()

    # -----------------------------------------------------
    # عضویت
    # -----------------------------------------------------

    if data == "check_membership":
        if not await is_member(
            context.bot,
            user_id
        ):
            await query.answer(
                "هنوز عضویت شما تأیید نشده است.",
                show_alert=True,
            )
            return

        await query.message.reply_text(
            "✅ عضویت شما تأیید شد.",
            reply_markup=main_keyboard(user_id),
        )

        pending = context.user_data.pop(
            "pending_product",
            None
        )

        if pending:
            await send_product(
                query.message,
                pending
            )
        else:
            await show_latest_products(
                query.message
            )

        return

    if data == "nothing":
        return

    # -----------------------------------------------------
    # خرید
    # -----------------------------------------------------

    if data.startswith("buy:"):
        code = data.split(":", 1)[1]

        product = get_product(code)

        if not product:
            await query.message.reply_text(
                "❌ محصول پیدا نشد."
            )
            return

        inventory = get_inventory(code)

        buttons = []

        for row in inventory:
            size = str(row["size"])
            qty = int(row["quantity"])

            if qty > 0:
                buttons.append([
                    InlineKeyboardButton(
                        f"سایز {size}",
                        callback_data=f"size:{code}:{size}",
                    )
                ])

        if not buttons:
            await query.message.reply_text(
                "❌ موجودی این مدل تمام شده است."
            )
            return

        await query.message.reply_text(
            f"👟 {product['name']}\n"
            f"🏷 کد: {code}\n"
            f"💰 قیمت: {money(product['price'])} تومان\n\n"
            "📏 سایز موردنظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    # -----------------------------------------------------
    # انتخاب سایز
    # -----------------------------------------------------

    if data.startswith("size:"):
        _, code, size = data.split(":", 2)

        product = get_product(code)

        if not product:
            return

        if get_stock(code, size) <= 0:
            await query.answer(
                "❌ این سایز تمام شده است.",
                show_alert=True,
            )
            return

        clear_mode(context)

        context.user_data["ordering"] = True
        context.user_data["step"] = "name"
        context.user_data["product_code"] = code
        context.user_data["size"] = size

        await query.message.reply_text(
            "🛒 ثبت سفارش\n\n"
            f"👟 {product['name']}\n"
            f"🏷 کد: {code}\n"
            f"📏 سایز: {size}\n"
            f"💰 مبلغ: {money(product['price'])} تومان\n\n"
            "👤 نام و نام خانوادگی را بفرستید:",
            reply_markup=cancel_keyboard(),
        )

        return

    # =====================================================
    # پنل مدیریت
    # =====================================================

    if data.startswith("admin_") or data.startswith("stock_"):
        if not is_admin(user_id):
            await query.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

    if data == "admin_products":
        await show_admin_products(
            query.message
        )
        return

    # -----------------------------------------------------
    # افزودن محصول
    # -----------------------------------------------------

    if data == "admin_add_product":
        clear_mode(context)

        context.user_data[
            "admin_add_product"
        ] = True

        context.user_data[
            "admin_step"
        ] = "code"

        await query.message.reply_text(
            "➕ افزودن محصول جدید\n\n"
            "🏷 کد محصول را وارد کنید.\n"
            "کد باید بین 001 تا 999 باشد.\n\n"
            "مثال: 006",
            reply_markup=cancel_keyboard(),
        )

        return

    # -----------------------------------------------------
    # محصول مدیریت
    # -----------------------------------------------------

    if data.startswith("admin_product:"):
        code = data.split(":", 1)[1]

        await show_admin_inventory(
            query.message,
            code
        )
        return

    # -----------------------------------------------------
    # موجودی +
    # -----------------------------------------------------

    if data.startswith("stock_plus:"):
        _, code, size = data.split(":", 2)

        qty = change_stock(
            code,
            size,
            1
        )

        await query.answer(
            f"✅ سایز {size}: {qty} جفت"
        )

        await show_admin_inventory(
            query.message,
            code
        )
        return

    # -----------------------------------------------------
    # موجودی -
    # -----------------------------------------------------

    if data.startswith("stock_minus:"):
        _, code, size = data.split(":", 2)

        qty = change_stock(
            code,
            size,
            -1
        )

        await query.answer(
            f"✅ سایز {size}: {qty} جفت"
        )

        await show_admin_inventory(
            query.message,
            code
        )
        return

    # -----------------------------------------------------
    # افزودن سایز
    # -----------------------------------------------------

    if data.startswith("admin_add_size:"):
        code = data.split(":", 1)[1]

        clear_mode(context)

        context.user_data[
            "admin_add_size"
        ] = True

        context.user_data[
            "admin_product_code"
        ] = code

        context.user_data[
            "admin_step"
        ] = "size"

        await query.message.reply_text(
            f"➕ افزودن سایز به محصول {code}\n\n"
            "شماره سایز را بفرستید.\n"
            "مثال: 40",
            reply_markup=cancel_keyboard(),
        )

        return

    # -----------------------------------------------------
    # حذف سایز
    # -----------------------------------------------------

    if data.startswith("admin_remove_size:"):
        code = data.split(":", 1)[1]

        inventory = get_inventory(code)

        if not inventory:
            await query.message.reply_text(
                "هیچ سایزی ثبت نشده است."
            )
            return

        buttons = []

        for row in inventory:
            size = str(row["size"])

            buttons.append([
                InlineKeyboardButton(
                    f"🗑 حذف سایز {size}",
                    callback_data=f"admin_delete_size:{code}:{size}",
                )
            ])

        await query.message.reply_text(
            "سایزی که می‌خواهید حذف کنید را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    if data.startswith("admin_delete_size:"):
        _, code, size = data.split(":", 2)

        remove_size(
            code,
            size
        )

        await query.answer(
            f"سایز {size} حذف شد ✅"
        )

        await show_admin_inventory(
            query.message,
            code
        )
        return

    # -----------------------------------------------------
    # قیمت
    # -----------------------------------------------------

    if data.startswith("admin_price:"):
        code = data.split(":", 1)[1]

        clear_mode(context)

        context.user_data[
            "admin_change_price"
        ] = True

        context.user_data[
            "admin_product_code"
        ] = code

        await query.message.reply_text(
            f"💰 قیمت جدید محصول {code} را به تومان بفرستید.\n\n"
            "مثال:\n8750000",
            reply_markup=cancel_keyboard(),
        )

        return

    # -----------------------------------------------------
    # نام
    # -----------------------------------------------------

    if data.startswith("admin_name:"):
        code = data.split(":", 1)[1]

        clear_mode(context)

        context.user_data[
            "admin_change_name"
        ] = True

        context.user_data[
            "admin_product_code"
        ] = code

        await query.message.reply_text(
            f"✏️ نام جدید محصول {code} را بفرستید.",
            reply_markup=cancel_keyboard(),
        )

        return

    # -----------------------------------------------------
    # حذف محصول
    # -----------------------------------------------------

    if data.startswith("admin_delete_product:"):
        code = data.split(":", 1)[1]

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ بله، حذف شود",
                    callback_data=f"admin_confirm_delete:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ خیر",
                    callback_data=f"admin_product:{code}",
                )
            ],
        ])

        await query.message.reply_text(
            f"⚠️ محصول {code} حذف شود؟",
            reply_markup=keyboard,
        )

        return

    if data.startswith("admin_confirm_delete:"):
        code = data.split(":", 1)[1]

        delete_product(code)

        await query.answer(
            "محصول حذف شد ✅"
        )

        await show_admin_products(
            query.message
        )

        return


# =========================================================
# زیبال
# =========================================================

def create_zibal_payment(order):
    if not ZIBAL_MERCHANT:
        raise Exception(
            "ZIBAL_MERCHANT تنظیم نشده"
        )

    if not PUBLIC_URL:
        raise Exception(
            "PUBLIC_URL تنظیم نشده"
        )

    payload = {
        "merchant": ZIBAL_MERCHANT,
        "amount": int(order["amount_rial"]),
        "callbackUrl": (
            f"{PUBLIC_URL}/zibal/callback"
        ),
        "description": (
            f"Katoni 530 Order #{order['id']}"
        ),
        "mobile": order["mobile"],
    }

    response = requests.post(
        ZIBAL_REQUEST_URL,
        json=payload,
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    if int(data.get("result", 0)) != 100:
        raise Exception(
            data.get(
                "message",
                "Zibal payment error"
            )
        )

    track_id = str(
        data.get("trackId", "")
    )

    if not track_id:
        raise Exception(
            "trackId دریافت نشد"
        )

    return track_id


def verify_zibal(track_id):
    response = requests.post(
        ZIBAL_VERIFY_URL,
        json={
            "merchant": ZIBAL_MERCHANT,
            "trackId": int(track_id),
        },
        timeout=20,
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# ارسال پیام از Callback
# =========================================================

def send_telegram_sync(chat_id, text):
    if not TOKEN:
        return

    async def sender():
        bot = Bot(token=TOKEN)

        try:
            await bot.send_message(
                chat_id=int(chat_id),
                text=text,
            )
        finally:
            await bot.shutdown()

    try:
        asyncio.run(sender())
    except Exception as e:
        print(
            "Telegram callback error:",
            e
        )


# =========================================================
# وب سرور پرداخت
# =========================================================

class PaymentCallbackHandler(
    BaseHTTPRequestHandler
):

    def log_message(self, format, *args):
        print(
            "HTTP:",
            format % args
        )

    def send_html(
        self,
        title,
        message
    ):
        page = f"""
        <!doctype html>
        <html lang="fa" dir="rtl">
        <head>
            <meta charset="utf-8">
            <meta
                name="viewport"
                content="width=device-width,initial-scale=1"
            >
            <title>
                {html.escape(title)}
            </title>
        </head>

        <body style="
            font-family:sans-serif;
            text-align:center;
            padding:40px;
        ">
            <h2>
                {html.escape(title)}
            </h2>

            <p>
                {html.escape(message)}
            </p>

            <p>
                می‌توانید به تلگرام برگردید.
            </p>

            <strong>
                👟 کتونی 530
            </strong>
        </body>
        </html>
        """

        body = page.encode("utf-8")

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(
            self.path
        )

        if parsed.path == "/":
            self.send_html(
                "کتونی 530",
                "ربات و درگاه پرداخت فعال است."
            )
            return

        if parsed.path != "/zibal/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(
            parsed.query
        )

        track_id = (
            params.get(
                "trackId",
                [""]
            )[0]
            or
            params.get(
                "trackid",
                [""]
            )[0]
        )

        success = params.get(
            "success",
            [""]
        )[0]

        if not track_id:
            self.send_html(
                "خطا",
                "شناسه پرداخت دریافت نشد."
            )
            return

        order = get_order_by_track_id(
            track_id
        )

        if not order:
            self.send_html(
                "خطا",
                "سفارش پیدا نشد."
            )
            return

        if order["status"] == "paid":
            self.send_html(
                "پرداخت تأیید شده است ✅",
                f"سفارش {order['id']} قبلاً ثبت شده است."
            )
            return

        if success != "1":
            mark_order_failed(
                order["id"]
            )

            send_telegram_sync(
                order["telegram_chat_id"],
                "❌ پرداخت انجام نشد یا لغو شد.\n"
                "سفارش نهایی ثبت نشده است."
            )

            self.send_html(
                "پرداخت ناموفق بود ❌",
                "سفارش نهایی نشده است."
            )
            return

        try:
            verify_data = verify_zibal(
                track_id
            )

            result = int(
                verify_data.get(
                    "result",
                    0
                )
            )

            if result not in (
                100,
                201
            ):
                self.send_html(
                    "پرداخت تأیید نشد ❌",
                    "تأیید نهایی درگاه دریافت نشد."
                )
                return

            verified_amount = (
                verify_data.get(
                    "amount"
                )
            )

            if (
                verified_amount
                is not None
                and
                int(verified_amount)
                !=
                int(order["amount_rial"])
            ):
                self.send_html(
                    "خطا در مبلغ",
                    "مبلغ پرداخت با سفارش مطابقت ندارد."
                )
                return

            ref_number = str(
                verify_data.get(
                    "refNumber",
                    ""
                )
                or track_id
            )

            stock_ok = (
                reduce_stock_after_payment(
                    order["id"]
                )
            )

            mark_order_paid(
                order["id"],
                ref_number
            )

            if not stock_ok:
                send_telegram_sync(
                    order["telegram_chat_id"],
                    "✅ پرداخت شما تأیید شد.\n\n"
                    "⚠️ سفارش برای بررسی موجودی به پشتیبانی ارسال شد."
                )

                if ADMIN_CHAT_ID:
                    send_telegram_sync(
                        ADMIN_CHAT_ID,
                        "⚠️ هشدار موجودی\n\n"
                        f"پرداخت سفارش #{order['id']} موفق بوده "
                        "ولی موجودی سایز هنگام ثبت نهایی صفر بوده است.\n"
                        "لطفاً سریع بررسی کنید."
                    )

                self.send_html(
                    "پرداخت موفق بود ✅",
                    "سفارش در حال بررسی موجودی است."
                )
                return

            remaining = get_stock(
                order["product_code"],
                order["size"]
            )

            send_telegram_sync(
                order["telegram_chat_id"],
                "🎉 پرداخت با موفقیت تأیید شد\n\n"
                f"🧾 شماره سفارش: {order['id']}\n"
                f"👟 محصول: {order['product_name']}\n"
                f"🏷 کد: {order['product_code']}\n"
                f"📏 سایز: {order['size']}\n"
                f"💰 مبلغ: {money(order['amount_toman'])} تومان\n"
                f"🔐 پیگیری پرداخت: {ref_number}\n\n"
                "✅ سفارش شما ثبت نهایی شد."
            )

            if ADMIN_CHAT_ID:
                send_telegram_sync(
                    ADMIN_CHAT_ID,
                    "🔔 سفارش جدید پرداخت شد\n\n"
                    f"🧾 سفارش: #{order['id']}\n"
                    f"👟 {order['product_name']}\n"
                    f"🏷 کد: {order['product_code']}\n"
                    f"📏 سایز: {order['size']}\n"
                    f"💰 مبلغ: {money(order['amount_toman'])} تومان\n\n"
                    f"👤 مشتری: {order['customer_name']}\n"
                    f"📱 موبایل: {order['mobile']}\n"
                    f"📍 آدرس: {order['address']}\n\n"
                    f"📦 موجودی باقی‌مانده این سایز: {remaining}"
                )

            self.send_html(
                "پرداخت موفق بود ✅",
                f"سفارش شماره {order['id']} ثبت شد."
            )

        except Exception as e:
            print(
                "VERIFY ERROR:",
                e
            )

            self.send_html(
                "خطا در بررسی پرداخت",
                "اگر مبلغ کسر شده، دوباره پرداخت نکنید."
            )


def start_http_server():
    server = ThreadingHTTPServer(
        (
            "0.0.0.0",
            PORT
        ),
        PaymentCallbackHandler
    )

    print(
        f"HTTP server running on {PORT}"
    )

    server.serve_forever()


# =========================================================
# پیام‌های متنی
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if (
        not update.message
        or
        not update.message.text
    ):
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id

    if not await is_member(
        context.bot,
        user_id
    ):
        await show_join_message(update)
        return

    # -----------------------------------------------------
    # خانه / لغو
    # -----------------------------------------------------

    if text in (
        "🏠 بازگشت به منوی اصلی",
        "❌ لغو عملیات",
    ):
        clear_mode(context)

        await update.message.reply_text(
            "🏠 منوی اصلی کتونی 530",
            reply_markup=main_keyboard(
                user_id
            ),
        )
        return

    # =====================================================
    # افزودن محصول توسط مدیر
    # =====================================================

    if context.user_data.get(
        "admin_add_product"
    ):
        if not is_admin(user_id):
            clear_mode(context)
            return

        step = context.user_data.get(
            "admin_step"
        )

        # کد
        if step == "code":
            code = normalize_code(text)

            if not code:
                await update.message.reply_text(
                    "❌ کد باید بین 001 تا 999 باشد.\n"
                    "مثال: 006"
                )
                return

            if get_product(code):
                await update.message.reply_text(
                    f"❌ محصول {code} قبلاً ثبت شده است."
                )
                return

            context.user_data[
                "new_product_code"
            ] = code

            context.user_data[
                "admin_step"
            ] = "name"

            await update.message.reply_text(
                f"✅ کد {code}\n\n"
                "👟 نام مدل را بفرستید.\n"
                "مثال:\nNew Balance 1906R"
            )
            return

        # نام
        if step == "name":
            if len(text) < 2:
                return

            context.user_data[
                "new_product_name"
            ] = text

            context.user_data[
                "admin_step"
            ] = "price"

            await update.message.reply_text(
                "💰 قیمت را به تومان بفرستید.\n\n"
                "مثال:\n8750000"
            )
            return

        # قیمت
        if step == "price":
            price_text = (
                text.replace(",", "")
                .replace("٬", "")
                .replace(" ", "")
            )

            if not price_text.isdigit():
                await update.message.reply_text(
                    "❌ فقط عدد قیمت را بفرستید.\n"
                    "مثال: 8750000"
                )
                return

            context.user_data[
                "new_product_price"
            ] = int(price_text)

            context.user_data[
                "admin_step"
            ] = "category"

            keyboard = ReplyKeyboardMarkup(
                [
                    ["👟 زنانه", "👟 مردانه"],
                    ["👟 عمومی"],
                    ["❌ لغو عملیات"],
                ],
                resize_keyboard=True,
            )

            await update.message.reply_text(
                "این محصول در کدام بخش باشد؟",
                reply_markup=keyboard,
            )
            return

        # دسته
        if step == "category":
            category_map = {
                "👟 زنانه": "women",
                "👟 مردانه": "men",
                "👟 عمومی": "all",
            }

            if text not in category_map:
                await update.message.reply_text(
                    "یکی از گزینه‌ها را انتخاب کنید."
                )
                return

            code = context.user_data[
                "new_product_code"
            ]

            name = context.user_data[
                "new_product_name"
            ]

            price = context.user_data[
                "new_product_price"
            ]

            category = category_map[text]

            success = add_product(
                code,
                name,
                price,
                category
            )

            if not success:
                clear

import os
import html
import sqlite3
import threading
import requests

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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

DB_FILE = "orders.db"

# هزینه ارسال برای هر جفت
SHIPPING_COST = 350000

ZIBAL_REQUEST_URL = "https://gateway.zibal.ir/v1/request"
ZIBAL_VERIFY_URL = "https://gateway.zibal.ir/v1/verify"
ZIBAL_START_URL = "https://gateway.zibal.ir/start/"


# =========================================================
# سایزهای ثابت فروشگاه
# =========================================================

WOMEN_SIZES = ["37", "38", "39", "40"]
MEN_SIZES = ["41", "42", "43", "44", "45"]


def sizes_for_category(category):
    if category == "women":
        return WOMEN_SIZES

    if category == "men":
        return MEN_SIZES

    return []


# =========================================================
# ابزارهای عمومی
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
    if context.user_data is not None:
        context.user_data.clear()


def user_data_safe(context):
    if context.user_data is None:
        return {}

    return context.user_data


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


def column_exists(table_name, column_name):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute(
        f"PRAGMA table_info({table_name})"
    )

    columns = [
        row["name"]
        for row in cur.fetchall()
    ]

    conn.close()

    return column_name in columns


def init_db():
    conn = db_connection()
    cur = conn.cursor()

    # محصولات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            category TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            photo TEXT
        )
    """)

    # موجودی
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
            product_price_toman INTEGER NOT NULL DEFAULT 0,
            shipping_toman INTEGER NOT NULL DEFAULT 0,
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

    conn.commit()
    conn.close()

    # سازگاری با دیتابیس قدیمی
    conn = db_connection()
    cur = conn.cursor()

    if not column_exists(
        "products",
        "photo"
    ):
        try:
            cur.execute("""
                ALTER TABLE products
                ADD COLUMN photo TEXT
            """)
        except Exception:
            pass

    if not column_exists(
        "orders",
        "stock_reduced"
    ):
        try:
            cur.execute("""
                ALTER TABLE orders
                ADD COLUMN stock_reduced
                INTEGER NOT NULL DEFAULT 0
            """)
        except Exception:
            pass

    if not column_exists(
        "orders",
        "product_price_toman"
    ):
        try:
            cur.execute("""
                ALTER TABLE orders
                ADD COLUMN product_price_toman
                INTEGER NOT NULL DEFAULT 0
            """)
        except Exception:
            pass

    if not column_exists(
        "orders",
        "shipping_toman"
    ):
        try:
            cur.execute("""
                ALTER TABLE orders
                ADD COLUMN shipping_toman
                INTEGER NOT NULL DEFAULT 0
            """)
        except Exception:
            pass

    conn.commit()
    conn.close()

    # محصول اولیه 005
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO products
        (
            code,
            name,
            price,
            category,
            active
        )
        VALUES (?, ?, ?, ?, 1)
    """, (
        "005",
        "New Balance 530 🤎",
        7250000,
        "women",
    ))

    initial_stock = {
        "37": 4,
        "38": 4,
        "39": 4,
        "40": 0,
    }

    for size in WOMEN_SIZES:
        cur.execute("""
            INSERT OR IGNORE INTO inventory
            (
                product_code,
                size,
                quantity
            )
            VALUES (?, ?, ?)
        """, (
            "005",
            size,
            initial_stock.get(
                size,
                0
            ),
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
    """, (
        code,
    ))

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
    """, (
        category,
    ))

    rows = cur.fetchall()
    conn.close()

    return rows


def seed_product_sizes(code, category):
    conn = db_connection()
    cur = conn.cursor()

    for size in sizes_for_category(
        category
    ):
        cur.execute("""
            INSERT OR IGNORE INTO inventory
            (
                product_code,
                size,
                quantity
            )
            VALUES (?, ?, 0)
        """, (
            code,
            size,
        ))

    conn.commit()
    conn.close()


def create_product(
    code,
    name,
    price,
    category
):
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
        """, (
            code,
        ))

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
                (
                    code,
                    name,
                    price,
                    category,
                    active
                )
                VALUES (?, ?, ?, ?, 1)
            """, (
                code,
                name,
                int(price),
                category,
            ))

        conn.commit()

    except Exception as e:
        print(
            "CREATE PRODUCT ERROR:",
            repr(e)
        )

        conn.rollback()
        conn.close()

        return False

    conn.close()

    seed_product_sizes(
        code,
        category
    )

    return True


def update_product_name(
    code,
    name
):
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


def update_product_price(
    code,
    price
):
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


def update_product_photo(
    code,
    file_id
):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE products
        SET photo = ?
        WHERE code = ?
    """, (
        file_id,
        code,
    ))

    conn.commit()
    conn.close()


def remove_product_photo(code):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE products
        SET photo = NULL
        WHERE code = ?
    """, (
        code,
    ))

    conn.commit()
    conn.close()


def update_product_category(
    code,
    category
):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE products
        SET category = ?
        WHERE code = ?
    """, (
        category,
        code,
    ))

    conn.commit()
    conn.close()

    seed_product_sizes(
        code,
        category
    )


def delete_product(code):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE products
        SET active = 0
        WHERE code = ?
    """, (
        code,
    ))

    conn.commit()
    conn.close()


# =========================================================
# موجودی
# =========================================================

def get_stock(
    code,
    size
):
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

    return int(
        row["quantity"]
    )


def change_stock(
    code,
    size,
    amount
):
    product = get_product(code)

    if not product:
        return 0

    allowed = sizes_for_category(
        product["category"]
    )

    if str(size) not in allowed:
        return 0

    conn = db_connection()

    try:
        cur = conn.cursor()

        cur.execute(
            "BEGIN IMMEDIATE"
        )

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
                (
                    product_code,
                    size,
                    quantity
                )
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
# سفارش
# =========================================================

def create_order(
    telegram_user_id,
    telegram_chat_id,
    product_code,
    product_name,
    size,
    product_price_toman,
    customer_name,
    mobile,
    address,
):
    shipping_toman = SHIPPING_COST

    total_toman = (
        int(product_price_toman)
        +
        int(shipping_toman)
    )

    amount_rial = (
        total_toman * 10
    )

    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orders (
            telegram_user_id,
            telegram_chat_id,
            product_code,
            product_name,
            size,
            product_price_toman,
            shipping_toman,
            amount_toman,
            amount_rial,
            customer_name,
            mobile,
            address,
            status
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            'waiting_payment'
        )
    """, (
        telegram_user_id,
        telegram_chat_id,
        product_code,
        product_name,
        size,
        int(product_price_toman),
        int(shipping_toman),
        int(total_toman),
        int(amount_rial),
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


def get_user_order(
    order_id,
    user_id
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
        cur = conn.cursor()

        cur.execute(
            "BEGIN IMMEDIATE"
        )

        cur.execute("""
            SELECT *
            FROM orders
            WHERE id = ?
        """, (
            order_id,
        ))

        order = cur.fetchone()

        if not order:
            conn.rollback()
            return False

        if int(
            order["stock_reduced"]
            or 0
        ) == 1:
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
        """, (
            order_id,
        ))

        conn.commit()

        return True

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# کیبوردها
# =========================================================

def main_keyboard(
    user_id=None
):
    buttons = [
        ["🔥 جدیدترین مدل‌ها"],
        [
            "👟 کفش زنانه",
            "👞 کفش مردانه",
        ],
        ["🔎 جستجو با کد محصول"],
        [
            "🛒 ثبت سفارش",
            "📦 پیگیری سفارش",
        ],
        [
            "💰 قیمت و موجودی",
            "📏 راهنمای سایز",
        ],
        ["💳 پرداخت و مشکلات پرداخت"],
        [
            "👨‍💬 پشتیبانی",
            "📣 کانال تلگرام",
        ],
    ]

    if (
        user_id
        and
        is_admin(user_id)
    ):
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
            [
                "🛍 راهنمای خرید",
                "📦 پیگیری سفارش",
            ],
            [
                "💳 مشکل پرداخت",
                "🔄 تعویض / مشکل سفارش",
            ],
            [
                "📏 راهنمای انتخاب سایز",
                "💰 استعلام قیمت و موجودی",
            ],
            [
                "👨‍💼 ارتباط مستقیم با پشتیبان",
            ],
            [
                "🏠 بازگشت به منوی اصلی",
            ],
        ],
        resize_keyboard=True,
    )


# =========================================================
# عضویت کانال
# =========================================================

async def is_member(
    bot,
    user_id
):
    try:
        member = await bot.get_chat_member(
            CHANNEL,
            user_id,
        )

        return member.status in (
            "member",
            "administrator",
            "creator",
        )

    except Exception as e:
        print(
            "MEMBERSHIP ERROR:",
            repr(e)
        )

        return True


async def show_join_message(
    update
):
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
# نمایش محصول برای مشتری
# =========================================================

async def send_product(
    message,
    code
):
    code = normalize_code(code)

    if not code:
        await message.reply_text(
            "❌ کد محصول باید بین 001 تا 999 باشد."
        )

        return

    product = get_product(code)

    if not product:
        await message.reply_text(
            f"❌ محصول با کد {code} هنوز در فروشگاه ثبت نشده است."
        )

        return

    sizes = sizes_for_category(
        product["category"]
    )

    available_sizes = []

    for size in sizes:
        if get_stock(
            code,
            size
        ) > 0:
            available_sizes.append(
                size
            )

    category_name = (
        "زنانه"
        if product["category"] == "women"
        else "مردانه"
    )

    if available_sizes:
        size_text = " - ".join(
            available_sizes
        )

        availability = (
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
        availability = (
            "❌ فعلاً ناموجود"
        )

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
        f"👤 دسته: {category_name}\n"
        f"{availability}\n"
        f"💰 قیمت: {money(product['price'])} تومان\n"
        f"🚚 ارسال هر جفت: {money(SHIPPING_COST)} تومان"
    )

    # اگر عکس ثبت شده باشد عکس کفش نمایش داده می‌شود
    if product["photo"]:
        try:
            await message.reply_photo(
                photo=product["photo"],
                caption=caption,
                reply_markup=keyboard,
            )

            return

        except Exception as e:
            print(
                "SEND PRODUCT PHOTO ERROR:",
                repr(e)
            )

    await message.reply_text(
        caption,
        reply_markup=keyboard,
    )


async def show_latest_products(
    message
):
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

    for product in products[-10:]:
        await send_product(
            message,
            product["code"],
        )


async def show_category(
    message,
    category
):
    products = get_products_by_category(
        category
    )

    if not products:
        await message.reply_text(
            "فعلاً محصولی در این بخش ثبت نشده است."
        )

        return

    for product in products:
        await send_product(
            message,
            product["code"],
        )


# =========================================================
# مدیریت فروشگاه
# =========================================================

async def show_admin_home(
    message
):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👟 محصولات زنانه",
                callback_data="admin_category:women",
            )
        ],
        [
            InlineKeyboardButton(
                "👞 محصولات مردانه",
                callback_data="admin_category:men",
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
        "بخش موردنظر را انتخاب کنید 👇",
        reply_markup=keyboard,
    )


async def show_admin_category(
    message,
    category
):
    products = get_products_by_category(
        category
    )

    category_name = (
        "زنانه"
        if category == "women"
        else "مردانه"
    )

    buttons = []

    for product in products:
        buttons.append([
            InlineKeyboardButton(
                f"{product['code']} | {product['name']}",
                callback_data=f"admin_product:{product['code']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "➕ افزودن محصول جدید",
            callback_data="admin_add_product",
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ برگشت",
            callback_data="admin_home",
        )
    ])

    await message.reply_text(
        f"📦 محصولات {category_name}\n\n"
        "محصول را انتخاب کنید 👇",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


async def show_admin_product(
    message,
    code
):
    product = get_product(code)

    if not product:
        await message.reply_text(
            "❌ محصول پیدا نشد."
        )

        return

    category = product["category"]

    category_name = (
        "زنانه"
        if category == "women"
        else "مردانه"
    )

    sizes = sizes_for_category(
        category
    )

    text = (
        "📦 مدیریت محصول\n\n"
        f"👟 {product['name']}\n"
        f"🏷 کد: {product['code']}\n"
        f"👤 دسته: {category_name}\n"
        f"💰 قیمت: {money(product['price'])} تومان\n"
        f"🚚 ارسال: {money(SHIPPING_COST)} تومان\n\n"
        "📏 موجودی سایزها:\n"
    )

    buttons = []

    for size in sizes:
        quantity = get_stock(
            code,
            size
        )

        text += (
            f"سایز {size} = {quantity} جفت\n"
        )

        buttons.append([
            InlineKeyboardButton(
                "➖",
                callback_data=f"stock_minus:{code}:{size}",
            ),
            InlineKeyboardButton(
                f"سایز {size} | {quantity} جفت",
                callback_data="nothing",
            ),
            InlineKeyboardButton(
                "➕",
                callback_data=f"stock_plus:{code}:{size}",
            ),
        ])

    # عکس
    if product["photo"]:
        photo_title = (
            "🖼 تغییر عکس"
        )

    else:
        photo_title = (
            "🖼 افزودن عکس"
        )

    buttons.append([
        InlineKeyboardButton(
            photo_title,
            callback_data=f"admin_photo:{code}",
        ),
        InlineKeyboardButton(
            "🗑 حذف عکس",
            callback_data=f"admin_remove_photo:{code}",
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
            "🔄 تغییر دسته",
            callback_data=f"admin_category_change:{code}",
        )
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
            callback_data=f"admin_category:{category}",
        )
    ])

    # اگر عکس دارد در مدیریت هم عکس نشان بده
    if product["photo"]:
        try:
            await message.reply_photo(
                photo=product["photo"],
                caption=text,
                reply_markup=InlineKeyboardMarkup(
                    buttons
                ),
            )

            return

        except Exception as e:
            print(
                "ADMIN PHOTO DISPLAY ERROR:",
                repr(e)
            )

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user:
        return

    clear_mode(context)

    user_id = update.effective_user.id

    if not await is_member(
        context.bot,
        user_id,
    ):
        if context.args:
            code = normalize_code(
                context.args[0]
            )

            if (
                code
                and
                context.user_data is not None
            ):
                context.user_data[
                    "pending_product"
                ] = code

        await show_join_message(
            update
        )

        return

    if context.args:
        code = normalize_code(
            context.args[0]
        )

        await update.effective_message.reply_text(
            "👋 به فروشگاه کتونی 530 خوش آمدید.",
            reply_markup=main_keyboard(
                user_id
            ),
        )

        if code:
            await send_product(
                update.effective_message,
                code,
            )

        return

    await update.effective_message.reply_text(
        "👟 به فروشگاه کتونی 530 خوش آمدید\n\n"
        "🔥 جدیدترین مدل‌ها را ببینید 👇",
        reply_markup=main_keyboard(
            user_id
        ),
    )

    await show_latest_products(
        update.effective_message
    )


# =========================================================
# دکمه‌ها
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    if not query.from_user:
        return

    data = query.data or ""
    user_id = query.from_user.id

    await query.answer()

    if data == "nothing":
        return

    # عضویت
    if data == "check_membership":
        if not await is_member(
            context.bot,
            user_id,
        ):
            await query.answer(
                "هنوز عضویت شما تأیید نشده است.",
                show_alert=True,
            )

            return

        await query.message.reply_text(
            "✅ عضویت شما تأیید شد.",
            reply_markup=main_keyboard(
                user_id
            ),
        )

        pending = None

        if context.user_data is not None:
            pending = context.user_data.pop(
                "pending_product",
                None,
            )

        if pending:
            await send_product(
                query.message,
                pending,
            )

        else:
            await show_latest_products(
                query.message
            )

        return

    # =====================================================
    # خرید
    # =====================================================

    if data.startswith(
        "buy:"
    ):
        code = data.split(
            ":",
            1
        )[1]

        product = get_product(
            code
        )

        if not product:
            await query.message.reply_text(
                "❌ محصول پیدا نشد."
            )

            return

        buttons = []

        for size in sizes_for_category(
            product["category"]
        ):
            quantity = get_stock(
                code,
                size
            )

            if quantity > 0:
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
            f"💰 قیمت کفش: {money(product['price'])} تومان\n"
            f"🚚 ارسال: {money(SHIPPING_COST)} تومان\n"
            f"💳 مبلغ نهایی: {money(product['price'] + SHIPPING_COST)} تومان\n\n"
            "📏 سایز موردنظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(
                buttons
            ),
        )

        return

    if data.startswith(
        "size:"
    ):
        _, code, size = data.split(
            ":",
            2
        )

        product = get_product(
            code
        )

        if not product:
            return

        if get_stock(
            code,
            size
        ) <= 0:
            await query.answer(
                "❌ این سایز تمام شده است.",
                show_alert=True,
            )

            return

        clear_mode(context)

        if context.user_data is None:
            return

        context.user_data[
            "ordering"
        ] = True

        context.user_data[
            "step"
        ] = "name"

        context.user_data[
            "product_code"
        ] = code

        context.user_data[
            "size"
        ] = size

        total = (
            int(product["price"])
            +
            SHIPPING_COST
        )

        await query.message.reply_text(
            "🛒 ثبت سفارش\n\n"
            f"👟 {product['name']}\n"
            f"🏷 کد: {code}\n"
            f"📏 سایز: {size}\n"
            f"💰 قیمت کفش: {money(product['price'])} تومان\n"
            f"🚚 هزینه ارسال: {money(SHIPPING_COST)} تومان\n"
            f"💳 مبلغ نهایی: {money(total)} تومان\n\n"
            "👤 نام و نام خانوادگی را بفرستید:",
            reply_markup=cancel_keyboard(),
        )

        return

    # =====================================================
    # امنیت مدیریت
    # =====================================================

    if (
        data.startswith(
            "admin_"
        )
        or
        data.startswith(
            "stock_"
        )
    ):
        if not is_admin(
            user_id
        ):
            await query.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )

            return

    if data == "admin_home":
        await show_admin_home(
            query.message
        )

        return

    if data.startswith(
        "admin_category:"
    ):
        category = data.split(
            ":",
            1
        )[1]

        await show_admin_category(
            query.message,
            category,
        )

        return

    # افزودن محصول
    if data == "admin_add_product":
        clear_mode(context)

        if context.user_data is None:
            return

        context.user_data[
            "admin_add_product"
        ] = True

        context.user_data[
            "admin_step"
        ] = "code"

        await query.message.reply_text(
            "➕ افزودن محصول جدید\n\n"
            "🏷 کد محصول را وارد کنید.\n"
            "از 001 تا 999\n\n"
            "مثال: 007",
            reply_markup=cancel_keyboard(),
        )

        return

    # مدیریت محصول
    if data.startswith(
        "admin_product:"
    ):
        code = data.split(
            ":",
            1
        )[1]

        await show_admin_product(
            query.message,
            code,
        )

        return

    # زیاد کردن موجودی
    if data.startswith(
        "stock_plus:"
    ):
        _, code, size = data.split(
            ":",
            2
        )

        quantity = change_stock(
            code,
            size,
            1,
        )

        await query.answer(
            f"✅ سایز {size}: {quantity} جفت"
        )

        await show_admin_product(
            query.message,
            code,
        )

        return

    # کم کردن موجودی
    if data.startswith(
        "stock_minus:"
    ):
        _, code, size = data.split(
            ":",
            2
        )

        quantity = change_stock(
            code,
            size,
            -1,
        )

        await query.answer(
            f"✅ سایز {size}: {quantity} جفت"
        )

        await show_admin_product(
            query.message,
            code,
        )

        return

    # عکس محصول
    if data.startswith(
        "admin_photo:"
    ):
        code = data.split(
            ":",
            1
        )[1]

        clear_mode(context)

        if context.user_data is None:
            return

        context.user_data[
            "admin_photo_product"
        ] = code

        await query.message.reply_text(
            f"🖼 عکس محصول {code}\n\n"
            "حالا فقط عکس کفش را برای ربات ارسال کنید.",
            reply_markup=cancel_keyboard(),
        )

        return

    # حذف عکس
    if data.startswith(
        "admin_remove_photo:"
    ):
        code = data.split(
            ":",
            1
        )[1]

        remove_product_photo(
            code
        )

        await query.answer(
            "عکس محصول حذف شد ✅"
        )

        await show_admin_product(
            query.message,
            code,
        )

        return

    # تغییر قیمت
    if data.startswith(
        "admin_price:"
    ):
        code = data.split(
            ":",
            1
        )[1]

        clear_mode(context)

        if context.user_data is None:
            return

        context.user_data[
            "admin_change_price"
        ] = code

        await query.message.reply_text(
            f"💰 قیمت جدید محصول {code} را به تومان بفرستید.\n\n"
            "مثال: 7900000",
            reply_markup=cancel_keyboard(),
        )

        return

    # تغییر نام
    if data.startswith(
        "admin_name:"
    ):
        code = data.split(
            ":",
            1
        )[1]

        clear_mode(context)

        if context.user_data is None:
            return

        context.user_data[
            "admin_change_name"
        ] = code

        await query.message.reply_text(
            f"✏️ نام جدید محصول {code} را بفرستید.",
            reply_markup=cancel_keyboard(),
        )

        return

    # تغییر دسته
    if data.startswith(
        "admin_category_change:"
    ):
        code = data.split(
            ":",
            1
        )[1]

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👟 زنانه",
                    callback_data=f"admin_set_category:{code}:women",
                ),
                InlineKeyboardButton(
                    "👞 مردانه",
                    callback_data=f"admin_set_category:{code}:men",
                ),
            ]
        ])

        await query.message.reply_text(
            "دسته محصول را انتخاب کنید:",
            reply_markup=keyboard,
        )

        return

    if data.startswith(
        "admin_set_category:"
    ):
        _, code, category = data.split(
            ":",
            2
        )

        update_product_category(
            code,
            category,
        )

        await query.answer(
            "دسته محصول تغییر کرد ✅"
        )

        await show_admin_product(
            query.message,
            code,
        )

        return

    # حذف محصول
    if data.startswith(
        "admin_delete_product:"
    ):
        code = data.split(
            ":",
            1
        )[1]

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ بله، حذف شود",
                    callback_data=f"admin_delete_yes:{code}",
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

    if data.startswith(
        "admin_delete_yes:"
    ):
        code = data.split(
            ":",
            1
        )[1]

        product = get_product(
            code
        )

        category = (
            product["category"]
            if product
            else "women"
        )

        delete_product(
            code
        )

        await query.answer(
            "محصول حذف شد ✅"
        )

        await show_admin_category(
            query.message,
            category,
        )

        return


# =========================================================
# زیبال
# =========================================================

def create_zibal_payment(
    order
):
    if not ZIBAL_MERCHANT:
        raise RuntimeError(
            "ZIBAL_MERCHANT is empty"
        )

    if not PUBLIC_URL:
        raise RuntimeError(
            "PUBLIC_URL is empty"
        )

    payload = {
        "merchant":
            ZIBAL_MERCHANT,

        "amount":
            int(order["amount_rial"]),

        "callbackUrl":
            f"{PUBLIC_URL}/zibal/callback",

        "description":
            f"Katoni 530 Order #{order['id']}",

        "mobile":
            order["mobile"],
    }

    try:
        response = requests.post(
            ZIBAL_REQUEST_URL,
            json=payload,
            timeout=25,
        )

        print(
            "ZIBAL REQUEST HTTP:",
            response.status_code
        )

        print(
            "ZIBAL REQUEST BODY:",
            response.text[:1500]
        )

        response.raise_for_status()

        data = response.json()

    except Exception as e:
        print(
            "ZIBAL REQUEST EXCEPTION:",
            repr(e)
        )

        raise

    result = int(
        data.get(
            "result",
            0
        )
    )

    if result != 100:
        print(
            "ZIBAL REQUEST RESULT ERROR:",
            data
        )

        raise RuntimeError(
            f"Zibal result={result} message={data.get('message')}"
        )

    track_id = str(
        data.get(
            "trackId",
            ""
        )
    )

    if not track_id:
        raise RuntimeError(
            "Zibal trackId missing"
        )

    return track_id


def verify_zibal(
    track_id
):
    try:
        response = requests.post(
            ZIBAL_VERIFY_URL,
            json={
                "merchant":
                    ZIBAL_MERCHANT,

                "trackId":
                    int(track_id),
            },
            timeout=25,
        )

        print(
            "ZIBAL VERIFY HTTP:",
            response.status_code
        )

        print(
            "ZIBAL VERIFY BODY:",
            response.text[:1500]
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:
        print(
            "ZIBAL VERIFY EXCEPTION:",
            repr(e)
        )

        raise


# =========================================================
# ارسال پیام از Thread پرداخت
# =========================================================

def send_telegram_sync(
    chat_id,
    text
):
    if not TOKEN:
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id":
                    str(chat_id),

                "text":
                    text,
            },
            timeout=20,
        )

        if not response.ok:
            print(
                "TELEGRAM SEND ERROR:",
                response.text[:1000]
            )

    except Exception as e:
        print(
            "TELEGRAM SEND EXCEPTION:",
            repr(e)
        )


# =========================================================
# وب‌سرور Callback زیبال
# =========================================================

class PaymentCallbackHandler(
    BaseHTTPRequestHandler
):

    def log_message(
        self,
        format,
        *args
    ):
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
                content="width=device-width, initial-scale=1"
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

        body = page.encode(
            "utf-8"
        )

        self.send_response(
            200
        )

        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    def do_GET(
        self
    ):
        parsed = urlparse(
            self.path
        )

        if parsed.path == "/":
            self.send_html(
                "کتونی 530",
                "ربات و درگاه پرداخت فعال است.",
            )

            return

        if parsed.path != "/zibal/callback":
            self.send_response(
                404
            )

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
                "شناسه پرداخت دریافت نشد.",
            )

            return

        order = get_order_by_track_id(
            track_id
        )

        if not order:
            self.send_html(
                "خطا",
                "سفارش پیدا نشد.",
            )

            return

        if order["status"] == "paid":
            self.send_html(
                "پرداخت تأیید شده است ✅",
                f"سفارش {order['id']} قبلاً ثبت شده است.",
            )

            return

        if success != "1":
            mark_order_failed(
                order["id"]
            )

            send_telegram_sync(
                order[
                    "telegram_chat_id"
                ],
                "❌ پرداخت انجام نشد یا لغو شد.\n"
                "سفارش نهایی ثبت نشده است.",
            )

            self.send_html(
                "پرداخت ناموفق بود ❌",
                "سفارش نهایی نشده است.",
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
                201,
            ):
                print(
                    "VERIFY RESULT NOT SUCCESS:",
                    verify_data
                )

                self.send_html(
                    "پرداخت تأیید نشد ❌",
                    "تأیید نهایی از درگاه دریافت نشد.",
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
            ):
                if int(
                    verified_amount
                ) != int(
                    order[
                        "amount_rial"
                    ]
                ):
                    print(
                        "AMOUNT MISMATCH:",
                        verified_amount,
                        order[
                            "amount_rial"
                        ]
                    )

                    self.send_html(
                        "خطا در مبلغ",
                        "مبلغ پرداخت با سفارش مطابقت ندارد.",
                    )

                    return

            ref_number = str(
                verify_data.get(
                    "refNumber",
                    ""
                )
                or
                track_id
            )

            stock_ok = (
                reduce_stock_after_payment(
                    order["id"]
                )
            )

            mark_order_paid(
                order["id"],
                ref_number,
            )

            if not stock_ok:
                send_telegram_sync(
                    order[
                        "telegram_chat_id"
                    ],
                    "✅ پرداخت شما تأیید شد.\n\n"
                    "⚠️ سفارش برای بررسی موجودی به پشتیبانی ارسال شد.",
                )

                if ADMIN_CHAT_ID:
                    send_telegram_sync(
                        ADMIN_CHAT_ID,
                        "⚠️ هشدار موجودی\n\n"
                        f"پرداخت سفارش #{order['id']} موفق بوده "
                        "ولی موجودی سایز هنگام ثبت نهایی صفر بوده است.\n"
                        "لطفاً سفارش را بررسی کنید.",
                    )

                self.send_html(
                    "پرداخت موفق بود ✅",
                    "سفارش در حال بررسی موجودی است.",
                )

                return

            remaining = get_stock(
                order[
                    "product_code"
                ],
                order[
                    "size"
                ],
            )

            customer_message = (
                "🎉 پرداخت با موفقیت تأیید شد\n\n"
                f"🧾 شماره سفارش: {order['id']}\n"
                f"👟 محصول: {order['product_name']}\n"
                f"🏷 کد: {order['product_code']}\n"
                f"📏 سایز: {order['size']}\n"
                f"💰 قیمت کفش: {money(order['product_price_toman'])} تومان\n"
                f"🚚 ارسال: {money(order['shipping_toman'])} تومان\n"
                f"💳 مبلغ پرداختی: {money(order['amount_toman'])} تومان\n"
                f"🔐 پیگیری پرداخت: {ref_number}\n\n"
                "✅ سفارش شما ثبت نهایی شد."
            )

            send_telegram_sync(
                order[
                    "telegram_chat_id"
                ],
                customer_message,
            )

            if ADMIN_CHAT_ID:
                admin_message = (
                    "🔔 سفارش جدید پرداخت شد\n\n"
                    f"🧾 سفارش: #{order['id']}\n"
                    f"👟 {order['product_name']}\n"
                    f"🏷 کد: {order['product_code']}\n"
                    f"📏 سایز: {order['size']}\n"
                    f"💰 قیمت کفش: {money(order['product_price_toman'])} تومان\n"
                    f"🚚 ارسال: {money(order['shipping_toman'])} تومان\n"
                    f"💳 کل پرداخت: {money(order['amount_toman'])} تومان\n\n"
                    f"👤 مشتری: {order['customer_name']}\n"
                    f"📱 موبایل: {order['mobile']}\n"
                    f"📍 آدرس: {order['address']}\n\n"
                    f"📦 موجودی باقی‌مانده سایز {order['size']}: {remaining} جفت"
                )

                send_telegram_sync(
                    ADMIN_CHAT_ID,
                    admin_message,
                )

            self.send_html(
                "پرداخت موفق بود ✅",
                f"سفارش شماره {order['id']} ثبت شد.",
            )

        except Exception as e:
            print(
                "PAYMENT CALLBACK ERROR:",
                repr(e)
            )

            self.send_html(
                "خطا در بررسی پرداخت",
                "اگر مبلغ از حساب شما کسر شده، دوباره پرداخت نکنید.",
            )


def start_http_server():
    server = ThreadingHTTPServer(
        (
            "0.0.0.0",
            PORT,
        ),
        PaymentCallbackHandler,
    )

    print(
        f"HTTP SERVER STARTED ON PORT {PORT}"
    )

    server.serve_forever()


# =========================================================
# پیام‌های متنی
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    if not update.effective_user:
        return

    if update.message.text is None:
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id

    if not await is_member(
        context.bot,
        user_id,
    ):
        await show_join_message(
            update
        )

        return

    ud = user_data_safe(
        context
    )

    # لغو / خانه
    if text in (
        "❌ لغو عملیات",
        "🏠 بازگشت به منوی اصلی",
    ):
        clear_mode(
            context
        )

        await update.message.reply_text(
            "🏠 منوی اصلی کتونی 530",
            reply_markup=main_keyboard(
                user_id
            ),
        )

        return

    # =====================================================
    # افزودن محصول
    # =====================================================

    if ud.get(
        "admin_add_product"
    ):
        if not is_admin(
            user_id
        ):
            clear_mode(
                context
            )

            return

        step = ud.get(
            "admin_step"
        )

        # کد
        if step == "code":
            code = normalize_code(
                text
            )

            if not code:
                await update.message.reply_text(
                    "❌ کد باید بین 001 تا 999 باشد.\n"
                    "مثال: 007"
                )

                return

            if get_product(
                code
            ):
                await update.message.reply_text(
                    f"❌ محصول {code} قبلاً ثبت شده است."
                )

                return

            ud[
                "new_product_code"
            ] = code

            ud[
                "admin_step"
            ] = "name"

            await update.message.reply_text(
                f"✅ کد: {code}\n\n"
                "👟 نام مدل را بفرستید.\n"
                "مثال:\nNew Balance 740"
            )

            return

        # نام
        if step == "name":
            if len(
                text
            ) < 2:
                await update.message.reply_text(
                    "نام محصول را وارد کنید."
                )

                return

            ud[
                "new_product_name"
            ] = text

            ud[
                "admin_step"
            ] = "price"

            await update.message.reply_text(
                "💰 قیمت محصول را فقط به تومان بفرستید.\n\n"
                "مثال:\n7900000"
            )

            return

        # قیمت
        if step == "price":
            price_text = (
                text
                .replace(",", "")
                .replace("٬", "")
                .replace(" ", "")
            )

            if not price_text.isdigit():
                await update.message.reply_text(
                    "❌ فقط عدد قیمت را بفرستید.\n"
                    "مثال: 7900000"
                )

                return

            ud[
                "new_product_price"
            ] = int(
                price_text
            )

            ud[
                "admin_step"
            ] = "category"

            keyboard = ReplyKeyboardMarkup(
                [
                    [
                        "👟 زنانه",
                        "👞 مردانه",
                    ],
                    [
                        "❌ لغو عملیات",
                    ],
                ],
                resize_keyboard=True,
            )

            await update.message.reply_text(
                "این محصول زنانه است یا مردانه؟",
                reply_markup=keyboard,
            )

            return

        # دسته
        if step == "category":
            if text == "👟 زنانه":
                category = "women"

            elif text == "👞 مردانه":
                category = "men"

            else:
                await update.message.reply_text(
                    "یکی از گزینه‌های زنانه یا مردانه را انتخاب کنید."
                )

                return

            code = ud[
                "new_product_code"
            ]

            name = ud[
                "new_product_name"
            ]

            price = ud[
                "new_product_price"
            ]

            success = create_product(
                code,
                name,
                price,
                category,
            )

            clear_mode(
                context
            )

            if not success:
                await update.message.reply_text(
                    "❌ محصول ثبت نشد.",
                    reply_markup=main_keyboard(
                        user_id
                    ),
                )

                return

            await update.message.reply_text(
                "✅ محصول ثبت شد.\n\n"
                "حالا از مدیریت محصول با ➕ موجودی سایزها را تنظیم کن و عکس کفش را اضافه کن.",
                reply_markup=main_keyboard(
                    user_id
                ),
            )

            await show_admin_product(
                update.message,
                code,
            )

            return

    # =====================================================
    # تغییر قیمت
    # =====================================================

    if ud.get(
        "admin_change_price"
    ):
        if not is_admin(
            user_id
        ):
            clear_mode(
                context
            )

            return

        code = ud[
            "admin_change_price"
        ]

        price_text = (
            text
            .replace(",", "")
            .replace("٬", "")
            .replace(" ", "")
        )

        if not price_text.isdigit():
            await update.message.reply_text(
                "❌ قیمت را فقط به عدد بفرستید."
            )

            return

        update_product_price(
            code,
            int(price_text),
        )

        clear_mode(
            context
        )

        await update.message.reply_text(
            "✅ قیمت تغییر کرد."
        )

        await show_admin_product(
            update.message,
            code,
        )

        return

    # =====================================================
    # تغییر نام
    # =====================================================

    if ud.get(
        "admin_change_name"
    ):
        if not is_admin(
            user_id
        ):
            clear_mode(
                context
            )

            return

        code = ud[
            "admin_change_name"
        ]

        update_product_name(
            code,
            text,
        )

        clear_mode(
            context
        )

        await update.message.reply_text(
            "✅ نام محصول تغییر کرد."
        )

        await show_admin_product(
            update.message,
            code,
        )

        return

    # =====================================================
    # سفارش
    # =====================================================

    if ud.get(
        "ordering"
    ):
        step = ud.get(
            "step"
        )

        if step == "name":
            if len(
                text
            ) < 2:
                await update.message.reply_text(
                    "نام و نام خانوادگی را وارد کنید."
                )

                return

            ud[
                "customer_name"
            ] = text

            ud[
                "step"
            ] = "mobile"

            await update.message.reply_text(
                "📱 شماره موبایل را وارد کنید.\n"
                "مثال: 09123456789",
                reply_markup=cancel_keyboard(),
            )

            return

        if step == "mobile":
            mobile = (
                text
                .replace(" ", "")
                .replace("-", "")
            )

            if (
                not mobile.isdigit()
                or
                len(mobile) != 11
                or
                not mobile.startswith(
                    "09"
                )
            ):
                await update.message.reply_text(
                    "❌ شماره موبایل صحیح نیست.\n"
                    "مثال: 09123456789"
                )

                return

            ud[
                "mobile"
            ] = mobile

            ud[
                "step"
            ] = "address"

            await update.message.reply_text(
                "📍 آدرس کامل ارسال را بفرستید:",
                reply_markup=cancel_keyboard(),
            )

            return

        if step == "address":
            if len(
                text
            ) < 5:
                await update.message.reply_text(
                    "آدرس کامل‌تری وارد کنید."
                )

                return

            code = ud[
                "product_code"
            ]

            size = ud[
                "size"
            ]

            product = get_product(
                code
            )

            if not product:
                clear_mode(
                    context
                )

                return

            if get_stock(
                code,
                size
            ) <= 0:
                clear_mode(
                    context
                )

                await update.message.reply_text(
                    "❌ متأسفانه این سایز همین الان ناموجود شده است.",
                    reply_markup=main_keyboard(
                        user_id
                    ),
                )

                return

            customer_name = ud[
                "customer_name"
            ]

            mobile = ud[
                "mobile"
            ]

            try:
                order_id = create_order(
                    telegram_user_id=
                        user_id,

                    telegram_chat_id=
                        update.effective_chat.id,

                    product_code=
                        code,

                    product_name=
                        product["name"],

                    size=
                        size,

                    product_price_toman=
                        product["price"],

                    customer_name=
                        customer_name,

                    mobile=
                        mobile,

                    address=
                        text,
                )

                order = get_order(
                    order_id
                )

                print(
                    "CREATING ZIBAL PAYMENT FOR ORDER:",
                    order_id
                )

                track_id = create_zibal_payment(
                    order
                )

                set_track_id(
                    order_id,
                    track_id,
                )

                payment_url = (
                    f"{ZIBAL_START_URL}{track_id}"
                )

                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "💳 پرداخت آنلاین",
                            url=payment_url,
                        )
                    ]
                ])

                await update.message.reply_text(
                    "🧾 فاکتور سفارش\n\n"
                    f"🔢 شماره سفارش: {order_id}\n"
                    f"👟 محصول: {product['name']}\n"
                    f"🏷 کد: {code}\n"
                    f"📏 سایز: {size}\n\n"
                    f"💰 قیمت کفش: {money(product['price'])} تومان\n"
                    f"🚚 هزینه ارسال: {money(SHIPPING_COST)} تومان\n"
                    f"💳 مبلغ نهایی: {money(product['price'] + SHIPPING_COST)} تومان\n\n"
                    f"👤 نام: {customer_name}\n"
                    f"📱 موبایل: {mobile}\n"
                    f"📍 آدرس: {text}\n\n"
                    "⚠️ سفارش بعد از پرداخت موفق ثبت نهایی می‌شود.",
                    reply_markup=keyboard,
                )

                clear_mode(
                    context
                )

            except Exception as e:
                print(
                    "PAYMENT ERROR:",
                    repr(e)
                )

                clear_mode(
                    context
                )

                await update.message.reply_text(
                    "❌ اتصال به درگاه انجام نشد.\n\n"
                    "هیچ مبلغی از حساب شما کسر نشده است.",
                    reply_markup=main_keyboard(
                        user_id
                    ),
                )

            return

    # =====================================================
    # جستجو
    # =====================================================

    if ud.get(
        "searching"
    ):
        clear_mode(
            context
        )

        await send_product(
            update.message,
            text,
        )

        return

    # =====================================================
    # پیگیری
    # =====================================================

    if ud.get(
        "tracking"
    ):
        try:
            order_id = int(
                text
            )

        except ValueError:
            await update.message.reply_text(
                "❌ شماره سفارش باید عدد باشد."
            )

            return

        order = get_user_order(
            order_id,
            user_id,
        )

        clear_mode(
            context
        )

        if not order:
            await update.message.reply_text(
                "❌ سفارش پیدا نشد.",
                reply_markup=main_keyboard(
                    user_id
                ),
            )

            return

        status_map = {
            "waiting_payment":
                "⏳ در انتظار پرداخت",

            "paid":
                "✅ پرداخت شده و ثبت نهایی شده",

            "payment_failed":
                "❌ پرداخت ناموفق یا لغو شده",
        }

        await update.message.reply_text(
            "📦 وضعیت سفارش\n\n"
            f"🔢 شماره: {order['id']}\n"
            f"👟 {order['product_name']}\n"
            f"🏷 کد: {order['product_code']}\n"
            f"📏 سایز: {order['size']}\n"
            f"💰 مبلغ: {money(order['amount_toman'])} تومان\n"
            f"📌 وضعیت: {status_map.get(order['status'], order['status'])}",
            reply_markup=main_keyboard(
                user_id
            ),
        )

        return

    # =====================================================
    # پشتیبانی متنی
    # =====================================================

    if ud.get(
        "support_mode"
    ):
        if not ADMIN_CHAT_ID:
            clear_mode(
                context
            )

            return

        user = update.effective_user

        message_text = (
            "📩 پیام جدید مشتری\n\n"
            f"👤 {user.full_name}\n"
            f"🆔 {user.id}\n\n"
            f"💬 {text}"
        )

        try:
            await context.bot.send_message(
                chat_id=int(
                    ADMIN_CHAT_ID
                ),
                text=message_text,
            )

            clear_mode(
                context
            )

            await update.message.reply_text(
                "✅ پیام شما برای پشتیبانی ارسال شد.",
                reply_markup=support_keyboard(),
            )

        except Exception as e:
            print(
                "SUPPORT ERROR:",
                repr(e)
            )

        return

    # =====================================================
    # منوی اصلی
    # =====================================================

    if text == "🔥 جدیدترین مدل‌ها":
        await show_latest_products(
            update.message
        )

        return

    if text == "👟 کفش زنانه":
        await show_category(
            update.message,
            "women",
        )

        return

    if text == "👞 کفش مردانه":
        await show_category(
            update.message,
            "men",
        )

        return

    if text in (
        "🔎 جستجو با کد محصول",
        "💰 قیمت و موجودی",
        "💰 استعلام قیمت و موجودی",
    ):
        clear_mode(
            context
        )

        if context.user_data is not None:
            context.user_data[
                "searching"
            ] = True

        await update.message.reply_text(
            "🔎 کد محصول را وارد کنید.\n"
            "مثال: 003",
            reply_markup=cancel_keyboard(),
        )

        return

    if text == "🛒 ثبت سفارش":
        await show_latest_products(
            update.message
        )

        return

    if text == "📦 پیگیری سفارش":
        clear_mode(
            context
        )

        if context.user_data is not None:
            context.user_data[
                "tracking"
            ] = True

        await update.message.reply_text(
            "📦 شماره سفارش را وارد کنید:",
            reply_markup=cancel_keyboard(),
        )

        return

    if text in (
        "📏 راهنمای سایز",
        "📏 راهنمای انتخاب سایز",
    ):
        await update.message.reply_text(
            "📏 سایزبندی فروشگاه\n\n"
            "👟 زنانه: 37، 38، 39، 40\n"
            "👞 مردانه: 41، 42، 43، 44، 45",
            reply_markup=main_keyboard(
                user_id
            ),
        )

        return

    if text == "💳 پرداخت و مشکلات پرداخت":
        await update.message.reply_text(
            "💳 پرداخت سفارش از طریق درگاه امن انجام می‌شود.\n\n"
            "اگر مبلغ کسر شد ولی سفارش تأیید نشد، دوباره پرداخت نکنید و با پشتیبانی تماس بگیرید.",
            reply_markup=support_keyboard(),
        )

        return

    if text == "👨‍💬 پشتیبانی":
        await update.message.reply_text(
            "👨‍💬 مرکز پشتیبانی کتونی 530",
            reply_markup=support_keyboard(),
        )

        return

    if text == "🛍 راهنمای خرید":
        await update.message.reply_text(
            "🛍 راهنمای خرید\n\n"
            "1️⃣ محصول را انتخاب کنید.\n"
            "2️⃣ سایز را انتخاب کنید.\n"
            "3️⃣ مشخصات را وارد کنید.\n"
            "4️⃣ مبلغ کفش + 350 هزار تومان ارسال را پرداخت کنید.\n"
            "5️⃣ بعد از پرداخت موفق، موجودی همان سایز خودکار یک عدد کم می‌شود.",
            reply_markup=support_keyboard(),
        )

        return

    if text in (
        "💳 مشکل پرداخت",
        "🔄 تعویض / مشکل سفارش",
        "👨‍💼 ارتباط مستقیم با پشتیبان",
    ):
        clear_mode(
            context
        )

        if context.user_data is not None:
            context.user_data[
                "support_mode"
            ] = True

        await update.message.reply_text(
            "👨‍💬 پیام خود را بفرستید.\n"
            "می‌توانید عکس هم ارسال کنید.",
            reply_markup=cancel_keyboard(),
        )

        return

    if text == "📣 کانال تلگرام":
        await update.message.reply_text(
            "📣 کانال رسمی کتونی 530 👇",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📣 ورود به کانال",
                        url=CHANNEL_LINK,
                    )
                ]
            ]),
        )

        return

    if text == "🔐 مدیریت فروشگاه":
        if not is_admin(
            user_id
        ):
            await update.message.reply_text(
                "⛔ دسترسی ندارید."
            )

            return

        await show_admin_home(
            update.message
        )

        return

    await update.message.reply_text(
        "یکی از گزینه‌های منو را انتخاب کنید 👇",
        reply_markup=main_keyboard(
            user_id
        ),
    )


# =========================================================
# دریافت عکس و فایل
# رفع خطای NoneType
# =========================================================

async def media_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    # این کنترل‌ها جلوی همان خطای NoneType را می‌گیرند
    if update is None:
        return

    if update.message is None:
        return

    if update.effective_user is None:
        return

    if context is None:
        return

    ud = user_data_safe(
        context
    )

    user_id = update.effective_user.id

    # =====================================================
    # عکس محصول توسط مدیر
    # =====================================================

    product_code = ud.get(
        "admin_photo_product"
    )

    if product_code:
        if not is_admin(
            user_id
        ):
            clear_mode(
                context
            )

            return

        if not update.message.photo:
            await update.message.reply_text(
                "❌ لطفاً عکس کفش را به‌صورت Photo ارسال کنید."
            )

            return

        # بزرگ‌ترین نسخه عکس
        file_id = (
            update.message.photo[-1].file_id
        )

        update_product_photo(
            product_code,
            file_id,
        )

        clear_mode(
            context
        )

        await update.message.reply_text(
            f"✅ عکس محصول {product_code} ذخیره شد."
        )

        await show_admin_product(
            update.message,
            product_code,
        )

        return

    # =====================================================
    # عکس / فایل پشتیبانی مشتری
    # =====================================================

    if not ud.get(
        "support_mode"
    ):
        return

    if not ADMIN_CHAT_ID:
        clear_mode(
            context
        )

        return

    user = update.effective_user

    try:
        await context.bot.send_message(
            chat_id=int(
                ADMIN_CHAT_ID
            ),
            text=(
                "📩 عکس/فایل جدید مشتری\n\n"
               

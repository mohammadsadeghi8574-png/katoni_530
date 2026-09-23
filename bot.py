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
# منوها
# =========================================================

def main_keyboard(
    user_id=None
):
    buttons = [
        ["🔥 جدیدترین مدل‌ها"],
        [
            "👟 کفش زنانه",
            "👟 کفش مردانه",
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
            "Membership error:",
            e
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
# نمایش محصول
# =========================================================

async def send_product(
    message,
    code
):
    code = normalize_code(
        code
    )

    if not code:
        await message.reply_text(
            "❌ کد محصول باید بین 001 تا 999 باشد."
        )
        return

    product = get_product(
        code
    )

    if not product:
        await message.reply_text(
            f"❌ محصول با کد {code} هنوز ثبت نشده است."
        )
        return

    sizes = allowed_sizes(
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

    if available_sizes:
        sizes_text = " - ".join(
            available_sizes
        )

        stock_text = (
            f"📏 سایزهای موجود: {sizes_text}"
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
        stock_text = (
            "❌ فعلاً ناموجود"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ ناموجود",
                    callback_data="nothing",
                )
            ]
        ])

    category_name = (
        "زنانه"
        if product["category"] == "women"
        else "مردانه"
    )

    caption = (
        f"👟 {product['name']}\n\n"
        f"🏷 کد محصول: {code}\n"
        f"👤 دسته: {category_name}\n"
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
            print(
                "Photo error:",
                e
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
    products = (
        get_products_by_category(
            category
        )
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

async def show_admin_panel(
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
    products = (
        get_products_by_category(
            category
        )
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
        "محصول موردنظر را انتخاب کنید 👇",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


async def show_admin_inventory(
    message,
    code
):
    product = get_product(
        code
    )

    if not product:
        await message.reply_text(
            "❌ محصول پیدا نشد."
        )
        return

    category = product[
        "category"
    ]

    sizes = allowed_sizes(
        category
    )

    category_name = (
        "زنانه"
        if category == "women"
        else "مردانه"
    )

    text = (
        "📦 مدیریت موجودی\n\n"
        f"👟 {product['name']}\n"
        f"🏷 کد: {product['code']}\n"
        f"👤 دسته: {category_name}\n"
        f"💰 قیمت: {money(product['price'])} تومان\n\n"
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
            callback_data=f"admin_category:{category}",
        )
    ])

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


# =========================================================
# /start
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    clear_mode(
        context
    )

    user_id = (
        update.effective_user.id
    )

    if not await is_member(
        context.bot,
        user_id,
    ):
        if context.args:
            code = normalize_code(
                context.args[0]
            )

            if code:
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

        if code:
            await update.message.reply_text(
                "👋 به فروشگاه کتونی 530 خوش آمدید.",
                reply_markup=main_keyboard(
                    user_id
                ),
            )

            await send_product(
                update.message,
                code,
            )

            return

    await update.message.reply_text(
        "👟 به فروشگاه کتونی 530 خوش آمدید\n\n"
        "🔥 جدیدترین مدل‌ها را ببینید 👇",
        reply_markup=main_keyboard(
            user_id
        ),
    )

    await show_latest_products(
        update.message
    )


# =========================================================
# دکمه‌ها
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = (
        update.callback_query
    )

    data = query.data
    user_id = query.from_user.id

    await query.answer()

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

        pending = (
            context.user_data.pop(
                "pending_product",
                None,
            )
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

    if data == "nothing":
        return

    # خرید محصول
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
            return

        buttons = []

        for size in allowed_sizes(
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
            f"💰 قیمت: {money(product['price'])} تومان\n\n"
            "📏 سایز موردنظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(
                buttons
            ),
        )

        return

    # انتخاب سایز
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

        clear_mode(
            context
        )

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

    # مدیریت فقط ادمین
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

    # صفحه اصلی مدیریت
    if data == "admin_home":
        await show_admin_panel(
            query.message
        )
        return

    # دسته‌بندی مدیریت
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
        clear_mode(
            context
        )

        context.user_data[
            "admin_add_product"
        ] = True

        context.user_data[
            "admin_step"
        ] = "code"

        await query.message.reply_text(
            "➕ افزودن محصول جدید\n\n"
            "🏷 کد محصول را وارد کنید.\n\n"
            "از 001 تا 999\n"
            "مثال: 006",
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

        await show_admin_inventory(
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

        await show_admin_inventory(
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

        await show_admin_inventory(
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

        clear_mode(
            context
        )

        context.user_data[
            "admin_change_price"
        ] = True

        context.user_data[
            "admin_product_code"
        ] = code

        await query.message.reply_text(
            f"💰 قیمت جدید محصول {code} را به تومان بفرستید.\n\n"
            "مثال: 8750000",
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

        clear_mode(
            context
        )

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

    if data.startswith(
        "admin_confirm_delete:"
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
        raise Exception(
            "ZIBAL_MERCHANT تنظیم نشده است."
        )

    if not PUBLIC_URL:
        raise Exception(
            "PUBLIC_URL تنظیم نشده است."
        )

    payload = {
        "merchant": ZIBAL_MERCHANT,
        "amount": int(
            order["amount_rial"]
        ),
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

    if int(
        data.get(
            "result",
            0
        )
    ) != 100:
        raise Exception(
            data.get(
                "message",
                "Zibal payment error",
            )
        )

    track_id = str(
        data.get(
            "trackId",
            ""
        )
    )

    if not track_id:
        raise Exception(
            "trackId دریافت نشد."
        )

    return track_id


def verify_zibal(
    track_id
):
    response = requests.post(
        ZIBAL_VERIFY_URL,
        json={
            "merchant":
                ZIBAL_MERCHANT,

            "trackId":
                int(track_id),
        },
        timeout=20,
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# ارسال پیام تلگرام بعد از پرداخت
# =========================================================

def send_telegram_sync(
    chat_id,
    text
):
    if not TOKEN:
        return

    async def sender():
        bot = Bot(
            token=TOKEN
        )

        try:
            await bot.send_message(
                chat_id=int(
                    chat_id
                ),
                text=text,
            )

        finally:
            await bot.shutdown()

    try:
        asyncio.run(
            sender()
        )

    except Exception as e:
        print(
            "Telegram callback error:",
            e
        )


# =========================================================
# Callback زیبال
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

        order = (
            get_order_by_track_id(
                track_id
            )
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

            send_telegram_sync(
                order[
                    "telegram_chat_id"
                ],
                "🎉 پرداخت با موفقیت تأیید شد\n\n"
                f"🧾 شماره سفارش: {order['id']}\n"
                f"👟 محصول: {order['product_name']}\n"
                f"🏷 کد: {order['product_code']}\n"
                f"📏 سایز: {order['size']}\n"
                f"💰 مبلغ: {money(order['amount_toman'])} تومان\n"
                f"🔐 پیگیری پرداخت: {ref_number}\n\n"
                "✅ سفارش شما ثبت نهایی شد.",
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
                    f"📦 موجودی باقی‌مانده سایز {order['size']}: {remaining}",
                )

            self.send_html(
                "پرداخت موفق بود ✅",
                f"سفارش شماره {order['id']} ثبت شد.",
            )

        except Exception as e:
            print(
                "VERIFY ERROR:",
                e
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
        f"HTTP server running on port {PORT}"
    )

    server.serve_forever()


# =========================================================
# پیام‌های متنی
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if (
        not update.message
        or
        not update.message.text
    ):
        return

    text = (
        update.message.text.strip()
    )

    user_id = (
        update.effective_user.id
    )

    if not await is_member(
        context.bot,
        user_id,
    ):
        await show_join_message(
            update
        )

        return

    # خانه / لغو
    if text in (
        "🏠 بازگشت به منوی اصلی",
        "❌ لغو عملیات",
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

    if context.user_data.get(
        "admin_add_product"
    ):
        if not is_admin(
            user_id
        ):
            clear_mode(
                context
            )
            return

        step = (
            context.user_data.get(
                "admin_step"
            )
        )

        # کد
        if step == "code":
            code = normalize_code(
                text
            )

            if not code:
                await update.message.reply_text(
                    "❌ کد باید بین 001 تا 999 باشد.\n"
                    "مثال: 006"
                )

                return

            if get_product(
                code
            ):
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
                f"✅ کد: {code}\n\n"
                "👟 نام مدل را بفرستید.\n"
                "مثال:\nNew Balance 1906R"
            )

            return

        # نام
        if step == "name":
            if len(
                text
            ) < 2:
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
                text
                .replace(",", "")
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
            ] = int(
                price_text
            )

            context.user_data[
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

        # دسته‌بندی
        if step == "category":
            category_map = {
                "👟 زنانه":
                    "women",

                "👞 مردانه":
                    "men",
            }

            if text not in category_map:
                await update.message.reply_text(
                    "یکی از گزینه‌ها را انتخاب کنید."
                )

                return

            code = (
                context.user_data[
                    "new_product_code"
                ]
            )

            name = (
                context.user_data[
                    "new_product_name"
                ]
            )

            price = (
                context.user_data[
                    "new_product_price"
                ]
            )

            category = (
                category_map[
                    text
                ]
            )

            success = add_product(
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

            if category == "women":
                sizes_text = (
                    "37، 38، 39، 40"
                )

            else:
                sizes_text = (
                    "41، 42، 43، 44، 45"
                )

            await update.message.reply_text(
                "✅ محصول ثبت شد.\n\n"
                f"🏷 کد: {code}\n"
                f"👟 {name}\n"
                f"💰 {money(price)} تومان\n"
                f"📏 سایزها: {sizes_text}\n\n"
                "حالا با ➕ موجودی هر سایز را وارد کن.",
                reply_markup=main_keyboard(
                    user_id
                ),
            )

            await show_admin_inventory(
                update.message,
                code,
            )

            return

    # =====================================================
    # تغییر قیمت
    # =====================================================

    if context.user_data.get(
        "admin_change_price"
    ):
        if not is_admin(
            user_id
        ):
            clear_mode(
                context
            )

            return

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

        code = (
            context.user_data[
                "admin_product_code"
            ]
        )

        update_product_price(
            code,
            int(price_text),
        )

        clear_mode(
            context
        )

        await update.message.reply_text(
            "✅ قیمت محصول تغییر کرد."
        )

        await show_admin_inventory(
            update.message,
            code,
        )

        return

    # =====================================================
    # تغییر نام
    # =====================================================

    if context.user_data.get(
        "admin_change_name"
    ):
        if not is_admin(
            user_id
        ):
            clear_mode(
                context
            )

            return

        code = (
            context.user_data[
                "admin_product_code"
            ]
        )

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

        await show_admin_inventory(
            update.message,
            code,
        )

        return

    # =====================================================
    # سفارش
    # =====================================================

    if context.user_data.get(
        "ordering"
    ):
        step = (
            context.user_data.get(
                "step"
            )
        )

        if step == "name":
            context.user_data[
                "customer_name"
            ] = text

            context.user_data[
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
                    "❌ شماره موبایل صحیح نیست."
                )

                return

            context.user_data[
                "mobile"
            ] = mobile

            context.user_data[
                "step"
            ] = "address"

            await update.message.reply_text(
                "📍 آدرس کامل ارسال را بفرستید:",
                reply_markup=cancel_keyboard(),
            )

            return

        if step == "address":
            code = (
                context.user_data[
                    "product_code"
                ]
            )

            size = (
                context.user_data[
                    "size"
                ]
            )

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
                    "❌ این سایز همین الان ناموجود شده است.",
                    reply_markup=main_keyboard(
                        user_id
                    ),
                )

                return

            try:
                order_id = create_order(
                    telegram_user_id=user_id,
                    telegram_chat_id=update.effective_chat.id,
                    product_code=code,
                    product_name=product["name"],
                    size=size,
                    amount_toman=product["price"],
                    customer_name=context.user_data[
                        "customer_name"
                    ],
                    mobile=context.user_data[
                        "mobile"
                    ],
                    address=text,
                )

                order = get_order(
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
                    f"📏 سایز: {size}\n"
                    f"💰 مبلغ: {money(product['price'])} تومان\n\n"
                    "⚠️ سفارش بعد از پرداخت موفق ثبت نهایی می‌شود.",
                    reply_markup=keyboard,
                )

                clear_mode(
                    context
                )

            except Exception as e:
                print(
                    "PAYMENT ERROR:",
                    e
                )

                clear_mode(
                    context
                )

                await update.message.reply_text(
                    "❌ اتصال به درگاه انجام نشد.",
                    reply_markup=main_keyboard(
                        user_id
                    ),
                )

            return

    # =====================================================
    # جستجو
    # =====================================================

    if context.user_data.get(
        "searching"
    ):
        clear_mode(
            context
        )

        code = normalize_code(
            text
        )

        if not code:
            await update.message.reply_text(
                "❌ کد باید بین 001 تا 999 باشد."
            )

            return

        await send_product(
            update.message,
            code,
        )

        return

    # =====================================================
    # پیگیری
    # =====================================================

    if context.user_data.get(
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

        if not order:
            await update.message.reply_text(
                "❌ سفارش پیدا نشد."
            )

            return

        status_map = {
            "paid":
                "✅ پرداخت شده و ثبت نهایی شده",

            "waiting_payment":
                "⏳ در انتظار پرداخت",

            "payment_failed":
                "❌ پرداخت ناموفق یا لغو شده",
        }

        clear_mode(
            context
        )

        await update.message.reply_text(
            "📦 وضعیت سفارش\n\n"
            f"🔢 شماره: {order['id']}\n"
            f"👟 {order['product_name']}\n"
            f"🏷 کد: {order['product_code']}\n"
            f"📏 سایز: {order['size']}\n"
            f"📌 وضعیت: {status_map.get(order['status'], order['status'])}",
            reply_markup=main_keyboard(
                user_id
            ),
        )

        return

    # =====================================================
    # پشتیبانی
    # =====================================================

    if context.user_data.get(
        "support_mode"
    ):
        if not ADMIN_CHAT_ID:
            clear_mode(
                context
            )

            return

        user = (
            update.effective_user
        )

        support_text = (
            "📩 پیام جدید مشتری\n\n"
            f"👤 {user.full_name}\n"
            f"🆔 {user.id}\n\n"
            f"💬 {text}"
        )

        await context.bot.send_message(
            chat_id=int(
                ADMIN_CHAT_ID
            ),
            text=support_text,
        )

        clear_mode(
            context
        )

        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد.",
            reply_markup=support_keyboard(),
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

    if text == "👟 کفش مردانه":
        await show_category(
            update.message,
            "men",
        )
        return

    if text == "🔎 جستجو با کد محصول":
        clear_mode(
            context
        )

        context.user_data[
            "searching"
        ] = True

        await update.message.reply_text(
            "🔎 کد محصول را وارد کنید.\n"
            "مثال: 006",
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

        context.user_data[
            "tracking"
        ] = True

        await update.message.reply_text(
            "📦 شماره سفارش را وارد کنید:",
            reply_markup=cancel_keyboard(),
        )

        return

    if text in (
        "💰 قیمت و موجودی",
        "💰 استعلام قیمت و موجودی",
    ):
        clear_mode(
            context
        )

        context.user_data[
            "searching"
        ] = True

        await update.message.reply_text(
            "🏷 کد محصول را وارد کنید.\n"
            "مثال: 006",
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
            reply_markup=support_keyboard(),
        )

        return

    if text == "💳 پرداخت و مشکلات پرداخت":
        await update.message.reply_text(
            "💳 پرداخت از طریق درگاه امن انجام می‌شود.\n\n"
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
            "1️⃣ مدل را انتخاب کنید.\n"
            "2️⃣ سایز را انتخاب کنید.\n"
            "3️⃣ مشخصات را وارد کنید.\n"
            "4️⃣ پرداخت کنید.\n"
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

        context.user_data[
            "support_mode"
        ] = True

        await update.message.reply_text(
            "👨‍💬 پیام خود را بفرستید:",
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

        await show_admin_panel(
            update.message
        )

        return

    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های منو را انتخاب کنید 👇",
        reply_markup=main_keyboard(
            user_id
        ),
    )


# =========================================================
# عکس / فایل پشتیبانی
# =========================================================

async def media_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not context.user_data.get(
        "support_mode"
    ):
        return

    if not ADMIN_CHAT_ID:
        return

    user = (
        update.effective_user
    )

    await context.bot.send_message(
        chat_id=int(
            ADMIN_CHAT_ID
        ),
        text=(
            "📩 عکس/فایل مشتری\n\n"
            f"👤 {user.full_name}\n"
            f"🆔 {user.id}"
        ),
    )

    await update.message.copy(
        chat_id=int(
            ADMIN_CHAT_ID
        )
    )

    clear_mode(
        context
    )

    await update.message.reply_text(
        "✅ برای پشتیبانی ارسال شد.",
        reply_markup=support_keyboard(),
    )


# =========================================================
# دستورات
# =========================================================

async def products_command(
    update,
    context
):
    clear_mode(
        context
    )

    await show_latest_products(
        update.message
    )


async def search_command(
    update,
    context
):
    clear_mode(
        context
    )

    context.user_data[
        "searching"
    ] = True

    await update.message.reply_text(
        "🔎 کد محصول را بفرستید.\n"
        "مثال: 006",
        reply_markup=cancel_keyboard(),
    )


async def order_command(
    update,
    context
):
    clear_mode(
        context
    )

    await show_latest_products(
        update.message
    )


async def track_command(
    update,
    context
):
    clear_mode(
        context
    )

    context.user_data[
        "tracking"
    ] = True

    await update.message.reply_text(
        "📦 شماره سفارش را وارد کنید:",
        reply_markup=cancel_keyboard(),
    )


async def support_command(
    update,
    context
):
    clear_mode(
        context
    )

    await update.message.reply_text(
        "👨‍💬 مرکز پشتیبانی کتونی 530",
        reply_markup=support_keyboard(),
    )


async def admin_command(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "⛔ دسترسی ندارید."
        )

        return

    clear_mode(
        context
    )

    await show_admin_panel(
        update.message
    )


# =========================================================
# اجرا
# =========================================================

def main():
    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN تنظیم نشده است."
        )

    if not ZIBAL_MERCHANT:
        raise RuntimeError(
            "ZIBAL_MERCHANT تنظیم نشده است."
        )

    if not PUBLIC_URL:
        raise RuntimeError(
            "PUBLIC_URL تنظیم نشده است."
        )

    init_db()

    http_thread = threading.Thread(
        target=start_http_server,
        daemon=True,
    )

    http_thread.start()

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "products",
            products_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "search",
            search_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "order",
            order_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "track",
            track_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "support",
            support_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_handler,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO
            | filters.Document.ALL
            | filters.VIDEO,
            media_handler,
        )
    )

    print(
        "Katoni 530 bot started successfully"
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()

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
# تنظیمات
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
# محصولات اصلی
# برای اضافه کردن محصول جدید بعداً از همین ساختار استفاده می‌کنیم
# =========================================================

PRODUCTS = {
    "005": {
        "name": "New Balance 530 🤎",
        "category": "women",
        "price": 7_250_000,
        "sizes": {
            "37": 4,
            "38": 4,
            "39": 4,
            "40": 0,
        },
        "photo": None,
    }
}


# =========================================================
# ابزارهای عمومی
# =========================================================

def money(value):
    return f"{int(value):,}"


def normalize_code(value):
    value = str(value).strip()

    if value.isdigit():
        return value.zfill(3)

    return value.upper()


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
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connection()
    cur = conn.cursor()

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

    # اگر دیتابیس قدیمی باشد و ستون stock_reduced نداشته باشد
    try:
        cur.execute("""
            ALTER TABLE orders
            ADD COLUMN stock_reduced INTEGER NOT NULL DEFAULT 0
        """)
    except sqlite3.OperationalError:
        pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            product_code TEXT NOT NULL,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (product_code, size)
        )
    """)

    # فقط اگر سایز هنوز در دیتابیس وجود ندارد،
    # موجودی اولیه وارد شود.
    for code, product in PRODUCTS.items():
        for size, quantity in product["sizes"].items():
            cur.execute("""
                INSERT OR IGNORE INTO inventory
                (product_code, size, quantity)
                VALUES (?, ?, ?)
            """, (
                code,
                size,
                quantity,
            ))

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
        ORDER BY CAST(size AS INTEGER)
    """, (code,))

    rows = cur.fetchall()
    conn.close()

    return {
        str(row["size"]): int(row["quantity"])
        for row in rows
    }


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


def change_stock(code, size, amount):
    conn = db_connection()

    try:
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

        if not row:
            if amount > 0:
                cur.execute("""
                    INSERT INTO inventory
                    (product_code, size, quantity)
                    VALUES (?, ?, ?)
                """, (
                    code,
                    str(size),
                    amount,
                ))

                conn.commit()
                return amount

            return 0

        current = int(row["quantity"])
        new_quantity = max(0, current + amount)

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

    finally:
        conn.close()


def add_size(code, size):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO inventory
        (product_code, size, quantity)
        VALUES (?, ?, 0)
    """, (
        code,
        str(size),
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


def reduce_stock_after_payment(order_id):
    """
    فقط یک بار بعد از پرداخت موفق موجودی کم می‌شود.
    """

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
            SELECT quantity
            FROM inventory
            WHERE product_code = ?
            AND size = ?
        """, (
            order["product_code"],
            order["size"],
        ))

        stock_row = cur.fetchone()

        if not stock_row:
            conn.rollback()
            return False

        current_stock = int(stock_row["quantity"])

        if current_stock <= 0:
            conn.rollback()
            return False

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
        str(ref_number or ""),
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


def cancel_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["❌ لغو عملیات"],
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

        return member.status in [
            "member",
            "administrator",
            "creator",
        ]

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
    product = PRODUCTS.get(code)

    if not product:
        await message.reply_text(
            "❌ محصولی با این کد پیدا نشد.\n\n"
            "مثال کد محصول: 005"
        )
        return

    inventory = get_inventory(code)

    available_sizes = [
        size
        for size, qty in inventory.items()
        if qty > 0
    ]

    if available_sizes:
        sizes_text = " - ".join(available_sizes)
        availability_text = f"📏 سایزهای موجود: {sizes_text}"
        button_text = "🛒 خرید این مدل"
        callback = f"buy:{code}"
    else:
        availability_text = "❌ این مدل فعلاً ناموجود است."
        button_text = "❌ ناموجود"
        callback = f"soldout:{code}"

    caption = (
        f"👟 {product['name']}\n\n"
        f"🏷 کد محصول: {code}\n"
        f"{availability_text}\n"
        f"💰 قیمت: {money(product['price'])} تومان"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                button_text,
                callback_data=callback,
            )
        ],
        [
            InlineKeyboardButton(
                "📣 کانال کتونی 530",
                url=CHANNEL_LINK,
            )
        ],
    ])

    if product.get("photo"):
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
    await message.reply_text(
        "🔥 جدیدترین مدل‌های کتونی 530\n\n"
        "مدل موردنظر را انتخاب کنید 👇"
    )

    for code in PRODUCTS:
        await send_product(message, code)


async def show_products_by_category(message, category):
    found = False

    for code, product in PRODUCTS.items():
        if product["category"] == category:
            found = True
            await send_product(message, code)

    if not found:
        await message.reply_text(
            "فعلاً مدلی در این بخش ثبت نشده است."
        )


# =========================================================
# پنل مدیریت موجودی
# =========================================================

async def show_admin_products(message):
    buttons = []

    for code, product in PRODUCTS.items():
        buttons.append([
            InlineKeyboardButton(
                f"👟 {code} | {product['name']}",
                callback_data=f"admin_product:{code}",
            )
        ])

    await message.reply_text(
        "🔐 مدیریت فروشگاه\n\n"
        "محصول موردنظر را انتخاب کنید 👇",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_admin_inventory(message, code):
    product = PRODUCTS.get(code)

    if not product:
        await message.reply_text(
            "❌ محصول پیدا نشد."
        )
        return

    inventory = get_inventory(code)

    text = (
        f"📦 مدیریت موجودی\n\n"
        f"👟 {product['name']}\n"
        f"🏷 کد: {code}\n\n"
    )

    buttons = []

    for size, qty in inventory.items():

        status = (
            f"{qty} جفت"
            if qty > 0
            else "ناموجود"
        )

        text += (
            f"📏 سایز {size}: {status}\n"
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

    buttons.append([
        InlineKeyboardButton(
            "➕ افزودن سایز",
            callback_data=f"add_size:{code}",
        ),
        InlineKeyboardButton(
            "🗑 حذف سایز",
            callback_data=f"remove_size:{code}",
        ),
    ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ محصولات",
            callback_data="admin_products",
        )
    ])

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =========================================================
# START
# لینک مستقیم:
# https://t.me/katoni_530_bot?start=005
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    clear_mode(context)

    user_id = update.effective_user.id

    if not await is_member(context.bot, user_id):

        if context.args:
            context.user_data["pending_product"] = normalize_code(
                context.args[0]
            )

        await show_join_message(update)
        return

    if context.args:
        code = normalize_code(context.args[0])

        if code in PRODUCTS:
            await update.message.reply_text(
                "👋 به فروشگاه کتونی 530 خوش آمدید.\n\n"
                "محصول انتخابی شما 👇",
                reply_markup=main_keyboard(user_id),
            )

            await send_product(
                update.message,
                code
            )
            return

    await update.message.reply_text(
        "سلام 👋\n\n"
        "👟 به فروشگاه کتونی 530 خوش آمدید\n\n"
        "🔥 جدیدترین مدل‌ها را ببینید 👇",
        reply_markup=main_keyboard(user_id),
    )

    await show_latest_products(update.message)


# =========================================================
# Callback buttons
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    # -----------------------------------------------------
    # عضویت
    # -----------------------------------------------------

    if data == "check_membership":

        if not await is_member(context.bot, user_id):
            await query.message.reply_text(
                "❌ هنوز عضویت شما تأیید نشده است."
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

        if pending and pending in PRODUCTS:
            await send_product(
                query.message,
                pending
            )
        else:
            await show_latest_products(
                query.message
            )

        return

    # -----------------------------------------------------
    # ناموجود
    # -----------------------------------------------------

    if data.startswith("soldout:"):
        await query.answer(
            "این مدل فعلاً ناموجود است.",
            show_alert=True,
        )
        return

    # -----------------------------------------------------
    # انتخاب خرید
    # -----------------------------------------------------

    if data.startswith("buy:"):
        code = normalize_code(
            data.split(":", 1)[1]
        )

        product = PRODUCTS.get(code)

        if not product:
            await query.message.reply_text(
                "❌ محصول پیدا نشد."
            )
            return

        inventory = get_inventory(code)

        buttons = []

        for size, qty in inventory.items():

            if qty <= 0:
                continue

            buttons.append([
                InlineKeyboardButton(
                    f"سایز {size}",
                    callback_data=f"size:{code}:{size}",
                )
            ])

        if not buttons:
            await query.message.reply_text(
                "❌ متأسفانه موجودی این مدل تمام شده است."
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

        code = normalize_code(code)
        product = PRODUCTS.get(code)

        if not product:
            await query.message.reply_text(
                "❌ محصول پیدا نشد."
            )
            return

        stock = get_stock(code, size)

        if stock <= 0:
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
            f"👟 محصول: {product['name']}\n"
            f"🏷 کد: {code}\n"
            f"📏 سایز: {size}\n"
            f"💰 مبلغ: {money(product['price'])} تومان\n\n"
            "👤 نام و نام خانوادگی خود را بفرستید:",
            reply_markup=cancel_keyboard(),
        )

        return

    # =====================================================
    # مدیریت فروشگاه
    # =====================================================

    if data == "nothing":
        return

    if data == "admin_products":

        if not is_admin(user_id):
            await query.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        await show_admin_products(
            query.message
        )
        return

    if data.startswith("admin_product:"):

        if not is_admin(user_id):
            await query.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        code = normalize_code(
            data.split(":", 1)[1]
        )

        await show_admin_inventory(
            query.message,
            code
        )
        return

    # -----------------------------------------------------
    # زیاد کردن موجودی
    # -----------------------------------------------------

    if data.startswith("stock_plus:"):

        if not is_admin(user_id):
            await query.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        _, code, size = data.split(":", 2)

        new_qty = change_stock(
            code,
            size,
            1
        )

        await query.answer(
            f"✅ سایز {size}: {new_qty} جفت"
        )

        await show_admin_inventory(
            query.message,
            code
        )
        return

    # -----------------------------------------------------
    # کم کردن موجودی
    # -----------------------------------------------------

    if data.startswith("stock_minus:"):

        if not is_admin(user_id):
            await query.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True,
            )
            return

        _, code, size = data.split(":", 2)

        new_qty = change_stock(
            code,
            size,
            -1
        )

        await query.answer(
            f"✅ سایز {size}: {new_qty} جفت"
        )

        await show_admin_inventory(
            query.message,
            code
        )
        return

    # -----------------------------------------------------
    # افزودن سایز
    # -----------------------------------------------------

    if data.startswith("add_size:"):

        if not is_admin(user_id):
            return

        code = normalize_code(
            data.split(":", 1)[1]
        )

        clear_mode(context)

        context.user_data["admin_add_size"] = True
        context.user_data["admin_product_code"] = code

        await query.message.reply_text(
            f"➕ افزودن سایز به محصول {code}\n\n"
            "شماره سایز جدید را بفرستید.\n"
            "مثال: 40",
            reply_markup=cancel_keyboard(),
        )

        return

    # -----------------------------------------------------
    # حذف سایز
    # -----------------------------------------------------

    if data.startswith("remove_size:"):

        if not is_admin(user_id):
            return

        code = normalize_code(
            data.split(":", 1)[1]
        )

        inventory = get_inventory(code)

        buttons = []

        for size in inventory:
            buttons.append([
                InlineKeyboardButton(
                    f"🗑 حذف سایز {size}",
                    callback_data=f"delete_size:{code}:{size}",
                )
            ])

        await query.message.reply_text(
            "سایزی که می‌خواهید حذف شود را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    if data.startswith("delete_size:"):

        if not is_admin(user_id):
            return

        _, code, size = data.split(":", 2)

        remove_size(code, size)

        await query.answer(
            f"سایز {size} حذف شد ✅"
        )

        await show_admin_inventory(
            query.message,
            code
        )

        return


# =========================================================
# زیبال
# =========================================================

def create_zibal_payment(order):
    if not ZIBAL_MERCHANT:
        raise Exception("ZIBAL_MERCHANT تنظیم نشده است.")

    if not PUBLIC_URL:
        raise Exception("PUBLIC_URL تنظیم نشده است.")

    payload = {
        "merchant": ZIBAL_MERCHANT,
        "amount": int(order["amount_rial"]),
        "callbackUrl": f"{PUBLIC_URL}/zibal/callback",
        "description": f"Katoni 530 Order #{order['id']}",
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
            data.get("message", "Zibal payment error")
        )

    track_id = str(
        data.get("trackId", "")
    )

    if not track_id:
        raise Exception("trackId دریافت نشد.")

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
# پیام بعد از پرداخت
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
        print("Telegram callback error:", e)


def notify_paid_order(order, ref_number):
    remaining = get_stock(
        order["product_code"],
        order["size"]
    )

    customer_text = (
        "🎉 پرداخت با موفقیت تأیید شد\n\n"
        f"🧾 شماره سفارش: {order['id']}\n"
        f"👟 محصول: {order['product_name']}\n"
        f"🏷 کد: {order['product_code']}\n"
        f"📏 سایز: {order['size']}\n"
        f"💰 مبلغ: {money(order['amount_toman'])} تومان\n"
        f"🔐 کد پیگیری پرداخت: {ref_number}\n\n"
        "✅ سفارش شما ثبت نهایی شد.\n"
        "📦 سفارش برای ارسال آماده می‌شود.\n\n"
        "👟 کتونی 530"
    )

    send_telegram_sync(
        order["telegram_chat_id"],
        customer_text
    )

    if ADMIN_CHAT_ID:
        admin_text = (
            "🔔 سفارش جدید پرداخت شد\n\n"
            f"🧾 سفارش: #{order['id']}\n"
            f"👟 محصول: {order['product_name']}\n"
            f"🏷 کد: {order['product_code']}\n"
            f"📏 سایز: {order['size']}\n"
            f"💰 مبلغ: {money(order['amount_toman'])} تومان\n\n"
            f"👤 مشتری: {order['customer_name']}\n"
            f"📱 موبایل: {order['mobile']}\n"
            f"📍 آدرس: {order['address']}\n\n"
            f"📦 موجودی باقی‌مانده سایز {order['size']}: {remaining} جفت\n"
            f"🔐 پیگیری پرداخت: {ref_number}"
        )

        send_telegram_sync(
            ADMIN_CHAT_ID,
            admin_text
        )


# =========================================================
# Callback پرداخت
# =========================================================

class PaymentCallbackHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print("HTTP:", format % args)

    def send_html(self, title, message):
        page = f"""
        <!doctype html>
        <html lang="fa" dir="rtl">
        <head>
            <meta charset="utf-8">
            <meta name="viewport"
                  content="width=device-width, initial-scale=1">
            <title>{html.escape(title)}</title>
        </head>
        <body style="font-family:sans-serif;text-align:center;padding:40px">
            <h2>{html.escape(title)}</h2>
            <p>{html.escape(message)}</p>
            <p>می‌توانید به تلگرام برگردید.</p>
            <strong>👟 کتونی 530</strong>
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
        parsed = urlparse(self.path)

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

        params = parse_qs(parsed.query)

        track_id = (
            params.get("trackId", [""])[0]
            or params.get("trackid", [""])[0]
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

        order = get_order_by_track_id(track_id)

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
            mark_order_failed(order["id"])

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
            verify_data = verify_zibal(track_id)

            result = int(
                verify_data.get("result", 0)
            )

            if result not in (100, 201):
                self.send_html(
                    "پرداخت تأیید نشد ❌",
                    "تأیید نهایی از درگاه دریافت نشد."
                )
                return

            verified_amount = verify_data.get("amount")

            if verified_amount is not None:
                if int(verified_amount) != int(
                    order["amount_rial"]
                ):
                    self.send_html(
                        "خطا در مبلغ",
                        "مبلغ پرداخت با سفارش مطابقت ندارد."
                    )
                    return

            # اول موجودی را کم می‌کنیم.
            stock_ok = reduce_stock_after_payment(
                order["id"]
            )

            if not stock_ok:
                # پرداخت تأیید شده، پس آن را گم نمی‌کنیم.
                # ادمین باید این سفارش را بررسی کند.
                mark_order_paid(
                    order["id"],
                    str(
                        verify_data.get(
                            "refNumber",
                            track_id
                        )
                    )
                )

                if ADMIN_CHAT_ID:
                    send_telegram_sync(
                        ADMIN_CHAT_ID,
                        "⚠️ هشدار مهم\n\n"
                        f"پرداخت سفارش #{order['id']} تأیید شده "
                        "اما موجودی سایز هنگام ثبت نهایی صفر بوده است.\n"
                        "لطفاً سفارش را دستی بررسی کنید."
                    )

                send_telegram_sync(
                    order["telegram_chat_id"],
                    "✅ پرداخت شما تأیید شده است.\n\n"
                    "سفارش شما نیاز به بررسی موجودی دارد و "
                    "پشتیبانی کتونی 530 آن را بررسی می‌کند."
                )

                self.send_html(
                    "پرداخت موفق بود ✅",
                    "پرداخت تأیید شد و سفارش در حال بررسی است."
                )
                return

            ref_number = str(
                verify_data.get(
                    "refNumber",
                    ""
                )
                or track_id
            )

            mark_order_paid(
                order["id"],
                ref_number
            )

            order = get_order(order["id"])

            notify_paid_order(
                order,
                ref_number
            )

            self.send_html(
                "پرداخت موفق بود ✅",
                f"سفارش شماره {order['id']} ثبت شد."
            )

        except Exception as e:
            print("VERIFY ERROR:", e)

            self.send_html(
                "خطا در بررسی پرداخت",
                "اگر مبلغ از حساب شما کسر شده، دوباره پرداخت نکنید."
            )


def start_http_server():
    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        PaymentCallbackHandler
    )

    print(f"HTTP server running on port {PORT}")
    server.serve_forever()


# =========================================================
# پشتیبانی
# =========================================================

async def send_support_to_admin(update, context):
    if not ADMIN_CHAT_ID:
        await update.message.reply_text(
            "❌ پشتیبانی در دسترس نیست.",
            reply_markup=main_keyboard(
                update.effective_user.id
            ),
        )
        clear_mode(context)
        return

    user = update.effective_user

    header = (
        "📩 پیام جدید مشتری\n\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user.id}\n"
    )

    if user.username:
        header += f"🔗 @{user.username}\n"

    header += "\n👇 پیام مشتری:"

    try:
        await context.bot.send_message(
            chat_id=int(ADMIN_CHAT_ID),
            text=header,
        )

        await update.message.copy(
            chat_id=int(ADMIN_CHAT_ID)
        )

        clear_mode(context)

        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد.",
            reply_markup=support_keyboard(),
        )

    except Exception as e:
        print("Support error:", e)

        await update.message.reply_text(
            "❌ ارسال پیام انجام نشد."
        )


# =========================================================
# پیام متنی
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id

    if not await is_member(context.bot, user_id):
        await show_join_message(update)
        return

    # -----------------------------------------------------
    # خانه و لغو
    # -----------------------------------------------------

    if text == "🏠 بازگشت به منوی اصلی":
        clear_mode(context)

        await update.message.reply_text(
            "🏠 منوی اصلی کتونی 530",
            reply_markup=main_keyboard(user_id),
        )
        return

    if text == "❌ لغو عملیات":
        clear_mode(context)

        await update.message.reply_text(
            "✅ عملیات لغو شد.",
            reply_markup=main_keyboard(user_id),
        )
        return

    # =====================================================
    # افزودن سایز توسط مدیر
    # =====================================================

    if context.user_data.get("admin_add_size"):

        if not is_admin(user_id):
            clear_mode(context)
            return

        size = text.strip()

        if not size.isdigit():
            await update.message.reply_text(
                "❌ فقط شماره سایز را بفرستید.\n"
                "مثال: 40"
            )
            return

        code = context.user_data["admin_product_code"]

        add_size(code, size)
        clear_mode(context)

        await update.message.reply_text(
            f"✅ سایز {size} به محصول {code} اضافه شد.\n"
            "موجودی اولیه آن صفر است."
        )

        await show_admin_inventory(
            update.message,
            code
        )
        return

    # =====================================================
    # مراحل سفارش
    # =====================================================

    if context.user_data.get("ordering"):

        step = context.user_data.get("step")

        if step == "name":
            if len(text) < 2:
                await update.message.reply_text(
                    "لطفاً نام و نام خانوادگی را وارد کنید."
                )
                return

            context.user_data["customer_name"] = text
            context.user_data["step"] = "mobile"

            await update.message.reply_text(
                "📱 شماره موبایل را وارد کنید.\n"
                "مثال: 09123456789",
                reply_markup=cancel_keyboard(),
            )
            return

        if step == "mobile":
            mobile = (
                text.replace(" ", "")
                .replace("-", "")
            )

            if (
                not mobile.isdigit()
                or len(mobile) != 11
                or not mobile.startswith("09")
            ):
                await update.message.reply_text(
                    "❌ شماره موبایل صحیح نیست.\n"
                    "مثال: 09123456789"
                )
                return

            context.user_data["mobile"] = mobile
            context.user_data["step"] = "address"

            await update.message.reply_text(
                "📍 آدرس کامل برای ارسال را بنویسید:",
                reply_markup=cancel_keyboard(),
            )
            return

        if step == "address":
            if len(text) < 5:
                await update.message.reply_text(
                    "لطفاً آدرس کامل‌تری بنویسید."
                )
                return

            context.user_data["address"] = text

            code = context.user_data["product_code"]
            size = context.user_data["size"]

            product = PRODUCTS.get(code)

            if not product:
                clear_mode(context)
                return

            # قبل از ساخت درگاه دوباره موجودی چک می‌شود.
            if get_stock(code, size) <= 0:
                clear_mode(context)

                await update.message.reply_text(
                    "❌ متأسفانه این سایز همین الان ناموجود شده است.\n"
                    "لطفاً سایز دیگری انتخاب کنید.",
                    reply_markup=main_keyboard(user_id),
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
                    mobile=context.user_data["mobile"],
                    address=context.user_data["address"],
                )

                order = get_order(order_id)

                track_id = create_zibal_payment(order)

                set_track_id(
                    order_id,
                    track_id
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
                    f"👤 نام: {context.user_data['customer_name']}\n"
                    f"📱 موبایل: {context.user_data['mobile']}\n"
                    f"📍 آدرس: {context.user_data['address']}\n\n"
                    "⚠️ سفارش هنوز ثبت نهایی نشده است.\n"
                    "بعد از پرداخت موفق ثبت نهایی می‌شود 👇",
                    reply_markup=keyboard,
                )

                clear_mode(context)

            except Exception as e:
                print("PAYMENT ERROR:", e)

                clear_mode(context)

                await update.message.reply_text(
                    "❌ اتصال به درگاه انجام نشد.\n"
                    "هیچ مبلغی از حساب شما کسر نشده است.",
                    reply_markup=main_keyboard(user_id),
                )

            return

    # =====================================================
    # جستجو
    # =====================================================

    if context.user_data.get("searching"):
        clear_mode(context)

        await send_product(
            update.message,
            normalize_code(text)
        )
        return

    # =====================================================
    # پیگیری
    # =====================================================

    if context.user_data.get("tracking"):

        try:
            order_id = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ شماره سفارش باید عدد باشد."
            )
            return

        order = get_user_order(
            order_id,
            user_id
        )

        if not order:
            await update.message.reply_text(
                "❌ سفارشی با این شماره پیدا نشد."
            )
            return

        status_map = {
            "paid": "✅ پرداخت شده و ثبت نهایی شده",
            "waiting_payment": "⏳ در انتظار پرداخت",
            "payment_failed": "❌ پرداخت ناموفق یا لغو شده",
        }

        status_text = status_map.get(
            order["status"],
            order["status"]
        )

        clear_mode(context)

        await update.message.reply_text(
            "📦 وضعیت سفارش\n\n"
            f"🔢 شماره: {order['id']}\n"
            f"👟 {order['product_name']}\n"
            f"🏷 کد: {order['product_code']}\n"
            f"📏 سایز: {order['size']}\n"
            f"💰 {money(order['amount_toman'])} تومان\n"
            f"📌 وضعیت: {status_text}",
            reply_markup=main_keyboard(user_id),
        )
        return

    # =====================================================
    # پشتیبانی فعال
    # =====================================================

    if context.user_data.get("support_mode"):
        await send_support_to_admin(
            update,
            context
        )
        return

    # =====================================================
    # منو
    # =====================================================

    if text == "🔥 جدیدترین مدل‌ها":
        await show_latest_products(update.message)
        return

    if text == "👟 کفش زنانه":
        await show_products_by_category(
            update.message,
            "women"
        )
        return

    if text == "👟 کفش مردانه":
        await show_products_by_category(
            update.message,
            "men"
        )
        return

    if text == "🔎 جستجو با کد محصول":
        clear_mode(context)
        context.user_data["searching"] = True

        await update.message.reply_text(
            "🔎 کد محصول را وارد کنید.\n"
            "مثال: 005",
            reply_markup=cancel_keyboard(),
        )
        return

    if text == "🛒 ثبت سفارش":
        await update.message.reply_text(
            "🛒 ابتدا مدل کفش را انتخاب کنید.\n\n"
            "از «🔥 جدیدترین مدل‌ها» یا جستجوی کد استفاده کنید.",
            reply_markup=main_keyboard(user_id),
        )
        return

    if text == "📦 پیگیری سفارش":
        clear_mode(context)
        context.user_data["tracking"] = True

        await update.message.reply_text(
            "📦 شماره سفارش را وارد کنید:",
            reply_markup=cancel_keyboard(),
        )
        return

    if text in [
        "💰 قیمت و موجودی",
        "💰 استعلام قیمت و موجودی",
    ]:
        clear_mode(context)
        context.user_data["searching"] = True

        await update.message.reply_text(
            "🏷 کد محصول را وارد کنید.\n"
            "مثال: 005",
            reply_markup=cancel_keyboard(),
        )
        return

    if text in [
        "📏 راهنمای سایز",
        "📏 راهنمای انتخاب سایز",
    ]:
        await update.message.reply_text(
            "📏 سایزهای موجود هر کفش داخل مشخصات همان مدل نمایش داده می‌شود.\n\n"
            "اگر برای انتخاب سایز نیاز به راهنمایی دارید، با پشتیبانی در ارتباط باشید.",
            reply_markup=support_keyboard(),
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
        clear_mode(context)

        await update.message.reply_text(
            "👨‍💬 مرکز پشتیبانی کتونی 530\n\n"
            "موضوع موردنظر را انتخاب کنید 👇",
            reply_markup=support_keyboard(),
        )
        return

    if text == "🛍 راهنمای خرید":
        await update.message.reply_text(
            "🛍 راهنمای خرید\n\n"
            "1️⃣ مدل را انتخاب کنید.\n"
            "2️⃣ سایز را انتخاب کنید.\n"
            "3️⃣ مشخصات را وارد کنید.\n"
            "4️⃣ پرداخت را انجام دهید.\n"
            "5️⃣ بعد از پرداخت موفق، سفارش ثبت نهایی و موجودی همان سایز خودکار کم می‌شود. ✅",
            reply_markup=support_keyboard(),
        )
        return

    if text in [
        "💳 مشکل پرداخت",
        "🔄 تعویض / مشکل سفارش",
        "👨‍💼 ارتباط مستقیم با پشتیبان",
    ]:
        clear_mode(context)
        context.user_data["support_mode"] = True

        await update.message.reply_text(
            "👨‍💬 پیام خود را همین‌جا ارسال کنید.\n\n"
            "پیام شما برای پشتیبانی کتونی 530 ارسال می‌شود.\n"
            "⚠️ اطلاعات محرمانه بانکی ارسال نکنید.",
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

    # =====================================================
    # پنل ادمین
    # =====================================================

    if text == "🔐 مدیریت فروشگاه":

        if not is_admin(user_id):
            await update.message.reply_text(
                "⛔ شما به این بخش دسترسی ندارید."
            )
            return

        await show_admin_products(
            update.message
        )
        return

    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های منو را انتخاب کنید 👇",
        reply_markup=main_keyboard(user_id),
    )


# =========================================================
# عکس و فایل پشتیبانی
# =========================================================

async def media_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message:
        return

    if not context.user_data.get("support_mode"):
        await update.message.reply_text(
            "برای ارسال عکس یا فایل ابتدا وارد بخش پشتیبانی شوید.",
            reply_markup=main_keyboard(
                update.effective_user.id
            ),
        )
        return

    if not ADMIN_CHAT_ID:
        return

    user = update.effective_user

    header = (
        "📩 عکس/فایل جدید مشتری\n\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user.id}"
    )

    if user.username:
        header += f"\n🔗 @{user.username}"

    try:
        await context.bot.send_message(
            chat_id=int(ADMIN_CHAT_ID),
            text=header,
        )

        await update.message.copy(
            chat_id=int(ADMIN_CHAT_ID)
        )

        clear_mode(context)

        await update.message.reply_text(
            "✅ برای پشتیبانی ارسال شد.",
            reply_markup=support_keyboard(),
        )

    except Exception as e:
        print("Media error:", e)


# =========================================================
# Commands
# =========================================================

async def products_command(update, context):
    clear_mode(context)
    await show_latest_products(update.message)


async def search_command(update, context):
    clear_mode(context)
    context.user_data["searching"] = True

    await update.message.reply_text(
        "🔎 کد محصول را بفرستید.\nمثال: 005",
        reply_markup=cancel_keyboard(),
    )


async def order_command(update, context):
    clear_mode(context)
    await show_latest_products(update.message)


async def track_command(update, context):
    clear_mode(context)
    context.user_data["tracking"] = True

    await update.message.reply_text(
        "📦 شماره سفارش را وارد کنید:",
        reply_markup=cancel_keyboard(),
    )


async def support_command(update, context):
    clear_mode(context)

    await update.message.reply_text(
        "👨‍💬 مرکز پشتیبانی کتونی 530",
        reply_markup=support_keyboard(),
    )


async def admin_command(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "⛔ دسترسی ندارید."
        )
        return

    clear_mode(context)

    await show_admin_products(
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
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("products", products_command)
    )

    app.add_handler(
        CommandHandler("search", search_command)
    )

    app.add_handler(
        CommandHandler("order", order_command)
    )

    app.add_handler(
        CommandHandler("track", track_command)
    )

    app.add_handler(
        CommandHandler("support", support_command)
    )

    app.add_handler(
        CommandHandler("admin", admin_command)
    )

    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
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

    print("Katoni 530 bot started successfully")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()

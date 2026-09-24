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


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ZIBAL_MERCHANT = os.getenv("ZIBAL_MERCHANT", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

PORT = int(os.getenv("PORT", "8080"))

CHANNEL = "@katooni_530"
CHANNEL_LINK = "https://t.me/katooni_530"

DB_FILE = "orders.db"

SHIPPING_COST = 350000

ZIBAL_REQUEST_URL = "https://gateway.zibal.ir/v1/request"
ZIBAL_VERIFY_URL = "https://gateway.zibal.ir/v1/verify"
ZIBAL_START_URL = "https://gateway.zibal.ir/start/"

WOMEN_SIZES = ["37", "38", "39", "40"]
MEN_SIZES = ["41", "42", "43", "44", "45"]


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


def sizes_for(category):
    if category == "women":
        return WOMEN_SIZES

    if category == "men":
        return MEN_SIZES

    return []


def is_admin(user_id):
    return (
        bool(ADMIN_CHAT_ID)
        and str(user_id) == str(ADMIN_CHAT_ID)
    )


def db():
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False,
    )

    conn.row_factory = sqlite3.Row

    return conn


def ensure_column(
    table_name,
    column_name,
    definition,
):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        f"PRAGMA table_info({table_name})"
    )

    columns = {
        row["name"]
        for row in cur.fetchall()
    }

    if column_name not in columns:
        try:
            cur.execute(
                f"""
                ALTER TABLE {table_name}
                ADD COLUMN {definition}
                """
            )

            conn.commit()

        except Exception as e:
            print(
                "ALTER ERROR:",
                repr(e)
            )

    conn.close()


def init_db():
    conn = db()
    cur = conn.cursor()

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            product_code TEXT NOT NULL,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (
                product_code,
                size
            )
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

    ensure_column(
        "products",
        "photo",
        "photo TEXT",
    )

    ensure_column(
        "orders",
        "product_price_toman",
        "product_price_toman INTEGER NOT NULL DEFAULT 0",
    )

    ensure_column(
        "orders",
        "shipping_toman",
        "shipping_toman INTEGER NOT NULL DEFAULT 0",
    )

    ensure_column(
        "orders",
        "stock_reduced",
        "stock_reduced INTEGER NOT NULL DEFAULT 0",
    )

    conn = db()
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
        VALUES (
            '005',
            'New Balance 530 🤎',
            7250000,
            'women',
            1
        )
    """)

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
            initial_stock[size],
        ))

    conn.commit()
    conn.close()


def get_product(code):
    code = normalize_code(code)

    if not code:
        return None

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM products
        WHERE code = ?
        AND active = 1
    """, (
        code,
    )).fetchone()

    conn.close()

    return row


def get_products(category=None):
    conn = db()

    if category:
        rows = conn.execute("""
            SELECT *
            FROM products
            WHERE active = 1
            AND category = ?
            ORDER BY CAST(code AS INTEGER)
        """, (
            category,
        )).fetchall()

    else:
        rows = conn.execute("""
            SELECT *
            FROM products
            WHERE active = 1
            ORDER BY CAST(code AS INTEGER)
        """).fetchall()

    conn.close()

    return rows


def seed_sizes(
    code,
    category,
):
    conn = db()
    cur = conn.cursor()

    for size in sizes_for(
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
    category,
):
    code = normalize_code(code)

    if not code:
        return False

    conn = db()

    try:
        row = conn.execute("""
            SELECT code
            FROM products
            WHERE code = ?
        """, (
            code,
        )).fetchone()

        if row:
            conn.execute("""
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
            conn.execute("""
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

    seed_sizes(
        code,
        category,
    )

    return True


def update_product_field(
    code,
    field,
    value,
):
    allowed = {
        "name",
        "price",
        "photo",
        "category",
        "active",
    }

    if field not in allowed:
        return

    conn = db()

    conn.execute(
        f"""
        UPDATE products
        SET {field} = ?
        WHERE code = ?
        """,
        (
            value,
            code,
        ),
    )

    conn.commit()
    conn.close()


def get_stock(
    code,
    size,
):
    conn = db()

    row = conn.execute("""
        SELECT quantity
        FROM inventory
        WHERE product_code = ?
        AND size = ?
    """, (
        code,
        str(size),
    )).fetchone()

    conn.close()

    if not row:
        return 0

    return int(
        row["quantity"]
    )


def change_stock(
    code,
    size,
    amount,
):
    product = get_product(
        code
    )

    if not product:
        return 0

    if size not in sizes_for(
        product["category"]
    ):
        return 0

    conn = db()

    try:
        cur = conn.cursor()

        cur.execute(
            "BEGIN IMMEDIATE"
        )

        row = cur.execute("""
            SELECT quantity
            FROM inventory
            WHERE product_code = ?
            AND size = ?
        """, (
            code,
            size,
        )).fetchone()

        current = (
            int(row["quantity"])
            if row
            else 0
        )

        if not row:
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
                size,
            ))

        new_quantity = max(
            0,
            current + int(amount),
        )

        cur.execute("""
            UPDATE inventory
            SET quantity = ?
            WHERE product_code = ?
            AND size = ?
        """, (
            new_quantity,
            code,
            size,
        ))

        conn.commit()

        return new_quantity

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def create_order(
    user_id,
    chat_id,
    product,
    size,
    customer_name,
    mobile,
    address,
):
    shipping = SHIPPING_COST

    total = (
        int(product["price"])
        +
        shipping
    )

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orders
        (
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
        user_id,
        chat_id,
        product["code"],
        product["name"],
        size,
        int(product["price"]),
        shipping,
        total,
        total * 10,
        customer_name,
        mobile,
        address,
    ))

    order_id = cur.lastrowid

    conn.commit()
    conn.close()

    return order_id


def get_order(order_id):
    conn = db()

    row = conn.execute("""
        SELECT *
        FROM orders
        WHERE id = ?
    """, (
        order_id,
    )).fetchone()

    conn.close()

    return row


def get_order_by_track(
    track_id
):
    conn = db()

    row = conn.execute("""
        SELECT *
        FROM orders
        WHERE track_id = ?
    """, (
        str(track_id),
    )).fetchone()

    conn.close()

    return row


def set_track_id(
    order_id,
    track_id,
):
    conn = db()

    conn.execute("""
        UPDATE orders
        SET track_id = ?
        WHERE id = ?
    """, (
        str(track_id),
        order_id,
    ))

    conn.commit()
    conn.close()


def mark_failed(order_id):
    conn = db()

    conn.execute("""
        UPDATE orders
        SET status = 'payment_failed'
        WHERE id = ?
        AND status != 'paid'
    """, (
        order_id,
    ))

    conn.commit()
    conn.close()


def finalize_paid(
    order_id,
    ref_number,
):
    conn = db()

    try:
        cur = conn.cursor()

        cur.execute(
            "BEGIN IMMEDIATE"
        )

        order = cur.execute("""
            SELECT *
            FROM orders
            WHERE id = ?
        """, (
            order_id,
        )).fetchone()

        if not order:
            conn.rollback()

            return False, None

        if (
            order["status"] == "paid"
            and
            int(
                order["stock_reduced"]
                or 0
            ) == 1
        ):
            conn.rollback()

            return (
                True,
                get_stock(
                    order["product_code"],
                    order["size"],
                ),
            )

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

        stock_ok = (
            cur.rowcount == 1
        )

        cur.execute("""
            UPDATE orders
            SET status = 'paid',
                ref_number = ?,
                paid_at = CURRENT_TIMESTAMP,
                stock_reduced =
                    CASE
                        WHEN ? = 1
                        THEN 1
                        ELSE stock_reduced
                    END
            WHERE id = ?
        """, (
            str(ref_number),
            1 if stock_ok else 0,
            order_id,
        ))

        conn.commit()

        remaining = None

        if stock_ok:
            remaining = get_stock(
                order["product_code"],
                order["size"],
            )

        return (
            stock_ok,
            remaining,
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def main_keyboard(
    user_id=None
):
    rows = [
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
        rows.append(
            ["🔐 مدیریت فروشگاه"]
        )

    return ReplyKeyboardMarkup(
        rows,
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


async def is_member(
    bot,
    user_id,
):
    try:
        member = (
            await bot.get_chat_member(
                CHANNEL,
                user_id,
            )
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


async def show_join(
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
                callback_data="check_member",
            )
        ],
    ])

    await update.effective_message.reply_text(
        "برای استفاده از فروشگاه ابتدا عضو کانال شوید 👇",
        reply_markup=keyboard,
    )


async def send_product(
    message,
    code,
):
    code = normalize_code(
        code
    )

    if not code:
        await message.reply_text(
            "❌ کد باید بین 001 تا 999 باشد."
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

    available = []

    for size in sizes_for(
        product["category"]
    ):
        if get_stock(
            code,
            size,
        ) > 0:
            available.append(
                size
            )

    category_name = (
        "زنانه"
        if product["category"] == "women"
        else "مردانه"
    )

    if available:
        stock_line = (
            "📏 سایزهای موجود: "
            +
            " - ".join(
                available
            )
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
        stock_line = (
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
        f"{stock_line}\n"
        f"💰 قیمت: {money(product['price'])} تومان\n"
        f"🚚 هزینه ارسال: {money(SHIPPING_COST)} تومان"
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
                "PHOTO ERROR:",
                repr(e)
            )

    await message.reply_text(
        caption,
        reply_markup=keyboard,
    )


async def show_latest(
    message
):
    products = get_products()

    if not products:
        await message.reply_text(
            "فعلاً محصولی ثبت نشده است."
        )

        return

    await message.reply_text(
        "🔥 جدیدترین مدل‌ها 👇"
    )

    for product in products[-10:]:
        await send_product(
            message,
            product["code"],
        )


async def show_category(
    message,
    category,
):
    products = get_products(
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


async def admin_home(
    message
):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👟 محصولات زنانه",
                callback_data="admin_cat:women",
            )
        ],
        [
            InlineKeyboardButton(
                "👞 محصولات مردانه",
                callback_data="admin_cat:men",
            )
        ],
        [
            InlineKeyboardButton(
                "➕ افزودن محصول جدید",
                callback_data="admin_add",
            )
        ],
    ])

    await message.reply_text(
        "🔐 مدیریت فروشگاه\n\n"
        "بخش موردنظر را انتخاب کنید 👇",
        reply_markup=keyboard,
    )


async def admin_category(
    message,
    category,
):
    buttons = []

    products = get_products(
        category
    )

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
            callback_data="admin_add",
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ برگشت",
            callback_data="admin_home",
        )
    ])

    title = (
        "زنانه"
        if category == "women"
        else "مردانه"
    )

    await message.reply_text(
        f"📦 محصولات {title}\n\n"
        "محصول را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


async def admin_product(
    message,
    code,
):
    product = get_product(
        code
    )

    if not product:
        await message.reply_text(
            "❌ محصول پیدا نشد."
        )

        return

    title = (
        "زنانه"
        if product["category"] == "women"
        else "مردانه"
    )

    text = (
        "📦 مدیریت محصول\n\n"
        f"👟 {product['name']}\n"
        f"🏷 کد: {product['code']}\n"
        f"👤 دسته: {title}\n"
        f"💰 قیمت: {money(product['price'])} تومان\n"
        f"🚚 ارسال: {money(SHIPPING_COST)} تومان\n\n"
        "📏 موجودی سایزها:\n"
    )

    buttons = []

    for size in sizes_for(
        product["category"]
    ):
        quantity = get_stock(
            code,
            size,
        )

        text += (
            f"سایز {size} = "
            f"{quantity} جفت\n"
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
            (
                "🖼 تغییر عکس"
                if product["photo"]
                else "🖼 افزودن عکس"
            ),
            callback_data=f"admin_photo:{code}",
        ),
        InlineKeyboardButton(
            "🗑 حذف عکس",
            callback_data=f"admin_photo_remove:{code}",
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
            callback_data=f"admin_change_cat:{code}",
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            "🗑 حذف محصول",
            callback_data=f"admin_delete:{code}",
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ برگشت",
            callback_data=f"admin_cat:{product['category']}",
        )
    ])

    markup = InlineKeyboardMarkup(
        buttons
    )

    if product["photo"]:
        try:
            await message.reply_photo(
                photo=product["photo"],
                caption=text,
                reply_markup=markup,
            )

            return

        except Exception as e:
            print(
                "ADMIN PHOTO ERROR:",
                repr(e)
            )

    await message.reply_text(
        text,
        reply_markup=markup,
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user:
        return

    context.user_data.clear()

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

        await show_join(
            update
        )

        return

    await update.effective_message.reply_text(
        "👋 به فروشگاه کتونی 530 خوش آمدید.",
        reply_markup=main_keyboard(
            user_id
        ),
    )

    if context.args:
        code = normalize_code(
            context.args[0]
        )

        if code:
            await send_product(
                update.effective_message,
                code,
            )

            return

    await show_latest(
        update.effective_message
    )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = (
        update.callback_query
    )

    if not query:
        return

    if not query.from_user:
        return

    data = query.data or ""

    user_id = (
        query.from_user.id
    )

    await query.answer()

    if data == "nothing":
        return

    if data == "check_member":
        if not await is_member(
            context.bot,
            user_id,
        ):
            await query.answer(
                "هنوز عضویت تأیید نشده است.",
                show_alert=True,
            )

            return

        await query.message.reply_text(
            "✅ عضویت تأیید شد.",
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
            await show_latest(
                query.message
            )

        return

    if data.startswith(
        "buy:"
    ):
        code = data.split(
            ":",
            1,
        )[1]

        product = get_product(
            code
        )

        if not product:
            return

        buttons = []

        for size in sizes_for(
            product["category"]
        ):
            if get_stock(
                code,
                size,
            ) > 0:
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

        total = (
            int(product["price"])
            +
            SHIPPING_COST
        )

        await query.message.reply_text(
            f"👟 {product['name']}\n"
            f"💰 قیمت کفش: {money(product['price'])} تومان\n"
            f"🚚 ارسال: {money(SHIPPING_COST)} تومان\n"
            f"💳 مبلغ نهایی: {money(total)} تومان\n\n"
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
            2,
        )

        product = get_product(
            code
        )

        if not product:
            return

        if get_stock(
            code,
            size,
        ) <= 0:
            await query.answer(
                "❌ این سایز تمام شده است.",
                show_alert=True,
            )

            return

        context.user_data.clear()

        context.user_data.update({
            "ordering": True,
            "step": "name",
            "product_code": code,
            "size": size,
        })

        total = (
            int(product["price"])
            +
            SHIPPING_COST
        )

        await query.message.reply_text(
            "🛒 ثبت سفارش\n\n"
            f"👟 {product['name']}\n"
            f"📏 سایز: {size}\n"
            f"💰 قیمت کفش: {money(product['price'])} تومان\n"
            f"🚚 ارسال: {money(SHIPPING_COST)} تومان\n"
            f"💳 مبلغ نهایی: {money(total)} تومان\n\n"
            "👤 نام و نام خانوادگی را بفرستید:",
            reply_markup=cancel_keyboard(),
        )

        return

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
        await admin_home(
            query.message
        )

        return

    if data.startswith(
        "admin_cat:"
    ):
        category = data.split(
            ":",
            1,
        )[1]

        await admin_category(
            query.message,
            category,
        )

        return

    if data == "admin_add":
        context.user_data.clear()

        context.user_data.update({
            "admin_add": True,
            "admin_step": "code",
        })

        await query.message.reply_text(
            "➕ افزودن محصول\n\n"
            "کد محصول را بفرستید.\n"
            "مثال: 006",
            reply_markup=cancel_keyboard(),
        )

        return

    if data.startswith(
        "admin_product:"
    ):
        code = data.split(
            ":",
            1,
        )[1]

        await admin_product(
            query.message,
            code,
        )

        return

    if data.startswith(
        "stock_plus:"
    ):
        _, code, size = data.split(
            ":",
            2,
        )

        quantity = change_stock(
            code,
            size,
            1,
        )

        await query.answer(
            f"✅ سایز {size}: {quantity} جفت"
        )

        await admin_product(
            query.message,
            code,
        )

        return

    if data.startswith(
        "stock_minus:"
    ):
        _, code, size = data.split(
            ":",
            2,
        )

        quantity = change_stock(
            code,
            size,
            -1,
        )

        await query.answer(
            f"✅ سایز {size}: {quantity} جفت"
        )

        await admin_product(
            query.message,
            code,
        )

        return

    if data.startswith(
        "admin_photo:"
    ):
        code = data.split(
            ":",
            1,
        )[1]

        context.user_data.clear()

        context.user_data[
            "admin_photo_code"
        ] = code

        await query.message.reply_text(
            f"🖼 عکس محصول {code}\n\n"
            "حالا عکس کفش را برای ربات بفرست.",
            reply_markup=cancel_keyboard(),
        )

        return

    if data.startswith(
        "admin_photo_remove:"
    ):
        code = data.split(
            ":",
            1,
        )[1]

        update_product_field(
            code,
            "photo",
            None,
        )

        await query.answer(
            "✅ عکس حذف شد."
        )

        await admin_product(
            query.message,
            code,
        )

        return

    if data.startswith(
        "admin_price:"
    ):
        code = data.split(
            ":",
            1,
        )[1]

        context.user_data.clear()

        context.user_data[
            "admin_price_code"
        ] = code

        await query.message.reply_text(
            "💰 قیمت جدید را به تومان بفرستید.",
            reply_markup=cancel_keyboard(),
        )

        return

    if data.startswith(
        "admin_name:"
    ):
        code = data.split(
            ":",
            1,
        )[1]

        context.user_data.clear()

        context.user_data[
            "admin_name_code"
        ] = code

        await query.message.reply_text(
            "✏️ نام جدید محصول را بفرستید.",
            reply_markup=cancel_keyboard(),
        )

        return

    if data.startswith(
        "admin_change_cat:"
    ):
        code = data.split(
            ":",
            1,
        )[1]

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👟 زنانه",
                    callback_data=f"admin_set_cat:{code}:women",
                ),
                InlineKeyboardButton(
                    "👞 مردانه",
                    callback_data=f"admin_set_cat:{code}:men",
                ),
            ]
        ])

        await query.message.reply_text(
            "دسته محصول را انتخاب کنید:",
            reply_markup=keyboard,
        )

        return

    if data.startswith(
        "admin_set_cat:"
    ):
        _, code, category = data.split(
            ":",
            2,
        )

        update_product_field(
            code,
            "category",
            category,
        )

        seed_sizes(
            code,
            category,
        )

        await query.answer(
            "✅ دسته تغییر کرد."
        )

        await admin_product(
            query.message,
            code,
        )

        return

    if data.startswith(
        "admin_delete:"
    ):
        code = data.split(
            ":",
            1,
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
            1,
        )[1]

        product = get_product(
            code
        )

        category = (
            product["category"]
            if product
            else "women"
        )

        update_product_field(
            code,
            "active",
            0,
        )

        await query.answer(
            "✅ محصول حذف شد."
        )

        await admin_category(
            query.message,
            category,
        )

        return


def create_zibal_payment(
    order
):
    if not ZIBAL_MERCHANT:
        raise RuntimeError(
            "ZIBAL_MERCHANT خالی است"
        )

    if not PUBLIC_URL:
        raise RuntimeError(
            "PUBLIC_URL خالی است"
        )

    payload = {
        "merchant":
            ZIBAL_MERCHANT,

        "amount":
            int(
                order["amount_rial"]
            ),

        "callbackUrl":
            f"{PUBLIC_URL}/zibal/callback",

        "description":
            f"Katoni 530 Order #{order['id']}",

        "mobile":
            order["mobile"],
    }

    response = requests.post(
        ZIBAL_REQUEST_URL,
        json=payload,
        timeout=25,
    )

    print(
        "ZIBAL REQUEST:",
        response.status_code,
        response.text[:1200],
    )

    response.raise_for_status()

    data = response.json()

    if int(
        data.get(
            "result",
            0,
        )
    ) != 100:
        raise RuntimeError(
            f"Zibal result="
            f"{data.get('result')} "
            f"message="
            f"{data.get('message')}"
        )

    track_id = str(
        data.get(
            "trackId",
            "",
        )
    )

    if not track_id:
        raise RuntimeError(
            "Zibal trackId دریافت نشد"
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
        timeout=25,
    )

    print(
        "ZIBAL VERIFY:",
        response.status_code,
        response.text[:1200],
    )

    response.raise_for_status()

    return response.json()


def telegram_send(
    chat_id,
    text,
):
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
                response.text[:1000],
            )

    except Exception as e:
        print(
            "TELEGRAM SEND EXCEPTION:",
            repr(e),
        )


class PaymentHandler(
    BaseHTTPRequestHandler
):

    def log_message(
        self,
        fmt,
        *args
    ):
        print(
            "HTTP:",
            fmt % args,
        )

    def page(
        self,
        title,
        message,
    ):
        page_html = f"""
        <!doctype html>
        <html lang="fa" dir="rtl">
        <head>
            <meta charset="utf-8">
            <meta
                name="viewport"
                content="width=device-width,initial-scale=1"
            >
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
                👟 کتونی 530
            </p>
        </body>
        </html>
        """

        body = page_html.encode(
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
            self.page(
                "کتونی 530",
                "ربات و درگاه فعال است.",
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
                [""],
            )[0]
            or
            params.get(
                "trackid",
                [""],
            )[0]
        )

        success = params.get(
            "success",
            [""],
        )[0]

        if not track_id:
            self.page(
                "خطا",
                "شناسه پرداخت دریافت نشد.",
            )

            return

        order = get_order_by_track(
            track_id
        )

        if not order:
            self.page(
                "خطا",
                "سفارش پیدا نشد.",
            )

            return

        if order["status"] == "paid":
            self.page(
                "پرداخت تأیید شده ✅",
                "این سفارش قبلاً ثبت شده است.",
            )

            return

        if success != "1":
            mark_failed(
                order["id"]
            )

            telegram_send(
                order["telegram_chat_id"],
                "❌ پرداخت انجام نشد یا لغو شد.",
            )

            self.page(
                "پرداخت ناموفق ❌",
                "سفارش ثبت نشد.",
            )

            return

        try:
            data = verify_zibal(
                track_id
            )

            result = int(
                data.get(
                    "result",
                    0,
                )
            )

            if result not in (
                100,
                201,
            ):
                self.page(
                    "پرداخت تأیید نشد",
                    "تأیید نهایی دریافت نشد.",
                )

                return

            if (
                data.get(
                    "amount"
                )
                is not None
                and
                int(
                    data["amount"]
                )
                !=
                int(
                    order["amount_rial"]
                )
            ):
                self.page(
                    "خطا",
                    "مبلغ پرداخت صحیح نیست.",
                )

                return

            ref_number = str(
                data.get(
                    "refNumber"
                )
                or
                track_id
            )

            (
                stock_ok,
                remaining,
            ) = finalize_paid(
                order["id"],
                ref_number,
            )

            telegram_send(
                order[
                    "telegram_chat_id"
                ],
                "✅ پرداخت موفق بود.\n\n"
                f"🧾 سفارش: {order['id']}\n"
                f"👟 {order['product_name']}\n"
                f"📏 سایز: {order['size']}\n"
                f"💰 قیمت کفش: "
                f"{money(order['product_price_toman'])} تومان\n"
                f"🚚 ارسال: "
                f"{money(order['shipping_toman'])} تومان\n"
                f"💳 پرداختی: "
                f"{money(order['amount_toman'])} تومان",
            )

            if ADMIN_CHAT_ID:
                admin_text = (
                    "🔔 سفارش جدید پرداخت شد\n\n"
                    f"🧾 سفارش: {order['id']}\n"
                    f"🏷 کد: {order['product_code']}\n"
                    f"📏 سایز: {order['size']}\n"
                    f"👤 {order['customer_name']}\n"
                    f"📱 {order['mobile']}\n"
                    f"📍 {order['address']}"
                )

                if stock_ok:
                    admin_text += (
                        f"\n📦 موجودی باقی‌مانده: "
                        f"{remaining} جفت"
                    )

                else:
                    admin_text += (
                        "\n⚠️ هشدار: "
                        "موجودی این سایز "
                        "هنگام تأیید پرداخت صفر بوده است."
                    )

                telegram_send(
                    ADMIN_CHAT_ID,
                    admin_text,
                )

            self.page(
                "پرداخت موفق ✅",
                f"سفارش شماره "
                f"{order['id']} ثبت شد.",
            )

        except Exception as e:
            print(
                "PAYMENT CALLBACK ERROR:",
                repr(e),
            )

            self.page(
                "خطا در بررسی پرداخت",
                "اگر مبلغ کسر شده، "
                "دوباره پرداخت نکنید.",
            )


def run_server():
    server = ThreadingHTTPServer(
        (
            "0.0.0.0",
            PORT,
        ),
        PaymentHandler,
    )

    print(
        "HTTP SERVER STARTED:",
        PORT,
    )

    server.serve_forever()


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
        await show_join(
            update
        )

        return

    if text in (
        "❌ لغو عملیات",
        "🏠 بازگشت به منوی اصلی",
    ):
        context.user_data.clear()

        await update.message.reply_text(
            "🏠 منوی اصلی",
            reply_markup=main_keyboard(
                user_id
            ),
        )

        return

    user_data = (
        context.user_data
    )

    if user_data.get(
        "admin_add"
    ):
        step = user_data.get(
            "admin_step"
        )

        if step == "code":
            code = normalize_code(
                text
            )

            if not code:
                await update.message.reply_text(
                    "❌ کد باید بین 001 تا 999 باشد."
                )

                return

            if get_product(
                code
            ):
                await update.message.reply_text(
                    "❌ این کد قبلاً ثبت شده است."
                )

                return

            user_data[
                "new_code"
            ] = code

            user_data[
                "admin_step"
            ] = "name"

            await update.message.reply_text(
                "👟 نام مدل را بفرستید."
            )

            return

        if step == "name":
            user_data[
                "new_name"
            ] = text

            user_data[
                "admin_step"
            ] = "price"

            await update.message.reply_text(
                "💰 قیمت را فقط به تومان بفرستید.\n"
                "مثال: 7900000"
            )

            return

        if step == "price":
            price_text = (
                text
                .replace(",", "")
                .replace("٬", "")
                .replace(" ", "")
            )

            if not price_text.isdigit():
                await update.message.reply_text(
                    "❌ فقط عدد قیمت را بفرستید."
                )

                return

            user_data[
                "new_price"
            ] = int(
                price_text
            )

            user_data[
                "admin_step"
            ] = "category"

            await update.message.reply_text(
                "محصول زنانه است یا مردانه؟",
                reply_markup=ReplyKeyboardMarkup(
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
                ),
            )

            return

        if step == "category":
            if text == "👟 زنانه":
                category = "women"

            elif text == "👞 مردانه":
                category = "men"

            else:
                await update.message.reply_text(
                    "یکی از دو گزینه را انتخاب کنید."
                )

                return

            code = user_data[
                "new_code"
            ]

            name = user_data[
                "new_name"
            ]

            price = user_data[
                "new_price"
            ]

            success = create_product(
                code,
                name,
                price,
                category,
            )

            context.user_data.clear()

            if not success:
                await update.message.reply_text(
                    "❌ محصول ثبت نشد."
                )

                return

            await update.message.reply_text(
                "✅ محصول ثبت شد.",
                reply_markup=main_keyboard(
                    user_id
                ),
            )

            await admin_product(
                update.message,
                code,
            )

            return

    if user_data.get(
        "admin_price_code"
    ):
        code = user_data[
            "admin_price_code"
        ]

        price_text = (
            text
            .replace(",", "")
            .replace("٬", "")
            .replace(" ", "")
        )

        if not price_text.isdigit():
            await update.message.reply_text(
                "❌ فقط عدد قیمت را بفرستید."
            )

            return

        update_product_field(
            code,
            "price",
            int(price_text),
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ قیمت تغییر کرد."
        )

        await admin_product(
            update.message,
            code,
        )

        return

    if user_data.get(
        "admin_name_code"
    ):
        code = user_data[
            "admin_name_code"
        ]

        update_product_field(
            code,
            "name",
            text,
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ نام تغییر کرد."
        )

        await admin_product(
            update.message,
            code,
        )

        return

    if user_data.get(
        "ordering"
    ):
        step = user_data.get(
            "step"
        )

        if step == "name":
            user_data[
                "customer_name"
            ] = text

            user_data[
                "step"
            ] = "mobile"

            await update.message.reply_text(
                "📱 شماره موبایل را وارد کنید.\n"
                "مثال: 09123456789"
            )

            return

        if step == "mobile":
            mobile = (
                text
                .replace(" ", "")
                .replace("-", "")
            )

            if not (
                mobile.isdigit()
                and
                len(mobile) == 11
                and
                mobile.startswith(
                    "09"
                )
            ):
                await update.message.reply_text(
                    "❌ شماره موبایل صحیح نیست."
                )

                return

            user_data[
                "mobile"
            ] = mobile

            user_data[
                "step"
            ] = "address"

            await update.message.reply_text(
                "📍 آدرس کامل ارسال را بفرستید:"
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

            code = user_data[
                "product_code"
            ]

            size = user_data[
                "size"
            ]

            product = get_product(
                code
            )

            if not product:
                context.user_data.clear()

                return

            if get_stock(
                code,
                size,
            ) <= 0:
                context.user_data.clear()

                await update.message.reply_text(
                    "❌ این سایز ناموجود شده است.",
                    reply_markup=main_keyboard(
                        user_id
                    ),
                )

                return

            try:
                order_id = create_order(
                    user_id,
                    update.effective_chat.id,
                    product,
                    size,
                    user_data[
                        "customer_name"
                    ],
                    user_data[
                        "mobile"
                    ],
                    text,
                )

                order = get_order(
                    order_id
                )

                track_id = (
                    create_zibal_payment(
                        order
                    )
                )

                set_track_id(
                    order_id,
                    track_id,
                )

                payment_url = (
                    f"{ZIBAL_START_URL}"
                    f"{track_id}"
                )

                total = (
                    int(
                        product["price"]
                    )
                    +
                    SHIPPING_COST
                )

                await update.message.reply_text(
                    "🧾 فاکتور سفارش\n\n"
                    f"🔢 شماره سفارش: {order_id}\n"
                    f"👟 {product['name']}\n"
                    f"📏 سایز: {size}\n"
                    f"💰 قیمت کفش: "
                    f"{money(product['price'])} تومان\n"
                    f"🚚 هزینه ارسال: "
                    f"{money(SHIPPING_COST)} تومان\n"
                    f"💳 مبلغ نهایی: "
                    f"{money(total)} تومان\n\n"
                    "⚠️ سفارش بعد از پرداخت موفق "
                    "ثبت نهایی می‌شود.",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "💳 پرداخت آنلاین",
                                url=payment_url,
                            )
                        ]
                    ]),
                )

                context.user_data.clear()

            except Exception as e:
                print(
                    "PAYMENT ERROR:",
                    repr(e),
                )

                context.user_data.clear()

                await update.message.reply_text(
                    "❌ اتصال به درگاه انجام نشد.\n"
                    "هیچ مبلغی از حساب شما کسر نشده است.",
                    reply_markup=main_keyboard(
                        user_id
                    ),
                )

            return

    if user_data.get(
        "searching"
    ):
        context.user_data.clear()

        await send_product(
            update.message,
            text,
        )

        return

    if user_data.get(
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

        conn = db()

        order = conn.execute("""
            SELECT *
            FROM orders
            WHERE id = ?
            AND telegram_user_id = ?
        """, (
            order_id,
            user_id,
        )).fetchone()

        conn.close()

        context.user_data.clear()

        if not order:
            await update.message.reply_text(
                "❌ سفارش پیدا نشد."
            )

            return

        status_map = {
            "waiting_payment":
                "⏳ در انتظار پرداخت",

            "paid":
                "✅ پرداخت شده",

            "payment_failed":
                "❌ پرداخت ناموفق",
        }

        await update.message.reply_text(
            f"📦 سفارش {order['id']}\n"
            f"👟 {order['product_name']}\n"
            f"📏 سایز: {order['size']}\n"
            f"📌 وضعیت: "
            f"{status_map.get(order['status'], order['status'])}",
            reply_markup=main_keyboard(
                user_id
            ),
        )

        return

    if user_data.get(
        "support_mode"
    ):
        if ADMIN_CHAT_ID:
            user = (
                update.effective_user
            )

            await context.bot.send_message(
                chat_id=int(
                    ADMIN_CHAT_ID
                ),
                text=(
                    "📩 پیام مشتری\n\n"
                    f"👤 {user.full_name}\n"
                    f"🆔 {user.id}\n\n"
                    f"💬 {text}"
                ),
            )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد.",
            reply_markup=support_keyboard(),
        )

        return

    if text == "🔥 جدیدترین مدل‌ها":
        await show_latest(
            update.message
        )

    elif text == "👟 کفش زنانه":
        await show_category(
            update.message,
            "women",
        )

    elif text == "👞 کفش مردانه":
        await show_category(
            update.message,
            "men",
        )

    elif text in (
        "🔎 جستجو با کد محصول",
        "💰 قیمت و موجودی",
        "💰 استعلام قیمت و موجودی",
    ):
        context.user_data.clear()

        context.user_data[
            "searching"
        ] = True

        await update.message.reply_text(
            "🔎 کد محصول را وارد کنید.\n"
            "مثال: 003",
            reply_markup=cancel_keyboard(),
        )

    elif text == "🛒 ثبت سفارش":
        await show_latest(
            update.message
        )

    elif text == "📦 پیگیری سفارش":
        context.user_data.clear()

        context.user_data[
            "tracking"
        ] = True

        await update.message.reply_text(
            "📦 شماره سفارش را وارد کنید:",
            reply_markup=cancel_keyboard(),
        )

    elif text in (
        "📏 راهنمای سایز",
        "📏 راهنمای انتخاب سایز",
    ):
        await update.message.reply_text(
            "📏 سایزبندی فروشگاه\n\n"
            "👟 زنانه: 37، 38، 39، 40\n"
            "👞 مردانه: 41، 42، 43، 44، 45"
        )

    elif text == "💳 پرداخت و مشکلات پرداخت":
        await update.message.reply_text(
            "اگر مبلغ کسر شد ولی سفارش تأیید نشد، "
            "دوباره پرداخت نکنید و با پشتیبانی تماس بگیرید.",
            reply_markup=support_keyboard(),
        )

    elif text == "👨‍💬 پشتیبانی":
        await update.message.reply_text(
            "👨‍💬 مرکز پشتیبانی",
            reply_markup=support_keyboard(),
        )

    elif text in (
        "💳 مشکل پرداخت",
        "🔄 تعویض / مشکل سفارش",
        "👨‍💼 ارتباط مستقیم با پشتیبان",
    ):
        context.user_data.clear()

        context.user_data[
            "support_mode"
        ] = True

        await update.message.reply_text(
            "پیام خود را بفرستید. "
            "می‌توانید عکس هم بفرستید.",
            reply_markup=cancel_keyboard(),
        )

    elif text == "🛍 راهنمای خرید":
        await update.message.reply_text(
            "1️⃣ مدل را انتخاب کنید.\n"
            "2️⃣ سایز را انتخاب کنید.\n"
            "3️⃣ مشخصات را وارد کنید.\n"
            "4️⃣ مبلغ کفش + 350 هزار تومان ارسال را پرداخت کنید.\n"
            "5️⃣ بعد از پرداخت موفق موجودی همان سایز یک عدد کم می‌شود."
        )

    elif text == "📣 کانال تلگرام":
        await update.message.reply_text(
            "📣 کانال رسمی 👇",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📣 ورود به کانال",
                        url=CHANNEL_LINK,
                    )
                ]
            ]),
        )

    elif text == "🔐 مدیریت فروشگاه":
        if is_admin(
            user_id
        ):
            await admin_home(
                update.message
            )

        else:
            await update.message.reply_text(
                "⛔ دسترسی ندارید."
            )

    else:
        await update.message.reply_text(
            "یکی از گزینه‌های منو را انتخاب کنید.",
            reply_markup=main_keyboard(
                user_id
            ),
        )


async def media_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    if not update.effective_user:
        return

    user_id = (
        update.effective_user.id
    )

    user_data = (
        context.user_data
    )

    if user_data.get(
        "admin_photo_code"
    ):
        if not is_admin(
            user_id
        ):
            context.user_data.clear()

            return

        if not update.message.photo:
            await update.message.reply_text(
                "❌ عکس را به صورت Photo ارسال کنید."
            )

            return

        code = user_data[
            "admin_photo_code"
        ]

        file_id = (
            update.message.photo[-1]
            .file_id
        )

        update_product_field(
            code,
            "photo",
            file_id,
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ عکس محصول ذخیره شد."
        )

        await admin_product(
            update.message,
            code,
        )

        return

    if user_data.get(
        "support_mode"
    ):
        if ADMIN_CHAT_ID:
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

        context.user_data.clear()

        await update.message.reply_text(
            "✅ برای پشتیبانی ارسال شد.",
            reply_markup=support_keyboard(),
        )


async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user:
        return

    if not is_admin(
        update.effective_user.id
    ):
        await update.effective_message.reply_text(
            "⛔ دسترسی ندارید."
        )

        return

    context.user_data.clear()

    await admin_home(
        update.effective_message
    )


async def error_handler(
    update,
    context,
):
    print(
        "TELEGRAM HANDLER ERROR:",
        repr(
            context.error
        ),
    )


def main():
    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN تنظیم نشده است"
        )

    if not ZIBAL_MERCHANT:
        raise RuntimeError(
            "ZIBAL_MERCHANT تنظیم نشده است"
        )

    if not PUBLIC_URL:
        raise RuntimeError(
            "PUBLIC_URL تنظیم نشده است"
        )

    init_db()

    server_thread = threading.Thread(
        target=run_server,
        daemon=True,
    )

    server_thread.start()

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
            &
            ~filters.COMMAND,
            text_handler,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO
            |
            filters.Document.ALL
            |
            filters.VIDEO,
            media_handler,
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        "KATONI 530 BOT STARTED"
    )

    app.run_polling(
        allowed_updates=
            Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()

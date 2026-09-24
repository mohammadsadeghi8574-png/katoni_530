# bot.py
import html
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import psycopg
import requests
from psycopg.rows import dict_row
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ZIBAL_MERCHANT = os.getenv("ZIBAL_MERCHANT", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
PORT = int(os.getenv("PORT", "8080"))

CHANNEL = "@katooni_530"
CHANNEL_LINK = "https://t.me/katooni_530"
SHIPPING_COST = 350_000

WOMEN_SIZES = ("37", "38", "39", "40")
MEN_SIZES = ("41", "42", "43", "44", "45")

ZIBAL_REQUEST_URL = "https://gateway.zibal.ir/v1/request"
ZIBAL_VERIFY_URL = "https://gateway.zibal.ir/v1/verify"
ZIBAL_START_URL = "https://gateway.zibal.ir/start/"


def money(value):
    return f"{int(value):,}"


def normalize_code(value):
    value = str(value).strip()
    if value.isdigit() and 1 <= int(value) <= 999:
        return f"{int(value):03d}"
    return None


def sizes_for(category):
    return WOMEN_SIZES if category == "women" else MEN_SIZES if category == "men" else ()


def is_admin(user_id):
    return bool(ADMIN_CHAT_ID) and str(user_id) == ADMIN_CHAT_ID


def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    code VARCHAR(3) PRIMARY KEY,
                    name TEXT NOT NULL,
                    price BIGINT NOT NULL CHECK (price > 0),
                    category TEXT NOT NULL CHECK (category IN ('women', 'men')),
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    photo TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    product_code VARCHAR(3) NOT NULL
                        REFERENCES products(code) ON DELETE CASCADE,
                    size TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
                    PRIMARY KEY (product_code, size)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id BIGSERIAL PRIMARY KEY,
                    telegram_user_id BIGINT NOT NULL,
                    telegram_chat_id BIGINT NOT NULL,
                    product_code VARCHAR(3) NOT NULL,
                    product_name TEXT NOT NULL,
                    size TEXT NOT NULL,
                    product_price_toman BIGINT NOT NULL,
                    shipping_toman BIGINT NOT NULL,
                    amount_toman BIGINT NOT NULL,
                    amount_rial BIGINT NOT NULL,
                    customer_name TEXT NOT NULL,
                    mobile TEXT NOT NULL,
                    address TEXT NOT NULL,
                    track_id TEXT UNIQUE,
                    ref_number TEXT,
                    status TEXT NOT NULL DEFAULT 'waiting_payment',
                    stock_reduced BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    paid_at TIMESTAMPTZ
                )
            """)


def get_product(code, include_inactive=False):
    code = normalize_code(code)
    if not code:
        return None
    with db() as conn:
        with conn.cursor() as cur:
            if include_inactive:
                cur.execute("SELECT * FROM products WHERE code=%s", (code,))
            else:
                cur.execute(
                    "SELECT * FROM products WHERE code=%s AND active=TRUE",
                    (code,),
                )
            return cur.fetchone()


def get_products(category=None, limit=None):
    sql = "SELECT * FROM products WHERE active=TRUE"
    params = []
    if category:
        sql += " AND category=%s"
        params.append(category)
    sql += " ORDER BY code::INTEGER DESC"
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()


def create_product(code, name, price, category):
    code = normalize_code(code)
    if not code or category not in ("women", "men") or int(price) <= 0:
        raise ValueError("اطلاعات محصول صحیح نیست.")
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO products (code, name, price, category, active)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (code) DO UPDATE SET
                    name=EXCLUDED.name,
                    price=EXCLUDED.price,
                    category=EXCLUDED.category,
                    active=TRUE
            """, (code, name, int(price), category))
            for size in sizes_for(category):
                cur.execute("""
                    INSERT INTO inventory (product_code, size, quantity)
                    VALUES (%s, %s, 0)
                    ON CONFLICT (product_code, size) DO NOTHING
                """, (code, size))


def update_product_field(code, field, value):
    if field not in {"name", "price", "photo", "active"}:
        raise ValueError("فیلد غیرمجاز")
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE products SET {field}=%s WHERE code=%s",
                (value, normalize_code(code)),
            )


def get_stock(code, size):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT quantity FROM inventory
                WHERE product_code=%s AND size=%s
            """, (normalize_code(code), str(size)))
            row = cur.fetchone()
            return int(row["quantity"]) if row else 0


def change_stock(code, size, delta):
    product = get_product(code)
    if not product or size not in sizes_for(product["category"]):
        return None
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO inventory (product_code, size, quantity)
                VALUES (%s, %s, 0)
                ON CONFLICT (product_code, size) DO NOTHING
            """, (product["code"], size))
            cur.execute("""
                UPDATE inventory
                SET quantity=GREATEST(0, quantity+%s)
                WHERE product_code=%s AND size=%s
                RETURNING quantity
            """, (int(delta), product["code"], size))
            return int(cur.fetchone()["quantity"])


def create_order(user_id, chat_id, product, size, name, mobile, address):
    total = int(product["price"]) + SHIPPING_COST
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO orders (
                    telegram_user_id, telegram_chat_id,
                    product_code, product_name, size,
                    product_price_toman, shipping_toman,
                    amount_toman, amount_rial,
                    customer_name, mobile, address
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (
                user_id, chat_id, product["code"], product["name"], size,
                int(product["price"]), SHIPPING_COST, total, total * 10,
                name, mobile, address,
            ))
            return int(cur.fetchone()["id"])


def get_order(order_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            return cur.fetchone()


def get_order_by_track(track_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE track_id=%s", (str(track_id),))
            return cur.fetchone()


def set_track_id(order_id, track_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE orders SET track_id=%s WHERE id=%s",
                (str(track_id), order_id),
            )


def mark_failed(order_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders SET status='payment_failed'
                WHERE id=%s AND status!='paid'
            """, (order_id,))


def finalize_paid(order_id, ref_number):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE id=%s FOR UPDATE", (order_id,))
            order = cur.fetchone()
            if not order:
                return False, None, False
            if order["status"] == "paid":
                return bool(order["stock_reduced"]), None, False

            cur.execute("""
                UPDATE inventory SET quantity=quantity-1
                WHERE product_code=%s AND size=%s AND quantity>0
                RETURNING quantity
            """, (order["product_code"], order["size"]))
            row = cur.fetchone()
            stock_ok = row is not None
            remaining = int(row["quantity"]) if row else None

            cur.execute("""
                UPDATE orders SET status='paid', ref_number=%s,
                    paid_at=NOW(), stock_reduced=%s
                WHERE id=%s
            """, (str(ref_number), stock_ok, order_id))
            return stock_ok, remaining, True


def main_keyboard(user_id=None):
    rows = [
        ["🔥 جدیدترین مدل‌ها"],
        ["👟 کفش زنانه", "👞 کفش مردانه"],
        ["🔎 جستجو با کد محصول"],
        ["🛒 ثبت سفارش", "📦 پیگیری سفارش"],
        ["💰 قیمت و موجودی", "📏 راهنمای سایز"],
        ["💳 پرداخت و مشکلات پرداخت"],
        ["👨‍💬 پشتیبانی", "📣 کانال تلگرام"],
    ]
    if user_id and is_admin(user_id):
        rows.append(["🔐 مدیریت فروشگاه"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def cancel_keyboard():
    return ReplyKeyboardMarkup(
        [["❌ لغو عملیات"], ["🏠 بازگشت به منوی اصلی"]],
        resize_keyboard=True,
    )


def support_keyboard():
    return ReplyKeyboardMarkup([
        ["🛍 راهنمای خرید", "📦 پیگیری سفارش"],
        ["💳 مشکل پرداخت", "🔄 تعویض / مشکل سفارش"],
        ["📏 راهنمای انتخاب سایز", "💰 استعلام قیمت و موجودی"],
        ["👨‍💼 ارتباط مستقیم با پشتیبان"],
        ["🏠 بازگشت به منوی اصلی"],
    ], resize_keyboard=True)


async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as exc:
        print("MEMBERSHIP ERROR:", repr(exc))
        return True


async def show_join(message):
    await message.reply_text(
        "برای استفاده از فروشگاه ابتدا عضو کانال شوید 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📣 عضویت در کانال", url=CHANNEL_LINK)],
            [InlineKeyboardButton("✅ عضو شدم", callback_data="check_member")],
        ]),
    )


async def send_product(message, code):
    code = normalize_code(code)
    if not code:
        await message.reply_text("❌ کد باید بین 001 تا 999 باشد.")
        return
    product = get_product(code)
    if not product:
        await message.reply_text(f"❌ محصول با کد {code} ثبت نشده است.")
        return

    available = [
        size for size in sizes_for(product["category"])
        if get_stock(code, size) > 0
    ]
    buy_button = (
        InlineKeyboardButton("🛒 خرید این مدل", callback_data=f"buy:{code}")
        if available else
        InlineKeyboardButton("❌ ناموجود", callback_data="nothing")
    )
    caption = (
        f"👟 {product['name']}\n\n"
        f"🏷 کد محصول: {code}\n"
        f"👤 دسته: {'زنانه' if product['category'] == 'women' else 'مردانه'}\n"
        f"{'📏 سایزهای موجود: ' + ' - '.join(available) if available else '❌ فعلاً ناموجود'}\n"
        f"💰 قیمت: {money(product['price'])} تومان\n"
        f"🚚 هزینه ارسال: {money(SHIPPING_COST)} تومان"
    )
    keyboard = InlineKeyboardMarkup([
        [buy_button],
        [InlineKeyboardButton("📣 کانال کتونی 530", url=CHANNEL_LINK)],
    ])
    if product["photo"]:
        try:
            await message.reply_photo(
                photo=product["photo"], caption=caption, reply_markup=keyboard
            )
            return
        except Exception as exc:
            print("PHOTO ERROR:", repr(exc))
    await message.reply_text(caption, reply_markup=keyboard)


async def show_products(message, category=None, limit=None):
    products = get_products(category, limit)
    if not products:
        await message.reply_text("فعلاً محصولی در این بخش ثبت نشده است.")
        return
    for product in products:
        await send_product(message, product["code"])


async def admin_home(message):
    await message.reply_text(
        "🔐 مدیریت فروشگاه\n\nبخش موردنظر را انتخاب کنید 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👟 محصولات زنانه", callback_data="admin_cat:women")],
            [InlineKeyboardButton("👞 محصولات مردانه", callback_data="admin_cat:men")],
            [InlineKeyboardButton("➕ افزودن محصول جدید", callback_data="admin_add")],
        ]),
    )


async def admin_category(message, category):
    if category not in ("women", "men"):
        return
    buttons = [
        [InlineKeyboardButton(
            f"{product['code']} | {product['name']}",
            callback_data=f"admin_product:{product['code']}",
        )]
        for product in get_products(category)
    ]
    buttons += [
        [InlineKeyboardButton("➕ افزودن محصول جدید", callback_data="admin_add")],
        [InlineKeyboardButton("⬅️ برگشت", callback_data="admin_home")],
    ]
    title = "زنانه" if category == "women" else "مردانه"
    await message.reply_text(
        f"📦 محصولات {title}\n\nمحصول را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def admin_product(message, code):
    product = get_product(code)
    if not product:
        await message.reply_text("❌ محصول پیدا نشد.")
        return
    caption = (
        "📦 مدیریت محصول\n\n"
        f"👟 {product['name']}\n"
        f"🏷 کد: {product['code']}\n"
        f"👤 دسته: {'زنانه' if product['category'] == 'women' else 'مردانه'}\n"
        f"💰 قیمت: {money(product['price'])} تومان\n"
        f"🚚 ارسال: {money(SHIPPING_COST)} تومان\n\n"
        "📏 موجودی سایزها:\n"
    )
    buttons = []
    for size in sizes_for(product["category"]):
        quantity = get_stock(code, size)
        caption += f"سایز {size} = {quantity} جفت\n"
        buttons.append([
            InlineKeyboardButton("➖", callback_data=f"stock_minus:{code}:{size}"),
            InlineKeyboardButton(f"سایز {size} | {quantity}", callback_data="nothing"),
            InlineKeyboardButton("➕", callback_data=f"stock_plus:{code}:{size}"),
        ])
    buttons += [
        [
            InlineKeyboardButton("🖼 افزودن/تغییر عکس", callback_data=f"admin_photo:{code}"),
            InlineKeyboardButton("🗑 حذف عکس", callback_data=f"admin_photo_remove:{code}"),
        ],
        [
            InlineKeyboardButton("💰 تغییر قیمت", callback_data=f"admin_price:{code}"),
            InlineKeyboardButton("✏️ تغییر نام", callback_data=f"admin_name:{code}"),
        ],
        [InlineKeyboardButton("🗑 حذف محصول", callback_data=f"admin_delete:{code}")],
        [InlineKeyboardButton("⬅️ برگشت", callback_data=f"admin_cat:{product['category']}")],
    ]
    markup = InlineKeyboardMarkup(buttons)
    if product["photo"]:
        try:
            await message.reply_photo(
                photo=product["photo"], caption=caption, reply_markup=markup
            )
            return
        except Exception as exc:
            print("ADMIN PHOTO ERROR:", repr(exc))
    await message.reply_text(caption, reply_markup=markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_message:
        return
    context.user_data.clear()
    user_id = update.effective_user.id
    code = normalize_code(context.args[0]) if context.args else None
    if not await is_member(context.bot, user_id):
        if code:
            context.user_data["pending_product"] = code
        await show_join(update.effective_message)
        return
    await update.effective_message.reply_text(
        "👋 به فروشگاه کتونی 530 خوش آمدید.",
        reply_markup=main_keyboard(user_id),
    )
    if code:
        await send_product(update.effective_message, code)
    else:
        await show_products(update.effective_message, limit=10)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_message:
        return
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("⛔ دسترسی ندارید.")
        return
    context.user_data.clear()
    await admin_home(update.effective_message)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.message:
        return
    data = query.data or ""
    user_id = query.from_user.id
    await query.answer()

    if data == "nothing":
        return

    if data == "check_member":
        if not await is_member(context.bot, user_id):
            await query.message.reply_text("❌ هنوز عضویت کانال تأیید نشده است.")
            return
        await query.message.reply_text(
            "✅ عضویت تأیید شد.", reply_markup=main_keyboard(user_id)
        )
        code = context.user_data.pop("pending_product", None)
        if code:
            await send_product(query.message, code)
        else:
            await show_products(query.message, limit=10)
        return

    if not is_admin(user_id) and not await is_member(context.bot, user_id):
        await show_join(query.message)
        return

    if data.startswith("buy:"):
        code = data.split(":", 1)[1]
        product = get_product(code)
        if not product:
            await query.message.reply_text("❌ محصول پیدا نشد.")
            return
        buttons = []
        for size in sizes_for(product["category"]):
            quantity = get_stock(code, size)
            if quantity > 0:
                buttons.append([InlineKeyboardButton(
                    f"سایز {size} | {quantity} جفت",
                    callback_data=f"size:{code}:{size}",
                )])
        if not buttons:
            await query.message.reply_text("❌ موجودی این مدل تمام شده است.")
            return
        total = int(product["price"]) + SHIPPING_COST
        await query.message.reply_text(
            f"👟 {product['name']}\n"
            f"💰 قیمت کفش: {money(product['price'])} تومان\n"
            f"🚚 ارسال: {money(SHIPPING_COST)} تومان\n"
            f"💳 مبلغ نهایی: {money(total)} تومان\n\n"
            "📏 سایز موردنظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("size:"):
        _, code, size = data.split(":", 2)
        product = get_product(code)
        if not product or size not in sizes_for(product["category"]):
            await query.message.reply_text("❌ محصول یا سایز پیدا نشد.")
            return
        if get_stock(code, size) <= 0:
            await query.message.reply_text("❌ این سایز تمام شده است.")
            return
        context.user_data.clear()
        context.user_data.update({
            "ordering": True,
            "step": "name",
            "product_code": code,
            "size": size,
        })
        total = int(product["price"]) + SHIPPING_COST
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

    if not (data.startswith("admin_") or data.startswith("stock_")):
        return
    if not is_admin(user_id):
        await query.message.reply_text("⛔ دسترسی ندارید.")
        return

    if data == "admin_home":
        await admin_home(query.message)
    elif data.startswith("admin_cat:"):
        await admin_category(query.message, data.split(":", 1)[1])
    elif data == "admin_add":
        context.user_data.clear()
        context.user_data.update({"admin_add": True, "admin_step": "code"})
        await query.message.reply_text(
            "➕ افزودن محصول\n\nکد محصول را بفرستید.\nاز 001 تا 999\nمثال: 008",
            reply_markup=cancel_keyboard(),
        )
    elif data.startswith("admin_product:"):
        await admin_product(query.message, data.split(":", 1)[1])
    elif data.startswith("stock_plus:") or data.startswith("stock_minus:"):
        action, code, size = data.split(":", 2)
        quantity = change_stock(code, size, 1 if action == "stock_plus" else -1)
        if quantity is None:
            await query.message.reply_text("❌ محصول یا سایز پیدا نشد.")
            return
        await query.message.reply_text(f"✅ سایز {size}: {quantity} جفت")
        await admin_product(query.message, code)
    elif data.startswith("admin_photo:"):
        code = data.split(":", 1)[1]
        context.user_data.clear()
        context.user_data["admin_photo_code"] = code
        await query.message.reply_text(
            f"🖼 عکس محصول {code}\n\nحالا عکس کفش را بفرستید.",
            reply_markup=cancel_keyboard(),
        )
    elif data.startswith("admin_photo_remove:"):
        code = data.split(":", 1)[1]
        update_product_field(code, "photo", None)
        await query.message.reply_text("✅ عکس حذف شد.")
        await admin_product(query.message, code)
    elif data.startswith("admin_price:"):
        context.user_data.clear()
        context.user_data["admin_price_code"] = data.split(":", 1)[1]
        await query.message.reply_text(
            "💰 قیمت جدید را فقط به تومان بفرستید.",
            reply_markup=cancel_keyboard(),
        )
    elif data.startswith("admin_name:"):
        context.user_data.clear()
        context.user_data["admin_name_code"] = data.split(":", 1)[1]
        await query.message.reply_text(
            "✏️ نام جدید محصول را بفرستید.",
            reply_markup=cancel_keyboard(),
        )
    elif data.startswith("admin_delete_yes:"):
        code = data.split(":", 1)[1]
        product = get_product(code, include_inactive=True)
        if not product:
            await query.message.reply_text("❌ محصول پیدا نشد.")
            return
        update_product_field(code, "active", False)
        await query.message.reply_text("✅ محصول حذف شد.")
        await admin_category(query.message, product["category"])
    elif data.startswith("admin_delete:"):
        code = data.split(":", 1)[1]
        await query.message.reply_text(
            f"⚠️ محصول {code} حذف شود؟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ بله، حذف شود", callback_data=f"admin_delete_yes:{code}"
                )],
                [InlineKeyboardButton(
                    "❌ خیر", callback_data=f"admin_product:{code}"
                )],
            ]),
        )


def create_zibal_payment(order):
    payload = {
        "merchant": ZIBAL_MERCHANT,
        "amount": int(order["amount_rial"]),
        "callbackUrl": f"{PUBLIC_URL}/zibal/callback",
        "description": f"Katoni 530 Order #{order['id']}",
        "mobile": order["mobile"],
    }
    response = requests.post(ZIBAL_REQUEST_URL, json=payload, timeout=25)
    response.raise_for_status()
    data = response.json()
    if int(data.get("result", 0)) != 100:
        raise RuntimeError(f"Zibal request failed: {data.get('result')}")
    track_id = str(data.get("trackId") or "")
    if not track_id.isdigit():
        raise RuntimeError("Zibal trackId دریافت نشد")
    return track_id


def verify_zibal(track_id):
    response = requests.post(
        ZIBAL_VERIFY_URL,
        json={"merchant": ZIBAL_MERCHANT, "trackId": int(track_id)},
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def telegram_send(chat_id, message):
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": str(chat_id), "text": message},
            timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:
        print("TELEGRAM SEND ERROR:", repr(exc))


class PaymentHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("HTTP:", fmt % args)

    def page(self, title, message):
        body = (
            '<!doctype html><html lang="fa" dir="rtl">'
            '<head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '</head><body style="font-family:sans-serif;text-align:center;padding:40px">'
            f"<h2>{html.escape(title)}</h2>"
            f"<p>{html.escape(message)}</p>"
            "<p>👟 کتونی 530</p></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.page("کتونی 530", "ربات و درگاه پرداخت فعال است.")
            return
        if parsed.path != "/zibal/callback":
            self.send_error(404)
            return

        params = parse_qs(parsed.query)
        track_id = (
            params.get("trackId", [""])[0]
            or params.get("trackid", [""])[0]
        )
        if not track_id or not track_id.isdigit():
            self.page("خطا", "شناسه پرداخت دریافت نشد.")
            return

        try:
            order = get_order_by_track(track_id)
            if not order:
                self.page("خطا", "سفارش پیدا نشد.")
                return
            if order["status"] == "paid":
                self.page("پرداخت تأیید شده ✅", "این سفارش قبلاً ثبت شده است.")
                return

            if params.get("success", [""])[0] != "1":
                mark_failed(order["id"])
                telegram_send(order["telegram_chat_id"], "❌ پرداخت انجام نشد یا لغو شد.")
                self.page("پرداخت ناموفق ❌", "پرداخت انجام نشد.")
                return

            data = verify_zibal(track_id)
            if int(data.get("result", 0)) not in (100, 201):
                self.page("پرداخت تأیید نشد", "تأیید نهایی پرداخت دریافت نشد.")
                return
            if data.get("amount") is not None and int(data["amount"]) != int(order["amount_rial"]):
                self.page("خطا", "مبلغ پرداخت صحیح نیست.")
                return

            ref_number = str(data.get("refNumber") or track_id)
            stock_ok, remaining, newly_paid = finalize_paid(order["id"], ref_number)
            if newly_paid:
                telegram_send(
                    order["telegram_chat_id"],
                    "✅ پرداخت موفق بود.\n\n"
                    f"🧾 سفارش: {order['id']}\n"
                    f"👟 {order['product_name']}\n"
                    f"📏 سایز: {order['size']}\n"
                    f"💰 قیمت کفش: {money(order['product_price_toman'])} تومان\n"
                    f"🚚 ارسال: {money(order['shipping_toman'])} تومان\n"
                    f"💳 پرداختی: {money(order['amount_toman'])} تومان",
                )
                if ADMIN_CHAT_ID:
                    alert = (
                        "🔔 سفارش جدید پرداخت شد\n\n"
                        f"🧾 سفارش: {order['id']}\n"
                        f"🏷 کد: {order['product_code']}\n"
                        f"📏 سایز: {order['size']}\n"
                        f"👤 {order['customer_name']}\n"
                        f"📱 {order['mobile']}\n"
                        f"📍 {order['address']}\n"
                    )
                    alert += (
                        f"📦 موجودی باقی‌مانده: {remaining} جفت"
                        if stock_ok else
                        "⚠️ پرداخت موفق است ولی موجودی این سایز هنگام تأیید صفر بود."
                    )
                    telegram_send(ADMIN_CHAT_ID, alert)
            self.page("پرداخت موفق ✅", f"سفارش شماره {order['id']} ثبت شد.")
        except Exception as exc:
            print("PAYMENT CALLBACK ERROR:", repr(exc))
            self.page(
                "خطا در بررسی پرداخت",
                "اگر مبلغ کسر شده، دوباره پرداخت نکنید و با پشتیبانی تماس بگیرید.",
            )


def run_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), PaymentHandler)
    print("HTTP SERVER STARTED:", PORT)
    server.serve_forever()


def parse_price(value):
    value = value.replace(",", "").replace("٬", "").replace(" ", "")
    return int(value) if value.isdigit() and int(value) > 0 else None


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or update.message.text is None:
        return
    text = update.message.text.strip()
    user_id = update.effective_user.id
    ud = context.user_data

    if not await is_member(context.bot, user_id):
        await show_join(update.message)
        return

    if text in ("❌ لغو عملیات", "🏠 بازگشت به منوی اصلی"):
        ud.clear()
        await update.message.reply_text(
            "🏠 منوی اصلی", reply_markup=main_keyboard(user_id)
        )
        return

    if ud.get("admin_add"):
        if not is_admin(user_id):
            ud.clear()
            return
        step = ud.get("admin_step")
        if step == "code":
            code = normalize_code(text)
            if not code:
                await update.message.reply_text("❌ کد باید بین 001 تا 999 باشد.")
                return
            existing = get_product(code, include_inactive=True)
            if existing and existing["active"]:
                await update.message.reply_text("❌ این کد قبلاً ثبت شده است.")
                return
            ud["new_code"] = code
            ud["admin_step"] = "name"
            await update.message.reply_text("👟 نام مدل را بفرستید.")
            return
        if step == "name":
            ud["new_name"] = text
            ud["admin_step"] = "price"
            await update.message.reply_text(
                "💰 قیمت را فقط به تومان بفرستید.\nمثال: 7900000"
            )
            return
        if step == "price":
            price = parse_price(text)
            if price is None:
                await update.message.reply_text("❌ فقط عدد قیمت را بفرستید.")
                return
            ud["new_price"] = price
            ud["admin_step"] = "category"
            await update.message.reply_text(
                "محصول زنانه است یا مردانه؟",
                reply_markup=ReplyKeyboardMarkup(
                    [["👟 زنانه", "👞 مردانه"], ["❌ لغو عملیات"]],
                    resize_keyboard=True,
                ),
            )
            return
        if step == "category":
            category = {
                "👟 زنانه": "women",
                "👞 مردانه": "men",
            }.get(text)
            if not category:
                await update.message.reply_text("زنانه یا مردانه را انتخاب کنید.")
                return
            code = ud["new_code"]
            create_product(code, ud["new_name"], ud["new_price"], category)
            ud.clear()
            await update.message.reply_text(
                "✅ محصول ثبت شد.", reply_markup=main_keyboard(user_id)
            )
            await admin_product(update.message, code)
            return

    if ud.get("admin_price_code"):
        if not is_admin(user_id):
            ud.clear()
            return
        price = parse_price(text)
        if price is None:
            await update.message.reply_text("❌ فقط عدد قیمت را بفرستید.")
            return
        code = ud["admin_price_code"]
        update_product_field(code, "price", price)
        ud.clear()
        await update.message.reply_text("✅ قیمت تغییر کرد.")
        await admin_product(update.message, code)
        return

    if ud.get("admin_name_code"):
        if not is_admin(user_id):
            ud.clear()
            return
        code = ud["admin_name_code"]
        update_product_field(code, "name", text)
        ud.clear()
        await update.message.reply_text("✅ نام تغییر کرد.")
        await admin_product(update.message, code)
        return

    if ud.get("ordering"):
        step = ud.get("step")
        if step == "name":
            ud["customer_name"] = text
            ud["step"] = "mobile"
            await update.message.reply_text(
                "📱 شماره موبایل را وارد کنید.\nمثال: 09123456789"
            )
            return
        if step == "mobile":
            mobile = text.replace(" ", "").replace("-", "")
            if not (mobile.isdigit() and len(mobile) == 11 and mobile.startswith("09")):
                await update.message.reply_text("❌ شماره موبایل صحیح نیست.")
                return
            ud["mobile"] = mobile
            ud["step"] = "address"
            await update.message.reply_text("📍 آدرس کامل ارسال را بفرستید:")
            return
        if step == "address":
            if len(text) < 5:
                await update.message.reply_text("آدرس کامل‌تری وارد کنید.")
                return
            code = ud["product_code"]
            size = ud["size"]
            product = get_product(code)
            if not product or get_stock(code, size) <= 0:
                ud.clear()
                await update.message.reply_text(
                    "❌ محصول یا سایز ناموجود شده است.",
                    reply_markup=main_keyboard(user_id),
                )
                return
            try:
                order_id = create_order(
                    user_id, update.effective_chat.id, product, size,
                    ud["customer_name"], ud["mobile"], text,
                )
                order = get_order(order_id)
                track_id = create_zibal_payment(order)
                set_track_id(order_id, track_id)
                total = int(product["price"]) + SHIPPING_COST
                await update.message.reply_text(
                    "🧾 فاکتور سفارش\n\n"
                    f"🔢 شماره سفارش: {order_id}\n"
                    f"👟 {product['name']}\n"
                    f"📏 سایز: {size}\n"
                    f"💰 قیمت کفش: {money(product['price'])} تومان\n"
                    f"🚚 هزینه ارسال: {money(SHIPPING_COST)} تومان\n"
                    f"💳 مبلغ نهایی: {money(total)} تومان\n\n"
                    "⚠️ سفارش بعد از پرداخت موفق ثبت نهایی می‌شود.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            "💳 پرداخت آنلاین",
                            url=f"{ZIBAL_START_URL}{track_id}",
                        )]
                    ]),
                )
                ud.clear()
            except Exception as exc:
                print("PAYMENT ERROR:", repr(exc))
                ud.clear()
                await update.message.reply_text(
                    "❌ اتصال به درگاه انجام نشد. لطفاً دوباره تلاش کنید.",
                    reply_markup=main_keyboard(user_id),
                )
            return

    if ud.get("searching"):
        ud.clear()
        await send_product(update.message, text)
        return

    if ud.get("tracking"):
        if not text.isdigit():
            await update.message.reply_text("❌ شماره سفارش باید عدد باشد.")
            return
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM orders
                    WHERE id=%s AND telegram_user_id=%s
                """, (int(text), user_id))
                order = cur.fetchone()
        ud.clear()
        if not order:
            await update.message.reply_text("❌ سفارش پیدا نشد.")
            return
        status = {
            "waiting_payment": "⏳ در انتظار پرداخت",
            "paid": "✅ پرداخت شده",
            "payment_failed": "❌ پرداخت ناموفق",
        }.get(order["status"], order["status"])
        await update.message.reply_text(
            f"📦 سفارش {order['id']}\n"
            f"👟 {order['product_name']}\n"
            f"📏 سایز: {order['size']}\n"
            f"📌 وضعیت: {status}",
            reply_markup=main_keyboard(user_id),
        )
        return

    if ud.get("support_mode"):
        if ADMIN_CHAT_ID:
            user = update.effective_user
            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=(
                    "📩 پیام مشتری\n\n"
                    f"👤 {user.full_name}\n"
                    f"🆔 {user.id}\n\n"
                    f"💬 {text}"
                ),
            )
        ud.clear()
        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد.",
            reply_markup=support_keyboard(),
        )
        return

    if text == "🔥 جدیدترین مدل‌ها":
        await show_products(update.message, limit=10)
    elif text == "👟 کفش زنانه":
        await show_products(update.message, category="women")
    elif text == "👞 کفش مردانه":
        await show_products(update.message, category="men")
    elif text in (
        "🔎 جستجو با کد محصول",
        "💰 قیمت و موجودی",
        "💰 استعلام قیمت و موجودی",
    ):
        ud.clear()
        ud["searching"] = True
        await update.message.reply_text(
            "🔎 کد محصول را وارد کنید.\nاز 001 تا 999\nمثال: 008",
            reply_markup=cancel_keyboard(),
        )
    elif text == "🛒 ثبت سفارش":
        await show_products(update.message, limit=10)
    elif text == "📦 پیگیری سفارش":
        ud.clear()
        ud["tracking"] = True
        await update.message.reply_text(
            "📦 شماره سفارش را وارد کنید:",
            reply_markup=cancel_keyboard(),
        )
    elif text in ("📏 راهنمای سایز", "📏 راهنمای انتخاب سایز"):
        await update.message.reply_text(
            "📏 سایزبندی فروشگاه\n\n"
            "👟 زنانه:\n37 - 38 - 39 - 40\n\n"
            "👞 مردانه:\n41 - 42 - 43 - 44 - 45"
        )
    elif text == "💳 پرداخت و مشکلات پرداخت":
        await update.message.reply_text(
            "اگر مبلغ کسر شد ولی سفارش تأیید نشد، دوباره پرداخت نکنید و با پشتیبانی تماس بگیرید.",
            reply_markup=support_keyboard(),
        )
    elif text == "👨‍💬 پشتیبانی":
        await update.message.reply_text(
            "👨‍💬 مرکز پشتیبانی", reply_markup=support_keyboard()
        )
    elif text in (
        "💳 مشکل پرداخت",
        "🔄 تعویض / مشکل سفارش",
        "👨‍💼 ارتباط مستقیم با پشتیبان",
    ):
        ud.clear()
        ud["support_mode"] = True
        await update.message.reply_text(
            "پیام خود را بفرستید. می‌توانید عکس هم بفرستید.",
            reply_markup=cancel_keyboard(),
        )
    elif text == "🛍 راهنمای خرید":
        await update.message.reply_text(
            "1️⃣ مدل را انتخاب کنید.\n"
            "2️⃣ سایز را انتخاب کنید.\n"
            "3️⃣ نام، موبایل و آدرس را وارد کنید.\n"
            "4️⃣ مبلغ کفش و هزینه ارسال را پرداخت کنید.\n"
            "5️⃣ پس از پرداخت موفق، موجودی همان سایز یک جفت کم می‌شود."
        )
    elif text == "📣 کانال تلگرام":
        await update.message.reply_text(
            "📣 کانال رسمی 👇",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📣 ورود به کانال", url=CHANNEL_LINK)]
            ]),
        )
    elif text == "🔐 مدیریت فروشگاه":
        if is_admin(user_id):
            await admin_home(update.message)
        else:
            await update.message.reply_text("⛔ دسترسی ندارید.")
    else:
        code = normalize_code(text)
        if code:
            await send_product(update.message, code)
        else:
            await update.message.reply_text(
                "یکی از گزینه‌های منو را انتخاب کنید.",
                reply_markup=main_keyboard(user_id),
            )


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    ud = context.user_data

    if ud.get("admin_photo_code"):
        if not is_admin(user_id):
            ud.clear()
            return
        if not update.message.photo:
            await update.message.reply_text("❌ عکس را به صورت Photo ارسال کنید.")
            return
        code = ud["admin_photo_code"]
        update_product_field(code, "photo", update.message.photo[-1].file_id)
        ud.clear()
        await update.message.reply_text("✅ عکس محصول ذخیره شد.")
        await admin_product(update.message, code)
        return

    if ud.get("support_mode"):
        if ADMIN_CHAT_ID:
            user = update.effective_user
            await context.bot.send_message(
                chat_id=int(ADMIN_CHAT_ID),
                text=f"📩 عکس/فایل مشتری\n\n👤 {user.full_name}\n🆔 {user.id}",
            )
            await update.message.copy(chat_id=int(ADMIN_CHAT_ID))
        ud.clear()
        await update.message.reply_text(
            "✅ برای پشتیبانی ارسال شد.",
            reply_markup=support_keyboard(),
        )


async def error_handler(update, context):
    print("TELEGRAM HANDLER ERROR:", repr(context.error))


def main():
    required = {
        "TELEGRAM_BOT_TOKEN": TOKEN,
        "DATABASE_URL": DATABASE_URL,
        "ZIBAL_MERCHANT": ZIBAL_MERCHANT,
        "PUBLIC_URL": PUBLIC_URL,
    }
    for name, value in required.items():
        if not value:
            raise RuntimeError(f"{name} تنظیم نشده است")

    init_db()
    threading.Thread(target=run_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.ALL | filters.VIDEO,
        media_handler,
    ))
    app.add_error_handler(error_handler)
    print("KATONI 530 BOT STARTED WITH POSTGRESQL")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

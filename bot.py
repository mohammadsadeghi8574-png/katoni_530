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


# =========================================================
# محصولات
#
# قیمت‌ها فقط تومان هستند.
# دلار فعلاً کاملاً حذف شده است.
# =========================================================

PRODUCTS = {
    "005": {
        "name": "New Balance 530 🤎",
        "category": "women",
        "price": 7_250_000,
        "sizes": ["37", "38", "39", "40"],

        # فعلاً عکس را بعداً به این محصول متصل می‌کنیم.
        "photo": None,
    },
}


# =========================================================
# دیتابیس سفارش‌ها
# =========================================================

DB_FILE = "orders.db"


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
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            paid_at DATETIME
        )
    """)

    conn.commit()
    conn.close()


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
    # زیبال مبلغ را به ریال دریافت می‌کند.
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

    cur.execute(
        "SELECT * FROM orders WHERE id = ?",
        (order_id,)
    )

    row = cur.fetchone()

    conn.close()

    return row


def get_order_by_track_id(track_id):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM orders WHERE track_id = ?",
        (str(track_id),)
    )

    row = cur.fetchone()

    conn.close()

    return row


def get_user_order(order_id, telegram_user_id):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM orders
        WHERE id = ?
        AND telegram_user_id = ?
    """, (
        order_id,
        telegram_user_id,
    ))

    row = cur.fetchone()

    conn.close()

    return row


def set_track_id(order_id, track_id):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute(
        "UPDATE orders SET track_id = ? WHERE id = ?",
        (
            str(track_id),
            order_id,
        )
    )

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
# ابزارها
# =========================================================

def money(value):
    return f"{int(value):,}"


def normalize_code(value):
    value = value.strip()

    if value.isdigit():
        return value.zfill(3)

    return value.upper()


def clear_mode(context):
    context.user_data.clear()


# =========================================================
# منوی اصلی
# =========================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🔥 جدیدترین مدل‌ها"],
            ["👟 کفش زنانه", "👟 کفش مردانه"],
            ["🔎 جستجو با کد محصول"],
            ["🛒 ثبت سفارش", "📦 پیگیری سفارش"],
            ["💰 قیمت و موجودی", "📏 راهنمای سایز"],
            ["💳 پرداخت و مشکلات پرداخت"],
            ["👨‍💬 پشتیبانی", "📣 کانال تلگرام"],
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

        # در صورت خطای موقت تلگرام مشتری قفل نشود.
        return True


async def show_join_message(update):
    keyboard = InlineKeyboardMarkup(
        [
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
        ]
    )

    await update.effective_message.reply_text(
        "سلام 👋\n\n"
        "برای استفاده از فروشگاه کتونی 530 "
        "ابتدا عضو کانال شوید 👇\n\n"
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
            "کد محصول را دوباره بررسی کنید.\n"
            "مثال: 005"
        )
        return

    sizes_text = " - ".join(product["sizes"])

    caption = (
        f"👟 {product['name']}\n\n"
        f"🏷 کد محصول: {code}\n"
        f"📏 سایزهای موجود: {sizes_text}\n"
        f"💰 قیمت: {money(product['price'])} تومان\n\n"
        "برای خرید روی دکمه زیر بزنید 👇"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛒 خرید این مدل",
                    callback_data=f"buy:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    "📣 مشاهده کانال",
                    url=CHANNEL_LINK,
                )
            ],
        ]
    )

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


async def show_products_by_category(message, category):
    found = False

    for code, product in PRODUCTS.items():
        if product["category"] == category:
            found = True

            await send_product(
                message,
                code
            )

    if not found:
        await message.reply_text(
            "فعلاً مدلی در این بخش ثبت نشده است."
        )


async def show_latest_products(message):
    await message.reply_text(
        "🔥 جدیدترین مدل‌های کتونی 530\n\n"
        "مدل موردنظر را انتخاب کنید 👇"
    )

    # فعلاً همه محصولات ثبت‌شده را نمایش می‌دهیم.
    for code in PRODUCTS:
        await send_product(
            message,
            code
        )


# =========================================================
# START
#
# /start
#
# یا خرید مستقیم:
# /start 005
#
# لینک:
# https://t.me/katoni_530_bot?start=005
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
        # اگر مشتری از لینک محصول آمده باشد،
        # کد را نگه می‌داریم تا بعد از عضویت محصول باز شود.
        if context.args:
            context.user_data[
                "pending_product"
            ] = normalize_code(
                context.args[0]
            )

        await show_join_message(update)
        return

    # اگر مشتری از لینک مستقیم محصول آمده است
    if context.args:
        code = normalize_code(
            context.args[0]
        )

        if code in PRODUCTS:
            await update.message.reply_text(
                "👋 به فروشگاه کتونی 530 خوش آمدید.\n\n"
                "محصولی که انتخاب کردید 👇",
                reply_markup=main_keyboard(),
            )

            await send_product(
                update.message,
                code
            )

            return

    # ورود معمولی به ربات
    await update.message.reply_text(
        "سلام 👋\n\n"
        "👟 به فروشگاه کتونی 530 خوش آمدید\n\n"
        "🔥 جدیدترین مدل‌ها را همین پایین ببینید 👇",
        reply_markup=main_keyboard(),
    )

    # ویترین از همان استارت
    await show_latest_products(
        update.message
    )


# =========================================================
# دکمه‌های ربات
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    data = query.data

    # -------------------------------------
    # تأیید عضویت
    # -------------------------------------

    if data == "check_membership":

        if not await is_member(
            context.bot,
            query.from_user.id
        ):
            await query.message.reply_text(
                "❌ هنوز عضویت شما تأیید نشده است.\n\n"
                "ابتدا عضو کانال شوید و دوباره "
                "روی «✅ عضو شدم» بزنید."
            )

            return

        await query.message.reply_text(
            "✅ عضویت شما تأیید شد.\n\n"
            "به فروشگاه کتونی 530 خوش آمدید 👟",
            reply_markup=main_keyboard(),
        )

        pending_product = (
            context.user_data.get(
                "pending_product"
            )
        )

        if (
            pending_product
            and pending_product in PRODUCTS
        ):
            context.user_data.pop(
                "pending_product",
                None
            )

            await send_product(
                query.message,
                pending_product
            )

        else:
            await show_latest_products(
                query.message
            )

        return

    # -------------------------------------
    # خرید
    # -------------------------------------

    if data.startswith("buy:"):

        code = normalize_code(
            data.split(":", 1)[1]
        )

        product = PRODUCTS.get(code)

        if not product:
            await query.message.reply_text(
                "❌ این محصول پیدا نشد."
            )
            return

        buttons = []
        row = []

        for size in product["sizes"]:
            row.append(
                InlineKeyboardButton(
                    f"سایز {size}",
                    callback_data=(
                        f"size:{code}:{size}"
                    ),
                )
            )

            if len(row) == 2:
                buttons.append(row)
                row = []

        if row:
            buttons.append(row)

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

    # -------------------------------------
    # انتخاب سایز
    # -------------------------------------

    if data.startswith("size:"):

        parts = data.split(":")

        if len(parts) != 3:
            return

        code = normalize_code(
            parts[1]
        )

        size = parts[2]

        product = PRODUCTS.get(code)

        if not product:
            await query.message.reply_text(
                "❌ محصول پیدا نشد."
            )
            return

        if size not in product["sizes"]:
            await query.message.reply_text(
                "❌ این سایز موجود نیست."
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
            "👤 لطفاً نام و نام خانوادگی خود را بفرستید:",
            reply_markup=cancel_keyboard(),
        )

        return


# =========================================================
# درخواست پرداخت زیبال
# =========================================================

def create_zibal_payment(order):
    if not ZIBAL_MERCHANT:
        raise Exception(
            "ZIBAL_MERCHANT تنظیم نشده است."
        )

    if not PUBLIC_URL:
        raise Exception(
            "PUBLIC_URL تنظیم نشده است."
        )

    callback_url = (
        f"{PUBLIC_URL}/zibal/callback"
    )

    payload = {
        "merchant": ZIBAL_MERCHANT,

        # مبلغ ذخیره‌شده به ریال
        "amount": int(
            order["amount_rial"]
        ),

        "callbackUrl": callback_url,

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

    print(
        "Zibal request:",
        data
    )

    if int(
        data.get("result", 0)
    ) != 100:
        raise Exception(
            data.get(
                "message",
                "Zibal payment error"
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
            "Zibal trackId دریافت نشد."
        )

    return track_id


# =========================================================
# تأیید پرداخت
# =========================================================

def verify_zibal(track_id):
    payload = {
        "merchant": ZIBAL_MERCHANT,
        "trackId": int(track_id),
    }

    response = requests.post(
        ZIBAL_VERIFY_URL,
        json=payload,
        timeout=20,
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# ارسال پیام تلگرام از Callback
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
                chat_id=int(chat_id),
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


def notify_paid_order(
    order,
    ref_number
):
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
            f"🧾 شماره سفارش: #{order['id']}\n"
            f"👟 محصول: {order['product_name']}\n"
            f"🏷 کد: {order['product_code']}\n"
            f"📏 سایز: {order['size']}\n"
            f"💰 مبلغ: {money(order['amount_toman'])} تومان\n\n"
            f"👤 مشتری: {order['customer_name']}\n"
            f"📱 موبایل: {order['mobile']}\n"
            f"📍 آدرس: {order['address']}\n\n"
            f"🔐 پیگیری پرداخت: {ref_number}"
        )

        send_telegram_sync(
            ADMIN_CHAT_ID,
            admin_text
        )


# =========================================================
# سرور Callback پرداخت
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

            <style>

                body {{
                    font-family: sans-serif;
                    background: #f5f5f5;
                    margin: 0;
                    padding: 30px 15px;
                    text-align: center;
                }}

                .box {{
                    max-width: 500px;
                    margin: auto;
                    background: white;
                    border-radius: 20px;
                    padding: 30px 20px;
                    box-shadow:
                        0 4px 20px
                        rgba(0,0,0,.08);
                }}

                p {{
                    line-height: 2;
                }}

            </style>

        </head>

        <body>

            <div class="box">

                <h2>
                    {html.escape(title)}
                </h2>

                <p>
                    {html.escape(message)}
                </p>

                <p>
                    می‌توانید این صفحه را ببندید
                    و به تلگرام برگردید.
                </p>

                <strong>
                    👟 کتونی 530
                </strong>

            </div>

        </body>

        </html>
        """

        body = page.encode(
            "utf-8"
        )

        self.send_response(200)

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

    def do_GET(self):
        parsed = urlparse(
            self.path
        )

        # صفحه اصلی Railway
        if parsed.path == "/":

            self.send_html(
                "کتونی 530",
                "ربات و درگاه پرداخت فعال است."
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
                "شناسه پرداخت دریافت نشد."
            )

            return

        order = get_order_by_track_id(
            track_id
        )

        if not order:

            self.send_html(
                "خطا",
                "سفارش مربوط به این پرداخت پیدا نشد."
            )

            return

        if order["status"] == "paid":

            self.send_html(
                "پرداخت تأیید شده است ✅",
                (
                    f"سفارش شماره "
                    f"{order['id']} "
                    f"قبلاً ثبت نهایی شده است."
                )
            )

            return

        if success != "1":

            mark_order_failed(
                order["id"]
            )

            send_telegram_sync(
                order["telegram_chat_id"],
                "❌ پرداخت انجام نشد یا لغو شد.\n\n"
                "سفارش نهایی ثبت نشده است."
            )

            self.send_html(
                "پرداخت ناموفق بود ❌",
                "سفارش شما نهایی نشده است."
            )

            return

        try:

            verify_data = verify_zibal(
                track_id
            )

            print(
                "Zibal verify:",
                verify_data
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
                    "تأیید نهایی پرداخت از زیبال دریافت نشد."
                )

                return

            # بررسی مبلغ برای امنیت بیشتر
            verified_amount = (
                verify_data.get(
                    "amount"
                )
            )

            if verified_amount is not None:

                verified_amount = int(
                    verified_amount
                )

                if verified_amount != int(
                    order["amount_rial"]
                ):

                    print(
                        "SECURITY: amount mismatch"
                    )

                    self.send_html(
                        "خطا در مبلغ پرداخت",
                        "مبلغ پرداخت با مبلغ سفارش مطابقت ندارد."
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

            order = get_order(
                order["id"]
            )

            notify_paid_order(
                order,
                ref_number
            )

            self.send_html(
                "پرداخت موفق بود ✅",
                (
                    f"سفارش شماره "
                    f"{order['id']} "
                    f"با موفقیت ثبت شد."
                )
            )

        except Exception as e:

            print(
                "VERIFY ERROR:",
                e
            )

            self.send_html(
                "خطا در بررسی پرداخت",
                (
                    "اگر مبلغ از حساب شما کسر شده، "
                    "دوباره پرداخت نکنید و با پشتیبانی تماس بگیرید."
                )
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
        f"HTTP server running on port {PORT}"
    )

    server.serve_forever()


# =========================================================
# ارسال پیام مشتری به پشتیبانی
# =========================================================

async def send_support_to_admin(
    update,
    context
):
    if not ADMIN_CHAT_ID:

        await update.message.reply_text(
            "❌ پشتیبانی در حال حاضر در دسترس نیست.",
            reply_markup=main_keyboard(),
        )

        clear_mode(context)

        return

    user = update.effective_user

    header = (
        "📩 پیام جدید مشتری\n\n"
        f"👤 نام تلگرام: {user.full_name}\n"
        f"🆔 Telegram ID: {user.id}\n"
    )

    if user.username:
        header += (
            f"🔗 @{user.username}\n"
        )

    header += (
        "\n👇 پیام مشتری:"
    )

    try:

        await context.bot.send_message(
            chat_id=int(
                ADMIN_CHAT_ID
            ),
            text=header,
        )

        await update.message.copy(
            chat_id=int(
                ADMIN_CHAT_ID
            )
        )

        clear_mode(context)

        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد.\n\n"
            "همکاران کتونی 530 پیام شما را بررسی می‌کنند.",
            reply_markup=support_keyboard(),
        )

    except Exception as e:

        print(
            "Support error:",
            e
        )

        await update.message.reply_text(
            "❌ ارسال پیام انجام نشد. لطفاً دوباره امتحان کنید.",
            reply_markup=support_keyboard(),
        )


# =========================================================
# پیام‌های متنی
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if (
        not update.message
        or not update.message.text
    ):
        return

    text = update.message.text.strip()

    if not await is_member(
        context.bot,
        update.effective_user.id
    ):
        await show_join_message(
            update
        )

        return

    # -------------------------------------
    # خانه
    # -------------------------------------

    if text == "🏠 بازگشت به منوی اصلی":

        clear_mode(context)

        await update.message.reply_text(
            "🏠 منوی اصلی کتونی 530",
            reply_markup=main_keyboard(),
        )

        return

    # -------------------------------------
    # لغو
    # -------------------------------------

    if text == "❌ لغو عملیات":

        clear_mode(context)

        await update.message.reply_text(
            "✅ عملیات لغو شد.\n\n"
            "به منوی اصلی برگشتید.",
            reply_markup=main_keyboard(),
        )

        return

    # =====================================================
    # مراحل سفارش
    # =====================================================

    if context.user_data.get(
        "ordering"
    ):

        step = context.user_data.get(
            "step"
        )

        # نام مشتری
        if step == "name":

            if len(text) < 2:

                await update.message.reply_text(
                    "لطفاً نام و نام خانوادگی خود را وارد کنید."
                )

                return

            context.user_data[
                "customer_name"
            ] = text

            context.user_data[
                "step"
            ] = "mobile"

            await update.message.reply_text(
                "📱 شماره موبایل خود را وارد کنید.\n\n"
                "مثال:\n"
                "09123456789",
                reply_markup=cancel_keyboard(),
            )

            return

        # موبایل
        if step == "mobile":

            mobile = (
                text
                .replace(" ", "")
                .replace("-", "")
            )

            if (
                not mobile.isdigit()
                or len(mobile) != 11
                or not mobile.startswith("09")
            ):

                await update.message.reply_text(
                    "❌ شماره موبایل صحیح نیست.\n\n"
                    "مثال صحیح:\n"
                    "09123456789"
                )

                return

            context.user_data[
                "mobile"
            ] = mobile

            context.user_data[
                "step"
            ] = "address"

            await update.message.reply_text(
                "📍 لطفاً آدرس کامل برای ارسال را بنویسید:",
                reply_markup=cancel_keyboard(),
            )

            return

        # آدرس
        if step == "address":

            if len(text) < 5:

                await update.message.reply_text(
                    "لطفاً آدرس کامل‌تری بنویسید."
                )

                return

            context.user_data[
                "address"
            ] = text

            code = context.user_data[
                "product_code"
            ]

            size = context.user_data[
                "size"
            ]

            product = PRODUCTS.get(
                code
            )

            if not product:

                clear_mode(context)

                await update.message.reply_text(
                    "❌ محصول پیدا نشد.",
                    reply_markup=main_keyboard(),
                )

                return

            price = product["price"]

            try:

                order_id = create_order(
                    telegram_user_id=
                        update.effective_user.id,

                    telegram_chat_id=
                        update.effective_chat.id,

                    product_code=code,

                    product_name=
                        product["name"],

                    size=size,

                    amount_toman=price,

                    customer_name=
                        context.user_data[
                            "customer_name"
                        ],

                    mobile=
                        context.user_data[
                            "mobile"
                        ],

                    address=
                        context.user_data[
                            "address"
                        ],
                )

                order = get_order(
                    order_id
                )

                track_id = create_zibal_payment(
                    order
                )

                set_track_id(
                    order_id,
                    track_id
                )

                payment_url = (
                    f"{ZIBAL_START_URL}{track_id}"
                )

                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "💳 پرداخت آنلاین",
                                url=payment_url,
                            )
                        ]
                    ]
                )

                customer_name = (
                    context.user_data[
                        "customer_name"
                    ]
                )

                mobile = (
                    context.user_data[
                        "mobile"
                    ]
                )

                address = (
                    context.user_data[
                        "address"
                    ]
                )

                await update.message.reply_text(
                    "🧾 فاکتور سفارش\n\n"
                    f"🔢 شماره سفارش: {order_id}\n"
                    f"👟 محصول: {product['name']}\n"
                    f"🏷 کد: {code}\n"
                    f"📏 سایز: {size}\n"
                    f"💰 مبلغ: {money(price)} تومان\n\n"
                    f"👤 نام: {customer_name}\n"
                    f"📱 موبایل: {mobile}\n"
                    f"📍 آدرس: {address}\n\n"
                    "⚠️ سفارش هنوز نهایی نشده است.\n\n"
                    "برای ثبت نهایی، پرداخت را انجام دهید 👇",
                    reply_markup=keyboard,
                )

                clear_mode(context)

            except Exception as e:

                print(
                    "PAYMENT CREATE ERROR:",
                    e
                )

                clear_mode(context)

                await update.message.reply_text(
                    "❌ اتصال به درگاه پرداخت انجام نشد.\n\n"
                    "هیچ مبلغی از حساب شما کسر نشده است.\n"
                    "لطفاً دوباره امتحان کنید.",
                    reply_markup=main_keyboard(),
                )

            return

    # =====================================================
    # جستجوی محصول
    # =====================================================

    if context.user_data.get(
        "searching"
    ):

        clear_mode(context)

        await send_product(
            update.message,
            normalize_code(text)
        )

        return

    # =====================================================
    # پیگیری سفارش
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
                "❌ شماره سفارش باید عدد باشد.\n\n"
                "مثال: 25",
                reply_markup=cancel_keyboard(),
            )

            return

        order = get_user_order(
            order_id,
            update.effective_user.id
        )

        if not order:

            await update.message.reply_text(
                "❌ سفارشی با این شماره برای شما پیدا نشد.",
                reply_markup=cancel_keyboard(),
            )

            return

        status = order["status"]

        if status == "paid":
            status_text = (
                "✅ پرداخت شده و ثبت نهایی شده"
            )

        elif status == "waiting_payment":
            status_text = (
                "⏳ در انتظار پرداخت"
            )

        elif status == "payment_failed":
            status_text = (
                "❌ پرداخت ناموفق یا لغو شده"
            )

        else:
            status_text = status

        clear_mode(context)

        await update.message.reply_text(
            "📦 وضعیت سفارش\n\n"
            f"🔢 شماره سفارش: {order['id']}\n"
            f"👟 محصول: {order['product_name']}\n"
            f"🏷 کد: {order['product_code']}\n"
            f"📏 سایز: {order['size']}\n"
            f"💰 مبلغ: {money(order['amount_toman'])} تومان\n"
            f"📌 وضعیت: {status_text}",
            reply_markup=main_keyboard(),
        )

        return

    # =====================================================
    # پیام پشتیبانی
    # =====================================================

    if context.user_data.get(
        "support_mode"
    ):

        await send_support_to_admin(
            update,
            context
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

        context.user_data[
            "searching"
        ] = True

        await update.message.reply_text(
            "🔎 کد محصول را وارد کنید.\n\n"
            "مثال:\n"
            "005",
            reply_markup=cancel_keyboard(),
        )

        return

    if text == "🛒 ثبت سفارش":

        await update.message.reply_text(
            "🛒 برای ثبت سفارش ابتدا مدل کفش را انتخاب کنید.\n\n"
            "می‌توانید از «🔥 جدیدترین مدل‌ها» استفاده کنید "
            "یا کد محصول را جستجو کنید.",
            reply_markup=main_keyboard(),
        )

        return

    if text == "📦 پیگیری سفارش":

        clear_mode(context)

        context.user_data[
            "tracking"
        ] = True

        await update.message.reply_text(
            "📦 شماره سفارش خود را وارد کنید:",
            reply_markup=cancel_keyboard(),
        )

        return

    if text in [
        "💰 قیمت و موجودی",
        "💰 استعلام قیمت و موجودی",
    ]:

        clear_mode(context)

        context.user_data[
            "searching"
        ] = True

        await update.message.reply_text(
            "💰 برای مشاهده قیمت و موجودی، "
            "کد محصول را وارد کنید.\n\n"
            "مثال: 005",
            reply_markup=cancel_keyboard(),
        )

        return

    if text in [
        "📏 راهنمای سایز",
        "📏 راهنمای انتخاب سایز",
    ]:

        await update.message.reply_text(
            "📏 راهنمای انتخاب سایز\n\n"
            "سایزهای موجود هر مدل داخل مشخصات همان محصول نمایش داده می‌شود.\n\n"
            "اگر بین دو سایز شک دارید، "
            "از بخش پشتیبانی پیام بدهید.",
            reply_markup=support_keyboard(),
        )

        return

    if text == "💳 پرداخت و مشکلات پرداخت":

        await update.message.reply_text(
            "💳 پرداخت و مشکلات پرداخت\n\n"
            "پرداخت سفارش‌ها از طریق درگاه امن انجام می‌شود.\n\n"
            "⚠️ اگر مبلغ از حساب شما کسر شد ولی سفارش تأیید نشد، "
            "دوباره پرداخت نکنید و از بخش «💳 مشکل پرداخت» پیام بدهید.",
            reply_markup=support_keyboard(),
        )

        return

    # =====================================================
    # پشتیبانی
    # =====================================================

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
            "1️⃣ مدل کفش را انتخاب کنید.\n"
            "2️⃣ سایز را انتخاب کنید.\n"
            "3️⃣ نام، موبایل و آدرس را وارد کنید.\n"
            "4️⃣ فاکتور را بررسی کنید.\n"
            "5️⃣ پرداخت آنلاین را انجام دهید.\n"
            "6️⃣ بعد از تأیید پرداخت، سفارش ثبت نهایی می‌شود. ✅",
            reply_markup=support_keyboard(),
        )

        return

    if text == "💳 مشکل پرداخت":

        clear_mode(context)

        context.user_data[
            "support_mode"
        ] = True

        await update.message.reply_text(
            "💳 مشکل پرداخت\n\n"
            "مشکل خود را همین‌جا بنویسید.\n\n"
            "اگر شماره سفارش دارید، آن را هم ارسال کنید.\n\n"
            "⚠️ شماره کارت، رمز یا اطلاعات محرمانه بانکی را ارسال نکنید.",
            reply_markup=cancel_keyboard(),
        )

        return

    if text == "🔄 تعویض / مشکل سفارش":

        clear_mode(context)

        context.user_data[
            "support_mode"
        ] = True

        await update.message.reply_text(
            "🔄 تعویض / مشکل سفارش\n\n"
            "شماره سفارش و توضیح مشکل را برای ما ارسال کنید.",
            reply_markup=cancel_keyboard(),
        )

        return

    if text == "👨‍💼 ارتباط مستقیم با پشتیبان":

        clear_mode(context)

        context.user_data[
            "support_mode"
        ] = True

        await update.message.reply_text(
            "👨‍💼 ارتباط مستقیم با پشتیبان\n\n"
            "پیام خود را همین‌جا ارسال کنید.\n\n"
            "پیام شما مستقیماً برای پشتیبانی کتونی 530 ارسال می‌شود. ✅",
            reply_markup=cancel_keyboard(),
        )

        return

    if text == "📣 کانال تلگرام":

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📣 ورود به کانال کتونی 530",
                        url=CHANNEL_LINK,
                    )
                ]
            ]
        )

        await update.message.reply_text(
            "📣 کانال رسمی کتونی 530\n\n"
            "جدیدترین مدل‌ها را در کانال ببینید 👇",
            reply_markup=keyboard,
        )

        return

    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های منو را انتخاب کنید 👇",
        reply_markup=main_keyboard(),
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

    if not context.user_data.get(
        "support_mode"
    ):
        await update.message.reply_text(
            "برای ارسال عکس یا فایل ابتدا وارد بخش 👨‍💬 پشتیبانی شوید.",
            reply_markup=main_keyboard(),
        )

        return

    if not ADMIN_CHAT_ID:

        await update.message.reply_text(
            "❌ پشتیبانی در حال حاضر در دسترس نیست."
        )

        return

    user = update.effective_user

    header = (
        "📩 عکس/فایل جدید از مشتری\n\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user.id}"
    )

    if user.username:
        header += (
            f"\n🔗 @{user.username}"
        )

    try:

        await context.bot.send_message(
            chat_id=int(
                ADMIN_CHAT_ID
            ),
            text=header,
        )

        await update.message.copy(
            chat_id=int(
                ADMIN_CHAT_ID
            )
        )

        clear_mode(context)

        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد.",
            reply_markup=support_keyboard(),
        )

    except Exception as e:

        print(
            "Media support error:",
            e
        )

        await update.message.reply_text(
            "❌ ارسال انجام نشد. دوباره امتحان کنید."
        )


# =========================================================
# Commands
# =========================================================

async def products_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    clear_mode(context)

    await show_latest_products(
        update.message
    )


async def search_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    clear_mode(context)

    context.user_data[
        "searching"
    ] = True

    await update.message.reply_text(
        "🔎 کد محصول را ارسال کنید.\n"
        "مثال: 005",
        reply_markup=cancel_keyboard(),
    )


async def order_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    clear_mode(context)

    await update.message.reply_text(
        "🛒 ابتدا مدل موردنظر را انتخاب کنید.",
        reply_markup=main_keyboard(),
    )


async def track_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    clear_mode(context)

    context.user_data[
        "tracking"
    ] = True

    await update.message.reply_text(
        "📦 شماره سفارش خود را وارد کنید:",
        reply_markup=cancel_keyboard(),
    )


async def support_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    clear_mode(context)

    await update.message.reply_text(
        "👨‍💬 مرکز پشتیبانی کتونی 530\n\n"
        "موضوع موردنظر را انتخاب کنید 👇",
        reply_markup=support_keyboard(),
    )


# =========================================================
# اجرای برنامه
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

    # سرور پرداخت Railway
    http_thread = threading.Thread(
        target=start_http_server,
        daemon=True,
    )

    http_thread.start()

    # ربات تلگرام
    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "products",
            products_command
        )
    )

    app.add_handler(
        CommandHandler(
            "search",
            search_command
        )
    )

    app.add_handler(
        CommandHandler(
            "order",
            order_command
        )
    )

    app.add_handler(
        CommandHandler(
            "track",
            track_command
        )
    )

    app.add_handler(
        CommandHandler(
            "support",
            support_command
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
            text_handler
        )
    )

    app.add_handler(
        MessageHandler(
            (
                filters.PHOTO
                | filters.Document.ALL
                | filters.VIDEO
            ),
            media_handler
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

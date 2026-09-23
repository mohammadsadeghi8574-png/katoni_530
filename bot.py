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

USD_RATE = 232_000  # تومان

ZIBAL_REQUEST_URL = "https://gateway.zibal.ir/v1/request"
ZIBAL_VERIFY_URL = "https://gateway.zibal.ir/v1/verify"
ZIBAL_START_URL = "https://gateway.zibal.ir/start/"


# =========================================================
# محصولات
# بعداً هر تعداد محصول خواستی به همین بخش اضافه می‌کنیم
# =========================================================

PRODUCTS = {
    "K530-05": {
        "name": "کتونی مردانه مدل K530-05",
        "category": "men",
        "usd_price": 55,
        "sizes": ["41", "42", "43", "44", "45"],
    },
    "K530-06": {
        "name": "کتونی زنانه مدل K530-06",
        "category": "women",
        "usd_price": 55,
        "sizes": ["37", "38", "39", "40"],
    },
}


# =========================================================
# دیتابیس
# =========================================================

DB_FILE = "orders.db"


def db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connection()
    cur = conn.cursor()

    cur.execute(
        """
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
        """
    )

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
    amount_rial = int(amount_toman) * 10

    conn = db_connection()
    cur = conn.cursor()

    cur.execute(
        """
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
        """,
        (
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
        ),
    )

    order_id = cur.lastrowid
    conn.commit()
    conn.close()

    return order_id


def set_track_id(order_id, track_id):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute(
        "UPDATE orders SET track_id = ? WHERE id = ?",
        (str(track_id), order_id),
    )

    conn.commit()
    conn.close()


def get_order_by_track_id(track_id):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM orders WHERE track_id = ?",
        (str(track_id),),
    )

    row = cur.fetchone()
    conn.close()

    return row


def get_order(order_id):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM orders WHERE id = ?",
        (order_id,),
    )

    row = cur.fetchone()
    conn.close()

    return row


def mark_order_paid(order_id, ref_number=""):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE orders
        SET status = 'paid',
            ref_number = ?,
            paid_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (str(ref_number or ""), order_id),
    )

    conn.commit()
    conn.close()


def mark_order_failed(order_id):
    conn = db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE orders
        SET status = 'payment_failed'
        WHERE id = ? AND status != 'paid'
        """,
        (order_id,),
    )

    conn.commit()
    conn.close()


# =========================================================
# قیمت
# =========================================================

def get_price_toman(product):
    return int(product["usd_price"] * USD_RATE)


def money(value):
    return f"{int(value):,}"


# =========================================================
# منوی اصلی
# =========================================================

def main_keyboard():
    keyboard = [
        ["👟 کفش مردانه ۴۱ تا ۴۵"],
        ["👟 کفش زنانه ۳۷ تا ۴۰"],
        ["🔎 جستجو با کد محصول"],
        ["🛒 ثبت سفارش", "📦 پیگیری سفارش"],
        ["💬 استعلام قیمت و موجودی"],
        ["👨‍💬 پشتیبانی", "📣 کانال تلگرام"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
    )


# =========================================================
# بررسی عضویت کانال
# =========================================================

async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(CHANNEL, user_id)

        return member.status in [
            "member",
            "administrator",
            "creator",
        ]

    except Exception as e:
        print("Membership check error:", e)

        # اگر تلگرام موقتاً خطا داد، ربات کاملاً قفل نشود
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
        "برای استفاده از ربات کتونی 530 ابتدا عضو کانال شوید 👇\n\n"
        "بعد از عضویت روی «✅ عضو شدم» بزنید.",
        reply_markup=keyboard,
    )


# =========================================================
# شروع
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    user_id = update.effective_user.id

    if not await is_member(context.bot, user_id):
        await show_join_message(update)
        return

    await update.effective_message.reply_text(
        "سلام 👋\n"
        "👟 به فروشگاه کتونی 530 خوش آمدید\n\n"
        "دسته‌بندی موردنظر را انتخاب کنید:",
        reply_markup=main_keyboard(),
    )


# =========================================================
# نمایش محصول
# =========================================================

async def send_product(message, code):
    code = code.upper().strip()

    product = PRODUCTS.get(code)

    if not product:
        await message.reply_text(
            "❌ محصولی با این کد پیدا نشد.\n\n"
            "کد محصول را دوباره بررسی کنید."
        )
        return

    price = get_price_toman(product)

    sizes_text = " - ".join(product["sizes"])

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛒 خرید این محصول",
                    callback_data=f"buy:{code}",
                )
            ]
        ]
    )

    await message.reply_text(
        f"👟 {product['name']}\n\n"
        f"🏷️ کد محصول: {code}\n"
        f"💵 قیمت پایه: {product['usd_price']} دلار\n"
        f"💵 نرخ دلار: {money(USD_RATE)} تومان\n"
        f"💰 قیمت امروز: {money(price)} تومان\n"
        f"📏 سایزهای موجود: {sizes_text}\n\n"
        "برای خرید روی دکمه زیر بزنید 👇",
        reply_markup=keyboard,
    )


# =========================================================
# محصولات دسته‌بندی
# =========================================================

async def show_category(update, category):
    found = False

    for code, product in PRODUCTS.items():
        if product["category"] == category:
            found = True
            await send_product(update.effective_message, code)

    if not found:
        await update.effective_message.reply_text(
            "فعلاً محصولی در این دسته ثبت نشده است."
        )


# =========================================================
# Callback دکمه‌ها
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "check_membership":

        if await is_member(context.bot, query.from_user.id):

            await query.message.reply_text(
                "✅ عضویت شما تأیید شد.\n\n"
                "به فروشگاه کتونی 530 خوش آمدید 👟",
                reply_markup=main_keyboard(),
            )

        else:

            await query.message.reply_text(
                "❌ هنوز عضویت شما در کانال تأیید نشده است.\n"
                "ابتدا عضو کانال شوید و دوباره امتحان کنید."
            )

        return

    if data.startswith("buy:"):

        code = data.split(":", 1)[1]

        product = PRODUCTS.get(code)

        if not product:
            await query.message.reply_text(
                "❌ محصول پیدا نشد."
            )
            return

        buttons = []

        for size in product["sizes"]:
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"سایز {size}",
                        callback_data=f"size:{code}:{size}",
                    )
                ]
            )

        await query.message.reply_text(
            f"📏 سایز موردنظر برای {code} را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    if data.startswith("size:"):

        parts = data.split(":")

        if len(parts) != 3:
            return

        code = parts[1]
        size = parts[2]

        product = PRODUCTS.get(code)

        if not product:
            await query.message.reply_text(
                "❌ محصول پیدا نشد."
            )
            return

        context.user_data.clear()

        context.user_data["ordering"] = True
        context.user_data["step"] = "name"
        context.user_data["product_code"] = code
        context.user_data["size"] = size

        price = get_price_toman(product)

        await query.message.reply_text(
            f"✅ محصول: {code}\n"
            f"📏 سایز: {size}\n"
            f"💰 مبلغ: {money(price)} تومان\n\n"
            "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
        )

        return


# =========================================================
# ساخت درخواست پرداخت زیبال
# =========================================================

def create_zibal_payment(order):
    if not ZIBAL_MERCHANT:
        raise Exception("ZIBAL_MERCHANT تنظیم نشده است.")

    if not PUBLIC_URL:
        raise Exception("PUBLIC_URL تنظیم نشده است.")

    callback_url = f"{PUBLIC_URL}/zibal/callback"

    payload = {
        "merchant": ZIBAL_MERCHANT,
        "amount": int(order["amount_rial"]),
        "callbackUrl": callback_url,
        "description": f"Katoni 530 - Order #{order['id']}",
        "mobile": order["mobile"],
    }

    response = requests.post(
        ZIBAL_REQUEST_URL,
        json=payload,
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    print("Zibal request response:", data)

    if int(data.get("result", 0)) != 100:
        raise Exception(
            f"Zibal error: {data.get('message', 'unknown error')}"
        )

    track_id = str(data.get("trackId", ""))

    if not track_id:
        raise Exception("Zibal trackId دریافت نشد.")

    return track_id


# =========================================================
# تأیید پرداخت زیبال
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

    data = response.json()

    print("Zibal verify response:", data)

    return data


# =========================================================
# ارسال پیام تلگرام از Callback پرداخت
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
        print("Telegram callback message error:", e)


def notify_paid_order(order, ref_number):
    customer_text = (
        "✅ پرداخت شما با موفقیت تأیید شد.\n\n"
        f"🧾 شماره سفارش: {order['id']}\n"
        f"👟 محصول: {order['product_code']}\n"
        f"📏 سایز: {order['size']}\n"
        f"💰 مبلغ: {money(order['amount_toman'])} تومان\n"
        f"🔐 کد پیگیری پرداخت: {ref_number or order['track_id']}\n\n"
        "📦 سفارش شما با موفقیت ثبت نهایی شد.\n"
        "کتونی 530 👟"
    )

    send_telegram_sync(
        order["telegram_chat_id"],
        customer_text,
    )

    if ADMIN_CHAT_ID:

        admin_text = (
            "🔔 سفارش جدید پرداخت شد\n\n"
            f"🧾 شماره سفارش: {order['id']}\n"
            f"👟 محصول: {order['product_code']}\n"
            f"📏 سایز: {order['size']}\n"
            f"💰 مبلغ: {money(order['amount_toman'])} تومان\n\n"
            f"👤 نام: {order['customer_name']}\n"
            f"📱 موبایل: {order['mobile']}\n"
            f"📍 آدرس: {order['address']}\n\n"
            f"🔐 کد پیگیری: {ref_number or order['track_id']}"
        )

        send_telegram_sync(
            ADMIN_CHAT_ID,
            admin_text,
        )


# =========================================================
# سرور Callback زیبال
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
                    border-radius: 18px;
                    padding: 30px 20px;
                    box-shadow: 0 4px 20px rgba(0,0,0,.08);
                }}
                h2 {{
                    margin-top: 0;
                }}
                p {{
                    line-height: 2;
                }}
            </style>
        </head>

        <body>
            <div class="box">
                <h2>{html.escape(title)}</h2>
                <p>{html.escape(message)}</p>
                <p>می‌توانید این صفحه را ببندید و به تلگرام برگردید.</p>
                <strong>کتونی 530 👟</strong>
            </div>
        </body>
        </html>
        """

        body = page.encode("utf-8")

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

        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":

            self.send_html(
                "کتونی 530",
                "ربات و درگاه پرداخت فعال است.",
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

        success = params.get("success", [""])[0]

        print(
            "Zibal callback:",
            "trackId=",
            track_id,
            "success=",
            success,
        )

        if not track_id:

            self.send_html(
                "خطا",
                "شناسه پرداخت دریافت نشد.",
            )
            return

        order = get_order_by_track_id(track_id)

        if not order:

            self.send_html(
                "خطا",
                "سفارش مربوط به این پرداخت پیدا نشد.",
            )
            return

        if order["status"] == "paid":

            self.send_html(
                "پرداخت قبلاً تأیید شده است ✅",
                f"سفارش شماره {order['id']} قبلاً ثبت نهایی شده است.",
            )
            return

        if success != "1":

            mark_order_failed(order["id"])

            send_telegram_sync(
                order["telegram_chat_id"],
                "❌ پرداخت انجام نشد یا توسط شما لغو شد.\n\n"
                "سفارش نهایی ثبت نشده است.\n"
                "برای خرید می‌توانید دوباره از ربات اقدام کنید.",
            )

            self.send_html(
                "پرداخت ناموفق بود ❌",
                "سفارش شما نهایی نشده است.",
            )
            return

        try:

            verify_data = verify_zibal(track_id)

            result = int(
                verify_data.get("result", 0)
            )

            # 100 = تأیید موفق
            # 201 = قبلاً تأیید شده
            if result not in (100, 201):

                self.send_html(
                    "پرداخت تأیید نشد ❌",
                    "تأیید نهایی پرداخت از زیبال دریافت نشد.",
                )
                return

            # اگر زیبال مبلغ را در پاسخ برگرداند،
            # حتماً با مبلغ سفارش مقایسه می‌کنیم.
            verified_amount = verify_data.get("amount")

            if verified_amount is not None:

                try:
                    verified_amount = int(
                        verified_amount
                    )

                    if verified_amount != int(
                        order["amount_rial"]
                    ):
                        print(
                            "SECURITY: amount mismatch",
                            verified_amount,
                            order["amount_rial"],
                        )

                        self.send_html(
                            "خطا در مبلغ پرداخت",
                            "مبلغ تراکنش با مبلغ سفارش مطابقت ندارد.",
                        )
                        return

                except Exception:
                    pass

            ref_number = str(
                verify_data.get("refNumber", "")
                or verify_data.get("ref_number", "")
                or track_id
            )

            mark_order_paid(
                order["id"],
                ref_number,
            )

            # دوباره سفارش را می‌گیریم
            order = get_order(order["id"])

            notify_paid_order(
                order,
                ref_number,
            )

            self.send_html(
                "پرداخت موفق بود ✅",
                f"سفارش شماره {order['id']} با موفقیت ثبت شد.",
            )

        except Exception as e:

            print("VERIFY ERROR:", e)

            self.send_html(
                "خطا در بررسی پرداخت",
                "پرداخت فعلاً قابل تأیید نیست. "
                "اگر مبلغ از حساب شما کسر شده، دوباره پرداخت نکنید.",
            )


def start_http_server():
    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        PaymentCallbackHandler,
    )

    print(f"HTTP server running on port {PORT}")

    server.serve_forever()


# =========================================================
# پیام‌های معمولی و مراحل سفارش
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    user_id = update.effective_user.id

    if not await is_member(context.bot, user_id):
        await show_join_message(update)
        return

    # -------------------------
    # مراحل ثبت سفارش
    # -------------------------

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
                "📱 شماره موبایل خود را وارد کنید.\n"
                "مثال:\n"
                "09123456789"
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
                    "❌ شماره موبایل صحیح نیست.\n\n"
                    "لطفاً به شکل 09123456789 ارسال کنید."
                )
                return

            context.user_data["mobile"] = mobile
            context.user_data["step"] = "address"

            await update.message.reply_text(
                "📍 لطفاً آدرس کامل برای ارسال سفارش را بنویسید:"
            )
            return

        if step == "address":

            if len(text) < 5:
                await update.message.reply_text(
                    "لطفاً آدرس کامل‌تری ارسال کنید."
                )
                return

            context.user_data["address"] = text

            code = context.user_data["product_code"]
            size = context.user_data["size"]

            product = PRODUCTS.get(code)

            if not product:
                context.user_data.clear()

                await update.message.reply_text(
                    "❌ محصول پیدا نشد.",
                    reply_markup=main_keyboard(),
                )
                return

            price = get_price_toman(product)

            try:

                order_id = create_order(
                    telegram_user_id=update.effective_user.id,
                    telegram_chat_id=update.effective_chat.id,
                    product_code=code,
                    product_name=product["name"],
                    size=size,
                    amount_toman=price,
                    customer_name=context.user_data["customer_name"],
                    mobile=context.user_data["mobile"],
                    address=context.user_data["address"],
                )

                order = get_order(order_id)

                track_id = create_zibal_payment(order)

                set_track_id(
                    order_id,
                    track_id,
                )

                payment_url = (
                    f"{ZIBAL_START_URL}{track_id}"
                )

                payment_keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "💳 پرداخت آنلاین",
                                url=payment_url,
                            )
                        ]
                    ]
                )

                await update.message.reply_text(
                    "🧾 اطلاعات سفارش\n\n"
                    f"👟 محصول: {code}\n"
                    f"📏 سایز: {size}\n"
                    f"💰 مبلغ: {money(price)} تومان\n"
                    f"👤 نام: {context.user_data['customer_name']}\n"
                    f"📱 موبایل: {context.user_data['mobile']}\n"
                    f"📍 آدرس: {context.user_data['address']}\n\n"
                    "⚠️ سفارش هنوز نهایی نشده است.\n\n"
                    "برای ثبت نهایی سفارش ابتدا پرداخت را انجام دهید 👇",
                    reply_markup=payment_keyboard,
                )

                context.user_data.clear()

            except Exception as e:

                print("CREATE PAYMENT ERROR:", e)

                await update.message.reply_text(
                    "❌ در اتصال به درگاه پرداخت مشکلی پیش آمد.\n\n"
                    "هیچ پرداختی انجام نشده است.\n"
                    "لطفاً کمی بعد دوباره امتحان کنید.",
                    reply_markup=main_keyboard(),
                )

            return

    # -------------------------
    # منوی اصلی
    # -------------------------

    if text == "👟 کفش مردانه ۴۱ تا ۴۵":
        await show_category(update, "men")
        return

    if text == "👟 کفش زنانه ۳۷ تا ۴۰":
        await show_category(update, "women")
        return

    if text == "🔎 جستجو با کد محصول":

        context.user_data.clear()
        context.user_data["searching"] = True

        await update.message.reply_text(
            "🔎 کد محصول را ارسال کنید.\n\n"
            "مثال:\n"
            "K530-05"
        )
        return

    if context.user_data.get("searching"):

        context.user_data["searching"] = False

        await send_product(
            update.message,
            text.upper(),
        )
        return

    if text == "🛒 ثبت سفارش":

        await update.message.reply_text(
            "👟 ابتدا محصول موردنظر را از بخش محصولات "
            "انتخاب کنید و سپس روی «🛒 خرید این محصول» بزنید."
        )
        return

    if text == "📦 پیگیری سفارش":

        await update.message.reply_text(
            "📦 برای پیگیری سفارش، شماره سفارش خود را "
            "برای پشتیبانی ارسال کنید."
        )
        return

    if text == "💬 استعلام قیمت و موجودی":

        await update.message.reply_text(
            "💬 کد کفش و سایز موردنظر را ارسال کنید.\n\n"
            "مثال:\n"
            "K530-05 سایز 42"
        )
        return

    if text == "👨‍💬 پشتیبانی":

        await update.message.reply_text(
            "👨‍💬 برای ارتباط با فروشگاه، پیام خود را "
            "همین‌جا ارسال کنید."
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
            "کانال رسمی کتونی 530 👇",
            reply_markup=keyboard,
        )
        return

    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های منو را انتخاب کنید 👇",
        reply_markup=main_keyboard(),
    )


# =========================================================
# دستورات
# =========================================================

async def products_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "👟 دسته‌بندی موردنظر را انتخاب کنید:",
        reply_markup=main_keyboard(),
    )


async def search_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()
    context.user_data["searching"] = True

    await update.message.reply_text(
        "🔎 کد محصول را ارسال کنید.\n"
        "مثال: K530-05"
    )


async def order_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "👟 ابتدا محصول را انتخاب کنید و روی دکمه خرید بزنید.",
        reply_markup=main_keyboard(),
    )


async def track_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "📦 شماره سفارش خود را برای پشتیبانی ارسال کنید."
    )


async def support_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "👨‍💬 پیام خود را برای پشتیبانی ارسال کنید."
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

    # سرور Callback پرداخت
    http_thread = threading.Thread(
        target=start_http_server,
        daemon=True,
    )

    http_thread.start()

    # ربات تلگرام
    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
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
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    print("Katoni 530 bot started...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()

import os
import time
import requests

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

# =====================================
# تنظیمات کتونی 530
# =====================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

CHANNEL = "@katooni_530"
CHANNEL_LINK = "https://t.me/katooni_530"

SUPPORT_USERNAME = "@katooni_530"

# =====================================
# نرخ دلار
# =====================================

# اگر اینترنت یا منبع نرخ قطع شد، موقتاً از این نرخ استفاده می‌شود.
FALLBACK_USD_TOMAN = 232000

usd_cache = {
    "rate": FALLBACK_USD_TOMAN,
    "time": 0
}

# هر یک ساعت
CACHE_SECONDS = 60 * 60


def get_usd_rate():

    now = time.time()

    # اگر کمتر از یک ساعت از دریافت قبلی گذشته
    if now - usd_cache["time"] < CACHE_SECONDS:
        return usd_cache["rate"]

    try:
        # منبع رایگان نرخ ارز
        url = "https://api.navasan.tech/latest/"

        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()

            # دلار بازار آزاد
            if "usd_sell" in data:
                value = data["usd_sell"]

                if isinstance(value, dict):
                    value = value.get("value")

                rate = int(
                    str(value)
                    .replace(",", "")
                    .replace("٬", "")
                )

                # بعضی منابع ریال می‌دهند
                if rate > 1000000:
                    rate = rate // 10

                if rate > 50000:
                    usd_cache["rate"] = rate
                    usd_cache["time"] = now
                    return rate

    except Exception as e:
        print("Dollar rate error:", e)

    return usd_cache["rate"]


# =====================================
# محصولات
# =====================================

PRODUCTS = {

    "K530-05": {
        "name": "کتونی مردانه",
        "usd": 55,
        "sizes": ["41", "42", "43", "44", "45"],
    },

    "K530-06": {
        "name": "کتونی زنانه",
        "usd": 55,
        "sizes": ["37", "38", "39", "40"],
    },

}


# =====================================
# منوی اصلی
# =====================================

def main_menu():

    keyboard = [

        [
            "👟 کفش مردانه ۴۱ تا ۴۵",
            "👟 کفش زنانه ۳۷ تا ۴۰"
        ],

        [
            "🔎 جستجو با کد محصول",
            "🛒 ثبت سفارش"
        ],

        [
            "📦 پیگیری سفارش",
            "💬 استعلام قیمت و موجودی"
        ],

        [
            "👨‍💬 پشتیبانی",
            "📣 کانال تلگرام"
        ]

    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =====================================
# بررسی عضویت کانال
# =====================================

async def is_member(update, context):

    try:

        user_id = update.effective_user.id

        member = await context.bot.get_chat_member(
            CHANNEL,
            user_id
        )

        return member.status in [
            "member",
            "administrator",
            "creator"
        ]

    except Exception as e:

        print("Membership error:", e)

        # برای اینکه ربات در صورت خطای تلگرام قفل نشود
        return True


async def membership_message(update):

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📣 عضویت در کانال",
                url=CHANNEL_LINK
            )
        ],

        [
            InlineKeyboardButton(
                "✅ عضو شدم",
                callback_data="check_join"
            )
        ]

    ])

    await update.message.reply_text(

        "سلام 👋\n\n"
        "برای استفاده از ربات کتونی 530 "
        "ابتدا عضو کانال شوید 👇\n\n"
        "بعد از عضویت روی «✅ عضو شدم» بزنید.",

        reply_markup=keyboard
    )


# =====================================
# شروع
# =====================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_member(update, context):

        await membership_message(update)

        return

    await update.message.reply_text(

        "سلام 👋\n\n"
        "به فروشگاه کتونی 530 خوش آمدید 👟\n\n"
        "دسته‌بندی موردنظر را انتخاب کنید:",

        reply_markup=main_menu()
    )


# =====================================
# بررسی دکمه عضو شدم
# =====================================

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    try:

        member = await context.bot.get_chat_member(
            CHANNEL,
            query.from_user.id
        )

        if member.status in [
            "member",
            "administrator",
            "creator"
        ]:

            await query.message.reply_text(

                "✅ عضویت شما تأیید شد.\n\n"
                "به فروشگاه کتونی 530 خوش آمدید 👟",

                reply_markup=main_menu()
            )

        else:

            await query.answer(
                "❌ هنوز عضو کانال نیستید.",
                show_alert=True
            )

    except Exception as e:

        print(e)

        await query.message.reply_text(
            "لطفاً دوباره امتحان کنید."
        )


# =====================================
# نمایش محصول
# =====================================

async def show_product(update, code):

    product = PRODUCTS.get(code)

    if not product:

        await update.message.reply_text(
            "❌ محصولی با این کد پیدا نشد."
        )

        return

    rate = get_usd_rate()

    toman_price = product["usd"] * rate

    sizes = " - ".join(product["sizes"])

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🛒 خرید این محصول",
                callback_data=f"buy_{code}"
            )
        ]

    ])

    text = (

        f"👟 {product['name']} مدل {code}\n\n"

        f"🏷️ کد محصول: {code}\n\n"

        f"💵 قیمت پایه: {product['usd']} دلار\n\n"

        f"💵 نرخ دلار: {rate:,} تومان\n\n"

        f"💰 قیمت امروز: {toman_price:,} تومان\n\n"

        f"📏 سایزهای موجود: {sizes}\n\n"

        "برای خرید روی دکمه زیر بزنید 👇"

    )

    await update.message.reply_text(
        text,
        reply_markup=keyboard
    )


# =====================================
# دکمه خرید محصول
# =====================================

async def buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    code = query.data.replace("buy_", "")

    product = PRODUCTS.get(code)

    if not product:
        return

    buttons = []

    for size in product["sizes"]:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"سایز {size}",
                    callback_data=f"size_{code}_{size}"
                )
            ]
        )

    await query.message.reply_text(

        f"👟 {product['name']}\n"
        f"🏷️ کد: {code}\n\n"
        "📏 سایز موردنظر را انتخاب کنید:",

        reply_markup=InlineKeyboardMarkup(buttons)
    )


# =====================================
# انتخاب سایز
# =====================================

async def select_size(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    data = query.data.split("_")

    code = data[1]

    size = data[2]

    context.user_data["product"] = code

    context.user_data["size"] = size

    context.user_data["ordering"] = True

    await query.message.reply_text(

        f"✅ محصول: {code}\n"
        f"📏 سایز: {size}\n\n"

        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )

    context.user_data["order_step"] = "name"


# =====================================
# پیام‌ها
# =====================================

async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text.strip()

    # -------------------------------
    # مراحل سفارش
    # -------------------------------

    if context.user_data.get("ordering"):

        step = context.user_data.get("order_step")

        if step == "name":

            context.user_data["name"] = text

            context.user_data["order_step"] = "phone"

            await update.message.reply_text(
                "📱 شماره موبایل خود را ارسال کنید:"
            )

            return

        if step == "phone":

            context.user_data["phone"] = text

            context.user_data["order_step"] = "address"

            await update.message.reply_text(
                "📍 آدرس کامل برای ارسال را بنویسید:"
            )

            return

        if step == "address":

            context.user_data["address"] = text

            code = context.user_data["product"]

            size = context.user_data["size"]

            product = PRODUCTS[code]

            rate = get_usd_rate()

            price = product["usd"] * rate

            name = context.user_data["name"]

            phone = context.user_data["phone"]

            address = context.user_data["address"]

            await update.message.reply_text(

                "✅ سفارش شما ثبت شد.\n\n"

                f"👟 محصول: {code}\n"

                f"📏 سایز: {size}\n"

                f"💰 مبلغ: {price:,} تومان\n\n"

                f"👤 نام: {name}\n"

                f"📱 موبایل: {phone}\n"

                f"📍 آدرس: {address}\n\n"

                "📦 اطلاعات سفارش شما ثبت شد.",

                reply_markup=main_menu()
            )

            context.user_data.clear()

            return


    # -------------------------------
    # مردانه
    # -------------------------------

    if text == "👟 کفش مردانه ۴۱ تا ۴۵":

        await show_product(
            update,
            "K530-05"
        )

        return


    # -------------------------------
    # زنانه
    # -------------------------------

    if text == "👟 کفش زنانه ۳۷ تا ۴۰":

        await show_product(
            update,
            "K530-06"
        )

        return


    # -------------------------------
    # جستجو
    # -------------------------------

    if text == "🔎 جستجو با کد محصول":

        context.user_data["searching"] = True

        await update.message.reply_text(

            "🔎 کد محصول را وارد کنید.\n\n"
            "مثال:\n"
            "K530-06"
        )

        return


    if context.user_data.get("searching"):

        context.user_data["searching"] = False

        code = text.upper()

        await show_product(
            update,
            code
        )

        return


    # -------------------------------
    # ثبت سفارش
    # -------------------------------

    if text == "🛒 ثبت سفارش":

        await update.message.reply_text(

            "🛒 برای ثبت سفارش ابتدا محصول موردنظر "
            "را انتخاب کنید و سپس روی "
            "«خرید این محصول» بزنید."
        )

        return


    # -------------------------------
    # پیگیری
    # -------------------------------

    if text == "📦 پیگیری سفارش":

        await update.message.reply_text(

            "📦 برای پیگیری سفارش، "
            "شماره سفارش یا شماره موبایل خود را "
            "برای پشتیبانی ارسال کنید."
        )

        return


    # -------------------------------
    # استعلام
    # -------------------------------

    if text == "💬 استعلام قیمت و موجودی":

        rate = get_usd_rate()

        await update.message.reply_text(

            "💬 برای استعلام قیمت و موجودی، "
            "کد کفش را ارسال کنید.\n\n"

            f"💵 نرخ فعلی دلار ربات: "
            f"{rate:,} تومان"
        )

        return


    # -------------------------------
    # پشتیبانی
    # -------------------------------

    if text == "👨‍💬 پشتیبانی":

        await update.message.reply_text(

            "👨‍💬 پشتیبانی کتونی 530\n\n"

            f"تلگرام:\n{SUPPORT_USERNAME}"
        )

        return


    # -------------------------------
    # کانال
    # -------------------------------

    if text == "📣 کانال تلگرام":

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "📣 ورود به کانال کتونی 530",
                    url=CHANNEL_LINK
                )
            ]

        ])

        await update.message.reply_text(

            "📣 کانال رسمی کتونی 530 👇",

            reply_markup=keyboard
        )

        return


    # -------------------------------
    # جستجوی مستقیم کد
    # -------------------------------

    if text.upper() in PRODUCTS:

        await show_product(
            update,
            text.upper()
        )

        return


    await update.message.reply_text(

        "لطفاً یکی از گزینه‌های منو را انتخاب کنید 👇",

        reply_markup=main_menu()
    )


# =====================================
# دستورات
# =====================================

async def products_command(update, context):

    await update.message.reply_text(

        "👟 دسته‌بندی محصولات را انتخاب کنید:",

        reply_markup=main_menu()
    )


async def search_command(update, context):

    context.user_data["searching"] = True

    await update.message.reply_text(
        "🔎 کد محصول را وارد کنید:"
    )


async def order_command(update, context):

    await update.message.reply_text(

        "🛒 ابتدا محصول موردنظر را انتخاب کنید.",

        reply_markup=main_menu()
    )


async def track_command(update, context):

    await update.message.reply_text(
        "📦 شماره سفارش یا شماره موبایل خود را ارسال کنید."
    )


async def support_command(update, context):

    await update.message.reply_text(

        f"👨‍💬 پشتیبانی کتونی 530\n\n"
        f"{SUPPORT_USERNAME}"
    )


# =====================================
# اجرای ربات
# =====================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN تنظیم نشده است."
        )

    app = Application.builder().token(TOKEN).build()

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
            check_join,
            pattern="^check_join$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            buy_product,
            pattern="^buy_"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            select_size,
            pattern="^size_"
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            messages
        )
    )

    print("Katoni 530 bot started...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

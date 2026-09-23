import os

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
    ConversationHandler,
    filters,
)

# =========================
# تنظیمات کتونی 530
# =========================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

CHANNEL = "@katooni_530"
CHANNEL_LINK = "https://t.me/katooni_530"

# فعلاً نرخ دلار دستی است.
# بعداً نرخ روز خودکار را وصل می‌کنیم.
USD_TO_TOMAN = 110000


# =========================
# محصولات
# بعداً مدل‌های واقعی خودتان را اینجا اضافه می‌کنیم
# =========================

PRODUCTS = {
    "K530-05": {
        "name": "کتونی مردانه مدل K530-05",
        "category": "men",
        "price_usd": 65,
        "sizes": ["41", "42", "43", "44", "45"],
    },
    "K530-06": {
        "name": "کتونی زنانه مدل K530-06",
        "category": "women",
        "price_usd": 55,
        "sizes": ["37", "38", "39", "40"],
    },
}


# =========================
# مراحل ثبت سفارش
# =========================

SELECT_SIZE, GET_NAME, GET_PHONE, GET_ADDRESS = range(4)


# =========================
# منوی اصلی
# =========================

def main_menu():
    keyboard = [
        ["👟 کفش مردانه ۴۱ تا ۴۵", "👟 کفش زنانه ۳۷ تا ۴۰"],
        ["🔎 جستجو با کد محصول", "🛒 ثبت سفارش"],
        ["📦 پیگیری سفارش", "💬 استعلام قیمت و موجودی"],
        ["👨‍💬 پشتیبانی", "📣 کانال تلگرام"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
    )


# =========================
# عضویت کانال
# =========================

async def is_member(context, user_id):
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL,
            user_id=user_id,
        )

        return member.status in [
            "member",
            "administrator",
            "creator",
        ]

    except Exception as e:
        print("Membership check error:", e)
        return False


def join_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📣 عضویت در کانال کتونی 530",
                    url=CHANNEL_LINK,
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ عضو شدم",
                    callback_data="check_join",
                )
            ],
        ]
    )


async def ask_to_join(update):
    text = (
        "سلام 👋\n\n"
        "برای استفاده از ربات کتونی 530 ابتدا عضو کانال شوید 👇\n\n"
        "بعد از عضویت روی «✅ عضو شدم» بزنید."
    )

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=join_keyboard(),
        )


async def require_member(update, context):
    user_id = update.effective_user.id

    if await is_member(context, user_id):
        return True

    await ask_to_join(update)
    return False


async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if await is_member(context, user_id):
        await query.message.reply_text(
            "✅ عضویت شما تأیید شد.\n\n"
            "به فروشگاه کتونی 530 خوش آمدید 👟",
            reply_markup=main_menu(),
        )
    else:
        await query.answer(
            "هنوز عضو کانال نشده‌اید.",
            show_alert=True,
        )


# =========================
# شروع
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await require_member(update, context):
        return

    await update.message.reply_text(
        "سلام 👋\n\n"
        "به فروشگاه کتونی 530 خوش آمدید 👟\n\n"
        "دسته‌بندی موردنظر را انتخاب کنید:",
        reply_markup=main_menu(),
    )


# =========================
# قیمت
# =========================

def toman_price(price_usd):
    return price_usd * USD_TO_TOMAN


def format_price(price):
    return f"{price:,}"


# =========================
# نمایش محصول
# =========================

async def show_product(message, code):

    product = PRODUCTS.get(code.upper())

    if not product:
        await message.reply_text(
            "❌ محصولی با این کد پیدا نشد."
        )
        return

    price_toman = toman_price(product["price_usd"])

    sizes = " - ".join(product["sizes"])

    text = (
        f"👟 {product['name']}\n\n"
        f"🔖 کد محصول: {code}\n"
        f"💵 قیمت پایه: {product['price_usd']} دلار\n"
        f"💰 قیمت امروز: {format_price(price_toman)} تومان\n"
        f"📏 سایزهای موجود: {sizes}\n\n"
        "برای خرید روی دکمه زیر بزنید 👇"
    )

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
        text,
        reply_markup=keyboard,
    )


# =========================
# محصولات مردانه
# =========================

async def men_products(update, context):

    if not await require_member(update, context):
        return

    found = False

    for code, product in PRODUCTS.items():

        if product["category"] == "men":
            found = True
            await show_product(update.message, code)

    if not found:
        await update.message.reply_text(
            "فعلاً محصول مردانه ثبت نشده است."
        )


# =========================
# محصولات زنانه
# =========================

async def women_products(update, context):

    if not await require_member(update, context):
        return

    found = False

    for code, product in PRODUCTS.items():

        if product["category"] == "women":
            found = True
            await show_product(update.message, code)

    if not found:
        await update.message.reply_text(
            "فعلاً محصول زنانه ثبت نشده است."
        )


# =========================
# جستجوی محصول
# =========================

async def search_product(update, context):

    if not await require_member(update, context):
        return

    context.user_data["waiting_for_code"] = True

    await update.message.reply_text(
        "🔎 کد محصول را ارسال کنید.\n\n"
        "مثال:\n"
        "K530-05"
    )


# =========================
# شروع خرید
# =========================

async def buy_product(update, context):

    query = update.callback_query
    await query.answer()

    code = query.data.split(":")[1]

    product = PRODUCTS.get(code)

    if not product:
        await query.message.reply_text(
            "❌ محصول پیدا نشد."
        )
        return ConversationHandler.END

    context.user_data["order_product"] = code

    buttons = []

    for size in product["sizes"]:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"سایز {size}",
                    callback_data=f"size:{size}",
                )
            ]
        )

    await query.message.reply_text(
        "📏 سایز موردنظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

    return SELECT_SIZE


# =========================
# انتخاب سایز
# =========================

async def select_size(update, context):

    query = update.callback_query
    await query.answer()

    size = query.data.split(":")[1]

    context.user_data["order_size"] = size

    await query.message.reply_text(
        f"✅ سایز {size} انتخاب شد.\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )

    return GET_NAME


# =========================
# دریافت نام
# =========================

async def get_name(update, context):

    context.user_data["customer_name"] = update.message.text

    await update.message.reply_text(
        "📱 شماره موبایل خود را ارسال کنید:"
    )

    return GET_PHONE


# =========================
# دریافت شماره
# =========================

async def get_phone(update, context):

    context.user_data["customer_phone"] = update.message.text

    await update.message.reply_text(
        "📍 آدرس کامل برای ارسال سفارش را وارد کنید:"
    )

    return GET_ADDRESS


# =========================
# دریافت آدرس و ثبت سفارش
# =========================

async def get_address(update, context):

    context.user_data["customer_address"] = update.message.text

    code = context.user_data.get("order_product")
    size = context.user_data.get("order_size")
    name = context.user_data.get("customer_name")
    phone = context.user_data.get("customer_phone")
    address = context.user_data.get("customer_address")

    product = PRODUCTS.get(code)

    if not product:
        await update.message.reply_text(
            "❌ خطا در ثبت سفارش."
        )
        return ConversationHandler.END

    price = toman_price(product["price_usd"])

    order_text = (
        "✅ سفارش شما ثبت شد\n\n"
        f"👟 محصول: {product['name']}\n"
        f"🔖 کد: {code}\n"
        f"📏 سایز: {size}\n"
        f"💰 مبلغ: {format_price(price)} تومان\n\n"
        f"👤 نام: {name}\n"
        f"📱 موبایل: {phone}\n"
        f"📍 آدرس: {address}\n\n"
        "فروشگاه کتونی 530 👟"
    )

    await update.message.reply_text(
        order_text,
        reply_markup=main_menu(),
    )

    return ConversationHandler.END


# =========================
# لغو سفارش
# =========================

async def cancel_order(update, context):

    await update.message.reply_text(
        "❌ ثبت سفارش لغو شد.",
        reply_markup=main_menu(),
    )

    return ConversationHandler.END


# =========================
# کانال
# =========================

async def channel(update, context):

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
        "📣 کانال رسمی فروشگاه کتونی 530",
        reply_markup=keyboard,
    )


# =========================
# پشتیبانی
# =========================

async def support(update, context):

    await update.message.reply_text(
        "👨‍💬 پشتیبانی کتونی 530\n\n"
        "پیام خود را ارسال کنید تا فروشگاه بررسی کند."
    )


# =========================
# پیگیری سفارش
# =========================

async def track_order(update, context):

    await update.message.reply_text(
        "📦 برای پیگیری سفارش، کد یا شماره سفارش خود را ارسال کنید."
    )


# =========================
# استعلام
# =========================

async def inquiry(update, context):

    await update.message.reply_text(
        "💬 برای استعلام قیمت و موجودی، کد کفش را ارسال کنید.\n\n"
        "مثال: K530-05"
    )

    context.user_data["waiting_for_code"] = True


# =========================
# ثبت سفارش از منو
# =========================

async def order_menu(update, context):

    await update.message.reply_text(
        "🛒 ابتدا محصول موردنظر را از بخش مردانه یا زنانه انتخاب کنید، "
        "سپس روی «خرید این محصول» بزنید."
    )


# =========================
# پیام‌های متنی
# =========================

async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await require_member(update, context):
        return

    text = update.message.text.strip()

    if text == "👟 کفش مردانه ۴۱ تا ۴۵":
        await men_products(update, context)
        return

    if text == "👟 کفش زنانه ۳۷ تا ۴۰":
        await women_products(update, context)
        return

    if text == "🔎 جستجو با کد محصول":
        await search_product(update, context)
        return

    if text == "🛒 ثبت سفارش":
        await order_menu(update, context)
        return

    if text == "📦 پیگیری سفارش":
        await track_order(update, context)
        return

    if text == "💬 استعلام قیمت و موجودی":
        await inquiry(update, context)
        return

    if text == "👨‍💬 پشتیبانی":
        await support(update, context)
        return

    if text == "📣 کانال تلگرام":
        await channel(update, context)
        return

    if context.user_data.get("waiting_for_code"):

        context.user_data["waiting_for_code"] = False

        await show_product(
            update.message,
            text.upper(),
        )
        return

    # اگر مشتری مستقیماً کد محصول فرستاد
    if text.upper() in PRODUCTS:
        await show_product(
            update.message,
            text.upper(),
        )
        return

    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های منو را انتخاب کنید 👇",
        reply_markup=main_menu(),
    )


# =========================
# MAIN
# =========================

def main():

    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN تنظیم نشده است."
        )

    app = Application.builder().token(TOKEN).build()

    order_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                buy_product,
                pattern=r"^buy:",
            )
        ],
        states={
            SELECT_SIZE: [
                CallbackQueryHandler(
                    select_size,
                    pattern=r"^size:",
                )
            ],
            GET_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_name,
                )
            ],
            GET_PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_phone,
                )
            ],
            GET_ADDRESS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_address,
                )
            ],
        },
        fallbacks=[
            CommandHandler(
                "cancel",
                cancel_order,
            )
        ],
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            check_join,
            pattern=r"^check_join$",
        )
    )

    # این باید قبل از MessageHandler اصلی باشد
    app.add_handler(order_conversation)

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            messages,
        )
    )

    print("Katoni 530 bot started...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()

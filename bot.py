import os
import random
from datetime import datetime

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

# ==========================================
# تنظیمات اصلی کتونی 530
# ==========================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

CHANNEL = "@katooni_530"
CHANNEL_LINK = "https://t.me/katooni_530"

SUPPORT_USERNAME = "@katoni_530"

# Telegram ID صاحب فروشگاه
ADMIN_CHAT_ID = 7051086090

# فعلاً نرخ دلار دستی
USD_TO_TOMAN = 232000


# ==========================================
# محصولات
# ==========================================

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


# ==========================================
# منوی اصلی
# ==========================================

def main_menu():
    keyboard = [
        [
            "👟 کفش مردانه ۴۱ تا ۴۵",
            "👟 کفش زنانه ۳۷ تا ۴۰",
        ],
        [
            "🔎 جستجو با کد محصول",
            "🛒 ثبت سفارش",
        ],
        [
            "📦 پیگیری سفارش",
            "💬 استعلام قیمت و موجودی",
        ],
        [
            "👨‍💬 پشتیبانی",
            "📣 کانال تلگرام",
        ],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# ==========================================
# بررسی عضویت کانال
# ==========================================

async def is_member(user_id, context):
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL,
            user_id=user_id
        )

        return member.status in [
            "member",
            "administrator",
            "creator"
        ]

    except Exception as e:
        print("Membership check error:", e)

        # اگر تلگرام موقتاً خطا داد، مشتری قفل نشود
        return True


async def send_join_message(message):
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

    await message.reply_text(
        "سلام 👋\n\n"
        "برای استفاده از ربات کتونی 530 "
        "ابتدا عضو کانال شوید 👇\n\n"
        "بعد از عضویت روی «✅ عضو شدم» بزنید.",
        reply_markup=keyboard
    )


# ==========================================
# /start
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if not await is_member(user_id, context):
        await send_join_message(update.message)
        return

    await update.message.reply_text(
        "سلام 👋\n\n"
        "به فروشگاه کتونی 530 خوش آمدید 👟\n\n"
        "دسته‌بندی موردنظر را انتخاب کنید:",
        reply_markup=main_menu()
    )


# ==========================================
# دکمه عضو شدم
# ==========================================

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    if await is_member(query.from_user.id, context):

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


# ==========================================
# قیمت محصول
# ==========================================

def product_price(code):

    product = PRODUCTS.get(code)

    if not product:
        return 0

    return product["usd"] * USD_TO_TOMAN


# ==========================================
# نمایش محصول
# ==========================================

async def show_product(message, code):

    product = PRODUCTS.get(code)

    if not product:

        await message.reply_text(
            "❌ محصولی با این کد پیدا نشد."
        )

        return

    price = product_price(code)

    sizes = " - ".join(product["sizes"])

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛒 خرید این محصول",
                callback_data=f"buy|{code}"
            )
        ]
    ])

    await message.reply_text(
        f"👟 {product['name']} مدل {code}\n\n"
        f"🏷 کد محصول: {code}\n"
        f"💵 قیمت پایه: {product['usd']} دلار\n"
        f"💱 نرخ دلار: {USD_TO_TOMAN:,} تومان\n"
        f"💰 قیمت امروز: {price:,} تومان\n"
        f"📏 سایزهای موجود: {sizes}\n\n"
        "برای خرید روی دکمه زیر بزنید 👇",
        reply_markup=keyboard
    )


# ==========================================
# خرید محصول
# ==========================================

async def buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    try:
        code = query.data.split("|")[1]
    except Exception:
        return

    product = PRODUCTS.get(code)

    if not product:

        await query.message.reply_text(
            "❌ محصول پیدا نشد."
        )

        return

    buttons = []

    for size in product["sizes"]:

        buttons.append([
            InlineKeyboardButton(
                f"سایز {size}",
                callback_data=f"size|{code}|{size}"
            )
        ])

    await query.message.reply_text(
        f"👟 {product['name']}\n"
        f"🏷 کد محصول: {code}\n\n"
        "📏 سایز موردنظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ==========================================
# انتخاب سایز
# ==========================================

async def select_size(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    await query.answer()

    try:
        _, code, size = query.data.split("|")
    except Exception:
        return

    context.user_data.clear()

    context.user_data["ordering"] = True
    context.user_data["order_step"] = "name"
    context.user_data["product"] = code
    context.user_data["size"] = size

    await query.message.reply_text(
        f"✅ کد محصول: {code}\n"
        f"📏 سایز انتخابی: {size}\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )


# ==========================================
# شماره سفارش
# ==========================================

def create_order_id():

    date_part = datetime.now().strftime("%m%d%H%M")

    random_part = random.randint(
        100,
        999
    )

    return f"K530-{date_part}-{random_part}"


# ==========================================
# ارسال سفارش برای صاحب فروشگاه
# ==========================================

async def notify_admin(
    context,
    customer,
    order_id,
    code,
    size,
    name,
    phone,
    address,
    price
):

    if customer.username:

        customer_username = (
            "@" + customer.username
        )

    else:

        customer_username = "ندارد"

    admin_text = (
        "🔔🔔 سفارش جدید کتونی 530 🔔🔔\n\n"
        f"🧾 شماره سفارش:\n{order_id}\n\n"
        f"👟 کد محصول: {code}\n"
        f"📏 سایز: {size}\n"
        f"💰 مبلغ: {price:,} تومان\n\n"
        f"👤 نام مشتری: {name}\n"
        f"📱 شماره موبایل: {phone}\n\n"
        f"📍 آدرس:\n{address}\n\n"
        f"💬 آیدی تلگرام: {customer_username}\n"
        f"🆔 Telegram ID: {customer.id}"
    )

    try:

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_text
        )

        print(
            "ADMIN NOTIFICATION SENT:",
            order_id
        )

        return True

    except Exception as e:

        print(
            "ADMIN NOTIFICATION FAILED:",
            repr(e)
        )

        return False


# ==========================================
# پیام‌های مشتری
# ==========================================

async def messages(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    # ======================================
    # مراحل ثبت سفارش
    # ======================================

    if context.user_data.get("ordering"):

        step = context.user_data.get(
            "order_step"
        )

        # نام
        if step == "name":

            context.user_data["name"] = text

            context.user_data[
                "order_step"
            ] = "phone"

            await update.message.reply_text(
                "📱 شماره موبایل خود را ارسال کنید:"
            )

            return

        # موبایل
        if step == "phone":

            context.user_data["phone"] = text

            context.user_data[
                "order_step"
            ] = "address"

            await update.message.reply_text(
                "📍 آدرس کامل برای ارسال را بنویسید:"
            )

            return

        # آدرس و ثبت نهایی
        if step == "address":

            context.user_data["address"] = text

            code = context.user_data.get(
                "product"
            )

            size = context.user_data.get(
                "size"
            )

            name = context.user_data.get(
                "name"
            )

            phone = context.user_data.get(
                "phone"
            )

            address = context.user_data.get(
                "address"
            )

            product = PRODUCTS.get(code)

            if not product:

                context.user_data.clear()

                await update.message.reply_text(
                    "❌ محصول پیدا نشد.",
                    reply_markup=main_menu()
                )

                return

            price = product_price(code)

            order_id = create_order_id()

            # =================================
            # مهم: ارسال سفارش برای خودت
            # =================================

            admin_sent = await notify_admin(
                context=context,
                customer=update.effective_user,
                order_id=order_id,
                code=code,
                size=size,
                name=name,
                phone=phone,
                address=address,
                price=price
            )

            # =================================
            # پاسخ مشتری
            # =================================

            await update.message.reply_text(
                "✅ سفارش شما با موفقیت ثبت شد.\n\n"
                f"🧾 شماره سفارش:\n{order_id}\n\n"
                f"👟 کد محصول: {code}\n"
                f"📏 سایز: {size}\n"
                f"💰 مبلغ: {price:,} تومان\n\n"
                f"👤 نام: {name}\n"
                f"📱 موبایل: {phone}\n"
                f"📍 آدرس: {address}\n\n"
                "🔔 سفارش شما برای فروشگاه ارسال شد.\n"
                "شماره سفارش را برای پیگیری نگه دارید.",
                reply_markup=main_menu()
            )

            if admin_sent:

                print(
                    "ORDER COMPLETED AND "
                    "ADMIN RECEIVED:",
                    order_id
                )

            else:

                print(
                    "ORDER COMPLETED BUT "
                    "ADMIN MESSAGE FAILED:",
                    order_id
                )

            context.user_data.clear()

            return


    # ======================================
    # منتظر کد محصول
    # ======================================

    if context.user_data.get("searching"):

        context.user_data[
            "searching"
        ] = False

        code = (
            text.upper()
            .replace(" ", "")
        )

        await show_product(
            update.message,
            code
        )

        return


    # ======================================
    # کفش مردانه
    # ======================================

    if text == "👟 کفش مردانه ۴۱ تا ۴۵":

        await show_product(
            update.message,
            "K530-05"
        )

        return


    # ======================================
    # کفش زنانه
    # ======================================

    if text == "👟 کفش زنانه ۳۷ تا ۴۰":

        await show_product(
            update.message,
            "K530-06"
        )

        return


    # ======================================
    # جستجو
    # ======================================

    if text == "🔎 جستجو با کد محصول":

        context.user_data[
            "searching"
        ] = True

        await update.message.reply_text(
            "🔎 کد محصول را ارسال کنید.\n\n"
            "مثال:\n"
            "K530-06"
        )

        return


    # ======================================
    # ثبت سفارش
    # ======================================

    if text == "🛒 ثبت سفارش":

        await update.message.reply_text(
            "🛒 ابتدا محصول موردنظر را انتخاب کنید.\n\n"
            "بعد روی «خرید این محصول» بزنید."
        )

        return


    # ======================================
    # پیگیری سفارش
    # ======================================

    if text == "📦 پیگیری سفارش":

        await update.message.reply_text(
            "📦 برای پیگیری سفارش، "
            "شماره سفارش خود را برای پشتیبانی بفرستید.\n\n"
            f"👨‍💬 {SUPPORT_USERNAME}"
        )

        return


    # ======================================
    # استعلام
    # ======================================

    if text == "💬 استعلام قیمت و موجودی":

        context.user_data[
            "searching"
        ] = True

        await update.message.reply_text(
            "💬 کد کفش را ارسال کنید.\n\n"
            "مثال:\n"
            "K530-06"
        )

        return


    # ======================================
    # پشتیبانی
    # ======================================

    if text == "👨‍💬 پشتیبانی":

        await update.message.reply_text(
            "👨‍💬 پشتیبانی کتونی 530\n\n"
            f"{SUPPORT_USERNAME}"
        )

        return


    # ======================================
    # کانال تلگرام
    # ======================================

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


    # ======================================
    # اگر مشتری مستقیم کد فرستاد
    # ======================================

    direct_code = (
        text.upper()
        .replace(" ", "")
    )

    if direct_code in PRODUCTS:

        await show_product(
            update.message,
            direct_code
        )

        return


    # ======================================
    # پیام نامشخص
    # ======================================

    await update.message.reply_text(
        "متوجه نشدم 😊\n\n"
        "از گزینه‌های منو انتخاب کنید "
        "یا کد محصول را ارسال کنید 👇",
        reply_markup=main_menu()
    )


# ==========================================
# Commands
# ==========================================

async def products_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "👟 دسته‌بندی موردنظر را انتخاب کنید:",
        reply_markup=main_menu()
    )


async def search_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data[
        "searching"
    ] = True

    await update.message.reply_text(
        "🔎 کد محصول را ارسال کنید:"
    )


async def order_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🛒 ابتدا محصول موردنظر را انتخاب کنید.",
        reply_markup=main_menu()
    )


async def track_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "📦 شماره سفارش را برای پشتیبانی ارسال کنید.\n\n"
        f"{SUPPORT_USERNAME}"
    )


async def support_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "👨‍💬 پشتیبانی کتونی 530\n\n"
        f"{SUPPORT_USERNAME}"
    )


# ==========================================
# اجرای ربات
# ==========================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN "
            "در Railway تنظیم نشده است."
        )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # دستورات
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

    # عضویت کانال
    app.add_handler(
        CallbackQueryHandler(
            check_join,
            pattern=r"^check_join$"
        )
    )

    # خرید
    app.add_handler(
        CallbackQueryHandler(
            buy_product,
            pattern=r"^buy\|"
        )
    )

    # سایز
    app.add_handler(
        CallbackQueryHandler(
            select_size,
            pattern=r"^size\|"
        )
    )

    # پیام‌ها
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            messages
        )
    )

    print(
        "Katoni 530 bot started..."
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

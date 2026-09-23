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

# =====================================
# تنظیمات کتونی 530
# =====================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

CHANNEL = "@katooni_530"
CHANNEL_LINK = "https://t.me/katooni_530"

SUPPORT_USERNAME = "@katoni_530"

# سفارش‌های جدید به این اکانت ارسال می‌شوند
ADMIN_CHAT_ID = 7051086090

# فعلاً نرخ دستی - بعداً خودکار می‌کنیم
USD_TO_TOMAN = 227800


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


# =====================================
# بررسی عضویت کانال
# =====================================

async def check_membership(user_id, context):
    try:
        member = await context.bot.get_chat_member(
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

        # در صورت خطای موقت تلگرام، ربات قفل نشود
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
        ],
    ])

    await message.reply_text(
        "سلام 👋\n\n"
        "برای استفاده از ربات کتونی 530 "
        "ابتدا عضو کانال شوید 👇\n\n"
        "بعد از عضویت روی «✅ عضو شدم» بزنید.",
        reply_markup=keyboard
    )


# =====================================
# شروع ربات
# =====================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not await check_membership(user_id, context):
        await send_join_message(update.message)
        return

    await update.message.reply_text(
        "سلام 👋\n\n"
        "به فروشگاه کتونی 530 خوش آمدید 👟\n\n"
        "دسته‌بندی موردنظر را انتخاب کنید:",
        reply_markup=main_menu()
    )


# =====================================
# دکمه عضو شدم
# =====================================

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if await check_membership(query.from_user.id, context):
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


# =====================================
# نمایش محصول
# =====================================

async def show_product(message, code):
    product = PRODUCTS.get(code)

    if not product:
        await message.reply_text(
            "❌ محصولی با این کد پیدا نشد."
        )
        return

    price = product["usd"] * USD_TO_TOMAN
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


# =====================================
# خرید محصول
# =====================================

async def buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    code = query.data.split("|")[1]
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


# =====================================
# انتخاب سایز
# =====================================

async def select_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, code, size = query.data.split("|")

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


# =====================================
# ساخت شماره سفارش
# =====================================

def create_order_id():
    date_part = datetime.now().strftime("%m%d")
    random_part = random.randint(1000, 9999)

    return f"K530-{date_part}-{random_part}"


# =====================================
# ارسال سفارش برای مدیر
# =====================================

async def send_order_to_admin(
    context,
    order_id,
    code,
    size,
    price,
    name,
    phone,
    address,
    customer
):
    username = (
        f"@{customer.username}"
        if customer.username
        else "ندارد"
    )

    text = (
        "🔔 سفارش جدید کتونی 530\n\n"
        f"🧾 شماره سفارش: {order_id}\n"
        f"👟 کد محصول: {code}\n"
        f"📏 سایز: {size}\n"
        f"💰 مبلغ: {price:,} تومان\n\n"
        f"👤 نام مشتری: {name}\n"
        f"📱 موبایل: {phone}\n"
        f"📍 آدرس: {address}\n\n"
        f"💬 تلگرام مشتری: {username}\n"
        f"🆔 Telegram ID: {customer.id}"
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=text
        )

    except Exception as e:
        print("Admin notification error:", e)


# =====================================
# پیام‌های مشتری
# =====================================

async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # ---------------------------------
    # مراحل ثبت سفارش
    # ---------------------------------

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
            name = context.user_data["name"]
            phone = context.user_data["phone"]
            address = context.user_data["address"]

            product = PRODUCTS.get(code)

            if not product:
                context.user_data.clear()

                await update.message.reply_text(
                    "❌ محصول پیدا نشد.",
                    reply_markup=main_menu()
                )
                return

            price = product["usd"] * USD_TO_TOMAN
            order_id = create_order_id()

            # اول سفارش برای خودت ارسال می‌شود
            await send_order_to_admin(
                context=context,
                order_id=order_id,
                code=code,
                size=size,
                price=price,
                name=name,
                phone=phone,
                address=address,
                customer=update.effective_user
            )

            # بعد تأیید برای مشتری
            await update.message.reply_text(
                "✅ سفارش شما با موفقیت ثبت شد.\n\n"
                f"🧾 شماره سفارش: {order_id}\n"
                f"👟 محصول: {code}\n"
                f"📏 سایز: {size}\n"
                f"💰 مبلغ: {price:,} تومان\n\n"
                f"👤 نام: {name}\n"
                f"📱 موبایل: {phone}\n"
                f"📍 آدرس: {address}\n\n"
                "🔔 سفارش برای فروشگاه ارسال شد.\n"
                "برای پیگیری، شماره سفارش خود را نگه دارید.",
                reply_markup=main_menu()
            )

            context.user_data.clear()
            return

    # ---------------------------------
    # جستجو منتظر کد
    # ---------------------------------

    if context.user_data.get("searching"):
        context.user_data["searching"] = False

        code = text.upper().replace(" ", "")

        await show_product(
            update.message,
            code
        )
        return

    # ---------------------------------
    # مردانه
    # ---------------------------------

    if text == "👟 کفش مردانه ۴۱ تا ۴۵":
        await show_product(
            update.message,
            "K530-05"
        )
        return

    # ---------------------------------
    # زنانه
    # ---------------------------------

    if text == "👟 کفش زنانه ۳۷ تا ۴۰":
        await show_product(
            update.message,
            "K530-06"
        )
        return

    # ---------------------------------
    # جستجو
    # ---------------------------------

    if text == "🔎 جستجو با کد محصول":
        context.user_data["searching"] = True

        await update.message.reply_text(
            "🔎 کد محصول را ارسال کنید.\n\n"
            "مثال:\n"
            "K530-06"
        )
        return

    # ---------------------------------
    # ثبت سفارش
    # ---------------------------------

    if text == "🛒 ثبت سفارش":
        await update.message.reply_text(
            "🛒 برای ثبت سفارش، ابتدا محصول را انتخاب کنید "
            "و روی «خرید این محصول» بزنید."
        )
        return

    # ---------------------------------
    # پیگیری
    # ---------------------------------

    if text == "📦 پیگیری سفارش":
        await update.message.reply_text(
            "📦 شماره سفارش خود را برای پشتیبانی ارسال کنید.\n\n"
            f"👨‍💬 پشتیبانی: {SUPPORT_USERNAME}"
        )
        return

    # ---------------------------------
    # استعلام
    # ---------------------------------

    if text == "💬 استعلام قیمت و موجودی":
        context.user_data["searching"] = True

        await update.message.reply_text(
            "💬 کد کفش موردنظر را ارسال کنید.\n\n"
            "مثال: K530-06"
        )
        return

    # ---------------------------------
    # پشتیبانی
    # ---------------------------------

    if text == "👨‍💬 پشتیبانی":
        await update.message.reply_text(
            "👨‍💬 پشتیبانی کتونی 530\n\n"
            f"{SUPPORT_USERNAME}"
        )
        return

    # ---------------------------------
    # کانال
    # ---------------------------------

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

    # ---------------------------------
    # اگر مشتری مستقیم کد محصول بفرستد
    # ---------------------------------

    direct_code = text.upper().replace(" ", "")

    if direct_code in PRODUCTS:
        await show_product(
            update.message,
            direct_code
        )
        return

    # ---------------------------------
    # پاسخ عمومی
    # ---------------------------------

    await update.message.reply_text(
        "متوجه نشدم 😊\n\n"
        "از گزینه‌های پایین انتخاب کنید یا کد محصول را ارسال کنید 👇",
        reply_markup=main_menu()
    )


# =====================================
# دستورات
# =====================================

async def products_command(update, context):
    await update.message.reply_text(
        "👟 دسته‌بندی موردنظر را انتخاب کنید:",
        reply_markup=main_menu()
    )


async def search_command(update, context):
    context.user_data["searching"] = True

    await update.message.reply_text(
        "🔎 کد محصول را ارسال کنید:"
    )


async def order_command(update, context):
    await update.message.reply_text(
        "🛒 ابتدا محصول موردنظر را انتخاب کنید.",
        reply_markup=main_menu()
    )


async def track_command(update, context):
    await update.message.reply_text(
        "📦 شماره سفارش خود را برای پشتیبانی ارسال کنید.\n\n"
        f"{SUPPORT_USERNAME}"
    )


async def support_command(update, context):
    await update.message.reply_text(
        "👨‍💬 پشتیبانی کتونی 530\n\n"
        f"{SUPPORT_USERNAME}"
    )


# =====================================
# اجرای ربات
# =====================================

def main():

    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN در Railway تنظیم نشده است."
        )

    app = Application.builder().token(TOKEN).build()

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
        CommandHandler("track",

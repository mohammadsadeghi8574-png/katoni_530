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
    filters,
)

# =========================
# تنظیمات کتونی 530
# =========================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

CHANNEL = "@katooni_530"
CHANNEL_LINK = "https://t.me/katooni_530"

# =========================
# منوی اصلی
# =========================

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["👟 کفش مردانه ۴۱ تا ۴۵", "👟 کفش زنانه ۳۷ تا ۴۰"],
        ["🔎 جستجو با کد محصول", "🛒 ثبت سفارش"],
        ["📦 پیگیری سفارش", "💬 استعلام قیمت و موجودی"],
        ["👨‍💬 پشتیبانی", "📣 کانال تلگرام"],
    ],
    resize_keyboard=True,
)


# =========================
# بررسی عضویت در کانال
# =========================

async def is_member(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL,
            user_id=user_id
        )

        return member.status in [
            "member",
            "administrator",
            "creator",
        ]

    except Exception as e:
        print("Membership check error:", e)
        return False


def join_buttons():
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


async def ask_to_join(update: Update):
    text = (
        "👋 سلام\n\n"
        "برای استفاده از ربات کتونی 530 ابتدا عضو کانال شوید 👇\n\n"
        "بعد از عضویت روی «✅ عضو شدم» بزنید."
    )

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=join_buttons(),
        )


async def require_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    if await is_member(context, user_id):
        return True

    await ask_to_join(update)
    return False


# =========================
# نمایش منوی اصلی
# =========================

async def show_menu(update: Update):
    text = (
        "👋 سلام\n\n"
        "به فروشگاه کتونی 530 خوش آمدید 👟\n\n"
        "دسته‌بندی موردنظر را انتخاب کنید:"
    )

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=MAIN_MENU,
        )

    elif update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            reply_markup=MAIN_MENU,
        )


# =========================
# دستور START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await require_member(update, context):
        return

    await show_menu(update)


# =========================
# دکمه عضو شدم
# =========================

async def check_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if await is_member(context, user_id):

        await query.answer(
            "✅ عضویت شما تأیید شد",
            show_alert=True,
        )

        await show_menu(update)

    else:

        await query.answer(
            "❌ هنوز عضو کانال نشده‌اید.",
            show_alert=True,
        )


# =========================
# محصولات
# =========================

async def products(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await require_member(update, context):
        return

    await update.message.reply_text(
        "👟 محصولات کتونی 530\n\n"
        "یکی از دسته‌بندی‌های مردانه یا زنانه را انتخاب کنید.",
        reply_markup=MAIN_MENU,
    )


async def men(update: Update):
    await update.message.reply_text(
        "👟 کفش مردانه | سایز ۴۱ تا ۴۵\n\n"
        "برای استعلام مدل موردنظر، کد کفش را ارسال کنید.\n\n"
        "مثال:\n"
        "K530-05"
    )


async def women(update: Update):
    await update.message.reply_text(
        "👟 کفش زنانه | سایز ۳۷ تا ۴۰\n\n"
        "برای استعلام مدل موردنظر، کد کفش را ارسال کنید.\n\n"
        "مثال:\n"
        "K530-05"
    )


# =========================
# جستجوی محصول
# =========================

async def search_product(update: Update):
    context_text = (
        "🔎 جستجو با کد محصول\n\n"
        "کد کفش موردنظر را ارسال کنید.\n\n"
        "مثال:\n"
        "K530-05"
    )

    await update.message.reply_text(context_text)


# =========================
# ثبت سفارش
# =========================

async def order(update: Update):
    await update.message.reply_text(
        "🛒 ثبت سفارش\n\n"
        "برای ثبت سفارش اطلاعات زیر را در یک پیام ارسال کنید:\n\n"
        "👟 کد کفش:\n"
        "📏 سایز:\n"
        "👤 نام و نام خانوادگی:\n"
        "📱 شماره تماس:\n"
        "📍 شهر:\n\n"
        "پشتیبانی سفارش شما را بررسی می‌کند."
    )


# =========================
# پیگیری سفارش
# =========================

async def track(update: Update):
    await update.message.reply_text(
        "📦 پیگیری سفارش\n\n"
        "شماره تماس یا کد سفارش خود را ارسال کنید تا سفارش شما بررسی شود."
    )


# =========================
# استعلام
# =========================

async def price(update: Update):
    await update.message.reply_text(
        "💬 استعلام قیمت و موجودی\n\n"
        "لطفاً کد محصول یا عکس کفش موردنظر را ارسال کنید."
    )


# =========================
# پشتیبانی
# =========================

async def support(update: Update):
    await update.message.reply_text(
        "👨‍💬 پشتیبانی کتونی 530\n\n"
        "پیام خود را همین‌جا ارسال کنید.\n"
        "پشتیبانی در اولین فرصت پاسخ می‌دهد."
    )


# =========================
# کانال تلگرام
# =========================

async def channel(update: Update):
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
        "📣 برای مشاهده جدیدترین مدل‌ها وارد کانال شوید:",
        reply_markup=keyboard,
    )


# =========================
# پیام‌های کاربران
# =========================

async def messages(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await require_member(update, context):
        return

    text = update.message.text

    if text == "👟 کفش مردانه ۴۱ تا ۴۵":
        await men(update)

    elif text == "👟 کفش زنانه ۳۷ تا ۴۰":
        await women(update)

    elif text == "🔎 جستجو با کد محصول":
        await search_product(update)

    elif text == "🛒 ثبت سفارش":
        await order(update)

    elif text == "📦 پیگیری سفارش":
        await track(update)

    elif text == "💬 استعلام قیمت و موجودی":
        await price(update)

    elif text == "👨‍💬 پشتیبانی":
        await support(update)

    elif text == "📣 کانال تلگرام":
        await channel(update)

    else:
        await update.message.reply_text(
            "پیام شما دریافت شد ✅\n\n"
            "برای انتخاب بخش موردنظر از منوی پایین استفاده کنید.",
            reply_markup=MAIN_MENU,
        )


# =========================
# اجرای ربات
# =========================

def main():

    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN در Railway تنظیم نشده است."
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("products", products))
    app.add_handler(CommandHandler("search", search_product))
    app.add_handler(CommandHandler("order", order))
    app.add_handler(CommandHandler("track", track))
    app.add_handler(CommandHandler("support", support))

    app.add_handler(
        CallbackQueryHandler(
            check_join,
            pattern="^check_join$",
        )
    )

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

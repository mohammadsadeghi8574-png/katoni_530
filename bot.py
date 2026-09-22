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
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

CHANNEL = "@katooni_530"
CHANNEL_LINK = "https://t.me/katooni_530"

MENU = [
    ["👟 محصولات", "🔎 جستجو با کد"],
    ["🛒 ثبت سفارش", "📦 پیگیری سفارش"],
    ["👨‍💬 پشتیبانی", "📣 کانال تلگرام"],
]

keyboard = ReplyKeyboardMarkup(
    MENU,
    resize_keyboard=True
)


async def is_member(context, user_id):
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
    except Exception:
        return False


async def ask_to_join(update):
    buttons = [
        [
            InlineKeyboardButton(
                "📣 عضویت در کانال کتونی 530",
                url=CHANNEL_LINK
            )
        ]
    ]

    await update.message.reply_text(
        "👋 برای استفاده از ربات، ابتدا عضو کانال کتونی 530 شوید.\n\n"
        "بعد از عضویت دوباره /start را بزنید.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if not await is_member(context, user_id):
        await ask_to_join(update)
        return

    await update.message.reply_text(
        "سلام 👋\n\n"
        "به فروشگاه کتونی 530 خوش آمدید 👟\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=keyboard,
    )


async def products(update: Update, context: ContextTypes.DEFAULT_TYPE):

    buttons = [
        [
            InlineKeyboardButton(
                "📣 مشاهده مدل‌های جدید",
                url=CHANNEL_LINK
            )
        ]
    ]

    await update.message.reply_text(
        "👟 محصولات جدید کتونی 530\n\n"
        "برای مشاهده مدل‌های موجود وارد کانال شوید 👇",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🔎 کد کفش را ارسال کنید.\n\n"
        "مثال:\nK530-05"
    )


async def order(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🛒 ثبت سفارش\n\n"
        "کد کفش + سایز + شماره تماس خود را ارسال کنید."
    )


async def track(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "📦 پیگیری سفارش\n\n"
        "شماره سفارش خود را ارسال کنید."
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "👨‍💬 پشتیبانی کتونی 530\n\n"
        "پیام خود را ارسال کنید تا فروشگاه بررسی کند."
    )


async def channel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    buttons = [
        [
            InlineKeyboardButton(
                "📣 ورود به کانال کتونی 530",
                url=CHANNEL_LINK
            )
        ]
    ]

    await update.message.reply_text(
        "📣 کانال رسمی کتونی 530",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text.strip()

    if text == "👟 محصولات":
        await products(update, context)

    elif text == "🔎 جستجو با کد":
        await search(update, context)

    elif text == "🛒 ثبت سفارش":
        await order(update, context)

    elif text == "📦 پیگیری سفارش":
        await track(update, context)

    elif text == "👨‍💬 پشتیبانی":
        await support(update, context)

    elif text == "📣 کانال تلگرام":
        await channel(update, context)

    else:
        await update.message.reply_text(
            "🔎 کد دریافت شد:\n\n"
            f"{text}\n\n"
            "برای بررسی این مدل با فروشگاه در ارتباط باشید."
        )


def main():

    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set"
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("products", products))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("order", order))
    app.add_handler(CommandHandler("track", track))
    app.add_handler(CommandHandler("support", support))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            messages
        )
    )

    print("Katoni 530 bot started")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

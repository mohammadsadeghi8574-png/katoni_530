import os

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

CHANNEL = "@katooni_530"

MENU = [
    ["👟 محصولات", "🔎 جستجو با کد"],
    ["🛒 ثبت سفارش", "📦 پیگیری سفارش"],
    ["👨‍💬 پشتیبانی", "📢 کانال تلگرام"],
]

keyboard = ReplyKeyboardMarkup(
    MENU,
    resize_keyboard=True
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                "📢 مشاهده محصولات در کانال",
                url="https://t.me/katooni_530"
            )
        ]
    ]

    await update.message.reply_text(
        "👟 محصولات جدید کتونی 530\n\n"
        "برای دیدن مدل‌های موجود وارد کانال شوید 👇",
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
        "لطفاً کد کفش، سایز و شماره تماس خود را ارسال کنید."
    )


async def track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📦 پیگیری سفارش\n\n"
        "لطفاً شماره سفارش خود را ارسال کنید."
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👨‍💬 پشتیبانی کتونی 530\n\n"
        "پیام خود را همینجا ارسال کنید."
    )


async def channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [
            InlineKeyboardButton(
                "📢 ورود به کانال کتونی 530",
                url="https://t.me/katooni_530"
            )
        ]
    ]

    await update.message.reply_text(
        "برای مشاهده مدل‌های جدید وارد کانال شوید 👇",
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

    elif text == "📢 کانال تلگرام":
        await channel(update, context)

    else:
        await update.message.reply_text(
            "✅ پیام شما دریافت شد.\n\n"
            "برای انتخاب بخش موردنظر از دکمه‌های پایین استفاده کنید.",
            reply_markup=keyboard,
        )


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("products", products))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("order", order))
    app.add_handler(CommandHandler("track", track))
    app.add_handler(CommandHandler("support", support))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, messages)
    )

    print("Katoni 530 bot started")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

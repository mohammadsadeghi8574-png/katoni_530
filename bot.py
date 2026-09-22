
import os

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

CHANNEL_LINK = "https://t.me/katooni_530"

MENU = [
    ["👟 کفش مردانه", "👟 کفش زنانه"],
    ["💰 استعلام قیمت", "📣 کانال تلگرام"],
]

keyboard = ReplyKeyboardMarkup(
    MENU,
    resize_keyboard=True
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام 👋\n\n"
        "👟 به فروشگاه کتونی 530 خوش آمدید\n\n"
        "دسته‌بندی موردنظر را انتخاب کنید:",
        reply_markup=keyboard
    )


async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "👟 کفش مردانه":
        await update.message.reply_text(
            "👟 کفش مردانه\n\n"
            "لطفاً کد کفش موردنظر را ارسال کنید.\n"
            "مثال: K530-05"
        )

    elif text == "👟 کفش زنانه":
        await update.message.reply_text(
            "👟 کفش زنانه\n\n"
            "لطفاً کد کفش موردنظر را ارسال کنید."
        )

    elif text == "💰 استعلام قیمت":
        await update.message.reply_text(
            "💰 برای استعلام قیمت، کد کفش را ارسال کنید."
        )

    elif text == "📣 کانال تلگرام":
        await update.message.reply_text(
            "📣 کانال رسمی کتونی 530\n\n"
            + CHANNEL_LINK
        )

    else:
        await update.message.reply_text(
            "✅ کد دریافت شد:\n\n"
            f"{text}\n\n"
            "برای بررسی قیمت و موجودی، پیام شما ثبت شد."
        )


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            messages
        )
    )

    print("Katoni 530 bot started")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

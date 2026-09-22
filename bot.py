import os

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

MENU = [
    ["👟 کفش مردانه", "👟 کفش زنانه"],
    ["🧒 کفش بچگانه"],
    ["💰 استعلام قیمت", "📣 کانال تلگرام"],
]

keyboard = ReplyKeyboardMarkup(
    MENU,
    resize_keyboard=True
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام 👋\n\n"
        "به فروشگاه کتونی 530 خوش آمدید 👟\n\n"
        "دسته‌بندی موردنظر را انتخاب کنید:",
        reply_markup=keyboard
    )


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    print("Katoni 530 bot started", flush=True)

    app.run_polling()


if __name__ == "__main__":
    main()

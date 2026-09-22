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

CHANNEL_LINK = "https://t.me/katooni_530"
SUPPORT_LINK = "https://t.me/katoni_530"

MENU = [
    ["👟 کفش مردانه ۴۱ تا ۴۵", "👟 کفش زنانه ۳۷ تا ۴۰"],
    ["💬 استعلام قیمت و موجودی", "📣 کانال تلگرام"],
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


async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    if text == "👟 کفش مردانه ۴۱ تا ۴۵":

        buttons = [
            [
                InlineKeyboardButton(
                    "👟 مشاهده مدل‌های مردانه",
                    url=CHANNEL_LINK
                )
            ],
            [
                InlineKeyboardButton(
                    "💬 استعلام قیمت و موجودی",
                    url=SUPPORT_LINK
                )
            ]
        ]

        await update.message.reply_text(
            "👟 کفش مردانه\n"
            "سایزهای ۴۱ تا ۴۵\n\n"
            "برای مشاهده مدل‌ها وارد کانال شوید 👇",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif text == "👟 کفش زنانه ۳۷ تا ۴۰":

        buttons = [
            [
                InlineKeyboardButton(
                    "👟 مشاهده مدل‌های زنانه",
                    url=CHANNEL_LINK
                )
            ],
            [
                InlineKeyboardButton(
                    "💬 استعلام قیمت و موجودی",
                    url=SUPPORT_LINK
                )
            ]
        ]

        await update.message.reply_text(
            "👟 کفش زنانه\n"
            "سایزهای ۳۷ تا ۴۰\n\n"
            "برای مشاهده مدل‌ها وارد کانال شوید 👇",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif text == "💬 استعلام قیمت و موجودی":

        buttons = [
            [
                InlineKeyboardButton(
                    "💬 پیام به فروشگاه",
                    url=SUPPORT_LINK
                )
            ]
        ]

        await update.message.reply_text(
            "برای استعلام قیمت و موجودی 👇\n\n"
            "عکس مدل موردنظر را برای ما ارسال کنید.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif text == "📣 کانال تلگرام":

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
            reply_markup=InlineKeyboardMarkup(buttons)
        )


def main():

    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

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

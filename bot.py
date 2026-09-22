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

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

CHANNEL = "@katooni_530"
CHANNEL_LINK = "https://t.me/katooni_530"

MENU = [
    ["👟 کفش زنانه ۳۷ تا ۴۰", "👟 کفش مردانه ۴۱ تا ۴۵"],
    ["💬 استعلام قیمت و موجودی", "📣 کانال تلگرام"],
]

keyboard = ReplyKeyboardMarkup(
    MENU,
    resize_keyboard=True
)


async def is_member(context, user_id):
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
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📣 عضویت در کانال کتونی 530",
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


async def ask_to_join(update, context):
    text = (
        "👋 سلام\n\n"
        "برای استفاده از ربات کتونی 530 ابتدا عضو کانال شوید 👇\n\n"
        "بعد از عضویت روی «✅ عضو شدم» بزنید."
    )

    if update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            reply_markup=join_buttons()
        )
    else:
        await update.effective_message.reply_text(
            text,
            reply_markup=join_buttons()
        )


async def show_menu(message):
    await message.reply_text(
        "سلام 👋\n\n"
        "به فروشگاه کتونی 530 خوش آمدید 👟\n\n"
        "دسته‌بندی موردنظر را انتخاب کنید:",
        reply_markup=keyboard
    )


async def require_member(update, context):
    user_id = update.effective_user.id

    if await is_member(context, user_id):
        return True

    await ask_to_join(update, context)
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_member(update, context):
        return

    await show_menu(update.effective_message)


async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if await is_member(context, user_id):
        await query.answer("عضویت شما تأیید شد ✅")
        await show_menu(query.message)
    else:
        await query.answer(
            "هنوز عضو کانال نشده‌اید.",
            show_alert=True
        )


async def women(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👟 مشاهده مدل‌های زنانه",
                url=CHANNEL_LINK
            )
        ],
        [
            InlineKeyboardButton(
                "💬 استعلام قیمت و موجودی",
                url="https://t.me/katooni_530"
            )
        ]
    ])

    await update.message.reply_text(
        "👟 کفش زنانه\n"
        "سایزهای ۳۷ تا ۴۰\n\n"
        "برای مشاهده مدل‌ها وارد کانال شوید 👇",
        reply_markup=buttons
    )


async def men(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👟 مشاهده مدل‌های مردانه",
                url=CHANNEL_LINK
            )
        ],
        [
            InlineKeyboardButton(
                "💬 استعلام قیمت و موجودی",
                url="https://t.me/katooni_530"
            )
        ]
    ])

    await update.message.reply_text(
        "👟 کفش مردانه\n"
        "سایزهای ۴۱ تا ۴۵\n\n"
        "برای مشاهده مدل‌ها وارد کانال شوید 👇",
        reply_markup=buttons
    )


async def channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📣 ورود به کانال کتونی 530",
                url=CHANNEL_LINK
            )
        ]
    ])

    await update.message.reply_text(
        "📣 کانال رسمی کتونی 530",
        reply_markup=buttons
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💬 برای استعلام قیمت و موجودی، "
        "کد کفش و سایز موردنظر را همینجا ارسال کنید."
    )


async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_member(update, context):
        return

    text = update.message.text.strip()

    if text == "👟 کفش زنانه ۳۷ تا ۴۰":
        await women(update, context)

    elif text == "👟 کفش مردانه ۴۱ تا ۴۵":
        await men(update, context)

    elif text == "💬 استعلام قیمت و موجودی":
        await support(update, context)

    elif text == "📣 کانال تلگرام":
        await channel(update, context)

    else:
        await update.message.reply_text(
            "✅ پیام شما دریافت شد.\n\n"
            f"{text}\n\n"
            "برای استعلام این مدل، سایز موردنظر را هم ارسال کنید."
        )


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        CallbackQueryHandler(
            check_join,
            pattern="^check_join$"
        )
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

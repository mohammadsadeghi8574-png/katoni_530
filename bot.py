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

# آیدی تلگرام برای استعلام قیمت
SELLER_LINK = "https://t.me/katoni_530"

MENU = [
    ["👟 کفش مردانه", "👟 کفش زنانه"],
    ["🧒 کفش بچگانه"],
    ["💰 استعلام قیمت", "📣 کانال تلگرام"],
    ["👨‍💬 پشتیبانی"],
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
        "👋 برای استفاده از ربات ابتدا عضو کانال کتونی 530 شوید.\n\n"
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
        "دسته‌بندی موردنظر را انتخاب کنید:",
        reply_markup=keyboard,
    )


async def price_button(update):
    buttons = [
        [
            InlineKeyboardButton(
                "💰 استعلام قیمت",
                url=SELLER_LINK
            )
        ]
    ]

    await update.message.reply_text(
        "برای اطلاع از قیمت و موجودی، روی دکمه زیر بزنید 👇",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not await is_member(context, user_id):
        await ask_to_join(update)
        return

    text = update.message.text.strip()

    if text == "👟 کفش مردانه":
        await update.message.reply_text(
            "👟 مدل‌های کفش مردانه\n\n"
            "مدل‌های مردانه به‌زودی اینجا نمایش داده می‌شوند."
        )
       

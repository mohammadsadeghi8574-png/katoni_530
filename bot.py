import os
import requests

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WC_URL = os.getenv("WC_URL", "").rstrip("/")
WC_CONSUMER_KEY = os.getenv("WC_CONSUMER_KEY")
WC_CONSUMER_SECRET = os.getenv("WC_CONSUMER_SECRET")

MENU = [
    ["👟 محصولات", "🔎 جستجو با کد"],
    ["🛒 ثبت سفارش", "📦 پیگیری سفارش"],
    ["👨‍💬 پشتیبانی", "🌐 سایت فروشگاه"],
]

keyboard = ReplyKeyboardMarkup(MENU, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام 👋\n\n"
        "به فروشگاه کتونی 530 خوش آمدید 👟\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=keyboard,
    )


async def products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👟 برای پیدا کردن کفش، روی «🔎 جستجو با کد» بزنید."
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting_for_code"] = True

    await update.message.reply_text(
        "🔎 کد کفش را ارسال کنید.\n\n"
        "مثال:\nK530-05"
    )


async def find_product(update: Update, code: str):
    try:
        url = f"{WC_URL}/wp-json/wc/v3/products"

        response = requests.get(
            url,
            params={
                "sku": code,
                "consumer_key": WC_CONSUMER_KEY,
                "consumer_secret": WC_CONSUMER_SECRET,
            },
            timeout=15,
        )

        response.raise_for_status()
        products = response.json()

        if not products:
            await update.message.reply_text(
                f"❌ محصولی با کد {code} پیدا نشد."
            )
            return

        product = products[0]

        name = product.get("name", "بدون نام")
        price = product.get("price") or "نامشخص"
        stock = product.get("stock_status", "")
        permalink = product.get("permalink", WC_URL)

        stock_text = (
            "✅ موجود"
            if stock == "instock"
            else "❌ ناموجود"
        )

        message = (
            f"👟 {name}\n\n"
            f"🔎 کد: {code}\n"
            f"💰 قیمت: {price} تومان\n"
            f"📦 وضعیت: {stock_text}\n\n"
            f"🛒 مشاهده و خرید:\n{permalink}"
        )

        images = product.get("images", [])

        if images and images[0].get("src"):
            await update.message.reply_photo(
                photo=images[0]["src"],
                caption=message,
            )
        else:
            await update.message.reply_text(message)

    except Exception as e:
        print("WooCommerce error:", e)

        await update.message.reply_text(
            "⚠️ ارتباط با سایت برقرار نشد.\n"
            "لطفاً دوباره امتحان کنید."
        )


async def order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛒 برای ثبت سفارش، ابتدا محصول موردنظر را با کد جستجو کنید."
    )


async def track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📦 شماره سفارش خود را ارسال کنید."
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👨‍💬 پشتیبانی فروشگاه کتونی 530"
    )


async def website(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌐 سایت فروشگاه:\nhttps://katoni530.com"
    )


async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "👟 محصولات":
        await products(update, context)

    elif text == "🔎 جستجو با کد":
        await search_command(update, context)

    elif text == "🛒 ثبت سفارش":
        await order(update, context)

    elif text == "📦 پیگیری سفارش":
        await track(update, context)

    elif text == "👨‍💬 پشتیبانی":
        await support(update, context)

    elif text == "🌐 سایت فروشگاه":
        await website(update, context)

    elif context.user_data.get("waiting_for_code"):
        context.user_data["waiting_for_code"] = False
        await update.message.reply_text("⏳ در حال جستجوی محصول...")
        await find_product(update, text)

    else:
        await update.message.reply_text(
            "لطفاً یکی از گزینه‌های منو را انتخاب کنید.",
            reply_markup=keyboard,
        )


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("products", products))
    app.add_handler(CommandHandler("search", search_command))
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

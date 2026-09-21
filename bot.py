import os

from telegram import Update, ReplyKeyboardMarkup

from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

MENU = [

    ["👟 محصولات", "🔎 جستجو با کد"],

    ["🛒 ثبت سفارش", "📦 پیگیری سفارش"],

    ["👨‍💬 پشتیبانی", "🌐 سایت فروشگاه"]

]

keyboard = ReplyKeyboardMarkup(MENU, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(

        "سلام 👋\n"

        "به فروشگاه کتونی 530 خوش آمدید 👟\n\n"

        "از منوی زیر انتخاب کنید:",

        reply_markup=keyboard

    )

async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text.strip()

    if text == "👟 محصولات":

        await update.message.reply_text(

            "👟 جدیدترین محصولات کتونی 530\n"

            "به‌زودی محصولات سایت اینجا نمایش داده می‌شوند."

        )

    elif text == "🔎 جستجو با کد":

        context.user_data["search"] = True

        await update.message.reply_text(

            "🔎 کد کفش را بفرستید.\nمثال: K530-05"

        )

    elif text == "🛒 ثبت سفارش":

        await update.message.reply_text(

            "🛒 کد کفش و سایز موردنظر را ارسال کنید."

        )

    elif text == "📦 پیگیری سفارش":

        await update.message.reply_text(

            "📦 شماره سفارش خود را ارسال کنید."

        )

    elif text == "👨‍💬 پشتیبانی":

        await update.message.reply_text(

            "👨‍💬 پشتیبانی:\n@katoni_530"

        )

    elif text == "🌐 سایت فروشگاه":

        await update.message.reply_text(

            "🌐 katoni530.com"

        )

    elif context.user_data.get("search"):

        context.user_data["search"] = False

        await update.message.reply_text(

            f"🔎 کد محصول: {text}\n"

            "در مرحله بعد این قسمت به محصولات سایت وصل می‌شود."

        )

    else:

        await update.message.reply_text(

            "یکی از گزینه‌های منو را انتخاب کنید 👇",

            reply_markup=keyboard

        )

def main():

    if not TOKEN:

        raise RuntimeError("TELEGRAM_BOT_TOKEN not found")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(

        MessageHandler(filters.TEXT & ~filters.COMMAND, message)

    )

    app.run_polling()

if __name__ == "__main__":

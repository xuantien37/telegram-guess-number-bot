import os
import random
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Lưu trạng thái trò chơi của từng user
user_games = {}

# Lệnh /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Chào bạn! Gõ /play để bắt đầu trò chơi đoán số 🎯")

# Lệnh /play
async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    secret_number = random.randint(1, 100)
    user_games[user_id] = secret_number
    await update.message.reply_text("🤖 Mình đã chọn một số từ 1 đến 100. Hãy thử đoán xem!")

# Xử lý tin nhắn đoán số
async def handle_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message.text

    if user_id not in user_games:
        await update.message.reply_text("Bạn chưa bắt đầu trò chơi. Gõ /play để chơi nhé!")
        return

    if not message.isdigit():
        await update.message.reply_text("Vui lòng nhập một số nguyên từ 1 đến 100.")
        return

    guess = int(message)
    secret = user_games[user_id]

    if guess < secret:
        await update.message.reply_text("🔼 Cao hơn nhé!")
    elif guess > secret:
        await update.message.reply_text("🔽 Thấp hơn rồi!")
    else:
        await update.message.reply_text("🎉 Chính xác! Bạn đoán đúng rồi!")
        del user_games[user_id]

# Khởi chạy bot
if __name__ == '__main__':
    app = ApplicationBuilder().token('7135897467:AAGoOrR-QBFlcnVMhmmqRZwXYP8T8yxI0JQ').build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("play", play))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_guess))

    print("Bot đoán số đang chạy...")
    app.run_polling()

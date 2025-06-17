# File: guess_number_bot.py

import os
import random
import json
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ========== CẤU HÌNH ==========
TOKEN = '7135897467:AAGoOrR-QBFlcnVMhmmqRZwXYP8T8yxI0JQ'
SCORE_FILE = 'score_data.json'
MAX_HINTS = 1
TIMEOUT_SECONDS = 300  # 5 phút

# ========== DỮ LIỆU TOÀN CỤC ==========
user_games = {}
players_data = {}

# ========== LOAD / SAVE ==========
def load_data():
    global players_data
    if os.path.exists(SCORE_FILE):
        with open(SCORE_FILE, 'r') as f:
            players_data = json.load(f)

def save_data():
    with open(SCORE_FILE, 'w') as f:
        json.dump(players_data, f, indent=2)

# ========== LEVEL & ĐỘ KHÓ ==========
def get_level(score):
    if score < 100: return 1
    elif score < 300: return 2
    elif score < 600: return 3
    elif score < 1000: return 4
    return 5

def get_difficulty(level):
    return {
        1: {"range": (1, 100), "attempts": 7},
        2: {"range": (1, 200), "attempts": 6},
        3: {"range": (1, 300), "attempts": 6},
        4: {"range": (1, 400), "attempts": 5},
        5: {"range": (1, 500), "attempts": 4},
    }[level]

# ========== TRỢ GIÚP SHOP ==========
SHOP_ITEMS = {
    "extra_attempt": {"price": 30, "desc": "+1 lượt đoán"},
    "hint_type": {"price": 20, "desc": "Gợi ý chẵn/lẻ"},
    "hint_range": {"price": 40, "desc": "Gợi ý khoảng"},
    "change_secret": {"price": 50, "desc": "Đổi số bí mật"},
}

def get_player(uid):
    if str(uid) not in players_data:
        players_data[str(uid)] = {
            "score": 0,
            "wins": 0,
            "inventory": {}
        }
    return players_data[str(uid)]

# ========== TIMEOUT ==========
async def timeout_game(user_id, context):
    await asyncio.sleep(TIMEOUT_SECONDS)
    if user_id in user_games:
        del user_games[user_id]
        await context.bot.send_message(chat_id=user_id, text="⌛ Hết thời gian! Trò chơi đã kết thúc. Gõ /play để bắt đầu lại.")

# ========== LỆNH ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Gõ /play để bắt đầu đoán số 🎯")

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Người chơi"
    player = get_player(user_id)
    level = get_level(player["score"])
    diff = get_difficulty(level)
    secret = random.randint(*diff["range"])
    task = asyncio.create_task(timeout_game(user_id, context))
    user_games[user_id] = {
        "secret": secret,
        "attempts": 0,
        "max_attempts": diff["attempts"],
        "range": diff["range"],
        "timeout_task": task,
        "hints_used": 0
    }
    await update.message.reply_text(f"🎯 Level {level} ({diff['range'][0]}–{diff['range'][1]}), bạn có {diff['attempts']} lượt đoán. Bắt đầu nào!")

async def handle_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message.text.strip()

    if user_id not in user_games:
        await update.message.reply_text("⚠️ Gõ /play để bắt đầu trò chơi.")
        return

    if not message.isdigit():
        await update.message.reply_text("❌ Vui lòng nhập một số nguyên.")
        return

    guess = int(message)
    game = user_games[user_id]
    player = get_player(user_id)
    secret = game["secret"]
    game["attempts"] += 1

    if guess < secret:
        await update.message.reply_text(f"🔼 Cao hơn! ({game['max_attempts'] - game['attempts']} lượt còn lại)")
    elif guess > secret:
        await update.message.reply_text(f"🔽 Thấp hơn! ({game['max_attempts'] - game['attempts']} lượt còn lại)")
    else:
        points = max(10, 100 - game["attempts"] * 10)
        player["score"] += points
        player["wins"] += 1
        game["timeout_task"].cancel()
        del user_games[user_id]
        save_data()
        await update.message.reply_text(f"🎉 Đúng rồi! Bạn nhận được {points} điểm. Tổng điểm: {player['score']}")
        return

    if game["attempts"] >= game["max_attempts"]:
        del user_games[user_id]
        await update.message.reply_text(f"💥 Hết lượt! Số đúng là {secret}. Gõ /play để thử lại!")

async def show_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    msg = "🛒 CỬA HÀNG HỖ TRỢ\n\n"
    for key, item in SHOP_ITEMS.items():
        msg += f"🔹 {item['desc']} - {item['price']} điểm → /buy {key}\n"
    msg += f"\n🎯 Điểm hiện tại: {player['score']}"
    await update.message.reply_text(msg)

async def buy_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text("❓ Cú pháp: /buy <tên vật phẩm>")
        return
    item = args[0]
    player = get_player(user_id)

    if item not in SHOP_ITEMS:
        await update.message.reply_text("❌ Vật phẩm không tồn tại.")
        return
    price = SHOP_ITEMS[item]["price"]
    if player["score"] < price:
        await update.message.reply_text("❌ Bạn không đủ điểm.")
        return
    player["score"] -= price
    player["inventory"][item] = player["inventory"].get(item, 0) + 1
    save_data()
    await update.message.reply_text(f"✅ Đã mua {SHOP_ITEMS[item]['desc']} thành công!")

async def use_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    game = user_games.get(user_id)

    if not game:
        await update.message.reply_text("⚠️ Bạn chưa chơi. Gõ /play để bắt đầu.")
        return

    inv = player["inventory"]
    if inv.get("hint_type", 0) > 0:
        parity = "chẵn" if game["secret"] % 2 == 0 else "lẻ"
        inv["hint_type"] -= 1
        await update.message.reply_text(f"💡 Gợi ý: Số là số {parity}.")
    elif inv.get("hint_range", 0) > 0:
        secret = game["secret"]
        rng = game["range"]
        width = (rng[1] - rng[0]) // 4
        low = max(rng[0], secret - width)
        high = min(rng[1], secret + width)
        inv["hint_range"] -= 1
        await update.message.reply_text(f"📐 Gợi ý: Số nằm trong khoảng {low} – {high}.")
    else:
        await update.message.reply_text("❌ Bạn không có quyền trợ giúp nào.")

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    await update.message.reply_text(
        f"📊 THỐNG KÊ\n"
        f"🏆 Điểm: {player['score']}\n"
        f"✅ Số lần thắng: {player['wins']}\n"
        f"🎒 Túi đồ: {player['inventory']}"
    )

# ========== MAIN ==========
if __name__ == '__main__':
    load_data()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("play", play))
    app.add_handler(CommandHandler("shop", show_shop))
    app.add_handler(CommandHandler("buy", buy_item))
    app.add_handler(CommandHandler("hint", use_hint))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_guess))
    print("✅ Bot đã sẵn sàng!")
    app.run_polling()


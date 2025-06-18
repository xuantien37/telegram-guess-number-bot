import os
import random
import json
import asyncio
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ========== CẤU HÌNH ==========
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Vui lòng cung cấp BOT_TOKEN trong biến môi trường")

SCORE_FILE = 'score_data.json'
TIMEOUT_SECONDS = 300  # 5 phút
DAILY_REWARD_BASE = 20
MAX_DAILY_STREAK = 7

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== TRẠNG THÁI TRÒ CHƠI ==========
user_games = {}
players_data = {}
pvp_challenges = {}

# ========== XỬ LÝ DỮ LIỆU ==========
def load_data():
    global players_data
    try:
        if os.path.exists(SCORE_FILE):
            with open(SCORE_FILE, 'r') as f:
                players_data = json.load(f)
    except Exception as e:
        logger.error(f"Lỗi khi đọc file dữ liệu: {e}")
        players_data = {}

def save_data():
    try:
        with open(SCORE_FILE, 'w') as f:
            json.dump(players_data, f, indent=2)
    except Exception as e:
        logger.error(f"Lỗi khi lưu file dữ liệu: {e}")

def get_player(uid):
    uid_str = str(uid)
    if uid_str not in players_data:
        players_data[uid_str] = {
            "score": 0,
            "wins": 0,
            "losses": 0,
            "games_played": 0,
            "inventory": {},
            "current_streak": 0,
            "max_streak": 0,
            "last_reward_date": None,
            "reward_streak": 0,
            "completed_quests": {},
            "pvp_wins": 0,
            "pvp_losses": 0
        }
    return players_data[uid_str]

# ========== ĐỘ KHÓ TRÒ CHƠI ==========
def get_level(score):
    if score < 100: return 1
    elif score < 300: return 2
    elif score < 600: return 3
    elif score < 1000: return 4
    elif score < 1500: return 5
    elif score < 2500: return 6
    return 7

def get_difficulty(level):
    return {
        1: {"range": (1, 50), "attempts": 7, "penalty": 5},
        2: {"range": (1, 100), "attempts": 6, "penalty": 10},
        3: {"range": (1, 200), "attempts": 6, "penalty": 15},
        4: {"range": (1, 300), "attempts": 5, "penalty": 20},
        5: {"range": (1, 500), "attempts": 5, "penalty": 25},
        6: {"range": (1, 750), "attempts": 4, "penalty": 30},
        7: {"range": (1, 1000), "attempts": 4, "penalty": 40},
    }[level]

# ========== CỬA HÀNG ==========
SHOP_ITEMS = {
    "extra_attempt": {"price": 30, "desc": "+1 lượt đoán", "type": "game"},
    "hint_type": {"price": 20, "desc": "Gợi ý chẵn/lẻ", "type": "hint"},
    "hint_range": {"price": 40, "desc": "Gợi ý khoảng ±50", "type": "hint"},
    "change_secret": {"price": 50, "desc": "Đổi số bí mật", "type": "game"},
    "streak_protector": {"price": 100, "desc": "Bảo vệ streak khi thua", "type": "bonus"},
    "double_points": {"price": 150, "desc": "Nhận 2x điểm trong 3 ván", "type": "bonus"},
}

# ========== NHIỆM VỤ ==========
QUESTS = {
    "win_3_games": {"goal": 3, "reward": 50, "desc": "Thắng 3 trò chơi"},
    "reach_1000": {"goal": 1000, "reward": 100, "desc": "Đạt 1000 điểm"},
    "win_5_pvp": {"goal": 5, "reward": 150, "desc": "Thắng 5 trận PvP"},
    "daily_streak_7": {"goal": 7, "reward": 200, "desc": "Nhận quà 7 ngày liên tiếp"},
}

# ========== HỆ THỐNG PvP ==========
class PvPGame:
    def __init__(self, challenger_id, opponent_id, difficulty):
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id
        self.difficulty = difficulty
        self.secret = random.randint(*difficulty["range"])
        self.challenger_attempts = 0
        self.opponent_attempts = 0
        self.max_attempts = difficulty["attempts"]
        self.winner = None
        self.start_time = datetime.now()
        
    def make_guess(self, player_id, guess):
        if player_id == self.challenger_id:
            self.challenger_attempts += 1
        else:
            self.opponent_attempts += 1
            
        if guess == self.secret:
            self.winner = player_id
            return "win"
        elif guess < self.secret:
            return "higher"
        else:
            return "lower"

# ========== TÍNH ĐIỂM ==========
def calculate_points(attempts_used, max_attempts, streak=0, difficulty_level=1, is_pvp=False):
    base_points = max(10, (100 - attempts_used * 10) * difficulty_level)
    streak_bonus = streak * 5
    
    # Điểm thưởng cho PvP
    if is_pvp:
        base_points *= 1.5
    
    # Áp dụng double points nếu có
    return int(base_points + streak_bonus)

# ========== KIỂM TRA NHIỆM VỤ ==========
async def check_quests(user_id, context, quest_type, progress):
    player = get_player(user_id)
    completed = False
    
    for quest_id, quest in QUESTS.items():
        if quest_id.startswith(quest_type):
            current_progress = player.get("quest_progress", {}).get(quest_id, 0)
            new_progress = min(current_progress + progress, quest["goal"])
            
            player.setdefault("quest_progress", {})[quest_id] = new_progress
            
            if new_progress >= quest["goal"] and not player.get("completed_quests", {}).get(quest_id, False):
                player["score"] += quest["reward"]
                player.setdefault("completed_quests", {})[quest_id] = True
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎯 Hoàn thành nhiệm vụ: {quest['desc']}! +{quest['reward']} điểm"
                )
                completed = True
                save_data()
    
    return completed

# ========== HẸN GIỜ ==========
async def timeout_game(user_id, context):
    await asyncio.sleep(TIMEOUT_SECONDS)
    if user_id in user_games:
        player = get_player(user_id)
        player["losses"] += 1
        player["current_streak"] = 0
        save_data()
        
        del user_games[user_id]
        await context.bot.send_message(
            chat_id=user_id,
            text="⌛ Hết thời gian! Trò chơi kết thúc. Gõ /play để bắt đầu lại."
        )

async def timeout_pvp_game(game_id, context):
    await asyncio.sleep(TIMEOUT_SECONDS * 2)  # Thời gian dài hơn cho PvP
    if game_id in pvp_challenges:
        game = pvp_challenges[game_id]
        challenger = get_player(game.challenger_id)
        opponent = get_player(game.opponent_id)
        
        challenger["pvp_losses"] += 1
        opponent["pvp_losses"] += 1
        save_data()
        
        del pvp_challenges[game_id]
        await context.bot.send_message(
            chat_id=game.challenger_id,
            text="⌛ Trận đấu PvP đã hết thời gian mà không có người chiến thắng!"
        )
        await context.bot.send_message(
            chat_id=game.opponent_id,
            text="⌛ Trận đấu PvP đã hết thời gian mà không có người chiến thắng!"
        )

# ========== LỆNH CƠ BẢN ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Chào {user.first_name}! Tôi là bot đoán số thông minh.\n\n"
        "🎮 Các lệnh chính:\n"
        "/play - Bắt đầu trò chơi mới\n"
        "/pvp - Thách đấu người khác\n"
        "/shop - Cửa hàng vật phẩm\n"
        "/daily - Nhận quà hàng ngày\n"
        "/leaderboard - Bảng xếp hạng\n"
        "/stats - Thống kê cá nhân"
    )

# ========== TRÒ CHƠI CHÍNH ==========
async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in user_games:
        await update.message.reply_text("⚠️ Bạn đang có trò chơi hoạt động! Gõ /giveup nếu muốn bỏ cuộc.")
        return
    
    player = get_player(user_id)
    level = get_level(player["score"])
    diff = get_difficulty(level)
    
    # Tạo số bí mật tránh các số gần biên
    secret = random.randint(
        diff["range"][0] + int(0.1 * (diff["range"][1] - diff["range"][0])),
        diff["range"][1] - int(0.1 * (diff["range"][1] - diff["range"][0]))
    )
    
    task = asyncio.create_task(timeout_game(user_id, context))
    user_games[user_id] = {
        "secret": secret,
        "attempts": 0,
        "max_attempts": diff["attempts"],
        "range": diff["range"],
        "timeout_task": task,
        "level": level,
        "start_time": datetime.now(),
        "used_hints": []
    }
    
    await update.message.reply_text(
        f"🎮 Bắt đầu trò chơi cấp {level}!\n"
        f"🔢 Phạm vi số: {diff['range'][0]} - {diff['range'][1]}\n"
        f"💡 Số lượt đoán: {diff['attempts']}\n\n"
        f"Gửi số bạn đoán ngay bây giờ!"
    )

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
    
    # Kiểm tra xem có double points không
    is_double_points = "double_points" in player.get("active_bonuses", {})
    
    if guess < secret:
        await update.message.reply_text(
            f"🔼 Cao hơn! ({game['max_attempts'] - game['attempts']} lượt còn lại)" +
            (" 🎯 2x ĐIỂM!" if is_double_points else "")
        )
    elif guess > secret:
        await update.message.reply_text(
            f"🔽 Thấp hơn! ({game['max_attempts'] - game['attempts']} lượt còn lại)" +
            (" 🎯 2x ĐIỂM!" if is_double_points else "")
        )
    else:
        # Xử lý khi đoán đúng
        points = calculate_points(
            game["attempts"],
            game["max_attempts"],
            player.get("current_streak", 0),
            game["level"]
        )
        
        if is_double_points:
            points *= 2
            player["active_bonuses"]["double_points"] -= 1
            if player["active_bonuses"]["double_points"] <= 0:
                del player["active_bonuses"]["double_points"]
        
        player["score"] += points
        player["wins"] += 1
        player["games_played"] += 1
        player["current_streak"] = player.get("current_streak", 0) + 1
        player["max_streak"] = max(player.get("max_streak", 0), player["current_streak"])
        player["last_win_time"] = datetime.now().isoformat()
        
        # Kiểm tra nhiệm vụ
        await check_quests(user_id, context, "win_games", 1)
        
        game["timeout_task"].cancel()
        del user_games[user_id]
        save_data()
        
        await update.message.reply_text(
            f"🎉 Chính xác! Số là {secret}.\n"
            f"🏆 Điểm: +{points} | Tổng: {player['score']}\n"
            f"🔥 Streak: {player['current_streak']}\n"
            f"⏳ Bắt đầu ván mới sau 3 giây..."
        )
        
        await asyncio.sleep(3)
        await play(update, context)
        return
    
    if game["attempts"] >= game["max_attempts"]:
        # Xử lý khi hết lượt
        penalty = game.get("penalty", 20)
        
        # Kiểm tra streak protector
        if "streak_protector" in player.get("inventory", {}) and player["inventory"]["streak_protector"] > 0:
            player["inventory"]["streak_protector"] -= 1
            penalty = 0
            await update.message.reply_text("🛡️ Bạn đã sử dụng streak protector!")
        else:
            player["current_streak"] = 0
        
        player["score"] = max(0, player["score"] - penalty)
        player["losses"] += 1
        player["games_played"] += 1
        save_data()
        
        await update.message.reply_text(
            f"😢 Bạn đã hết lượt. Số đúng là {secret}.\n"
            f"❌ Trừ {penalty} điểm. Tổng điểm: {player['score']}\n"
            f"🔁 Gõ /play để chơi lại."
        )
        
        game["timeout_task"].cancel()
        del user_games[user_id]

# ========== TRÒ CHƠI PvP ==========
async def pvp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "🎮 Chế độ PvP - Thách đấu người khác\n\n"
            "Cách sử dụng:\n"
            "/pvp @username - Thách đấu người chơi khác\n"
            "/pvp accept - Chấp nhận thách đấu\n"
            "/pvp cancel - Hủy thách đấu"
        )
        return
    
    if context.args[0] == "accept":
        if user_id not in pvp_challenges:
            await update.message.reply_text("⚠️ Không có lời mời PvP nào đang chờ bạn.")
            return
            
        game_id, challenge = next((k, v) for k, v in pvp_challenges.items() if v.opponent_id == user_id)
        challenger_id = challenge.challenger_id
        
        # Tạo game PvP
        level = min(
            get_level(get_player(challenger_id)["score"]),
            get_level(get_player(user_id)["score"])
        )
        diff = get_difficulty(level)
        
        pvp_game = PvPGame(challenger_id, user_id, diff)
        pvp_challenges[game_id] = pvp_game
        task = asyncio.create_task(timeout_pvp_game(game_id, context))
        
        await context.bot.send_message(
            chat_id=challenger_id,
            text=f"🎮 Trận đấu PvP đã bắt đầu!\n"
                 f"🔢 Phạm vi số: {diff['range'][0]} - {diff['range'][1]}\n"
                 f"💡 Số lượt đoán mỗi người: {diff['attempts']}\n\n"
                 f"Gửi số bạn đoán ngay bây giờ!"
        )
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎮 Trận đấu PvP đã bắt đầu!\n"
                 f"🔢 Phạm vi số: {diff['range'][0]} - {diff['range'][1]}\n"
                 f"💡 Số lượt đoán mỗi người: {diff['attempts']}\n\n"
                 f"Gửi số bạn đoán ngay bây giờ!"
        )
        
        return
    
    elif context.args[0] == "cancel":
        # Hủy thách đấu
        pass
    
    else:
        # Thách đấu người khác
        pass

# ========== CỬA HÀNG ==========
async def show_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    
    keyboard = [
        [InlineKeyboardButton("Vật phẩm trò chơi", callback_data="shop_game")],
        [InlineKeyboardButton("Gợi ý", callback_data="shop_hint")],
        [InlineKeyboardButton("Bonus", callback_data="shop_bonus")],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🛒 CỬA HÀNG - Điểm hiện có: {player['score']}\n"
        "Chọn danh mục:",
        reply_markup=reply_markup
    )

async def shop_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    player = get_player(user_id)
    category = query.data.split("_")[1]
    
    items = {k: v for k, v in SHOP_ITEMS.items() if v["type"] == category}
    
    if not items:
        await query.edit_message_text("⚠️ Không có vật phẩm nào trong danh mục này.")
        return
    
    buttons = []
    for item_id, item in items.items():
        buttons.append([
            InlineKeyboardButton(
                f"{item['desc']} - {item['price']} điểm",
                callback_data=f"buy_{item_id}"
            )
        ])
    
    buttons.append([InlineKeyboardButton("🔙 Quay lại", callback_data="shop_back")])
    
    await query.edit_message_text(
        f"🛒 Danh mục {category.capitalize()} - Điểm hiện có: {player['score']}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def buy_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    item_id = query.data.split("_")[1]
    player = get_player(user_id)
    
    if item_id not in SHOP_ITEMS:
        await query.edit_message_text("⚠️ Vật phẩm không tồn tại.")
        return
    
    item = SHOP_ITEMS[item_id]
    
    if player["score"] < item["price"]:
        await query.edit_message_text("❌ Bạn không đủ điểm để mua vật phẩm này.")
        return
    
    player["score"] -= item["price"]
    player["inventory"][item_id] = player["inventory"].get(item_id, 0) + 1
    
    # Xử lý vật phẩm đặc biệt
    if item_id == "double_points":
        player.setdefault("active_bonuses", {})["double_points"] = 3
    
    save_data()
    
    await query.edit_message_text(
        f"✅ Đã mua {item['desc']} thành công!\n"
        f"💰 Điểm còn lại: {player['score']}"
    )

# ========== QUÀ HÀNG NGÀY ==========
async def daily_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    
    today = datetime.now().date().isoformat()
    last_reward = player.get("last_reward_date")
    
    if last_reward == today:
        await update.message.reply_text("⚠️ Bạn đã nhận quà hôm nay rồi!")
        return
    
    # Tính streak
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    if last_reward == yesterday:
        streak = player.get("reward_streak", 0) + 1
    else:
        streak = 1
    
    # Tính điểm thưởng
    reward = DAILY_REWARD_BASE + min(streak * 5, DAILY_REWARD_BASE * 2)
    player["score"] += reward
    player["last_reward_date"] = today
    player["reward_streak"] = streak
    
    # Kiểm tra nhiệm vụ streak
    await check_quests(user_id, context, "daily_streak", 1)
    
    save_data()
    
    await update.message.reply_text(
        f"🎁 Nhận {reward} điểm thưởng hàng ngày!\n"
        f"🔥 Streak nhận quà: {streak} ngày\n"
        f"💰 Tổng điểm: {player['score']}"
    )

# ========== THỐNG KÊ ==========
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    
    win_rate = (player["wins"] / player["games_played"] * 100) if player["games_played"] > 0 else 0
    pvp_win_rate = (player["pvp_wins"] / (player["pvp_wins"] + player["pvp_losses"]) * 100) if (player["pvp_wins"] + player["pvp_losses"]) > 0 else 0
    
    await update.message.reply_text(
        f"📊 THỐNG KÊ CÁ NHÂN\n\n"
        f"🏆 Điểm: {player['score']} (Cấp {get_level(player['score'])})\n"
        f"🎮 Tổng ván chơi: {player['games_played']}\n"
        f"✅ Thắng: {player['wins']} | ❌ Thua: {player['losses']} | 📈 Tỉ lệ: {win_rate:.1f}%\n"
        f"🔥 Streak hiện tại: {player.get('current_streak', 0)} | 🏅 Max streak: {player.get('max_streak', 0)}\n\n"
        f"⚔️ PvP:\n"
        f"🥇 Thắng: {player.get('pvp_wins', 0)} | 🥈 Thua: {player.get('pvp_losses', 0)} | 📈 Tỉ lệ: {pvp_win_rate:.1f}%\n\n"
        f"🎒 Vật phẩm: {sum(player.get('inventory', {}).values())}\n"
        f"📅 Streak nhận quà: {player.get('reward_streak', 0)}/{MAX_DAILY_STREAK}"
    )

# ========== BẢNG XẾP HẠNG ==========
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Lấy top 10 người chơi
    top_players = sorted(
        [(uid, data) for uid, data in players_data.items() if "score" in data],
        key=lambda x: x[1]["score"],
        reverse=True
    )[:10]
    
    message = "🏆 BẢNG XẾP HẠNG TOP 10\n\n"
    for i, (uid, pdata) in enumerate(top_players, 1):
        try:
            user = await context.bot.get_chat(int(uid))
            name = user.username or user.first_name
        except:
            name = f"Người chơi {uid[-4:]}"
        
        message += (
            f"{i}. {name} - {pdata['score']} điểm\n"
            f"   ✅ {pdata.get('wins', 0)}W | "
            f"🔥 {pdata.get('current_streak', 0)}S | "
            f"⚔️ {pdata.get('pvp_wins', 0)}PvP\n"
        )
    
    await update.message.reply_text(message)

# ========== GỢI Ý ==========
async def give_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_games:
        await update.message.reply_text("⚠️ Bạn không có trò chơi đang hoạt động")
        return
    
    player = get_player(user_id)
    game = user_games[user_id]
    
    # Kiểm tra inventory
    if player["inventory"].get("hint_type", 0) > 0 and "type" not in game["used_hints"]:
        player["inventory"]["hint_type"] -= 1
        hint = "chẵn" if game["secret"] % 2 == 0 else "lẻ"
        game["used_hints"].append("type")
        await update.message.reply_text(f"💡 Gợi ý: Số là {hint}")
    elif player["inventory"].get("hint_range", 0) > 0 and "range" not in game["used_hints"]:
        player["inventory"]["hint_range"] -= 1
        secret = game["secret"]
        lower = max(game["range"][0], secret - 50)
        upper = min(game["range"][1], secret + 50)
        game["used_hints"].append("range")
        await update.message.reply_text(f"💡 Gợi ý: Số nằm trong khoảng {lower}-{upper}")
    else:
        await update.message.reply_text("❌ Bạn không có gợi ý nào hoặc đã sử dụng hết. Mua tại /shop")
    
    save_data()

# ========== MAIN ==========
if __name__ == '__main__':
    load_data()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Lệnh cơ bản
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    
    # Lệnh trò chơi
    app.add_handler(CommandHandler("play", play))
    app.add_handler(CommandHandler("pvp", pvp))
    app.add_handler(CommandHandler("hint", give_hint))
    app.add_handler(CommandHandler("giveup", give_up))
    
    # Lệnh cửa hàng
    app.add_handler(CommandHandler("shop", show_shop))
    app.add_handler(CommandHandler("buy", buy_item))
    app.add_handler(CallbackQueryHandler(shop_category, pattern="^shop_"))
    app.add_handler(CallbackQueryHandler(buy_item, pattern="^buy_"))
    
    # Lệnh thống kê
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("daily", daily_reward))
    
    # Xử lý tin nhắn
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_guess))
    
    logger.info("✅ Bot đang chạy...")
    app.run_polling()

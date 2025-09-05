import re
import sqlite3
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ---------------- Хранилища ---------------- #
tournaments = {}  # {chat_id: {"matches": [], "scorers": {}, "playmakers": {}, "goals_today": {}, "assists_today": {}}}

# ---------------- Вспомогательные функции ---------------- #
def get_chat_data(chat_id):
    if chat_id not in tournaments:
        tournaments[chat_id] = {
            "matches": [],
            "scorers": {},
            "playmakers": {},
            "goals_today": {},
            "assists_today": {},
        }
    return tournaments[chat_id]

def parse_players(scorer_str):
    players = []
    if scorer_str.strip():
        for entry in scorer_str.split(","):
            entry = entry.strip()
            if "+" in entry:
                scorer, assistant = map(str.strip, entry.split("+"))
                players.append((scorer, assistant))
            else:
                players.append((entry, None))
    return players

# ---------------- Команды ---------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚽ Бот запущен! Используйте /result для добавления матча.")

async def result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "❌ Формат: /result Команда1 (Игрок1+Ассистент1, Игрок2) 2-1 Команда2 (Игрок3+Ассистент2)"
        )
        return

    # Используем регулярку для более гибкого разбора
    pattern = r"^(.+?)\s*(\((.*?)\))?\s*(\d+)\s*-\s*(\d+)\s*(.+?)\s*(\((.*?)\))?$"
    match = re.match(pattern, text)
    if not match:
        await update.message.reply_text(
            "⚠️ Неверный формат! Пример: /result Барса (Месси+Хави, Неймар) 2-1 Реал (Роналду+Бензема)"
        )
        return

    team1_name = match.group(1).strip()
    team1_players = match.group(3) or ""
    score1 = int(match.group(4))
    score2 = int(match.group(5))
    team2_name = match.group(6).strip()
    team2_players = match.group(8) or ""

    # Сохраняем матч для undo
    data["matches"].append((team1_name, score1, team2_name, score2, team1_players, team2_players))

    # Обработка игроков и ассистов
    for scorer, assistant in parse_players(team1_players) + parse_players(team2_players):
        if scorer:
            data["scorers"][scorer] = data["scorers"].get(scorer, 0) + 1
            data["goals_today"][scorer] = data["goals_today"].get(scorer, 0) + 1
        if assistant:
            data["playmakers"][assistant] = data["playmakers"].get(assistant, 0) + 1
            data["assists_today"][assistant] = data["assists_today"].get(assistant, 0) + 1

    await update.message.reply_text("✅ Результат добавлен!")

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    if not data["matches"]:
        await update.message.reply_text("⚠️ Нет матчей для отмены.")
        return

    last_match = data["matches"].pop()
    team1, score1, team2, score2, rest1, rest2 = last_match

    # Убираем очки из таблицы
    def remove_players(players_str):
        for scorer, assistant in parse_players(players_str):
            if scorer and scorer in data["scorers"]:
                data["scorers"][scorer] -= 1
                data["goals_today"][scorer] -= 1
                if data["scorers"][scorer] <= 0:
                    del data["scorers"][scorer]
                if data["goals_today"][scorer] <= 0:
                    del data["goals_today"][scorer]
            if assistant and assistant in data["playmakers"]:
                data["playmakers"][assistant] -= 1
                data["assists_today"][assistant] -= 1
                if data["playmakers"][assistant] <= 0:
                    del data["playmakers"][assistant]
                if data["assists_today"][assistant] <= 0:
                    del data["assists_today"][assistant]

    remove_players(rest1)
    remove_players(rest2)
    await update.message.reply_text("↩️ Последний матч отменён!")

async def table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    matches = data["matches"]

    teams = {}

    # Собираем статистику по командам
    for t1, s1, t2, s2, _, _ in matches:
        for t in [t1, t2]:
            if t not in teams:
                teams[t] = {
                    "P": 0, "W": 0, "D": 0, "L": 0,
                    "GF": 0, "GA": 0, "GD": 0,
                    "Pts": 0, "form": []
                }
             
        teams[t1]["GF"] += s1
        teams[t1]["GA"] += s2
        teams[t2]["GF"] += s2
        teams[t2]["GA"] += s1
        teams[t1]["P"] += 1
        teams[t2]["P"] += 1

        if s1 > s2:
            teams[t1]["W"] += 1
            teams[t2]["L"] += 1
            teams[t1]["Pts"] += 3
            teams[t1]["form"].append("W")
            teams[t2]["form"].append("L")
        elif s1 < s2:
            teams[t2]["W"] += 1
            teams[t1]["L"] += 1
            teams[t2]["Pts"] += 3
            teams[t2]["form"].append("W")
            teams[t1]["form"].append("L")
        else:
            teams[t1]["D"] += 1
            teams[t2]["D"] += 1
            teams[t1]["Pts"] += 1
            teams[t2]["Pts"] += 1
            teams[t1]["form"].append("D")
            teams[t2]["form"].append("D")

    text = "🏆 Турнирная таблица:\n"
    text += "📊       И | В-Н-П | З-П | Р | О | Ф\n"

    for t, stats in sorted(teams.items(), key=lambda x: -x[1]["Pts"]):
        gd = stats["GF"] - stats["GA"]
        form_str = "".join(stats["form"][-3:])  # последние 3 матча
        text += f"{t} | {stats['P']} | {stats['W']}-{stats['D']}-{stats['L']} | {stats['GF']}-{stats['GA']} | {gd} | {stats['Pts']} | {form_str}\n"

    await update.message.reply_text(text)

async def goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    text = "⚽ Бомбардиры сегодняшнего турнира:\n"
    for player, goals in sorted(data["goals_today"].items(), key=lambda x: -x[1]):
        text += f"{player}: {goals}\n"
    await update.message.reply_text(text)

async def assists(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    text = "🎯 Ассистенты сегодняшнего турнира:\n"
    for player, assists in sorted(data["assists_today"].items(), key=lambda x: -x[1]):
        text += f"{player}: {assists}\n"
    await update.message.reply_text(text)

async def topscorers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    text = "🏆 Лучшие бомбардиры за все турниры:\n"
    for player, goals in sorted(data["scorers"].items(), key=lambda x: -x[1]):
        text += f"{player}: {goals}\n"
    await update.message.reply_text(text)

async def playmakers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    text = "🥇 Лучшие ассистенты за все турниры:\n"
    for player, assists in sorted(data["playmakers"].items(), key=lambda x: -x[1]):
        text += f"{player}: {assists}\n"
    await update.message.reply_text(text)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    tournaments[chat_id] = {
        "matches": [],
        "scorers": {},
        "playmakers": {},
        "goals_today": {},
        "assists_today": {},
    }
    await update.message.reply_text("♻️ Статистика текущего турнира сброшена.")

async def fullreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_user.id not in [924957374]:  # список админов
        await update.message.reply_text("❌ Команда доступна только админам!")
        return
    if chat_id in tournaments:
        del tournaments[chat_id]
    await update.message.reply_text("🗑 Полная очистка всех данных!")

# ---------------- Запуск ---------------- #
def main():
    app = ApplicationBuilder().token("8483314210:AAED1QC7gkebH4a6HyAsRP436OoZMN5PzIM").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("result", result))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(CommandHandler("table", table))
    app.add_handler(CommandHandler("goals", goals))
    app.add_handler(CommandHandler("assists", assists))
    app.add_handler(CommandHandler("topscorers", topscorers))
    app.add_handler(CommandHandler("playmakers", playmakers))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("fullreset", fullreset))

    app.run_polling()

if __name__ == "__main__":
    main()

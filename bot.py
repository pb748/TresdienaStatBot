import re
import sqlite3
import logging
from datetime import date
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Google Sheets ---
import gspread
from oauth2client.service_account import ServiceAccountCredentials

SCOPE = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
CREDS_FILE = 'json-path'  # вставь путь к JSON ключу сервисного аккаунта
SHEET_NAME = 'file name'       # имя Google Sheet, в котором хранятся игроки

# ---------------- Логирование ---------------- #
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ---------------- Хранилища ---------------- #
tournaments = {}  # {chat_id: {"matches": [], "scorers": {}, "playmakers": {}, "teams": {}}}

# ---------------- Вспомогательные функции ---------------- #
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

def init_db():
    conn = sqlite3.connect("tournament.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            tournament_date TEXT,
            team_name TEXT,
            player_name TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            team1 TEXT,
            team2 TEXT,
            score1 INTEGER,
            score2 INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            player TEXT,
            goals INTEGER,
            assists INTEGER
        )
    """)
    conn.commit()
    conn.close()

def get_chat_data(chat_id):
    if chat_id not in tournaments:
        tournaments[chat_id] = {"matches": [], "scorers": {}, "playmakers": {}, "teams": {}}
    return tournaments[chat_id]

# ---------------- Google Sheets функции ---------------- #
def update_sheet(new_data_goals, new_data_assists):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1

    records = sheet.get_all_records()
    # словарь: имя игрока -> номер строки
    players_in_sheet = {row.get('Player', '').strip(): idx + 2 for idx, row in enumerate(records)}

    for player in set(list(new_data_goals.keys()) + list(new_data_assists.keys())):
        new_goals = new_data_goals.get(player, 0)
        new_assists = new_data_assists.get(player, 0)

        if player in players_in_sheet:
            row_number = players_in_sheet[player]

            # Получаем текущее значение, если пустое — 0
            current_goals = sheet.cell(row_number, 2).value
            current_assists = sheet.cell(row_number, 3).value
            current_goals = int(current_goals) if current_goals and current_goals.isdigit() else 0
            current_assists = int(current_assists) if current_assists and current_assists.isdigit() else 0

            # Прибавляем новые
            sheet.update_cell(row_number, 2, current_goals + new_goals)
            sheet.update_cell(row_number, 3, current_assists + new_assists)
        else:
            # Новый игрок — добавляем
            sheet.append_row([player, new_goals, new_assists])


def get_data_from_sheet():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
    data = sheet.get_all_records()
    scorers = {row['Player']: int(row['Goals']) for row in data if int(row['Goals']) > 0}
    assists = {row['Player']: int(row['Assists']) for row in data if int(row['Assists']) > 0}
    return scorers, assists

# ---------------- Команды ---------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    tournaments[chat_id] = {"matches": [], "scorers": {}, "playmakers": {}, "teams": {}}
    await update.message.reply_text("⚽ Новый турнир запущен! Хорошей игры!")

async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚽ Бот запущен!")

async def teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    if not context.args:
        await update.message.reply_text("❌ Введите список игроков после команды /teams")
        return
    text = update.message.text.partition(" ")[2]
    lines = text.split("\n")
    team_colors = ["🟦","🟩","🟧"]
    current_team_index = -1
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line[0].isdigit() and "." in line:
            number = int(line.split(".",1)[0].strip())
            current_team_index = number-1
            continue
        if 0 <= current_team_index < len(team_colors):
            team = team_colors[current_team_index]
            data["teams"].setdefault(team, []).append(line)
    await update.message.reply_text("✅ Составы сохранены!")

async def result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("❌ Формат: /result Команда1 (Игрок1+Ассистент1, Игрок2) 2-1 Команда2 (Игрок3+Ассистент2)")
        return
    pattern = r"^(.+?)\s*(\((.*?)\))?\s*(\d+)\s*-\s*(\d+)\s*(.+?)\s*(\((.*?)\))?$"
    match = re.match(pattern, text)
    if not match:
        await update.message.reply_text("⚠️ Неверный формат!")
        return
    t1_name = match.group(1).strip()
    t1_players = match.group(3) or ""
    s1 = int(match.group(4))
    s2 = int(match.group(5))
    t2_name = match.group(6).strip()
    t2_players = match.group(8) or ""
    data["matches"].append((t1_name,s1,t2_name,s2,t1_players,t2_players))
    for scorer, assistant in parse_players(t1_players)+parse_players(t2_players):
        if scorer:
            data["scorers"][scorer] = data["scorers"].get(scorer,0)+1
        if assistant:
            data["playmakers"][assistant] = data["playmakers"].get(assistant,0)+1
    await update.message.reply_text("✅ Результат добавлен!")

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    if not data["matches"]:
        await update.message.reply_text("⚠️ Нет матчей для отмены.")
        return

    last_match = data["matches"].pop()
    t1, s1, t2, s2, t1_players, t2_players = last_match

    def remove_players(players_str):
        for scorer, assistant in parse_players(players_str):
            if scorer and scorer in data["scorers"]:
                data["scorers"][scorer] -= 1
                if data["scorers"][scorer] <= 0:
                    del data["scorers"][scorer]
            if assistant and assistant in data["playmakers"]:
                data["playmakers"][assistant] -= 1
                if data["playmakers"][assistant] <= 0:
                    del data["playmakers"][assistant]

    remove_players(t1_players)
    remove_players(t2_players)

    await update.message.reply_text(f"↩️ Последний матч ({t1} {s1}-{s2} {t2}) отменён!")

async def table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    matches = data.get("matches", [])
    if not matches:
        await update.message.reply_text("⚠️ Нет матчей для отображения.")
        return

    teams_stats = {}
    for t1, s1, t2, s2, _, _ in matches:
        for t in [t1,t2]:
            if t not in teams_stats:
                teams_stats[t] = {"P":0,"W":0,"D":0,"L":0,"GF":0,"GA":0,"Pts":0,"form":[]}
        teams_stats[t1]["GF"] += s1
        teams_stats[t1]["GA"] += s2
        teams_stats[t2]["GF"] += s2
        teams_stats[t2]["GA"] += s1
        teams_stats[t1]["P"] += 1
        teams_stats[t2]["P"] += 1

        if s1 > s2:
            teams_stats[t1]["W"] += 1
            teams_stats[t2]["L"] += 1
            teams_stats[t1]["Pts"] += 3
            teams_stats[t1]["form"].append("W")
            teams_stats[t2]["form"].append("L")
        elif s1 < s2:
            teams_stats[t2]["W"] += 1
            teams_stats[t1]["L"] += 1
            teams_stats[t2]["Pts"] += 3
            teams_stats[t2]["form"].append("W")
            teams_stats[t1]["form"].append("L")
        else:
            teams_stats[t1]["D"] += 1
            teams_stats[t2]["D"] += 1
            teams_stats[t1]["Pts"] += 1
            teams_stats[t2]["Pts"] += 1
            teams_stats[t1]["form"].append("D")
            teams_stats[t2]["form"].append("D")

    sorted_teams = sorted(teams_stats.items(), key=lambda x: (-x[1]["Pts"], -(x[1]["GF"]-x[1]["GA"]), -x[1]["GF"]))
    text="🏆 Турнирная таблица:\n 📊 И | В-Н-П | З-П | Р | О | Ф\n"
    for t, stats in sorted_teams:
        gd = stats["GF"] - stats["GA"]
        form_str = "".join(stats["form"][-3:])
        text+=f"{t} | {stats['P']} | {stats['W']}-{stats['D']}-{stats['L']} | {stats['GF']}-{stats['GA']} | {gd} | {stats['Pts']} | {form_str}\n"
    await update.message.reply_text(text)

async def goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    if not data["scorers"]:
        await update.message.reply_text("⚠️ Нет голов.")
        return
    sorted_goals = sorted(data["scorers"].items(),key=lambda x:-x[1])
    text="⚽ Бомбардиры:\n"
    for player,g in sorted_goals:
        text+=f"{player}: {g}\n"
    await update.message.reply_text(text)

async def assists(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    if not data["playmakers"]:
        await update.message.reply_text("⚠️ Нет ассистов.")
        return
    sorted_assists = sorted(data["playmakers"].items(),key=lambda x:-x[1])
    text="🎯 Ассистенты:\n"
    for player,a in sorted_assists:
        text+=f"{player}: {a}\n"
    await update.message.reply_text(text)

async def topscorers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scorers,_ = get_data_from_sheet()
    if not scorers:
        await update.message.reply_text("⚠️ Нет данных о голах.")
        return
    text="⚽ Авторы голов:\n"
    for player,g in sorted(scorers.items(), key=lambda x:-x[1]):
        text+=f"{player}: {g}\n"
    await update.message.reply_text(text)

async def playmakers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _,assists = get_data_from_sheet()
    if not assists:
        await update.message.reply_text("⚠️ Нет данных об ассистах.")
        return
    text="🎯 Ассистенты:\n"
    for player,a in sorted(assists.items(), key=lambda x:-x[1]):
        text+=f"{player}: {a}\n"
    await update.message.reply_text(text)

async def opinion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Составы говно")

async def end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    if not data or not data["matches"]:
        await update.message.reply_text("⚠️ Нет данных для завершения.")
        return

    # Показываем таблицу
    await table(update, context)

    # MVP
    mvp_scores={p:data["scorers"].get(p,0)+data["playmakers"].get(p,0) for p in set(list(data["scorers"].keys())+list(data["playmakers"].keys()))}
    max_mvp=max(mvp_scores.values()) if mvp_scores else 0
    mvps=[p for p,val in mvp_scores.items() if val==max_mvp]
    await update.message.reply_text(f"🔥 MVP турнира: {', '.join(mvps)} (Goals+Assists = {max_mvp})")

    # Голы и ассисты
    await goals(update, context)
    await assists(update, context)

    # Сохраняем в SQLite
    conn = sqlite3.connect("tournament.db")
    cur = conn.cursor()
    tournament_date = str(date.today())
    for team_name,players in data.get("teams",{}).items():
        for p in players:
            cur.execute("INSERT INTO teams (chat_id,tournament_date,team_name,player_name) VALUES (?,?,?,?)",
                        (chat_id,tournament_date,team_name,p))
    for t1,s1,t2,s2,t1p,t2p in data["matches"]:
        cur.execute("INSERT INTO matches (chat_id,team1,team2,score1,score2) VALUES (?,?,?,?,?)", (chat_id,t1,t2,s1,s2))
        match_id = cur.lastrowid
        for scorer,assistant in parse_players(t1p)+parse_players(t2p):
            if scorer: cur.execute("INSERT INTO players (match_id,player,goals,assists) VALUES (?,?,?,?)",(match_id,scorer,1,0))
            if assistant: cur.execute("INSERT INTO players (match_id,player,goals,assists) VALUES (?,?,?,?)",(match_id,assistant,0,1))
    conn.commit()
    conn.close()

    # Обновляем Google Sheets
    update_sheet(data["scorers"], data["playmakers"])
    await update.message.reply_text("✅ Турнир завершён, голы и ассисты обновлены в Google Sheets!")

# ---------------- Запуск ---------------- #
def main():
    init_db()
    app = ApplicationBuilder().token("YOUR_TOKEN").build()

    app.add_handler(CommandHandler("hello", hello))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("teams", teams))
    app.add_handler(CommandHandler("result", result))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(CommandHandler("table", table))
    app.add_handler(CommandHandler("goals", goals))
    app.add_handler(CommandHandler("assists", assists))
    app.add_handler(CommandHandler("end", end))
    app.add_handler(CommandHandler("topscorers", topscorers))
    app.add_handler(CommandHandler("playmakers", playmakers))
    app.add_handler(CommandHandler("opinion", opinion))

    app.run_polling()

if __name__=="__main__":
    main()


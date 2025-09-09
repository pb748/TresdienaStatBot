# Telegram Tournament Bot

## Описание
Бот для проведения турниров, подсчёта статистики игроков (голы и ассисты) и синхронизации данных с Google Sheets.  

## Установка и запуск
1. Клонировать проект или скачать архив с кодом.
2. Создать виртуальное окружение:
   python3 -m venv venv
   source venv/bin/activate
3. Установить зависимости:
   pip install -r requirements.txt
4. Убедиться, что в корне проекта есть файл service_account.json (Google API ключ).
5. Убедиться, что файлы runtime.txt и requirements.txt присутствуют.
6. Запустить бота:
   python3 bot.py

## Переменные и настройки
- В коде задать:
  - `CREDS_FILE` = путь к JSON-ключу Google API (например: "service_account.json")
  - `SHEET_NAME` = название Google Sheet, где хранятся голы и ассисты
  - `BOT_TOKEN` = токен Telegram-бота
  
1. Нужно создать Google Sheet с тремя колонками; A - Player, B - Goals, C - Assists
2. Подключить Google Sheet к коду через Google Cloud

## Требования
- Python 3.11.8
- Google Sheets API доступ (сервисный аккаунт)
- Установленные зависимости из requirements.txt

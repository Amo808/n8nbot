import logging
import requests
from flask import Flask, request, jsonify
import threading
import time
import os

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Хранилище сообщений и таймеров
message_store = {}
timers = {}

# Загружаем вебхуки из переменных окружения
ACCOUNTS = {
    # Формат: "account_id": {"user_webhook": "...", "bot_webhook": "..."}
    os.getenv("ACC_1_ID"): {
        "user_webhook": os.getenv("ACC_1_USER_WEBHOOK"),
        "bot_webhook": os.getenv("ACC_1_BOT_WEBHOOK")
    },
    os.getenv("ACC_2_ID"): {
        "user_webhook": os.getenv("ACC_2_USER_WEBHOOK"),
        "bot_webhook": os.getenv("ACC_2_BOT_WEBHOOK")
    },
}

def send_to_target(data, url):
    """Отправка данных на целевой сервер."""
    if not url:
        logger.warning("Вебхук не задан.")
        return
    try:
        response = requests.post(url, json={"messages": data})
        response.raise_for_status()
        logger.info(f"Данные успешно отправлены на {url}.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при отправке данных на {url}: {e}")

def process_user_messages(sender_id, user_webhook):
    """Ждет 15 секунд и отправляет накопленные сообщения пользователя."""
    try:
        time.sleep(15)
        if sender_id in message_store and message_store[sender_id]:
            send_to_target(message_store.pop(sender_id, []), user_webhook)
        timers.pop(sender_id, None)
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщений пользователя {sender_id}: {e}")

@app.route("/", methods=["POST"])
def home():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Empty or invalid request body"}), 400

        logger.info(f"Получены данные: {data}")

        for message in data.get("entry", [{}])[0].get("messaging", []):
            sender_id = message.get("sender", {}).get("id")
            recipient_id = message.get("recipient", {}).get("id")
            is_echo = message.get("message", {}).get("is_echo", False)

            if not sender_id:
                continue

            # Определяем аккаунт по recipient_id
            account = ACCOUNTS.get(recipient_id)
            if not account:
                logger.warning(f"Аккаунт с ID {recipient_id} не найден.")
                continue

            user_webhook = account.get("user_webhook")
            bot_webhook = account.get("bot_webhook")

            # Если сообщение от бота (is_echo) или менеджера
            if sender_id == recipient_id or is_echo:
                send_to_target([data], bot_webhook)
            else:
                # Сообщение от пользователя
                message_store.setdefault(sender_id, []).append(data)
                if sender_id not in timers:
                    timers[sender_id] = threading.Thread(target=process_user_messages, args=(sender_id, user_webhook))
                    timers[sender_id].daemon = True
                    timers[sender_id].start()

        return jsonify({"status": "success", "data": data}), 200
    except Exception as e:
        logger.error(f"Ошибка при обработке данных: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/", methods=["GET"])
def get():
    return "Сервер работает! Отправьте POST-запрос на / для тестирования."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
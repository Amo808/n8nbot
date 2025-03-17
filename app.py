import logging
import requests
from flask import Flask, request, jsonify
import threading
import time

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

USER_WEBHOOK = "https://n8n-e66f.onrender.com/webhook/d6cbc19f-5140-4791-8fd8-c9cb901c90c7"
BOT_WEBHOOK = "https://n8n-e66f.onrender.com/webhook/a392f54a-ee58-4fe8-a951-359602f5ec70"
TEST_WEBHOOK = "https://n8n-e66f.onrender.com/webhook-test/d6cbc19f-5140-4791-8fd8-c9cb901c90c7"
AMO_WEBHOOK = "https://n8n-e66f.onrender.com/webhook/d6cbc19f-5140-4791-8fd8-c9cb901c90c7"  # Вебхук для первого сообщения из Amo

message_store = {}
timers = {}
recent_messages = {}  # Кэш для проверки дублей

DUPLICATE_TIMEOUT = 2  # Время, в течение которого дубли игнорируются (в секундах)

def is_duplicate(sender_id, message_text):
    """Проверяет, является ли сообщение дубликатом."""
    current_time = time.time()
    if sender_id in recent_messages:
        last_message, last_time = recent_messages[sender_id]
        if last_message == message_text and (current_time - last_time) < DUPLICATE_TIMEOUT:
            return True  # Дубликат найден
    recent_messages[sender_id] = (message_text, current_time)  # Обновляем кэш
    return False

def send_to_target(data, url):
    """Отправка данных на целевой сервер."""
    try:
        response = requests.post(url, json={"messages": data})
        response.raise_for_status()
        logger.info(f"Данные успешно отправлены на {url}.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при отправке данных на {url}: {e}")
        if response is not None:
            logger.error(f"Ответ сервера: {response.text}")

def process_user_messages(sender_id):
    """Ждет 15 секунд и отправляет накопленные сообщения пользователя."""
    try:
        time.sleep(60)
        if sender_id in message_store and message_store[sender_id]:
            send_to_target(message_store.pop(sender_id, []), USER_WEBHOOK)
            send_to_target(message_store.pop(sender_id, []), TEST_WEBHOOK)  # Отправка на тестовый вебхук
        timers.pop(sender_id, None)
    except Exception as e:
        logger.error(f"Ошибка в обработке сообщений пользователя {sender_id}: {e}")

@app.route("/", methods=["POST"])
def home():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Empty or invalid request body"}), 400

        logger.info(f"Получены данные: {data}")

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "comments":
                    comment_data = change.get("value")
                    sender_id = comment_data.get("from", {}).get("id")
                    comment_text = comment_data.get("text")

                    logger.info(f"Комментарий от {sender_id}: {comment_text}")

                    send_to_target([comment_data], USER_WEBHOOK)
                    send_to_target([comment_data], TEST_WEBHOOK)  # Если тестируете

            for message in entry.get("messaging", []):
                sender_id = message.get("sender", {}).get("id")
                recipient_id = message.get("recipient", {}).get("id")
                message_text = message.get("message", {}).get("text", "")
                is_echo = message.get("message", {}).get("is_echo", False)

                if not sender_id:
                    continue

                # Проверяем, не является ли сообщение дубликатом
                if is_duplicate(sender_id, message_text):
                    logger.info(f"Дубликат сообщения от {sender_id}, игнорируем: {message_text}")
                    continue

                # Обработка сообщений бота или менеджера
                if sender_id == recipient_id or is_echo:
                    send_to_target([data], BOT_WEBHOOK)
                    send_to_target([data], TEST_WEBHOOK)
                else:
                    logger.info(f"Сообщение от пользователя {sender_id}: {message}")

                    message_store.setdefault(sender_id, []).append(data)

                    if sender_id not in timers:
                        timers[sender_id] = threading.Thread(target=process_user_messages, args=(sender_id,))
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

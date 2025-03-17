import logging
import requests
from flask import Flask, request, jsonify
import threading
import time
import json

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Вебхуки
USER_WEBHOOK = "https://n8n-e66f.onrender.com/webhook/d6cbc19f-5140-4791-8fd8-c9cb901c90c7"
BOT_WEBHOOK = "https://n8n-e66f.onrender.com/webhook/a392f54a-ee58-4fe8-a951-359602f5ec70"
TEST_WEBHOOK = "https://n8n-e66f.onrender.com/webhook-test/d6cbc19f-5140-4791-8fd8-c9cb901c90c7"
AMO_WEBHOOK = "https://n8n-e66f.onrender.com/webhook/d6cbc19f-5140-4791-8fd8-c9cb901c90c7"

# Хранилище сообщений и таймеров
message_store = {}
timers = {}
recent_messages = {}

DUPLICATE_TIMEOUT = 5  # Фильтр дублей (секунды)

def is_duplicate(sender_id, message_text):
    """Проверяет, является ли сообщение дубликатом."""
    current_time = time.time()
    if sender_id in recent_messages:
        last_message, last_time = recent_messages[sender_id]
        if last_message == message_text and (current_time - last_time) < DUPLICATE_TIMEOUT:
            return True
    recent_messages[sender_id] = (message_text, current_time)
    return False

def send_to_target(data, url):
    """Отправка данных на целевой сервер."""
    try:
        response = requests.post(url, json={"messages": data})
        response.raise_for_status()
        logger.info(f"✅ Данные отправлены на {url}.")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Ошибка отправки данных на {url}: {e}")

def extract_text(data):
    """Рекурсивный поиск текста в JSON-структуре."""
    if isinstance(data, dict):
        if "text" in data:
            return data["text"]
        for value in data.values():
            result = extract_text(value)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = extract_text(item)
            if result:
                return result
    return None

def process_user_messages(sender_id):
    """Ждет 60 секунд и отправляет накопленные сообщения."""
    try:
        time.sleep(60)
        if sender_id in message_store and message_store[sender_id]:
            messages = message_store.pop(sender_id, [])
            send_to_target(messages, USER_WEBHOOK)
            send_to_target(messages, TEST_WEBHOOK)
        timers.pop(sender_id, None)
    except Exception as e:
        logger.error(f"❌ Ошибка в обработке сообщений {sender_id}: {e}")

@app.route("/", methods=["POST"])
def home():
    try:
        # Определяем тип контента
        if request.content_type == "application/json":
            data = request.get_json()
        elif request.content_type == "application/x-www-form-urlencoded":
            data = request.form.to_dict(flat=False)
            json_str = json.dumps(data)
            data = json.loads(json_str)
        else:
            return jsonify({"status": "error", "message": f"Unsupported Content-Type: {request.content_type}"}), 415

        if not data:
            return jsonify({"status": "error", "message": "Empty or invalid request body"}), 400

        logger.info(f"📩 Получены данные: {data}")

        # Проверяем, AmoCRM ли это
        if "unsorted[add][0][source_data][source]" in str(data):
            send_to_target(data, AMO_WEBHOOK)
            return jsonify({"status": "success", "message": "AmoCRM data processed"}), 200

        # Обработка входящих сообщений
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                comment_data = change.get("value", {})
                sender_id = comment_data.get("from", {}).get("id")
                comment_text = extract_text(comment_data)

                if sender_id and comment_text:
                    logger.info(f"💬 Комментарий от {sender_id}: {comment_text}")
                    send_to_target([comment_data], USER_WEBHOOK)
                    send_to_target([comment_data], TEST_WEBHOOK)

            for message in entry.get("messaging", []):
                sender_id = message.get("sender", {}).get("id")
                recipient_id = message.get("recipient", {}).get("id")
                message_text = extract_text(message)

                if not sender_id or not message_text:
                    continue

                if is_duplicate(sender_id, message_text):
                    logger.info(f"⚠️ Дубликат сообщения от {sender_id}, игнорируем: {message_text}")
                    continue

                if sender_id == recipient_id or message.get("message", {}).get("is_echo", False):
                    send_to_target([data], BOT_WEBHOOK)
                    send_to_target([data], TEST_WEBHOOK)
                else:
                    logger.info(f"📨 Сообщение от пользователя {sender_id}: {message_text}")
                    message_store.setdefault(sender_id, []).append(data)
                    if sender_id not in timers:
                        timers[sender_id] = threading.Thread(target=process_user_messages, args=(sender_id,))
                        timers[sender_id].daemon = True
                        timers[sender_id].start()

        return jsonify({"status": "success", "data": data}), 200
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке данных: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/", methods=["GET"])
def get():
    return "Сервер работает! Отправьте POST-запрос на / для тестирования."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

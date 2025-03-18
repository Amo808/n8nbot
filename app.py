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
WEBHOOKS = {
    "user": "https://n8n-e66f.onrender.com/webhook/d6cbc19f-5140-4791-8fd8-c9cb901c90c7",
    "bot": "https://n8n-e66f.onrender.com/webhook/a392f54a-ee58-4fe8-a951-359602f5ec70",
    "test": "https://n8n-e66f.onrender.com/webhook-test/d6cbc19f-5140-4791-8fd8-c9cb901c90c7",
    "amo": "https://n8n-e66f.onrender.com/webhook/d6cbc19f-5140-4791-8fd8-c9cb901c90c7"
}

# Хранилище сообщений и таймеров
message_store = {}
timers = {}
recent_messages = {}
DUPLICATE_TIMEOUT = 5  # Секунды защиты от дубликатов

def is_duplicate(sender_id, message_id, message_text):
    """Проверяет, является ли сообщение дубликатом."""
    current_time = time.time()
    last_message = recent_messages.get(sender_id, {})

    if (
        last_message.get("id") == message_id or
        (last_message.get("text") == message_text and (current_time - last_message.get("time", 0)) < DUPLICATE_TIMEOUT)
    ):
        logger.info(f"🔄 Дубликат найден! ID: {message_id}, текст: {message_text}")
        return True

    recent_messages[sender_id] = {"id": message_id, "text": message_text, "time": current_time}
    return False

def send_to_target(data, webhook):
    """Отправка данных на целевой сервер."""
    try:
        response = requests.post(webhook, json={"messages": data})
        response.raise_for_status()
        logger.info(f"✅ Данные отправлены на {webhook}.")
    except requests.RequestException as e:
        logger.error(f"❌ Ошибка отправки данных на {webhook}: {e}")

def extract_text(data):
    """Рекурсивный поиск текста в JSON."""
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
    """Отложенная отправка накопленных сообщений."""
    time.sleep(60)
    if sender_id in message_store:
        messages = message_store.pop(sender_id, [])
        send_to_target(messages, WEBHOOKS["user"])
        send_to_target(messages, WEBHOOKS["test"])
    timers.pop(sender_id, None)

def handle_amo_crm(data):
    """Обработка данных из AmoCRM."""
    send_to_target(data, WEBHOOKS["amo"])
    return jsonify({"status": "success", "message": "AmoCRM data processed"}), 200

def handle_instagram(data):
    """Обработка сообщений из Instagram."""
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            comment_data = change.get("value", {})
            sender_id = comment_data.get("from", {}).get("id")
            message_id = comment_data.get("mid")
            message_text = extract_text(comment_data)
            
            if sender_id and message_text and not is_duplicate(sender_id, message_id, message_text):
                message_store.setdefault(sender_id, []).append(comment_data)
                if sender_id not in timers:
                    timers[sender_id] = threading.Thread(target=process_user_messages, args=(sender_id,))
                    timers[sender_id].daemon = True
                    timers[sender_id].start()

        for message in entry.get("messaging", []):
            sender_id = message.get("sender", {}).get("id")
            message_id = message.get("message", {}).get("mid")
            message_text = extract_text(message)
            
            if sender_id and message_text and not is_duplicate(sender_id, message_id, message_text):
                if message.get("message", {}).get("is_echo", False):
                    send_to_target([data], WEBHOOKS["bot"])
                    send_to_target([data], WEBHOOKS["test"])
                else:
                    message_store.setdefault(sender_id, []).append(data)
                    if sender_id not in timers:
                        timers[sender_id] = threading.Thread(target=process_user_messages, args=(sender_id,))
                        timers[sender_id].daemon = True
                        timers[sender_id].start()
    return jsonify({"status": "success", "data": data}), 200

@app.route("/", methods=["POST"])
def home():
    try:
        data = request.get_json() if request.content_type == "application/json" else None
        if not data:
            return jsonify({"status": "error", "message": "Empty or invalid request body"}), 400
        
        logger.info(f"📩 Получены данные: {data}")
        
        if "unsorted[add][0][source_data][source]" in str(data):
            return handle_amo_crm(data)
        
        return handle_instagram(data)
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке данных: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/", methods=["GET"])
def get():
    return "Сервер работает! Отправьте POST-запрос на / для тестирования."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

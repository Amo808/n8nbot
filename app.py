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

message_store = {}
timers = {}
recent_messages = {}
DUPLICATE_TIMEOUT = 5  # Таймаут для фильтрации дублей


def is_duplicate(sender_id, message_text):
    """Проверяет, является ли сообщение дубликатом."""
    current_time = time.time()
    last_message, last_time = recent_messages.get(sender_id, (None, 0))
    
    if last_message == message_text and (current_time - last_time) < DUPLICATE_TIMEOUT:
        return True
    
    recent_messages[sender_id] = (message_text, current_time)
    return False


def send_to_target(data, url):
    """Отправка данных на целевой сервер."""
    try:
        response = requests.post(url, json={"messages": data})
        response.raise_for_status()
        logger.info(f"Данные успешно отправлены на {url}.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при отправке данных на {url}: {e}")


def process_user_messages(sender_id):
    """Ждет 60 секунд и отправляет накопленные сообщения."""
    time.sleep(60)
    if sender_id in message_store and message_store[sender_id]:
        send_to_target(message_store.pop(sender_id, []), WEBHOOKS["user"])
        send_to_target(message_store.pop(sender_id, []), WEBHOOKS["test"])
    timers.pop(sender_id, None)


def extract_text(data):
    """Извлекает текст сообщения из всех возможных мест."""
    if isinstance(data, dict):
        if "text" in data:
            return data["text"]
        for value in data.values():
            extracted = extract_text(value)
            if extracted:
                return extracted
    elif isinstance(data, list):
        for item in data:
            extracted = extract_text(item)
            if extracted:
                return extracted
    return ""


@app.route("/", methods=["POST"])
def home():
    try:
        data = request.get_json() or json.loads(json.dumps(request.form.to_dict(flat=False)))
        if not data:
            return jsonify({"status": "error", "message": "Empty or invalid request body"}), 400

        logger.info(f"Получены данные: {data}")

        # Проверяем формат данных AmoCRM
        if isinstance(data, dict) and "unsorted" in data:
            unsorted_list = data.get("unsorted", [])
            if unsorted_list and isinstance(unsorted_list[0], dict):
                source_data = unsorted_list[0].get("source_data", {})
                if "source" in source_data:
                    send_to_target(data, WEBHOOKS["amo"])
                    return jsonify({"status": "success", "message": "AmoCRM data processed"}), 200

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "comments":
                    comment_data = change.get("value", {})
                    sender_id = comment_data.get("from", {}).get("id")
                    logger.info(f"Комментарий от {sender_id}: {comment_data}")
                    send_to_target([comment_data], WEBHOOKS["user"])
                    send_to_target([comment_data], WEBHOOKS["test"])

            for message in entry.get("messaging", []):
                sender_id = message.get("sender", {}).get("id")
                recipient_id = message.get("recipient", {}).get("id")
                is_echo = message.get("message", {}).get("is_echo", False)
                message_text = extract_text(message)

                if not sender_id:
                    continue

                if is_duplicate(sender_id, message_text):
                    logger.info(f"Дубликат сообщения от {sender_id}, игнорируем: {message_text}")
                    continue

                if sender_id == recipient_id or is_echo:
                    send_to_target([data], WEBHOOKS["bot"])
                    send_to_target([data], WEBHOOKS["test"])
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

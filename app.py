import logging
import requests
from flask import Flask, request, jsonify
import threading
import time
import json

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

USER_WEBHOOK = "https://n8n-e66f.onrender.com/webhook/d6cbc19f-5140-4791-8fd8-c9cb901c90c7"
BOT_WEBHOOK = "https://n8n-e66f.onrender.com/webhook/a392f54a-ee58-4fe8-a951-359602f5ec70"
TEST_WEBHOOK = "https://n8n-e66f.onrender.com/webhook-test/d6cbc19f-5140-4791-8fd8-c9cb901c90c7"
AMO_WEBHOOK = "https://n8n-e66f.onrender.com/webhook/d6cbc19f-5140-4791-8fd8-c9cb901c90c7"

message_store = {}
timers = {}
recent_messages = {}

DUPLICATE_TIMEOUT = 5  # Таймаут для фильтрации дублей


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
        logger.info(f"Данные успешно отправлены на {url}.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при отправке данных на {url}: {e}")


def process_user_messages(sender_id):
    """Ждет 60 секунд и отправляет накопленные сообщения."""
    try:
        time.sleep(60)
        if sender_id in message_store and message_store[sender_id]:
            send_to_target(message_store.pop(sender_id, []), USER_WEBHOOK)
            send_to_target(message_store.pop(sender_id, []), TEST_WEBHOOK)
        timers.pop(sender_id, None)
    except Exception as e:
        logger.error(f"Ошибка в обработке сообщений пользователя {sender_id}: {e}")


def find_text_fields(data):
    """Рекурсивно ищет все значения с ключом 'text' в JSON."""
    texts = []

    if isinstance(data, dict):
        for key, value in data.items():
            if key == "text" and isinstance(value, (str, list)):
                if isinstance(value, list):
                    texts.extend(value)
                else:
                    texts.append(value)
            else:
                texts.extend(find_text_fields(value))
    elif isinstance(data, list):
        for item in data:
            texts.extend(find_text_fields(item))

    return texts


@app.route("/", methods=["POST"])
def home():
    try:
        # Обрабатываем разные форматы контента
        if request.content_type == "application/x-www-form-urlencoded":
            form_data = request.form.to_dict(flat=False)
            json_str = json.dumps(form_data)
            data = json.loads(json_str)
        else:
            data = request.get_json()

        if not data:
            return jsonify({"status": "error", "message": "Empty or invalid request body"}), 400

        logger.info(f"Получены данные: {data}")

        # Проверяем формат данных AmoCRM
        if "unsorted[add][0][source_data][source]" in data:
            send_to_target(data, AMO_WEBHOOK)
            return jsonify({"status": "success", "message": "AmoCRM data processed"}), 200

        # Ищем все текстовые сообщения в JSON
        text_messages = find_text_fields(data)

        if not text_messages:
            logger.info("Текстовые сообщения не найдены, игнорируем запрос.")
            return jsonify({"status": "ignored", "message": "No text fields found"}), 200

        sender_id = data.get("entry", [{}])[0].get("messaging", [{}])[0].get("sender", {}).get("id", "unknown")

        # Фильтрация дубликатов
        for text in text_messages:
            if is_duplicate(sender_id, text):
                logger.info(f"Дубликат сообщения от {sender_id}, игнорируем: {text}")
                continue

            # Отправка данных
            message_store.setdefault(sender_id, []).append({"sender_id": sender_id, "text": text})
            if sender_id not in timers:
                timers[sender_id] = threading.Thread(target=process_user_messages, args=(sender_id,))
                timers[sender_id].daemon = True
                timers[sender_id].start()

        return jsonify({"status": "success", "data": text_messages}), 200

    except Exception as e:
        logger.error(f"Ошибка при обработке данных: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/", methods=["GET"])
def get():
    return "Сервер работает! Отправьте POST-запрос на / для тестирования."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

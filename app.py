import logging
import requests
from flask import Flask, request, jsonify
import threading
import time

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Вебхуки для отправки данных
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
DUPLICATE_TIMEOUT = 5  # Защита от дубликатов (секунды)
PROCESS_DELAY = 60  # Время ожидания перед отправкой (секунды)


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
        if "text" in data and isinstance(data["text"], str):
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


def process_user_messages(sender_id, webhook_key):
    """Отложенная отправка накопленных сообщений."""
    time.sleep(PROCESS_DELAY)
    if sender_id in message_store:
        messages = message_store.pop(sender_id, [])
        send_to_target(messages, WEBHOOKS[webhook_key])
        send_to_target(messages, WEBHOOKS["test"])
    timers.pop(sender_id, None)


@app.route("/", methods=["POST"])
def handle_amo_webhook():
    """Обработка входящих вебхуков от amoCRM."""
    try:
        data = request.json
        logger.info(f"📩 Получены данные: {data}")

        # Извлекаем UID и текст сообщения
        sender_id = data.get("unsorted[add][0][source_data][client][id]", [""])[0]
        message_id = data.get("unsorted[add][0][source_data][data][0][id]", [""])[0]
        message_text = extract_text(data.get("unsorted[add][0][source_data][data]", []))

        if not sender_id or not message_text:
            logger.warning("⚠️ Сообщение без ID или текста, пропускаем...")
            return jsonify({"status": "ignored"}), 200

        # Проверка на дубликат
        if is_duplicate(sender_id, message_id, message_text):
            return jsonify({"status": "duplicate"}), 200

        # Добавляем в хранилище сообщений
        if sender_id not in message_store:
            message_store[sender_id] = []
        message_store[sender_id].append({"id": message_id, "text": message_text})

        # Запускаем таймер для отложенной отправки
        if sender_id not in timers:
            timers[sender_id] = threading.Thread(target=process_user_messages, args=(sender_id, "user"))
            timers[sender_id].start()

        return jsonify({"status": "received"}), 200

    except Exception as e:
        logger.error(f"❌ Ошибка обработки вебхука: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

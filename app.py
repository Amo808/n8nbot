import logging
import requests
from flask import Flask, request, jsonify
import threading
import time
import json

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WEBHOOKS = {
    "user": "https://n8n-e66f.onrender.com/webhook/d6cbc19f-5140-4791-8fd8-c9cb901c90c7",
    "bot": "https://n8n-e66f.onrender.com/webhook/a392f54a-ee58-4fe8-a951-359602f5ec70",
    "amo": "https://n8n-e66f.onrender.com/webhook/d6cbc19f-5140-4791-8fd8-c9cb901c90c7"
}

message_store = {}
timers = {}
recent_messages = {}
DUPLICATE_TIMEOUT = 5  # Защита от дубликатов
PROCESS_DELAY = 10  # Ожидание перед отправкой


def is_duplicate(sender_id, message_id, message_text):
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
    try:
        response = requests.post(webhook, json={"messages": data})
        response.raise_for_status()
        logger.info(f"✅ Данные отправлены на {webhook}.")
    except requests.RequestException as e:
        logger.error(f"❌ Ошибка отправки данных на {webhook}: {e}")


def process_messages(sender_id, webhook_key):
    time.sleep(PROCESS_DELAY)
    if sender_id in message_store:
        messages = message_store.pop(sender_id, [])
        send_to_target(messages, WEBHOOKS[webhook_key])
    timers.pop(sender_id, None)


def handle_instagram(data):
    for entry in data.get("entry", []):
        for message_event in entry.get("messaging", []):
            sender_id = message_event.get("sender", {}).get("id")
            message_id = message_event.get("message", {}).get("mid")
            message_text = message_event.get("message", {}).get("text", "")
            is_echo = message_event.get("message", {}).get("is_echo", False)

            if sender_id and message_text and not is_echo and not is_duplicate(sender_id, message_id, message_text):
                message_store.setdefault(sender_id, []).append({"id": message_id, "text": message_text})
                if sender_id not in timers:
                    timers[sender_id] = threading.Thread(target=process_messages, args=(sender_id, "user"))
                    timers[sender_id].daemon = True
                    timers[sender_id].start()

    return jsonify({"status": "success", "data": data}), 200


def handle_amo_crm(data):
    sender_id = data.get("unsorted[add][0][source_data][contact][id]", "amo")
    
    if sender_id not in message_store:
        message_store[sender_id] = []
    
    message_store[sender_id].append(data)
    
    if sender_id not in timers:
        timers[sender_id] = threading.Thread(target=process_messages, args=(sender_id, "amo"))
        timers[sender_id].daemon = True
        timers[sender_id].start()
    
    return jsonify({"status": "success", "message": "AmoCRM data received"}), 200


@app.route("/", methods=["POST"])
def home():
    try:
        data = request.get_json() if request.content_type == "application/json" else json.loads(json.dumps(request.form.to_dict(flat=False)))
        
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

import logging
import requests
from flask import Flask, request, jsonify
import threading
import time

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

USER_WEBHOOK = "https://therealclock.app.n8n.cloud/webhook/7a70ac3d-fed3-45de-a72b-384f3dd07dff"
BOT_WEBHOOK = "https://therealclock.app.n8n.cloud/webhook/15e66f8f-69a9-4dcc-b523-eac0e4bdb4a1"

message_store = {}
timers = {}

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
        time.sleep(15)
        if sender_id in message_store and message_store[sender_id]:
            send_to_target(message_store.pop(sender_id, []), USER_WEBHOOK)
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

        for message in data.get("entry", [{}])[0].get("messaging", []):
            sender_id = message.get("sender", {}).get("id")
            recipient_id = message.get("recipient", {}).get("id")
            is_echo = message.get("message", {}).get("is_echo", False)

            if not sender_id:
                continue

            # Обработка сообщений бота или менеджера
            if sender_id == recipient_id or is_echo:
                send_to_target([data], BOT_WEBHOOK)
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
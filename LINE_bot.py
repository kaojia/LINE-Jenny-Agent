from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from openai import OpenAI
from dotenv import load_dotenv
import os
import re
from difflib import SequenceMatcher
import requests

app = Flask(__name__)

# 🔹 載入環境變數
load_dotenv()

app = Flask(__name__)

# 🔹 讀取金鑰
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

# 初始化
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
client = OpenAI(api_key=OPENAI_KEY)

# ✅ 觸發 LINE Loading Animation API
def send_loading_animation(user_id, duration=20):
    url = "https://api.line.me/v2/bot/chat/loading/start"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "chatId": user_id,
        "loadingSeconds": duration  # 可設 5~60 秒
    }
    try:
        res = requests.post(url, headers=headers, json=data)
        print(f"✅ Loading API 狀態碼：{res.status_code}, 回應：{res.text}")
    except Exception as e:
        print("❌ Loading Animation API 錯誤：", e)

# 🔹 ChatGPT 回覆函式
def get_gpt_reply(user_message):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",   
            messages=[{"role": "user", "content": user_message}],
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ ChatGPT API 錯誤：", e)
        return "系統發生錯誤，請稍後再試。"

# 🔹 Webhook
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 🔹 LINE 訊息處理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        user_text = event.message.text

        # ✅ 判斷來源（user / group / room）
        source_type = event.source.type
        if source_type == "user":
            chat_id = event.source.user_id
        elif source_type == "group":
            chat_id = event.source.group_id
        elif source_type == "room":
            chat_id = event.source.room_id
        else:
            chat_id = "UNKNOWN"

        # ✅ 在 log 中清楚標記來源
        print(f"✅ 收到訊息：{user_text} | 來源：{source_type} | ID：{chat_id}")

        
        send_loading_animation(chat_id, duration=20)
        reply_text = get_gpt_reply(user_text)
        print(f"✅ ChatGPT 回覆給 {source_type}({chat_id})：{reply_text}")

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        
    except Exception as e:
        print("❌ handle_message 發生錯誤：", e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=500)

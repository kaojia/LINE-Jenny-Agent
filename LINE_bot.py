from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from openai import OpenAI
from dotenv import load_dotenv
import os
import re
from difflib import SequenceMatcher

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

# ✅ 快取與 FAQ
cache = {}
FAQ_RESPONSES = {
    # 中文
    "你好": "你好！我是Jenny 的 AI 助理，關於亞馬遜的問題歡迎詢問～",
    "幫助": "需要幫助嗎？請輸入：功能 / 教學 / 聯絡客服",

    # 英文
    "hello": "Hello! I'm Jenny's AI assistant. Feel free to ask anything about Amazon seller business.",
    "hi": "Hi there! I'm Jenny's AI assistant. You can ask me anything about Amazon seller topics.",
    "help": "Need help? You can type: features / tutorial / contact support."
}

# ✅ 語言檢測（英文比例 >50% → 英文）
def is_english_message(text):
    letters = re.findall(r'[A-Za-z]', text)
    return len(letters) / max(len(text), 1) > 0.5


# ✅ GPT 回覆函式
def get_gpt_reply(user_message):
    text = user_message.strip()
    text_lower = text.lower()

    # ✅ 3️⃣ 快取查詢
    if text in cache:
        return cache[text]

    english_input = is_english_message(text)

    # 🔹 GPT System Prompt
    prompt = (
        "You are Jenny's AI assistant. "
        "If user asks in English, respond fully in English. "
        "If user asks in Chinese, respond in Traditional Chinese. "
        "Keep answers concise and practical."
    )

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text}
                ],
                max_tokens=350
            )
            reply_text = response.choices[0].message.content.strip()

            cache[text] = reply_text
            return reply_text
        except Exception as e:
            print(f"❌ GPT API 錯誤（嘗試 {attempt+1}/3）：{e}")
            time.sleep(1)

    return "⚠️ 系統繁忙，請稍後再試。"

# ✅ 防止重複註冊 endpoint（特別是 Jupyter）
if "callback" in app.view_functions:
    app.view_functions.pop("callback")

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

# ✅ Keep-Alive Endpoint
@app.route("/ping", methods=['GET'])
def ping():
    print("✅ /ping 被呼叫")  # Debug log
    return "OK", 200

# 🔹 LINE 訊息處理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        user_text = event.message.text.strip()
        print(f"✅ 收到訊息：{user_text}")

        
        if event.source.type == "user":
        # 只回覆一對一聊天
        
            # 🟢 其他訊息 → 繼續走 GPT 回覆邏輯
            reply_text = get_gpt_reply(user_text)
            print(f"🤖 回覆：{reply_text}")

            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

        else:
        # 來自群組或聊天室 → 不回覆
            print("訊息來自群組或聊天室，跳過回覆")


    except Exception as e:
        print("❌ handle_message 發生錯誤：", e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=500)


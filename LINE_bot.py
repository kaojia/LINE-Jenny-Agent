import os
import base64
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
from openai import OpenAI
from dotenv import load_dotenv
import gspread
import json
from google.oauth2.service_account import Credentials
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

# 🔹 載入環境變數
load_dotenv()

app = Flask(__name__)

# 🔹 讀取金鑰
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
TARGET_GROUP_ID="C25afbbbc3a5a4c6d8d1083c907dea2d7"
key_json_str = os.getenv("Creds2")
CREDENTIALS_DICT2 = json.loads(key_json_str)
GOOGLE_SHEET_KEY = "1P56w56RVhU9Re_Q6hehLbI6eXnOZ_x-VJdLYK1_kWRE"



# 初始化
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
client = OpenAI(api_key=OPENAI_KEY)

def get_gs_client():
    SCOPE = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    # 確保每次呼叫都能重新取得憑證，減少 Token 過期問題
    creds = ServiceAccountCredentials.from_json_keyfile_dict(CREDENTIALS_DICT2, SCOPE)
    return gspread.authorize(creds)

# --- 功能函式區 ---

def send_loading_animation(chat_id, duration=20):
    """觸發 LINE Loading 動畫"""
    url = "https://api.line.me/v2/bot/chat/loading/start"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {"chatId": chat_id, "loadingSeconds": duration}
    try:
        requests.post(url, headers=headers, json=data)
    except Exception as e:
        print(f"❌ Loading API 錯誤：{e}")

def get_gpt_reply(user_message):
    """ChatGPT 純文字回覆"""
    try:
        response = client.chat.completions.create(
            model="gpt-5.4-mini",   
            messages=[{"role": "user", "content": user_message}],
            max_completion_tokens=500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ ChatGPT API 錯誤：{e}")
        return "系統發生錯誤，請稍後再試。"

def process_business_card(image_data, chat_id):
    """名片辨識、重複檢查與儲存（指定欄位版本）"""
    try:
        # 1. 呼叫 GPT-5.4-mini 辨識圖片 (Vision)
        base64_image = base64.b64encode(image_data).decode('utf-8')
        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                {
                    "role": "system", 
                    "content": """你是一個專業的名片辨識助手。請嚴格依照 JSON 格式回傳：
                    {
                        "is_card": true, 
                        "name": "中文姓名", 
                        "english_name": "英文姓名", 
                        "company": "公司", 
                        "title": "職稱",
                        "brand":"品牌",
                        "email": "Email", 
                        "phone": "電話"
                    }
                    
                    若名片上缺少某項資訊，請填入空字串。如果圖片內容不是名片，請回傳 {"is_card": false}。"""
                },
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]
                }
            ],
            response_format={ "type": "json_object" }
        )
        
        res_data = json.loads(response.choices[0].message.content)
        if not res_data.get('is_card'):
            return "⚠️ 偵測到非名片內容，已停止操作。"

        # 提取資訊用於重複檢查與檔名
        new_name = res_data.get('name', '')
        new_eng_name = res_data.get('english_name', '')
        new_company = res_data.get('company', '')
        new_brand = res_data.get('brand', '')
        new_title = res_data.get('title', '')

        # 2. 檢查重複 (以 姓名+公司 為準)
        # 請確保 Google Sheet 的標題名稱與程式碼中的 key 完全一致
        gc=get_gs_client()
        sheet = gc.open_by_key(GOOGLE_SHEET_KEY).sheet1
        all_records = sheet.get_all_records()
        for index, row in enumerate(all_records, start=2):
            if str(row.get('姓名')) == new_name and str(row.get('公司')) == new_company:
                return f"🚫 內容重複！此名片已存在於試算表第 {index} 列。"


        # 3. 寫入 Google Sheet (依照你指定的 5 個欄位順序)
        # 欄位順序：姓名、英文姓名、公司、Email、電話
        row_data = [
            new_name, 
            new_eng_name, 
            new_company,
            new_title,
            new_brand, 
            res_data.get('email', ''), 
            res_data.get('phone', ''), 
        ]
        sheet.append_row(row_data)
        
        return f"✅ 成功儲存！\n姓名：{new_name}\n英文姓名：{new_eng_name}\n品牌:{new_brand}\n公司：{new_company}\n資料已存至 Google Sheet。"

    except Exception as e:
        print(f"❌ process_business_card 錯誤：{e}")
        return f"處理名片時發生錯誤：{str(e)}"

# --- Webhook 路由 ---

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 訊息事件處理 ---

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    """處理圖片訊息 (僅限特定群組)"""
    source_type = event.source.type
    chat_id = getattr(event.source, f"{source_type}_id", "UNKNOWN")
    print(f"📌 目前訊息來源 chat_id: {chat_id}")
    
    if source_type == "group" and chat_id == TARGET_GROUP_ID:
        send_loading_animation(chat_id, duration=10)
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = message_content.content
        
        result_msg = process_business_card(image_data, chat_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result_msg))


# --- 工具函式：搜尋與修改 Google Sheets ---

def search_sheet_data(keyword):
    """根據姓名或公司名稱查找資料"""
    # 建議在執行查詢前重新獲取 client，避免長時間掛機導致 Token 失效
    
    try:
        print("📡 開始查詢 Google Sheet")   # 👈 加
        gc = get_gs_client()
        sheet = gc.open_by_key(GOOGLE_SHEET_KEY).sheet1        
        all_records = sheet.get_all_records()
        print(f"📊 讀到資料筆數: {len(all_records)}")   # 👈 加
        results = []
        
        for row in all_records:
            # 支援搜尋 姓名、英文姓名、公司名稱
            if keyword.lower() in str(row.get('姓名', '')).lower() or \
               keyword.lower() in str(row.get('英文姓名', '')).lower() or \
               keyword.lower() in str(row.get('公司', '')).lower() or  \
               keyword.lower() in str(row.get('品牌', '')).lower() or  \
               keyword.lower() in str(row.get('職稱', '')).lower():
                
                res_str = (f"👤 姓名：{row.get('姓名')}\n"
                            f"🔤 英文名：{row.get('英文姓名')}\n"
                            f"🏢 公司：{row.get('公司')}\n"
                            f"💼 職稱：{row.get('職稱')}\n"
                            f"⭐️ 品牌：{row.get('品牌')}\n"
                            f"📧 Email：{row.get('Email')}\n"
                            f"📞 電話：{row.get('電話')}")
                results.append(res_str)
        
        if not results:
            return f"🔍 找不到與「{keyword}」相關的資料。"
        return "✅ 找到以下名片資料：\n\n" + "\n---\n".join(results)
    except Exception as e:
        return f"❌ 查詢發生錯誤：{e}"

def update_sheet_data(name, column_name, new_value):
    """修改指定姓名的欄位資訊"""
    try:
        gc=get_gs_client()
        sheet = gc.open_by_key(GOOGLE_SHEET_KEY).sheet1
        headers = sheet.row_values(1) # 取得標題列
        
        if column_name not in headers:
            return f"❌ 找不到欄位「{column_name}」，請確認標題是否為：姓名、英文姓名、公司、職稱、品牌、Email、電話。"
        
        col_index = headers.index(column_name) + 1
        cell = sheet.find(name) # 尋找姓名儲存格
        
        if cell:
            sheet.update_cell(cell.row, col_index, new_value)
            return f"✨ 修改成功！\n已將「{name}」的【{column_name}】更新為：{new_value}"
        else:
            return f"❌ 找不到姓名為「{name}」的資料，請確認輸入是否正確。"
    except Exception as e:
        return f"❌ 修改失敗：{e}"

# --- LINE 訊息處理邏輯 ---

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        # 統一處理全形與半形空白/逗號
        user_text = event.message.text.strip().replace("，", ",").replace("  ", " ")
        source_type = event.source.type
        chat_id = getattr(event.source, f"{source_type}_id", "UNKNOWN")

        # 1. 🔍 查詢模式
        if user_text.startswith("查詢"):
            keyword = user_text.replace("查詢", "").strip()
            print(f"🔍 查詢關鍵字: {keyword}")   # 👈 加這行
            if keyword:
                send_loading_animation(chat_id, duration=5)
                reply_text = search_sheet_data(keyword)
            else:
                reply_text = "💡 請輸入關鍵字，例如：\n查詢 Jenny\n查詢 Amazon"
            
        # 2. 📝 修改模式 (模板：修改 姓名, 欄位, 內容)
        elif user_text.startswith("修改"):
            params = user_text.replace("修改", "").split(",")
            if len(params) == 3:
                name, col, val = [p.strip() for p in params]
                send_loading_animation(chat_id, duration=5)
                reply_text = update_sheet_data(name, col, val)
            else:
                reply_text = "❌ 格式錯誤！請參考模板：\n修改 高嘉彣，電話，0912345678"

        # 3. 🤖 一般對話模式 (原本的 ChatGPT)
        else:
            send_loading_animation(chat_id, duration=10)
            reply_text = get_gpt_reply(user_text)

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        
    except Exception as e:
        print(f"❌ handle_message 發生錯誤：{e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=500)
        


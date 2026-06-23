import os
import sys
import requests
from datetime import datetime
import zoneinfo
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')

if not channel_secret or not channel_access_token:
    print('Specify LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN as environment variables.')
    sys.exit(1)

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# ユーザーごとの設定を一時的に記憶する辞書（LINEのユーザーIDを鍵にします）
# 構造の例: {"ユーザーID": {"area": "札幌市北区", "burnable": [0, 3], "resource": [2]}}
USER_SETTINGS = {}

# 気象庁コード（主要都市対応）
REGION_CODES = {
    "札幌": "https://www.jma.go.jp/bosai/forecast/data/forecast/016000.json",
    "東京": "https://www.jma.go.jp/bosai/forecast/data/forecast/130000.json",
    "大阪": "https://www.jma.go.jp/bosai/forecast/data/forecast/270000.json"
}

def get_weather_detail(area_name):
    url = None
    if "札幌" in area_name:
        url = REGION_CODES.get("札幌")
    else:
        for key, value in REGION_CODES.items():
            if key in area_name:
                url = value
                break
    if not url:
        return None
    try:
        res = requests.get(url)
        if res.status_code != 200:
            return None
        data = res.json()
        weather_text = data[0]["timeSeries"][0]["areas"][0]["weathers"][0].replace("\u3000", " ")
        return f"【{area_name}の天気】\n今日：{weather_text}"
    except:
        return None

def get_garbage_info(user_id):
    tz = zoneinfo.ZoneInfo("Asia/Tokyo")
    weekday = datetime.now(tz).weekday()
    weekdays_ja = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
    
    # ユーザーの設定を取得（未登録ならデフォルト値）
    settings = USER_SETTINGS.get(user_id, {"burnable": [0, 3], "resource": [2]})
    
    if weekday in settings["burnable"]:
        garbage_type = "🔥「燃やせるゴミ」"
    elif weekday in settings["resource"]:
        garbage_type = "♻️「容器包装プラスチック・資源ゴミ」"
    else:
        garbage_type = "❌「本日のゴミ収集はありません」"
        
    return f"【今日のゴミ出し情報】\n今日は {weekdays_ja[weekday]} です。\n{garbage_type}"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id  # 話しかけてきた人の個別IDを取得
    user_message = event.message.text.strip()
    
    # 【新機能】「登録」から始まるメッセージで曜日を自由に変更できるようにする
    # 入力例：「登録 月木」や「登録 火金」
    if user_message.startswith("登録"):
        try:
            # 「登録」の後の文字を取得して曜日を判定
            days_str = user_message.replace("登録", "").strip()
            day_map = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
            
            burnable_days = [day_map[char] for char in days_str if char in day_map]
            
            if burnable_days:
                if user_id not in USER_SETTINGS:
                    USER_SETTINGS[user_id] = {"area": "札幌市北区", "burnable": [0, 3], "resource": [2]}
                
                USER_SETTINGS[user_id]["burnable"] = burnable_days
                reply_text = f"⚙️ ゴミの曜日を更新しました！\n燃やせるゴミ：{days_str}"
            else:
                reply_text = "曜日の指定がうまく読み取れませんでした。\n「登録 月木」のように送ってください。"
        except Exception as e:
            reply_text = f"登録エラーが発生しました。"
            
    else:
        # 通常の天気・ゴミの確認
        weather_info = get_weather_detail(user_message)
        
        if weather_info:
            # ユーザーが送ってきた区の情報をその人の設定として上書き保存
            if user_id not in USER_SETTINGS:
                USER_SETTINGS[user_id] = {"area": user_message, "burnable": [0, 3], "resource": [2]}
            else:
                USER_SETTINGS[user_id]["area"] = user_message
                
            garbage_info = get_garbage_info(user_id)
            reply_text = f"{weather_info}\n\n{garbage_info}"
        else:
            # 地域が未登録の場合の案内
            settings = USER_SETTINGS.get(user_id)
            if settings:
                # 登録済みの地域があれば、文字は何でもその地域の情報を返す
                saved_area = settings["area"]
                weather_info = get_weather_detail(saved_area)
                garbage_info = get_garbage_info(user_id)
                reply_text = f"現在の登録地：{saved_area}\n\n{weather_info}\n\n{garbage_info}"
            else:
                reply_text = "「札幌市北区」のように送ると、その地域の天気とゴミ情報を確認できます！\n\nまた、「登録 火金」のように送ると、あなたの燃やせるゴミの曜日を自由に変更できます。"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)

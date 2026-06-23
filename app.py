import os
import sys
import requests
from datetime import datetime, timedelta
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

USER_SETTINGS = {}

REGION_CODES = {
    "札幌": "https://www.jma.go.jp/bosai/forecast/data/forecast/016000.json",
    "東京": "https://www.jma.go.jp/bosai/forecast/data/forecast/130000.json",
    "大阪": "https://www.jma.go.jp/bosai/forecast/data/forecast/270000.json"
}

def get_weather_and_garbage(area_name, user_id):
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
            return f"天気データの取得に失敗しました。"
        data = res.json()
        
        # 気象庁から今日、明日、明後日の天気を取得
        weathers = data[0]["timeSeries"][0]["areas"][0]["weathers"]
        today_w = weathers[0].replace("\u3000", " ")
        tomorrow_w = weathers[1].replace("\u3000", " ") if len(weathers) > 1 else "データなし"
        day_after_w = weathers[2].replace("\u3000", " ") if len(weathers) > 2 else "データなし"
        
        # 日本時間での曜日計算用の準備
        tz = zoneinfo.ZoneInfo("Asia/Tokyo")
        now_tokyo = datetime.now(tz)
        
        weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
        settings = USER_SETTINGS.get(user_id, {"burnable": [1, 4], "resource": [2]})
        burnable_days = settings.get("burnable", [1, 4])
        resource_days = settings.get("resource", [2])

        def judge_garbage(target_date):
            w_idx = target_date.weekday()
            if w_idx in burnable_days:
                return f"🔥燃やせるゴミ"
            elif w_idx in resource_days:
                return f"♻️プラ・資源"
            else:
                return f"❌なし"

        # 3日分の日付とゴミを判定
        date_0 = now_tokyo
        date_1 = now_tokyo + timedelta(days=1)
        date_2 = now_tokyo + timedelta(days=2)

        msg = f"【{area_name}の案内】\n\n"
        msg += f"📅今日 ({weekdays_ja[date_0.weekday()]}): {today_w}\n ┗ゴミ: {judge_garbage(date_0)}\n\n"
        msg += f"📅明日 ({weekdays_ja[date_1.weekday()]}): {tomorrow_w}\n ┗ゴミ: {judge_garbage(date_1)}\n\n"
        msg += f"📅明後日 ({weekdays_ja[date_2.weekday()]}): {day_after_w}\n ┗ゴミ: {judge_garbage(date_2)}"
        
        return msg
    except Exception as e:
        return f"データ解析エラーが発生しました。詳細: {str(e)}"

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
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    
    if user_message.startswith("登録"):
        try:
            days_str = user_message.replace("登録", "").strip()
            day_map = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
            burnable_days = [day_map[char] for char in days_str if char in day_map]
            
            if burnable_days:
                if user_id not in USER_SETTINGS:
                    USER_SETTINGS[user_id] = {"area": "札幌市北区", "burnable": burnable_days, "resource": [2]}
                else:
                    USER_SETTINGS[user_id]["burnable"] = burnable_days
                reply_text = f"⚙️ ゴミの曜日を更新しました！\n燃やせるゴミ：{days_str}"
            else:
                reply_text = "曜日の指定がうまく読み取れませんでした。\n「登録 火金」のように送ってください。"
        except:
            reply_text = f"登録エラーが発生しました。"
            
    else:
        # 入力されたテキストを地域として判定させて、3日分のメッセージを作る
        # すでに登録済みの人なら、何を送っても登録地で計算
        settings = USER_SETTINGS.get(user_id)
        area_to_check = user_message
        
        if not REGION_CODES.get(user_message[:2]) and settings:
            area_to_check = settings["area"]

        info_msg = get_weather_and_garbage(area_to_check, user_id)
        
        if info_msg:
            if user_id not in USER_SETTINGS:
                USER_SETTINGS

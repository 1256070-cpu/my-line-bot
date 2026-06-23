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

# ユーザーごとの設定を記憶する辞書
USER_SETTINGS = {}

# 気象庁コード
REGION_CODES = {
    "札幌": "https://www.jma.go.jp/bosai/forecast/data/forecast/016000.json",
    "東京": "https://www.jma.go.jp/bosai/forecast/data/forecast/130000.json",
    "大阪": "https://www.jma.go.jp/bosai/forecast/data/forecast/270000.json"
}

# 【新機能】札幌市の住所のキーワードに応じたゴミの日自動判定ルール
# 0=月, 1=火, 2=水, 3=木, 4=金, 5=土, 6=日
def judge_garbage_days_by_address(address):
    # デフォルトは火・金（燃やせる）、水（プラ）
    result = {"burnable": [1, 4], "resource": [2]}
    
    # 住所の文字を見て、月・木ルートの地域を自動判別
    # 例：あいの里、拓北、篠路、屯田の一部など（実際のカレンダーに合わせて後からいくらでも増やせます）
    monthly_thursday_keywords = ["あいの里", "拓北", "篠路", "茨戸", "太平"]
    
    for kw in monthly_thursday_keywords:
        if kw in address:
            result["burnable"] = [0, 3] # 月・木に変更
            result["resource"] = [2]    # 水（プラ）
            break
            
    return result

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
            return None
        data = res.json()
        
        weathers = data[0]["timeSeries"][0]["areas"][0]["weathers"]
        today_w = weathers[0].replace("\u3000", " ")
        tomorrow_w = weathers[1].replace("\u3000", " ") if len(weathers) > 1 else "データなし"
        day_after_w = weathers[2].replace("\u3000", " ") if len(weathers) > 2 else "データなし"
        
        tz = zoneinfo.ZoneInfo("Asia/Tokyo")
        now_tokyo = datetime.now(tz)
        weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
        
        # ユーザーに紐づいたゴミの日設定を取得
        settings = USER_SETTINGS.get(user_id, {"burnable": [1, 4], "resource": [2]})
        burnable_days = settings["burnable"]
        resource_days = settings["resource"]

        def judge_garbage(target_date):
            w_idx = target_date.weekday()
            if w_idx in burnable_days:
                return f"🔥燃やせるゴミ"
            elif w_idx in resource_days:
                return f"♻️プラ・資源"
            else:
                return f"❌なし"

        date_0 = now_tokyo
        date_1 = now_tokyo + timedelta(days=1)
        date_2 = now_tokyo + timedelta(days=2)

        msg = f"【{area_name}の案内】\n"
        # 燃やせるゴミの曜日を分かりやすく表示
        b_days_str = "・".join([weekdays_ja[d] for d in burnable_days])
        msg += f"（設定された燃やせるゴミの日: {b_days_str}）\n\n"
        
        msg += f"📅今日 ({weekdays_ja[date_0.weekday()]}): {today_w}\n ┗ゴミ: {judge_garbage(date_0)}\n\n"
        msg += f"📅明日 ({weekdays_ja[date_1.weekday()]}): {tomorrow_w}\n ┗ゴミ: {judge_garbage(date_1)}\n\n"
        msg += f"📅明後日 ({weekdays_ja[date_2.weekday()]}): {day_after_w}\n ┗ゴミ: {judge_garbage(date_2)}"
        
        return msg
    except:
        return None

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

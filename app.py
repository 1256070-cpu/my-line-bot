import os
import sys
import requests
import traceback  # エラーの場所を完全に特定するためのライブラリ
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

def judge_garbage_days_by_address(address):
    result = {"burnable": [1, 4], "resource": [2]}
    monthly_thursday_keywords = ["あいの里", "拓北", "篠路", "茨戸", "太平"]
    for kw in monthly_thursday_keywords:
        if kw in address:
            result["burnable"] = [0, 3]
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
        print(f"DEBUG: URLが見つかりません。入力された文字: {area_name}")
        return f"地域「{area_name}」の天気URLが見つかりませんでした。"

    try:
        res = requests.get(url)
        print(f"DEBUG: 天気サーバー応答ステータス: {res.status_code}")
        if res.status_code != 200:
            return "天気データの取得に失敗しました。"
            
        data = res.json()
        weathers = data[0]["timeSeries"][0]["areas"][0]["weathers"]
        today_w = weathers[0].replace("\u3000", " ")
        tomorrow_w = weathers[1].replace("\u3000", " ") if len(weathers) > 1 else "データなし"
        day_after_w = weathers[2].replace("\u3000", " ") if len(weathers) > 2 else "データなし"
        
        tz = zoneinfo.ZoneInfo("Asia/Tokyo")
        now_tokyo = datetime.now(tz)
        weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
        
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

        b_days_str = "・".join([weekdays_ja[d] for d in burnable_days])
        
        msg = f"【{area_name}の案内】\n"
        msg += f"（設定された燃やせるゴミの日: {b_days_str}）\n\n"
        msg += f"📅今日 ({weekdays_ja[date_0.weekday()]}): {today_w}\n ┗ゴミ: {judge_garbage(date_0)}\n\n"
        msg += f"📅明日 ({weekdays_ja[date_1.weekday()]}): {tomorrow_w}\n ┗ゴミ: {judge_garbage(date_1)}\n\n"
        msg += f"📅明後日 ({weekdays_ja[date_2.weekday()]}): {day_after_w}\n ┗ゴミ: {judge_garbage(date_2)}"
        
        return msg
    except Exception as e:
        print("DEBUG: 天気・ゴミデータ処理中にエラー発生！")
        print(traceback.format_exc()) # エラー内容をログに全部出す
        return f"データ処理中にエラーが発生しました: {str(e)}"

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
    
    print(f"DEBUG: 受信メッセージ: {user_message}")
    
    is_sapporo = "札幌" in user_message
    
    if is_sapporo:
        garbage_rule = judge_garbage_days_by_address(user_message)
        USER_SETTINGS[user_id] = {
            "area": user_message,
            "burnable": garbage_rule["burnable"],
            "resource": garbage_rule["resource"]
        }
        reply_text = get_weather_and_garbage(user_message, user_id)
    else:
        settings = USER_SETTINGS.get(user_id)
        if settings:
            saved_area = settings["area"]
            reply_text = get_weather_and_garbage(saved_area, user_id)
        else:
            reply_text = "お住まいの地域を「札幌市北区あいの里」のように送ってください！"

    print(f"DEBUG: LINEに返信するテキスト:\n{reply_text}")

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
        print("DEBUG: LINEへの送信処理が完了しました。")
    except Exception as e:
        print("DEBUG: LINEへの送信中に致命的なエラーが発生しました！")
        print(traceback.format_exc())

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)

import os
import sys
import requests
from datetime import datetime
import zoneinfo # 日本時間を正確に計算するため
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

# 気象庁の地域コード（札幌市各区はすべて「石狩地方」なので016000でカバーできます）
REGION_CODES = {
    "札幌": "https://www.jma.go.jp/bosai/forecast/data/forecast/016000.json",
    "東京": "https://www.jma.go.jp/bosai/forecast/data/forecast/130000.json",
    "大阪": "https://www.jma.go.jp/bosai/forecast/data/forecast/270000.json"
}

def get_weather_detail(area_name):
    # 「札幌市北区」「札幌市中央区」など、文字に「札幌」が入っていれば札幌のURLを選択
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
            return f"天気データの取得に失敗しました。(Status: {res.status_code})"
            
        data = res.json()
        
        # エラーの元だった気温データは削除し、確実に取れる天気テキストのみを取得
        weather_text = data[0]["timeSeries"][0]["areas"][0]["weathers"][0]
        weather_text = weather_text.replace("\u3000", " ")
        
        return f"【{area_name}の天気】\n今日：{weather_text}"
    except Exception as e:
        return f"天気データ解析エラー: {str(e)}"

def get_garbage_info():
    # 日本時間で現在の曜日を取得（月=0, 火=1, 水=2, 木=3, 金=4, 土=5, 日=6）
    tz = zoneinfo.ZoneInfo("Asia/Tokyo")
    now = datetime.now(tz)
    weekday = now.weekday()
    
    # 曜日の日本語テキスト
    weekdays_ja = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
    today_weekday_str = weekdays_ja[weekday]
    
    # 札幌市の一般的なゴミ収集日（例：月木が燃やせる、水が資源）の簡易判定
    # ※後ほど、ユーザーごとに個別の曜日を設定できるように拡張します
    if weekday == 0 or weekday == 3: # 月曜日または木曜日
        garbage_type = "🔥「燃やせるゴミ」"
    elif weekday == 2: # 水曜日
        garbage_type = "♻️「容器包装プラスチック・資源ゴミ」"
    else:
        garbage_type = "❌「本日のゴミ収集はありません」"
        
    return f"【今日のゴミ出し情報】\n今日は {today_weekday_str} です。\n{garbage_type}"

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
    user_message = event.message.text.strip()
    
    # 天気情報の取得
    weather_info = get_weather_detail(user_message)
    
    if weather_info:
        # ゴミ情報の取得
        garbage_info = get_garbage_info()
        reply_text = f"{weather_info}\n\n{garbage_info}"
    else:
        reply_text = f"「{user_message}」ですね！\n\n「札幌市中央区」や「札幌市北区」のように送ると、その地域の天気と今日のゴミ出し情報をセットで返します！"

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

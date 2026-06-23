import os
import sys
import requests
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

# 地域ごとの気象庁コード（詳細版への布石）
# 札幌一括ではなく、今後ユーザーごとに地域コードを切り替えられるようにします
REGION_CODES = {
    "札幌": "016000", # 石狩地方
    "東京": "130000",
    "大阪": "270000"
}

def get_weather_detail(area_name):
    # 現状は「札幌」が含まれていれば石狩地方のデータを取得
    code = REGION_CODES.get("札幌") if "札幌" in area_name else REGION_CODES.get(area_name)
    if not code:
        return None
    try:
        url = f"https://www.jma.go.jp/bosai/forecast/data/forecast/{code}.json"
        res = requests.get(url).json()
        
        # 今日・明日の天気と気温を取得
        weather_text = res[0]["timeSeries"][0]["areas"][0]["weathers"][0].replace("\u3000", " ")
        
        # 気温データの取得（一番近い発表場所から取得）
        temp_data = res[0]["timeSeries"][2]["temps"]
        today_max_temp = temp_data[1] if len(temp_data) > 1 else "---"
        
        return f"【{area_name}の天気】\n今日：{weather_text}\n予想気温：{today_max_temp}度"
    except Exception as e:
        return f"データ取得エラー: {str(e)}"

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
    
    # 1. 天気情報の取得を試みる
    weather_info = get_weather_detail(user_message)
    
    if weather_info:
        # 2. ゴリ出し情報のダミー（次のステップで、曜日連動・ユーザー個別判定にします）
        dummy_garbage = "\n\n【今日のゴミ】\n設定された曜日（月・木）に基づき、本日は「燃やせるゴミ」の日です！"
        reply_text = weather_info + dummy_garbage
    else:
        reply_text = f"「{user_message}」ですね！\n\n【地域登録のデモ】\n「札幌市北区」のように送ると、その地域の天気（試作版）とゴミの日を返します。"

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

import os
import sys
import requests
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')

if channel_secret is None or channel_access_token is None:
    print('Specify LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN as environment variables.')
    sys.exit(1)

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# 正しいURL構造に直した気象庁のデータ
CITY_URLS = {
    "東京": "https://www.jma.go.jp/bosai/forecast/data/forecast/130000.json",
    "大阪": "https://www.jma.go.jp/bosai/forecast/data/forecast/270000.json",
    "名古屋": "https://www.jma.go.jp/bosai/forecast/data/forecast/230000.json",
    "福岡": "https://www.jma.go.jp/bosai/forecast/data/forecast/400000.json",
    "札幌": "https://www.jma.go.jp/bosai/forecast/data/forecast/016000.json"
}

def get_weather(city_name):
    url = CITY_URLS.get(city_name)
    if not url:
        return None
    try:
        # 気象庁から実際のデータを取得
        res = requests.get(url)
        if res.status_code != 200:
            return f"天気データの取得に失敗しました。(Status: {res.status_code})"
            
        data = res.json()
        
        # 確実にデータが存在する場所から「今日の天気」のテキストを取得
        weather_text = data[0]["timeSeries"][0]["areas"][0]["weathers"][0]
        weather_text = weather_text.replace("\u3000", " ") # 全角スペースを半角に綺麗にする
        
        return f"【{city_name}の天気】\n今日：{weather_text}"
    except Exception as e:
        return f"天気データの解析に失敗しました。詳細: {str(e)}"

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
    weather_info = get_weather(user_message)
    
    if weather_info:
        reply_text = weather_info
    else:
        reply_text = f"「{user_message}」ですね！\n\n※現在はテスト中につき「東京」「大阪」「名古屋」「福岡」「札幌」のいずれかを送ると天気を返します！"

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

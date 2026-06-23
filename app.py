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

# 環境変数からトークン等を取得
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')

if channel_secret is None or channel_access_token is None:
    print('Specify LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN as environment variables.')
    sys.exit(1)

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# 主要都市の気象庁地域コード
CITY_CODES = {
    "東京": "130010",
    "大阪": "270000",
    "名古屋": "230010",
    "福岡": "400010",
    "札幌": "016010"
}

def get_weather(city_name):
    code = CITY_CODES.get(city_name)
    if not code:
        return None
    try:
        # 気象庁の無料APIを利用
        url = f"https://www.jma.go.jp/bosai/forecast/data/forecast/{code}.json"
        res = requests.get(url).json()
        
        # 明日朝の定期配信への布石として、今日の天気を取得
        report_time = res[0]["reportDatetime"]
        area_data = res[0]["timeSeries"][0]["areas"][0]
        weather = area_data["weathers"][0] # 今日の天気
        
        return f"【{city_name}の天気】\n今日：{weather}"
    except Exception as e:
        return f"天気データの取得に失敗しました。({str(e)})"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

@handler.add(MessageEvent, content_type=TextMessageContent)
def handle_message(event):
    user_message = event.message.text.strip()
    
    # 送られた文字が都市名にあるかチェック
    weather_info = get_weather(user_message)
    
    if weather_info:
        reply_text = weather_info
    else:
        reply_text = f"「{user_message}」ですね！\n\n※現在はテスト中につき「東京」「大阪」「名古屋」「福岡」「札幌」のいずれかを送ると、ピンポイントで今日の天気を返します！"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)

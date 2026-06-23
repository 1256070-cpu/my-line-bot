import os
import sys
import requests
from datetime import datetime, timedelta
import zoneinfo
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, MessageAction, PushMessageRequest
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent

app = Flask(__name__)

channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')

if not channel_secret or not channel_access_token:
    print('Specify LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN as environment variables.')
    sys.exit(1)

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# ユーザーの設定を記憶する辞書
USER_SETTINGS = {}

# 全国主要地域の気象庁コード（お友達の地域に合わせて自由に追加できます）
REGION_CODES = {
    "札幌": "https://www.jma.go.jp/bosai/forecast/data/forecast/016000.json",
    "根室": "https://www.jma.go.jp/bosai/forecast/data/forecast/014100.json",
    "旭川": "https://www.jma.go.jp/bosai/forecast/data/forecast/012000.json",
    "函館": "https://www.jma.go.jp/bosai/forecast/data/forecast/017000.json",
    "東京": "https://www.jma.go.jp/bosai/forecast/data/forecast/130000.json",
    "大阪": "https://www.jma.go.jp/bosai/forecast/data/forecast/270000.json"
}

SAPPORO_WARDS = ["中央区", "北区", "東区", "白石区", "厚別区", "豊平区", "清田区", "南区", "西区", "手稲区"]

def get_nth_week(target_date):
    first_day = target_date.replace(day=1)
    adjusted_dom = target_date.day + first_day.weekday()
    return (adjusted_dom - 1) // 7 + 1

def get_weather_and_garbage(user_id):
    settings = USER_SETTINGS.get(user_id)
    if not settings or "paper_week" not in settings:
        return None
        
    area_name = settings.get("area", "札幌市北区")
    url = "https://www.jma.go.jp/bosai/forecast/data/forecast/016000.json"
    for key, value in REGION_CODES.items():
        if key in area_name:
            url = value
            break

    try:
        res = requests.get(url)
        if res.status_code != 200: 
            return f"【{area_name}の案内や！】\n天気のデータ、上手く取れんかったわ！すまんな！"
        data = res.json()
        
        # 天気情報の取得
        weathers = data[0]["timeSeries"][0]["areas"][0]["weathers"]
        today_w = weathers[0].replace("\u3000", " ")
        tomorrow_w = weathers[1].replace("\u3000", " ") if len(weathers) > 1 else "わからん"
        day_after_w = weathers[2].replace("\u3000", " ") if len(weathers) > 2 else "わからん"
        
        # 気温情報の取得（今日・明日の最高/最低気温）
        temp_text_today = ""
        temp_text_tomorrow = ""
        try:
            # 気象庁データの気温セクションを解析
            for ts in data[0]["timeSeries"]:
                if "temps" in ts:
                    temps = ts["temps"]
                    if len(temps) >= 2:
                        temp_text_today = f" (気温: {temps[0]}℃〜{temps[1]}℃)"
                    if len(temps) >= 4:
                        temp_text_tomorrow = f" (気温: {temps[2]}℃〜{temps[3]}℃)"
                    break
        except Exception:
            pass # 気温が取れない地域・時間帯は空欄のまま進む

        tz = zoneinfo.ZoneInfo("Asia/Tokyo")
        now_tokyo = datetime.now(tz)
        weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
        
        burnable_days = settings.get("burnable", [])
        plastic_days = settings.get("plastic", [])
        bottle_can_days = settings.get("bottle_can", [])
        paper_days = settings.get("paper", [])
        paper_week = settings.get("paper_week", "毎週")

        def judge_garbage(target_date):
            w_idx = target_date.weekday()
            nth_week = get_nth_week(target_date)
            g_list = []
            
            if w_idx in burnable_days: 
                g_list.append("🔥燃やせるゴミ")
            if w_idx in plastic_days: 
                g_list.append("♻️容器包装プラスチック")
            if w_idx in bottle_can_days: 
                g_list.append("🍾びん・缶・ペット")
                
            if w_idx in paper_days:
                if paper_week == "毎週": 
                    g_list.append("📰雑がみ・紙類")
                elif paper_week == "第1・第3" and nth_week in [1, 3]: 
                    g_list.append("📰雑がみ（第1・3週）")
                elif paper_week == "第2・第4" and nth_week in [2, 4]: 
                    g_list.append("📰雑がみ（第2・4週）")
                
            return "・".join(g_list) if g_list else "❌何もないわ！"

        date_0 = now_tokyo
        date_1 = now_tokyo + timedelta(days=1)
        date_2 = now_tokyo + timedelta(days=2)
        
        lines = [
            f"【{area_name}の案内やでぇ！】",
            "おっしゃ、今日の天気とゴミ情報教えたるわ！\n",
            f"📅今日 ({weekdays_ja[date_0.weekday()]}): {today_w}{temp_text_today}\n ┗ ゴミ: {judge_garbage(date_0)}\n",
            f"📅明日 ({weekdays_ja[date_1.weekday()]}): {tomorrow_w}{temp_text_tomorrow}\n ┗ ゴミ: {judge_garbage(date_1)}\n",
            f"📅明後日 ({weekdays_ja[date_2.weekday()]}): {day_after_w}\n ┗ ゴミ: {judge_garbage(date_2)}\n",
            "うかうかしとったらゴミ出し遅れるでぇ！気ぃ引き締めや！"
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"あア、なんかエラー出てもうたわ！すまんなぁ！: {str(e)}"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ⏰ 毎朝自動送信（プッシュ通知）を叩くためのURL
@app.route("/morning-push", methods=['GET'])
def morning_push():
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        # 登録されている全員に一斉送信
        for user_id

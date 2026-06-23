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
    QuickReply, QuickReplyItem, MessageAction
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

# ユーザーの設定を記憶する辞書
USER_SETTINGS = {}

# 気象庁コード（札幌、東京、大阪）
REGION_CODES = {
    "札幌": "https://www.jma.go.jp/bosai/forecast/data/forecast/016000.json",
    "東京": "https://www.jma.go.jp/bosai/forecast/data/forecast/130000.json",
    "大阪": "https://www.jma.go.jp/bosai/forecast/data/forecast/270000.json"
}

# 札幌市の10区リスト
SAPPORO_WARDS = ["中央区", "北区", "東区", "白石区", "厚別区", "豊平区", "清田区", "南区", "西区", "手稲区"]

def get_weather_and_garbage(user_id):
    # 設定がなければデフォルト値を仮セット
    settings = USER_SETTINGS.get(user_id, {"area": "札幌市北区", "burnable": [2, 5], "plastic": [3], "resource": [4]})
    area_name = settings.get("area", "札幌市北区")
    
    url = REGION_CODES.get("札幌")
    for key, value in REGION_CODES.items():
        if key in area_name:
            url = value
            break

    try:
        res = requests.get(url)
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
        
        burnable_days = settings.get("burnable", [2, 5])
        plastic_days = settings.get("plastic", [3])
        resource_days = settings.get("resource", [4])

        def judge_garbage(target_date):
            w_idx = target_date.weekday()
            if w_idx in burnable_days:
                return f"🔥燃やせるゴミ"
            elif w_idx in plastic_days:
                return f"♻️容器包装プラスチック"
            elif w_idx in resource_days:
                return f"💎資源ゴミ（雑がみ・缶・ペット等）"
            else:
                return f"❌なし"

        date_0 = now_tokyo
        date_1 = now_tokyo + timedelta(days=1)
        date_2 = now_tokyo + timedelta(days=2)

        b_days_str = "・".join([weekdays_ja[d] for d in burnable_days])
        p_days_str = "・".join([weekdays_ja[d] for d in plastic_days])
        r_days_str = "・".join([weekdays_ja[d] for d in resource_days])
        
        msg = f"【{area_name}の案内】\n"
        msg += f"（設定：燃やせる={b_days_str} / プラ={p_days_str} / 資源={r_days_str}）\n\n"
        msg += f"📅今日 ({weekdays_ja[date_0.weekday()]}): {today_w}\n ┗ゴミ: {judge_garbage(date_0)}\n\n"
        msg += f"📅明日 ({weekdays_ja[date_1.weekday()]}): {tomorrow_w}\n ┗ゴミ: {judge_garbage(date_1)}\n\n"
        msg += f"📅明後日 ({weekdays_ja[date_2.weekday()]}): {day_after_w}\n ┗ゴミ: {judge_

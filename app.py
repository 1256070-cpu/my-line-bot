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
    # デフォルト値
    settings = USER_SETTINGS.get(user_id, {"area": "札幌市北区", "burnable": [2, 5], "plastic": [3], "bottle_can": [4], "paper": [4]})
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
        bottle_can_days = settings.get("bottle_can", [4])
        paper_days = settings.get("paper", [4])

        def judge_garbage(target_date):
            w_idx = target_date.weekday()
            g_list = []
            if w_idx in burnable_days:
                g_list.append("🔥燃やせるゴミ")
            if w_idx in plastic_days:
                g_list.append("♻️容器包装プラスチック")
            if w_idx in bottle_can_days:
                g_list.append("🍾びん・缶・ペット")
            if w_idx in paper_days:
                g_list.append("📰雑がみ・新聞・段ボール")
                
            if g_list:
                return "・".join(g_list)
            else:
                return "❌なし"

        date_0 = now_tokyo
        date_1 = now_tokyo + timedelta(days=1)
        date_2 = now_tokyo + timedelta(days=2)

        b_str = "・".join([weekdays_ja[d] for d in burnable_days])
        p_str = "・".join([weekdays_ja[d] for d in plastic_days])
        bc_str = "・".join([weekdays_ja[d] for d in bottle_can_days])
        pa_str = "・".join([weekdays_ja[d] for d in paper_days])
        
        lines = [
            f"【{area_name}の案内】",
            f"（設定：燃やせる={b_str} / プラ={p_str} / びん缶={bc_str} / 雑がみ={pa_str}）\n",
            f"📅今日 ({weekdays_ja[date_0.weekday()]}): {today_w}\n ┗ゴミ: {judge_garbage(date_0)}\n",
            f"📅明日 ({weekdays_ja[date_1.weekday()]}): {tomorrow_w}\n ┗ゴミ: {judge_garbage(date_1)}\n",
            f"📅明後日 ({weekdays_ja[date_2.weekday()]}): {day_after_w}\n ┗ゴミ: {judge_garbage(date_2)}"
        ]
        return "\n".join(lines)
    except:
        return "データ処理中にエラーが発生しました。"

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
    
    reply_text = ""
    quick_reply_items = []
    day_map = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
    patterns_week = ["月曜", "火曜", "水曜", "木曜", "金曜"]

    # 1. 初期設定スタート（区を選択）
    if user_message in ["初期設定", "設定"]:
        reply_text = "お住まいの「区」をタップして選択してください！"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=ward, text=f"区選択:{ward}")) for ward in SAPPORO_WARDS
        ]
        
    # 2. 区選択 -> 燃やせるゴミ
    elif user_message.startswith("区選択:"):
        ward = user_message.split(":")[1]
        USER_SETTINGS[user_id] = {"area": f"札幌市{ward}"}
        
        reply_text = f"【札幌市{ward}】を登録しました。\n次に「燃やせるゴミ」の収集曜日を選んでください！"
        patterns = ["月・木", "火・金", "水・土"]
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=p, text=f"燃やせる:{p}")) for p in patterns
        ]

    # 3. 燃やせるゴミ選択 -> プラスチック
    elif user_message.startswith("燃やせる:"):
        p_str = user_message.split(":")[1]
        burnable_days = [day_map[char] for char in p_str if char in day_map]
        
        if user_id not in USER_SETTINGS:
            USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["burnable"] = burnable_days
        
        reply_text = f"燃やせるゴミ（{p_str}）を設定しました。\n次に「容器包装プラスチック」の曜日を選んでください！"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=p, text=f"プラ:{p}")) for p in patterns_week
        ]

    # 4. プラスチック選択 -> びん・缶・ペットボトル
    elif user_message.startswith("プラ:"):
        p_str = user_message.split(":")[1][0]
        plastic_day = [day_map[p_str]]
        
        if user_id not in USER_SETTINGS:
            USER_SETTINGS[user_id] = {"area": "札幌市北区", "burnable": [2, 5]}
        USER_SETTINGS[user_id]["plastic"] = plastic_day
        
        reply_text = f"容器包装プラスチック（{p_str}曜）を設定しました。\n次に「びん・缶・ペットボトル」の曜日を選んでください！"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=p, text=f"びん缶:{p}")) for p in patterns_week
        ]

    # 5. びん・缶・ペットボトル選択 -> 雑がみ・紙類
    elif user_message.startswith("びん缶:"):
        bc_str = user_message.split(":")[1][0]
        bottle_can_day = [day_map[bc_str]]
        
        if user_id not in USER_SETTINGS:
            USER_SETTINGS[user_id] = {"area": "札幌市北区", "burnable": [2, 5], "plastic": [3]}
        USER_SETTINGS[user_id]["bottle_can"] = bottle_can_day
        
        reply_text = f"びん・缶・ペットボトル（{bc_str}曜）を設定しました。\n最後に「雑がみ・新聞・段ボール」の曜日を選んでください！"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=p, text=f"雑がみ:{p}")) for p in patterns_week
        ]

    # 6. 雑がみ選択（すべての設定が完了）
    elif user_message.startswith("雑がみ:"):
        r_str = user_message.split(":")[1][0]
        resource_day = [day_map[r_str]]
        
        if user_id not in USER_SETTINGS:
            USER_SETTINGS[user_id] = {"area": "札幌市北区", "burnable": [2, 5], "plastic": [3], "bottle_can": [4]}
        USER_SETTINGS[user_id]["paper"] = resource_day
        
        reply_text = "🎉 すべての設定が完了しました！\n\n次からは、何か文字（「あ」など）を送るだけで、あなた専用の3日分の天気と、細かく分かれたすべてのゴミ出し情報をいつでも確認できます。"

    # 7. 通常時
    else:
        if user_id in USER_SETTINGS and "paper" in USER_SETTINGS[user_id]:
            reply_text = get_weather_and_garbage(user_id)
        else:
            reply_text = "ご利用ありがとうございます！\nまずはあなたの地域を設定しましょう。\n\n下のボタンを押すか、「初期設定」と送ってください。"
            quick_reply_items = [QuickReplyItem(action=MessageAction(label="⚙️ 初期設定を始める", text="初期設定"))]

    # LINEに返信を送信
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        q_reply = QuickReply(items=quick_reply_items) if quick_reply_items else None
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text, quick_reply=q_reply)]
            )
        )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)

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

USER_SETTINGS = {}

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
            return f"【{area_name}の案内】\n天気データの取得に失敗しました。"
        data = res.json()
        
        weathers = data[0]["timeSeries"][0]["areas"][0]["weathers"]
        today_w = weathers[0].replace("\u3000", " ")
        tomorrow_w = weathers[1].replace("\u3000", " ") if len(weathers) > 1 else "データなし"
        day_after_w = weathers[2].replace("\u3000", " ") if len(weathers) > 2 else "データなし"
        
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
                
            return "・".join(g_list) if g_list else "❌なし"

        date_0 = now_tokyo
        date_1 = now_tokyo + timedelta(days=1)
        date_2 = now_tokyo + timedelta(days=2)

        b_str = "・".join([weekdays_ja[d] for d in burnable_days])
        p_str = "・".join([weekdays_ja[d] for d in plastic_days])
        bc_str = "・".join([weekdays_ja[d] for d in bottle_can_days])
        pa_str = "・".join([weekdays_ja[d] for d in paper_days])
        
        lines = [
            f"【{area_name}の案内】",
            f"（設定：燃やせる={b_str} / プラ={p_str} / びん缶={bc_str} / 雑がみ={pa_str}({paper_week})）\n",
            f"📅今日 ({weekdays_ja[date_0.weekday()]}): {today_w}\n ┗ゴミ: {judge_garbage(date_0)}\n",
            f"📅明日 ({weekdays_ja[date_1.weekday()]}): {tomorrow_w}\n ┗ゴミ: {judge_garbage(date_1)}\n",
            f"📅明後日 ({weekdays_ja[date_2.weekday()]}): {day_after_w}\n ┗ゴミ: {judge_garbage(date_2)}"
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"エラーが発生しました: {str(e)}"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@app.route("/morning-push", methods=['GET'])
def morning_push():
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        for user_id in USER_SETTINGS.keys():
            msg_text = get_weather_and_garbage(user_id)
            if msg_text:
                try:
                    line_bot_api.push_message(
                        PushMessageRequest(to=user_id, messages=[TextMessage(text=msg_text)])
                    )
                except Exception as e:
                    print(f"Push failed for {user_id}: {e}")
    return 'Push Sent'

@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    reply_text = "登録ありがとうございます！🎉\nお住まいの地域の「天気」と「ゴミの日」をまとめてお届けするボットです。\n\nまずは下のボタンを押して、初期設定を始めてください！"
    quick_reply_items = [QuickReplyItem(action=MessageAction(label="⚙️ 初期設定を始める", text="初期設定"))]
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text, quick_reply=QuickReply(items=quick_reply_items))]
            )
        )

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    
    reply_text = ""
    quick_reply_items = []
    day_map = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
    patterns_week = ["月曜", "火曜", "水曜", "木曜", "金曜"]

    if user_message in ["初期設定", "設定"]:
        reply_text = "お住まいの地域はどちらですか？"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label="札幌市", text="地域選択:札幌市")),
            QuickReplyItem(action=MessageAction(label="その他の市町村（根室など）", text="地域選択:その他"))
        ]
        
    elif user_message == "地域選択:札幌市":
        reply_text = "お住まいの「区」を選択してください！"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=ward, text=f"区選択:{ward}")) for ward in SAPPORO_WARDS
        ]
        
    elif user_message == "地域選択:その他":
        reply_text = "お住まいの市町村名を「根室市」や「旭川市」のようにメッセージで直接送信してください！"

    elif any(user_message.endswith(s) for s in ["市", "町", "村"]) and not user_message.startswith("区選択:"):
        USER_SETTINGS[user_id] = {"area": user_message}
        reply_text = f"【{user_message}】を登録しました。\n次に「燃やせるゴミ」の収集曜日を選んでください！"
        patterns = ["月・木", "火・金", "水・土", "月・水・金", "火・木・土"]
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=p, text=f"燃やせる:{p}")) for p in patterns
        ]

    elif user_message.startswith("区選択:"):
        ward = user_message.split(":")[1]
        USER_SETTINGS[user_id] = {"area": f"札幌市{ward}"}
        reply_text = f"【札幌市{ward}】を登録しました。\n次に「燃やせるゴミ」の収集曜日を選んでください！"
        patterns = ["月・木", "火・金", "水・土"]
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=p, text=f"燃やせる:{p}")) for p in patterns
        ]

    elif user_message.startswith("燃やせる:"):
        p_str = user_message.split(":")[1]
        burnable_days = [day_map[char] for char in p_str if char in day_map]
        if user_id not in USER_SETTINGS: USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["burnable"] = burnable_days
        
        reply_text = f"燃やせるゴミ（{p_str}）を設定しました。\n次に「容器包装プラスチック」の曜日を選んでください！"
        quick_reply_items = [QuickReplyItem(action=MessageAction(label=p, text=f"プラ:{p}")) for p in patterns_week]

    elif user_message.startswith("プラ:"):
        p_str = user_message.split(":")[1][0]
        plastic_day = [day_map[p_str]]
        if user_id not in USER_SETTINGS: USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["plastic"] = plastic_day
        
        reply_text = f"容器包装プラスチック（{p_str}曜）を設定しました。\n次に「びん・缶・ペットボトル」の曜日を選んでください！"
        quick_reply_items = [QuickReplyItem(action=MessageAction(label=p, text=f"びん缶:{p}")) for p in patterns_week]

    elif user_message.startswith("びん缶:"):
        bc_str = user_message.split(":")[1][0]
        bottle_can_day = [day_map[bc_str]]
        if user_id not in USER_SETTINGS: USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["bottle_can"] = bottle_can_day
        
        reply_text = f"びん・缶・ペットボトル（{bc_str}曜）を設定しました。\n次に「雑がみ・紙類」の曜日を選んでください！"
        quick_reply_items = [QuickReplyItem(action=MessageAction(label=p, text=f"雑がみ曜日:{p}")) for p in patterns_week]

    elif user_message.startswith("雑がみ曜日:"):
        r_str = user_message.split(":")[1][0]
        resource_day = [day_map[r_str]]
        if user_id not in USER_SETTINGS: USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["paper"] = resource_day
        
        reply_text = f"雑がみ・紙類（{r_str}曜）を設定しました。\n収集の頻度を選んでください！"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label="毎週", text="雑がみ頻度:毎週")),
            QuickReplyItem(action=MessageAction(label="第1・第3週のみ（隔週）", text="雑がみ頻度:第1・第3")),
            QuickReplyItem(action=MessageAction(label="第2・第4週のみ（隔週）", text="雑がみ頻度:第2・第4"))
        ]

    elif user_message.startswith("雑がみ頻度:"):
        freq = user_message.split(":")[1]
        if user_id not in USER_SETTINGS: USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["paper_week"] = freq
        
        reply_text = "🎉 すべての設定が完了しました！\n何か文字（「あ」など）を送ればいつでも3日分の天気とゴミの日を確認できます。"

    else:
        if user_id in USER_SETTINGS and "paper_week" in USER_SETTINGS[user_id]:
            msg_text = get_weather_and_garbage(user_id)
            reply_text = msg_text if msg_text else "データの取得に失敗しました。"
        else:
            reply_text = "地域を設定しましょう！\n下のボタンを押すか、「初期設定」と送ってください。"
            quick_reply_items = [QuickReplyItem(action=MessageAction(label="⚙️ 初期設定を始める", text="初期設定"))]

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        q_reply = QuickReply(items=quick_reply_items) if quick_reply_items else None
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text, quick_reply=q_reply)])
        )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)

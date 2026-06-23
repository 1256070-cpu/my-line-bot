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

def judge_garbage(target_date, settings):
    w_idx = target_date.weekday()
    nth_week = get_nth_week(target_date)
    g_list = []
    
    burnable_days = settings.get("burnable", [])
    plastic_days = settings.get("plastic", [])
    bottle_can_days = settings.get("bottle_can", [])
    paper_days = settings.get("paper", [])
    paper_week = settings.get("paper_week", "毎週")
    
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

def get_weather_and_garbage(user_id, is_tomorrow=False):
    settings = USER_SETTINGS.get(user_id)
    if not settings or "push_time" not in settings:
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
    except Exception:
        return f"【{area_name}の案内や！】\n天気のデータ、上手く取れんかったわ！すまんな！"
        
    try:
        weathers = data[0]["timeSeries"][0]["areas"][0]["weathers"]
        today_w = weathers[0].replace("\u3000", " ")
        tomorrow_w = weathers[1].replace("\u3000", " ") if len(weathers) > 1 else "わからん"
    except Exception:
        today_w, tomorrow_w = "データなし", "データなし"
        
    temp_text_today = ""
    temp_text_tomorrow = ""
    try:
        for ts in data[0]["timeSeries"]:
            if "temps" in ts:
                temps = ts["temps"]
                if len(temps) >= 2:
                    temp_text_today = f" (気温: {temps[0]}℃〜{temps[1]}℃)"
                if len(temps) >= 4:
                    temp_text_tomorrow = f" (気温: {temps[2]}℃〜{temps[3]}℃)"
                break
    except Exception:
        pass

    tz = zoneinfo.ZoneInfo("Asia/Tokyo")
    now_tokyo = datetime.now(tz)
    weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
    
    if is_tomorrow:
        target_date = now_tokyo + timedelta(days=1)
        lines = [
            f"【{area_name}の夜回りやでぇ！】",
            "夜遅くにすまんな！明日のゴミ出しの準備はできとるか？\n",
            f"📅明日 ({weekdays_ja[target_date.weekday()]}): {tomorrow_w}{temp_text_tomorrow}",
            f" ┗ 出すゴミ: {judge_garbage(target_date, settings)}\n",
            "うかうかしとったら、明日の朝ゴミ出し遅れるでぇ！",
            "準備できたら下のボタン押しや！"
        ]
    else:
        target_date = now_tokyo
        lines = [
            f"【{area_name}の朝の挨拶やでぇ！】",
            "おっしゃ、今日の天気とゴミ情報教えたるわ！おんどれ起きや！\n",
            f"📅今日 ({weekdays_ja[target_date.weekday()]}): {today_w}{temp_text_today}",
            f" ┗ 出すゴミ: {judge_garbage(target_date, settings)}\n",
            "しっかりゴミ出して、シャキッと働きや！",
            "出したら下のボタン押しや！"
        ]
        
    return "\n".join(lines)

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
    tz = zoneinfo.ZoneInfo("Asia/Tokyo")
    current_hour = datetime.now(tz).hour
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        for user_id, settings in USER_SETTINGS.items():
            push_time = settings.get("push_time")
            if not push_time:
                continue
                
            is_match = False
            is_tomorrow = False
            
            if push_time.startswith("前日夜"):
                target_hour = int(push_time.replace("前日夜:", "").replace("時", ""))
                if current_hour == target_hour:
                    is_match = True
                    is_tomorrow = True
            elif push_time.startswith("当日朝"):
                target_hour = int(push_time.replace("当日朝:", "").replace("時", ""))
                if current_hour == target_hour:
                    is_match = True
                    
            if is_match:
                msg_text = get_weather_and_garbage(user_id, is_tomorrow=is_tomorrow)
                if msg_text:
                    try:
                        quick_reply_items = [QuickReplyItem(action=MessageAction(label="👍 出したで！", text="ゴミ出したで！"))]
                        line_bot_api.push_message(
                            PushMessageRequest(
                                to=user_id, 
                                messages=[TextMessage(text=msg_text, quick_reply=QuickReply(items=quick_reply_items))]
                            )
                        )
                    except Exception as e:
                        print(f"Push failed for {user_id}: {e}")
    return 'Push Sent'

@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    reply_text = "自分、登録してくれたんか！ありがとなぁ！🎉\nここはウチがおんどれの地域の「天気」と「ゴミの日」をまとめて教えたる場所や。\n\nまずは下のボタン押して、設定から始めよかぇ！"
    quick_reply_items = [QuickReplyItem(action=MessageAction(label="⚙️ 設定を始めるんや！", text="初期設定"))]
    
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

    if user_message == "ゴミ出したで！":
        reply_text = "おぅ、ちゃんと出せたみたいやな。明日も遅れんとキリキリ働きや！"

    elif user_message in ["初期設定", "設定"]:
        reply_text = "おんどれの住んどる地域はどっちや？選べや！"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label="札幌市や", text="地域選択:札幌市")),
            QuickReplyItem(action=MessageAction(label="他の市町村や（根室とか）", text="地域選択:その他"))
        ]
        
    elif user_message == "地域選択:札幌市":
        reply_text = "お住まいの「区」をきっちり選びや！"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=ward, text=f"区選択:{ward}")) for ward in SAPPORO_WARDS
        ]
        
    elif user_message == "地域選択:その他":
        reply_text = "おんどれの市町村名を「根室市」とか「旭川市」みたいに直接チャットで打ち込んで送りや！"

    elif any(user_message.endswith(s) for s in ["市", "町", "村"]) and not user_message.startswith("区選択:"):
        USER_SETTINGS[user_id] = {"area": user_message}
        reply_text = f"【{user_message}】で頭に叩き込んだわ！\n次は「燃やせるゴミ」の曜日を教えや！"
        patterns = ["月・木", "火・金", "水・土", "月・水・金", "火・木・土"]
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=p, text=f"燃やせる:{p}")) for p in patterns
        ]

    elif user_message.startswith("区選択:"):
        ward = user_message.split(":")[1]
        USER_SETTINGS[user_id] = {"area": f"札幌市{ward}"}
        reply_text = f"【札幌市{ward}】で頭に叩き込んだわ！\n次は「燃やせるゴミ」の曜日を教えや！"
        patterns = ["月・木", "火・金", "水・土"]
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label=p, text=f"燃やせる:{p}")) for p in patterns
        ]

    elif user_message.startswith("燃やせる:"):
        p_str = user_message.split(":")[1]
        burnable_days = [day_map[char] for char in p_str if char in day_map]
        if user_id not in USER_SETTINGS: USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["burnable"] = burnable_days
        
        reply_text = f"燃やせるゴミは（{p_str}）やな！了解や！\n次は「容器包装プラスチック」の曜日を選びや！"
        quick_reply_items = [QuickReplyItem(action=MessageAction(label=p, text=f"プラ:{p}")) for p in patterns_week]

    elif user_message.startswith("プラ:"):
        p_str = user_message.split(":")[1][0]
        plastic_day = [day_map[p_str]]
        if user_id not in USER_SETTINGS: USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["plastic"] = plastic_day
        
        reply_text = f"プラスチックは（{p_str}曜）やな！\nおっしゃ、次は「びん・缶・ペットボトル」の曜日や！"
        quick_reply_items = [QuickReplyItem(action=MessageAction(label=p, text=f"びん缶:{p}")) for p in patterns_week]

    elif user_message.startswith("びん缶:"):
        bc_str = user_message.split(":")[1][0]
        bottle_can_day = [day_map[bc_str]]
        if user_id not in USER_SETTINGS: USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["bottle_can"] = bottle_can_day
        
        reply_text = f"びん缶ペットは（{bc_str}曜）やな、覚えたで！\nほな、最後に「雑がみ・紙類」の曜日を選んでや！"
        quick_reply_items = [QuickReplyItem(action=MessageAction(label=p, text=f"雑がみ曜日:{p}")) for p in patterns_week]

    elif user_message.startswith("雑がみ曜日:"):
        r_str = user_message.split(":")[1][0]
        resource_day = [day_map[r_str]]
        if user_id not in USER_SETTINGS: USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["paper"] = resource_day
        
        reply_text = f"雑がみは（{r_str}曜）やな！\nこれ、収集のペースはどんなもんや？"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label="毎週や！", text="雑がみ頻度:毎週")),
            QuickReplyItem(action=MessageAction(label="第1・第3週だけや！", text="雑がみ頻度:第1・第3")),
            QuickReplyItem(action=MessageAction(label="第2・第4週だけや！", text="雑がみ頻度:第2・第4"))
        ]

    elif user_message.startswith("雑がみ頻度:"):
        freq = user_message.split(":")[1]
        if user_id not in USER_SETTINGS: USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["paper_week"] = freq
        
        reply_text = "ほな、最後に通知するタイミングを選びや！\n「前日の夜」か「当日の朝」か、どっちがええ？"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label="🌙 前日の夜にするわ", text="通知タイプ:夜")),
            QuickReplyItem(action=MessageAction(label="☀️ 当日の朝にするわ", text="通知タイプ:朝"))
        ]

    elif user_message == "通知タイプ:夜":
        reply_text = "前日の夜やな！何時頃に鳴らしたらええ？"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label="20:00頃", text="通知時間:前日夜:20時")),
            QuickReplyItem(action=MessageAction(label="21:00頃", text="通知時間:前日夜:21時")),
            QuickReplyItem(action=MessageAction(label="22:00頃", text="通知時間:前日夜:22時"))
        ]

    elif user_message == "通知タイプ:朝":
        reply_text = "当日の朝やな！何時頃に起こしたらええ？"
        quick_reply_items = [
            QuickReplyItem(action=MessageAction(label="06:00頃", text="通知時間:当日朝:6時")),
            QuickReplyItem(action=MessageAction(label="07:00頃", text="通知時間:当日朝:7時")),
            QuickReplyItem(action=MessageAction(label="08:00頃", text="通知時間:当日朝:8時"))
        ]

    elif user_message.startswith("通知時間:"):
        time_setting = user_message.replace("通知時間:", "")
        if user_id not in USER_SETTINGS: USER_SETTINGS[user_id] = {"area": "札幌市北区"}
        USER_SETTINGS[user_id]["push_time"] = time_setting
        
        reply_text = "🎉 おっしゃ！これですべての設定が完了やでぇ！\n選んでもらった時間帯にウチからきっちり連絡入れたるからな！気ぃ引き締めや！"

    else:
        if user_id in USER_SETTINGS and "push_time" in USER_SETTINGS[user_id]:
            is_tomorrow = USER_SETTINGS[user_id]["push_time"].startswith("前日夜")
            msg_text = get_weather_and_garbage(user_id, is_tomorrow=is_tomorrow)
            reply_text = msg_text if msg_text else "データうまく取れんかったわ、すまんな！"
        else:
            reply_text = "地域の設定がまだやで！\n下のボタン押すか、「初期設定」って送って設定しぃや！"
            quick_reply_items = [QuickReplyItem(action=MessageAction(label="⚙️ 設定を始めるんや！", text="初期設定"))]

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        q_reply = QuickReply(items=quick_reply_items) if quick_reply_items else None
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text, quick_reply=q_reply)])
        )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)

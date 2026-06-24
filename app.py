import os
import sys
import requests
from datetime import datetime, timedelta
import zoneinfo
import psycopg2
from psycopg2.extras import DictCursor
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
db_url = os.environ.get('DATABASE_URL')

if not channel_secret or not channel_access_token or not db_url:
    print('Specify LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN and DATABASE_URL.')
    sys.exit(1)

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

REGION_CODES = {
    "札幌": "https://www.jma.go.jp/bosai/forecast/data/forecast/016000.json",
    "根室": "https://www.jma.go.jp/bosai/forecast/data/forecast/014100.json",
    "旭川": "https://www.jma.go.jp/bosai/forecast/data/forecast/012000.json",
    "函館": "https://www.jma.go.jp/bosai/forecast/data/forecast/017000.json",
    "東京": "https://www.jma.go.jp/bosai/forecast/data/forecast/130000.json",
    "大阪": "https://www.jma.go.jp/bosai/forecast/data/forecast/270000.json"
}

SAPPORO_WARDS = ["中央区", "北区", "東区", "白石区", "厚別区", "豊平区", "清田区", "南区", "西区", "手稲区"]

def init_db():
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            area TEXT,
            burnable INT[],
            plastic INT[],
            bottle_can INT[],
            paper INT[],
            paper_week TEXT,
            push_time TEXT
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

def load_settings(user_id):
    conn = psycopg2.connect(db_url)
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s;", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return dict(row)
    return None

def save_settings(user_id, key, value):
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (user_id, {0}) VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET {0} = EXCLUDED.{0};
    """.format(key), (user_id, value))
    conn.commit()
    cur.close()
    conn.close()

def get_nth_week(target_date):
    first_day = target_date.replace(day=1)
    adjusted_dom = target_date.day + first_day.weekday()
    return (adjusted_dom - 1) // 7 + 1

def judge_garbage(target_date, settings):
    w_idx = target_date.weekday()
    nth_week = get_nth_week(target_date)
    g_list = []
    
    burnable_days = settings.get("burnable") or []
    plastic_days = settings.get("plastic") or []
    bottle_can_days = settings.get("bottle_can") or []
    paper_days = settings.get("paper") or []
    paper_week = settings.get("paper_week") or "毎週"
    
    if w_idx in burnable_days: 
        g_list.append("🔥燃やせるゴミ")
    if w_idx in plastic_days: 
        g_list.append("♻️容器包装プラスチック")
    if w_idx in bottle_can_days: 
        g_list.append("🍾びん・缶・ペット（※スプレー缶・電池もここや！）")
        
    if w_idx in paper_days:
        if paper_week == "毎週": 
            g_list.append("📰雑がみ・紙類")
        elif paper_week == "第1・第3" and nth_week in [1, 3]: 
            g_list.append("📰雑がみ（第1・3週）")
        elif paper_week == "第2・第4" and nth_week in [2, 4]: 
            g_list.append("📰雑がみ（第2・4週）")
        
    return "・".join(g_list) if g_list else "❌定期回収のゴミはないわ！"

def get_majima_notice():
    return "\n⚠️あとなぁ！月1回の「燃やせないゴミ」とか期間限定の「枝・葉・草」みたいなレアなやつは、ウチの通知をアテにせんと自分でカレンダー確認して出しにいきや！忘れたら承知せんでぇ！"

def get_weather_and_garbage(user_id, is_tomorrow=False):
    settings = load_settings(user_id)
    if not settings or not settings.get("push_time"):
        return None
        
    area_name = settings.get("area") or "札幌市北区"
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
                if len(temps) >= 2: temp_text_today = f" (気温: {temps[0]}℃〜{temps[1]}℃)"
                if len(temps) >= 4: temp_text_tomorrow = f" (気温: {temps[2]}℃〜{temps[3]}℃)"
                break
    except Exception:
        pass

    tz = zoneinfo.ZoneInfo("Asia/Tokyo")
    now_tokyo = datetime.now(tz)
    weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
    
    if is_tomorrow:
        target_date = now_tokyo + timedelta(days=1)
        lines = [
            f"【{area_name}の夜回りやてぇ！】",
            "夜遅くにすまんな！明日のゴミ出しの準備はできとるか？\n",
            f"📅明日 ({weekdays_ja[target_date.weekday()]}): {tomorrow_w}{temp_text_tomorrow}",
            f" ┗ 出すゴミ: {judge_garbage(target_date, settings)}\n",
            "うかうかしとったら、明日の朝ゴミ出し遅れるでぇ！",
            get_majima_notice(),
            "\n準備できたら下のボタン押しや！"
        ]
    else:
        target_date = now_tokyo
        lines = [
            f"【{area_name}の朝の挨拶やてぇ！】",
            "おっしゃ、今日の天気とゴミ情報教えたるわ！おんどれ起きや！\n",
            f"📅今日 ({weekdays_ja[target_date.weekday()]}): {today_w}{temp_text_today}",
            f" ┗ 出すゴミ: {judge_garbage(target_date, settings)}\n",
            "しっかりゴミ出して、シャキッと働きや！",
            get_majima_notice(),
            "\n出したら下のボタン押しや！"
        ]
        
    return "\n".join(lines)

def get_anytime_info(user_id, target_day_str="全部"):
    settings = load_settings(user_id)
    if not settings or not settings.get("push_time"):
        return None
        
    area_name = settings.get("area") or "札幌市北区"
    url = "https://www.jma.go.jp/bosai/forecast/data/forecast/016000.json"
    for key, value in REGION_CODES.items():
        if key in area_name:
            url = value
            break

    try:
        res = requests.get(url)
        data = res.json() if res.status_code == 200 else None
    except Exception:
        data = None

    today_w, tomorrow_w, day_after_w = "データなし", "データなし", "データなし"
    temp_today, temp_tomorrow = "", ""
    
    if data:
        try:
            weathers = data[0]["timeSeries"][0]["areas"][0]["weathers"]
            today_w = weathers[0].replace("\u3000", " ")
            tomorrow_w = weathers[1].replace("\u3000", " ") if len(weathers) > 1 else "わからん"
            day_after_w = weathers[2].replace("\u3000", " ") if len(weathers) > 2 else "わからん"
            
            for ts in data[0]["timeSeries"]:
                if "temps" in ts:
                    temps = ts["temps"]
                    if len(temps) >= 2: temp_today = f" ({temps[0]}℃〜{temps[1]}℃)"
                    if len(temps) >= 4: temp_tomorrow = f" ({temps[2]}℃〜{temps[3]}℃)"
                    break
        except Exception:
            pass

    tz = zoneinfo.ZoneInfo("Asia/Tokyo")
    now_tokyo = datetime.now(tz)
    weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
    
    d0 = now_tokyo
    d1 = now_tokyo + timedelta(days=1)
    d2 = now_tokyo + timedelta(days=2)
    
    notice = get_majima_notice()
    
    if target_day_str == "今日":
        return f"【{area_name}：今日の情報や！】\n📅今日 ({weekdays_ja[d0.weekday()]}): {today_w}{temp_today}\n ┗ ゴミ: {judge_garbage(d0, settings)}\n{notice}"
    elif target_day_str == "明日":
        return f"【{area_name}：明日の情報や！】\n📅明日 ({weekdays_ja[d1.weekday()]}): {tomorrow_w}{temp_tomorrow}\n ┗ ゴミ: {judge_garbage(d1, settings)}\n{notice}"
    elif target_day_str == "明後日":
        return f"【{area_name}：明後日の情報や！】\n📅明後日 ({weekdays_ja[d2.weekday()]}): {day_after_w}\n ┗ ゴミ: {judge_garbage(d2, settings)}\n{notice}"
    else:
        lines = [
            f"【{area_name}のご案内や！】",
            f"📅今日 ({weekdays_ja[d0.weekday()]}): {today_w}{temp_today}\n ┗ ゴミ: {judge_garbage(d0, settings)}",
            f"📅明日 ({weekdays_ja[d1.weekday()]}):

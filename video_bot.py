# main.py
import sqlite3
import datetime
import requests
import time
import json
import os
from collections import defaultdict

# 配置参数 - 使用环境变量
TOKEN = os.environ.get("BOT_TOKEN", "8383996095:AAFp9x0Wyu-25qCTnoVRKSrnFYA1uiQloE0")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8521105475"))
VIDEO_PRICE = int(os.environ.get("VIDEO_PRICE", "20"))
DAILY_POINTS = int(os.environ.get("DAILY_POINTS", "20"))

# 频道配置
REQUIRED_CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@Mingming_Kindergarten")
REQUIRED_CHANNEL_ID = os.environ.get("CHANNEL_ID", "-1002030634486")

# 临时存储
pending_videos = {}
editing_video = {}
user_pagination = {}
user_last_message = {}

# 限流配置
RATE_LIMIT = 15
RATE_LIMIT_WINDOW = 60
user_rate_limit = defaultdict(list)

# 全局变量
PROXY = None

API_URL = f"https://api.telegram.org/bot{TOKEN}/"

# 数据库路径（Railway 磁盘持久化）
DB_PATH = os.environ.get("DB_PATH", "/app/data/user_data.db")

def init_db():
    """初始化数据库"""
    # 确保数据目录存在
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  first_name TEXT,
                  points INTEGER DEFAULT 0,
                  last_checkin DATE,
                  videos_exchanged INTEGER DEFAULT 0,
                  joined_channel INTEGER DEFAULT 0,
                  last_check TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS videos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT,
                  file_id TEXT,
                  description TEXT,
                  price INTEGER DEFAULT 100,
                  duration INTEGER,
                  is_available INTEGER DEFAULT 1,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS exchanges
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  video_id INTEGER,
                  video_title TEXT,
                  exchange_date DATE,
                  points_spent INTEGER)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS points_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  admin_id INTEGER,
                  old_points INTEGER,
                  new_points INTEGER,
                  change_amount INTEGER,
                  reason TEXT,
                  change_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # 检查并添加可能缺失的列
    try:
        c.execute("ALTER TABLE users ADD COLUMN joined_channel INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    try:
        c.execute("ALTER TABLE users ADD COLUMN last_check TIMESTAMP")
    except sqlite3.OperationalError:
        pass
    
    try:
        c.execute("ALTER TABLE videos ADD COLUMN duration INTEGER")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()
    print(f"✅ 数据库初始化成功，路径: {DB_PATH}")

def check_rate_limit(user_id):
    """检查用户是否超过限流"""
    now = time.time()
    user_rate_limit[user_id] = [t for t in user_rate_limit[user_id] if now - t < RATE_LIMIT_WINDOW]
    
    if len(user_rate_limit[user_id]) >= RATE_LIMIT:
        oldest = min(user_rate_limit[user_id])
        wait_time = int(RATE_LIMIT_WINDOW - (now - oldest)) + 1
        return False, wait_time
    
    user_rate_limit[user_id].append(now)
    return True, 0

def delete_message(chat_id, message_id):
    """删除消息"""
    url = API_URL + 'deleteMessage'
    data = {'chat_id': chat_id, 'message_id': message_id}
    
    try:
        if PROXY:
            response = requests.post(url, data=data, timeout=10, proxies=PROXY)
        else:
            response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"删除消息失败: {e}")
        return False

def edit_message(chat_id, message_id, text, reply_markup=None):
    """编辑消息"""
    url = API_URL + 'editMessageText'
    data = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        data['reply_markup'] = reply_markup
    
    try:
        if PROXY:
            response = requests.post(url, data=data, timeout=30, proxies=PROXY)
        else:
            response = requests.post(url, data=data, timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"编辑消息失败: {e}")
        return False

def send_message(chat_id, text, reply_markup=None, delete_old=False):
    """发送消息"""
    allowed, wait_time = check_rate_limit(chat_id)
    if not allowed:
        send_simple_message(chat_id, f"⚠️ 操作过于频繁，请 {wait_time} 秒后再试")
        return None
    
    url = API_URL + 'sendMessage'
    data = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        data['reply_markup'] = reply_markup
    
    try:
        if PROXY:
            response = requests.post(url, data=data, timeout=30, proxies=PROXY)
        else:
            response = requests.post(url, data=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            message_id = result.get('result', {}).get('message_id')
            
            if delete_old and chat_id in user_last_message:
                old_msg_id = user_last_message[chat_id]
                if old_msg_id and old_msg_id != message_id:
                    delete_message(chat_id, old_msg_id)
            
            if message_id:
                user_last_message[chat_id] = message_id
            return message_id
        return None
    except Exception as e:
        print(f"发送消息异常: {e}")
        return None

def send_simple_message(chat_id, text, reply_markup=None):
    """发送简单消息"""
    url = API_URL + 'sendMessage'
    data = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        data['reply_markup'] = reply_markup
    
    try:
        if PROXY:
            response = requests.post(url, data=data, timeout=30, proxies=PROXY)
        else:
            response = requests.post(url, data=data, timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"发送消息异常: {e}")
        return False

def send_video(chat_id, video_file_id, caption):
    """发送视频"""
    url = API_URL + 'sendVideo'
    data = {'chat_id': chat_id, 'video': video_file_id, 'caption': caption}
    
    try:
        if PROXY:
            response = requests.post(url, data=data, timeout=60, proxies=PROXY)
        else:
            response = requests.post(url, data=data, timeout=60)
        return response.status_code == 200
    except Exception as e:
        print(f"发送视频异常: {e}")
        return False

def get_or_create_user(user_id, username, first_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    
    if not user:
        c.execute("INSERT INTO users (user_id, username, first_name, points, joined_channel, last_check) VALUES (?, ?, ?, ?, ?, ?)",
                 (user_id, username or "", first_name or "", 0, 1, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    
    conn.close()

def add_video_to_db(file_id, title, price, description="", duration=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("INSERT INTO videos (title, file_id, description, price, duration) VALUES (?, ?, ?, ?, ?)",
             (title, file_id, description, price, duration))
    conn.commit()
    video_id = c.lastrowid
    conn.close()
    
    return video_id

def update_video_info(video_id, title=None, price=None, description=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    updates = []
    params = []
    
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if price is not None:
        updates.append("price = ?")
        params.append(price)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    
    if updates:
        query = f"UPDATE videos SET {', '.join(updates)} WHERE id = ?"
        params.append(video_id)
        c.execute(query, params)
        conn.commit()
    
    conn.close()
    return True

def checkin(chat_id, user_id, username, first_name):
    get_or_create_user(user_id, username, first_name)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    today = datetime.date.today()
    
    c.execute("SELECT last_checkin, points FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    
    if result and result[0] == str(today):
        send_simple_message(chat_id, f"❌ 你今天已经签过到了！\n当前积分：{result[1]} 积分\n明天再来吧~")
        conn.close()
        return
    
    points_to_add = DAILY_POINTS
    
    if result:
        new_points = result[1] + points_to_add
        c.execute("UPDATE users SET points = ?, last_checkin = ? WHERE user_id = ?",
                 (new_points, str(today), user_id))
    else:
        new_points = points_to_add
        c.execute("INSERT INTO users (user_id, username, first_name, points, last_checkin, joined_channel) VALUES (?, ?, ?, ?, ?, 1)",
                 (user_id, username or "", first_name or "", points_to_add, str(today)))
    
    conn.commit()
    conn.close()
    
    message = f"✅ 签到成功！\n获得 {points_to_add} 积分\n当前总积分：{new_points} 积分\n\n💡 使用 /videos 查看可兑换视频"
    send_simple_message(chat_id, message)

def show_points(chat_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT points, videos_exchanged FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        points, videos_exchanged = result
        message = (f"💰 你的账户信息：\n\n"
                  f"积分余额：{points} 积分\n"
                  f"已兑换视频：{videos_exchanged} 个\n"
                  f"兑换所需：{VIDEO_PRICE} 积分/个\n\n"
                  f"💡 每日签到可获得 {DAILY_POINTS} 积分")
        send_simple_message(chat_id, message)
    else:
        send_simple_message(chat_id, f"📝 你还没有积分，请使用 /checkin 签到获取积分！")

def show_videos(chat_id, user_id, page=1, message_id=None):
    allowed, wait_time = check_rate_limit(chat_id)
    if not allowed:
        send_simple_message(chat_id, f"⚠️ 操作过于频繁，请 {wait_time} 秒后再试")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    user_points_result = c.fetchone()
    user_points = user_points_result[0] if user_points_result else 0
    
    c.execute("SELECT COUNT(*) FROM videos WHERE is_available = 1")
    total_videos = c.fetchone()[0]
    
    if total_videos == 0:
        send_simple_message(chat_id, "📭 暂无可用视频\n请稍后再来查看")
        conn.close()
        return
    
    videos_per_page = 5
    total_pages = (total_videos + videos_per_page - 1) // videos_per_page
    
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    
    offset = (page - 1) * videos_per_page
    
    c.execute("SELECT id, title, price, file_id FROM videos WHERE is_available = 1 ORDER BY id DESC LIMIT ? OFFSET ?",
             (videos_per_page, offset))
    videos_list = c.fetchall()
    conn.close()
    
    keyboard = []
    for video in videos_list:
        video_id, title, price, file_id = video
        status = "✅" if user_points >= price else "🔒"
        row = [
            {"text": f"{status} {title} ({price}积分)", "callback_data": f"none"},
            {"text": "💰 兑换", "callback_data": f"exchange_{video_id}"}
        ]
        keyboard.append(row)
    
    nav_row = []
    if page > 1:
        nav_row.append({"text": "◀️ 上一页", "callback_data": f"videos_page_{page - 1}"})
    nav_row.append({"text": f"📄 {page}/{total_pages}", "callback_data": "none"})
    if page < total_pages:
        nav_row.append({"text": "下一页 ▶️", "callback_data": f"videos_page_{page + 1}"})
    keyboard.append(nav_row)
    
    keyboard.append([{"text": "🔄 刷新列表", "callback_data": f"refresh_videos_{page}"}])
    
    reply_markup = json.dumps({"inline_keyboard": keyboard})
    
    message_text = f"📺 视频列表 (第{page}/{total_pages}页)\n你的积分：{user_points} 积分\n\n点击「兑换」可使用积分兑换完整视频"
    
    if message_id:
        edit_message(chat_id, message_id, message_text, reply_markup)
    else:
        old_msg_id = user_last_message.get(chat_id)
        if old_msg_id:
            delete_message(chat_id, old_msg_id)
        new_msg_id = send_message(chat_id, message_text, reply_markup)
        if new_msg_id:
            user_last_message[chat_id] = new_msg_id
    
    user_pagination[user_id] = page

def exchange_video(chat_id, user_id, video_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT title, file_id, price, description FROM videos WHERE id = ? AND is_available = 1", (video_id,))
    video = c.fetchone()
    
    if not video:
        send_simple_message(chat_id, "❌ 视频不存在或已下架")
        conn.close()
        return
    
    video_title, video_file_id, video_price, video_desc = video
    
    c.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    
    if not result:
        send_simple_message(chat_id, f"❌ 请先使用 /checkin 签到获取积分！")
        conn.close()
        return
    
    user_points = result[0]
    
    if user_points < video_price:
        send_simple_message(chat_id, f"❌ 积分不足！\n需要：{video_price} 积分\n当前：{user_points} 积分\n差额：{video_price - user_points} 积分\n\n💡 每日签到可获得 {DAILY_POINTS} 积分")
        conn.close()
        return
    
    new_points = user_points - video_price
    today = datetime.date.today()
    
    try:
        c.execute("UPDATE users SET points = ?, videos_exchanged = videos_exchanged + 1 WHERE user_id = ?",
                 (new_points, user_id))
        c.execute("INSERT INTO exchanges (user_id, video_id, video_title, exchange_date, points_spent) VALUES (?, ?, ?, ?, ?)",
                 (user_id, video_id, video_title, str(today), video_price))
        conn.commit()
        
        send_simple_message(chat_id, f"✅ 兑换成功！\n\n📹 视频：{video_title}\n💰 花费：{video_price} 积分\n💎 剩余积分：{new_points} 积分\n\n正在发送完整视频...")
        
        caption = f"🎉 你兑换的视频：{video_title}\n\n{video_desc if video_desc else '感谢你的支持！'}\n\n💡 使用 /videos 继续兑换更多视频"
        send_video(chat_id, video_file_id, caption)
        
    except Exception as e:
        conn.rollback()
        send_simple_message(chat_id, f"❌ 兑换失败：{str(e)}")
    finally:
        conn.close()

def show_history(chat_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''SELECT video_title, exchange_date, points_spent 
                 FROM exchanges 
                 WHERE user_id = ? 
                 ORDER BY exchange_date DESC LIMIT 20''', (user_id,))
    
    records = c.fetchall()
    conn.close()
    
    if not records:
        send_simple_message(chat_id, "📝 你还没有兑换过任何视频\n使用 /videos 查看可兑换视频")
        return
    
    message = "📜 你的兑换记录：\n\n"
    total_spent = 0
    for i, record in enumerate(records, 1):
        message += f"{i}. {record[0]}\n   时间：{record[1]}\n   花费：{record[2]}积分\n\n"
        total_spent += record[2]
    
    message += f"📊 总计花费：{total_spent} 积分\n"
    message += f"💡 共兑换 {len(records)} 个视频"
    
    send_simple_message(chat_id, message)

def show_leaderboard(chat_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT first_name, username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 10")
    points_leaders = c.fetchall()
    
    c.execute("SELECT first_name, username, videos_exchanged FROM users WHERE videos_exchanged > 0 ORDER BY videos_exchanged DESC LIMIT 10")
    exchange_leaders = c.fetchall()
    
    conn.close()
    
    message = "🏆 积分排行榜 TOP 10 🏆\n\n"
    
    if points_leaders:
        for i, (first_name, username, points) in enumerate(points_leaders, 1):
            display_name = first_name if first_name else (username if username else f"用户{i}")
            if len(display_name) > 15:
                display_name = display_name[:12] + "..."
            message += f"{i}. {display_name} - {points} 积分\n"
    else:
        message += "暂无数据\n"
    
    message += "\n🎬 兑换排行榜 TOP 10 🎬\n\n"
    
    if exchange_leaders:
        for i, (first_name, username, videos) in enumerate(exchange_leaders, 1):
            display_name = first_name if first_name else (username if username else f"用户{i}")
            if len(display_name) > 15:
                display_name = display_name[:12] + "..."
            message += f"{i}. {display_name} - {videos} 个视频\n"
    else:
        message += "暂无数据"
    
    send_simple_message(chat_id, message)

def remove_video(chat_id, user_id, args):
    if user_id != ADMIN_ID:
        send_simple_message(chat_id, "❌ 你没有权限使用此命令")
        return
    
    if len(args) < 1:
        send_simple_message(chat_id, "使用方法：/removevideo 视频ID")
        return
    
    try:
        video_id = int(args[0])
    except:
        send_simple_message(chat_id, "❌ 视频ID必须是数字")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE videos SET is_available = 0 WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()
    
    send_simple_message(chat_id, f"✅ 视频 ID {video_id} 已下架")

def restore_video(chat_id, user_id, video_id):
    if user_id != ADMIN_ID:
        send_simple_message(chat_id, "❌ 你没有权限使用此命令")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE videos SET is_available = 1 WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()
    
    send_simple_message(chat_id, f"✅ 视频 ID {video_id} 已重新上架")

def change_video_price(chat_id, user_id, video_id, new_price):
    if user_id != ADMIN_ID:
        send_simple_message(chat_id, "❌ 你没有权限使用此命令")
        return False
    
    if new_price < 0:
        send_simple_message(chat_id, "❌ 价格不能为负数")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT title, price FROM videos WHERE id = ?", (video_id,))
    video = c.fetchone()
    
    if not video:
        send_simple_message(chat_id, f"❌ 视频 ID {video_id} 不存在")
        conn.close()
        return False
    
    old_price = video[1]
    c.execute("UPDATE videos SET price = ? WHERE id = ?", (new_price, video_id))
    conn.commit()
    conn.close()
    
    send_simple_message(chat_id, f"✅ 视频价格已修改！\n\n📹 视频：{video[0]}\n💰 原价格：{old_price} 积分\n💰 新价格：{new_price} 积分")
    return True

def edit_video_info(chat_id, user_id, video_id):
    if user_id != ADMIN_ID:
        send_simple_message(chat_id, "❌ 你没有权限使用此命令")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, title, price, description, is_available FROM videos WHERE id = ?", (video_id,))
    video = c.fetchone()
    conn.close()
    
    if not video:
        send_simple_message(chat_id, f"❌ 视频 ID {video_id} 不存在")
        return
    
    editing_video[user_id] = {
        'video_id': video_id,
        'step': 'waiting_field'
    }
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "📝 修改标题", "callback_data": f"edit_title_{video_id}"}],
            [{"text": "💰 修改价格", "callback_data": f"edit_price_{video_id}"}],
            [{"text": "📄 修改描述", "callback_data": f"edit_desc_{video_id}"}],
            [{"text": "❌ 取消编辑", "callback_data": "cancel_edit"}]
        ]
    }
    
    status = "✅ 上架" if video[4] == 1 else "❌ 下架"
    message = f"✏️ 编辑视频信息\n\n"
    message += f"ID：{video[0]}\n"
    message += f"标题：{video[1]}\n"
    message += f"价格：{video[2]} 积分\n"
    message += f"描述：{video[3] if video[3] else '无'}\n"
    message += f"状态：{status}\n\n"
    message += "请选择要修改的字段："
    
    send_simple_message(chat_id, message, json.dumps(keyboard))

def list_all_videos(chat_id, user_id):
    if user_id != ADMIN_ID:
        send_simple_message(chat_id, "❌ 你没有权限使用此命令")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, title, price, is_available, created_at, description FROM videos ORDER BY id DESC")
    videos = c.fetchall()
    conn.close()
    
    if not videos:
        send_simple_message(chat_id, "📭 暂无任何视频")
        return
    
    message = "📋 所有视频列表：\n\n"
    count = 0
    for video in videos:
        status = "✅ 可用" if video[3] == 1 else "❌ 已下架"
        desc_preview = (video[5][:30] + "...") if video[5] and len(video[5]) > 30 else (video[5] if video[5] else "无")
        message += f"ID:{video[0]} | {video[1]}\n"
        message += f"   💰 {video[2]}积分 | {status}\n"
        message += f"   📄 {desc_preview}\n"
        message += f"   📅 {video[4][:10]}\n\n"
        count += 1
        
        if count % 10 == 0:
            send_simple_message(chat_id, message)
            message = "📋 视频列表（续）：\n\n"
    
    if message != "📋 视频列表（续）：\n\n" and message != "📋 所有视频列表：\n\n":
        send_simple_message(chat_id, message)
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "➕ 添加视频", "callback_data": "admin_add_video"}],
            [{"text": "✏️ 编辑视频", "callback_data": "admin_edit_video"}],
            [{"text": "💰 修改价格", "callback_data": "admin_change_price"}],
            [{"text": "❌ 下架视频", "callback_data": "admin_remove_video"}],
            [{"text": "🔄 恢复视频", "callback_data": "admin_restore_video"}]
        ]
    }
    send_simple_message(chat_id, "🔧 视频管理菜单：", json.dumps(keyboard))

def handle_video_upload(chat_id, user_id, file_id, caption=None, duration=None):
    if user_id != ADMIN_ID:
        send_simple_message(chat_id, "❌ 只有管理员可以上传视频")
        return
    
    pending_videos[user_id] = {
        'file_id': file_id,
        'caption': caption,
        'duration': duration,
        'step': 'waiting_title'
    }
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "❌ 取消上传", "callback_data": "cancel_upload"}]
        ]
    }
    
    send_simple_message(chat_id, 
        "📤 收到视频！请按以下格式回复：\n\n"
        "【视频标题】\n"
        "【积分价格】\n"
        "【视频描述（可选）】\n\n"
        "示例：\n"
        "我的精彩视频\n"
        "100\n"
        "这是一个超精彩的视频内容\n\n"
        "回复 /cancel 取消添加",
        json.dumps(keyboard))

def process_video_info(chat_id, user_id, text):
    if user_id not in pending_videos:
        return False
    
    video_info = pending_videos[user_id]
    
    if text.lower() == '/cancel':
        del pending_videos[user_id]
        send_simple_message(chat_id, "❌ 已取消添加视频")
        return True
    
    lines = text.strip().split('\n')
    
    if len(lines) >= 2:
        title = lines[0].strip()
        try:
            price = int(lines[1].strip())
        except:
            send_simple_message(chat_id, "❌ 价格必须是数字！请重新输入：\n【价格】\n例如：100")
            return True
        
        description = '\n'.join(lines[2:]).strip() if len(lines) > 2 else ""
        
        video_id = add_video_to_db(
            video_info['file_id'], 
            title, 
            price, 
            description,
            video_info.get('duration')
        )
        
        success_msg = f"✅ 视频添加成功！\n\n📹 ID：{video_id}\n📝 标题：{title}\n💰 价格：{price} 积分\n📄 描述：{description if description else '无'}"
        send_simple_message(chat_id, success_msg)
        
        del pending_videos[user_id]
        return True
    
    elif text.startswith('/add'):
        parts = text.split(maxsplit=3)
        if len(parts) >= 3:
            title = parts[1]
            try:
                price = int(parts[2])
            except:
                send_simple_message(chat_id, "❌ 价格必须是数字")
                return True
            description = parts[3] if len(parts) > 3 else ""
            
            video_id = add_video_to_db(
                video_info['file_id'], 
                title, 
                price, 
                description,
                video_info.get('duration')
            )
            send_simple_message(chat_id, f"✅ 视频添加成功！\n\n📹 ID：{video_id}\n📝 标题：{title}\n💰 价格：{price} 积分")
            
            del pending_videos[user_id]
            return True
    
    else:
        send_simple_message(chat_id, "❌ 格式错误！请使用以下格式：\n\n"
                           "【视频标题】\n"
                           "【积分价格】\n"
                           "【视频描述（可选）】\n\n"
                           "例如：\n"
                           "我的精彩视频\n"
                           "100\n"
                           "这是一个超精彩的视频\n\n"
                           "或使用：/add 标题 价格 描述\n"
                           "回复 /cancel 取消")
        return True
    
    return False

def handle_callback(chat_id, user_id, callback_data):
    allowed, wait_time = check_rate_limit(user_id)
    if not allowed:
        send_simple_message(chat_id, f"⚠️ 操作过于频繁，请 {wait_time} 秒后再试")
        return True
    
    if callback_data == "cancel_upload":
        if user_id in pending_videos:
            del pending_videos[user_id]
        send_simple_message(chat_id, "❌ 已取消上传")
        return True
    
    elif callback_data == "cancel_edit":
        if user_id in editing_video:
            del editing_video[user_id]
        send_simple_message(chat_id, "❌ 已取消编辑")
        return True
    
    elif callback_data.startswith("exchange_"):
        video_id = int(callback_data.split('_')[1])
        exchange_video(chat_id, user_id, video_id)
        return True
    
    elif callback_data.startswith("videos_page_"):
        page = int(callback_data.split('_')[2])
        current_msg_id = user_last_message.get(chat_id)
        show_videos(chat_id, user_id, page, current_msg_id)
        return True
    
    elif callback_data.startswith("refresh_videos_"):
        page = int(callback_data.split('_')[2])
        current_msg_id = user_last_message.get(chat_id)
        show_videos(chat_id, user_id, page, current_msg_id)
        return True
    
    elif callback_data == "admin_add_video":
        send_simple_message(chat_id, "📹 请直接发送视频文件给我")
        return True
    
    elif callback_data == "admin_edit_video":
        send_simple_message(chat_id, "✏️ 请输入要编辑的视频ID\n\n格式：/editvideo 视频ID")
        return True
    
    elif callback_data == "admin_change_price":
        send_simple_message(chat_id, "💰 请输入要修改价格的视频ID和新价格\n\n格式：/changeprice 视频ID 新价格\n\n示例：/changeprice 5 50")
        return True
    
    elif callback_data == "admin_remove_video":
        send_simple_message(chat_id, "❌ 请输入要下架的视频ID\n\n格式：/removevideo 视频ID")
        return True
    
    elif callback_data == "admin_restore_video":
        send_simple_message(chat_id, "🔄 请输入要恢复上架的视频ID\n\n格式：/restorevideo 视频ID")
        return True
    
    elif callback_data.startswith("edit_title_"):
        video_id = int(callback_data.split('_')[2])
        editing_video[user_id] = {
            'video_id': video_id,
            'field': 'title',
            'step': 'waiting_value'
        }
        send_simple_message(chat_id, f"✏️ 请输入视频的新标题：\n\n当前标题：{get_video_info(video_id, 'title')}\n\n回复 /cancel 取消")
        return True
    
    elif callback_data.startswith("edit_price_"):
        video_id = int(callback_data.split('_')[2])
        editing_video[user_id] = {
            'video_id': video_id,
            'field': 'price',
            'step': 'waiting_value'
        }
        send_simple_message(chat_id, f"💰 请输入视频的新价格：\n\n当前价格：{get_video_info(video_id, 'price')} 积分\n\n回复 /cancel 取消")
        return True
    
    elif callback_data.startswith("edit_desc_"):
        video_id = int(callback_data.split('_')[2])
        editing_video[user_id] = {
            'video_id': video_id,
            'field': 'description',
            'step': 'waiting_value'
        }
        send_simple_message(chat_id, f"📄 请输入视频的新描述：\n\n当前描述：{get_video_info(video_id, 'description') or '无'}\n\n回复 /cancel 取消")
        return True
    
    return False

def get_video_info(video_id, field):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"SELECT {field} FROM videos WHERE id = ?", (video_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def process_edit_video(chat_id, user_id, text):
    if user_id not in editing_video:
        return False
    
    edit_info = editing_video[user_id]
    
    if text.lower() == '/cancel':
        del editing_video[user_id]
        send_simple_message(chat_id, "❌ 已取消编辑")
        return True
    
    if edit_info.get('step') == 'waiting_value':
        field = edit_info['field']
        video_id = edit_info['video_id']
        
        if field == 'title':
            update_video_info(video_id, title=text)
            send_simple_message(chat_id, f"✅ 标题已更新为：{text}")
        elif field == 'price':
            try:
                new_price = int(text)
                if new_price < 0:
                    send_simple_message(chat_id, "❌ 价格不能为负数")
                    return True
                update_video_info(video_id, price=new_price)
                send_simple_message(chat_id, f"✅ 价格已更新为：{new_price} 积分")
            except ValueError:
                send_simple_message(chat_id, "❌ 请输入有效的数字")
                return True
        elif field == 'description':
            update_video_info(video_id, description=text)
            send_simple_message(chat_id, f"✅ 描述已更新")
        
        del editing_video[user_id]
        return True
    
    return False

def modify_points(chat_id, admin_id, target_user_id, points_change, reason=""):
    if admin_id != ADMIN_ID:
        send_simple_message(chat_id, "❌ 你没有权限使用此命令")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT points, username, first_name FROM users WHERE user_id = ?", (target_user_id,))
    result = c.fetchone()
    
    if not result:
        send_simple_message(chat_id, f"❌ 用户 {target_user_id} 不存在")
        conn.close()
        return False
    
    old_points, username, first_name = result
    new_points = old_points + points_change
    
    if new_points < 0:
        send_simple_message(chat_id, f"❌ 积分不能为负数！用户当前积分：{old_points}")
        conn.close()
        return False
    
    c.execute("UPDATE users SET points = ? WHERE user_id = ?", (new_points, target_user_id))
    c.execute("INSERT INTO points_log (user_id, admin_id, old_points, new_points, change_amount, reason) VALUES (?, ?, ?, ?, ?, ?)",
             (target_user_id, admin_id, old_points, new_points, points_change, reason))
    
    conn.commit()
    conn.close()
    
    action = "增加" if points_change > 0 else "扣除"
    send_simple_message(chat_id, f"✅ 已{action}用户积分！\n\n"
                        f"用户：{first_name} (@{username})\n"
                        f"用户ID：{target_user_id}\n"
                        f"变动：{points_change} 积分\n"
                        f"原积分：{old_points}\n"
                        f"新积分：{new_points}\n"
                        f"原因：{reason if reason else '无'}")
    
    try:
        notify_text = f"📢 管理员{action}了你的积分！\n\n变动：{points_change} 积分\n原积分：{old_points}\n新积分：{new_points}\n"
        if reason:
            notify_text += f"原因：{reason}\n"
        notify_text += f"\n使用 /points 查看当前积分"
        send_simple_message(target_user_id, notify_text)
    except:
        pass
    
    return True

def show_points_log(chat_id, admin_id, target_user_id=None, limit=10):
    if admin_id != ADMIN_ID:
        send_simple_message(chat_id, "❌ 你没有权限使用此命令")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if target_user_id:
        c.execute('''SELECT user_id, admin_id, old_points, new_points, change_amount, reason, change_date 
                     FROM points_log 
                     WHERE user_id = ? 
                     ORDER BY change_date DESC LIMIT ?''', (target_user_id, limit))
    else:
        c.execute('''SELECT user_id, admin_id, old_points, new_points, change_amount, reason, change_date 
                     FROM points_log 
                     ORDER BY change_date DESC LIMIT ?''', (limit,))
    
    logs = c.fetchall()
    conn.close()
    
    if not logs:
        send_simple_message(chat_id, "📝 暂无积分修改记录")
        return
    
    message = "📋 积分修改记录：\n\n"
    for log in logs:
        user_id, admin_id_log, old_points, new_points, change_amount, reason, change_date = log
        action = "+" if change_amount > 0 else ""
        message += f"用户ID：{user_id}\n"
        message += f"变动：{action}{change_amount}\n"
        message += f"积分：{old_points} → {new_points}\n"
        message += f"时间：{change_date[:16]}\n"
        if reason:
            message += f"原因：{reason}\n"
        message += "-" * 30 + "\n"
    
    send_simple_message(chat_id, message)

def batch_add_points(chat_id, admin_id, points_amount):
    if admin_id != ADMIN_ID:
        send_simple_message(chat_id, "❌ 你没有权限使用此命令")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT user_id, points, username, first_name FROM users")
    users = c.fetchall()
    
    if not users:
        send_simple_message(chat_id, "❌ 没有用户")
        conn.close()
        return
    
    success_count = 0
    for user in users:
        user_id, old_points, username, first_name = user
        new_points = old_points + points_amount
        c.execute("UPDATE users SET points = ? WHERE user_id = ?", (new_points, user_id))
        c.execute("INSERT INTO points_log (user_id, admin_id, old_points, new_points, change_amount, reason) VALUES (?, ?, ?, ?, ?, ?)",
                 (user_id, admin_id, old_points, new_points, points_amount, "批量添加"))
        success_count += 1
    
    conn.commit()
    conn.close()
    
    send_simple_message(chat_id, f"✅ 批量添加积分完成！\n"
                        f"影响用户数：{success_count}\n"
                        f"每人添加：{points_amount} 积分")

def get_user_stats(chat_id, admin_id):
    if admin_id != ADMIN_ID:
        send_simple_message(chat_id, "❌ 你没有权限使用此命令")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT SUM(points) FROM users")
    total_points = c.fetchone()[0] or 0
    
    c.execute("SELECT SUM(videos_exchanged) FROM users")
    total_exchanges = c.fetchone()[0] or 0
    
    c.execute("SELECT AVG(points) FROM users")
    avg_points = c.fetchone()[0] or 0
    
    c.execute("SELECT MAX(points) FROM users")
    max_points = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM videos WHERE is_available = 1")
    total_videos = c.fetchone()[0] or 0
    
    conn.close()
    
    message = (f"📊 统计信息：\n\n"
              f"总用户数：{total_users}\n"
              f"总积分：{total_points}\n"
              f"平均积分：{avg_points:.1f}\n"
              f"最高积分：{max_points}\n"
              f"总兑换次数：{total_exchanges}\n"
              f"可用视频数：{total_videos}\n"
              f"视频价格：{VIDEO_PRICE} 积分")
    
    send_simple_message(chat_id, message)

def process_updates():
    global PROXY
    last_update_id = 0
    
    print("🔄 开始监听消息...")
    
    while True:
        try:
            url = API_URL + 'getUpdates'
            params = {'offset': last_update_id + 1, 'timeout': 20}
            
            if PROXY:
                response = requests.get(url, params=params, timeout=25, proxies=PROXY)
            else:
                response = requests.get(url, params=params, timeout=25)
            
            if response.status_code == 200:
                updates = response.json()
                
                if updates.get('ok') and updates.get('result'):
                    for update in updates['result']:
                        last_update_id = update['update_id']
                        
                        if 'callback_query' in update:
                            callback = update['callback_query']
                            chat_id = callback['message']['chat']['id']
                            user_id = callback['from']['id']
                            callback_data = callback['data']
                            
                            if callback_data != "none":
                                handle_callback(chat_id, user_id, callback_data)
                            
                            callback_url = API_URL + 'answerCallbackQuery'
                            requests.post(callback_url, data={'callback_query_id': callback['id']})
                        
                        elif 'message' in update:
                            msg = update['message']
                            chat_id = msg['chat']['id']
                            user_id = msg['from']['id']
                            username = msg['from'].get('username', '')
                            first_name = msg['from'].get('first_name', '')
                            
                            if user_id in editing_video and 'text' in msg:
                                if process_edit_video(chat_id, user_id, msg['text'].strip()):
                                    continue
                            
                            if user_id in pending_videos and 'text' in msg:
                                process_video_info(chat_id, user_id, msg['text'].strip())
                                continue
                            
                            if 'text' in msg:
                                text = msg['text'].strip()
                                
                                if text == '/start':
                                    welcome = f"🎉 欢迎 {first_name} 使用视频兑换机器人！\n\n" \
                                             f"📝 使用说明：\n" \
                                             f"• /checkin - 每日签到获取积分\n" \
                                             f"• /videos - 查看视频列表\n" \
                                             f"• /exchange ID - 兑换视频\n" \
                                             f"• /points - 查询积分\n" \
                                             f"• /history - 查看兑换记录\n" \
                                             f"• /leaderboard - 查看排行榜\n\n" \
                                             f"💰 每日签到可获得 {DAILY_POINTS} 积分\n" \
                                             f"🎬 兑换视频需要 {VIDEO_PRICE} 积分\n\n" \
                                             f"📢 感谢你的支持！"
                                    send_simple_message(chat_id, welcome)
                                
                                elif text == '/checkin':
                                    checkin(chat_id, user_id, username, first_name)
                                
                                elif text == '/points':
                                    show_points(chat_id, user_id)
                                
                                elif text == '/videos':
                                    if chat_id in user_last_message:
                                        old_msg_id = user_last_message[chat_id]
                                        delete_message(chat_id, old_msg_id)
                                        del user_last_message[chat_id]
                                    show_videos(chat_id, user_id, 1)
                                
                                elif text == '/history':
                                    show_history(chat_id, user_id)
                                
                                elif text == '/leaderboard':
                                    show_leaderboard(chat_id, user_id)
                                
                                elif text.startswith('/exchange'):
                                    parts = text.split()
                                    if len(parts) == 2:
                                        try:
                                            video_id = int(parts[1])
                                            exchange_video(chat_id, user_id, video_id)
                                        except:
                                            send_simple_message(chat_id, "❌ 视频ID必须是数字")
                                    else:
                                        send_simple_message(chat_id, "使用方法：/exchange 视频ID")
                                
                                elif text == '/help':
                                    help_text = f"""📋 命令列表：

用户命令：
/start - 启动机器人
/checkin - 每日签到（+{DAILY_POINTS}积分）
/points - 查询我的积分
/videos - 查看视频列表
/exchange ID - 兑换视频
/history - 兑换记录
/leaderboard - 排行榜
/help - 显示帮助"""
                                    
                                    if user_id == ADMIN_ID:
                                        help_text += """

管理员命令：
📹 视频管理：
  直接发送视频 - 自动添加
  /add 标题 价格 [描述] - 快速添加
  /listvideos - 查看所有视频
  /editvideo ID - 编辑视频信息
  /changeprice ID 价格 - 修改视频价格
  /removevideo ID - 下架视频
  /restorevideo ID - 恢复上架视频

💰 积分管理：
  /addpoints 用户ID 积分 [原因]
  /subpoints 用户ID 积分 [原因]
  /setpoints 用户ID 积分 [原因]
  /checkuser 用户ID
  /pointslog [用户ID]
  /stats - 统计信息
  /batchadd 积分"""
                                    
                                    send_simple_message(chat_id, help_text)
                                
                                elif user_id == ADMIN_ID:
                                    if text.startswith('/addpoints'):
                                        parts = text.split()
                                        if len(parts) >= 3:
                                            try:
                                                target_id = int(parts[1])
                                                points = int(parts[2])
                                                reason = ' '.join(parts[3:]) if len(parts) > 3 else "管理员增加积分"
                                                modify_points(chat_id, user_id, target_id, points, reason)
                                            except:
                                                send_simple_message(chat_id, "使用方法：/addpoints 用户ID 积分 [原因]")
                                        else:
                                            send_simple_message(chat_id, "使用方法：/addpoints 用户ID 积分 [原因]")
                                    
                                    elif text.startswith('/subpoints'):
                                        parts = text.split()
                                        if len(parts) >= 3:
                                            try:
                                                target_id = int(parts[1])
                                                points = -abs(int(parts[2]))
                                                reason = ' '.join(parts[3:]) if len(parts) > 3 else "管理员扣除积分"
                                                modify_points(chat_id, user_id, target_id, points, reason)
                                            except:
                                                send_simple_message(chat_id, "使用方法：/subpoints 用户ID 积分 [原因]")
                                        else:
                                            send_simple_message(chat_id, "使用方法：/subpoints 用户ID 积分 [原因]")
                                    
                                    elif text.startswith('/setpoints'):
                                        parts = text.split()
                                        if len(parts) >= 3:
                                            try:
                                                target_id = int(parts[1])
                                                target_points = int(parts[2])
                                                reason = ' '.join(parts[3:]) if len(parts) > 3 else "管理员设置积分"
                                                
                                                conn = sqlite3.connect(DB_PATH)
                                                c = conn.cursor()
                                                c.execute("SELECT points FROM users WHERE user_id = ?", (target_id,))
                                                result = c.fetchone()
                                                conn.close()
                                                
                                                if result:
                                                    change = target_points - result[0]
                                                    modify_points(chat_id, user_id, target_id, change, reason)
                                                else:
                                                    send_simple_message(chat_id, f"❌ 用户 {target_id} 不存在")
                                            except:
                                                send_simple_message(chat_id, "使用方法：/setpoints 用户ID 积分 [原因]")
                                        else:
                                            send_simple_message(chat_id, "使用方法：/setpoints 用户ID 积分 [原因]")
                                    
                                    elif text.startswith('/checkuser'):
                                        parts = text.split()
                                        if len(parts) == 2:
                                            try:
                                                target_id = int(parts[1])
                                                conn = sqlite3.connect(DB_PATH)
                                                c = conn.cursor()
                                                c.execute("SELECT user_id, username, first_name, points, videos_exchanged FROM users WHERE user_id = ?", (target_id,))
                                                user = c.fetchone()
                                                conn.close()
                                                
                                                if user:
                                                    user_id, username, first_name, points, videos_exchanged = user
                                                    message = (f"📊 用户信息：\n\n"
                                                              f"ID：{user_id}\n"
                                                              f"名称：{first_name}\n"
                                                              f"用户名：@{username if username else '无'}\n"
                                                              f"积分：{points}\n"
                                                              f"兑换次数：{videos_exchanged}")
                                                    send_simple_message(chat_id, message)
                                                else:
                                                    send_simple_message(chat_id, f"❌ 用户 {target_id} 不存在")
                                            except:
                                                send_simple_message(chat_id, "使用方法：/checkuser 用户ID")
                                        else:
                                            send_simple_message(chat_id, "使用方法：/checkuser 用户ID")
                                    
                                    elif text.startswith('/pointslog'):
                                        parts = text.split()
                                        if len(parts) == 2:
                                            try:
                                                target_id = int(parts[1])
                                                show_points_log(chat_id, user_id, target_id)
                                            except:
                                                show_points_log(chat_id, user_id)
                                        else:
                                            show_points_log(chat_id, user_id)
                                    
                                    elif text == '/stats':
                                        get_user_stats(chat_id, user_id)
                                    
                                    elif text.startswith('/batchadd'):
                                        parts = text.split()
                                        if len(parts) == 2:
                                            try:
                                                points = int(parts[1])
                                                batch_add_points(chat_id, user_id, points)
                                            except:
                                                send_simple_message(chat_id, "使用方法：/batchadd 积分")
                                        else:
                                            send_simple_message(chat_id, "使用方法：/batchadd 积分")
                                    
                                    elif text == '/listvideos':
                                        list_all_videos(chat_id, user_id)
                                    
                                    elif text.startswith('/removevideo'):
                                        parts = text.split()
                                        if len(parts) == 2:
                                            try:
                                                video_id = int(parts[1])
                                                remove_video(chat_id, user_id, [video_id])
                                            except:
                                                send_simple_message(chat_id, "❌ 视频ID必须是数字")
                                        else:
                                            send_simple_message(chat_id, "使用方法：/removevideo 视频ID")
                                    
                                    elif text.startswith('/restorevideo'):
                                        parts = text.split()
                                        if len(parts) == 2:
                                            try:
                                                video_id = int(parts[1])
                                                restore_video(chat_id, user_id, video_id)
                                            except:
                                                send_simple_message(chat_id, "❌ 视频ID必须是数字")
                                        else:
                                            send_simple_message(chat_id, "使用方法：/restorevideo 视频ID")
                                    
                                    elif text.startswith('/changeprice'):
                                        parts = text.split()
                                        if len(parts) == 3:
                                            try:
                                                video_id = int(parts[1])
                                                new_price = int(parts[2])
                                                change_video_price(chat_id, user_id, video_id, new_price)
                                            except:
                                                send_simple_message(chat_id, "❌ 视频ID和价格必须是数字")
                                        else:
                                            send_simple_message(chat_id, "使用方法：/changeprice 视频ID 新价格\n\n示例：/changeprice 5 50")
                                    
                                    elif text.startswith('/editvideo'):
                                        parts = text.split()
                                        if len(parts) == 2:
                                            try:
                                                video_id = int(parts[1])
                                                edit_video_info(chat_id, user_id, video_id)
                                            except:
                                                send_simple_message(chat_id, "❌ 视频ID必须是数字")
                                        else:
                                            send_simple_message(chat_id, "使用方法：/editvideo 视频ID")
                                    
                                    elif text.startswith('/add') and not text.startswith('/addpoints'):
                                        parts = text.split(maxsplit=3)
                                        if len(parts) >= 3 and user_id in pending_videos:
                                            process_video_info(chat_id, user_id, text)
                                        elif len(parts) < 3:
                                            send_simple_message(chat_id, "使用方法：/add 标题 价格 [描述]\n请先发送视频文件")
                            
                            elif 'video' in msg and user_id == ADMIN_ID:
                                file_id = msg['video']['file_id']
                                caption = msg['video'].get('caption', '')
                                duration = msg['video'].get('duration')
                                handle_video_upload(chat_id, user_id, file_id, caption, duration)
            
            else:
                print(f"请求失败: {response.status_code}")
                
        except Exception as e:
            print(f"错误: {e}")
            time.sleep(5)
        
        time.sleep(1)

def main():
    global PROXY
    
    print("=" * 60)
    print("🤖 视频兑换机器人启动中...")
    print(f"数据库路径: {DB_PATH}")
    print(f"管理员ID: {ADMIN_ID}")
    print(f"签到奖励: {DAILY_POINTS}积分")
    print(f"视频价格: {VIDEO_PRICE}积分")
    print("=" * 60)
    
    # 检测网络代理
    try:
        requests.get('https://api.telegram.org', timeout=5)
        PROXY = None
        print("✅ 使用直连模式")
    except:
        try:
            proxy = {'http': 'http://127.0.0.1:7897', 'https': 'http://127.0.0.1:7897'}
            requests.get('https://api.telegram.org', timeout=5, proxies=proxy)
            PROXY = proxy
            print("✅ 使用代理模式 (端口 7897)")
        except:
            PROXY = None
            print("⚠️ 无法连接，尝试直连模式")
    
    # 初始化数据库
    init_db()
    
    print("=" * 60)
    print("📹 管理员视频管理命令：")
    print("  /listvideos - 查看所有视频")
    print("  /editvideo ID - 编辑视频信息")
    print("  /changeprice ID 价格 - 修改视频价格")
    print("  /removevideo ID - 下架视频")
    print("  /restorevideo ID - 恢复上架视频")
    print("  直接发送视频文件 - 添加新视频")
    print("=" * 60)
    print("\n按 Ctrl+C 停止\n")
    
    try:
        process_updates()
    except KeyboardInterrupt:
        print("\n👋 机器人已停止")

if __name__ == "__main__":
    main()
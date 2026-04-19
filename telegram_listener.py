import requests
import time
from video_bot import API_URL, PROXY, handle_callback, handle_message

last_update_id = 0

def start_listener():
    """启动消息监听"""
    global last_update_id
    print("🔄 开始监听消息...")
    
    while True:
        try:
            url = API_URL + 'getUpdates'
            params = {'offset': last_update_id + 1, 'timeout': 30}
            
            if PROXY:
                response = requests.get(url, params=params, timeout=35, proxies=PROXY)
            else:
                response = requests.get(url, params=params, timeout=35)
            
            if response.status_code == 200:
                updates = response.json()
                
                if updates.get('ok') and updates.get('result'):
                    for update in updates['result']:
                        last_update_id = update['update_id']
                        
                        if 'callback_query' in update:
                            callback = update['callback_query']
                            from video_bot import handle_callback
                            handle_callback(
                                callback['message']['chat']['id'],
                                callback['from']['id'],
                                callback['data']
                            )
                            
                            callback_url = API_URL + 'answerCallbackQuery'
                            requests.post(callback_url, data={'callback_query_id': callback['id']})
                        
                        elif 'message' in update:
                            from video_bot import handle_message
                            handle_message(update['message'])
            
            time.sleep(1)
        except Exception as e:
            print(f"监听错误: {e}")
            time.sleep(5)
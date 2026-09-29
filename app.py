from flask import Flask, request, abort, render_template, jsonify
import urllib3
import os
import traceback
from dotenv import load_dotenv

from google import genai
import google.genai.errors
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

# 載入自訂偵測模組
from modules import url_checker
from modules import text_checker
from modules import rag_searcher
from modules import image_checker

# 環境變數設定
current_dir = os.path.dirname(os.path.abspath(__file__))
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv(dotenv_path=os.path.join(current_dir, '.env'))

channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')

# LINE 相關物件：有填憑證才啟用，Website 可以不需要
line_enabled = bool(channel_access_token and LINE_CHANNEL_SECRET)
configuration = None
handler = None

if line_enabled:
    from linebot.v3 import WebhookHandler
    from linebot.v3.messaging import Configuration
    configuration = Configuration(access_token=channel_access_token)
    handler = WebhookHandler(LINE_CHANNEL_SECRET)
else:
    print("ℹ️ 未偵測到 LINE 憑證，目前只啟用 Website 模式。")

app = Flask(__name__)

print("==== 🔐 環境變數載入測試 ====")
if line_enabled:
    print(f"LINE Token 實際長度: {len(channel_access_token)} 字元")
else:
    print("LINE Token: 未設定（Website 模式可正常使用）")

# 165 資料庫網址
CSV_URL = "https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/29E8E643-88ED-4952-B21E-BD42A3B7108C/resource/FCAF44C5-978E-405D-BCCB-4FCF16DF7D25/download"

# API 金鑰輪替設定池
API_KEYS = [
    os.getenv('GEMINI_API_KEY_1'),
    os.getenv('GEMINI_API_KEY_2'),
    os.getenv('GEMINI_API_KEY_3')
]

current_key_index = 0

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(google.genai.errors.APIError),
    reraise=True
)
def _call_gemini_api(prompt):
    global current_key_index
    usable_keys = [key for key in API_KEYS if key]
    if not usable_keys:
        raise Exception("尚未設定任何 GEMINI_API_KEY，請在 .env 填入金鑰")

    for _ in range(len(usable_keys)):
        try:
            active_key = API_KEYS[current_key_index]
            if not active_key:
                current_key_index = (current_key_index + 1) % len(API_KEYS)
                continue
            temp_client = genai.Client(api_key=active_key)
            return temp_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config={"temperature": 0.0}
            )
        except Exception as e:
            print(f"⚠️ 金鑰索引 {current_key_index} 呼叫失敗。錯誤: {e}")
            current_key_index = (current_key_index + 1) % len(API_KEYS)
            print(f"🔄 自動切換至下一組金鑰索引: {current_key_index}")

    raise Exception("金鑰池中所有可用的 API Key 皆暫時無法連線或已被限流")

# 啟動時加載 165 黑名單
scam_urls_set = url_checker.load_scam_urls(CSV_URL)


def analyze_user_text(user_text):
    """
    核心分析：輸入一段文字，回傳一段風險評估結果。
    Website 和 LINE Bot 都呼叫這個函式，避免寫兩套邏輯。
    """
    user_text = user_text.strip()
    if not user_text:
        return "請先貼上可疑的文字或網址，再按送出。"

    print(f"收到使用者訊息: {user_text}")

    # ---------------------------------------------------------
    # 🔥 【核心第一關】優先進行 165 實體 CSV 交叉對比精準攔截
    # ---------------------------------------------------------
    matched_scam_url = url_checker.check_if_user_input_matches_165(user_text, scam_urls_set)

    if matched_scam_url:
        return (
            f"🚨【內政部 165 通報黑名單確診】\n\n"
            f"警告！您輸入的內容中包含已被 165 反詐騙網站封鎖的惡意網址：\n"
            f"🔗 {matched_scam_url}\n\n"
            f"系統評估得分：100 分\n"
            f"風險等級：🔴 高風險詐騙\n\n"
            f"💡 專家極力勸阻：此網域為百分之百的詐騙釣魚網站，請絕對不要點擊、填寫信用卡或任何個人個資！"
        )

    # ---------------------------------------------------------
    # 【第二關】165 未直接命中，才走原本的分析分流邏輯
    # ---------------------------------------------------------
    input_type, urls = url_checker.detect_input_type(user_text)

    if input_type == "url":
        raw_url = urls[0]
        main_domain = url_checker.extract_main_domain(raw_url)

        if main_domain in url_checker.WHITE_LIST:
            return f"✅ 經辨識此為官方知名網站 ({main_domain})。\n目前評估安全無虞，請安心使用。"

        print("【灰色地帶網址觸發】啟動 Gemini AI 分析中...")
        ai_analysis_result = url_checker.check_gray_zone_with_ai(user_text, raw_url, _call_gemini_api)
        return f"🔍 提示：此網址為新興或未經通報之網址。\n🤖 【AI 專家動態風險評估】\n\n{ai_analysis_result}"

    # 純文字且大於 15 字，啟動 PTT 弱標籤 RAG 匹配 + Gemini Agent 報告
    if len(user_text) > 15:
        print("【RAG 觸發】正在從已標籤化的 PTT 資料庫匹配相似案例...")
        ptt_cases = rag_searcher.search_related_cases(user_text, top_k=2)

        print("【Gemini Agent 評分啟動】進行 0-100 動態風險分級中...")
        ai_analysis_result = text_checker.check_text_scam_with_ai(
            user_text, _call_gemini_api, ptt_cases=ptt_cases
        )

        reply_text = f"🔍 提示：系統已自動調閱本地真實詐騙案例庫...\n\n{ai_analysis_result}"

        if ptt_cases:
            reply_text += "\n\n🔗 參考 PTT 受害者討論串鏈接："
            for case in ptt_cases:
                reply_text += f"\n- {case['title']}: {case['url']}"

        return reply_text

    if user_text == "你好":
        return "哈囉我是反詐騙助手！您可以貼上「可疑的網址」或「一整段懷疑是詐騙的文字」讓我幫您評估風險喔！"

    if "詐騙" in user_text:
        return "你是疑似遇到詐騙了嗎，請提供對方的網址或訊息。"

    return "收到您的訊息！這段文字較短，且目前未偵測到高風險特徵。如果這是某個陌生事件的開頭，後續要求匯款或點連結時請務必提高警覺。"


def analyze_user_image(image_bytes):
    """
    核心影像分析：輸入圖片的 bytes，回傳風險評估文字。
    Website 上傳圖片與 LINE 收到的圖片，最後都走這裡。
    """
    global current_key_index

    if not image_bytes:
        return "請先選擇一張圖片再開始分析。"

    print(f"📥 圖片準備送往 image_checker，大小: {len(image_bytes)} bytes")
    ai_analysis_result, current_key_index = image_checker.check_image_scam_with_ai(
        image_bytes, API_KEYS, current_key_index
    )
    return f"🤖 【AI 影像詐騙風險分析結果】\n\n{ai_analysis_result}"


def reply_line_text(event, reply_text):
    """把文字結果回傳到 LINE 聊天室。"""
    from linebot.v3.messaging import (
        ApiClient,
        MessagingApi,
        ReplyMessageRequest,
        TextMessage,
    )

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


# =========================
# Website 路由
# =========================

@app.route("/", methods=['GET'])
def home():
    """打開瀏覽器時，顯示反詐騙網頁。"""
    return render_template("index.html")


@app.route("/api/check", methods=['POST'])
def api_check():
    """
    網頁按下「開始分析」後會打到這裡。
    前端送來 JSON：{ "text": "使用者貼上的內容" }
    後端回傳 JSON：{ "result": "分析結果文字" }
    """
    data = request.get_json(silent=True) or {}
    user_text = data.get("text", "")

    try:
        result = analyze_user_text(user_text)
        return jsonify({"result": result})
    except Exception:
        traceback.print_exc()
        return jsonify({
            "result": "⚠️ 系統暫時無法完成分析，請稍後再試一次。"
        }), 500


@app.route("/api/check-image", methods=['POST'])
def api_check_image():
    """
    網頁上傳圖片後會打到這裡。
    前端用 FormData 送來欄位名稱 image 的檔案。
    """
    if "image" not in request.files:
        return jsonify({"result": "請先選擇一張圖片再開始分析。"}), 400

    image_file = request.files["image"]
    if not image_file or image_file.filename == "":
        return jsonify({"result": "請先選擇一張圖片再開始分析。"}), 400

    try:
        image_bytes = image_file.read()
        result = analyze_user_image(image_bytes)
        return jsonify({"result": result})
    except Exception:
        traceback.print_exc()
        return jsonify({
            "result": "⚠️ 系統訊息：抱歉，處理圖片時發生非預期錯誤，請確保圖片內容清晰。"
        }), 500


# =========================
# LINE Bot 路由（有憑證才啟用）
# =========================

if line_enabled:
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent
    from linebot.v3.messaging import ApiClient, MessagingApiBlob

    @app.route("/callback", methods=['POST'])
    def callback():
        if 'X-Line-Signature' not in request.headers:
            abort(400)
        signature = request.headers['X-Line-Signature']
        body = request.get_data(as_text=True)
        try:
            handler.handle(body, signature)
        except InvalidSignatureError:
            abort(400)
        except Exception:
            traceback.print_exc()
            abort(500)
        return 'OK'

    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message(event):
        reply_text = analyze_user_text(event.message.text)
        reply_line_text(event, reply_text)

    @handler.add(MessageEvent, message=ImageMessageContent)
    def handle_image_message(event):
        print(f"\n📸 收到使用者傳送圖片 (ID: {event.message.id})，啟動多模態反詐騙分析...")

        try:
            with ApiClient(configuration) as api_client:
                messaging_blob_api = MessagingApiBlob(api_client)
                image_content = messaging_blob_api.get_message_content(event.message.id)

                if isinstance(image_content, bytes):
                    image_bytes = image_content
                else:
                    image_bytes = b"".join([chunk for chunk in image_content])

            reply_text = analyze_user_image(image_bytes)

        except Exception:
            print("❌ 圖片處理流程內部發生錯誤！詳細 Traceback 如下：")
            traceback.print_exc()
            reply_text = "⚠️ 系統訊息：抱歉，處理圖片時發生非預期錯誤，請確保圖片內容清晰。"

        try:
            reply_line_text(event, reply_text)
        except Exception as line_err:
            print(f"❌ 回傳 LINE 訊息時失敗: {line_err}")


if __name__ == "__main__":
    rag_searcher.update_ptt_database()
    # macOS AirPlay 常占用 5000，改用 5001 避免瀏覽器出現 403
    app.run(debug=True, port=5001)

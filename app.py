from flask import Flask, request, jsonify, send_from_directory, abort, session
from flask_cors import CORS
import urllib3
import os
import secrets
import traceback
from functools import wraps
from dotenv import load_dotenv

from google import genai
import google.genai.errors
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

# 載入自訂偵測模組（反詐騙核心邏輯，與前端入口無關）
from modules import url_checker
from modules import text_checker
from modules import rag_searcher
from modules import image_checker
from modules import review_store

# 環境變數設定（金鑰只放後端，不要寫進前端）
current_dir = os.path.dirname(os.path.abspath(__file__))
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv(dotenv_path=os.path.join(current_dir, ".env"))

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# GitHub Pages 前端會從不同網域呼叫 API，所以需要 CORS
# 正式環境建議在 Render 設定 FRONTEND_ORIGIN=https://你的帳號.github.io
frontend_origin = os.getenv("FRONTEND_ORIGIN", "*")
cors_origins = [origin.strip() for origin in frontend_origin.split(",") if origin.strip()]
CORS(app, resources={r"/api/*": {"origins": cors_origins or ["*"]}})

print("==== 🔐 環境變數載入測試 ====")
print(f"FRONTEND_ORIGIN: {frontend_origin}")
print(f"REVIEW_PASSWORD set: {'yes' if os.getenv('REVIEW_PASSWORD') else 'no'}")

# 165 資料庫網址
CSV_URL = "https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/29E8E643-88ED-4952-B21E-BD42A3B7108C/resource/FCAF44C5-978E-405D-BCCB-4FCF16DF7D25/download"

# Gemini API 金鑰只從後端環境變數讀取
API_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
]

current_key_index = 0


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(google.genai.errors.APIError),
    reraise=True,
)
def _call_gemini_api(prompt):
    global current_key_index
    usable_keys = [key for key in API_KEYS if key]
    if not usable_keys:
        raise Exception("尚未設定任何 GEMINI_API_KEY，請在後端環境變數填入金鑰")

    for _ in range(len(usable_keys)):
        try:
            active_key = API_KEYS[current_key_index]
            if not active_key:
                current_key_index = (current_key_index + 1) % len(API_KEYS)
                continue
            temp_client = genai.Client(api_key=active_key)
            return temp_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={"temperature": 0.0},
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
    Website API 只負責收送資料，真正判斷仍走這段邏輯。
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
        return (
            f"🔍 提示：此網址為新興或未經通報之網址。\n"
            f"🤖 【AI 專家動態風險評估】\n\n{ai_analysis_result}"
        )

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

    return (
        "收到您的訊息！這段文字較短，且目前未偵測到高風險特徵。"
        "如果這是某個陌生事件的開頭，後續要求匯款或點連結時請務必提高警覺。"
    )


def analyze_user_image(image_bytes):
    """核心影像分析：輸入圖片 bytes，回傳風險評估文字。"""
    global current_key_index

    if not image_bytes:
        return "請先選擇一張圖片再開始分析。"

    print(f"📥 圖片準備送往 image_checker，大小: {len(image_bytes)} bytes")
    ai_analysis_result, current_key_index = image_checker.check_image_scam_with_ai(
        image_bytes, API_KEYS, current_key_index
    )
    return f"🤖 【AI 影像詐騙風險分析結果】\n\n{ai_analysis_result}"


# =========================
# Website API
# =========================

@app.route("/api/health", methods=["GET"])
def api_health():
    """部署平台可用這個網址確認後端是否活著。"""
    return jsonify({"status": "ok"})


@app.route("/api/check", methods=["POST"])
def api_check():
    """
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
        return jsonify({"result": "⚠️ 系統暫時無法完成分析，請稍後再試一次。"}), 500


@app.route("/api/check-image", methods=["POST"])
def api_check_image():
    """前端用 FormData 送來欄位名稱 image 的檔案。"""
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
# 研究小組 Review（密碼保護；不影響公開 docs 網站）
# =========================

def _review_password_configured() -> str:
    return (os.getenv("REVIEW_PASSWORD") or "").strip()


def review_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("review_authenticated"):
            return jsonify({"error": "未授權：請先登入 review"}), 401
        return view(*args, **kwargs)

    return wrapped


@app.route("/review", methods=["GET"])
@app.route("/review/", methods=["GET"])
def review_home():
    return send_from_directory("review", "index.html")


@app.route("/review/<path:filename>", methods=["GET"])
def review_static(filename):
    # 只允許前端靜態檔，不直接暴露研究 CSV
    if filename in {"index.html", "style.css", "app.js"}:
        return send_from_directory("review", filename)
    abort(404)


@app.route("/api/review/login", methods=["POST"])
def api_review_login():
    expected = _review_password_configured()
    if not expected:
        return jsonify({"error": "伺服器尚未設定 REVIEW_PASSWORD"}), 503

    data = request.get_json(silent=True) or {}
    password = str(data.get("password") or "")
    if not password or not secrets.compare_digest(password, expected):
        return jsonify({"error": "密碼錯誤"}), 401

    session.clear()
    session["review_authenticated"] = True
    return jsonify({"ok": True})


@app.route("/api/review/logout", methods=["POST"])
def api_review_logout():
    session.clear()
    return jsonify({"ok": True})


def _review_dataset_id() -> str:
    raw = (
        request.args.get("dataset")
        or (request.get_json(silent=True) or {}).get("dataset")
        or "fuzzy"
    )
    return str(raw).strip() or "fuzzy"


@app.route("/api/review/session", methods=["GET"])
@review_login_required
def api_review_session():
    return jsonify(
        {
            "ok": True,
            "authenticated": True,
            "datasets": review_store.list_datasets(),
        }
    )


@app.route("/api/review/datasets", methods=["GET"])
@review_login_required
def api_review_datasets():
    return jsonify({"datasets": review_store.list_datasets()})


@app.route("/api/review/items", methods=["GET"])
@review_login_required
def api_review_items():
    dataset_id = _review_dataset_id()
    try:
        dataset = review_store.get_dataset(dataset_id)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        items = review_store.load_review_items(dataset_id)
        progress = review_store.progress_stats(items, dataset_id)
        return jsonify(
            {
                "dataset": {
                    "id": dataset["id"],
                    "label": dataset["label"],
                    "kind": dataset["kind"],
                    "description": dataset["description"],
                },
                "items": items,
                "progress": progress,
            }
        )
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "讀取 review 資料失敗"}), 500


@app.route("/api/review/save", methods=["POST"])
@review_login_required
def api_review_save():
    data = request.get_json(silent=True) or {}
    review_id = data.get("review_id")
    if review_id is None or str(review_id).strip() == "":
        return jsonify({"error": "缺少 review_id"}), 400
    dataset_id = str(data.get("dataset") or "fuzzy").strip() or "fuzzy"
    try:
        review_store.get_dataset(dataset_id)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        saved = review_store.upsert_answer(str(review_id), data, dataset_id)
        return jsonify({"ok": True, "dataset": dataset_id, "answer": saved})
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "存檔失敗"}), 500


@app.route("/api/review/export.csv", methods=["GET"])
@review_login_required
def api_review_export_csv():
    import csv
    from io import StringIO

    dataset_id = _review_dataset_id()
    try:
        dataset = review_store.get_dataset(dataset_id)
        items = review_store.load_review_items(dataset_id)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "匯出失敗"}), 500

    fieldnames = dataset["export_fields"]
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for item in items:
        writer.writerow(review_store.export_item_row(item, dataset_id))

    # UTF-8 BOM，方便 Excel
    payload = "\ufeff" + buffer.getvalue()
    return (
        payload,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": f"attachment; filename={dataset['export_filename']}",
        },
    )


# =========================
# 本機開發時也可直接打開前端頁面
# 正式環境的前端請用 GitHub Pages（docs/）
# =========================

@app.route("/", methods=["GET"])
def home():
    return send_from_directory("docs", "index.html")


@app.route("/<path:filename>", methods=["GET"])
def frontend_files(filename):
    # 避免把 /api/... 或 /review... 誤當成 docs 靜態檔
    if filename.startswith("api/") or filename == "review" or filename.startswith("review/"):
        abort(404)
    return send_from_directory("docs", filename)


if __name__ == "__main__":
    # 本機開發：python app.py
    # 正式部署：由 gunicorn 啟動，不會走進這段
    rag_searcher.update_ptt_database()
    port = int(os.getenv("PORT", "5001"))
    # macOS AirPlay 常占用 5000，本機預設改用 5001
    app.run(debug=True, host="127.0.0.1", port=port)

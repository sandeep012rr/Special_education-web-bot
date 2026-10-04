import os
import re
import json
import time
import threading
import telebot
from telebot.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    WebAppInfo
)
from pypdf import PdfReader
from docx import Document
from flask import Flask, render_template, jsonify, request

# ================= FLASK SERVER SETUP =================
app = Flask(__name__, template_folder="templates")

DATA_DIR = "test_data"
CONFIG_FILE = "folders_config.json"

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

if not os.path.exists(CONFIG_FILE):
    default_config = {
        "folders": [
            {"id": "default", "title": "General Tests", "test_ids": []}
        ]
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(default_config, f, indent=2)

def read_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

WEBAPP_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://quizz-lfdt.onrender.com")

@app.route('/')
def home():
    return render_template("index.html")

@app.route('/api/folders')
def api_get_folders():
    cfg = read_config()
    out = []
    for f in cfg.get("folders", []):
        out.append({
            "id": f["id"],
            "title": f["title"],
            "test_count": len(f.get("test_ids", []))
        })
    return jsonify(out)

@app.route('/api/folder/create', methods=['POST'])
def api_create_folder():
    data = request.json or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "Title required"}), 400
    cfg = read_config()
    folder_id = f"f_{int(time.time())}"
    cfg["folders"].append({"id": folder_id, "title": title, "test_ids": []})
    save_config(cfg)
    return jsonify({"success": True, "id": folder_id})

@app.route('/api/folder/<folder_id>/tests')
def api_folder_tests(folder_id):
    cfg = read_config()
    folder = next((f for f in cfg.get("folders", []) if f["id"] == folder_id), None)
    if not folder:
        return jsonify([])
    tests = []
    for tid in folder.get("test_ids", []):
        path = os.path.join(DATA_DIR, f"{tid}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as tf:
                    tdata = json.load(tf)
                    tests.append({
                        "id": tid,
                        "title": tdata.get("title", tid),
                        "total_questions": len(tdata.get("questions", []))
                    })
            except Exception:
                pass
    return jsonify(tests)

@app.route('/api/test/<test_id>')
def api_get_test(test_id):
    path = os.path.join(DATA_DIR, f"{test_id}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "Not found"}), 404

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()
# ======================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
bot = telebot.TeleBot(BOT_TOKEN)
current_target_channel = "@FIRST_GARDE_SPL"
user_active_folder = {}

# नीचे कीबोर्ड में दिखने वाले स्थायी बटन
def get_main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    btn_portal = KeyboardButton("📂 Open Portal")
    btn_list = KeyboardButton("📁 List Folders")
    btn_post = KeyboardButton("📢 Post to Channel")
    btn_help = KeyboardButton("ℹ️ Help")
    
    markup.row(btn_portal, btn_list)
    markup.row(btn_post, btn_help)
    return markup

def extract_text_from_pdf(file_path):
    text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            t = page.extract_text()
            if t: text += t + "\n"
    except Exception as e:
        print(f"PDF Error: {e}")
    return text

def extract_text_from_docx(file_path):
    text = ""
    try:
        doc = Document(file_path)
        for p in doc.paragraphs:
            if p.text: text += p.text + "\n"
    except Exception as e:
        print(f"DOCX Error: {e}")
    return text

def parse_document_to_mcqs(text):
    quizzes = []
    raw_blocks = re.split(r'\n(?=Question:)', "\n" + text.strip())
    opt_map = {'a': 0, 'b': 1, 'c': 2, 'd': 3}

    for block in raw_blocks:
        if not block.strip() or "Question:" not in block:
            continue
        try:
            q_match = re.search(r'Question:\s*(.*?)(?=\([a-dA-D]\)|Answer:|$)', block, re.DOTALL)
            if not q_match: continue
            question = q_match.group(1).strip()

            options = []
            opt_pattern = re.findall(r'\(([a-dA-D])\)\s*(.*?)(?=\([a-dA-D]\)|Answer:|Solution:|Key Points:|Positive Marks:|$)', block, re.DOTALL)
            for tag, opt_text in opt_pattern:
                clean_opt = opt_text.strip()
                if clean_opt: options.append(clean_opt)

            ans_match = re.search(r'Answer:\s*([a-dA-D])', block, re.IGNORECASE)
            correct_id = opt_map.get(ans_match.group(1).lower(), 0) if ans_match else 0

            sol_match = re.search(r'Solution:\s*(.*?)(?=Key Points:|Positive Marks:|Negative Marks:|\n\n|$)', block, re.DOTALL)
            solution = sol_match.group(1).strip() if sol_match else ""

            kp_match = re.search(r'Key Points:\s*(.*?)(?=Positive Marks:|Negative Marks:|\n\n|$)', block, re.DOTALL)
            key_points = kp_match.group(1).strip() if kp_match else ""

            if question and len(options) >= 2:
                quizzes.append({
                    "question": question,
                    "options": options,
                    "correct_id": min(correct_id, len(options) - 1),
                    "solution": solution,
                    "key_points": key_points
                })
        except Exception:
            continue
    return quizzes

@bot.message_handler(commands=['start', 'help'])
@bot.message_handler(func=lambda m: m.text in ["ℹ️ Help", "/help"])
def send_welcome(message):
    current_url = os.environ.get("RENDER_EXTERNAL_URL", WEBAPP_URL)
    
    # Inline Web App Button
    inline_markup = InlineKeyboardMarkup()
    inline_markup.add(InlineKeyboardButton(text="🚀 Launch Exam Portal", web_app=WebAppInfo(url=current_url)))

    cfg = read_config()
    folder_list_str = "\n".join([f"• <b>{f['title']}</b>" for f in cfg.get("folders", [])])

    text = (
        "🤖 <b>Testbook Multi-Folder Portal Controller</b>\n\n"
        f"🎯 <b>वर्तमान चैनल:</b> <code>{current_target_channel}</code>\n\n"
        "📁 <b>उपलब्ध फ़ोल्डर:</b>\n"
        f"{folder_list_str}\n\n"
        "🛠 <b>कमांड्स की सूची:</b>\n"
        "1. <code>/newfolder FolderName</code> - नया फ़ोल्डर बनाएँ\n"
        "2. <code>/setfolder FolderName</code> - फ़ाइल अपलोड हेतु फ़ोल्डर चुनें\n"
        "3. <code>/renamefolder PuranaNaam -> NayaNaam</code> - फ़ोल्डर का नाम बदलें\n"
        "4. <code>/setchannel @channel</code> - लक्ष्य चैनल बदलें\n\n"
        "नीचे मेनू बटन का उपयोग करके भी कमांड भेज सकते हैं 👇"
    )
    # Reply Keyboard + Inline Keyboard दोनों भेजें
    bot.send_message(message.chat.id, "कंट्रोल पैनल सक्रिय है:", reply_markup=get_main_keyboard())
    bot.reply_to(message, text, reply_markup=inline_markup, parse_mode="HTML")

# बटन: 📂 Open Portal
@bot.message_handler(func=lambda m: m.text == "📂 Open Portal")
def btn_open_portal(message):
    current_url = os.environ.get("RENDER_EXTERNAL_URL", WEBAPP_URL)
    inline_markup = InlineKeyboardMarkup()
    inline_markup.add(InlineKeyboardButton(text="🚀 Testbook Web App खोलें", web_app=WebAppInfo(url=current_url)))
    bot.reply_to(message, "पोर्टल खोलने के लिए नीचे दिए गए बटन पर टैप करें:", reply_markup=inline_markup)

# बटन: 📁 List Folders
@bot.message_handler(commands=['listfolders'])
@bot.message_handler(func=lambda m: m.text == "📁 List Folders")
def btn_list_folders(message):
    cfg = read_config()
    res = "📁 <b>उपलब्ध फ़ोल्डर एवं टेस्ट की संख्या:</b>\n\n"
    for idx, f in enumerate(cfg.get("folders", []), 1):
        res += f"{idx}. <b>{f['title']}</b> ({len(f.get('test_ids', []))} टेस्ट उपलब्ध)\n"
    res += "\nनया फ़ोल्डर बनाने के लिए लिखें:\n<code>/newfolder FolderName</code>"
    bot.reply_to(message, res, parse_mode="HTML")

# बटन: 📢 Post to Channel
@bot.message_handler(commands=['posttochannel'])
@bot.message_handler(func=lambda m: m.text == "📢 Post to Channel")
def post_channel_cmd(message):
    try:
        bot_info = bot.get_me()
        bot_username = bot_info.username
        channel_url = f"https://t.me/{bot_username}?startapp=test"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(text="🚀 Open Test Portal", url=channel_url))

        post_text = (
            "📢 <b>Online Mock Test Series Portal Live!</b>\n\n"
            "• Testbook Style Navigation & Timer\n"
            "• Folder-wise Categorized Test Series\n"
            "• Instant Scorecard, Analysis & Complete Solutions\n\n"
            "टेस्ट देने के लिए नीचे बटन पर क्लिक करें 👇"
        )
        bot.send_message(chat_id=current_target_channel, text=post_text, reply_markup=markup, parse_mode="HTML")
        bot.reply_to(message, f"✅ चैनल <code>{current_target_channel}</code> पर सफलतापूर्वक पोस्ट हो गया!", parse_mode="HTML")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['newfolder'])
def new_folder_cmd(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "फ़ोल्डर का नाम लिखें। उदाहरण: <code>/newfolder Batch 2</code>", parse_mode="HTML")
        return
    title = parts[1].strip()
    cfg = read_config()
    fid = f"f_{int(time.time())}"
    cfg["folders"].append({"id": fid, "title": title, "test_ids": []})
    save_config(cfg)
    user_active_folder[message.chat.id] = fid
    bot.reply_to(message, f"✅ नया फ़ोल्डर बन गया और चुना गया: <b>{title}</b>", parse_mode="HTML")

@bot.message_handler(commands=['setfolder'])
def set_active_folder_cmd(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "फ़ोल्डर का नाम लिखें। उदाहरण: <code>/setfolder Batch 1</code>", parse_mode="HTML")
        return
    query = parts[1].strip().lower()
    cfg = read_config()
    match = next((f for f in cfg["folders"] if query in f["title"].lower()), None)
    if match:
        user_active_folder[message.chat.id] = match["id"]
        bot.reply_to(message, f"✅ अगली फ़ाइलें इस फ़ोल्डर में जाएँगी: <b>{match['title']}</b>", parse_mode="HTML")
    else:
        bot.reply_to(message, "❌ यह फ़ोल्डर नहीं मिला। पहले <code>/newfolder</code> से बनाएँ।", parse_mode="HTML")

@bot.message_handler(commands=['renamefolder'])
def rename_folder_cmd(message):
    raw_text = message.text.replace('/renamefolder', '', 1).strip()
    if "->" not in raw_text:
        bot.reply_to(
            message,
            "❌ <b>गलत फॉर्मेट!</b>\n\nइस तरह लिखें:\n<code>/renamefolder PuranaNaam -> NayaNaam</code>",
            parse_mode="HTML"
        )
        return

    old_name, new_name = [x.strip() for x in raw_text.split("->", 1)]
    if not old_name or not new_name:
        bot.reply_to(message, "पुराना और नया दोनों नाम लिखना ज़रूरी है।")
        return

    cfg = read_config()
    folder = next((f for f in cfg.get("folders", []) if old_name.lower() in f["title"].lower()), None)
    
    if folder:
        old_title = folder["title"]
        folder["title"] = new_name
        save_config(cfg)
        bot.reply_to(
            message,
            f"✅ <b>फ़ोल्डर का नाम बदल दिया गया है!</b>\n\n📁 पहले: <s>{old_title}</s>\n✨ अब: <b>{new_name}</b>",
            parse_mode="HTML"
        )
    else:
        bot.reply_to(message, f"❌ '<code>{old_name}</code>' नाम का कोई फ़ोल्डर नहीं मिला।", parse_mode="HTML")

@bot.message_handler(commands=['setchannel'])
def set_channel_cmd(message):
    global current_target_channel
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "चैनल का यूज़रनेम लिखें: <code>/setchannel @MyChannel</code>", parse_mode="HTML")
        return
    ch = parts[1].strip()
    if not ch.startswith("@") and not ch.startswith("-100"): ch = "@" + ch
    current_target_channel = ch
    bot.reply_to(message, f"✅ लक्ष्य चैनल सेट हो गया: <code>{current_target_channel}</code>", parse_mode="HTML")

@bot.message_handler(content_types=['document'])
def handle_doc_upload(message):
    local_path = None
    try:
        file_name = message.document.file_name
        lower_name = file_name.lower()
        if not (lower_name.endswith('.docx') or lower_name.endswith('.pdf')):
            bot.reply_to(message, "⚠️ कृपया केवल .docx या .pdf फ़ाइल भेजें।")
            return

        status = bot.reply_to(message, "⏳ फ़ाइल डाउनलोड व पार्स हो रही है...")
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)

        local_path = f"temp_{int(time.time())}_{file_name}"
        with open(local_path, 'wb') as f: f.write(downloaded)

        if lower_name.endswith('.docx'): raw_text = extract_text_from_docx(local_path)
        else: raw_text = extract_text_from_pdf(local_path)

        quizzes = parse_document_to_mcqs(raw_text)
        if not quizzes:
            bot.edit_message_text("❌ फ़ाइल में वैध प्रश्न नहीं मिले।", chat_id=message.chat.id, message_id=status.message_id)
            return

        safe_title = re.sub(r'[^a-zA-Z0-9_\u0900-\u097F\s-]', '', file_name.rsplit('.', 1)[0]).strip()
        test_id = f"test_{int(time.time())}"
        test_payload = {
            "id": test_id,
            "title": safe_title if safe_title else f"Mock Test {int(time.time())}",
            "questions": quizzes
        }

        with open(os.path.join(DATA_DIR, f"{test_id}.json"), 'w', encoding='utf-8') as f:
            json.dump(test_payload, f, ensure_ascii=False, indent=2)

        cfg = read_config()
        chosen_fid = user_active_folder.get(message.chat.id)
        target_folder = next((f for f in cfg["folders"] if f["id"] == chosen_fid), None)
        if not target_folder:
            target_folder = cfg["folders"][0]

        target_folder["test_ids"].append(test_id)
        save_config(cfg)

        current_url = os.environ.get("RENDER_EXTERNAL_URL", WEBAPP_URL)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(text="📂 Open Portal", web_app=WebAppInfo(url=current_url)))

        bot.edit_message_text(
            f"🎉 <b>नया टेस्ट लोड हो गया!</b>\n\n"
            f"📁 <b>फ़ोल्डर:</b> {target_folder['title']}\n"
            f"📝 <b>टेस्ट:</b> {test_payload['title']}\n"
            f"📊 <b>कुल प्रश्न:</b> {len(quizzes)}",
            chat_id=message.chat.id,
            message_id=status.message_id,
            reply_markup=markup,
            parse_mode="HTML"
        )

        try:
            bot_info = bot.get_me()
            bot_username = bot_info.username
            channel_url = f"https://t.me/{bot_username}?startapp=test"

            ch_markup = InlineKeyboardMarkup()
            ch_markup.add(InlineKeyboardButton(text=f"📝 Start {test_payload['title']}", url=channel_url))

            bot.send_message(
                chat_id=current_target_channel,
                text=(
                    f"🔥 <b>New Test Uploaded!</b>\n\n"
                    f"📁 <b>फ़ोल्डर:</b> {target_folder['title']}\n"
                    f"📝 <b>टेस्ट:</b> {test_payload['title']}\n"
                    f"📊 <b>कुल प्रश्न:</b> {len(quizzes)}\n\n"
                    "टेस्ट देने के लिए नीचे बटन पर क्लिक करें:"
                ),
                reply_markup=ch_markup,
                parse_mode="HTML"
            )
        except Exception as ce:
            print(f"Channel post error: {ce}")

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
    finally:
        if local_path and os.path.exists(local_path): os.remove(local_path)

@bot.message_handler(content_types=['web_app_data'])
def handle_result(message):
    try:
        data = json.loads(message.web_app_data.data)
        bot.reply_to(
            message,
            f"📊 <b>परिणाम सहेजा गया:</b>\nस्कोर: <b>{data['score']}/{data['total']}</b> | सटीकता: <b>{data['accuracy']}%</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass

if __name__ == "__main__":
    print("Folder Portal Bot Live with Buttons...")
    try: bot.remove_webhook()
    except Exception: pass
    bot.infinity_polling(skip_pending=True)
    

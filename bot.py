import os
import re
import json
import time
import threading
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from pypdf import PdfReader
from docx import Document
from flask import Flask, render_template, jsonify

# ================= FLASK WEB APP SERVER =================
app = Flask(__name__, template_folder="templates")

# जब Render पर नई सेवा बन जाएगी तो यह URL अपने आप सेट हो जाएगा
WEBAPP_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://quizz-lfdt.onrender.com")
QUESTIONS_FILE = "questions.json"

@app.route('/')
def home():
    return render_template("index.html")

@app.route('/api/questions')
def get_questions():
    if os.path.exists(QUESTIONS_FILE):
        try:
            with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception:
            return jsonify([])
    return jsonify([])

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()
# ========================================================

# नया टोकन Render Environment me dalenge
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PASTE_YOUR_NEW_BOT_TOKEN_HERE")
bot = telebot.TeleBot(BOT_TOKEN)

def extract_text_from_pdf(file_path):
    text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
    except Exception as e:
        print(f"PDF Error: {e}")
    return text

def extract_text_from_docx(file_path):
    text = ""
    try:
        doc = Document(file_path)
        for p in doc.paragraphs:
            if p.text:
                text += p.text + "\n"
    except Exception as e:
        print(f"DOCX Error: {e}")
    return text

def parse_document_to_testbook_format(text):
    quizzes = []
    raw_blocks = re.split(r'\n(?=Question:)', "\n" + text.strip())
    opt_map = {'a': 0, 'b': 1, 'c': 2, 'd': 3}

    for block in raw_blocks:
        if not block.strip() or "Question:" not in block:
            continue
        try:
            q_match = re.search(r'Question:\s*(.*?)(?=\([a-dA-D]\)|Answer:|$)', block, re.DOTALL)
            if not q_match:
                continue
            question = q_match.group(1).strip()

            options = []
            opt_pattern = re.findall(r'\(([a-dA-D])\)\s*(.*?)(?=\([a-dA-D]\)|Answer:|Solution:|Key Points:|Positive Marks:|$)', block, re.DOTALL)
            for tag, opt_text in opt_pattern:
                clean_opt = opt_text.strip()
                if clean_opt:
                    options.append(clean_opt)

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
        except Exception as e:
            continue

    return quizzes

@bot.message_handler(commands=['start', 'test', 'help'])
def send_welcome(message):
    total_q = 0
    if os.path.exists(QUESTIONS_FILE):
        try:
            with open(QUESTIONS_FILE, 'r', encoding='utf-8') as f:
                total_q = len(json.load(f))
        except Exception:
            pass

    current_url = os.environ.get("RENDER_EXTERNAL_URL", WEBAPP_URL)
    markup = InlineKeyboardMarkup()
    btn = InlineKeyboardButton(
        text="🚀 Open Testbook Exam Portal",
        web_app=WebAppInfo(url=current_url)
    )
    markup.add(btn)

    text = (
        "📖 **Online Examination & Mock Test Portal**\n\n"
        f"📊 **वर्तमान टेस्ट:** {total_q} प्रश्न उपलब्ध हैं।\n"
        "⏱ **समय:** 30 मिनट\n"
        "• Testbook जैसा Question Palette (1, 2, 3... Grid)\n"
        "• Instant Scorecard & Analytics\n"
        "• सबमिट के बाद सम्पूर्ण हल और Key Points\n\n"
        "📌 **नया टेस्ट अपलोड करने के लिए:** मुझे अपनी .docx या .pdf फ़ाइल भेजें!\n\n"
        "नीचे बटन पर क्लिक करके टेस्ट दें 👇"
    )
    bot.reply_to(message, text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(content_types=['document'])
def handle_upload(message):
    local_path = None
    try:
        file_name = message.document.file_name.lower()
        if not (file_name.endswith('.docx') or file_name.endswith('.pdf')):
            bot.reply_to(message, "⚠️ कृपया केवल .docx या .pdf फ़ाइल भेजें।")
            return

        status = bot.reply_to(message, "⏳ फ़ाइल डाउनलोड की जा रही है...")
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)

        local_path = f"temp_{int(time.time())}_{message.document.file_name}"
        with open(local_path, 'wb') as f:
            f.write(downloaded)

        bot.edit_message_text("🔍 फ़ाइल से प्रश्नों को पार्स किया जा रहा है...", chat_id=message.chat.id, message_id=status.message_id)

        if local_path.lower().endswith('.docx'):
            raw_text = extract_text_from_docx(local_path)
        else:
            raw_text = extract_text_from_pdf(local_path)

        quizzes = parse_document_to_testbook_format(raw_text)

        if not quizzes:
            bot.edit_message_text("❌ फ़ाइल में वैध प्रश्न नहीं मिले।", chat_id=message.chat.id, message_id=status.message_id)
            return

        with open(QUESTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(quizzes, f, ensure_ascii=False, indent=2)

        current_url = os.environ.get("RENDER_EXTERNAL_URL", WEBAPP_URL)
        markup = InlineKeyboardMarkup()
        btn = InlineKeyboardButton(
            text=f"📝 Start Test ({len(quizzes)} Questions)",
            web_app=WebAppInfo(url=current_url)
        )
        markup.add(btn)

        bot.edit_message_text(
            f"🎉 **सफलतापूर्वक नया टेस्ट लोड हो गया!**\n\n"
            f"• कुल प्रश्न: **{len(quizzes)}**\n"
            f"• सभी व्याख्या और मुख्य बिंदु पोर्टल में अपडेट हो चुके हैं।\n\n"
            f"नीचे दिए गए बटन से टेस्ट शुरू करें:",
            chat_id=message.chat.id,
            message_id=status.message_id,
            reply_markup=markup,
            parse_mode="Markdown"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ एरर: {e}")
    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)

@bot.message_handler(content_types=['web_app_data'])
def receive_result(message):
    try:
        data = json.loads(message.web_app_data.data)
        summary = (
            "📋 **आपका टेस्ट परिणाम (Scorecard)**\n\n"
            f"🎯 कुल स्कोर: *{data['score']} / {data['total']}*\n"
            f"✅ सही प्रश्न: *{data['correct']}*\n"
            f"❌ गलत प्रश्न: *{data['wrong']}*\n"
            f"⚪ अनुत्तरित (Skipped): *{data['skipped']}*\n"
            f"📊 सटीकता (Accuracy): *{data['accuracy']}%*\n\n"
            "विस्तृत समाधान देखने के लिए ऐप में नीचे स्क्रॉल करें।"
        )
        bot.reply_to(message, summary, parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "टेस्ट पूरा करने के लिए धन्यवाद!")

if __name__ == "__main__":
    print("Bot & Web App starting...")
    try:
        bot.remove_webhook()
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
                               

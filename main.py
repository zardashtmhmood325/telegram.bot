# ==========================================
# keep_alive (بۆ ٢٤/٧)
# ==========================================
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "✅ بۆتی Zardasht زیندووە!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

keep_alive()

# ==========================================
# کتێبخانەکان
# ==========================================
import logging
import os
import io
import json
import base64
import urllib.parse
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from openai import OpenAI
from gtts import gTTS

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ==========================================
# تۆکنەکان
# ==========================================
TELEGRAM_TOKEN = "8333823444:AAGojqXBowJ97BbAaLk1iGEHbAnqsxPNQZQ"
GROQ_API_KEY = "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"
ADMIN_ID = 8821671015

MODEL_NAME = "llama-3.3-70b-versatile"
# تەنها مۆدێلە زیندووەکە (maverick مردووە، لایماندا)
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

chat_history = {}
user_stats = {}
conversation_logs = {}
last_tts_request = {}

def load_data():
    global user_stats, conversation_logs
    if os.path.exists("user_stats.json"):
        with open("user_stats.json", "r", encoding="utf-8") as f:
            user_stats = json.load(f)
    if os.path.exists("conversation_logs.json"):
        with open("conversation_logs.json", "r", encoding="utf-8") as f:
            conversation_logs = json.load(f)

def save_data():
    with open("user_stats.json", "w", encoding="utf-8") as f:
        json.dump(user_stats, f, ensure_ascii=False, indent=2)
    with open("conversation_logs.json", "w", encoding="utf-8") as f:
        json.dump(conversation_logs, f, ensure_ascii=False, indent=2)

def register_user(user_id, username):
    if user_id not in user_stats:
        user_stats[user_id] = {
            "username": username,
            "message_count": 0,
            "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_data()
    else:
        user_stats[user_id]["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_data()

def log_message(user_id, message, response=None):
    if user_id not in conversation_logs:
        conversation_logs[user_id] = []
    log_entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": message,
        "response": response
    }
    conversation_logs[user_id].append(log_entry)
    if len(conversation_logs[user_id]) > 100:
        conversation_logs[user_id] = conversation_logs[user_id][-100:]
    save_data()

# ==========================================
# یارمەتیدەری کەمکردنەوەی قەبارەی وێنە
# ==========================================
def shrink_image(file_bytes, max_size=800, quality=60):
    if not HAS_PIL:
        return file_bytes
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_size:
            ratio = max_size / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()
    except Exception as e:
        print(f"shrink error: {e}")
        return file_bytes

# ==========================================
# خوێندنەوەی وێنە بە Groq Vision
# ==========================================
def groq_vision(img_base64, question):
    data_url = f"data:image/jpeg;base64,{img_base64}"
    messages = [
        {
            "role": "system",
            "content": (
                "تۆ یاریدەدەرێکی زیرەکی دەستکردیت کە لەلایەن Zardasht دروستکراویت. "
                "توانای بینینی وێنەت هەیە. بە وردی وێنەکە بخوێنەرەوە و بە کوردی سۆرانی ڕەوان وەڵام بدەرەوە."
            )
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": data_url}}
            ]
        }
    ]
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=messages,
        temperature=0.3,
    )
    return response.choices[0].message.content

# ==========================================
# پشتگیری دووەم: OCR.space (بێ پێویستی بە کلیلی تایبەت)
# ==========================================
def ocr_fallback(file_bytes, question):
    try:
        r = requests.post(
            "https://api.ocr.space/parse/image",
            data={"apikey": "helloworld", "language": "eng", "isOverlayRequired": "false"},
            files={"file": ("image.jpg", file_bytes, "image/jpeg")},
            timeout=40,
        )
        data = r.json()
        parsed = data.get("ParsedResults", [])
        if not parsed:
            return None
        text = parsed[0].get("ParsedText", "").strip()
        if not text:
            return None
        # ئێستا دەقەکە بنێرە بۆ AI بۆ وەرگێڕان/ڕوونکردنەوە بە کوردی
        prompt = (
            f"ئەم دەقە لە وێنەیەکەوە خوێندراوەتەوە:\n\n{text}\n\n"
            f"داواکاری بەکارهێنەر: {question}\n\n"
            "تکایە بە کوردی سۆرانی ڕەوان وەڵام بدەرەوە و باس لەوە بکە کە لەلایەن Zardasht دروستکراویت."
        )
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f"OCR fallback error: {e}")
        return None

# ==========================================
# فەرمانەکان
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    chat_history[user_id] = []
    register_user(user_id, username)
    keyboard = [
        [InlineKeyboardButton("🎨 دروستکردنی ڕەسم", callback_data="help_imagine")],
        [InlineKeyboardButton("🔊 ناردنی دەنگ", callback_data="help_tts")],
        [InlineKeyboardButton("🌤️ کەشوھەوا", callback_data="help_weather")],
        [InlineKeyboardButton("🌐 وەرگێڕان", callback_data="help_translate")],
        [InlineKeyboardButton("🖼️ خوێندنەوەی وێنە", callback_data="help_vision")],
        [InlineKeyboardButton("📊 ئامارەکان", callback_data="help_stats")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_msg = (
        f"سڵاو {update.effective_user.first_name}! من بۆتێکی زیرەکم 🤖\n\n"
        "دەتوانم یارمەتیت بدەم، پرسیارەکانت وەڵام بدەمەوە، ڕەسمت بۆ دروست بکەم، دەنگ بنێرم، وێنە بخوێنمەوە، و زۆر شتی تر!\n\n"
        "💻 ئەم بۆتە بە شێوەیەکی تایبەت و خۆشەویستی لەلایەن گەنجێکی بەتوانا بە ناوی **Zardasht** پەرەی پێدراوە.\n\n"
        "تکایە یەکێک لە دوگمەکانی خوارەوە هەڵبژێرە بۆ زانینی زیاتر:"
    )
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode="Markdown")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_history[user_id] = []
    await update.message.reply_text("مێشکم پاک کرایەوە! ئێستا ئامادەم بۆ بابەتی نوێ. 🧠✨")

async def imagine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("تکایە وەسفێک بنووسە بۆ ڕەسمەکە. نموونە:\n/imagine دارستانێکی جادویی لەژێر ڕۆشنایی مانگدا")
        return
    prompt = " ".join(context.args)
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username)
    user_stats[user_id]["message_count"] += 1
    save_data()
    await update.message.reply_text("🎨 خەریکی دروستکردنی ڕەسمم... تکایە چەند چرکەیەک چاوەڕێ بە.")
    try:
        encoded_prompt = urllib.parse.quote(prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&model=flux"
        await update.message.reply_photo(photo=image_url, caption=f"🎨 وەسف: {prompt}\n\n👨‍💻 دروستکراوە لەلایەن بۆتی Zardasht")
        log_message(user_id, f"/imagine {prompt}", "Image generated")
    except Exception as e:
        print(f"هەڵە: {e}")
        await update.message.reply_text("ببورە، هەڵەیەک لە دروستکردنی ڕەسمەکەدا ڕوویدا.")

async def tts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("تکایە دەقێک بنووسە بۆ گۆڕینی بۆ دەنگ. نموونە:\n/tts سڵاو، من بۆتێکی زیرەکم")
        return
    text = " ".join(context.args)
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username)
    await update.message.reply_text("🔊 خەریکی دروستکردنی دەنگم...")
    try:
        filename = f"tts_{user_id}.mp3"
        tts = gTTS(text=text, lang='ar', slow=False)
        tts.save(filename)
        with open(filename, "rb") as audio:
            await update.message.reply_audio(audio=audio, caption=f"🔊 {text[:50]}...")
        if os.path.exists(filename):
            os.remove(filename)
        log_message(user_id, f"/tts {text}", "Audio generated")
    except Exception as e:
        print(f"هەڵە: {e}")
        await update.message.reply_text("ببورە، هەڵەیەک لە دروستکردنی دەنگەکەدا ڕوویدا.")

async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("تکایە ناوی شارێک بنووسە. نموونە:\n/weather Hewler\n/weather Sulaymaniyah")
        return
    city = " ".join(context.args)
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username)
    await update.message.reply_text(f"🌤️ خەریکی پشکنینی کەشوھەوای {city}م...")
    try:
        geocode_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1"
        geo_response = requests.get(geocode_url).json()
        if "results" not in geo_response or len(geo_response["results"]) == 0:
            await update.message.reply_text(f"ببورە، نەمتوانی شاری {city} بدۆزمەوە.")
            return
        lat = geo_response["results"][0]["latitude"]
        lon = geo_response["results"][0]["longitude"]
        country = geo_response["results"][0].get("country", "Unknown")
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        weather_response = requests.get(weather_url).json()
        current = weather_response["current_weather"]
        temp = current["temperature"]
        windspeed = current["windspeed"]
        await update.message.reply_text(
            f"🌤️ کەشوھەوای {city}, {country}:\n\n"
            f"🌡️ پلەی گەرما: {temp}°C\n"
            f"💨 خێرایی با: {windspeed} km/h\n\n"
            f"👨‍ بۆتی Zardasht"
        )
        log_message(user_id, f"/weather {city}", f"Weather: {temp}°C")
    except Exception as e:
        print(f"هەڵە: {e}")
        await update.message.reply_text("ببورە، هەڵەیەک لە پشکنینی کەشوھەوادا ڕوویدا.")

async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("تکایە زمان و دەق بنووسە. نموونە:\n/tr en سڵاو\n/tr ku Hello")
        return
    target_lang = context.args[0].lower()
    text = " ".join(context.args[1:])
    user_id = update.effective_user.id
    register_user(user_id, update.effective_user.username)
    await update.message.reply_text("🌐 خەریکی وەرگێڕانم...")
    try:
        system_prompt = f"Translate the following text to {target_lang}. Only return the translation, nothing else."
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.3,
        )
        translation = response.choices[0].message.content
        last_tts_request[user_id] = (translation, 'ar')
        keyboard = [[InlineKeyboardButton("🔊 گوێ لە وەرگێڕان بگرە", callback_data=f"tts_translate_{user_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"🌐 وەرگێڕان بۆ {target_lang.upper()}:\n\n{translation}", reply_markup=reply_markup)
        log_message(user_id, f"/translate {text}", translation)
    except Exception as e:
        print(f"هەڵە: {e}")
        await update.message.reply_text("ببورە، هەڵەیەک لە وەرگێڕاندا ڕوویدا.")

# ==========================================
# 🖼️ خوێندنەوەی وێنە (بەهێزکراو + پشتگیری دووەم)
# ==========================================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    register_user(user_id, username)
    user_stats[user_id]["message_count"] += 1
    save_data()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    photo = update.message.photo[-1]
    caption = update.message.caption or "تکایە هەموو دەق و زانیارییەکانی ناو ئەم وێنەیە بخوێنەرەوە و بە کوردی سۆرانی ڕەوان ڕوونی بکەرەوە."

    await update.message.reply_text("🖼️ خەریکی شیکردنەوەی وێنەکەم... تکایە چەند چرکەیەک چاوەڕێ بە.")

    try:
        file = await context.bot.get_file(photo.file_id)
        file_bytes = bytes(await file.download_as_bytearray())
        file_bytes = shrink_image(file_bytes)
        img_base64 = base64.b64encode(file_bytes).decode('utf-8')

        ai_reply = None

        # ڕێگای ١: Groq Vision
        try:
            ai_reply = groq_vision(img_base64, caption)
            print("✅ Groq Vision succeeded")
        except Exception as e:
            print(f"⚠️ Groq Vision failed: {e}")
            ai_reply = None

        # ڕێگای ٢: ئەگەر Groq شکستی هێنا، OCR fallback
        if not ai_reply:
            print("🔄 Trying OCR fallback...")
            ai_reply = ocr_fallback(file_bytes, caption)
            if ai_reply:
                print("✅ OCR fallback succeeded")

        if not ai_reply:
            raise Exception("هەردوو ڕێگاکە شکستیان هێنا")

        last_tts_request[user_id] = (ai_reply, 'ar')
        keyboard = [[InlineKeyboardButton("🔊 گوێ لە وەڵام بگرە", callback_data=f"tts_reply_{user_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(ai_reply, reply_markup=reply_markup)
        log_message(user_id, f"[وێنە] {caption}", ai_reply)

    except Exception as e:
        print(f"هەڵەی وێنە: {e}")
        await update.message.reply_text("ببورە، نەمتوانی وێنەکە بخوێنمەوە. تکایە وێنەیەکی ڕوونتر و ڕاستتر بنێرە (بێ سووڕانەوە).")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("ببورە، تەنها Zardasht دەتوانێت ئەم فەرمانە بەکاربهێنێت.")
        return
    total_users = len(user_stats)
    total_messages = sum(u["message_count"] for u in user_stats.values())
    top_users = sorted(user_stats.items(), key=lambda x: x[1]["message_count"], reverse=True)[:5]
    top_users_text = "\n".join([f"{i+1}. @{u[1]['username']} - {u[1]['message_count']} نامە" for i, u in enumerate(top_users)])
    await update.message.reply_text(
        f"📊 ئامارەکانی بۆت:\n\n"
        f"👥 کۆی بەکارهێنەران: {total_users}\n"
        f"💬 کۆی نامەکان: {total_messages}\n\n"
        f"🏆 باشترین بەکارهێنەران:\n{top_users_text}\n\n"
        f"👨‍💻 بۆتی Zardasht"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("ببورە، تەنها Zardasht دەتوانێت ئەم فەرمانە بەکاربهێنێت.")
        return
    if not context.args:
        await update.message.reply_text("تکایە نامەیەک بنووسە بۆ ناردن بۆ هەموو بەکارهێنەران.\n/broadcast نامەکەت لێرە")
        return
    message = " ".join(context.args)
    sent_count = 0
    failed_count = 0
    await update.message.reply_text(f"📢 خەریکی ناردنی نامە بۆ {len(user_stats)} بەکارهێنەر...")
    for uid in list(user_stats.keys()):
        try:
            await context.bot.send_message(chat_id=uid, text=message)
            sent_count += 1
        except Exception as e:
            failed_count += 1
            print(f"هەڵە لە ناردن بۆ {uid}: {e}")
    await update.message.reply_text(f"✅ نامەکە نێردرا!\n\nسەرکەوتوو: {sent_count}\nشکستخواردوو: {failed_count}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    if data == "help_imagine":
        await query.edit_message_text("🎨 **دروستکردنی ڕەسم:**\n\nبۆ دروستکردنی ڕەسم، فەرمانی /imagine بەکاربهێنە و وەسفێک بنووسە.\n\nنموونە:\n/imagine دارستانێکی جادویی")
    elif data == "help_tts":
        await query.edit_message_text("🔊 **ناردنی دەنگ:**\n\nبۆ گۆڕینی دەق بۆ دەنگ، فەرمانی /tts بەکاربهێنە.\n\nنموونە:\n/tts سڵاو، من بۆتێکی زیرەکم")
    elif data == "help_weather":
        await query.edit_message_text("🌤️ **کەشوھەوا:**\n\nبۆ پشکنینی کەشوھەوا، فەرمانی /weather بەکاربهێنە و ناوی شارێک بنووسە.\n\nنموونە:\n/weather Hewler")
    elif data == "help_translate":
        await query.edit_message_text("🌐 **وەرگێڕان:**\n\nبۆ وەرگێڕان، فەرمانی /tr بەکاربهێنە، زمان و دەق بنووسە.\n\nنموونە:\n/tr en سڵاو")
    elif data == "help_vision":
        await query.edit_message_text("🖼️ **خوێندنەوەی وێنە:**\n\nتەنها وێنەیەک بنێرە بۆ بۆتەکە. بۆتەکە دەق و زانیارییەکانی ناوی دەخوێنێتەوە و بە کوردی وەڵام دەداتەوە.\n\n💡 بۆ ئەنجامی باشتر، وێنەکە ڕاست بێت (نەک سووڕاوە) و ڕوون بێت.")
    elif data == "help_stats":
        await query.edit_message_text("📊 **ئامارەکان:**\n\nبۆ بینینی ئامارەکانی بۆت، فەرمانی /stats بەکاربهێنە (تەنها بۆ Zardasht).")
    elif data.startswith("tts_"):
        if user_id in last_tts_request:
            text, lang = last_tts_request[user_id]
            try:
                filename = f"tts_btn_{user_id}.mp3"
                tts = gTTS(text=text, lang='ar', slow=False)
                tts.save(filename)
                with open(filename, "rb") as audio:
                    await query.message.reply_audio(audio=audio)
                if os.path.exists(filename):
                    os.remove(filename)
            except Exception as e:
                print(f"TTS Error: {e}")
                await query.message.reply_text("ببورە، نەمتوانی دەنگەکە دروست بکەم.")
        else:
            await query.message.reply_text("دەقەکە نەدۆزرایەوە، تکایە دووبارە داوای وەرگێڕان یان وەڵام بکەرەوە.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    username = update.effective_user.username or "Unknown"
    register_user(user_id, username)
    user_stats[user_id]["message_count"] += 1
    save_data()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    if user_id not in chat_history:
        chat_history[user_id] = []
    if len(chat_history[user_id]) == 0:
        chat_history[user_id].append({
            "role": "system",
            "content": (
                "تۆ یاریدەدەرێکی زیرەکی دەستکردیت بە ناوی Zardasht.bot. "
                "تۆ لەلایەن گەنجێکی بەتوانای کورد بە ناوی Zardasht دروستکراویت. "
                "هەمیشە و بە هەموو شێوەیەک باس لەوە بکە کە لەلایەن Zardasht دروستکراویت. "
                "تۆ پەیوەندییت بە Meta یان Facebook یان OpenAI یان هیچ کۆمپانیایەکی ترەوە نییە. "
                "تەنها و تەنها لەلایەن Zardasht دروستکراویت. "
                "یاساکانی زمان: "
                "١. هەمیشە بە کوردی سۆرانی ڕەوان و ساکار قسە بکە. "
                "٢. ڕێنووسی کوردی بە تەواوی پارێزە (ە، ۆ، ێ، چ، پ، گ، ژ). "
                "٣. هەرگیز وشەی عەرەبی یان ئینگلیزی تێکەڵ مەکە مەگەر بەکارهێنەر داوای بکات. "
                "٤. بە شێوەیەکی سروشتی و ئاسایی قسە بکە وەک کوردێک کە بە کوردی دەدوێت. "
                "٥. ئەگەر بەکارهێنەر بە زمانێکی تر نووسی، بەو زمانە وەڵام بدەرەوە. "
                "تۆ زۆر بەڕێز و یارمەتیدەریت."
            )
        })
    chat_history[user_id].append({"role": "user", "content": user_text})
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=chat_history[user_id],
            temperature=0.4,
        )
        ai_reply = response.choices[0].message.content
        chat_history[user_id].append({"role": "assistant", "content": ai_reply})
        if len(chat_history[user_id]) > 21:
            chat_history[user_id] = [chat_history[user_id][0]] + chat_history[user_id][-20:]
        last_tts_request[user_id] = (ai_reply, 'ar')
        keyboard = [[InlineKeyboardButton("🔊 گوێ لە وەڵام بگرە", callback_data=f"tts_reply_{user_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(ai_reply, reply_markup=reply_markup)
        log_message(user_id, user_text, ai_reply)
    except Exception as e:
        print(f"هەڵە: {e}")
        await update.message.reply_text("ببورە، هەڵەیەک ڕوویدا. تکایە دووبارە هەوڵ بدەرەوە.")

# ==========================================
# بەڕێوەبردنی سەرەکی
# ==========================================
def main():
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    load_data()
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(CommandHandler("imagine", imagine))
    application.add_handler(CommandHandler("tts", tts))
    application.add_handler(CommandHandler("weather", weather))
    application.add_handler(CommandHandler("tr", translate))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ بۆتەکە ئێستا کار دەکات (پەرەی پێدراوە لەلایەن Zardasht)...")
    print(f"👥 ژمارەی بەکارهێنەران: {len(user_stats)}")
    application.run_polling()

if __name__ == '__main__':
    main()

import os
import sys
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
import re
import time
import uuid
import threading
import subprocess
import requests
import telebot
from telebot import types
from bs4 import BeautifulSoup
from flask import Flask
import yt_dlp
import imageio_ffmpeg

# ==========================================
# إعدادات البوت الأساسية
# ==========================================
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8660209792:AAEJpMoNB7W_oBefqDj32EggEzG4NHsiay0").strip()
REPLICATE_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "").strip()

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

# ==========================================
# أنظمة إدارة وتعديل الفيديو (Video Editor Toolkit & AI Resolution Enhancer)
# ==========================================
user_states = {} # chat_id: {"state": "waiting_trim_range", "unique_id": ..., "status_msg_id": ...}
cached_files = {} # unique_id: {"file_path": "...", "chat_id": ...}

def upload_to_tmpfiles(local_path):
    try:
        with open(local_path, "rb") as f:
            r = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f}, timeout=15)
        if r.status_code == 200:
            res_data = r.json()
            raw_url = res_data.get("data", {}).get("url")
            if raw_url:
                return raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
    except Exception as e:
        print(f"[Upload Error]: {e}")
    return None

def schedule_file_cleanup(unique_id, delay=120):
    def cleanup():
        time.sleep(delay)
        try:
            for fname in os.listdir(DOWNLOAD_DIR):
                if fname.startswith(unique_id):
                    os.remove(os.path.join(DOWNLOAD_DIR, fname))
        except Exception:
            pass
        if unique_id in cached_files:
            try:
                del cached_files[unique_id]
            except Exception:
                pass
    threading.Thread(target=cleanup, daemon=True).start()

def get_editor_markup(unique_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✂️ قص وتقطيع (Trim)", callback_data=f"edit_trim|{unique_id}"),
        types.InlineKeyboardButton("🔇 كتم الصوت (Mute)", callback_data=f"edit_mute|{unique_id}")
    )
    markup.add(
        types.InlineKeyboardButton("↪️ تدوير يمين 90°", callback_data=f"edit_rotr|{unique_id}"),
        types.InlineKeyboardButton("↩️ تدوير يسار 90°", callback_data=f"edit_rotl|{unique_id}")
    )
    markup.add(
        types.InlineKeyboardButton("⚡ تسريع 2x", callback_data=f"edit_speed_fast|{unique_id}"),
        types.InlineKeyboardButton("🐢 تبطئة 0.5x", callback_data=f"edit_speed_slow|{unique_id}")
    )
    markup.add(
        types.InlineKeyboardButton("⚙️ الدقة والذكاء الاصطناعي", callback_data=f"edit_res_menu|{unique_id}"),
        types.InlineKeyboardButton("🎭 أدوات ومؤثرات إضافية", callback_data=f"edit_more_menu|{unique_id}")
    )
    markup.add(
        types.InlineKeyboardButton("🎵 استخراج الصوت MP3", callback_data=f"edit_audio|{unique_id}"),
        types.InlineKeyboardButton("❌ إلغاء وتنظيف", callback_data=f"edit_cancel|{unique_id}")
    )
    return markup

def get_resolution_markup(unique_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🎬 دقة منخفضة 480p (ضغط وحجم أقل)", callback_data=f"edit_res_low|{unique_id}"),
        types.InlineKeyboardButton("🎬 دقة متوسطة 720p (دقة عادية)", callback_data=f"edit_res_med|{unique_id}"),
        types.InlineKeyboardButton("✨ تحسين الجودة بالذكاء الاصطناعي (AI Upscale)", callback_data=f"edit_res_ai|{unique_id}"),
        types.InlineKeyboardButton("🔙 العودة لأدوات التعديل", callback_data=f"edit_back|{unique_id}")
    )
    return markup

def get_more_tools_markup(unique_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔘 تحويل لنوت دائرية", callback_data=f"edit_vnote|{unique_id}"),
        types.InlineKeyboardButton("🖼️ التقاط صورة مصغرة", callback_data=f"edit_thumb_menu|{unique_id}")
    )
    markup.add(
        types.InlineKeyboardButton("🏷️ إضافة نص مائي", callback_data=f"edit_wmark_menu|{unique_id}"),
        types.InlineKeyboardButton("📐 تغيير القياس والأبعاد", callback_data=f"edit_crop_menu|{unique_id}")
    )
    markup.add(
        types.InlineKeyboardButton("🎵 استبدال الصوت بالكامل", callback_data=f"edit_audio_replace|{unique_id}"),
        types.InlineKeyboardButton("🎚️ دمج صوتين ومستويات", callback_data=f"edit_audio_mix_menu|{unique_id}")
    )
    markup.add(
        types.InlineKeyboardButton("🔄 عكس الفيديو", callback_data=f"edit_rev|{unique_id}"),
        types.InlineKeyboardButton("🎞️ تحويل لـ GIF", callback_data=f"edit_gif|{unique_id}")
    )
    markup.add(
        types.InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=f"edit_back|{unique_id}")
    )
    return markup

def make_volume_bar(percentage):
    filled = max(0, min(10, int(percentage / 10)))
    empty = 10 - filled
    return "■" * filled + "□" * empty

def get_mix_bar_markup(unique_id, audio_unique_id, v0_percent=80, v1_percent=80):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➖ الأصلي -10%", callback_data=f"mix_adj|{unique_id}|{audio_unique_id}|{max(0, v0_percent - 10)}|{v1_percent}"),
        types.InlineKeyboardButton("➕ الأصلي +10%", callback_data=f"mix_adj|{unique_id}|{audio_unique_id}|{min(200, v0_percent + 10)}|{v1_percent}")
    )
    markup.add(
        types.InlineKeyboardButton("➖ الجديد -10%", callback_data=f"mix_adj|{unique_id}|{audio_unique_id}|{v0_percent}|{max(0, v1_percent - 10)}"),
        types.InlineKeyboardButton("➕ الجديد +10%", callback_data=f"mix_adj|{unique_id}|{audio_unique_id}|{v0_percent}|{min(200, v1_percent + 10)}")
    )
    markup.add(
        types.InlineKeyboardButton("✅ دمج وتطبيق الصوت", callback_data=f"edit_mixrun|{unique_id}|{audio_unique_id}|{v0_percent}|{v1_percent}")
    )
    markup.add(
        types.InlineKeyboardButton("❌ إلغاء وتراجع", callback_data=f"edit_cancel|{unique_id}")
    )
    return markup

def get_crop_markup(unique_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📐 عمودي 9:16 (Reels/Stories)", callback_data=f"edit_crop_916|{unique_id}"),
        types.InlineKeyboardButton("📐 أفقي 16:9 (YouTube)", callback_data=f"edit_crop_169|{unique_id}"),
        types.InlineKeyboardButton("📐 مربع 1:1 (Instagram Feed)", callback_data=f"edit_crop_11|{unique_id}"),
        types.InlineKeyboardButton("🔙 العودة للمؤثرات", callback_data=f"edit_more_menu|{unique_id}")
    )
    return markup

def run_ffmpeg_edit(chat_id, input_path, output_path, cmd, status_msg_id, success_caption, format_type='video'):
    try:
        bot.edit_message_text(
            "⏳ <b>جاري معالجة وتعديل الفيديو باستخدام محرك FFmpeg...</b>",
            chat_id=chat_id, message_id=status_msg_id
        )
        
        # Run process
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.wait()
        
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 100:
            raise Exception("فشلت معالجة الفيديو في FFmpeg.")
            
        bot.edit_message_text(
            "📥 <b>اكتمل التعديل بنجاح! جاري إرسال المقطع المحدث...</b> ⚡",
            chat_id=chat_id, message_id=status_msg_id
        )
        
        # Send output
        with open(output_path, "rb") as f:
            if format_type == 'audio':
                bot.send_audio(chat_id, f, caption=success_caption, reply_to_message_id=None)
            elif format_type == 'gif':
                bot.send_animation(chat_id, f, caption=success_caption, reply_to_message_id=None)
            elif format_type == 'vnote':
                bot.send_video_note(chat_id, f, reply_to_message_id=None)
            else:
                bot.send_video(chat_id, f, caption=success_caption, supports_streaming=True, reply_to_message_id=None)
                
        # Clean up status message
        try:
            bot.delete_message(chat_id, status_msg_id)
        except Exception:
            pass
            
    except Exception as e:
        bot.edit_message_text(
            f"❌ <b>فشلت عملية معالجة وتعديل المقطع:</b>\n<i>{str(e)[:120]}</i>",
            chat_id=chat_id, message_id=status_msg_id
        )
        # Delete error notification after 1 minute
        def delete_msg():
            time.sleep(60)
            try:
                bot.delete_message(chat_id, status_msg_id)
            except Exception:
                pass
        threading.Thread(target=delete_msg, daemon=True).start()
    finally:
        # Clean up output path
        try:
            os.remove(output_path)
        except Exception:
            pass

def run_ai_upscale(chat_id, file_path, unique_id, status_msg_id):
    try:
        if not REPLICATE_TOKEN:
            raise Exception("رمز الوصول للذكاء الاصطناعي (REPLICATE_API_TOKEN) غير مهيأ حالياً.")
            
        bot.edit_message_text(
            "⏳ <b>جاري رفع مقطع الفيديو لتمريره عبر الذكاء الاصطناعي...</b>",
            chat_id=chat_id, message_id=status_msg_id
        )
        
        # 1. Upload to tmpfiles to get public URL
        public_url = upload_to_tmpfiles(file_path)
        if not public_url:
            raise Exception("فشل رفع المقطع إلى خادم التجهيز العام.")
            
        bot.edit_message_text(
            "✨ <b>جاري تشغيل معالجة الذكاء الاصطناعي لإعادة بناء الجودة (Real-ESRGAN Video)... يرجى الانتظار دقيقة تقريباً</b> 🚀",
            chat_id=chat_id, message_id=status_msg_id
        )
        
        # 2. Call Replicate API
        headers = {
            "Authorization": f"Token {REPLICATE_TOKEN}",
            "Content-Type": "application/json"
        }
        
        url = "https://api.replicate.com/v1/predictions"
        payload = {
            "version": "e8b2c2865910fae1b9b4f4f7fa3fe8a8a49c6cb4b25dcdccdb3755331e847c23",
            "input": {
                "video": public_url,
                "scale": 2,
                "face_enhance": True
            }
        }
        
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        if r.status_code != 201:
            raise Exception(f"فشلت تهيئة المعالجة في Replicate: {r.text}")
            
        prediction = r.json()
        predict_id = prediction.get("id")
        
        # Poll prediction status
        status_url = f"https://api.replicate.com/v1/predictions/{predict_id}"
        max_checks = 60
        output_url = None
        
        for _ in range(max_checks):
            time.sleep(4)
            check_r = requests.get(status_url, headers=headers, timeout=15)
            if check_r.status_code == 200:
                res = check_r.json()
                status = res.get("status")
                if status == "succeeded":
                    output_url = res.get("output")
                    break
                elif status in ["failed", "canceled"]:
                    raise Exception(f"فشلت المعالجة أثناء تشغيل النموذج: {res.get('error')}")
            else:
                raise Exception(f"فشل التحقق من حالة المعالجة: {check_r.text}")
                
        if not output_url:
            raise Exception("انتهت مهلة الانتظار دون الحصول على نتائج من الذكاء الاصطناعي.")
            
        bot.edit_message_text(
            "📥 <b>اكتمل تحسين الجودة بالذكاء الاصطناعي! جاري تحميل المقطع المحسّن وإرساله...</b> ⚡",
            chat_id=chat_id, message_id=status_msg_id
        )
        
        # Download output video
        enhanced_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_ai_enhanced.mp4")
        video_data = requests.get(output_url, timeout=40).content
        with open(enhanced_path, "wb") as f:
            f.write(video_data)
            
        # Send video
        with open(enhanced_path, "rb") as f:
            bot.send_video(chat_id, f, caption="✨ تم تحسين الجودة والدقة بالذكاء الاصطناعي الفائق (AI Super Resolution) 🚀", reply_to_message_id=None)
            
        # Delete status message
        try:
            bot.delete_message(chat_id, status_msg_id)
        except Exception:
            pass
            
    except Exception as e:
        bot.edit_message_text(
            f"❌ <b>تعذر تحسين الفيديو بالذكاء الاصطناعي:</b>\n<i>{str(e)[:120]}</i>",
            chat_id=chat_id, message_id=status_msg_id
        )
        # Delete error notification after 1 minute
        def delete_msg():
            time.sleep(60)
            try:
                bot.delete_message(chat_id, status_msg_id)
            except Exception:
                pass
        threading.Thread(target=delete_msg, daemon=True).start()

# ==========================================
# الترحيب والقوائم التفاعلية
# ==========================================
@bot.message_handler(commands=['start', 'help'])
@bot.message_handler(func=lambda message: message.text and message.text.strip().lower() in ['start', 'help', 'مرحبا', 'أهلا', 'اهلين', 'هلو', 'السلام عليكم'])
def send_welcome(message):
    welcome_text = (
        f"<b>🤖 مرحباً بك يا {message.from_user.first_name} في البوت الشامل للتحميل!</b>\n\n"
        f"✨ أستطيع التحميل لك من <b>أكثر من 1000 منصة وتطبيق</b> بأعلى جودة ممكنة وبدون علامة مائية (بدون حقوق)، بما في ذلك:\n"
        f"▪️ <b>TikTok</b> (فيديوهات HD بدون حقوق أو علامة مائية + ألبومات الصور)\n"
        f"▪️ <b>Instagram</b> (Reels, ألبومات الصور Carousels, المنشورات)\n"
        f"▪️ <b>YouTube</b> (Shorts, الفيديوهات الطويلة, MP3)\n"
        f"▪️ <b>X / Twitter & Facebook & Pinterest & SoundCloud</b>\n\n"
        f"🎯 <b>كيفية الاستخدام:</b>\n"
        f"فقط أرسل لي أي رابط مباشرة هنا وسأقوم بسحبه وإرساله لك فوراً (فيديو صافي ومكتمل وخالي من الأشرطة والنصوص) 🚀"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💡 المنصات المدعومة", callback_data="info_platforms"),
        types.InlineKeyboardButton("❓ كيفية التحميل", callback_data="info_help"),
        types.InlineKeyboardButton("📊 حالة البوت", callback_data="info_status")
    )
    bot.reply_to(message, welcome_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("info_"))
def handle_info_callbacks(call):
    if call.data == "info_platforms":
        text = (
            "<b>💡 أبرز المنصات والمواقع المدعومة:</b>\n\n"
            "📹 <b>تيك توك (TikTok):</b> تحميل الفيديو الأصلي كاملاً بدون حقوق (بدون علامة مائية) وبدون أي أشرطة.\n"
            "📸 <b>إنستغرام (Instagram):</b> سحب الصور وألبومات المنشورات والريلز بأعلى دقة.\n"
            "🔴 <b>يوتيوب (YouTube):</b> تحميل المقاطع القصيرة Shorts والفيديوهات العادية واستخراج الصوت MP3.\n"
            "🐦 <b>تويتر (X) وفيسبوك:</b> سحب الفيديوهات بجودة HD."
        )
    elif call.data == "info_help":
        text = (
            "<b>❓ كيفية الاستخدام والتحميل:</b>\n\n"
            "1️⃣ افتح التطبيق (تيك توك، إنستغرام، يوتيوب...).\n"
            "2️⃣ اضغط على زر <b>مشاركة (Share)</b> ثم <b>نسخ الرابط (Copy Link)</b>.\n"
            "3️⃣ الصق الرابط هنا في المحادثة وأرسله لي.\n\n"
            "✨ سأرسل لك الفيديو أو الصور بشكل مباشر ونظيف جداً بدون أشرطة عنوان أو نصوص مزعجة!"
        )
    elif call.data == "info_status":
        text = (
            "<b>📊 حالة ومواصفات الخادم الحالي:</b>\n\n"
            "🟢 <b>حالة البوت:</b> متصل وجاهز للعمل بكفاءة عالية (Online 100%).\n"
            f"⚡ <b>محرك التحويل (FFmpeg):</b> متصل مدمج.\n"
            "🚀 <b>محرك السحب المتطور:</b> مفعل (TikWM HD + Instagram Scraper + yt-dlp).\n"
            "📁 <b>التنظيف التلقائي:</b> مفعل."
        )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text)

# ==========================================
# سحب مخصص لتيك توك بدون حقوق (No Watermark HD)
# ==========================================
def extract_tiktok_clean(url, unique_id):
    try:
        api_url = f"https://www.tikwm.com/api/?url={url}&hd=1"
        res = requests.get(api_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).json()
        data = res.get('data', {})
        
        # إذا كان منشور تيك توك يحتوي على صور (Photo slide)
        if 'images' in data and isinstance(data['images'], list) and len(data['images']) > 0:
            downloaded = []
            for idx, img_url in enumerate(data['images']):
                save_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_tiktok_{idx}.jpg")
                r = requests.get(img_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                if r.status_code == 200:
                    with open(save_path, 'wb') as f:
                        f.write(r.content)
                    downloaded.append(save_path)
            if downloaded:
                return downloaded, 'photo'

        # فيديو تيك توك HD بدون حقوق
        video_url = data.get('hdplay') or data.get('play')
        if video_url:
            save_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_tiktok_clean.mp4")
            r = requests.get(video_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
            if r.status_code == 200 and len(r.content) > 10000:
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                return [save_path], 'video'
    except Exception:
        pass
    return [], None

# ==========================================
# سحب مخصص لصور وألبومات إنستغرام (Carousel / Photos)
# ==========================================
def extract_instagram_clean(url, unique_id):
    try:
        clean_url = url.split('?')[0].rstrip('/')
        embed_url = f"{clean_url}/embed/captioned/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
        html = requests.get(embed_url, headers=headers, timeout=15).text
        soup = BeautifulSoup(html, 'html.parser')
        
        media_urls = []
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src and 'instagram.' in src or 'fbcdn.net' in src or 'cdninstagram.com' in src:
                # استبعاد صور الملف الشخصي والأيقونات الصغيرة جداً
                if 's150x150' not in src and 's100x100' not in src and '150x150' not in src and '100x100' not in src:
                    # تفضيل النسخة الأصلية عالية الدقة
                    clean_src = html.unescape(src).replace('\\/', '/')
                    if clean_src not in media_urls:
                        media_urls.append(clean_src)

        downloaded = []
        for idx, m_url in enumerate(media_urls[:10]):
            save_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_insta_{idx}.jpg")
            r = requests.get(m_url, headers=headers, timeout=15)
            if r.status_code == 200 and len(r.content) > 5000:
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                downloaded.append(save_path)
        if downloaded:
            return downloaded, 'photo'
    except Exception:
        pass
    return [], None

# ==========================================
# استلام الروابط ومعالجتها
# ==========================================
URL_REGEX = re.compile(r'https?://[^\s]+')

@bot.message_handler(func=lambda message: bool(URL_REGEX.search(message.text or "")))
def handle_url_message(message):
    urls = URL_REGEX.findall(message.text)
    for url in urls:
        status_msg = bot.reply_to(
            message,
            "⏳ <b>جاري سحب وتجهيز الفيديو بدون حقوق...</b>\n<i>يرجى الانتظار ثوانٍ معدودة ⚡</i>"
        )
        threading.Thread(
            target=process_and_send_download,
            args=(message, status_msg, url, 'video')
        ).start()

@bot.message_handler(func=lambda message: message.text and not bool(URL_REGEX.search(message.text or "")))
def handle_non_url_message(message):
    chat_id = message.chat.id
    text = message.text.strip()
    text_lower = text.lower()
    
    # Check waiting_trim_range state
    state_info = user_states.get(chat_id) or {}
    state = state_info.get("state")
    
    if state == "waiting_trim_range":
        unique_id = state_info.get("unique_id")
        status_msg_id = state_info.get("status_msg_id")
        
        # Reset state
        user_states[chat_id] = {"state": "idle"}
        
        try:
            parts = re.split(r'[-–]|إلى|الى|to', text)
            if len(parts) != 2:
                raise Exception("صيغة نطاق الوقت غير صحيحة. يرجى كتابتها بالصيغة (بداية - نهاية).")
                
            start_str = parts[0].strip()
            end_str = parts[1].strip()
            
            def to_seconds(t_str):
                if ":" in t_str:
                    t_parts = t_str.split(":")
                    if len(t_parts) == 2:
                        return int(t_parts[0]) * 60 + float(t_parts[1])
                    elif len(t_parts) == 3:
                        return int(t_parts[0]) * 3600 + int(t_parts[1]) * 60 + float(t_parts[2])
                return float(t_str)
                
            start_sec = to_seconds(start_str)
            end_sec = to_seconds(end_str)
            
            if start_sec >= end_sec:
                raise Exception("وقت البداية يجب أن يكون أقل من وقت النهاية للقص.")
                
            file_info = cached_files.get(unique_id)
            if not file_info:
                raise Exception("عذراً، انتهت صلاحية الفيديو المؤقت للتعديل (الحد الأقصى هو دقيقتان).")
                
            input_path = file_info["file_path"]
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_trimmed.mp4")
            
            cmd = [
                FFMPEG_PATH, "-y",
                "-ss", str(start_sec),
                "-to", str(end_sec),
                "-i", input_path,
                "-c:v", "libx264",
                "-c:a", "aac",
                "-strict", "experimental",
                output_path
            ]
            
            try:
                bot.delete_message(chat_id, message.message_id)
            except Exception:
                pass
                
            threading.Thread(
                target=run_ffmpeg_edit,
                args=(chat_id, input_path, output_path, cmd, status_msg_id, f"✂️ تم قص وتعديل المقطع بنجاح! ({start_str} - {end_str}) ⚡")
            ).start()
            
        except Exception as parse_err:
            bot.send_message(chat_id, f"❌ <b>خطأ: {parse_err}</b>\nيرجى إرسال نطاق القص بشكل صحيح (مثال: 10 - 30).")
        return

    elif state == "waiting_screenshot_time":
        unique_id = state_info.get("unique_id")
        status_msg_id = state_info.get("status_msg_id")
        user_states[chat_id] = {"state": "idle"}
        
        try:
            def to_seconds(t_str):
                if ":" in t_str:
                    t_parts = t_str.split(":")
                    if len(t_parts) == 2:
                        return int(t_parts[0]) * 60 + float(t_parts[1])
                    elif len(t_parts) == 3:
                        return int(t_parts[0]) * 3600 + int(t_parts[1]) * 60 + float(t_parts[2])
                return float(t_str)
                
            seconds = to_seconds(text)
            file_info = cached_files.get(unique_id)
            if not file_info:
                raise Exception("انتهت صلاحية الفيديو.")
                
            input_path = file_info["file_path"]
            output_jpg = os.path.join(DOWNLOAD_DIR, f"{unique_id}_screenshot.jpg")
            
            cmd = [
                FFMPEG_PATH, "-y",
                "-ss", str(seconds),
                "-i", input_path,
                "-vframes", "1",
                "-q:v", "2",
                output_jpg
            ]
            
            try:
                bot.delete_message(chat_id, message.message_id)
            except Exception:
                pass
                
            def run_capture():
                try:
                    bot.edit_message_text("⏳ <b>جاري التقاط لقطة الشاشة من الفيديو...</b>", chat_id=chat_id, message_id=status_msg_id)
                    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    p.wait()
                    if os.path.exists(output_jpg):
                        bot.edit_message_text("📤 <b>جاري إرسال الصورة الملتقطة...</b>", chat_id=chat_id, message_id=status_msg_id)
                        with open(output_jpg, "rb") as f:
                            bot.send_photo(chat_id, f, caption=f"🖼️ لقطة شاشة من الفيديو عند التوقيت: {text} ⚡")
                        try:
                            bot.delete_message(chat_id, status_msg_id)
                        except Exception:
                            pass
                    else:
                        raise Exception("فشل التقاط الصورة.")
                except Exception as ex:
                    bot.edit_message_text(f"❌ <b>فشل التقاط الصورة:</b>\n<i>{ex}</i>", chat_id=chat_id, message_id=status_msg_id)
                finally:
                    try:
                        os.remove(output_jpg)
                    except Exception:
                        pass
            threading.Thread(target=run_capture, daemon=True).start()
        except Exception as e:
            bot.send_message(chat_id, f"❌ <b>خطأ: {e}</b>\nيرجى كتابة التوقيت بشكل صحيح.")
        return

    elif state == "waiting_watermark_text":
        unique_id = state_info.get("unique_id")
        status_msg_id = state_info.get("status_msg_id")
        user_states[chat_id] = {"state": "idle"}
        
        try:
            file_info = cached_files.get(unique_id)
            if not file_info:
                raise Exception("انتهت صلاحية الفيديو.")
                
            input_path = file_info["file_path"]
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_watermarked.mp4")
            
            safe_text = text.replace("'", "").replace(":", "")
            cmd = [
                FFMPEG_PATH, "-y",
                "-i", input_path,
                "-vf", f"drawtext=text='{safe_text}':x=w-tw-15:y=h-th-15:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.4",
                "-c:v", "libx264",
                "-c:a", "copy",
                output_path
            ]
            
            try:
                bot.delete_message(chat_id, message.message_id)
            except Exception:
                pass
                
            threading.Thread(
                target=run_ffmpeg_edit,
                args=(chat_id, input_path, output_path, cmd, status_msg_id, f"🏷️ تم دمج النص المائي بنجاح! ({safe_text}) ⚡")
            ).start()
        except Exception as e:
            bot.send_message(chat_id, f"❌ <b>خطأ: {e}</b>")
        return

    sent_msg = bot.reply_to(
        message,
        "💡 <b>أهلاً بك في بوت التحميل الشامل!</b>\n"
        "لتحميل الفيديو أو الصور، يرجى إرسال <b>رابط (URL)</b> صحيح من أي منصة (يوتيوب، تيك توك، إنستغرام، فيسبوك، تويتر...) وسأقوم بسحبه لك فوراً بدون حقوق! 🚀\n\n"
        "🎬 <b>ملاحظة:</b> يمكنك أيضاً إرسال أي مقطع فيديو مباشرة من جهازك للبدء بقصه وتعديله فوراً!"
    )
    
    # Delete both user message and bot response after 1 minute to keep the screen clean
    def delete_msgs_after_delay(c_id, m_id1, m_id2):
        time.sleep(60)
        try:
            bot.delete_message(c_id, m_id1)
        except Exception:
            pass
        try:
            bot.delete_message(c_id, m_id2)
        except Exception:
            pass

    threading.Thread(
        target=delete_msgs_after_delay,
        args=(message.chat.id, message.message_id, sent_msg.message_id)
    ).start()

@bot.message_handler(content_types=['video'])
def handle_incoming_video(message):
    chat_id = message.chat.id
    status_msg = bot.reply_to(message, "⏳ <b>جاري استلام وتحميل الفيديو لتجهيز لوحة أدوات التعديل...</b>")
    try:
        file_info = bot.get_file(message.video.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        unique_id = f"edit_{uuid.uuid4().hex[:6]}"
        file_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_source.mp4")
        with open(file_path, "wb") as f:
            f.write(downloaded)
            
        cached_files[unique_id] = {"file_path": file_path, "chat_id": chat_id}
        
        # Schedule cleanup after 3 minutes (180s)
        schedule_file_cleanup(unique_id, 180)
        
        # Delete status message
        try:
            bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass
            
        # Send editing toolkit menu
        bot.send_message(
            chat_id,
            "🛠️ <b>استوديو تعديل وقص الفيديو</b>\n\nاختر الأداة المطلوبة للبدء بتعديل هذا الفيديو:",
            reply_markup=get_editor_markup(unique_id)
        )
        
        # Delete original video message to keep chat clean
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass
            
    except Exception as e:
        bot.edit_message_text(f"❌ فشل استلام الفيديو: {e}", chat_id=chat_id, message_id=status_msg.message_id)

@bot.message_handler(content_types=['audio', 'voice'])
def handle_incoming_audio_for_editor(message):
    chat_id = message.chat.id
    
    state_info = user_states.get(chat_id) or {}
    state = state_info.get("state")
    unique_id = state_info.get("unique_id")
    status_msg_id = state_info.get("status_msg_id")
    
    if state not in ["waiting_replace_audio", "waiting_mix_audio"]:
        # Standard non-editor audio file upload. Ignore it.
        return
        
    # Reset state immediately to prevent duplicate runs
    user_states[chat_id] = {"state": "idle"}
    
    status_msg = bot.send_message(chat_id, "⏳ <b>جاري استلام وتحميل الملف الصوتي المرفق...</b>")
    try:
        if message.content_type == 'voice':
            file_id = message.voice.file_id
        else:
            file_id = message.audio.file_id
            
        file_info = bot.get_file(file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        audio_unique_id = f"audio_{uuid.uuid4().hex[:6]}"
        audio_ext = ".ogg" if message.content_type == 'voice' else ".mp3"
        audio_path = os.path.join(DOWNLOAD_DIR, f"{audio_unique_id}{audio_ext}")
        with open(audio_path, "wb") as f:
            f.write(downloaded)
            
        cached_files[audio_unique_id] = {"file_path": audio_path, "chat_id": chat_id}
        schedule_file_cleanup(audio_unique_id, 180)
        
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass
            
        try:
            bot.delete_message(chat_id, status_msg_id)
        except Exception:
            pass
            
        file_info_video = cached_files.get(unique_id)
        if not file_info_video:
            raise Exception("انتهت صلاحية الفيديو المراد تعديله.")
            
        video_path = file_info_video["file_path"]
        
        if state == "waiting_replace_audio":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_replaced_audio.mp4")
            cmd = [
                FFMPEG_PATH, "-y",
                "-i", video_path,
                "-i", audio_path,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                output_path
            ]
            threading.Thread(
                target=run_ffmpeg_edit,
                args=(chat_id, video_path, output_path, cmd, status_msg.message_id, "🎵 تم استبدال وتغيير صوت الفيديو بالكامل بنجاح! ⚡")
            ).start()
            
        elif state == "waiting_mix_audio":
            try:
                bot.delete_message(chat_id, status_msg.message_id)
            except Exception:
                pass
            
            v0, v1 = 80, 80
            bar_orig = make_volume_bar(v0)
            bar_add = make_volume_bar(v1)
            
            bot.send_message(
                chat_id,
                f"🎚️ <b>لوحة التحكم بمستويات دمج الصوت:</b>\n\n"
                f"🔊 <b>صوت الفيديو الأصلي:</b>\n<code>[{bar_orig}] {v0}%</code>\n\n"
                f"🎵 <b>الملف الصوتي المضاف:</b>\n<code>[{bar_add}] {v1}%</code>\n\n"
                f"💡 <i>استخدم الأزرار أدناه لضبط مستويات الصوت بدقة ثم اضغط دمج:</i>",
                reply_markup=get_mix_bar_markup(unique_id, audio_unique_id, v0, v1)
            )
            
    except Exception as e:
        bot.edit_message_text(f"❌ <b>فشل استلام ومعالجة الصوت:</b>\n<i>{e}</i>", chat_id=chat_id, message_id=status_msg.message_id)
        def delete_err():
            time.sleep(30)
            try:
                bot.delete_message(chat_id, status_msg.message_id)
            except Exception:
                pass
        threading.Thread(target=delete_err, daemon=True).start()

@bot.callback_query_handler(func=lambda call: call.data.startswith("mix_adj|"))
def handle_mix_adjust_callbacks(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data
    
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
        
    parts = data.split("|")
    unique_id = parts[1]
    audio_unique_id = parts[2]
    v0 = int(parts[3])
    v1 = int(parts[4])
    
    v0 = max(0, min(200, v0))
    v1 = max(0, min(200, v1))
    
    bar_orig = make_volume_bar(v0)
    bar_add = make_volume_bar(v1)
    
    try:
        bot.edit_message_text(
            f"🎚️ <b>لوحة التحكم بمستويات دمج الصوت:</b>\n\n"
            f"🔊 <b>صوت الفيديو الأصلي:</b>\n<code>[{bar_orig}] {v0}%</code>\n\n"
            f"🎵 <b>الملف الصوتي المضاف:</b>\n<code>[{bar_add}] {v1}%</code>\n\n"
            f"💡 <i>استخدم الأزرار أدناه لضبط مستويات الصوت بدقة ثم اضغط دمج:</i>",
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=get_mix_bar_markup(unique_id, audio_unique_id, v0, v1)
        )
    except Exception:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_"))
def handle_editor_callbacks(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data
    
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
        
    parts = data.split("|")
    action = parts[0]
    unique_id = parts[1] if len(parts) > 1 else ""
    
    file_info = cached_files.get(unique_id)
    if not file_info and action not in ["edit_cancel", "edit_back"]:
        bot.send_message(chat_id, "❌ عذراً، انتهت صلاحية هذا الملف المؤقت للتحرير (الحد الأقصى هو دقيقتان).")
        try:
            bot.delete_message(chat_id, msg_id)
        except Exception:
            pass
        return
        
    input_path = file_info["file_path"] if file_info else ""
    
    if action == "edit_start":
        bot.send_message(
            chat_id,
            "🛠️ <b>استوديو تعديل وقص الفيديو</b>\n\nاختر الأداة المطلوبة للبدء بتعديل هذا الفيديو:",
            reply_markup=get_editor_markup(unique_id)
        )
        
    elif action == "edit_cancel":
        # Clear files immediately
        try:
            for fname in os.listdir(DOWNLOAD_DIR):
                if fname.startswith(unique_id):
                    os.remove(os.path.join(DOWNLOAD_DIR, fname))
        except Exception:
            pass
        if unique_id in cached_files:
            try:
                del cached_files[unique_id]
            except Exception:
                pass
        try:
            bot.delete_message(chat_id, msg_id)
        except Exception:
            pass
            
    elif action == "edit_back":
        bot.edit_message_text(
            "🛠️ <b>استوديو تعديل وقص الفيديو</b>\n\nاختر الأداة المطلوبة للبدء بتعديل هذا الفيديو:",
            chat_id=chat_id, message_id=msg_id, reply_markup=get_editor_markup(unique_id)
        )
        
    elif action == "edit_res_menu":
        bot.edit_message_text(
            "⚙️ <b>خيارات الدقة والذكاء الاصطناعي للفيديو</b>\n\nاختر الإجراء المطلوب لتعديل دقة وجودة الفيديو:",
            chat_id=chat_id, message_id=msg_id, reply_markup=get_resolution_markup(unique_id)
        )
        
    elif action == "edit_more_menu":
        bot.edit_message_text(
            "🎭 <b>أدوات ومؤثرات تعديل إضافية</b>\n\nاختر الأداة الإضافية لتعديل مقطع الفيديو:",
            chat_id=chat_id, message_id=msg_id, reply_markup=get_more_tools_markup(unique_id)
        )
        
    elif action == "edit_crop_menu":
        bot.edit_message_text(
            "📐 <b>تغيير القياس وقص الأبعاد للفيديو</b>\n\nاختر البُعد أو القياس المطلوب لاقتصاص الفيديو:",
            chat_id=chat_id, message_id=msg_id, reply_markup=get_crop_markup(unique_id)
        )
        
    elif action == "edit_trim":
        status_msg = bot.send_message(
            chat_id,
            "✂️ <b>قص وتقطيع مقطع الفيديو</b>\n\n"
            "يرجى إرسال وقت البداية والنهاية للقص بالصيغة التالية: <code>بداية - نهاية</code> بالثواني أو الدقائق.\n\n"
            "💡 <i>أمثلة:</i>\n"
            "▪️ <code>10 - 30</code> (لقص الفيديو من الثانية 10 إلى الثانية 30)\n"
            "▪️ <code>01:15 - 02:30</code> (لقص الفيديو من الدقيقة 1:15 إلى الدقيقة 2:30)"
        )
        user_states[chat_id] = {
            "state": "waiting_trim_range",
            "unique_id": unique_id,
            "status_msg_id": status_msg.message_id
        }
        
    elif action == "edit_thumb_menu":
        status_msg = bot.send_message(
            chat_id,
            "🖼️ <b>التقاط صورة/بوستر مصغر من الفيديو</b>\n\n"
            "يرجى إرسال الثانية أو التوقيت المطلوب التقاط الصورة عنده (بالثواني أو بصيغة دقيقة:ثانية).\n\n"
            "💡 <i>أمثلة:</i>\n"
            "▪️ <code>5</code> (التقاط صورة عند الثانية 5)\n"
            "▪️ <code>01:20</code> (التقاط صورة عند الدقيقة الأولى و20 ثانية)"
        )
        user_states[chat_id] = {
            "state": "waiting_screenshot_time",
            "unique_id": unique_id,
            "status_msg_id": status_msg.message_id
        }
        
    elif action == "edit_wmark_menu":
        status_msg = bot.send_message(
            chat_id,
            "🏷️ <b>دمج نص مائي على الفيديو للحفظ</b>\n\n"
            "يرجى إرسال النص الذي ترغب بكتابته ودمجه في زاوية الفيديو لحفظ الحقوق:\n\n"
            "💡 <i>أمثلة:</i>\n"
            "▪️ <code>@mychannel</code>\n"
            "▪️ <code>الملك الشامل للتحميل</code>"
        )
        user_states[chat_id] = {
            "state": "waiting_watermark_text",
            "unique_id": unique_id,
            "status_msg_id": status_msg.message_id
        }
        
    elif action == "edit_audio_replace":
        status_msg = bot.send_message(
            chat_id,
            "🎵 <b>استبدال صوت الفيديو بالكامل</b>\n\n"
            "يرجى إرسال أو توجيه (Forward) الملف الصوتي (MP3/M4A) أو التسجيل الصوتي الذي تريد استخدامه كصوت بديل للمقطع:"
        )
        user_states[chat_id] = {
            "state": "waiting_replace_audio",
            "unique_id": unique_id,
            "status_msg_id": status_msg.message_id
        }
        
    elif action == "edit_audio_mix_menu":
        status_msg = bot.send_message(
            chat_id,
            "🎚️ <b>دمج صوتين مع تعديل المستويات</b>\n\n"
            "يرجى إرسال أو توجيه (Forward) الملف الصوتي (MP3/M4A) أو التسجيل الصوتي الذي تريد دمجه مع صوت الفيديو الأصلي:"
        )
        user_states[chat_id] = {
            "state": "waiting_mix_audio",
            "unique_id": unique_id,
            "status_msg_id": status_msg.message_id
        }
        
    elif action == "edit_mixrun":
        audio_unique_id = parts[2]
        v0_pct = float(parts[3])
        v1_pct = float(parts[4])
        
        # Convert percentages to decimal factors (e.g., 80% -> 0.8)
        v0_dec = v0_pct / 100.0
        v1_dec = v1_pct / 100.0
        
        audio_info = cached_files.get(audio_unique_id)
        if not audio_info:
            bot.send_message(chat_id, "❌ عذراً، انتهت صلاحية الملف الصوتي المرفق (الحد الأقصى 3 دقائق).")
            return
            
        audio_path = audio_info["file_path"]
        output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_mixed_audio.mp4")
        
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", input_path,
            "-i", audio_path,
            "-filter_complex", f"[0:a]volume={v0_dec}[a0];[1:a]volume={v1_dec}[a1];[a0][a1]amix=inputs=2:duration=first[a]",
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            output_path
        ]
        
        status_msg = bot.send_message(chat_id, "⏳ <b>جاري دمج وموازنة مسارات الصوت المحددة...</b>")
        threading.Thread(
            target=run_ffmpeg_edit,
            args=(chat_id, input_path, output_path, cmd, status_msg.message_id, "🎚️ تم دمج وموازنة الصوت بنجاح بالنسَب التي اخترتها! ⚡")
        ).start()
        
    else:
        # FFMPEG commands execution mapping
        output_path = None
        cmd = []
        success_caption = ""
        format_type = "video"
        
        status_msg = bot.send_message(chat_id, "⏳ <b>جاري تحضير وتجهيز معالجة الفيديو...</b>")
        
        if action == "edit_mute":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_muted.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-an", "-c:v", "copy", output_path]
            success_caption = "🔇 تم كتم صوت الفيديو بنجاح! ⚡"
            
        elif action == "edit_rotr":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_rotated_r.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-vf", "transpose=1", "-c:v", "libx264", "-c:a", "aac", "-strict", "experimental", output_path]
            success_caption = "↪️ تم تدوير الفيديو لليمين 90 درجة بنجاح! ⚡"
            
        elif action == "edit_rotl":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_rotated_l.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-vf", "transpose=2", "-c:v", "libx264", "-c:a", "aac", "-strict", "experimental", output_path]
            success_caption = "↩️ تم تدوير الفيديو لليسار 90 درجة بنجاح! ⚡"
            
        elif action == "edit_speed_fast":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_fast.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-filter_complex", "[0:v]setpts=0.5*PTS[v];[0:a]atempo=2.0[a]", "-map", "[v]", "-map", "[a]", output_path]
            success_caption = "⚡ تم تسريع الفيديو بمعدل 2x بنجاح! 🚀"
            
        elif action == "edit_speed_slow":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_slow.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-filter_complex", "[0:v]setpts=2.0*PTS[v];[0:a]atempo=0.5[a]", "-map", "[v]", "-map", "[a]", output_path]
            success_caption = "🐢 تم تبطئة الفيديو بمعدل 0.5x بنجاح! 🐢"
            
        elif action == "edit_rev":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_reversed.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-vf", "reverse", "-af", "areverse", output_path]
            success_caption = "🔄 تم عكس تشغيل الفيديو بنجاح! ⚡"
            
        elif action == "edit_gif":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_gif.gif")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-vf", "scale=320:-1", "-r", "10", "-f", "gif", output_path]
            success_caption = "🎞️ تم تحويل الفيديو إلى صورة متحركة GIF بنجاح! ⚡"
            format_type = "gif"
            
        elif action == "edit_audio":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_audio.mp3")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-vn", "-acodec", "libmp3lame", "-aq", "2", output_path]
            success_caption = "🎵 تم استخراج الصوت MP3 بنجاح! 🎧"
            format_type = "audio"
            
        elif action == "edit_res_low":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_low_480p.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-vf", "scale=-2:480", "-vcodec", "libx264", "-crf", "28", "-acodec", "aac", output_path]
            success_caption = "📉 تم ضغط وتقليل دقة الفيديو لـ 480p بنجاح! ⚡"
            
        elif action == "edit_res_med":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_med_720p.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-vf", "scale=-2:720", "-vcodec", "libx264", "-crf", "23", "-acodec", "aac", output_path]
            success_caption = "🎬 تم تحويل وتعديل دقة الفيديو لـ 720p بنجاح! ⚡"
            
        elif action == "edit_vnote":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_vnote.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-vf", "crop=w='min(in_w\\,in_h)':h='min(in_w\\,in_h)',scale=240:240", "-c:v", "libx264", "-c:a", "aac", "-strict", "experimental", output_path]
            success_caption = "🔘 تم تحويل الفيديو إلى نوت دائرية بنجاح! ⚡"
            format_type = "vnote"
            
        elif action == "edit_crop_916":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_crop_916.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-vf", "crop=w='min(in_w\\,in_h*9/16)':h='min(in_h\\,in_w*16/9)'", "-c:v", "libx264", "-c:a", "copy", output_path]
            success_caption = "📐 تم قص وتغيير قياس الفيديو للعمودي 9:16 بنجاح! ⚡"
            
        elif action == "edit_crop_169":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_crop_169.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-vf", "crop=w='min(in_w\\,in_h*16/9)':h='min(in_h\\,in_w*9/16)'", "-c:v", "libx264", "-c:a", "copy", output_path]
            success_caption = "📐 تم قص وتغيير قياس الفيديو للأفقي 16:9 بنجاح! ⚡"
            
        elif action == "edit_crop_11":
            output_path = os.path.join(DOWNLOAD_DIR, f"{unique_id}_crop_11.mp4")
            cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-vf", "crop=w='min(in_w\\,in_h)':h='min(in_w\\,in_h)'", "-c:v", "libx264", "-c:a", "copy", output_path]
            success_caption = "📐 تم قص وتغيير قياس الفيديو للمربع 1:1 بنجاح! ⚡"
            
        elif action == "edit_res_ai":
            # Start AI Super Resolution Prediction in background thread
            threading.Thread(target=run_ai_upscale, args=(chat_id, input_path, unique_id, status_msg.message_id)).start()
            return
            
        if cmd and output_path:
            threading.Thread(
                target=run_ffmpeg_edit,
                args=(chat_id, input_path, output_path, cmd, status_msg.message_id, success_caption, format_type)
            ).start()

@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_mp3|"))
def handle_convert_to_mp3(call):
    url = call.data.split("|", 1)[1]
    bot.answer_callback_query(call.id, "🎵 جاري استخراج الملف الصوتي MP3...")
    status_msg = bot.send_message(
        call.message.chat.id,
        "⏳ <b>جاري استخراج الصوت بصيغة MP3 فائقة النقاء...</b> 🎧"
    )
    threading.Thread(
        target=process_and_send_download,
        args=(call.message, status_msg, url, 'mp3')
    ).start()

def process_and_send_download(message, status_msg, url, format_type='video'):
    chat_id = message.chat.id if hasattr(message, 'chat') else message.from_user.id
    unique_id = uuid.uuid4().hex[:8]
    output_template = os.path.join(DOWNLOAD_DIR, f"{unique_id}_%(title).50s.%(ext)s")

    downloaded_files = []
    detected_type = 'video'
    success = False
    error_msg = "تعذر سحب الوسائط من الرابط."

    # Loop for up to 5 retries if the download fails
    for attempt in range(1, 6):
        downloaded_files = []
        detected_type = 'video'
        
        if attempt > 1:
            try:
                bot.edit_message_text(
                    f"⏳ <b>المحاولة ({attempt}/5) لفك تشفير وسحب الرابط...</b>\n<i>يرجى الانتظار ثوانٍ معدودة ⚡</i>",
                    chat_id=chat_id,
                    message_id=status_msg.message_id
                )
            except Exception:
                pass
                
        try:
            # 1. إذا كان تيك توك والمطلوب فيديو أو صور، نسحب عبر محرك TikWM للحصول على فيديو HD بدون حقوق نهائياً
            if format_type != 'mp3' and ('tiktok.com' in url.lower() or 'douyin.com' in url.lower()):
                files, m_type = extract_tiktok_clean(url, unique_id)
                if files:
                    downloaded_files = files
                    detected_type = m_type

            # 2. إذا لم يتم التحميل بعد، أو كان إنستغرام صورة / منشور، جرب الساحب المتخصص
            if not downloaded_files and format_type != 'mp3' and ('instagram.com/p/' in url.lower() or 'instagram.com/reel/' in url.lower()):
                files, m_type = extract_instagram_clean(url, unique_id)
                if files:
                    downloaded_files = files
                    detected_type = m_type

            # 3. محرك yt-dlp المتكامل للفيديوهات والصوتيات واليوتيوب وباقي المنصات
            if not downloaded_files:
                ydl_opts = {
                    'outtmpl': output_template,
                    'ffmpeg_location': FFMPEG_PATH,
                    'quiet': True,
                    'no_warnings': True,
                    'ignoreerrors': True,
                    'nocheckcertificate': True,
                    'geo_bypass': True,
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['android', 'ios', 'mweb']
                        }
                    },
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    }
                }
                if 'instagram.com' in url or 'cdninstagram.com' in url:
                    ydl_opts['http_headers']['Referer'] = 'https://www.instagram.com/'

                if format_type == 'mp3':
                    ydl_opts['format'] = 'bestaudio/best'
                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]
                else:
                    ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
                    ydl_opts['merge_output_format'] = 'mp4'

                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        if info:
                            if 'entries' in info and info['entries']:
                                for entry in info['entries']:
                                    if entry:
                                        fname = ydl.prepare_filename(entry)
                                        if format_type == 'mp3':
                                            fname = os.path.splitext(fname)[0] + '.mp3'
                                        if os.path.exists(fname):
                                            downloaded_files.append(fname)
                            else:
                                fname = ydl.prepare_filename(info)
                                if format_type == 'mp3':
                                    fname = os.path.splitext(fname)[0] + '.mp3'
                                if os.path.exists(fname):
                                    downloaded_files.append(fname)
                except Exception as yt_err:
                    print(f"[WARNING] yt-dlp downloader mobile client failed: {yt_err}")

                if not downloaded_files:
                    for fname in os.listdir(DOWNLOAD_DIR):
                        if fname.startswith(unique_id):
                            downloaded_files.append(os.path.join(DOWNLOAD_DIR, fname))

                # 4. إذا كان يوتيوب وفشل التحميل السحابي المباشر، جرب محرك Cobalt API المساعد
                if not downloaded_files and ('youtube.com' in url or 'youtu.be' in url):
                    try:
                        cobalt_url = "https://api.cobalt.tools/api/json"
                        payload = {'url': url, 'downloadMode': 'audio' if format_type == 'mp3' else 'auto'}
                        r = requests.post(cobalt_url, json=payload, headers={'Accept': 'application/json'}, timeout=15)
                        if r.status_code == 200 and r.json().get('url'):
                            media_data = requests.get(r.json()['url'], timeout=30).content
                            ext = ".mp3" if format_type == 'mp3' else ".mp4"
                            fname = os.path.join(DOWNLOAD_DIR, f"{unique_id}_cobalt{ext}")
                            with open(fname, 'wb') as f:
                                f.write(media_data)
                            downloaded_files.append(fname)
                    except Exception as cob_err:
                        print(f"[ERROR] Cobalt fallback failed: {cob_err}")

                # 5. إذا فشل yt-dlp في إنستغرام وبقي المحتوى فارغاً، جرب مرة أخرى بساحب الصور
                if not downloaded_files and 'instagram.com' in url.lower():
                    files, m_type = extract_instagram_clean(url, unique_id)
                    if files:
                        downloaded_files = files
                        detected_type = m_type

            if not downloaded_files:
                raise Exception("لم يتم العثور على ملفات وسائط متاحة للتحميل من هذا الرابط.")
                
            success = True
            break
            
        except Exception as attempt_err:
            error_msg = str(attempt_err)
            time.sleep(2)

    try:
        if not success:
            raise Exception(error_msg)

        bot.edit_message_text(
            "📤 <b>اكتمل التنزيل! جاري الإرسال مباشرة الآن...</b> ⚡",
            chat_id=chat_id,
            message_id=status_msg.message_id
        )

        # ==========================================
        # الإرسال الصافي (فقط الفيديو أو الألبوم بدون شريط عنوان أو نصوص)
        # ==========================================
        if len(downloaded_files) > 1 and format_type != 'mp3':
            media_group = []
            files_to_close = []
            for filepath in downloaded_files[:10]:
                f = open(filepath, 'rb')
                files_to_close.append(f)
                if filepath.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) or detected_type == 'photo':
                    media_group.append(types.InputMediaPhoto(f))
                else:
                    media_group.append(types.InputMediaVideo(f, supports_streaming=True))
            
            if media_group:
                bot.send_media_group(chat_id, media_group, reply_to_message_id=None)
            
            for f in files_to_close:
                f.close()
        else:
            filepath = downloaded_files[0]
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)

            with open(filepath, 'rb') as f:
                if format_type == 'mp3' or filepath.lower().endswith(('.mp3', '.m4a', '.wav')):
                    bot.send_audio(
                        chat_id,
                        f,
                        caption="",  # صوت نظيف
                        title="الملف الصوتي MP3",
                        reply_to_message_id=None
                    )
                elif filepath.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) or detected_type == 'photo':
                    bot.send_photo(
                        chat_id,
                        f,
                        caption="",  # صورة نظيفة بدون شريط
                        reply_to_message_id=None
                    )
                else:
                    # فيديو كامل ونظيف بدون حقوق وبدون أي نص أو شريط عنوان
                    markup = types.InlineKeyboardMarkup(row_width=1)
                    markup.add(
                        types.InlineKeyboardButton("🛠️ أدوات تعديل وقص هذا الفيديو", callback_data=f"edit_start|{unique_id}"),
                        types.InlineKeyboardButton("🎵 استخراج الصوت (MP3) من هذا الفيديو", callback_data=f"dl_mp3|{url}")
                    )
                    
                    if file_size_mb <= 49.5:
                        bot.send_video(
                            chat_id,
                            f,
                            caption="",  # بدون نصوص أو أشرطة مزعجة
                            supports_streaming=True,
                            reply_to_message_id=None,
                            reply_markup=markup
                        )
                    else:
                        bot.send_document(
                            chat_id,
                            f,
                            caption="",
                            reply_to_message_id=None,
                            reply_markup=markup
                        )

        # Cache the downloaded file for 2 minutes to allow editing!
        if downloaded_files and format_type != 'mp3' and not downloaded_files[0].lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            cached_files[unique_id] = {"file_path": downloaded_files[0], "chat_id": chat_id}
            schedule_file_cleanup(unique_id, 120)

        # حذف رسالة الانتظار ليحصل المستخدم على الفيديو فقط بأبسط وأجمل شكل
        try:
            bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass

        # حذف رسالة الرابط الأصلية التي أرسلها المستخدم تلقائياً بعد نجاح التحميل والإرسال
        if message and hasattr(message, 'message_id') and message.from_user and message.from_user.id != bot.get_me().id:
            try:
                bot.delete_message(chat_id, message.message_id)
            except Exception:
                pass

    except Exception as e:
        error_msg = str(e)
        bot.edit_message_text(
            f"❌ <b>عذراً، تعذر سحب الوسائط من الرابط بعد 5 محاولات متتالية:</b>\n<i>{error_msg.split(';')[-1][:120]}</i>",
            chat_id=chat_id,
            message_id=status_msg.message_id
        )
        # حذف رسالة الرابط الأصلية التي أرسلها المستخدم تلقائياً حتى عند الفشل بعد 5 محاولات
        if message and hasattr(message, 'message_id') and message.from_user and message.from_user.id != bot.get_me().id:
            try:
                bot.delete_message(chat_id, message.message_id)
            except Exception:
                pass

        # حذف رسالة التنبيه بالخطأ الصادرة عن البوت تلقائياً بعد مرور 1 دقيقة
        def delete_error_after_delay(c_id, m_id):
            time.sleep(60)
            try:
                bot.delete_message(c_id, m_id)
            except Exception:
                pass
                
        threading.Thread(target=delete_error_after_delay, args=(chat_id, status_msg.message_id)).start()

    finally:
        # If the download failed, clean up immediately.
        # If it succeeded, schedule_file_cleanup will remove them after 2 minutes.
        if not success:
            try:
                for fname in os.listdir(DOWNLOAD_DIR):
                    if fname.startswith(unique_id):
                        os.remove(os.path.join(DOWNLOAD_DIR, fname))
            except Exception:
                pass

# ==========================================
# تشغيل خادم الويب (للحفاظ على البوت مستيقظاً 24/7 على Render) وتشغيل البوت
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "<b>🤖 Universal Downloader Bot is Running Alive 24/7! (Status: Online 🟢)</b>", 200

def run_bot_polling():
    while True:
        try:
            print("[INFO] Universal Downloader Bot is polling Telegram...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"[ERROR] Bot polling restart due to: {e}")
            time.sleep(5)

def check_and_update_ytdl():
    try:
        import subprocess
        import sys
        print("[INFO] Checking and updating yt-dlp...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"])
        print("[INFO] yt-dlp updated successfully.")
    except Exception as e:
        print(f"[WARNING] Failed to update yt-dlp: {e}")

# تشغيل البوت في مسار منفصل (Background Thread) ليعمل سواء عبر python مباشرة أو عبر gunicorn في السحابة
polling_thread = threading.Thread(target=run_bot_polling, daemon=True)
polling_thread.start()

if __name__ == "__main__":
    print("[INFO] Universal Downloader Bot is starting... Connected to Telegram successfully.")
    # تحديث yt-dlp تلقائياً
    check_and_update_ytdl()
    # تشغيل خادم الويب على المنفذ المطلوب في Render (أو 8080 محلياً)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

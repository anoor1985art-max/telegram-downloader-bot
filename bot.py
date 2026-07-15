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
BOT_TOKEN = "8660209792:AAEJpMoNB7W_oBefqDj32EggEzG4NHsiay0"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

# ==========================================
# الترحيب والقوائم التفاعلية
# ==========================================
@bot.message_handler(commands=['start', 'help'])
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

            if not downloaded_files:
                for fname in os.listdir(DOWNLOAD_DIR):
                    if fname.startswith(unique_id):
                        downloaded_files.append(os.path.join(DOWNLOAD_DIR, fname))

            # إذا فشل yt-dlp في إنستغرام وبقي المحتوى فارغاً، جرب مرة أخرى بساحب الصور
            if not downloaded_files and 'instagram.com' in url.lower():
                files, m_type = extract_instagram_clean(url, unique_id)
                if files:
                    downloaded_files = files
                    detected_type = m_type

        if not downloaded_files:
            raise Exception("لم يتم العثور على ملفات وسائط متاحة للتحميل من هذا الرابط.")

        bot.edit_message_text(
            "📤 <b>اكتمل التنزيل! جاري الإرسال مباشرة الآن...</b> ⚡",
            chat_id=chat_id,
            message_id=status_msg.message_id
        )

        # ==========================================
        # الإرسال الصافي (فقط الفيديو أو الألبوم بدون شريط عنوان أو نصوص)
        # ==========================================
        # ملاحظة هامة: تم تعيين reply_to_message_id=None لكي لا يظهر شريط العنوان أو الرابط فوق الفيديو
        # وتم ترك caption="" لكي يظهر الفيديو كاملاً ونظيفاً تماماً كما طلبت
        
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
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🎵 استخراج الصوت (MP3) من هذا الفيديو", callback_data=f"dl_mp3|{url}"))
                    
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

        # حذف رسالة الانتظار ليحصل المستخدم على الفيديو فقط بأبسط وأجمل شكل
        try:
            bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass

    except Exception as e:
        error_msg = str(e)
        bot.edit_message_text(
            f"❌ <b>عذراً، تعذر سحب الوسائط من الرابط:</b>\n<i>{error_msg.split(';')[-1][:120]}</i>",
            chat_id=chat_id,
            message_id=status_msg.message_id
        )
    finally:
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

if __name__ == "__main__":
    print("[INFO] Universal Downloader Bot is starting... Connected to Telegram successfully.")
    # تشغيل البوت في مسار منفصل (Background Thread) لكي لا يتعارض مع خادم الويب
    polling_thread = threading.Thread(target=run_bot_polling, daemon=True)
    polling_thread.start()
    
    # تشغيل خادم الويب على المنفذ المطلوب في Render (أو 8080 محلياً)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

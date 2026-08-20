import os
import re
import requests
import telebot
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TOKEN = os.getenv('CALLER_ID_BOT_TOKEN')
RAPIDAPI_KEY = os.getenv('RAPIDAPI_KEY')

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "مرحباً بك في بوت كاشف الأرقام! 🕵️‍♂️\n\n"
        "أرسل لي أي رقم هاتف (مع رمز الدولة) وسأقوم بالبحث عنه لجلب:\n"
        "- اسم صاحب الرقم\n"
        "- صورته الشخصية\n"
        "- حسابات السوشيال ميديا الخاصة به\n\n"
        "مثال: +9647701234567"
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text
    phone = re.sub(r'[^\d+]', '', text)
    
    if not phone or len(phone) < 8:
        bot.reply_to(message, "يرجى إرسال رقم هاتف صحيح مع رمز الدولة.")
        return

    clean_phone = phone.replace('+', '')
    bot.reply_to(message, "جاري البحث في قواعد البيانات... ⏳")

    url = "https://caller-id-social-search-eyecon.p.rapidapi.com/search"
    querystring = {"phone": clean_phone}
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "caller-id-social-search-eyecon.p.rapidapi.com"
    }

    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            name = data.get('name', 'غير متوفر')
            photo = data.get('image', None)
            
            socials = []
            if 'socials' in data and data['socials']:
                for social in data['socials']:
                    if isinstance(social, dict) and 'name' in social and 'url' in social:
                        socials.append(f"• {social['name']}: {social['url']}")
            
            social_text = "\n".join(socials) if socials else "غير متوفر"

            result_msg = (
                f"👤 **الاسم:** {name}\n"
                f"📞 **الرقم:** {phone}\n\n"
                f"🌐 **حسابات التواصل:**\n{social_text}"
            )

            if photo and photo != "null":
                bot.send_photo(message.chat.id, photo, caption=result_msg, parse_mode='Markdown')
            else:
                bot.send_message(message.chat.id, result_msg, parse_mode='Markdown')
                
        elif response.status_code == 403:
            bot.reply_to(message, "❌ خطأ 403: يرجى التأكد من أنك اشتركت في باقة Eyecon على RapidAPI.")
        elif response.status_code == 404:
            bot.reply_to(message, "❌ لم يتم العثور على أي بيانات لهذا الرقم.")
        else:
            bot.reply_to(message, f"❌ حدث خطأ غير متوقع. كود الخطأ: {response.status_code}")
            
    except Exception as e:
        bot.reply_to(message, f"❌ تعذر الاتصال بالخادم. حاول مجدداً لاحقاً.\nالسبب: {str(e)[:50]}")

if __name__ == '__main__':
    print("[INFO] Caller ID Bot is running...")
    bot.infinity_polling()

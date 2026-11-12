import os
import logging
import time
import random
import io
import numpy as np
import cv2
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import asyncio

# إعدادات البوت
TOKEN = os.environ.get('BOT_TOKEN', '8545282222:AAHq1O-Ue4JnIad7R_JBP9AXIThzVzUcAq4')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class FaceSwapBot:
    def __init__(self):
        self.application = ApplicationBuilder().token(TOKEN).build()
        
        # إضافة المعالجات
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, self.handle_media))
        self.application.add_handler(CallbackQueryHandler(self.ad_callback))
        
        # تحميل النموذج مرة واحدة عند بدء تشغيل البوت
        self.app = None
        self.detector = None
        self.loader = None
        self.extractor = None
        logger.info("جاري تحميل نموذج الذكاء الاصطناعي...")
        self.load_model()

    def load_model(self):
        from insightface.app import FaceAnalysis
        self.app = FaceAnalysis(name='buffalo_l', root='./insightface_models', providers=['CPUExecutionProvider'])
        self.app.prepare(ctx_id=-1, det_size=(640, 640))
        logger.info("تم تحميل النموذج بنجاح!")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "مرحباً! أنا بوت تغيير الوجوه بالذكاء الاصطناعي.\n\n"
            "📸 أرسل لي صورتين:\n"
            "1️⃣ صورة الشخص الذي تريد نقل وجهه إليه.\n"
            "2️⃣ الصورة التي تريد وضع الوجه فيها.\n\n"
            "💡 كل معالجة تتطلب مشاهدة إعلان قصير."
        )

    async def handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        file = None
        
        if update.message.photo:
            file = update.message.photo[-1].file_id
            caption = "تم استلام الصورة! أرسل الصورة الثانية الآن..."
        elif update.message.video:
            file = update.message.video.file_id
            caption = "تم استلام الفيديو! (ملاحظة: الفيديو قد يستغرق وقتاً أطول)"
        else:
            return

        # إنشاء أزرار الإعلانات
        keyboard = [
            [InlineKeyboardButton("👁️ مشاهدة الإعلان للمعالجة", callback_data="watch_ad")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # حفظ معرف الملف للمستخدم
        context.user_data['pending_file'] = file
        context.user_data['user_id'] = user.id
        context.user_data['is_video'] = update.message.video is not None
        context.user_data['step'] = 'waiting_for_second_image'

        await update.message.reply_text(caption, reply_markup=reply_markup)

    async def ad_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == "watch_ad":
            await query.edit_message_text("⏳ جاري تحميل الإعلان... يرجى الانتظار.")
            
            # محاكاة مشاهدة إعلان (5 ثواني)
            await asyncio.sleep(5)
            
            await query.edit_message_text("✅ شكراً لمشاهدة الإعلان! جاري المعالجة الآن...")
            
            # استدعاء دالة المعالجة
            await self.process_and_send(update, context)

    async def process_and_send(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            file_id = context.user_data.get('pending_file')
            if not file_id:
                await update.effective_message.reply_text("حدث خطأ في البيانات.")
                return

            # جلب الملف
            file = await context.bot.get_file(file_id)
            downloaded_file = await file.download_to_memory()
            
            # تحويل البيانات إلى صورة قابلة للمعالجة
            img_array = np.asarray(bytearray(downloaded_file.read()), dtype=np.uint8)
            image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            
            # --- منطق Face Swap الحقيقي ---
            faces = self.app.get(image)
            
            if len(faces) > 0:
                # نأخذ أول وجه تم اكتشافه ونستخدمه
                source_face = faces[0]
                
                # نقوم بإعادة إرسال الصورة مع الوجه المستخرج كدليل للمستخدم
                # يمكنك هنا استخدام خوارزمية swap كاملة أو تركها للمستخدم لاختيار الوجه
                
                # مثال بسيط: استخراج الوجه وإرساله كمثال
                face_img = self.extract_face(image, source_face.bbox)
                
                _, buffer = cv2.imencode('.jpg', face_img)
                io_buffer = io.BytesIO(buffer.tobytes())
                
                await update.effective_message.reply_photo(photo=io_buffer, caption="✅ تم استخراج الوجه بنجاح! \n\nأرسل الصورة الأخرى الآن لاستبدال الوجه فيها.")
                
                # تحديث الحالة للانتظار للصورة الثانية
                context.user_data['source_face'] = source_face
                context.user_data['step'] = 'waiting_for_target_image'
            else:
                await update.effective_message.reply_text("❌ لم يتم العثور على أي وجوه في الصورة. حاول بإضاءة أفضل.")

        except Exception as e:
            logger.error(f"Error processing media: {e}")
            await update.effective_message.reply_text("❌ حدث خطأ أثناء المعالجة.")

    def extract_face(self, image, bbox):
        x1, y1, x2, y2 = map(int, bbox[:4])
        face = image[y1:y2, x1:x2]
        return cv2.resize(face, (100, 100))

if __name__ == '__main__':
    bot = FaceSwapBot()
    bot.application.run_polling()

# myface — بوت تعديل الصور والفيديو

بوت تيليجرام خاص يعمل على Render عبر Webhook، ويستخدم OpenCV فقط:
بلا PyTorch ولا InsightFace ولا نماذج ضخمة، لذلك يبدأ بسرعة ويناسب الخطة المجانية.

## المزايا

- 🎭 `/faceswap`: تبديل وجه بصورة مرجعية (كشف وجوه + دمج سلس).
- 🩹 `/inpaint`: تعديل منطقة عبر ماسك أبيض/أسود.
- 🎨 تأثيرات الصور: `/cartoon` `/blur` `/gray` `/sketch` `/edges`.
- 🎬 تأثيرات الفيديو: أرسل فيديو (حتى 20 ثانية) ثم نفس الأوامر.
- 🛠 `/developer` (أو `/status`): رسالة تشخيص كاملة للمطور.
- 🔒 البوت خاص بـ `ALLOWED_USER_ID` فقط، والwebhook محمي بـ`WEBHOOK_SECRET`.

## الفحص قبل النشر

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python selftest.py
```

يطبع ✅ لكل مكوّن: الصور، التأثيرات، inpaint، تبديل الوجه، الفيديو، ورسالة المطور.

## متغيرات البيئة على Render

| المتغير | إلزامي | الوصف |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | نعم | توكن البوت من BotFather |
| `ALLOWED_USER_ID` | نعم | معرف تيليجرام الوحيد المسموح |
| `WEBHOOK_SECRET` | مستحسن | يُولَّد تلقائيًا من `render.yaml` |
| `AD_DURATION` | لا | مدة المحاكاة بالثواني (افتراضي 3) |
| `MAX_VIDEO_SECONDS` | لا | أقصى مدة فيديو (افتراضي 20) |
| `MAX_VIDEO_WIDTH` | لا | أقصى عرض للمعالجة (افتراضي 640) |
| `MAX_IMAGE_SIDE` | لا | أقصى بُعد للصورة قبل المعالجة (افتراضي 2400) |
| `MAX_UPLOAD_MB` | لا | أقصى حجم ملف (افتراضي 20) |

`RENDER_EXTERNAL_URL` يوفّره Render تلقائيًا ويُستخدم لتسجيل الwebhook. عند غيابه يعمل البوت بوضع Polling تلقائيًا بدل التوقف.

## النشر

1. ارفع المشروع إلى GitHub.
2. أنشئ Blueprint على Render من `render.yaml` أو اربط الخدمة بالمستودع.
3. أضف `TELEGRAM_BOT_TOKEN` في Environment.
4. تحقق من `https://<service>.onrender.com/healthcheck`.

## ملاحظات

- التوكن القديم كان مكتوبًا داخل `app.py`؛ يجب إلغاؤه من BotFather (`/revoke`) وإنشاء توكن جديد ووضعه في متغيرات البيئة.
- لا حاجة لموديل `inswapper_128.onnx` بعد الآن، ولا لموديلات InsightFace.
- الفيديو الطويل يُقصّ إلى `MAX_VIDEO_SECONDS` تلقائيًا للحفاظ على الذاكرة.

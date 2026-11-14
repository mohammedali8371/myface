# 📩 رسالة إلى المطور — myface

## نص جاهز للإرسال

> **myface جاهز للتشغيل الكامل ✅**
>
> - الإصدار: **2026.11.14.1**
> - المحرك: OpenCV + NumPy فقط (بلا PyTorch / InsightFace / نماذج ضخمة) — يناسب Render المجاني ويبدأ بسرعة.
> - يعمل على الصور والفيديو: `/faceswap` `/inpaint` `/cartoon` `/blur` `/gray` `/sketch` `/edges`.
> - البوت خاص بـ `ALLOWED_USER_ID` فقط، والـWebhook محمي بـ`WEBHOOK_SECRET`.
> - يوجد أمر `/developer` داخل البوت يعرض رسالة تشخيص كاملة (الإصدار، مدة التشغيل، الحدود، حالة Webhook، المكتبات).
> - الفحص الذاتي: `python selftest.py` — يختبر الصور والفيديو والتأثيرات والدمج ويطبع ✅ لكل خطوة.
>
> **المطلوب منك الآن (خطوتان فقط):**
> 1. ألغِ التوكن القديم من BotFather عبر `/revoke` (كان مكشوفًا داخل الكود سابقًا)، ثم أنشئ توكنًا جديدًا.
> 2. أضف `TELEGRAM_BOT_TOKEN` في Render → Environment، واضغط Manual Deploy لآخر commit.
>
> ثم افتح: `https://<service>.onrender.com/healthcheck` — يجب أن يظهر `"ok": true` و`"version": "2026.11.14.1"`.

---

## حالة التشغيل

| العنصر | الحالة |
|---|---|
| صور: ترميز/فك ترميز | ✅ |
| تأثيرات الصور الخمسة | ✅ |
| تعديل منطقة (inpaint) | ✅ |
| تبديل الوجه (كشف + دمج) | ✅ |
| فيديو (قراءة/تأثير/ترميز MP4) | ✅ |
| رسالة المطور `/developer` | ✅ |
| Webhook + Healthcheck | ✅ (عند توفر `RENDER_EXTERNAL_URL`) |
| Polling محلي عند غياب عنوان عام | ✅ |
| نشر Render | ⏳ ينتظر التوكن وManual Deploy |

### نتائج الفحص الذاتي

```
✅ صور: ترميز/فك ترميز
✅ تأثير: cartoon / blur / gray / sketch / edges
✅ تعديل منطقة (inpaint)
✅ تبديل الوجه (منطق الدمج)
✅ فيديو: 10 إطارات
✅ رسالة المطور
🎉 myface 2026.11.14.1 — كل الفحوص نجحت
```

---

## متغيرات البيئة

| المتغير | إلزامي | القيمة |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | نعم | توكن جديد من BotFather |
| `ALLOWED_USER_ID` | نعم | `7958260008` (مضبوط في `render.yaml`) |
| `WEBHOOK_SECRET` | مستحسن | يُولَّد تلقائيًا |
| `AD_DURATION` | لا | `3` |
| `MAX_VIDEO_SECONDS` | لا | `20` |
| `MAX_VIDEO_WIDTH` | لا | `640` |
| `MAX_IMAGE_SIDE` | لا | `2400` |
| `MAX_UPLOAD_MB` | لا | `20` |
| `LOG_LEVEL` | لا | `INFO` |

> `RENDER_EXTERNAL_URL` يوفّره Render تلقائيًا، ويُستخدم لتسجيل الWebhook. عند غيابه يعمل البوت بوضع Polling بدل التوقف.

---

## نقاط النشر

1. ارفع المستودع إلى GitHub (الفرع `main`).
2. Render → New → Blueprint → اختر `render.yaml`.
3. أضف `TELEGRAM_BOT_TOKEN` في Environment.
4. Manual Deploy، ثم تحقق من:
   - `/healthcheck` → `{"ok":true,"service":"myface","version":"2026.11.14.1",...}`
   - `/` → `myface bot is running`
5. أرسل للبوت `/start` ثم `/developer` للتأكد من التفعيل.

## تحذير أمني

التوكن القديم `8545282222:...` كان مكتوبًا داخل `app.py` ويجب إلغاؤه من BotFather فورًا، ثم استخدام توكن جديد يُخزَّن فقط في متغيرات البيئة. لا ترفع أي توكن إلى Git.

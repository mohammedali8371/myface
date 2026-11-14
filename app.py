# ============================================================
# app.py — بوت تيليجرام (Webhook) لتبديل الوجوه وتعديل الصور والفيديو
# يعمل على Render بالخطة المجانية: OpenCV فقط، بلا نماذج ضخمة.
# ============================================================
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import math
import os
import tempfile
import time
from contextlib import asynccontextmanager

import cv2
import numpy as np

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

# ============================================================
# 1) الإعدادات — من متغيرات البيئة على Render فقط
# ============================================================
TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN", "") or "").strip()
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "7958260008") or 0)
PORT = int(os.getenv("PORT", "10000"))
RENDER_EXTERNAL_URL = (os.getenv("RENDER_EXTERNAL_URL", "") or "").rstrip("/")
PUBLIC_URL = RENDER_EXTERNAL_URL or (os.getenv("PUBLIC_URL", "") or "").rstrip("/")
WEBHOOK_SECRET = (os.getenv("WEBHOOK_SECRET", "") or "").strip()
if not WEBHOOK_SECRET and TOKEN:
    WEBHOOK_SECRET = hashlib.sha256(f"g1p-webhook:{TOKEN}".encode()).hexdigest()[:48]
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{PUBLIC_URL}{WEBHOOK_PATH}" if PUBLIC_URL else ""

AD_DURATION = int(os.getenv("AD_DURATION", "3") or 3)
MAX_VIDEO_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "20") or 20)
MAX_VIDEO_WIDTH = int(os.getenv("MAX_VIDEO_WIDTH", "640") or 640)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20") or 20)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
STARTED_AT = time.time()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
)
logger = logging.getLogger("myface")

HELP_TEXT = (
    "👋 أرسل صورة أو فيديو (الهدف) أولًا.\n\n"
    "🖼 الصور:\n"
    "• /faceswap — تبديل الوجه بصورة مرجعية.\n"
    "• /inpaint — تعديل منطقة عبر ماسك أبيض/أسود.\n"
    "• /cartoon /blur /gray /sketch /edges — تأثيرات فورية.\n\n"
    "🎬 الفيديو (حتى {sec} ثانية):\n"
    "• /cartoon /blur /gray /sketch /edges بعد إرسال الفيديو.\n\n"
    "• /cancel — إلغاء الحالة الحالية."
).format(sec=MAX_VIDEO_SECONDS)

EFFECTS = {
    "cartoon": "🎨 كرتون",
    "blur": "🌫 تمويه",
    "gray": "⚫ أبيض وأسود",
    "sketch": "✏️ رسم بالقلم",
    "edges": "🧩 حدود",
}


def is_allowed(update: Update) -> bool:
    user = update.effective_user
    return (
        user is not None
        and bool(ALLOWED_USER_ID)
        and int(user.id) == ALLOWED_USER_ID
    )


async def deny(update: Update) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text("⛔ هذا البوت خاص.")


def reset_user_state(ctx: ContextTypes.DEFAULT_TYPE, keep_target: bool = True) -> None:
    for key in ("expecting_reference", "expecting_mask", "expecting_effect"):
        ctx.user_data.pop(key, None)
    ctx.user_data.pop("target_image", None)
    ctx.user_data.pop("target_bgr", None)
    if not keep_target:
        ctx.user_data.pop("ad_passed", None)
        ctx.user_data.pop("target_kind", None)


# ============================================================
# 2) محرك المعالجة (OpenCV — خفيف وسريع على المعالج)
# ============================================================
_FACE_CASCADE: cv2.CascadeClassifier | None = None


def face_cascade() -> cv2.CascadeClassifier:
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        cascade = cv2.CascadeClassifier(path)
        if cascade.empty():
            raise RuntimeError("تعذّر تحميل كاشف الوجوه المرفق مع OpenCV.")
        _FACE_CASCADE = cascade
    return _FACE_CASCADE


def detect_faces(bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    faces = face_cascade().detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
    )
    return [tuple(int(v) for v in face) for face in faces]


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def swap_faces(source_bgr: np.ndarray, target_bgr: np.ndarray) -> np.ndarray:
    """تبديل هندسي خفيف: قصّ وجه المصدر ولصقه على وجوه الهدف."""
    src_faces = detect_faces(source_bgr)
    tgt_faces = detect_faces(target_bgr)
    if not src_faces:
        raise ValueError("لم يتم كشف وجه واضح في الصورة المرجعية.")
    if not tgt_faces:
        raise ValueError("لم يتم كشف وجه واضح في الصورة الهدف.")
    src_faces.sort(key=lambda f: f[2] * f[3], reverse=True)
    tgt_faces.sort(key=lambda f: f[2] * f[3], reverse=True)
    result = target_bgr.copy()
    height, width = result.shape[:2]
    for index, (tx, ty, tw, th) in enumerate(tgt_faces):
        sx, sy, sw, sh = src_faces[index % len(src_faces)]
        # هامش بسيط حول الوجه ليشمل الجبهة والذقن.
        pad = int(max(sw, sh) * 0.12)
        sx0 = _clamp(sx - pad, 0, source_bgr.shape[1] - 1)
        sy0 = _clamp(sy - pad, 0, source_bgr.shape[0] - 1)
        sx1 = _clamp(sx + sw + pad, sx0 + 2, source_bgr.shape[1])
        sy1 = _clamp(sy + sh + pad, sy0 + 2, source_bgr.shape[0])
        patch = source_bgr[sy0:sy1, sx0:sx1]
        if patch.size == 0:
            continue
        patch = cv2.resize(patch, (tw, th), interpolation=cv2.INTER_AREA)
        mask = np.zeros((th, tw, 3), dtype=np.uint8)
        cv2.ellipse(
            mask,
            (tw // 2, th // 2),
            (max(1, tw // 2 - 2), max(1, th // 2 - 2)),
            0,
            0,
            360,
            (255, 255, 255),
            -1,
        )
        cx = _clamp(tx + tw // 2, 1, width - 2)
        cy = _clamp(ty + th // 2, 1, height - 2)
        try:
            result = cv2.seamlessClone(
                patch, result, mask, (cx, cy), cv2.NORMAL_CLONE
            )
        except cv2.error:
            # بديل آمن إن فشل seamlessClone (حدود الصورة/الحجم).
            result[ty : ty + th, tx : tx + tw] = patch
    return result


def apply_effect(bgr: np.ndarray, name: str) -> np.ndarray:
    name = (name or "").strip().lower()
    if name == "gray":
        return cv2.cvtColor(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    if name == "blur":
        return cv2.GaussianBlur(bgr, (21, 21), 0)
    if name == "edges":
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 180)
        return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    if name == "sketch":
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        inverted = cv2.bitwise_not(gray)
        blurred = cv2.GaussianBlur(inverted, (21, 21), 0)
        sketch = cv2.divide(gray, cv2.bitwise_not(blurred), scale=256.0)
        return cv2.cvtColor(sketch, cv2.COLOR_GRAY2BGR)
    if name == "cartoon":
        color = cv2.bilateralFilter(bgr, 9, 250, 250)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        edges = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY,
            9,
            9,
        )
        return cv2.bitwise_and(color, cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR))
    return bgr


def inpaint_mask(target_bgr: np.ndarray, mask_bgr: np.ndarray) -> np.ndarray:
    mask = cv2.cvtColor(mask_bgr, cv2.COLOR_BGR2GRAY)
    if mask.shape[:2] != target_bgr.shape[:2]:
        mask = cv2.resize(
            mask, (target_bgr.shape[1], target_bgr.shape[0]), interpolation=cv2.INTER_NEAREST
        )
    _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
    if int(cv2.countNonZero(mask)) == 0:
        raise ValueError("الماسك فارغ: اجعل المنطقة المطلوبة بيضاء.")
    return cv2.inpaint(target_bgr, mask, 3, cv2.INPAINT_TELEA)


def buffer_to_bgr(buf: io.BytesIO) -> np.ndarray:
    data = np.frombuffer(buf.getvalue(), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("تعذّر فك ترميز الصورة — أرسل صورة JPG/PNG صالحة.")
    return img


def bgr_to_buffer(img: np.ndarray) -> io.BytesIO:
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 94])
    if not ok:
        raise ValueError("تعذّر ترميز الصورة.")
    buf = io.BytesIO(enc.tobytes())
    buf.seek(0)
    return buf


def process_video(path_in: str, path_out: str, effect: str) -> int:
    capture = cv2.VideoCapture(path_in)
    if not capture.isOpened():
        raise ValueError("تعذّر فتح الفيديو — جرّب MP4 أو MOV.")
    fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
    fps = float(fps)
    if not math.isfinite(fps) or fps <= 0:
        fps = 24.0
    fps = max(6.0, min(60.0, fps))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if width <= 0 or height <= 0:
        capture.release()
        raise ValueError("أبعاد الفيديو غير صالحة.")
    if width > MAX_VIDEO_WIDTH:
        height = max(2, int(height * (MAX_VIDEO_WIDTH / width)) // 2 * 2)
        width = MAX_VIDEO_WIDTH
    writer = cv2.VideoWriter(
        path_out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        capture.release()
        raise ValueError("تعذّر إنشاء ملف الفيديو الناتج.")
    max_frames = int(fps * MAX_VIDEO_SECONDS)
    frames = 0
    try:
        while frames < max_frames:
            ok, frame = capture.read()
            if not ok:
                break
            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            writer.write(apply_effect(frame, effect))
            frames += 1
    finally:
        capture.release()
        writer.release()
    if frames == 0:
        raise ValueError("الفيديو فارغ أو غير قابل للقراءة.")
    return frames


# ============================================================
# 3) محاكاة الإعلان (قصيرة وقابلة للضبط)
# ============================================================
async def run_ad_simulation(message, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await message.reply_text(f"⏳ محاكاة الإعلان — {AD_DURATION} ثانية…")
    for remaining in range(AD_DURATION - 1, -1, -1):
        await asyncio.sleep(1)
        try:
            await msg.edit_text(f"⏳ محاكاة الإعلان — {remaining} ثانية…")
        except Exception:
            pass
    try:
        await msg.edit_text("✅ انتهت المحاكاة. اختر الأمر الآن.")
    except Exception:
        pass
    ctx.user_data["ad_passed"] = True


# ============================================================
# 4) الأوامر
# ============================================================
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return await deny(update)
    keyboard = [
        [
            InlineKeyboardButton("🎭 تبديل وجه", callback_data="help:faceswap"),
            InlineKeyboardButton("🩹 تعديل منطقة", callback_data="help:inpaint"),
        ],
        [
            InlineKeyboardButton("🎨 تأثيرات الصور", callback_data="help:effects"),
            InlineKeyboardButton("🎬 تأثيرات الفيديو", callback_data="help:video"),
        ],
    ]
    await update.message.reply_text(
        HELP_TEXT,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    return await cmd_start(update, ctx)


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return await deny(update)
    reset_user_state(ctx, keep_target=False)
    await update.message.reply_text("تم الإلغاء. أرسل صورة أو فيديو جديدًا.")


def _need_ready(update: Update, ctx: ContextTypes.DEFAULT_TYPE, kind: str) -> bool:
    if not ctx.user_data.get("ad_passed"):
        asyncio.create_task(update.message.reply_text("أرسل الصورة/الفيديو أولًا ثم انتظر انتهاء المحاكاة."))
        return False
    if ctx.user_data.get("target_kind") != kind:
        asyncio.create_task(update.message.reply_text(
            "هذا الأمر يحتاج صورة." if kind == "photo" else "هذا الأمر يحتاج فيديو."
        ))
        return False
    return True


async def cmd_faceswap(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return await deny(update)
    if not _need_ready(update, ctx, "photo"):
        return
    ctx.user_data["expecting_reference"] = True
    await update.message.reply_text("أرسل الآن صورة الوجه المرجعي (JPG/PNG).")


async def cmd_inpaint(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return await deny(update)
    if not _need_ready(update, ctx, "photo"):
        return
    ctx.user_data["expecting_mask"] = True
    await update.message.reply_text(
        "أرسل الماسك بنفس مقاس الصورة: الأبيض = المنطقة التي تريد تعديلها."
    )


async def _effect_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE, name: str) -> None:
    if not is_allowed(update):
        return await deny(update)
    if not ctx.user_data.get("ad_passed"):
        return await update.message.reply_text("أرسل الصورة/الفيديو أولًا.")
    kind = ctx.user_data.get("target_kind")
    if kind == "photo":
        target = ctx.user_data.get("target_bgr")
        if target is None:
            return await update.message.reply_text("أعد إرسال الصورة.")
        out = await asyncio.to_thread(apply_effect, target, name)
        await update.message.reply_photo(
            photo=bgr_to_buffer(out), caption=f"✅ {EFFECTS.get(name, name)}"
        )
        return
    if kind == "video":
        await update.message.reply_text("⏳ جارٍ معالجة الفيديو… قد يستغرق بعض الوقت.")
        try:
            out = await asyncio.to_thread(
                _video_from_state, ctx.user_data.get("target_video_path"), name
            )
            await update.message.reply_video(
                video=out, caption=f"✅ {EFFECTS.get(name, name)}"
            )
        except Exception as exc:
            await update.message.reply_text(f"❌ فشل: {exc}")
        return
    await update.message.reply_text("أرسل صورة أو فيديو أولًا.")


async def cmd_cartoon(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    return await _effect_command(update, ctx, "cartoon")


async def cmd_blur(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    return await _effect_command(update, ctx, "blur")


async def cmd_gray(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    return await _effect_command(update, ctx, "gray")


async def cmd_sketch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    return await _effect_command(update, ctx, "sketch")


async def cmd_edges(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    return await _effect_command(update, ctx, "edges")


# ============================================================
# 5) معالجة الوسائط
# ============================================================
def primary_attachment(update: Update):
    msg = update.effective_message
    if msg is None:
        return None
    if msg.photo:
        return msg.photo[-1]
    if msg.video:
        return msg.video
    if msg.animation:
        return msg.animation
    if msg.document and (msg.document.mime_type or "").startswith("image/"):
        return msg.document
    return None


async def handle_media_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return await deny(update)
    if ctx.user_data.get("expecting_reference"):
        return await handle_reference(update, ctx)
    if ctx.user_data.get("expecting_mask"):
        return await handle_mask(update, ctx)
    if update.effective_message and (
        update.effective_message.video or update.effective_message.animation
    ):
        return await handle_target_video(update, ctx)
    return await handle_target_photo(update, ctx)


async def _download(message, attachment) -> io.BytesIO:
    size = int(getattr(attachment, "file_size", 0) or 0)
    if size and size > MAX_UPLOAD_BYTES:
        raise ValueError(f"الملف أكبر من {MAX_UPLOAD_MB} ميجابايت.")
    telegram_file = await attachment.get_file()
    buf = io.BytesIO()
    await telegram_file.download_to_memory(buf)
    buf.seek(0)
    return buf


async def _drop_target_video(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    path = ctx.user_data.pop("target_video_path", None)
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


async def handle_target_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    attachment = primary_attachment(update)
    if attachment is None:
        return await update.message.reply_text("أرسل صورة (JPG/PNG) أو مستند صورة.")
    try:
        buf = await _download(update.message, attachment)
        bgr = await asyncio.to_thread(buffer_to_bgr, buf)
    except Exception as exc:
        return await update.message.reply_text(f"❌ {exc}")
    await _drop_target_video(ctx)
    reset_user_state(ctx, keep_target=False)
    ctx.user_data["target_kind"] = "photo"
    ctx.user_data["target_bgr"] = bgr
    await run_ad_simulation(update.message, ctx)


async def handle_target_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    attachment = update.message.video or update.message.animation
    try:
        buf = await _download(update.message, attachment)
    except Exception as exc:
        return await update.message.reply_text(f"❌ {exc}")
    suffix = ".mp4"
    handle, path = tempfile.mkstemp(prefix="myface-in-", suffix=suffix)
    os.close(handle)
    with open(path, "wb") as fh:
        fh.write(buf.getvalue())
    await _drop_target_video(ctx)
    reset_user_state(ctx, keep_target=False)
    ctx.user_data["target_kind"] = "video"
    ctx.user_data["target_video_path"] = path
    await run_ad_simulation(update.message, ctx)
    await update.message.reply_text(
        "🎬 الفيديو جاهز. أرسل أحد الأوامر: /cartoon /blur /gray /sketch /edges"
    )


async def _download_reference(update: Update) -> io.BytesIO:
    if not update.message.photo:
        raise ValueError("أرسل صورة مرجعية وليس ملفًا آخر.")
    attachment = update.message.photo[-1]
    return await _download(update.message, attachment)


async def handle_reference(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.user_data.get("expecting_reference"):
        return
    attachment = primary_attachment(update)
    if attachment is None:
        return await update.message.reply_text("أرسل صورة مرجعية (JPG/PNG).")
    ctx.user_data["expecting_reference"] = False
    target = ctx.user_data.get("target_bgr")
    if target is None:
        return await update.message.reply_text("أعد إرسال الصورة الهدف أولًا.")
    try:
        ref_buf = await _download(update.message, attachment)
        ref_bgr = await asyncio.to_thread(buffer_to_bgr, ref_buf)
        result = await asyncio.to_thread(swap_faces, ref_bgr, target)
        await update.message.reply_photo(
            photo=bgr_to_buffer(result), caption="✅ اكتمل تبديل الوجه."
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ فشل: {exc}")


async def handle_mask(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.user_data.get("expecting_mask"):
        return
    attachment = primary_attachment(update)
    if attachment is None:
        return await update.message.reply_text("أرسل الماسك كصورة.")
    ctx.user_data["expecting_mask"] = False
    target = ctx.user_data.get("target_bgr")
    if target is None:
        return await update.message.reply_text("أعد إرسال الصورة الهدف أولًا.")
    try:
        mask_buf = await _download(update.message, attachment)
        mask_bgr = await asyncio.to_thread(buffer_to_bgr, mask_buf)
        result = await asyncio.to_thread(inpaint_mask, target, mask_bgr)
        await update.message.reply_photo(
            photo=bgr_to_buffer(result), caption="✅ اكتمل تعديل المنطقة."
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ فشل: {exc}")


def _video_from_state(path_in: str | None, effect: str) -> io.BytesIO:
    if not path_in or not os.path.exists(path_in):
        raise ValueError("انتهت صلاحية الفيديو — أعد إرساله.")
    handle, path_out = tempfile.mkstemp(prefix="myface-out-", suffix=".mp4")
    os.close(handle)
    try:
        process_video(path_in, path_out, effect)
        with open(path_out, "rb") as fh:
            data = fh.read()
        buf = io.BytesIO(data)
        buf.name = "myface.mp4"
        buf.seek(0)
        return buf
    finally:
        try:
            os.unlink(path_out)
        except OSError:
            pass


async def cmd_cleanup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    path = ctx.user_data.pop("target_video_path", None)
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass
    reset_user_state(ctx, keep_target=False)


# ============================================================
# 6) خادم الويب (Webhook + Healthcheck) لـ Render
# ============================================================
async def healthcheck(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "service": "myface",
            "uptime": int(time.time() - STARTED_AT),
            "webhook": bool(WEBHOOK_URL),
        }
    )


async def index(_: Request) -> PlainTextResponse:
    return PlainTextResponse("myface bot is running")


def build_starlette_app(ptb_app: Application) -> Starlette:
    @asynccontextmanager
    async def lifespan(_: Starlette):
        if WEBHOOK_URL:
            await ptb_app.initialize()
            await ptb_app.start()
            await ptb_app.bot.set_webhook(
                url=WEBHOOK_URL,
                secret_token=WEBHOOK_SECRET or None,
                drop_pending_updates=False,
                allowed_updates=["message", "callback_query"],
            )
            logger.info("تم تسجيل Webhook على %s", WEBHOOK_URL)
        yield
        if WEBHOOK_URL:
            try:
                await ptb_app.bot.delete_webhook()
            except Exception:
                pass
            try:
                await ptb_app.stop()
                await ptb_app.shutdown()
            except Exception:
                pass

    async def webhook(request: Request) -> PlainTextResponse:
        if WEBHOOK_SECRET:
            provided = request.headers.get("x-telegram-bot-api-secret-token", "")
            if provided != WEBHOOK_SECRET:
                return PlainTextResponse("forbidden", status_code=403)
        try:
            data = await request.json()
        except Exception:
            return PlainTextResponse("bad request", status_code=400)
        try:
            update = Update.de_json(data, ptb_app.bot)
            await ptb_app.process_update(update)
        except Exception:
            logger.exception("فشل معالجة تحديث")
        return PlainTextResponse("ok")

    routes = [
        Route("/", index, methods=["GET"]),
        Route("/healthcheck", healthcheck, methods=["GET"]),
        Route("/health", healthcheck, methods=["GET"]),
        Route(WEBHOOK_PATH, webhook, methods=["POST"]),
    ]
    return Starlette(routes=routes, lifespan=lifespan)


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is not None:
        await query.answer(
            "أرسل الصورة/الفيديو أولًا ثم استخدم الأمر المناسب.",
            show_alert=True,
        )


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("خطأ غير متوقع", exc_info=ctx.error)


# ============================================================
# 7) نقطة الدخول
# ============================================================
def build_application() -> Application:
    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN غير موجود. أضفه من متغيرات البيئة على Render."
        )
    ptb_app = (
        Application.builder()
        .token(TOKEN)
        .updater(None)
        .concurrent_updates(4)
        .build()
    )
    ptb_app.add_handler(CommandHandler("start", cmd_start))
    ptb_app.add_handler(CommandHandler("help", cmd_help))
    ptb_app.add_handler(CommandHandler("cancel", cmd_cancel))
    ptb_app.add_handler(CommandHandler("faceswap", cmd_faceswap))
    ptb_app.add_handler(CommandHandler("inpaint", cmd_inpaint))
    ptb_app.add_handler(CommandHandler("cartoon", cmd_cartoon))
    ptb_app.add_handler(CommandHandler("blur", cmd_blur))
    ptb_app.add_handler(CommandHandler("gray", cmd_gray))
    ptb_app.add_handler(CommandHandler("sketch", cmd_sketch))
    ptb_app.add_handler(CommandHandler("edges", cmd_edges))
    ptb_app.add_handler(CommandHandler("cleanup", cmd_cleanup))
    ptb_app.add_handler(CallbackQueryHandler(on_callback))
    ptb_app.add_handler(
        MessageHandler(
            (filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.Document.IMAGE),
            handle_media_router,
        )
    )
    ptb_app.add_error_handler(on_error)
    return ptb_app


def main() -> None:
    if not WEBHOOK_URL:
        logger.error("RENDER_EXTERNAL_URL/PUBLIC_URL غير موجود — لا يمكن تسجيل Webhook.")
        raise SystemExit(1)
    application = build_application()
    web_app = build_starlette_app(application)
    uvicorn.run(web_app, host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()

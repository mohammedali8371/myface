"""فحص ذاتي سريع لـ myface — شغّله قبل النشر: python selftest.py

لا يحتاج توكن ولا اتصالًا بتيليجرام؛ يختبر محرك OpenCV وبناء الرسائل فقط.
"""

from __future__ import annotations

import os
import tempfile

import cv2
import numpy as np

import app as bot


def _image() -> np.ndarray:
    img = np.zeros((240, 320, 3), np.uint8)
    cv2.rectangle(img, (40, 40), (280, 200), (30, 120, 200), -1)
    cv2.circle(img, (160, 120), 60, (200, 180, 120), -1)
    return img


def main() -> int:
    img = _image()

    back = bot.buffer_to_bgr(bot.bgr_to_buffer(img))
    assert back.shape[:2] == img.shape[:2]
    print("✅ صور: ترميز/فك ترميز")

    for effect in ("cartoon", "blur", "gray", "sketch", "edges"):
        out = bot.apply_effect(img, effect)
        assert out is not None and out.size
        print(f"✅ تأثير: {effect}")

    mask = np.zeros((240, 320, 3), np.uint8)
    cv2.rectangle(mask, (120, 80), (200, 160), (255, 255, 255), -1)
    assert bot.inpaint_mask(img, mask).shape == img.shape
    print("✅ تعديل منطقة (inpaint)")

    class FakeCascade:
        def detectMultiScale(self, *args, **kwargs):
            return np.array([[20, 20, 60, 60]], dtype=np.int32)

    original = bot.face_cascade
    bot.face_cascade = lambda: FakeCascade()
    try:
        assert bot.swap_faces(img.copy(), img.copy()).shape == img.shape
        print("✅ تبديل الوجه (منطق الدمج)")
    finally:
        bot.face_cascade = original

    with tempfile.TemporaryDirectory() as tmp:
        source = os.path.join(tmp, "in.mp4")
        target = os.path.join(tmp, "out.mp4")
        writer = cv2.VideoWriter(
            source, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240)
        )
        assert writer.isOpened()
        for index in range(10):
            frame = img.copy()
            cv2.putText(
                frame,
                str(index),
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 255, 255),
                2,
            )
            writer.write(frame)
        writer.release()
        frames = bot.process_video(source, target, "cartoon")
        assert frames == 10 and os.path.getsize(target) > 0
        print(f"✅ فيديو: {frames} إطارًا")

    report = bot.build_developer_report()
    assert "myface" in report and bot.SERVICE_VERSION in report
    print("✅ رسالة المطور")
    print(f"\n🎉 myface {bot.SERVICE_VERSION} — كل الفحوص نجحت")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

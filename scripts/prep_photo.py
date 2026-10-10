"""
Prepare a portrait photo for ASCII conversion:
  1. isolate the subject with rembg (set USE_REMBG=0 to skip, falls back to a
     plain black-floor crush of the background); the cutout is cached in
     source-cutout.png so tuning the other steps does not rerun the model
  2. boost local contrast (CLAHE) and bilateral-smooth skin texture
  3. stretch tones over the subject only so lit areas land in dense chars
  4. lift the subject's shadow side to a faint floor so the silhouette
     (hair, jacket) still prints as sparse chars instead of vanishing
  5. composite onto black and square-crop around the subject

Output: source-prepped.png (grayscale), consumed by make_ascii_svg.py.

    python scripts/prep_photo.py [input.png] [output.png]
"""
import os
import sys

import cv2
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
INP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "source-photo.png")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "source-prepped.png")

USE_REMBG = os.environ.get("USE_REMBG", "1") != "0"
SILHOUETTE_FLOOR = float(os.environ.get("SILHOUETTE_FLOOR", 0.14))
BLACK_FLOOR = float(os.environ.get("BLACK_FLOOR", 0.16))
STRETCH_LO, STRETCH_HI = 3, 97


CUTOUT_CACHE = os.path.join(HERE, "..", "source-cutout.png")


def isolate_subject(img):
    if not USE_REMBG:
        return img.convert("RGBA")
    if os.path.exists(CUTOUT_CACHE) and os.path.getmtime(CUTOUT_CACHE) >= os.path.getmtime(INP):
        return Image.open(CUTOUT_CACHE).convert("RGBA")
    from rembg import remove
    cut = remove(img.convert("RGBA"))
    cut.save(CUTOUT_CACHE)
    return cut


cut = isolate_subject(Image.open(INP))
rgb = np.array(cut.convert("RGB"))
alpha = np.array(cut.split()[-1])
gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
gray = clahe.apply(gray)

smooth = gray
for _ in range(2):
    smooth = cv2.bilateralFilter(smooth, 9, 40, 9)

subject = alpha > 128
tone = smooth.astype(np.float32) / 255.0
if USE_REMBG and subject.any():
    lo, hi = np.percentile(tone[subject], [STRETCH_LO, STRETCH_HI])
    tone = np.clip((tone - lo) / max(hi - lo, 1e-3), 0, 1)
    tone = np.where(subject, np.maximum(tone, SILHOUETTE_FLOOR), tone)
else:
    tone = np.where(tone < BLACK_FLOOR, 0.0, (tone - BLACK_FLOOR) / (1.0 - BLACK_FLOOR))

out = np.clip(tone, 0, 1) * 255
mask = cv2.GaussianBlur(alpha.astype(np.float32) / 255.0, (0, 0), 1.0)
out = out * mask

ys, xs = np.where(out > 25)
side = max(xs.max() - xs.min(), ys.max() - ys.min()) + 40
cx, cy = (xs.min() + xs.max()) // 2, (ys.min() + ys.max()) // 2
canvas = np.zeros((side, side), np.uint8)
x0, y0 = cx - side // 2, cy - side // 2
sx0, sy0 = max(x0, 0), max(y0, 0)
sx1, sy1 = min(x0 + side, out.shape[1]), min(y0 + side, out.shape[0])
canvas[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = out[sy0:sy1, sx0:sx1].astype(np.uint8)

Image.fromarray(canvas, mode="L").save(OUT)
print("wrote", OUT, canvas.shape)

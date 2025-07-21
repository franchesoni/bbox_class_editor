from pathlib import Path
import os
import json
import base64
import io
from typing import List

from PIL import Image
Image.MAX_IMAGE_PIXELS = 10_000_000_000
from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route

# ─── top of file ───
import csv                     # NEW
from datetime import datetime   # optional timestamp



"""Image visualizer – now uses an **external HTML template** (`app.html`).

How it works
------------
* `IMAGES`: list of image file paths.
* `INT_LISTS`: list of *metadata lists* (must match `IMAGES` length).
* `app.html` lives next to this script and contains placeholders that are
  filled server‑side.

Allowed placeholders inside **app.html** (use *single braces* and **double braces for literal CSS braces**):

```
{{  }}  -> literal brace for CSS (because we use `.format()`)
{idx}   -> zero‑based index (for calculations)
{display_idx} -> 1‑based index shown to user
{total} -> total number of images
{img_data_uri} -> base64 <img src>
{int_list} -> Python list / str
{next_idx} / {prev_idx} -> indices for navigation links
```

Example snippet for CSS braces in app.html:

```html
<style>
  body {{ font-family: Arial, sans-serif; }}
</style>
```

Run:
    uvicorn app:app --host 127.0.0.1 --port 8001
"""
# ---------------------------------------------------------------------------
# SECURITY
# ---------------------------------------------------------------------------
# ─── basic‑auth middleware ───
import secrets, base64
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
USERNAME, PASSWORD = "karim", "waldenstrom"

class BasicAuth(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        hdr = request.headers.get("authorization", "")
        if not hdr.startswith("Basic "):
            return PlainTextResponse("Auth required", 401,
                                     headers={"WWW-Authenticate": "Basic"})
        try:
            user, pwd = base64.b64decode(hdr[6:]).decode().split(":", 1)
        except Exception:
            return PlainTextResponse("Bad header", 400)
        if not (secrets.compare_digest(user, USERNAME) and
                secrets.compare_digest(pwd, PASSWORD)):
            return PlainTextResponse("Unauthorized", 401,
                                     headers={"WWW-Authenticate": "Basic"})
        return await call_next(request)



# ---------------------------------------------------------------------------
# 💾 Configure your image paths & metadata
# ---------------------------------------------------------------------------
ANNOT_CSV = Path(__file__)
CSV_HEADERS = [
    "timestamp", "image_path", "left", "top", "right", "bottom", "class"
]

def load_bboxes(json_path: str) -> List[int]:
    """Load bounding boxes from a JSON file and map class id -> name."""
    class_map = {0: "lymphocyte", 1: "lymphoplasmocyte", 2: "plasmocyte", 3: "other"}
    with open(json_path, "r") as f:
        raw = json.load(f)
    converted = []
    for bbox in raw:
        bbox = [int(e) for e in bbox]
        bbox[-1] = class_map.get(bbox[-1], "unknown")  # replace last int w/ label
        converted.append(bbox)
    return converted


pred_folder = Path("/home/franchesoni/pitie_data/predictions/")
IMAGES, INT_LISTS = [], []
for subdir in os.listdir(pred_folder):
    image = list((pred_folder / subdir).glob("assembled_image_img*.png"))
    bboxes = list((pred_folder / subdir).glob("bboxes_labels*.json"))
    if (len(image) >= 1) and (len(bboxes) == 1):
        image, bboxes = image[0], bboxes[0]  # select first element
        IMAGES.append(image)
        INT_LISTS.append(load_bboxes(bboxes))


# Sanity checks
if not IMAGES:
    raise RuntimeError("IMAGES list is empty – add paths to your images.")
if len(INT_LISTS) != len(IMAGES):
    raise RuntimeError("INT_LISTS must match IMAGES length ({} vs {}).".format(len(INT_LISTS), len(IMAGES)))

# ---------------------------------------------------------------------------
# 🔧 Helpers
# ---------------------------------------------------------------------------

def _encode_image(path: str) -> str:
    """Return a base64‑encoded JPEG data‑URI for *path*."""
    img = Image.open(Path(path)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

# Locate template next to this script
TEMPLATE_FILE = Path(__file__).with_name("app.html")
if not TEMPLATE_FILE.exists():
    raise RuntimeError("Template file 'app.html' not found alongside script.")

def _render_template(**kwargs) -> str:
    """Read *app.html* and .format(**kwargs)."""
    html_template = TEMPLATE_FILE.read_text(encoding="utf-8")
    return html_template.format(**kwargs)

# ---------------------------------------------------------------------------
# 🚀 Route
# ---------------------------------------------------------------------------
async def homepage(request):
    idx = int(request.query_params.get("idx", 0)) % len(IMAGES)
    next_idx, prev_idx = (idx + 1) % len(IMAGES), (idx - 1) % len(IMAGES)

    html = _render_template(
        idx=idx,
        display_idx=idx + 1,
        total=len(IMAGES),
        img_data_uri=_encode_image(IMAGES[idx]),
        int_list=INT_LISTS[idx],
        next_idx=next_idx,
        prev_idx=prev_idx,
    )
    return HTMLResponse(html)


async def save_annotations(request):
    """
    Expects JSON:
    {
        "image_idx": 0,
        "boxes": [[x1,y1,x2,y2,"class", timestamp], ...]
    }
    Appends one CSV row per box, using the provided timestamp (converted to ISO8601 UTC).
    Now saves image path instead of image index.
    """
    data = await request.json()
    image_idx = data.get("image_idx")
    boxes = data.get("boxes", [])

    # Get image path from index (with fallback)
    try:
        image_path = IMAGES[image_idx]
    except Exception:
        image_path = str(image_idx)

    # create file with header if it doesn't exist
    Path("annotations").mkdir(parents=True, exist_ok=True)
    with ANNOT_CSV.with_name(f"annotations/annotations_img{image_idx}.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)

        for box in boxes:
            # Accept both old and new format for backward compatibility
            if len(box) == 7:
                ts, x1, y1, x2, y2, cls = box[5], box[0], box[1], box[2], box[3], box[4]
                ts = box[5]
            elif len(box) == 6:
                x1, y1, x2, y2, cls, ts = box
            else:
                x1, y1, x2, y2, cls = box[:5]
                ts = datetime.utcnow().timestamp() * 1000
            # Convert ms timestamp to ISO8601 UTC
            try:
                ts_iso = datetime.utcfromtimestamp(float(ts)/1000).isoformat()
            except Exception:
                ts_iso = datetime.utcnow().isoformat()
            writer.writerow([ts_iso, image_path, x1, y1, x2, y2, cls])

    return HTMLResponse("OK", status_code=200)

# ---------------------------------------------------------------------------
# 🏁 Starlette application
# ---------------------------------------------------------------------------
from starlette.middleware import Middleware

routes = [
    Route("/", homepage),
    Route("/export", save_annotations, methods=["POST"]),  # NEW
]

app = Starlette(routes=routes, middleware=[Middleware(BasicAuth)])

from pathlib import Path
import json
import base64
import io
from typing import List

from PIL import Image
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
# 💾 Configure your image paths & metadata
# ---------------------------------------------------------------------------
ANNOT_CSV = Path(__file__)
CSV_HEADERS = [
    "timestamp", "image_path", "left", "top", "right", "bottom", "class"
]

IMAGES: List[str] = [
    "/home/franchesoni/mine/repos/annotation_apps/bbox_class_editor/data/assembled_image_img_1_1609.125_1817.0.png",
    "/home/franchesoni/mine/repos/annotation_apps/bbox_class_editor/data/assembled_image_img_1_2699.125_464.0.png",
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

# Example metadata per image
INT_LISTS: List[List[int]] = [
    load_bboxes("/home/franchesoni/mine/repos/annotation_apps/bbox_class_editor/data/bboxes_labels_1_1609.125_1817.0.json"),
    load_bboxes("/home/franchesoni/mine/repos/annotation_apps/bbox_class_editor/data/bboxes_labels_1_2699.125_464.0.json"),
]

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
    with ANNOT_CSV.with_name(f"annotations_img{image_idx}.csv").open("w", newline="") as f:
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
routes = [
    Route("/", homepage),
    Route("/export", save_annotations, methods=["POST"]),  # NEW
]

app = Starlette(routes=routes)

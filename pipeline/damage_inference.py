"""Run public wall-damage detections and derive explicit, reviewable takeoff proxies."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import cv2


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MODEL_ID = "wall-damage-detection/1"
MODEL_SOURCE = "https://universe.roboflow.com/wall-damage-detection/wall-damage-detection"
CLASS_NAMES = {
    "crack_damage": "crack",
    "flaking_paint_damage": "flaking_paint",
    "missing_piece_damage": "missing_material",
    "water_damage": "water_damage",
}
SCOPE_TEXT = {
    "crack": "Review, prepare, and seal detected crack; confirm crack cause and repair specification on site.",
    "flaking_paint": "Prepare the detected flaking finish and repaint after substrate review.",
    "missing_material": "Patch the detected missing wall-finish area after substrate review.",
    "water_damage": "Investigate the moisture source, dry the substrate, and repair the affected finish.",
}


def _post_roboflow_image(image_path: Path, api_key: str, *, confidence: float, timeout: float = 90) -> dict:
    """Call the public Roboflow hosted detector using a dependency-free multipart request."""
    boundary = "----PropertyVision" + secrets.token_hex(16)
    image_bytes = image_path.read_bytes()
    mime = {
        ".png": "image/png", ".webp": "image/webp", ".bmp": "image/bmp",
    }.get(image_path.suffix.lower(), "image/jpeg")
    chunks = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{image_path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8"),
        image_bytes,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ]
    query = urllib.parse.urlencode({"api_key": api_key, "confidence": round(confidence * 100)})
    request = urllib.request.Request(
        f"https://detect.roboflow.com/{MODEL_ID}?{query}",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Roboflow inference failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach the Roboflow inference API: {exc.reason}") from exc


def _measurement(value: float | None, unit: str, method: str, status: str = "partial") -> dict:
    return {"status": status, "value": round(float(value), 4) if value is not None else None,
            "unit": unit, "interval": None, "method": method}


def detections_to_assessment(
    image_path: Path,
    predictions: list[dict],
    *,
    scale_m_per_px: float | None = None,
    confidence_threshold: float = 0.25,
) -> tuple[list[dict], list[dict]]:
    """Convert model boxes to the project schema and bounded, non-priced scope quantities."""
    image_path = Path(image_path).resolve()
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image: {image_path}")
    image_height, image_width = image.shape[:2]
    if scale_m_per_px is not None and (not math.isfinite(scale_m_per_px) or scale_m_per_px <= 0):
        raise ValueError("scale_m_per_px must be a finite positive number.")
    regions, scope = [], []
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", image_path.stem).strip("_") or "image"
    image_token = f"{safe_stem}_{hashlib.sha256(str(image_path).encode('utf-8')).hexdigest()[:8]}"
    surface_id = "surface_" + image_token
    for prediction_index, prediction in enumerate(predictions, start=1):
        confidence = float(prediction.get("confidence", 0.0))
        if confidence < confidence_threshold:
            continue
        label = str(prediction.get("class", prediction.get("class_name", "unknown"))).lower()
        damage_class = CLASS_NAMES.get(label, label.replace("_damage", ""))
        center_x, center_y = float(prediction.get("x", 0)), float(prediction.get("y", 0))
        width, height = max(0.0, float(prediction.get("width", 0))), max(0.0, float(prediction.get("height", 0)))
        x0 = max(0.0, min(float(image_width), center_x - width / 2))
        x1 = max(0.0, min(float(image_width), center_x + width / 2))
        y0 = max(0.0, min(float(image_height), center_y - height / 2))
        y1 = max(0.0, min(float(image_height), center_y + height / 2))
        if x1 <= x0 or y1 <= y0:
            continue
        box_width, box_height = x1 - x0, y1 - y0
        is_linear = damage_class == "crack"
        raw_quantity = max(box_width, box_height) if is_linear else box_width * box_height
        if scale_m_per_px is None:
            unit = "px" if is_linear else "px^2"
            value = raw_quantity
            scale_note = "Image-space proxy only; no metric surface calibration was supplied."
        else:
            unit = "m" if is_linear else "m^2"
            value = raw_quantity * (scale_m_per_px if is_linear else scale_m_per_px**2)
            scale_note = "Metric proxy uses one caller-supplied image scale; perspective and surface tilt are not corrected."
        method = (
            f"Roboflow {MODEL_ID} detection bounding-box {('long-axis' if is_linear else 'area')} proxy; "
            f"confidence={confidence:.3f}. {scale_note} Bounding boxes are not pixel masks; quantity is preliminary."
        )
        region_id = f"damage_{image_token}_{prediction_index:03d}"
        regions.append({
            "region_id": region_id,
            "surface_id": surface_id,
            "class": damage_class,
            "extent": _measurement(value, unit, method),
            "confidence": min(1.0, max(0.0, confidence)),
            "image_regions": [{
                "image_path": str(image_path),
                "polygon_px": [[round(x0, 2), round(y0, 2)], [round(x1, 2), round(y0, 2)],
                               [round(x1, 2), round(y1, 2)], [round(x0, 2), round(y1, 2)]],
            }],
        })
        scope.append({
            "item_id": f"scope_{image_token}_{prediction_index:03d}",
            "surface_id": surface_id,
            "description": SCOPE_TEXT.get(damage_class, f"Review and repair visible {damage_class} damage; confirm scope on site."),
            "quantity": _measurement(value, unit, method),
        })
    return regions, scope


def build_damage_assessment(
    images: list[Path], *, api_key: str, scale_m_per_px: float | None = None,
    confidence_threshold: float = 0.25,
) -> dict:
    damage_regions, scope_line_items = [], []
    for image_path in images:
        response = _post_roboflow_image(image_path, api_key, confidence=confidence_threshold)
        predictions = response.get("predictions", [])
        if not isinstance(predictions, list):
            raise ValueError(f"Unexpected inference response for {image_path}: predictions is not an array.")
        regions, line_items = detections_to_assessment(
            image_path, predictions, scale_m_per_px=scale_m_per_px,
            confidence_threshold=confidence_threshold,
        )
        damage_regions.extend(regions)
        scope_line_items.extend(line_items)
    return {
        "assessment_metadata": {
            "source": "roboflow_hosted_inference",
            "model_id": MODEL_ID,
            "model_url": MODEL_SOURCE,
            "confidence_threshold": confidence_threshold,
            "scale_m_per_px": scale_m_per_px,
            "images_uploaded_to_provider": True,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "damage_regions": damage_regions,
        "concealed_damage_flags": [],
        "scope_line_items": scope_line_items,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify visible wall damage via the public Roboflow model and create a takeoff sidecar.")
    parser.add_argument("images", type=Path, help="An image file or a folder of wall/ceiling images.")
    parser.add_argument("--output", type=Path, default=Path("outputs/damage_assessment.json"), help="JSON assessment sidecar path.")
    parser.add_argument("--scale-m-per-px", type=float, help="Optional known scale for an approximately front-facing planar surface; omit to keep quantities in pixels.")
    parser.add_argument("--confidence", type=float, default=0.25, help="Minimum detector confidence from 0 to 1.")
    args = parser.parse_args(argv)
    if not 0 <= args.confidence <= 1:
        parser.error("--confidence must be from 0 to 1.")
    api_key = os.environ.get("ROBOFLOW_API_KEY", "").strip()
    if not api_key:
        parser.error("Set ROBOFLOW_API_KEY in the environment. The key is used only for inference and is never written to output.")
    source = args.images.resolve()
    if source.is_file():
        images = [source]
    elif source.is_dir():
        images = sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
    else:
        parser.error(f"Image input does not exist: {source}")
    if not images:
        parser.error(f"No supported images found under {source}")
    result = build_damage_assessment(images, api_key=api_key, scale_m_per_px=args.scale_m_per_px,
                                     confidence_threshold=args.confidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Classified {len(images)} image(s); wrote {len(result['damage_regions'])} damage regions and {len(result['scope_line_items'])} scope items to {args.output.resolve()}")
    print("All quantities are preliminary detector-box proxies; metric units require a supplied scale.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

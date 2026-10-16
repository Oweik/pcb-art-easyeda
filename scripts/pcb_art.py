"""PCB art manufacturing layers for EasyEDA: import, preview and verified draft export."""
import argparse
import json
import math
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LAYERS = ("front_copper", "front_mask_open", "front_silk", "back_copper", "back_mask_open", "back_silk")


def rectangles(rows):
    """Exact horizontal runs, merged vertically; preserves holes and all pixels."""
    active, result = {}, []
    for y, row in enumerate(rows + [[False] * len(rows[0])]):
        runs, x = [], 0
        while x < len(row):
            if not row[x]:
                x += 1
                continue
            start = x
            while x < len(row) and row[x]:
                x += 1
            runs.append((start, x))
        next_active = {}
        for run in runs:
            next_active[run] = active.pop(run, y)
        for (left, right), top in active.items():
            result.append([left, top, right - left, y - top])
        active = next_active
    return result


def load_masks(manifest):
    from PIL import Image
    spec = json.loads(manifest.read_text(encoding="utf-8"))
    if spec.get("polarity") != "black-selected" or spec.get("back_view") != "normal":
        raise ValueError("Manifest requires polarity=black-selected and back_view=normal")
    width, height = spec["width_mm"], spec["height_mm"]
    if not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError("Board dimensions must be positive finite millimeters")
    if set(spec["layers"]) - set(LAYERS):
        raise ValueError("Unknown layer name")
    masks, size = {}, None
    for layer, filename in spec["layers"].items():
        with Image.open(manifest.parent / filename) as source:
            image = source.convert("RGBA")
            if any(a != 255 for *_, a in image.getdata()):
                raise ValueError("Flatten transparency explicitly before conversion")
            rgb = image.convert('RGB')
            if any(pixel not in ((0,0,0),(255,255,255)) for pixel in rgb.getdata()):
                raise ValueError("Input masks must be binary 0/255; no implicit threshold")
            gray = rgb.convert("L")
            if size is not None and gray.size != size:
                raise ValueError("All masks must use the same canvas")
            size = gray.size
            data = list(gray.getdata())
            masks[layer] = [[data[y * size[0] + x] == 0 for x in range(size[0])] for y in range(size[1])]
    if not masks:
        raise ValueError("No masks supplied")
    empty = [[False] * size[0] for _ in range(size[1])]
    for side in ("front", "back"):
        copper, opening, silk = (masks.get(side + suffix, empty) for suffix in ("_copper", "_mask_open", "_silk"))
        if any(o and not c for cr, op in zip(copper, opening) for c, o in zip(cr, op)):
            raise ValueError(f"{side}: mask opening without copper")
        if any(o and s for sr, op in zip(silk, opening) for s, o in zip(sr, op)):
            raise ValueError(f"{side}: silkscreen overlaps mask opening")
    shapes = []
    for layer, rows in masks.items():
        for x, y, w, h in rectangles(rows):
            shapes.append({"layer": layer, "rect_mm": [x * width / size[0], y * height / size[1], w * width / size[0], h * height / size[1]]})
    return {"schema": 1, "width_mm": width, "height_mm": height, "shapes": shapes,
            "back_view": "normal", "pixel_mm": [width / size[0], height / size[1]], "canvas_px": list(size),
            "validation": "binary alignment, opening copper coverage, silk overlap; not DRC/CAM"}


def api(base, path, data=None):
    payload = None if data is None else json.dumps(data).encode()
    request = Request(base + path, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=40) as response:
        result = json.load(response)
    if result.get("success") is False:
        raise RuntimeError(result.get("error", "Bridge operation failed"))
    return result


def connect(window=None):
    for port in range(49620, 49630):
        base = f"http://127.0.0.1:{port}"
        try:
            with urlopen(base + "/health", timeout=0.5) as response:
                health = json.load(response)
            if health.get("service") != "easyeda-bridge":
                continue
        except (OSError, ValueError):
            continue
        windows = api(base, "/eda-windows")["windows"]
        connected = [w["windowId"] for w in windows if w["connected"]]
        if window and window in connected:
            return base, window
        if not window and len(connected) == 1:
            return base, connected[0]
        raise RuntimeError(f"Select --window from connected windows: {connected}; load run-api-gateway if empty")
    raise RuntimeError("No easyeda-bridge service found on ports 49620-49629")


def execute(base, window, code):
    return api(base, "/execute", {"code": code, "windowId": window})["result"]


def validate_plan(plan):
    if plan.get("schema") != 1 or plan.get("back_view") != "normal":
        raise ValueError("Unsupported schema or back orientation")
    width, height = plan["width_mm"], plan["height_mm"]
    if not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError("Invalid board dimensions")
    for shape in plan["shapes"]:
        if shape["layer"] not in LAYERS:
            raise ValueError("Unknown layer")
        x, y, w, h = shape["rect_mm"]
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (x, y, w, h)) or min(x, y) < 0 or min(w, h) <= 0 or x + w > width + 1e-8 or y + h > height + 1e-8:
            raise ValueError("Invalid/outside-board rectangle")


def import_plan(plan, base, window, receipt_path):
    validate_plan(plan)
    if len(plan['shapes']) > 2000:
        raise ValueError('Fill backend limited to 2000 shapes; use import-images with the source manifest for artwork')
    info = execute(base, window, "return await eda.dmt_SelectControl.getCurrentDocumentInfo();")
    if not info or info["documentType"] != 3:
        raise RuntimeError("Focus an empty PCB document first")
    runtime = (ROOT / "runtime.js").read_text(encoding="utf-8")
    receipt = {"status": "running", "document": info, "window": window, "batches": []}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        raise ValueError("Receipt exists; use a new path to preserve previous import records")
    def persist():
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    persist()
    try:
        for offset in range(0, max(1, len(plan["shapes"])), 12):
            batch = {"documentUuid": info["uuid"], "width_mm": plan["width_mm"], "height_mm": plan["height_mm"],
                     "shapes": plan["shapes"][offset:offset + 12], "outline": offset == 0, "requireEmpty": offset == 0}
            code = "const batch=" + json.dumps(batch, allow_nan=False) + ";" + runtime
            receipt["pending_batch"] = offset // 12
            persist()
            result = execute(base, window, code)
            receipt["batches"].append(result)
            if not result.get("ok"):
                raise RuntimeError(f"Batch failed: {result}")
            receipt.pop("pending_batch", None)
            persist()
        receipt["status"] = "native-readback-passed"
        try:
            view_code = "const doc=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(doc?.uuid!==" + json.dumps(info["uuid"]) + ")throw new Error('PCB focus changed');const Layer={TOP:1,TOP_SILKSCREEN:3,TOP_SOLDER_MASK:5,BOARD_OUTLINE:11};await eda.pcb_Layer.setLayerVisible([Layer.TOP,Layer.TOP_SILKSCREEN,Layer.TOP_SOLDER_MASK,Layer.BOARD_OUTLINE],true);await eda.pcb_Layer.selectLayer(Layer.TOP_SILKSCREEN);return await eda.pcb_Document.zoomToBoardOutline();"
            receipt["view_focused"] = execute(base, window, view_code)
        except Exception as error:
            receipt["view_error"] = str(error)
    except Exception as error:
        receipt["status"] = "incomplete-inspect-before-retry"
        receipt["error"] = str(error)
        raise
    finally:
        persist()
    return receipt


def make_demo(folder):
    from PIL import Image, ImageDraw
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for side in ("front", "back"):
        for kind in ("copper", "mask_open", "silk"):
            image = Image.new("L", (120, 160), 255)
            draw = ImageDraw.Draw(image)
            if kind == "copper":
                draw.rectangle((18, 24, 101, 113), fill=0)
            elif kind == "mask_open":
                draw.rectangle((25, 31, 94, 45), fill=0)
                draw.rectangle((25, 92, 45, 106), fill=0)
            else:
                draw.rectangle((30, 58, 43, 77), fill=0)
                draw.rectangle((76, 58, 89, 77), fill=0)
                draw.rectangle((53, 80, 66, 84), fill=0)
                # Asymmetric mark makes the back's single mirror visible.
                draw.rectangle((12 if side == "front" else 92, 135, 27 if side == "front" else 107, 141), fill=0)
            name = f"{side}_{kind}"
            image.save(folder / f"{name}.png")
            paths[name] = f"{name}.png"
    spec = {"width_mm": 30, "height_mm": 40, "polarity": "black-selected", "back_view": "normal", "layers": paths}
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    plan = load_masks(manifest)
    (folder / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return {"manifest": str(manifest), "shapes": len(plan["shapes"]), "size_mm": [30, 40]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("folder", type=Path)
    build = sub.add_parser("build")
    build.add_argument("manifest", type=Path)
    build.add_argument("output", type=Path)
    status = sub.add_parser("status")
    status.add_argument("--window")
    apply = sub.add_parser("import")
    apply.add_argument("plan", type=Path)
    apply.add_argument("--receipt", required=True, type=Path)
    apply.add_argument("--window")
    images = sub.add_parser('import-images', help='Import a source manifest as compound Image primitives')
    images.add_argument('manifest',type=Path)
    images.add_argument('--receipt',required=True,type=Path)
    images.add_argument('--window')
    for name in ('preview','export-gerber'):
        command = sub.add_parser(name)
        command.add_argument('manifest',type=Path)
        command.add_argument('output',type=Path)
    native = sub.add_parser('export-native')
    native.add_argument('output',type=Path)
    native.add_argument('--window')
    args = parser.parse_args()
    if args.command == "demo":
        result = make_demo(args.folder)
    elif args.command == "build":
        result = load_masks(args.manifest)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result = {"output": str(args.output), "shapes": len(result["shapes"])}
    elif args.command in ('preview','export-gerber'):
        from export_tools import preview, export_gerber
        result = (preview if args.command=='preview' else export_gerber)(args.manifest,args.output)
    else:
        base, window = connect(args.window)
        if args.command == "status":
            result = {"bridge": base, "window": window, "document": execute(base, window, "return await eda.dmt_SelectControl.getCurrentDocumentInfo();")}
        elif args.command == 'import-images':
            from image_backend import import_images
            result=import_images(args.manifest,base,window,args.receipt)
        elif args.command == 'export-native':
            from export_tools import export_native
            result=export_native(base,window,args.output)
        else:
            result = import_plan(json.loads(args.plan.read_text(encoding="utf-8")), base, window, args.receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, FileExistsError) as error:
        print(f'Error: {error}', file=sys.stderr)
        raise SystemExit(2)

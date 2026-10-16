"""Compound Image backend, calibrated with EasyEDA professional client 4.1.71."""
import hashlib
import json
import math
from pathlib import Path
import re

from pcb_art import LAYERS, ROOT, execute, load_masks, validate_plan

LAYER_IDS = dict(zip(LAYERS, (1, 5, 3, 2, 6, 4)))


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def guard(uuid):
    return 'const doc=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(doc?.uuid!==' + json.dumps(uuid) + '||doc.documentType!==3)throw new Error("Target PCB changed");'


def payload_for_layer(plan, layer):
    """Image mirrors bottom local x itself; top-right anchor yields one mirror."""
    shapes = [s['rect_mm'] for s in plan['shapes'] if s['layer'] == layer]
    if not shapes:
        return None
    left = min(r[0] for r in shapes)
    top = min(r[1] for r in shapes)
    right = max(r[0] + r[2] for r in shapes)
    bottom = max(r[1] + r[3] for r in shapes)
    sources = []
    for x, y, width, height in shapes:
        x -= left
        y -= top
        sources.append([x, -y, 'L', x+width, -y, x+width, -y-height, x, -y-height, x, -y])
    return {'sources': sources, 'x_mm': plan['width_mm']-left if layer.startswith('back_') else left,
            'y_mm': -top, 'width_mm': right-left, 'height_mm': bottom-top, 'layer': LAYER_IDS[layer]}


def raster_for_layer(plan, layer):
    px, py = plan['pixel_mm']
    width, height = round(plan['width_mm']/px), round(plan['height_mm']/py)
    raster = bytearray(width*height)
    for shape in plan['shapes']:
        if shape['layer'] != layer:
            continue
        x, y, w, h = shape['rect_mm']
        if layer.startswith('back_'):
            x = plan['width_mm']-x-w
        x0, y0, x1, y1 = round(x/px), round(y/py), round((x+w)/px), round((y+h)/py)
        for row in range(y0, y1):
            raster[row*width+x0:row*width+x1] = b'\x01'*(x1-x0)
    return raster


def normalized_svg_raster(sources, plan):
    """Client's normalized SVG uses absolute canvas axes and a 10 mil span."""
    px, py = plan['pixel_mm']
    width, height = round(plan['width_mm']/px), round(plan['height_mm']/py)
    raster = bytearray(width*height)
    if not isinstance(sources, list) or not sources or not all(isinstance(s, str) for s in sources):
        raise ValueError('Unrecognized Image readback format; cannot certify geometry')
    for source in sources:
        # This backend generates closed axis-aligned rectangles only; reject curves/relative paths.
        remaining = re.sub(r'[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?', '', source)
        if set(remaining) - set('ML ,\n\r\t') or not source.lstrip().startswith('M'):
            raise ValueError('Unsupported SVG commands in native readback')
        for part in source.split('M')[1:]:
            numbers = [float(n) for n in re.findall(r'[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?', part)]
            if len(numbers) != 10 or not all(math.isfinite(n) for n in numbers):
                raise ValueError('Expected one closed rectangle per path')
            points = list(zip(numbers[::2], numbers[1::2]))
            if points[0] != points[-1]:
                raise ValueError('Unclosed native rectangle')
            xs, ys = sorted(set(numbers[::2])), sorted(set(numbers[1::2]))
            if len(xs) != 2 or len(ys) != 2 or set(points) != {(x,y) for x in xs for y in ys}:
                raise ValueError('Non-rectangular native geometry')
            for a,b in zip(points,points[1:]):
                if a[0] != b[0] and a[1] != b[1]:
                    raise ValueError('Crossed native rectangle')
            x0,x1 = round(xs[0]*.254/px),round(xs[1]*.254/px)
            y0,y1 = round(ys[0]*.254/py),round(ys[1]*.254/py)
            if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                raise ValueError('Native geometry outside board or finer than input grid')
            for y in range(y0,y1):
                raster[y*width+x0:y*width+x1] = b'\x01'*(x1-x0)
    return raster


def close_numbers(a,b):
    if isinstance(a,list) and isinstance(b,list):
        return len(a)==len(b) and all(close_numbers(x,y) for x,y in zip(a,b))
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):
        return math.isfinite(a) and math.isfinite(b) and abs(a-b)<1e-7
    return a==b


def check_readback(actual, payload, plan, layer):
    if actual['layer'] != payload['layer'] or actual['mirror'] or actual['rotation'] != 0:
        raise ValueError('Native layer/mirror/rotation changed')
    for key, expected in [('x',payload['x_mm']),('y',payload['y_mm']),('width',payload['width_mm']),('height',payload['height_mm'])]:
        if abs(actual[key]*.0254-expected) > .00003:
            raise ValueError('Native position or dimensions changed')
    sources = actual['sources']
    if close_numbers(sources,payload['sources']):
        return {'method':'native source and placement comparison','pixel_difference':0}
    expected = raster_for_layer(plan,layer)
    restored = normalized_svg_raster(sources,plan)
    difference = sum(a!=b for a,b in zip(expected,restored))
    if difference:
        raise ValueError(f'Native Image roundtrip changed {difference} input pixels')
    return {'method':'normalized native SVG raster comparison','pixel_difference':difference}


def import_images(manifest, base, window, receipt_path):
    plan = load_masks(manifest)
    validate_plan(plan)
    info = execute(base,window,'return await eda.dmt_SelectControl.getCurrentDocumentInfo();')
    if not info or info['documentType'] != 3:
        raise RuntimeError('Focus a dedicated empty PCB document')
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive reservation prevents concurrent imports and preserves earlier receipts.
    with receipt_path.open('x',encoding='utf-8') as file:
        json.dump({'status':'reserved'},file)
    receipt = {'status':'running','document':info,'window':window,'backend':'compound-image',
               'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'layers':[]}
    atomic_json(receipt_path,receipt)
    prefix = guard(info['uuid'])
    try:
        batch = {'documentUuid':info['uuid'],'width_mm':plan['width_mm'],'height_mm':plan['height_mm'],
                 'shapes':[],'outline':True,'requireEmpty':True}
        runtime = (ROOT/'runtime.js').read_text(encoding='utf-8')
        receipt['pending']='empty-check-and-outline'
        atomic_json(receipt_path,receipt)
        result = execute(base,window,'const batch='+json.dumps(batch)+';'+runtime)
        receipt['outline']=result
        atomic_json(receipt_path,receipt)
        if not result.get('ok'):
            raise RuntimeError(result.get('error','Outline creation/readback failed'))
        for layer in LAYERS:
            payload = payload_for_layer(plan,layer)
            if payload is None:
                continue
            receipt['pending']=layer
            atomic_json(receipt_path,receipt)
            code = prefix+'const d='+json.dumps(payload,allow_nan=False,separators=(',',':'))+';const m=v=>eda.sys_Unit.mmToMil(v);const p=eda.pcb_MathPolygon.createComplexPolygon(d.sources);if(!p)throw new Error("Invalid Image geometry");const item=await eda.pcb_PrimitiveImage.create(m(d.x_mm),m(d.y_mm),p,d.layer,m(d.width_mm),m(d.height_mm),0,false,false);if(!item)throw new Error("Image create returned undefined");return item.getState_PrimitiveId();'
            identifier = execute(base,window,code)
            entry={'name':layer,'id':identifier,'rectangle_count':len(payload['sources']),'status':'created'}
            receipt['layers'].append(entry)
            atomic_json(receipt_path,receipt)
            actual = execute(base,window,prefix+'const image=await eda.pcb_PrimitiveImage.get('+json.dumps(identifier)+');if(!image)throw new Error("Image missing");return {layer:image.getState_Layer(),x:image.getState_X(),y:image.getState_Y(),width:image.getState_Width(),height:image.getState_Height(),rotation:image.getState_Rotation(),mirror:image.getState_HorizonMirror(),sources:image.getState_ComplexPolygon()};')
            entry['verification']=check_readback(actual,payload,plan,layer)
            entry['status']='readback-passed'
            atomic_json(receipt_path,receipt)
        receipt.pop('pending',None)
        receipt['status']='native-readback-passed'
        try:
            receipt['view_focused']=execute(base,window,prefix+'const Layer={TOP:1,TOP_SILKSCREEN:3,TOP_SOLDER_MASK:5,BOARD_OUTLINE:11};await eda.pcb_Layer.setLayerVisible([Layer.TOP,Layer.TOP_SILKSCREEN,Layer.TOP_SOLDER_MASK,Layer.BOARD_OUTLINE],true);await eda.pcb_Layer.selectLayer(Layer.TOP_SILKSCREEN);return await eda.pcb_Document.zoomToBoardOutline();')
        except Exception as error:
            receipt['view_error']=str(error)
    except Exception as error:
        receipt['status']='incomplete-inspect-before-retry'
        receipt['error']=str(error)
        raise
    finally:
        atomic_json(receipt_path,receipt)
    return receipt

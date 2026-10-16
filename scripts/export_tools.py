"""Local previews and draft Gerber; native export through the existing bridge."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from pcb_art import execute, load_masks, LAYERS
from image_backend import atomic_json, guard, raster_for_layer


def preview(manifest,output):
    from PIL import Image
    plan=load_masks(manifest)
    output.mkdir(parents=True,exist_ok=True)
    # Preserve existing reviews by requiring distinct paths, even when the input is unchanged.
    for side in ('front','back'):
        for suffix in ('','_low_contrast'):
            if (output/(side+suffix+'.png')).exists():
                raise FileExistsError('Preview exists; use a versioned output directory')
    width,height=plan['canvas_px']
    files=[]
    for side in ('front','back'):
        # Material previews display the back normally; native/Gerber comparisons use manufacturing coordinates.
        masks=[]
        for kind in ('copper','mask_open','silk'):
            layer=side+'_'+kind
            data=raster_for_layer(plan,layer)
            mask=Image.frombytes('L',(width,height),bytes(v*255 for v in data))
            if side=='back':
                mask=mask.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            masks.append(mask)
        for low in (False,True):
            image=Image.new('RGB',(width,height),(54,28,81))
            image.paste((70,40,96) if low else (121,82,155),mask=masks[0])
            image.paste((217,179,91),mask=masks[1])
            image.paste((244,240,247),mask=masks[2])
            path=output/(side+('_low_contrast' if low else '')+'.png')
            image.save(path)
            files.append(str(path.resolve()))
    return {'files':files,'meaning':'layer-derived material schematic, not calibrated factory color'}


GERBERS=dict(zip(LAYERS,(
    ('F_Cu.gtl','Copper,L1,Top'),('F_Mask.gts','Soldermask,Top'),('F_SilkS.gto','Legend,Top'),
    ('B_Cu.gbl','Copper,L2,Bot'),('B_Mask.gbs','Soldermask,Bot'),('B_SilkS.gbo','Legend,Bot'))))


def coordinate(x,y,operation):
    return f'X{round(x*1e6)}Y{round(y*1e6)}D{operation:02d}*\n'


def verify_rectangles(path,plan,layer):
    # Independent parser is optional for imports/previews, mandatory for a verified Gerber draft.
    from gerbonara import GerberFile
    expected=raster_for_layer(plan,layer)
    restored=bytearray(len(expected))
    width,height=plan['canvas_px']
    px,py=plan['pixel_mm']
    gerber=GerberFile.open(path)
    for obj in gerber.objects:
        for primitive in obj.to_primitives():
            if not hasattr(primitive,'outline') or any(primitive.arc_centers):
                raise ValueError('Unexpected non-rectangular Gerber primitive')
            xs=sorted(set(round(p[0],6) for p in primitive.outline))
            ys=sorted(set(round(p[1],6) for p in primitive.outline))
            if len(xs)!=2 or len(ys)!=2:
                raise ValueError('Unexpected Gerber contour')
            x0,x1=round(xs[0]/px),round(xs[1]/px)
            y0,y1=round(-ys[1]/py),round(-ys[0]/py)
            if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                raise ValueError('Gerber geometry outside input canvas')
            value=b'\x01' if primitive.polarity_dark else b'\x00'
            for y in range(y0,y1):
                restored[y*width+x0:y*width+x1]=value*(x1-x0)
    difference=sum(a!=b for a,b in zip(expected,restored))
    if difference:
        raise ValueError(f'{layer}: {difference} pixels changed after independent Gerber parse')
    return {'pixel_difference':0,'objects':len(gerber.objects),'bbox_mm':gerber.bounding_box()}


def export_gerber(manifest,output):
    from gerbonara import GerberFile
    plan=load_masks(manifest)
    if max(plan['width_mm'],plan['height_mm'])>=9999:
        raise ValueError('Board exceeds Gerber 4.6 coordinate format')
    output.mkdir(parents=True,exist_ok=False)
    report={'status':'building','generator':'local deterministic masks exporter; not EDA exporter',
            'back_mirror':'once about board width','pixel_mm':plan['pixel_mm'],'layers':{},
            'not_verified':['minimum feature widths','mask bridges','manufacturer CAM','physical appearance']}
    atomic_json(output/'validation.json',report)
    try:
        for layer,(filename,function) in GERBERS.items():
            path=output/filename
            with path.open('w',encoding='ascii',newline='\n') as file:
                file.write(f'G04 PCB art DRAFT*\n%TF.FileFunction,{function}*%\n%FSLAX46Y46*%\n%MOMM*%\n%LPD*%\nG01*\n')
                for shape in plan['shapes']:
                    if shape['layer']!=layer:
                        continue
                    x,y,w,h=shape['rect_mm']
                    if layer.startswith('back_'):
                        x=plan['width_mm']-x-w
                    file.write('G36*\n'+coordinate(x,-y,2))
                    for sx,sy in ((x+w,y),(x+w,y+h),(x,y+h),(x,y)):
                        file.write(coordinate(sx,-sy,1))
                    file.write('G37*\n')
                file.write('M02*\n')
            result=verify_rectangles(path,plan,layer)
            result['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            report['layers'][layer]=result
        path=output/'Edge_Cuts.gko'
        with path.open('w',encoding='ascii',newline='\n') as file:
            file.write('G04 Rectangular board outline*\n%TF.FileFunction,Profile,NP*%\n%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.100000*%\n%LPD*%\nG01*\nD10*\n'+coordinate(0,0,2))
            for x,y in ((plan['width_mm'],0),(plan['width_mm'],-plan['height_mm']),(0,-plan['height_mm']),(0,0)):
                file.write(coordinate(x,y,1))
            file.write('M02*\n')
        outline=GerberFile.open(path)
        # Check centerline coordinates, continuity and closure using the independent parser.
        expected_edges=[(0,0,plan['width_mm'],0),(plan['width_mm'],0,plan['width_mm'],-plan['height_mm']),
                        (plan['width_mm'],-plan['height_mm'],0,-plan['height_mm']),(0,-plan['height_mm'],0,0)]
        actual_edges=[(line.x1,line.y1,line.x2,line.y2) for line in outline.objects]
        if len(actual_edges)!=4 or any(abs(a-b)>1e-6 for actual,expected in zip(actual_edges,expected_edges) for a,b in zip(actual,expected)):
            raise ValueError('Outline is not the expected closed rectangle')
        report['status']='independent-gerber-mask-roundtrip-passed'
        report['outline']={'centerline_mm':[plan['width_mm'],plan['height_mm']],'segments':4}
        notes='DRAFT: CAM and physical validation required.\nTwo copper layers, rectangular outline, no drills.\nBack layers mirrored once; do not mirror again.\nFinish, mask color, thickness and silk color are order settings.\nRaster grid does not qualify minimum feature size.\n'
        (output/'FABRICATION_NOTES.txt').write_text(notes,encoding='utf-8')
        atomic_json(output/'validation.json',report)
        archive=output/'Gerber_DRAFT.zip'
        names=[filename for filename,_ in GERBERS.values()]+['Edge_Cuts.gko','FABRICATION_NOTES.txt']
        with ZipFile(archive,'w',ZIP_DEFLATED) as zipped:
            for name in names:
                zipped.write(output/name,name)
        with ZipFile(archive) as zipped:
            if zipped.testzip() is not None or any(zipped.read(name)!=(output/name).read_bytes() for name in names):
                raise ValueError('Packaged files differ from verified files')
        return {'archive':str(archive.resolve()),'validation':str((output/'validation.json').resolve()),'status':report['status']}
    except Exception as error:
        report['status']='failed'
        report['error']=str(error)
        atomic_json(output/'validation.json',report)
        raise


def export_native(base,window,output):
    if output.suffix.lower()!='.epro2':
        raise ValueError('Native output must have .epro2 extension')
    if output.exists():
        raise FileExistsError('Native file exists; use a versioned filename')
    info=execute(base,window,'return await eda.dmt_SelectControl.getCurrentDocumentInfo();')
    if not info or info['documentType']!=3:
        raise ValueError('Focus the intended PCB first')
    code=guard(info['uuid'])+'const file=await eda.sys_FileManager.getDocumentFile("pcb-art",undefined,"epro2");if(!file||file.size>50000000)throw new Error("Missing native file or larger than 50 MB; export manually");return {bytes:Array.from(new Uint8Array(await file.arrayBuffer()))};'
    result=execute(base,window,code)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as file:
        file.write(bytes(result['bytes']))
    with ZipFile(output) as zipped:
        if zipped.testzip() is not None or 'project2.json' not in zipped.namelist():
            raise ValueError('Unexpected native archive format')
    return {'file':str(output.resolve()),'document':info,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pcb_art import load_masks, make_demo
from image_backend import check_readback, import_images, normalized_svg_raster, payload_for_layer, raster_for_layer
from export_tools import export_gerber, preview


def svg_readback(plan,layer):
    paths=[]
    for item in plan['shapes']:
        if item['layer']!=layer:
            continue
        x,y,w,h=item['rect_mm']
        if layer.startswith('back_'):
            x=plan['width_mm']-x-w
        paths.append('M '+ ' L '.join([f'{x/.254} {y/.254}',f'{(x+w)/.254} {y/.254} {(x+w)/.254} {(y+h)/.254} {x/.254} {(y+h)/.254} {x/.254} {y/.254}']))
    return [' '.join(paths)]


class ImageBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        make_demo(self.folder)
        self.manifest=self.folder/'manifest.json'
        self.plan=load_masks(self.manifest)

    def test_image_anchor_mirrors_asymmetric_back_once(self):
        for layer in ('front_mask_open','back_mask_open'):
            payload=payload_for_layer(self.plan,layer)
            first=self.plan['shapes'][next(i for i,s in enumerate(self.plan['shapes']) if s['layer']==layer)]['rect_mm']
            expected=first[0] if layer.startswith('front') else self.plan['width_mm']-first[0]
            self.assertAlmostEqual(payload['x_mm'],expected)
            self.assertLess(payload['sources'][0][8],0)
            self.assertEqual(payload['sources'][0][:2],payload['sources'][0][-2:])

    def test_normalized_native_readback_all_six_layers(self):
        for layer in ('front_copper','front_silk','front_mask_open','back_copper','back_silk','back_mask_open'):
            payload=payload_for_layer(self.plan,layer)
            actual={'layer':payload['layer'],'x':payload['x_mm']/.0254,'y':payload['y_mm']/.0254,
                    'width':payload['width_mm']/.0254,'height':payload['height_mm']/.0254,'mirror':False,'rotation':0,
                    'sources':svg_readback(self.plan,layer)}
            self.assertEqual(check_readback(actual,payload,self.plan,layer)['pixel_difference'],0)
            actual['x']+=10
            with self.assertRaisesRegex(ValueError,'position'):
                check_readback(actual,payload,self.plan,layer)

    def test_wrong_back_mirror_is_detected(self):
        source=svg_readback(self.plan,'front_mask_open')
        restored=normalized_svg_raster(source,self.plan)
        self.assertNotEqual(restored,raster_for_layer(self.plan,'back_mask_open'))

    def test_unknown_svg_and_outside_geometry_stop(self):
        for source in [['M 0 0 C 1 1 2 2 3 3'],['M -2 0 L -1 0 -1 1 -2 1 -2 0'],['M 0 0 L 1 1 1 0 0 1 0 0']]:
            with self.assertRaises(ValueError):
                normalized_svg_raster(source,self.plan)

    def test_color_and_transparent_input_rejected(self):
        for mode,color in [('RGB',(255,255,254)),('RGBA',(0,0,0,0))]:
            Image.new(mode,(120,160),color).save(self.folder/'front_copper.png')
            with self.assertRaises(ValueError):
                load_masks(self.manifest)

    def test_preview_preserves_normal_back_view(self):
        result=preview(self.manifest,self.folder/'preview')
        self.assertEqual(len(result['files']),4)
        image=Image.open(self.folder/'preview'/'back.png')
        # The demo's asymmetric white back marker is on the right in normal viewing.
        self.assertEqual(image.getpixel((98,137)),(244,240,247))
        self.assertNotEqual(image.getpixel((20,137)),(244,240,247))
        with self.assertRaises(FileExistsError):
            preview(self.manifest,self.folder/'preview')

    def test_gerber_roundtrip_zip_and_empty_layer(self):
        spec=json.loads(self.manifest.read_text())
        del spec['layers']['back_silk']
        self.manifest.write_text(json.dumps(spec))
        result=export_gerber(self.manifest,self.folder/'gerber')
        report=json.loads(Path(result['validation']).read_text())
        self.assertEqual(report['status'],'independent-gerber-mask-roundtrip-passed')
        self.assertEqual(report['layers']['back_silk']['objects'],0)
        self.assertTrue(all(v['pixel_difference']==0 for v in report['layers'].values()))
        self.assertEqual(report['outline']['centerline_mm'],[30,40])
        with self.assertRaises(FileExistsError):
            export_gerber(self.manifest,self.folder/'gerber')

    def test_timeout_marks_unknown_state_and_does_not_retry(self):
        receipt=self.folder/'receipt.json'
        def fake_execute(base,window,code):
            if code.startswith('return await eda.dmt_SelectControl'):
                return {'uuid':'test','documentType':3}
            raise TimeoutError('injected timeout')
        with patch('image_backend.execute',side_effect=fake_execute) as execute:
            with self.assertRaises(TimeoutError):
                import_images(self.manifest,'http://127.0.0.1:49620','test-window',receipt)
            self.assertEqual(execute.call_count,2)
        result=json.loads(receipt.read_text())
        self.assertEqual(result['status'],'incomplete-inspect-before-retry')
        self.assertEqual(result['pending'],'empty-check-and-outline')


if __name__=='__main__':
    unittest.main()

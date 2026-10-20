"""Screen copy survives picture changes without qualifying physical product coverage."""
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import frappe
from PIL import Image
from joymedia.services.keyframes.overlay import lock_products_in_video


class TestScreenArtwork(TestCase):
    def test_screen_copy_stays_visible_for_every_frame_of_a_changing_picture(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, output, art = folder/'source.mp4', folder/'output.mp4', folder/'copy.png'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                "nullsrc=s=128x128:r=24,geq=lum='if(lt(T,0.5),32,220)':cb=128:cr=128",
                '-t','1','-pix_fmt','yuv420p',str(source)],check=True)
            Image.new('RGBA',(32,32),(255,0,0,255)).save(art)
            lock={'canvas':[128,128],'items':[{'box':[32,32,32,32],
                'file':'/private/files/copy.png','coordinate_space':'screen','kind':'typography'}]}
            with patch('joymedia.services.keyframes.overlay.frappe.get_doc',
                return_value=frappe._dict(get_full_path=lambda:str(art))):
                self.assertIsNotNone(lock_products_in_video(source,lock,output,24))
            import cv2
            cap=cv2.VideoCapture(str(output));count=0
            while True:
                ok,frame=cap.read()
                if not ok:break
                b,g,r=map(int,frame[48,48]);self.assertGreater(r,220);self.assertLess(b+g,35);count+=1
            cap.release();self.assertEqual(24,count)

    def test_physical_artwork_cannot_be_declared_screen_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                'color=c=white:s=128x128:r=24','-t','0.1',str(source)],check=True)
            art=Path(directory)/'patch.png';Image.new('RGBA',(32,32),'red').save(art)
            with patch('joymedia.services.keyframes.overlay.frappe.get_doc', return_value=frappe._dict(get_full_path=lambda:str(art))), self.assertRaisesRegex(ValueError,'typography'):
                lock_products_in_video(source,{'canvas':[128,128],'items':[
                    {'box':[0,0,32,32],'file':'/private/files/patch.png','coordinate_space':'screen','kind':'product'}]},Path(directory)/'out.mp4',24)

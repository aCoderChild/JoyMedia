"""Reference retention must survive stage boundaries without phantom anchors."""
import json
from unittest.mock import patch
import frappe
from frappe.tests.utils import FrappeTestCase
from joymedia.patches.register_ref2va_pipeline import register_video
from joymedia.services.generation.preparation import video_reference_inputs
from joymedia.services.workflows.resolver import build_execution_workflow


class TestRef2VA(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.workflow = frappe.get_doc('Generation Workflow', register_video())

    def graph(self, **inputs):
        return build_execution_workflow(self.workflow,
            inputs={'generation_prompt': 'The subject demonstrates its product.', 'first_frame': ['opening.png'], **inputs},
            seed=42, width=720, height=1280, fps=24, frame_count=96, output_prefix='ref-test')

    def test_product_is_separate_reference_and_opening_stays_anchored(self):
        graph = self.graph(product=['original-product.png'])
        self.assertEqual('original-product.png', graph['product']['inputs']['image'])
        self.assertEqual(['product', 0], graph['104']['inputs']['ref_images.ref_image_1'])
        self.assertEqual(['114', 0], graph['104']['inputs']['ref_images.ref_image_0'])
        self.assertEqual(['114', 0], graph['guide_first']['inputs']['image'])
        self.assertEqual(0, graph['guide_first']['inputs']['frame_idx'])
        self.assertEqual(['guide_first', 0], graph['16']['inputs']['conditioning'])
        self.assertIn('<Picture 2>', graph['104']['inputs']['prompt'])
        self.assertEqual((768, 1344), (graph['104']['inputs']['width'], graph['104']['inputs']['height']))
        self.assertEqual('MiniMaxH3ReferenceToVideo', graph['104']['class_type'])
        self.assertIn('ref2va', graph['6']['inputs']['unet_name'])
        self.assertNotIn('guide_last', graph)

    def test_no_product_has_no_second_picture_or_invented_last_frame(self):
        graph = self.graph()
        self.assertIsNone(graph['104']['inputs']['ref_images.ref_image_1'])
        self.assertNotIn('<Picture 2>', graph['104']['inputs']['prompt'])
        self.assertNotIn('guide_last', graph)
        self.assertNotIn('115', graph)

    def test_only_explicit_last_frame_adds_an_endpoint_guide(self):
        graph = self.graph(last_frame=['endpoint.png'])
        self.assertEqual('endpoint.png', graph['115']['inputs']['image'])
        self.assertEqual(-1, graph['guide_last']['inputs']['frame_idx'])
        self.assertEqual(['guide_first', 0], graph['guide_last']['inputs']['positive'])
        self.assertEqual(['guide_last', 0], graph['16']['inputs']['conditioning'])

    def test_later_stage_preserves_original_asset_but_never_overrides_chained_frames(self):
        shot={'references': [
            {'reference_role': 'Product', 'asset_version': 'ORIGINAL'},
            {'reference_role': 'Product', 'asset_version': 'ORIGINAL'},
            {'reference_role': 'first_frame', 'asset_version': 'OLD-OPENING'},
            {'reference_role': 'last_frame', 'asset_version': 'ENDPOINT'},
            {'reference_role': 'Character', 'asset_version': 'ACTOR'},
        ]}
        self.assertEqual({'product': ['ORIGINAL']}, video_reference_inputs(shot, self.workflow))
        # Existing I2V workflows receive no undeclared references.
        original=frappe._dict(name='I2V',bindings=[frappe._dict(required_input_role='first_frame',required=1,value_type='File Path',accepted_media_type='Image',allow_multiple=0)])
        self.assertEqual({}, video_reference_inputs(shot, original))

    def test_multiple_different_products_fail_instead_of_silently_losing_one(self):
        shot={'references':[{'reference_role':'Product','asset_version':value} for value in ('A','B')]}
        with self.assertRaises(frappe.ValidationError):
            video_reference_inputs(shot,self.workflow)

    def test_registration_is_idempotent_and_does_not_promote(self):
        from joymedia.services.workflows.pipeline import get_active_generation_pipeline
        previous=get_active_generation_pipeline().name
        self.assertEqual(self.workflow.name,register_video())
        self.assertEqual(previous,get_active_generation_pipeline().name)

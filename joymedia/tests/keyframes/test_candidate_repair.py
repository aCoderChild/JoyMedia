"""Saved inference can be repaired only after action admission and source access."""
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock,patch
import frappe
from joymedia.services.consistency import repair

class TestCandidateRepairAccess(TestCase):
 def test_foreign_or_stale_scene_never_queues_work(self):
  for owner,take in [('OTHER','OLD'),('OWN','NEW')]:
   project=Mock();project.name='OWN'
   with patch.object(frappe,'get_doc',side_effect=[project,frappe._dict(media_project=owner,selected_output_asset_version=take)]),patch.object(frappe,'throw',side_effect=ValueError),patch.object(frappe,'enqueue') as queue:
    with self.assertRaises(ValueError):repair.queue_candidate_artwork_repair('OWN','SHOT','ATT','OLD')
    queue.assert_not_called();project._require_write_access.assert_called_once()
 def test_failed_action_or_unfinished_inference_cannot_be_repaired_away(self):
  for completed,report in [(False,None),(True,{'status':'Needs Review','review_only':False})]:
   project=Mock();project.name='OWN'
   docs=[project,frappe._dict(name='SHOT',media_project='OWN',selected_output_asset_version='OLD'),frappe._dict(name='ATT',generation_task='TASK',status='Completed' if completed else 'Failed'),frappe._dict(shot='SHOT',status='Completed',generation_run='RUN')]
   if completed:docs.append(frappe._dict(name='RUN'))
   with patch.object(frappe,'get_doc',side_effect=docs),patch.object(frappe,'throw',side_effect=ValueError),patch('joymedia.services.review.admission.report_for',return_value=report),patch.object(frappe,'enqueue') as queue:
    with self.assertRaises(ValueError):repair.queue_candidate_artwork_repair('OWN','SHOT','ATT','OLD')
    queue.assert_not_called()
 def test_unversioned_patch_is_held_instead_of_guessed(self):
  with tempfile.TemporaryDirectory() as directory,patch('subprocess.check_output',return_value=b'{"streams":[{"width":320,"height":240}]}'):
   output=Path(directory)/'output.mp4'
   with self.assertRaisesRegex(ValueError,'immutable artwork'):
    repair.track_product_lock('video',{'canvas':[320,240],'items':[{'file':'unknown','box':[0,0,20,20]}]},output,Mock())
   self.assertFalse(output.exists())
 def test_same_tracker_handles_different_canvas_sizes_with_complete_coverage(self):
  from joymedia.tests.keyframes.test_tracking import TestTrackedSourceArt
  for scale in [1,2]:
   with tempfile.TemporaryDirectory() as directory:
    folder=Path(directory);video,art,_=TestTrackedSourceArt().fixture(folder);output=folder/'tracked.mp4'
    lock={'canvas':[320*scale,240*scale],'items':[{'box':[40*scale,30*scale,200*scale,160*scale],'file':'patch','patch_asset_version':'PATCH'}]}
    with patch.object(repair,'_project_asset_path',return_value=art),patch.object(frappe,'get_doc',return_value=frappe._dict(file='patch')):
     cert=repair.track_product_lock(video,lock,output,Mock())
    self.assertEqual(24,cert[0]['protected_frames']);self.assertEqual('tracked_source_plane',cert[0]['strategy']);self.assertTrue(output.exists())
 def test_uncertain_geometry_is_candidate_only_and_report_is_not_rewritten(self):
  import copy
  report={'status':'Needs Review','review_only':False,'results':[{'id':'authored_action','dimension':'action','verdict':'supported'},{'id':'cast','dimension':'cast','verdict':'supported'},{'id':'paw','dimension':'physics','verdict':'uncertain'}]};old=copy.deepcopy(report)
  self.assertTrue(repair.repair_review_candidate(report));self.assertEqual(old,report)
  for dim,verdict in [('action','uncertain'),('cast','uncertain'),('physics','violated')]:
   bad=copy.deepcopy(report);bad['results'].append({'id':'bad','dimension':dim,'verdict':verdict});self.assertFalse(repair.repair_review_candidate(bad))
  self.assertFalse(repair.repair_review_candidate({'status':'Not Checked'}))

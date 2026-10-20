import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import TestCase, skipIf

try:
	import cv2
	import numpy as np
except ImportError:
	cv2 = np = None

from joymedia.services.consistency.tracking import (
	PreservationError,
	_features,
	quad,
	restore_video,
	track_homography,
)


@skipIf(cv2 is None, "Install the tracking extra to run encoded-video restoration tests")
class TestTrackedSourceArt(TestCase):
	def test_fixed_composition_is_explicit_and_does_not_claim_tracking_evidence(self):
		from unittest.mock import patch

		with tempfile.TemporaryDirectory() as directory:
			folder = Path(directory)
			video, art, controls = self.fixture(folder)
			controls.pop("tracking_quad")
			with patch(
				"joymedia.services.consistency.tracking.track_homography",
				side_effect=AssertionError("must not track"),
			):
				report = restore_video(video, art, folder / "fixed.mp4", tracking_mode="fixed", **controls)
			self.assertEqual("fixed_source_plane", report["strategy"])
			self.assertEqual(24, report["protected_frames"])
			self.assertIsNone(report["maximum_reprojection_error"])
			self.assertIsNone(report["tracking_quad"])
			with self.assertRaises(PreservationError):
				restore_video(
					video,
					art,
					folder / "invalid.mp4",
					tracking_mode="fixed",
					tracking_quad=controls["target_quad"],
					**controls,
				)

	def test_stationary_scene_matte_keeps_rigid_edges_continuous_and_action_visible(self):
		with tempfile.TemporaryDirectory() as directory:
			folder = Path(directory)
			video, art, _ = self.fixture(folder)
			image = np.full((240, 320, 4), (90, 120, 150, 255), np.uint8)
			image[180:190, :, :3] = (20, 50, 220)  # a rigid edge spanning the scene
			image[40:120, 100:200, 3] = 0  # only the acting region is unconstrained
			cv2.imwrite(str(art), image)
			points = [[0, 0], [319, 0], [319, 239], [0, 239]]
			output = folder / "stationary-scene.mp4"
			report = restore_video(
				video, art, output, source_quad=points, target_quad=points, tracking_mode="fixed"
			)
			self.assertEqual(24, report["protected_frames"])
			cap = cv2.VideoCapture(str(output))
			action = []
			while True:
				ok, frame = cap.read()
				if not ok:
					break
				self.assertLess(
					float(np.abs(frame[182:188, 4:315].astype(float) - image[182:188, 4:315, :3]).mean()), 5
				)
				action.append(frame[50:110, 110:190].astype(float))
			cap.release()
			self.assertEqual(24, len(action))
			self.assertGreater(float(np.abs(action[-1] - action[0]).mean()), 5)

	def fixture(self, folder, *, lost=False, mask=False):
		video, art = folder / "input.mp4", folder / "art.png"
		rng = np.random.default_rng(817)
		anchor = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
		writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 24, (320, 240))
		for i in range(24):
			matrix = np.float32([[1, 0, i / 2], [0, 1, i / 4]])
			frame = cv2.warpAffine(anchor, matrix, (320, 240))
			if lost and i == 12:
				frame[:] = 0
			if mask:
				frame[85:110, 105:135] = (0, 255, 0)
			writer.write(frame)
		writer.release()
		image = np.full((64, 96, 4), (20, 50, 220, 255), np.uint8)
		cv2.putText(image, "BRAND", (3, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255, 255), 2)
		cv2.imwrite(str(art), image)
		controls = dict(
			source_quad=[[0, 0], [95, 0], [95, 63], [0, 63]],
			target_quad=[[90, 70], [185, 70], [185, 133], [90, 133]],
			tracking_quad=[[40, 30], [240, 30], [240, 190], [40, 190]],
		)
		if mask:
			path = folder / "mask.mp4"
			writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, (320, 240))
			for _ in range(24):
				frame = np.zeros((240, 320, 3), np.uint8)
				frame[85:110, 105:135] = 255
				writer.write(frame)
			writer.release()
			controls["occlusion"] = path
		return video, art, controls

	def test_restores_all_frames_and_preserves_foreground_occlusion(self):
		with tempfile.TemporaryDirectory() as directory:
			folder = Path(directory)
			video, art, controls = self.fixture(folder, mask=True)
			output = folder / "output.mp4"
			report = restore_video(video, art, output, **controls)
			self.assertEqual(report["protected_frames"], 24)
			cap = cv2.VideoCapture(str(output))
			self.assertEqual(int(cap.get(7)), 24)
			for _ in range(24):
				ok, frame = cap.read()
				self.assertTrue(ok)
				self.assertGreater(float(frame[90:105, 110:130, 1].mean()), 210)
				self.assertGreater(float(frame[73:78, 95:170, 2].mean()), 150)
			cap.release()

	def test_track_loss_is_atomic_and_never_returns_the_generated_clip(self):
		with tempfile.TemporaryDirectory() as directory:
			folder = Path(directory)
			video, art, controls = self.fixture(folder, lost=True)
			output = folder / "output.mp4"
			with self.assertRaisesRegex(PreservationError, "Frame 12"):
				restore_video(video, art, output, **controls)
			self.assertFalse(output.exists())

	def test_cancellation_and_bad_masks_do_not_publish_outputs(self):
		with tempfile.TemporaryDirectory() as directory:
			folder = Path(directory)
			video, art, controls = self.fixture(folder)
			with self.assertRaisesRegex(PreservationError, "cancelled"):
				restore_video(video, art, folder / "cancelled.mp4", cancelled=lambda: True, **controls)
			with self.assertRaisesRegex(PreservationError, "Occlusion"):
				restore_video(video, art, folder / "mask.mp4", occlusion=art, **controls)
			self.assertFalse((folder / "cancelled.mp4").exists())
			self.assertFalse((folder / "mask.mp4").exists())

	def test_concurrent_repairs_use_independent_outputs(self):
		with tempfile.TemporaryDirectory() as directory:
			folder = Path(directory)
			video, art, controls = self.fixture(folder)
			with ThreadPoolExecutor(max_workers=2) as pool:
				jobs = [
					pool.submit(restore_video, video, art, folder / f"{i}.mp4", **controls) for i in range(2)
				]
				self.assertTrue(all(job.result()["protected_frames"] == 24 for job in jobs))

	def test_invalid_regions_and_source_overwrites_are_rejected(self):
		for points in [
			[[0, 0]] * 4,
			[[0, 0], [20, 20], [20, 0], [0, 20]],
			[[0, 0], [20, 0], [20, float("nan")], [0, 20]],
		]:
			with self.assertRaises(PreservationError):
				quad(points, (32, 32))
		with tempfile.TemporaryDirectory() as directory:
			video, art, controls = self.fixture(Path(directory))
			with self.assertRaisesRegex(PreservationError, "replace"):
				restore_video(video, art, video, **controls)
			controls["source_quad"] = list(reversed(controls["source_quad"]))
			with self.assertRaisesRegex(PreservationError, "mirror"):
				restore_video(video, art, Path(directory) / "mirror.mp4", **controls)

	def test_surface_blending_uses_opencv_and_keeps_foreground_occlusion(self):
		with tempfile.TemporaryDirectory() as directory:
			folder = Path(directory)
			video, art, controls = self.fixture(folder, mask=True)
			output = folder / "seamless.mp4"
			report = restore_video(video, art, output, blend_mode="seamless", **controls)
			self.assertEqual(report["blend_mode"], "seamless")
			self.assertEqual(report["protected_frames"], 24)
			cap = cv2.VideoCapture(str(output))
			for _ in range(24):
				ok, frame = cap.read()
				self.assertTrue(ok)
				self.assertGreater(float(frame[90:105, 110:130, 1].mean()), 210)
			cap.release()
			with self.assertRaisesRegex(PreservationError, "blend mode"):
				restore_video(video, art, folder / "invalid.mp4", blend_mode="invented", **controls)

	def test_random_motion_is_measured_against_the_original_reference(self):
		rng = np.random.default_rng(1729)
		anchor = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
		polygon = quad([[50, 40], [260, 40], [260, 200], [50, 200]], (320, 240))
		features = _features(cv2.cvtColor(anchor, cv2.COLOR_BGR2GRAY), polygon)
		for _ in range(40):
			matrix = cv2.getRotationMatrix2D(
				(160, 120), float(rng.uniform(-5, 5)), float(rng.uniform(0.95, 1.05))
			)
			matrix[:, 2] += rng.uniform(-8, 8, 2)
			frame = cv2.warpAffine(anchor, matrix, (320, 240))
			measured, _quality = track_homography(features, frame, polygon)
			expected = cv2.transform(polygon[None, :, :], matrix)[0]
			actual = cv2.perspectiveTransform(polygon[None, :, :], measured)[0]
			self.assertLess(float(np.max(np.linalg.norm(expected - actual, axis=1))), 1)

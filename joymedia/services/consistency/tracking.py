"""Restore protected artwork using reference-anchored planar motion.

No model weights or vendor calls. Tracks are re-estimated against the original
frame, not accumulated. A missing/ambiguous track fails the job; unprotected
frames never silently escape as successful restoration. Non-planar subjects
need a different declared strategy rather than stretching a flat photograph.
"""

import hashlib
import json
import math
import subprocess
import tempfile
from pathlib import Path


class PreservationError(ValueError):
	pass


def file_hash(path):
	digest = hashlib.sha256()
	with open(path, "rb") as stream:
		for chunk in iter(lambda: stream.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def quad(value, size):
	import cv2
	import numpy as np

	points = np.asarray(value, dtype=np.float32)
	if points.shape != (4, 2) or not np.isfinite(points).all():
		raise PreservationError("A region requires four finite points in perimeter order.")
	if any(x < 0 or y < 0 or x >= size[0] or y >= size[1] for x, y in points):
		raise PreservationError("Region is outside the image.")
	if not cv2.isContourConvex(points) or abs(cv2.contourArea(points)) < 16:
		raise PreservationError("Region must be a convex polygon of at least 16 pixels.")
	return points


def _features(gray, polygon=None):
	import cv2
	import numpy as np

	mask = None
	if polygon is not None:
		mask = np.zeros(gray.shape, np.uint8)
		cv2.fillConvexPoly(mask, polygon.astype(np.int32), 255)
	return cv2.SIFT_create(nfeatures=1800).detectAndCompute(gray, mask)


def track_homography(anchor_features, frame, polygon, *, minimum_inliers=8):
	import cv2
	import numpy as np

	keypoints, descriptors = anchor_features
	current, features = _features(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
	if descriptors is None or features is None or len(current) < 2:
		raise PreservationError("No stable features for the protected region.")
	pairs = cv2.BFMatcher().knnMatch(descriptors, features, k=2)
	matches = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < 0.7 * pair[1].distance]
	if len(matches) < minimum_inliers:
		raise PreservationError("Protected region lost or insufficient unique features.")
	source = np.float32([keypoints[m.queryIdx].pt for m in matches])
	target = np.float32([current[m.trainIdx].pt for m in matches])
	matrix, mask = cv2.findHomography(source, target, cv2.RANSAC, 2.5)
	if matrix is None or mask is None or not np.isfinite(matrix).all():
		raise PreservationError("Protected-region transform is invalid.")
	inliers = mask.ravel().astype(bool)
	count = int(inliers.sum())
	if count < minimum_inliers or count / len(matches) < 0.6:
		raise PreservationError("Ambiguous protected-region tracking.")
	coverage = abs(cv2.contourArea(cv2.convexHull(source[inliers]))) / abs(cv2.contourArea(polygon))
	if coverage < 0.08:
		raise PreservationError("Tracking points do not span the protected surface.")
	projected = cv2.perspectiveTransform(source[inliers, None, :], matrix)[:, 0, :]
	error = float(np.median(np.linalg.norm(projected - target[inliers], axis=1)))
	if error > 2.5:
		raise PreservationError("Protected-region reprojection error is too large.")
	moved = cv2.perspectiveTransform(polygon[None, :, :], matrix)[0]
	area_ratio = abs(cv2.contourArea(moved)) / abs(cv2.contourArea(polygon))
	if not np.isfinite(moved).all() or not cv2.isContourConvex(moved) or not 0.1 <= area_ratio <= 10:
		raise PreservationError("Protected surface changed geometry or left the supported scale range.")
	# Reject mirrored planes; a logo must never be reflected to fit an invalid match.
	if cv2.contourArea(moved, oriented=True) * cv2.contourArea(polygon, oriented=True) <= 0:
		raise PreservationError("Protected surface was reflected.")
	return matrix, {"inliers": count, "matches": len(matches), "error": error}


def restore_video(
	video,
	artwork,
	output,
	*,
	source_quad,
	target_quad,
	tracking_quad=None,
	occlusion=None,
	visible_ranges=None,
	cancelled=None,
	maximum_frames=14400,
	blend_mode="source",
	tracking_mode="tracked",
):
	"""Write a restored MP4 only after every declared visible frame was protected.

	Artwork may be RGBA (a source-pixel matte) or opaque (a planar label). The
	optional occlusion video must match frame count, dimensions and rate, with
	white pixels denoting foreground objects. Visible ranges are inclusive and
	explicit; omission means every frame. Occlusion masks are authored controls,
	not evidence that a generative model obeyed an interaction.
	"""
	import cv2
	import numpy as np

	if not isinstance(blend_mode, str) or blend_mode not in {"source", "seamless"}:
		raise PreservationError("Unsupported surface blend mode.")
	if (
		not isinstance(tracking_mode, str)
		or tracking_mode not in {"tracked", "fixed"}
		or (tracking_mode == "fixed" and tracking_quad is not None)
	):
		raise PreservationError(
			"Choose tracked artwork or an explicitly fixed plane without tracking controls."
		)
	output = Path(output)
	if output.resolve() in {Path(video).resolve(), Path(artwork).resolve()}:
		raise PreservationError("Restoration output cannot replace a source file.")
	source_hashes = {
		"video": file_hash(video),
		"artwork": file_hash(artwork),
		"occlusion": file_hash(occlusion) if occlusion else None,
	}
	cap = cv2.VideoCapture(str(video))
	mask_cap = cv2.VideoCapture(str(occlusion)) if occlusion else None
	writer = None
	try:
		fps = cap.get(cv2.CAP_PROP_FPS)
		frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
		width, height = int(cap.get(3)), int(cap.get(4))
		if (
			not math.isfinite(fps)
			or fps <= 0
			or frames < 1
			or frames > maximum_frames
			or width < 2
			or height < 2
		):
			raise PreservationError("Invalid or over-budget source video.")
		if width * height > 4096 * 4096:
			raise PreservationError("Video exceeds the restoration pixel budget.")
		if width * height * frames > 2_000_000_000:
			raise PreservationError(
				"Video exceeds the total restoration frame-pixel budget; split the scene."
			)
		if mask_cap and (
			int(mask_cap.get(7)) != frames
			or int(mask_cap.get(3)) != width
			or int(mask_cap.get(4)) != height
			or abs(mask_cap.get(5) - fps) > 0.01
		):
			raise PreservationError("Occlusion mask must match video dimensions, rate and frames.")
		ranges = visible_ranges if visible_ranges is not None else [[0, frames - 1]]
		if not ranges or any(
			len(r) != 2 or any(type(x) is not int for x in r) or r[0] < 0 or r[1] < r[0] or r[1] >= frames
			for r in ranges
		):
			raise PreservationError("Visible ranges must be valid inclusive frame intervals.")
		from PIL import Image

		with Image.open(artwork) as header:
			if header.width * header.height > 4096 * 4096:
				raise PreservationError("Artwork exceeds the restoration pixel budget.")
		art = cv2.imread(str(artwork), cv2.IMREAD_UNCHANGED)
		if art is None or art.ndim != 3 or art.shape[2] not in (3, 4):
			raise PreservationError("Artwork must be an RGB or RGBA image.")
		source = quad(source_quad, (art.shape[1], art.shape[0]))
		target = quad(target_quad, (width, height))
		if cv2.contourArea(source, oriented=True) * cv2.contourArea(target, oriented=True) <= 0:
			raise PreservationError("Source and target corner order would mirror the artwork.")
		region = quad(tracking_quad if tracking_quad is not None else target_quad, (width, height))
		base_transform = cv2.getPerspectiveTransform(source, target)
		ok, first = cap.read()
		if not ok:
			raise PreservationError("Cannot decode the source video.")
		anchor = (
			_features(cv2.cvtColor(first, cv2.COLOR_BGR2GRAY), region) if tracking_mode == "tracked" else None
		)
		alpha = (
			art[:, :, 3].astype(np.float32) / 255 if art.shape[2] == 4 else np.ones(art.shape[:2], np.float32)
		)
		# Only the selected source plane may be painted, even for an opaque photograph.
		plane = np.zeros(art.shape[:2], np.uint8)
		cv2.fillConvexPoly(plane, source.astype(np.int32), 1)
		alpha *= plane
		if not np.any(alpha):
			raise PreservationError("Artwork plane is completely transparent.")
		protected, errors = 0, []
		with tempfile.TemporaryDirectory(prefix="joymedia-preserve-", dir=output.parent) as directory:
			plain = Path(directory) / "restored.mkv"
			writer = cv2.VideoWriter(str(plain), cv2.VideoWriter_fourcc(*"FFV1"), fps, (width, height))
			if not writer.isOpened():
				raise PreservationError("Cannot open the restoration encoder.")
			frame = first
			for index in range(frames):
				if cancelled and cancelled():
					raise PreservationError("Restoration cancelled.")
				if index:
					ok, frame = cap.read()
					if not ok:
						raise PreservationError(f"Video truncated at frame {index}.")
				foreground = None
				if mask_cap:
					ok, foreground = mask_cap.read()
					if not ok:
						raise PreservationError(f"Occlusion mask truncated at frame {index}.")
				if any(start <= index <= end for start, end in ranges):
					try:
						matrix, quality = (
							track_homography(anchor, frame, region)
							if index and tracking_mode == "tracked"
							else (np.eye(3), {"error": 0})
						)
						transform = matrix @ base_transform
						paint = cv2.warpPerspective(art[:, :, :3], transform, (width, height))
						opacity = cv2.warpPerspective(alpha, transform, (width, height))
						if not np.any(opacity > 0.1):
							raise PreservationError("Protected region is outside the frame.")
						if foreground is not None:
							opacity *= (
								1 - cv2.cvtColor(foreground, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
							)
						from joymedia.services.consistency.surfaces import blend_surface

						frame = blend_surface(frame, paint, opacity, mode=blend_mode)
						protected += 1
						errors.append(quality["error"])
					except PreservationError as exc:
						raise PreservationError(f"Frame {index}: {exc}") from exc
				writer.write(frame)
			writer.release()
			writer = None
			muxed = Path(directory) / "delivery.mp4"
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-y",
					"-i",
					str(plain),
					"-i",
					str(video),
					"-map",
					"0:v:0",
					"-map",
					"1:a?",
					"-c:v",
					"libx264",
					"-crf",
					"16",
					"-pix_fmt",
					"yuv420p",
					"-c:a",
					"copy",
					"-frames:v",
					str(frames),
					"-movflags",
					"+faststart",
					str(muxed),
				],
				check=True,
				capture_output=True,
				timeout=600,
			)
			if source_hashes != {
				"video": file_hash(video),
				"artwork": file_hash(artwork),
				"occlusion": file_hash(occlusion) if occlusion else None,
			}:
				raise PreservationError("A source file changed during restoration; result was not published.")
			muxed.replace(output)
		return {
			"version": 1,
			"strategy": "tracked_source_plane" if tracking_mode == "tracked" else "fixed_source_plane",
			"blend_mode": blend_mode,
			"source_video_sha256": source_hashes["video"],
			"artwork_sha256": source_hashes["artwork"],
			"output_sha256": file_hash(output),
			"frames": frames,
			"protected_frames": protected,
			"visible_ranges": ranges,
			"maximum_reprojection_error": max(errors) if tracking_mode == "tracked" else None,
			"source_quad": source.tolist(),
			"target_quad": target.tolist(),
			"tracking_quad": region.tolist() if tracking_mode == "tracked" else None,
			"occlusion_sha256": source_hashes["occlusion"],
		}
	finally:
		cap.release()
		if mask_cap:
			mask_cap.release()
		if writer:
			writer.release()

"""Shared OpenCV surface compositing for still-image and tracked-video repairs."""


def blend_surface(frame, paint, opacity, *, mode="source"):
	"""Project only the supplied mask; Poisson blending is an explicit colour choice."""
	import cv2
	import numpy as np

	from joymedia.services.consistency.tracking import PreservationError

	if mode not in {"source", "seamless"}:
		raise PreservationError("Unsupported surface blend mode.")
	if frame.shape != paint.shape or opacity.shape != frame.shape[:2]:
		raise PreservationError("Surface paint and opacity must match the receiving frame.")
	if not np.isfinite(opacity).all() or np.any(opacity < 0) or np.any(opacity > 1):
		raise PreservationError("Surface opacity must be finite and between zero and one.")
	if mode == "seamless":
		mask = (opacity > 0.01).astype(np.uint8) * 255
		mask[[0, -1], :] = 0
		mask[:, [0, -1]] = 0
		x, y, width, height = cv2.boundingRect(mask)
		if width < 3 or height < 3:
			raise PreservationError("Surface blend has no usable visible region.")
		paint = cv2.seamlessClone(paint, frame, mask, (x + width // 2, y + height // 2), cv2.NORMAL_CLONE)
	alpha = opacity[:, :, None]
	return np.clip(frame * (1 - alpha) + paint * alpha, 0, 255).astype(np.uint8)

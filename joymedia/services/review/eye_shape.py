"""Measure a character's eye drawing instead of asking a vision model to name it.

The vision model repeatedly called a mascot's open dot eyes "closed smiling
arcs", so pose generation was told to close them and the closed result passed.
The eyes of a stylised character are small near-black marks above its nose: an
open dot is a filled, roughly round blob; a closed arc is a thin stroke much
wider than tall.
"""

import cv2
import numpy as np

DARK = 70  # 8-bit grey level below which a pixel is an inked mark
HEAD_FRACTION = 0.5  # the eyes lie in the upper half of the character
MIN_MARK = 0.00002  # ignore specks smaller than this fraction of the picture


def _image(picture):
	if isinstance(picture, bytes | bytearray):
		data = bytes(picture)
	else:
		import frappe

		data = frappe.get_doc("File", {"file_url": picture}).get_content()
	return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)


def measured_eye_shape(picture):
	"""Return "open_dots", "closed_arcs" or None when no eye can be measured.

	Works on a character cutout or a character on a plain light background.
	"""
	try:
		image = _image(picture)
	except Exception:
		return None  # Unreadable here: the caller falls back to its other evidence.
	if image is None or image.ndim != 3:
		return None
	if image.shape[2] == 4:
		subject, colour = image[:, :, 3] > 128, image[:, :, :3]
	else:
		colour = image
		subject = cv2.cvtColor(colour, cv2.COLOR_BGR2GRAY) < 240
	ys = np.nonzero(subject)[0]
	if not len(ys):
		return None
	top, bottom = ys.min(), ys.max()
	marks = ((cv2.cvtColor(colour, cv2.COLOR_BGR2GRAY) < DARK) & subject).astype(np.uint8)
	marks[top + int(HEAD_FRACTION * (bottom - top)) :, :] = 0
	count, _, stats, centres = cv2.connectedComponentsWithStats(marks, 8)
	features = sorted(
		(
			(stats[i], centres[i])
			for i in range(1, count)
			if stats[i][cv2.CC_STAT_AREA] >= MIN_MARK * subject.size
		),
		key=lambda feature: -feature[0][cv2.CC_STAT_AREA],
	)
	if len(features) < 2:
		return None
	nose = features[0]  # the largest inked feature on the head
	nose_top = nose[1][1] - 0.2 * nose[0][cv2.CC_STAT_HEIGHT]
	eyes = [feature for feature in features[1:3] if feature[1][1] < nose_top]
	shapes = set()
	for stat, _ in eyes:
		width, height, area = stat[cv2.CC_STAT_WIDTH], stat[cv2.CC_STAT_HEIGHT], stat[cv2.CC_STAT_AREA]
		aspect, fill = width / height, area / (width * height)
		if aspect >= 1.6:
			shapes.add("closed_arcs")
		elif aspect <= 1.3 and fill >= 0.55:
			shapes.add("open_dots")
		else:
			return None
	return shapes.pop() if len(shapes) == 1 else None

"""Conservative opening-frame crop assessment using the existing vision client.

This is advisory grounding, not a pixel-accurate segmentation or camera proof.
Unknown, tight, or already cropped compositions do not authorize a camera move.
"""
import hashlib
import json
import math
import uuid
from pathlib import Path

QUESTION = '''Assess the framing of the PRIMARY PHYSICAL SUBJECTS in this image, including all product parts or material layers needed to understand the image. Do not include the room or plain backdrop in their bounds. Return JSON only: {"bbox_2d":[left,top,right,bottom],"complete":true,"reason":"short visible evidence"}. Use PIXEL coordinates of the image you received, covering ALL primary subject components together. complete is false if any required subject/component is cut by an image edge, or if you cannot establish completeness. Do not guess invisible boundaries.'''
VERSION = 1


def inspect_framing(shot):
	import frappe
	from joymedia.services.review.consistency import ask, IMAGE_EDGE
	from joymedia.services.runtime.endpoints import endpoint, is_configured
	from PIL import Image
	import io

	unknown = {'version': VERSION, 'status': 'unknown', 'reason': 'No assessed opening frame.'}
	refs = [r.get('asset_version') for r in shot.get('references') or []
		if str(r.get('reference_role') or r.get('input_role') or '').lower() == 'first_frame' and r.get('asset_version')]
	if len(refs) != 1 or not is_configured('vision'):
		return unknown
	version = frappe.get_doc('Asset Version', refs[0])
	file = frappe.get_doc('File', {'file_url': version.file})
	data = Path(file.get_full_path()).read_bytes()
	digest = hashlib.sha256(data).hexdigest()
	configured = endpoint('vision')
	key = hashlib.sha256((digest + QUESTION + str(configured.model) + str(configured.get('revision') or '')).encode()).hexdigest()
	cache = Path(frappe.get_site_path('private', 'joymedia-camera', key + '.json'))
	if cache.exists():
		return json.loads(cache.read_text())
	try:
		answer = ask(data, QUESTION, configured=configured)
		with Image.open(io.BytesIO(data)) as image:
			image.thumbnail((IMAGE_EDGE, IMAGE_EDGE))
			sent_width, sent_height = image.size
		pixels = answer.get('bbox_2d')
		if not isinstance(pixels, list) or len(pixels) != 4 or any(type(v) not in (int, float) for v in pixels):
			raise ValueError('Unusable pixel bounds.')
		bounds = [v / dimension for v, dimension in zip(pixels, [sent_width, sent_height, sent_width, sent_height])]
		if (not isinstance(bounds, list) or len(bounds) != 4 or
			any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in bounds) or
			not (bounds[0] < bounds[2] and bounds[1] < bounds[3]) or type(answer.get('complete')) is not bool):
			raise ValueError('Unusable subject bounds.')
		report = {'version': VERSION, 'status': 'assessed', 'frame_sha256': digest,
			'asset_version': version.name, 'model': configured.model, 'bounds': bounds,
			**{k: answer[k] for k in ('complete', 'reason') if k in answer}}
	except Exception as exc:
		return {**unknown, 'frame_sha256': digest, 'reason': 'Framing could not be established: ' + str(exc)[:160]}
	cache.parent.mkdir(parents=True, exist_ok=True)
	temporary = cache.with_suffix('.' + uuid.uuid4().hex + '.tmp')
	temporary.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True))
	temporary.replace(cache)
	return report


def allows_push(report):
	if not report or report.get('status') != 'assessed' or report.get('complete') is not True:
		return False
	bounds = report.get('bounds') or []
	if len(bounds) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds):
		return False
	left, top, right, bottom = bounds
	return .08 <= left < right <= .92 and .08 <= top < bottom <= .92

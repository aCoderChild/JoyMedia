"""Optional generated transition bridges between selected scene takes."""

import tempfile
from itertools import pairwise
from pathlib import Path

import frappe

from joymedia.services.editing.queries import _latest_version_of
from joymedia.services.editing.rendering import (
	_extract_frame,
	_render_video,
	_save_output,
	_slug,
	_video_workflow,
)
from joymedia.services.planning.film_director import PERSON_PATTERN

BRIDGE_OVERLAP_FRAMES = 28


BRIDGE_FRAMES = BRIDGE_OVERLAP_FRAMES * 2


MIN_TAKE_REMAINDER_FRAMES = 24


def _insert_bridge(project_name, outgoing, incoming):
	"""Trim both takes by the overlap and put a generated bridge between them."""
	overlap = BRIDGE_OVERLAP_FRAMES
	for clip in (outgoing, incoming):
		if int(clip.source_out_frame) - int(clip.source_in_frame) - overlap < MIN_TAKE_REMAINDER_FRAMES:
			return
	cut_frame = int(incoming.timeline_start_frame)
	bridge_version = _bridge_asset_version(project_name, outgoing, incoming)

	_shift_clip(outgoing.name, source_out_delta=-overlap)
	_shift_clip(incoming.name, source_in_delta=overlap, start_delta=overlap)
	frappe.get_doc(
		{
			"doctype": "Timeline Clip",
			"media_project": project_name,
			"clip_order": int(outgoing.clip_order or 0),
			"track_type": "Video",
			"track_index": 0,
			"timeline_start_frame": cut_frame - overlap,
			"initial_timeline_start_frame": cut_frame - overlap,
			"enabled": 1,
			"source_asset_version": bridge_version,
			"source_in_frame": 0,
			"source_out_frame": BRIDGE_FRAMES,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": BRIDGE_FRAMES,
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}
	).insert(ignore_permissions=True)
	_renumber_video_clips(project_name)
	frappe.db.commit()


def _shift_clip(clip_name, source_in_delta=0, source_out_delta=0, start_delta=0):
	"""Move a video clip's range and keep its linked source audio aligned."""
	names = [
		clip_name,
		*frappe.get_all("Timeline Clip", filters={"linked_video_clip": clip_name}, pluck="name"),
	]
	for name in names:
		clip = frappe.get_doc("Timeline Clip", name)
		clip.source_in_frame = int(clip.source_in_frame) + source_in_delta
		clip.source_out_frame = int(clip.source_out_frame) + source_out_delta
		clip.timeline_start_frame = int(clip.timeline_start_frame) + start_delta
		clip.save(ignore_permissions=True)


def _renumber_video_clips(project_name):
	clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Video"},
		fields=["name"],
		order_by="timeline_start_frame asc, clip_order asc",
	)
	for order, clip in enumerate(clips, start=1):
		frappe.db.set_value("Timeline Clip", clip.name, "clip_order", order, update_modified=False)
		for audio in frappe.get_all("Timeline Clip", filters={"linked_video_clip": clip.name}, pluck="name"):
			frappe.db.set_value("Timeline Clip", audio, "clip_order", order, update_modified=False)


def _bridge_asset_version(project_name, outgoing, incoming):
	"""Return a cached bridge for these two takes, or render one."""
	asset_name = (
		f"{project_name} Transition {outgoing.source_asset_version}@{outgoing.source_out_frame}"
		f" > {incoming.source_asset_version}@{incoming.source_in_frame}"
	)
	cached = _latest_version_of(project_name, asset_name)
	if cached:
		return cached

	from joymedia.services.editing.export import _asset_version_path

	with tempfile.TemporaryDirectory(prefix="joymedia-bridge-") as temp_dir:
		temp_path = Path(temp_dir)
		first = temp_path / "first.png"
		last = temp_path / "last.png"
		# The bridge starts on the frame after the trimmed outgoing take and ends on
		# the frame before the trimmed incoming take.
		_extract_frame(
			_asset_version_path(outgoing.source_asset_version),
			int(outgoing.source_out_frame) - BRIDGE_OVERLAP_FRAMES,
			first,
		)
		_extract_frame(
			_asset_version_path(incoming.source_asset_version),
			int(incoming.source_in_frame) + BRIDGE_OVERLAP_FRAMES - 1,
			last,
		)
		workflow, output_node = _video_workflow(
			project_name,
			first,
			_bridge_prompt(outgoing.shot, incoming.shot),
			BRIDGE_FRAMES / 24,
			last_frame=last,
		)
		video_bytes = _render_video(project_name, workflow, output_node)
	return _save_output(project_name, asset_name, "Video", f"{_slug(asset_name)}.mp4", video_bytes)


def _bridge_prompt(outgoing_shot, incoming_shot):
	prompts = frappe.get_all(
		"Shot",
		filters={"name": ["in", [outgoing_shot, incoming_shot]]},
		fields=["name", "generation_prompt"],
	)
	by_name = {row.name: row.generation_prompt or "" for row in prompts}
	from_place, to_place = _shot_place(outgoing_shot), _shot_place(incoming_shot)
	journey = (
		f"flow smoothly from {from_place} to {to_place}"
		if from_place and to_place and from_place != to_place
		else "flow smoothly into the next moment"
	)
	movement = (
		"The person keeps moving gracefully while the camera glides with them, and the surroundings"
		if all(PERSON_PATTERN.search(by_name.get(shot, "")) for shot in (outgoing_shot, incoming_shot))
		else "The camera glides smoothly forward and the surroundings"
	)
	identity = (
		" Keep their face, hair and outfit identical."
		if PERSON_PATTERN.search(by_name.get(outgoing_shot, ""))
		else ""
	)
	return (
		"Seamless cinematic transition from the first frame to the last frame. "
		f"{movement} {journey} as a soft warm light sweeps "
		f"across the frame.{identity} One continuous shot with no cuts, smooth stabilized motion, "
		"photorealistic, no text, no deformation. Audio: a soft airy whoosh."
	)


def _shot_place(shot_name):
	"""Name of the place a take is set in (its last reference image), or None.

	A take whose last reference is a product, not a place, has no place name: a product
	called "1" must not become "the 1" in a transition prompt.
	"""
	from joymedia.services.planning.film_director import PLACE, _asset_version_context, classify_reference

	asset_version = frappe.db.get_value(
		"Shot Reference", {"parent": shot_name, "parenttype": "Shot"}, "asset_version", order_by="idx desc"
	)
	if not asset_version:
		return None
	project = frappe.db.get_value("Shot", shot_name, "media_project")
	reference = (
		frappe.db.get_value(
			"Project Reference",
			{"parent": project, "asset_version": asset_version},
			["reference_role", "label"],
			as_dict=True,
		)
		or {}
	)
	if classify_reference(_asset_version_context(asset_version, reference)) != PLACE:
		return None
	media_asset = frappe.db.get_value("Asset Version", asset_version, "media_asset")
	name = frappe.db.get_value("Media Asset", media_asset, "asset_name") if media_asset else None
	return f"the {name}" if name else None

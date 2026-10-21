"""Finishing lifecycle, cancellation and timeline reconciliation.

Stable HTTP and queued-job entry points remain here. Music, transition bridges,
workflow rendering and media lookups live in their focused editing modules.
"""

import hashlib
import itertools
import subprocess

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from joymedia.services.editing.bridges import (
	BRIDGE_FRAMES,
	BRIDGE_OVERLAP_FRAMES,
	MIN_TAKE_REMAINDER_FRAMES,
	_bridge_asset_version,
	_bridge_prompt,
	_insert_bridge,
	_renumber_video_clips,
	_shift_clip,
	_shot_place,
)

# Stable service exports; implementation lives in focused finishing modules.
from joymedia.services.editing.music import (
	DEFAULT_SOUNDTRACK_MUSIC,
	MUSIC_CLIP_SECONDS,
	MUSIC_CLIP_SIZE,
	MUSIC_CROSSFADE_SECONDS,
	MUSIC_ENDING_SEARCH_SECONDS,
	MUSIC_FADE_OUT_FRAMES,
	MUSIC_GAIN_DB,
	SOUNDTRACK_FADE_IN_FRAMES,
	SOUNDTRACK_FADE_OUT_FRAMES,
	SOUNDTRACK_VERSION,
	_add_music_bed,
	_add_soundtrack,
	_music_start_frame,
	_render_music_bed,
	_render_soundtrack,
	_render_workflow_music_bed,
	_soundtrack_seconds,
	_soundtrack_workflow,
	music_bed,
	music_brief,
)
from joymedia.services.editing.queries import (
	_latest_version_of,
	_shot_video_clips,
)
from joymedia.services.editing.rendering import (
	COMFYUI_JOB_TIMEOUT_SECONDS,
	_extract_frame,
	_render_video,
	_save_output,
	_slug,
	_video_workflow,
)
from joymedia.services.project.render_queue import enqueue_render, is_render_alive
from joymedia.services.runtime.transactions import persist_result

# Finishing can repeat when selected scenes change during an in-flight job.
MAX_FINISHING_ROUNDS = 3
EFFECTS_AND_MUSIC = "Effects + music"


@frappe.whitelist()
def queue_post_production(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	# Asked for by hand: rebuild everything, including a timeline edited by hand.
	persist_result(
		lambda: frappe.db.set_value(
			"Media Project", project.name, "finished_timeline_signature", "", update_modified=False
		)
	)
	return queue_post_production_internal(project.name)


@frappe.whitelist(methods=["POST"])
def queue_music_bed(project_name: str):
	"""Replace only background music, preserving the approved picture, VO and effects."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	with frappe.cache.lock(f"joymedia-music:{project.name}", timeout=30, blocking_timeout=5):
		if is_render_alive(_job_id(project.name)):
			frappe.throw(_("Wait for the current finishing job to finish."))
		if project.export_status in ("Queued", "Running"):
			frappe.throw(_("Wait for the current export to finish."))
		if not _shot_video_clips(project.name):
			frappe.throw(_("Generate the scenes before adding music."))
		# This request must not be resumed as a full timeline rebuild by the scheduler.
		frappe.db.set_value(
			"Media Project", project.name, "post_production_requested_at", None, update_modified=False
		)
		_set_status(project.name, "Queued", step="Music", error="")
		enqueue_render(
			"joymedia.services.editing.post_production.run_music_bed",
			_job_id(project.name),
			timeout=COMFYUI_JOB_TIMEOUT_SECONDS,
			project_name=project.name,
		)
		frappe.db.commit()
	return {"status": "Queued"}


def run_music_bed(project_name: str):
	from joymedia.services.editing.timeline import _invalidate_project_output

	try:
		_set_status(project_name, "Running", step="Music", error="")
		_add_music_bed(project_name)
		_invalidate_project_output(project_name)
		frappe.db.set_value(
			"Media Project", project_name, "post_production_comfy_prompt_id", "", update_modified=False
		)
		_set_status(project_name, "Completed", step="")
	except Exception:
		frappe.db.rollback()
		frappe.db.set_value(
			"Media Project", project_name, "post_production_comfy_prompt_id", "", update_modified=False
		)
		_set_status(
			project_name,
			"Failed",
			step="Music",
			error=_("Music generation failed. Your previous mix has been kept; try again."),
		)
		raise


@frappe.whitelist()
def cancel_post_production(project_name: str):
	"""Stop the current finishing job and its active ComfyUI prompt, if any."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	prompt_id = str(project.get("post_production_comfy_prompt_id") or "").strip()
	if prompt_id:
		from joymedia.services.workflows.comfyui import delete_queue_prompts, interrupt

		try:
			interrupt(prompt_id=prompt_id)
			delete_queue_prompts([prompt_id])
		except Exception:
			frappe.logger("joymedia.post_production").exception(
				"Unable to cancel ComfyUI prompt %s", prompt_id
			)
	from frappe.utils.background_jobs import get_queue

	from joymedia.services.project.render_queue import _render_queue

	job = get_queue(_render_queue()).fetch_job(_job_id(project.name))
	if job:
		job.cancel()
	frappe.db.set_value(
		"Media Project",
		project.name,
		{
			"post_production_status": "Cancelled",
			"post_production_step": "",
			"post_production_error": "",
			"post_production_comfy_prompt_id": "",
		},
		update_modified=False,
	)
	frappe.db.commit()
	return {"status": "Cancelled"}


def queue_post_production_internal(project_name):
	"""Queue Finish film for a project whose caller is already authorized."""
	if not _shot_video_clips(project_name, create=True):
		frappe.throw(_("Generate the scenes before finishing the film."))
	# A finish already running repeats when it sees a request newer than its start.
	# Do this after validation but before checking for a live job: a newly approved
	# take must request another pass even while a previous finish is rendering.
	requested_at = now_datetime()
	persist_result(
		lambda: frappe.db.set_value(
			"Media Project", project_name, "post_production_requested_at", requested_at, update_modified=False
		)
	)
	status = frappe.db.get_value("Media Project", project_name, "post_production_status")
	if status in ("Queued", "Running") and is_render_alive(_job_id(project_name)):
		frappe.db.commit()
		return {"status": status}
	_set_status(project_name, "Queued", step="", error="")
	enqueue_render(
		"joymedia.services.editing.post_production.run_post_production",
		_job_id(project_name),
		timeout=COMFYUI_JOB_TIMEOUT_SECONDS * 3,
		project_name=project_name,
	)
	frappe.db.commit()
	return {"status": "Queued"}


def resume_queued_post_productions():
	"""Retry persisted finish requests whose enqueue operation did not reach a worker.

	``post_production_requested_at`` is committed before enqueueing, so an approved
	review remains actionable even during a transient Redis/worker outage.  Only
	Queued jobs without a live RQ job are retried; failed renders still require an
	explicit user retry instead of looping indefinitely.
	"""
	projects = frappe.get_all(
		"Media Project",
		filters={"post_production_status": "Queued"},
		fields=["name", "post_production_requested_at"],
	)
	for project in projects:
		if not project.post_production_requested_at or is_render_alive(_job_id(project.name)):
			continue
		if _finishing_is_current(project.name):
			continue
		try:
			queue_post_production_internal(project.name)
		except Exception:
			frappe.logger("joymedia.post_production").exception(
				"Unable to resume queued finishing for %s", project.name
			)


def resume_post_production(project_name):
	"""Rebuild the finished film from the scenes' current takes when they are not already in it.

	Selecting a take is a valid independent operation, so this helper never throws.
	"""
	# A partial selection is not a shorter authored film. Automatic finishing
	# closes timeline gaps and updates duration, so wait for every active scene.
	shots = frappe.get_all(
		"Shot",
		filters={"media_project": project_name, "is_removed": 0},
		fields=["selected_output_asset_version"],
	)
	if any(not shot.get("selected_output_asset_version") for shot in shots):
		return {"status": "Awaiting Scenes"}
	if not _shot_video_clips(project_name, create=True):
		return {"status": "Awaiting Scenes"}
	if _finishing_is_current(project_name):
		return {"status": "Completed"}
	return queue_post_production_internal(project_name)


@frappe.whitelist()
def get_post_production_status(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	if project.post_production_status in ("Queued", "Running") and not is_render_alive(_job_id(project.name)):
		_set_status(
			project.name, "Failed", step="", error=_("Finishing stopped unexpectedly. Please try again.")
		)
		project.reload()
	return {
		"status": project.post_production_status or "Idle",
		"step": project.post_production_step or "",
		"error": project.post_production_error or "",
	}


def _job_id(project_name):
	return f"joymedia:post_production:{project_name}"


def run_post_production(project_name: str):
	try:
		frappe.db.set_value(
			"Media Project", project_name, "post_production_comfy_prompt_id", "", update_modified=False
		)
		# Scenes regenerated or takes switched while this ran need another pass.
		last_round_started = None
		for _round in range(MAX_FINISHING_ROUNDS):
			started = now_datetime()
			last_round_started = started
			if _edited_by_hand(project_name):
				# Keep the user's edits: swap new takes in and redo only their transitions.
				_patch_changed_scenes(project_name)
				_keep_to_sound_effects(project_name)
			else:
				_finish_once(project_name)
				frappe.db.set_value(
					"Media Project",
					project_name,
					"finished_timeline_signature",
					timeline_signature(project_name),
					update_modified=False,
				)
			requested = frappe.db.get_value("Media Project", project_name, "post_production_requested_at")
			if not requested or get_datetime(requested) <= started:
				break
		frappe.db.set_value(
			"Media Project", project_name, "post_production_comfy_prompt_id", "", update_modified=False
		)
		# Do not publish a Completed state if the last permitted pass missed a
		# newer request, or if its selected takes no longer match the timeline.
		# The scheduler resumes this persisted Queued request once this RQ job ends.
		requested = frappe.db.get_value("Media Project", project_name, "post_production_requested_at")
		if (
			last_round_started and requested and get_datetime(requested) > last_round_started
		) or not _selected_outputs_are_incorporated(project_name):
			_set_status(project_name, "Queued", step="", error="")
			return {"status": "Queued"}
		_set_status(project_name, "Completed", step="")
		return {"status": "Completed"}
	except Exception as exc:
		frappe.db.rollback()
		if frappe.db.get_value("Media Project", project_name, "post_production_status") == "Cancelled":
			return
		frappe.log_error(title=f"Post-production failed for {project_name}")
		from joymedia.services.generation.failures import classify_failure, friendly_failure

		# Marketers see a plain message; the technical detail is in the Error Log.
		frappe.db.set_value(
			"Media Project", project_name, "post_production_comfy_prompt_id", "", update_modified=False
		)
		_set_status(
			project_name, "Failed", step="", error=friendly_failure(classify_failure(exc, "Generation"))
		)
		raise


def _finishing_is_current(project_name):
	"""Whether a completed timeline still contains its selected take versions."""
	project = frappe.db.get_value(
		"Media Project",
		project_name,
		["post_production_status", "post_production_requested_at"],
		as_dict=True,
	)
	if not project or project.post_production_status != "Completed":
		return False
	# A new take is put on the timeline as soon as it is made, so being on the timeline does not mean it was finished
	# (gaps closed, sound screened): a take made after the last finishing request has not been.
	newest_take = _newest_take_time(project_name)
	if (
		newest_take
		and project.post_production_requested_at
		and newest_take > project.post_production_requested_at
	):
		return False
	return _selected_outputs_are_incorporated(project_name)


def _newest_take_time(project_name):
	"""When the newest of the scenes' current takes was made."""
	return frappe.db.sql(
		"""select max(version.creation) from `tabShot` shot
		join `tabAsset Version` version on version.name = shot.selected_output_asset_version
		where shot.media_project = %s and shot.is_removed = 0""",
		project_name,
	)[0][0]


def _selected_outputs_are_incorporated(project_name):
	"""Check selected takes independently of manual timeline-edit detection.

	``finished_timeline_signature`` deliberately remains the pre-edit baseline
	used by ``_edited_by_hand``.  Treating it as proof of selected-output
	incorporation made a successful patch pass look stale forever.
	"""
	selected = dict(
		frappe.get_all(
			"Shot",
			filters={"media_project": project_name, "is_removed": 0},
			fields=["name", "selected_output_asset_version"],
			as_list=True,
		)
	)
	clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Video", "enabled": 1},
		fields=["shot", "source_asset_version"],
	)
	return all(not clip.shot or clip.source_asset_version == selected.get(clip.shot) for clip in clips)


def timeline_signature(project_name):
	"""Fingerprint of the editable timeline state."""
	rows = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name},
		fields=[
			"name",
			"track_type",
			"track_index",
			"enabled",
			"timeline_start_frame",
			"source_asset_version",
			"source_in_frame",
			"source_out_frame",
			"transition_to_next",
			"transition_frames",
			"gain_db",
			"fade_in_frames",
			"fade_out_frames",
			"audio_role",
		],
		order_by="name asc",
	)
	return hashlib.sha256(repr([tuple(row.values()) for row in rows]).encode()).hexdigest()


def _edited_by_hand(project_name):
	"""Whether the timeline changed since the last full Finish film (trims, moves, mutes...)."""
	finished = frappe.db.get_value("Media Project", project_name, "finished_timeline_signature")
	return bool(finished) and finished != timeline_signature(project_name)


def _patch_changed_scenes(project_name):
	"""Swap each scene's newly selected take into an edited timeline and redo its transitions.

	The user's trims, moves and audio settings stay; the soundtrack stays too.
	"""
	from joymedia.services.editing.timeline import update_timeline_source_for_shot

	_set_status(project_name, "Running", step="Timeline", error="")
	clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Video", "enabled": 1},
		fields=[
			"name",
			"shot",
			"source_asset_version",
			"source_in_frame",
			"source_out_frame",
			"timeline_start_frame",
			"clip_order",
		],
		order_by="timeline_start_frame asc, clip_order asc",
	)
	selected = dict(
		frappe.get_all(
			"Shot",
			filters={"media_project": project_name},
			fields=["name", "selected_output_asset_version"],
			as_list=True,
		)
	)
	changed = {
		clip.shot
		for clip in clips
		if clip.shot and selected.get(clip.shot) and clip.source_asset_version != selected[clip.shot]
	}
	for shot in changed:
		from joymedia.services.runtime.transactions import persist_result

		# Another take selection can commit while this worker reads the project.
		# Retry only the short editorial swap, never a transition render.
		persist_result(lambda: update_timeline_source_for_shot(project_name, shot))

	generation_mode = frappe.db.get_value("Media Project", project_name, "generation_mode") or "Multi-shot"
	if generation_mode in ("Continuous", "Consistency"):
		frappe.db.commit()
		return

	clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Video", "enabled": 1},
		fields=[
			"name",
			"shot",
			"source_asset_version",
			"source_in_frame",
			"source_out_frame",
			"timeline_start_frame",
			"clip_order",
		],
		order_by="timeline_start_frame asc, clip_order asc",
	)
	bridges = [
		(previous, bridge, following)
		for previous, bridge, following in zip(clips, clips[1:], clips[2:], strict=False)
		if not bridge.shot and (previous.shot in changed or following.shot in changed)
	]
	for index, (previous, bridge, following) in enumerate(bridges, start=1):
		_set_status(project_name, "Running", step=f"Transition {index}/{len(bridges)}")
		outgoing = frappe._dict(
			previous, source_out_frame=int(previous.source_out_frame) + BRIDGE_OVERLAP_FRAMES
		)
		incoming = frappe._dict(
			following, source_in_frame=int(following.source_in_frame) - BRIDGE_OVERLAP_FRAMES
		)
		try:
			version = _bridge_asset_version(project_name, outgoing, incoming)
		except (subprocess.CalledProcessError, ValueError):
			frappe.log_error(title=f"Transition not redone for {project_name}")
			continue
		frappe.db.set_value(
			"Timeline Clip", bridge.name, "source_asset_version", version, update_modified=False
		)
	frappe.db.commit()


def _finish_once(project_name):
	from joymedia.services.editing.timeline import close_timeline_gaps, reset_project_timeline

	_set_status(project_name, "Running", step="Timeline", error="")
	reset_project_timeline(project_name, preserve_narration=True)
	# The sheet's slack between scenes is not an intended pause: scenes cut directly into each other, never a held frame.
	close_timeline_gaps(project_name)
	clips = _shot_video_clips(project_name)
	generation_mode = frappe.db.get_value("Media Project", project_name, "generation_mode") or "Multi-shot"
	if generation_mode not in ("Continuous", "Consistency"):
		for index, (outgoing, incoming) in enumerate(itertools.pairwise(clips), start=1):
			# A new scene is an editorial cut. Synthesizing motion across independently
			# staged scenes can invent props, people or product print in the bridge.
			# Only a deliberately continued action calls for a generated handoff.
			if frappe.db.get_value("Shot", incoming.shot, "continuity_mode") != "Continue":
				continue
			_set_status(project_name, "Running", step=f"Transition {index}/{len(clips) - 1}")
			_insert_bridge(project_name, outgoing, incoming)
			clips = _shot_video_clips(project_name)
	# "Full soundtrack" lets the video model's music replace the scenes' sound; "Effects + music" keeps the scenes'
	# effects and lays one music bed under the whole film; the other modes are effects only.
	mode = _sound_mode(project_name)
	if mode == "Full soundtrack":
		_set_status(project_name, "Running", step="Soundtrack")
		_add_soundtrack(project_name)
	else:
		_keep_to_sound_effects(project_name)
		if mode == EFFECTS_AND_MUSIC:
			_set_status(project_name, "Running", step="Music")
			_add_music_bed(project_name)


def _sound_mode(project_name):
	return frappe.db.get_value("Media Project", project_name, "soundtrack_mode") or "Sound effects only"


def _keep_to_sound_effects(project_name):
	"""Make the film's sound effects only, whatever the video model put in the scenes' own audio.

	The video model is only asked for effects and cannot be forced to leave out music or voice, so the audio is
	screened: a scene that sounds like music or speech is silenced and given a generated effect layer
	("Sound effects only"), or every scene gets one ("Separate effects layer"). "Full soundtrack" is left alone.
	"""
	mode = _sound_mode(project_name)
	if mode == "Full soundtrack":
		return
	from joymedia.services.audio.plan import check_scene_audio, use_separate_effects_layer

	_set_status(project_name, "Running", step="Sound effects")
	if mode == "Separate effects layer":
		use_separate_effects_layer(project_name)
	else:
		check_scene_audio(project_name)


def _set_status(project_name, status, step=None, error=None):
	from joymedia.services.project.realtime import PROJECT_UPDATED, publish_project_event

	values = {"post_production_status": status}
	if step is not None:
		values["post_production_step"] = step
	if error is not None:
		values["post_production_error"] = error

	def write():
		if (
			status in {"Running", "Completed"}
			and frappe.db.get_value("Media Project", project_name, "post_production_status", for_update=True)
			== "Cancelled"
		):
			raise ValueError("Post-production was cancelled.")
		frappe.db.set_value("Media Project", project_name, values, update_modified=False)
		# Publish only after the short write commits; rollback drops the callback.
		publish_project_event(project_name, PROJECT_UPDATED, {"doctype": "Media Project"})

	persist_result(write)

import frappe
from frappe import _
from frappe.model.document import Document


class TimelineClip(Document):
	def validate(self):
		self.source_in_frame = int(self.source_in_frame or 0)
		self.source_out_frame = int(self.source_out_frame or 0)
		self.clip_order = int(self.clip_order or 0)
		self.track_index = int(self.track_index or 0)
		self.timeline_start_frame = int(self.timeline_start_frame or 0)
		self.transition_frames = int(self.transition_frames or 0)

		if self.clip_order < 1:
			frappe.throw(_("Timeline clip order must be at least 1."))
		if self.track_type not in ("Video", "Audio"):
			frappe.throw(_("Timeline clip track type must be Video or Audio."))
		if self.track_index < 0 or self.timeline_start_frame < 0:
			frappe.throw(_("Timeline clip track index and start frame cannot be negative."))
		if self.source_in_frame < 0:
			frappe.throw(_("Timeline clip source in frame cannot be negative."))
		if self.source_out_frame <= self.source_in_frame:
			frappe.throw(_("Timeline clip source out frame must be after the source in frame."))
		if self.transition_to_next not in ("Cut", "Dissolve", "Fade"):
			frappe.throw(_("Unsupported timeline transition."))
		if self.transition_frames < 0:
			frappe.throw(_("Transition frames cannot be negative."))
		if self.transition_to_next == "Cut":
			self.transition_frames = 0
		if self.track_type == "Video" and self.audio_role:
			self.audio_role = None
		if self.track_type == "Audio" and not self.audio_role:
			self.audio_role = "SFX"
		if self.track_type == "Video" and self.linked_video_clip:
			self.linked_video_clip = None
		_validate_video_transition(self)

	def after_insert(self):
		"""Preserve storyboard order while generated shots arrive asynchronously.

		Initial generated clips are created one-by-one as ComfyUI jobs finish. That
		completion order is not necessarily the storyboard order. Reorder only a
		pristine, one-clip-per-shot timeline; once a user trims, moves, splits,
		duplicates, transitions, or replaces a source, editorial order is sacred.
		"""
		if self.track_type == "Audio" and self.audio_role == "Source" and self.linked_video_clip:
			_align_source_audio_to_video(self)
			return
		if self.track_type != "Video" or not self.shot or not self.media_project:
			return
		_restore_pristine_generated_shot_order(self.media_project)


def _validate_video_transition(clip):
	"""Keep transition semantics on the visual track, never the interleaved audio rows."""
	if clip.track_type != "Video" or (clip.transition_to_next or "Cut") == "Cut":
		return
	if not clip.media_project:
		return

	filters = {
		"media_project": clip.media_project,
		"track_type": "Video",
		"enabled": 1,
		"clip_order": [">", int(clip.clip_order or 0)],
	}
	if clip.name:
		filters["name"] = ["!=", clip.name]
	next_clip = frappe.db.get_value(
		"Timeline Clip",
		filters,
		["source_in_frame", "source_out_frame"],
		as_dict=True,
		order_by="clip_order asc, creation asc",
	)
	if not next_clip:
		clip.transition_to_next = "Cut"
		clip.transition_frames = 0
		return

	current_frames = max(0, int(clip.source_out_frame or 0) - int(clip.source_in_frame or 0))
	next_frames = max(0, int(next_clip.source_out_frame or 0) - int(next_clip.source_in_frame or 0))
	max_transition = max(0, min(current_frames, next_frames) - 1)
	if int(clip.transition_frames or 0) < 1:
		frappe.throw(_("Dissolve and Fade transitions must be at least 1 frame."))
	if int(clip.transition_frames or 0) > max_transition:
		frappe.throw(_("Transition is longer than one of its neighboring video clips."))


def _align_source_audio_to_video(audio_clip):
	video = frappe.db.get_value(
		"Timeline Clip",
		audio_clip.linked_video_clip,
		[
			"clip_order",
			"timeline_start_frame",
			"initial_timeline_start_frame",
			"source_in_frame",
			"source_out_frame",
			"initial_source_in_frame",
			"initial_source_out_frame",
		],
		as_dict=True,
	)
	if not video:
		return
	frappe.db.set_value(
		"Timeline Clip",
		audio_clip.name,
		{
			"clip_order": int(video.clip_order or 0),
			"timeline_start_frame": int(video.timeline_start_frame or 0),
			"initial_timeline_start_frame": int(
				video.initial_timeline_start_frame or video.timeline_start_frame or 0
			),
			"source_in_frame": int(video.source_in_frame or 0),
			"source_out_frame": int(video.source_out_frame or 0),
			"initial_source_in_frame": int(video.initial_source_in_frame or video.source_in_frame or 0),
			"initial_source_out_frame": int(video.initial_source_out_frame or video.source_out_frame or 0),
		},
		update_modified=False,
	)


def _restore_pristine_generated_shot_order(project_name):
	clips = frappe.get_all(
		"Timeline Clip",
		filters={
			"media_project": project_name,
			"track_type": "Video",
			"enabled": 1,
		},
		fields=[
			"name",
			"shot",
			"clip_order",
			"timeline_start_frame",
			"initial_timeline_start_frame",
			"source_in_frame",
			"source_out_frame",
			"initial_source_in_frame",
			"initial_source_out_frame",
			"transition_to_next",
			"transition_frames",
			"is_outdated",
		],
		order_by="clip_order asc, creation asc",
	)
	if not clips:
		return

	seen_shots = set()
	cursor = 0
	for clip in clips:
		if not clip.shot or clip.shot in seen_shots:
			return
		seen_shots.add(clip.shot)
		if int(clip.source_in_frame or 0) != int(clip.initial_source_in_frame or 0):
			return
		if int(clip.source_out_frame or 0) != int(clip.initial_source_out_frame or 0):
			return
		if int(clip.timeline_start_frame or 0) != int(clip.initial_timeline_start_frame or 0):
			return
		if int(clip.timeline_start_frame or 0) != cursor:
			return
		if clip.is_outdated or (clip.transition_to_next or "Cut") != "Cut" or int(clip.transition_frames or 0):
			return
		cursor += max(0, int(clip.source_out_frame or 0) - int(clip.source_in_frame or 0))

	shots = frappe.get_all(
		"Shot",
		filters={
			"media_project": project_name,
			"name": ["in", list(seen_shots)],
			"is_removed": 0,
		},
		fields=["name", "shot_number"],
	)
	if len(shots) != len(seen_shots):
		return
	shot_number = {row.name: int(row.shot_number or 0) for row in shots}
	ordered = sorted(clips, key=lambda clip: (shot_number.get(clip.shot, 0), clip.name))

	cursor = 0
	for index, clip in enumerate(ordered, start=1):
		frappe.db.set_value(
			"Timeline Clip",
			clip.name,
			{
				"clip_order": index,
				"timeline_start_frame": cursor,
				"initial_timeline_start_frame": cursor,
			},
			update_modified=False,
		)
		linked_audio = frappe.db.get_value(
			"Timeline Clip",
			{"linked_video_clip": clip.name, "track_type": "Audio"},
			"name",
		)
		if linked_audio:
			frappe.db.set_value(
				"Timeline Clip",
				linked_audio,
				{
					"clip_order": index,
					"timeline_start_frame": cursor,
					"initial_timeline_start_frame": cursor,
				},
				update_modified=False,
			)
		cursor += max(0, int(clip.source_out_frame or 0) - int(clip.source_in_frame or 0))

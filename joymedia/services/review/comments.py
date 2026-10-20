"""Review comments: notes on a frame, or a range of frames, of a scene's take, and applying them.

The reviewer watches the generated scene, pauses, and writes what should change at that frame or between two frames
(Frame.io, Webgate and Kitsu all anchor comments this way). Comments belong to the exact take they were written on.
"Apply" hands every open comment of a scene to the language model together with the scene's prompts, saves the
revised prompts and renders a new take; the comments are then marked Addressed and stay as history of that take.
Nothing blocks delivery: open comments are shown, not enforced.
"""

import random
import time
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import get_fullname, now_datetime, strip_html_tags

from joymedia.services.editing.view import _project_fps, _source_max_frames
from joymedia.services.project.realtime import PROJECT_UPDATED, publish_project_event

MAX_OPEN_PER_SCENE = 50
EDITABLE_STATUSES = ("Open", "Resolved")


def _retrying(action, attempts=4):
	"""Run a small database write again when MariaDB picks it as the loser of a lock race (Frappe's own advice)."""
	for attempt in range(attempts):
		try:
			return action()
		except (frappe.QueryDeadlockError, frappe.TimestampMismatchError):
			frappe.db.rollback()
			if attempt == attempts - 1:
				raise
			time.sleep(0.05 * (attempt + 1) + random.random() * 0.05)


@contextmanager
def _applying(project_name):
	"""One apply per project at a time. A second click (or tab) is told so instead of rendering everything twice.

	A MariaDB named lock is shared by every web and worker process and is released if the connection dies.
	"""
	name = f"joymedia-apply-comments-{project_name}"
	if not frappe.db.sql("select get_lock(%s, 0)", name)[0][0]:
		frappe.throw(_("These comments are already being applied. Wait a moment."))
	try:
		# Start a fresh database snapshot: an apply that just finished must be visible, or its comments would be applied twice.
		frappe.db.commit()
		yield
	finally:
		frappe.db.sql("select release_lock(%s)", name)


def _project(project_name, write):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access() if write else project._require_read_access()
	return project


def _scene(project, shot_name):
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name or shot.is_removed:
		frappe.throw(_("The scene does not belong to this project."))
	return shot


def _frame_limit(project, shot):
	"""Number of frames in the scene's selected take."""
	fps = _project_fps(project.name)
	return _source_max_frames(shot.selected_output_asset_version, fps) or round(float(shot.duration_seconds or 0) * fps), fps


def _as_frame(value, name):
	try:
		number = float(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be a frame number.").format(name))
	if number != number or number in (float("inf"), float("-inf")) or number != int(number) or number < 0:
		frappe.throw(_("{0} must be a whole frame number of 0 or more.").format(name))
	return int(number)


@frappe.whitelist()
def add_review_comment(project_name, shot_name, comment, start_frame=None, end_frame=None, whole_scene=0):
	"""Add a comment on the whole scene, on a frame (end_frame omitted) or on a range of frames of its current take.

	The storyboard view comments on whole scenes; the timeline view on the frames under its playhead.
	"""
	project = _project(project_name, write=True)
	shot = _scene(project, shot_name)
	if not shot.selected_output_asset_version:
		frappe.throw(_("Generate the scene before commenting on it."))
	whole = str(whole_scene).lower() in {"1", "true", "yes", "on"}
	limit, fps = _frame_limit(project, shot)
	start = end = None
	if not whole:
		start = _as_frame(start_frame, _("Start frame"))
		end = start if end_frame in (None, "") else _as_frame(end_frame, _("End frame"))
		if end < start:
			start, end = end, start
		if limit and start >= limit:
			frappe.throw(_("This take has {0} frames; frame {1} is past its end.").format(limit, start))
		end = min(end, limit - 1) if limit else end
	def insert():
		# The limit check and the insert are one step per scene, or simultaneous requests would all see room:
		# the scene's row lock queues them, and a locking read sees comments committed while one waited.
		frappe.db.sql("select name from `tabShot` where name = %s for update", shot.name)
		open_count = frappe.db.sql(
			"select count(*) from `tabReview Comment` where shot = %s and output_asset_version = %s and status = 'Open' for update",
			(shot.name, shot.selected_output_asset_version),
		)[0][0]
		if open_count >= MAX_OPEN_PER_SCENE:
			frappe.throw(_("This scene already has {0} open comments. Apply or resolve them first.").format(MAX_OPEN_PER_SCENE))
		return frappe.get_doc({
			"doctype": "Review Comment", "media_project": project.name, "shot": shot.name,
			"output_asset_version": shot.selected_output_asset_version, "start_frame": start, "end_frame": end,
			"scope": "Scene" if whole else "Frames", "comment": " ".join(strip_html_tags(str(comment or "")).split()),
		}).insert(ignore_permissions=True)

	doc = _retrying(insert)
	frappe.db.commit()
	publish_project_event(project.name, PROJECT_UPDATED, {"doctype": "Review Comment", "shot": shot.name})
	return _row(doc.as_dict(), shot.selected_output_asset_version, fps)


def _row(row, current_take, fps):
	frames = row.get("scope") != "Scene" and row["start_frame"] is not None
	return {
		"name": row["name"], "shot": row["shot"], "output_asset_version": row["output_asset_version"],
		"scope": "Frames" if frames else "Scene",
		"start_frame": row["start_frame"] if frames else None, "end_frame": row["end_frame"] if frames else None,
		"start_seconds": round(row["start_frame"] / fps, 3) if frames else None,
		"end_seconds": round((row["end_frame"] + 1) / fps, 3) if frames else None,
		"comment": row["comment"], "status": row["status"], "author": row["owner"], "author_name": get_fullname(row["owner"]),
		"created": row["creation"], "current_take": row["output_asset_version"] == current_take,
	}


@frappe.whitelist()
def get_review_comments(project_name, shot_name=None):
	"""Every comment of the project (or one scene), oldest first, each marked with whether it is on the scene's current take."""
	project = _project(project_name, write=False)
	filters = {"media_project": project.name}
	if shot_name:
		filters["shot"] = _scene(project, shot_name).name
	rows = frappe.get_all(
		"Review Comment", filters=filters, order_by="shot asc, start_frame asc, creation asc",
		fields=["name", "shot", "output_asset_version", "scope", "start_frame", "end_frame", "comment", "status", "owner", "creation"],
	)
	if not rows:
		return []
	fps = _project_fps(project.name)
	current = dict(frappe.get_all("Shot", filters={"name": ["in", {r["shot"] for r in rows}]}, fields=["name", "selected_output_asset_version"], as_list=True))
	return [_row(row, current.get(row["shot"]), fps) for row in rows]


def open_comment_counts(project_name):
	"""{scene: number of open comments on its current take}, for the storyboard cards."""
	rows = frappe.db.sql(
		"""select c.shot, count(*) from `tabReview Comment` c join `tabShot` s on s.name = c.shot
		where c.media_project = %s and c.status = 'Open' and c.output_asset_version = s.selected_output_asset_version
		group by c.shot""",
		project_name,
	)
	return dict(rows)


@frappe.whitelist()
def set_review_comment_status(project_name, comment_name, status):
	"""Mark a comment Resolved (done by hand) or reopen it."""
	project = _project(project_name, write=True)
	if status not in EDITABLE_STATUSES:
		frappe.throw(_("Status must be Open or Resolved."))
	doc = _comment(project, comment_name)
	resolved = status == "Resolved"
	_retrying(lambda: frappe.db.set_value("Review Comment", doc.name, {
		"status": status, "resolved_by": frappe.session.user if resolved else None,
		"resolved_at": now_datetime() if resolved else None,
	}))
	frappe.db.commit()
	publish_project_event(project.name, PROJECT_UPDATED, {"doctype": "Review Comment", "shot": doc.shot})
	return {"name": doc.name, "status": status}


@frappe.whitelist()
def delete_review_comment(project_name, comment_name):
	project = _project(project_name, write=True)
	doc = _comment(project, comment_name)
	_retrying(lambda: frappe.delete_doc("Review Comment", doc.name, ignore_permissions=True))
	frappe.db.commit()
	publish_project_event(project.name, PROJECT_UPDATED, {"doctype": "Review Comment", "shot": doc.shot})
	return {"deleted": comment_name}


def _comment(project, comment_name):
	doc = frappe.get_doc("Review Comment", comment_name)
	if doc.media_project != project.name:
		frappe.throw(_("The comment does not belong to this project."))
	return doc


def _reseal_approved_plan(project_name):
	"""Keep an approved storyboard approved after the reviewer's own revision of a scene.

	Any change to a scene's prompts makes the approved plan look edited, and a changed plan cannot render without a new
	approval. A revision written from the reviewer's comments is not an unreviewed edit, so the plan is sealed again.
	"""
	from joymedia.services.planning.signature import compute_plan_signature

	if frappe.db.get_value("Media Project", project_name, "storyboard_approval_status") == "Approved":
		frappe.db.set_value(
			"Media Project", project_name, "approved_plan_signature", compute_plan_signature(project_name), update_modified=False
		)


CORRECTIONS_MARKER = "Reviewer corrections (carry these out exactly and keep everything else as it is):"
MAX_CORRECTIONS_CHARS = 1800


def _when(row, fps):
	if row.get("scope") == "Scene" or row.get("start_frame") is None:
		return "for the whole scene"
	start, end = row["start_frame"] / fps, (row["end_frame"] + 1) / fps
	return f"at {start:.1f}s" if row["end_frame"] == row["start_frame"] else f"from {start:.1f}s to {end:.1f}s"


def strip_corrections(prompt):
	"""A scene's prompt without the corrections block, so the block is rebuilt from the comments, never stacked."""
	return str(prompt or "").split("\n\n" + CORRECTIONS_MARKER)[0].rstrip()


def with_corrections(prompt, rows, fps):
	"""The prompt followed by the reviewer's requests as timed instructions, in the reviewer's own words (as English).

	This is deliberately not a model rewrite: a paraphrase can lose or soften a request, and the video model needs the
	exact ask. Raises when the open requests alone do not fit, rather than silently dropping one.
	"""
	base = strip_corrections(prompt)
	if not rows:
		return base
	lines, used = [], len(CORRECTIONS_MARKER)
	# Open requests are mandatory; earlier, already addressed ones are kept (newest first) while there is room.
	for row in sorted(rows, key=lambda r: (r["status"] == "Open", r["creation"]), reverse=True):
		line = f"- {_when(row, fps)}: {row['english']}"
		if used + len(line) + 1 > MAX_CORRECTIONS_CHARS:
			if row["status"] == "Open":
				frappe.throw(_("These comments are too long to apply together. Shorten them or apply fewer at a time."))
			continue
		lines.append((row, line))
		used += len(line) + 1
	# Whole-scene requests first, then the rest in the order they happen.
	lines.sort(key=lambda pair: (pair[0]["start_frame"] is not None, pair[0]["start_frame"] or 0, pair[0]["creation"]))
	return base + "\n\n" + CORRECTIONS_MARKER + "\n" + "\n".join(line for _row, line in lines)


def _in_english(rows):
	from joymedia.services.planning.llm import to_english

	return [{**row, "english": to_english(row["comment"])} for row in rows]


def revised_generation_prompt(shot, rows, fps):
	"""The scene's video prompt with the comments written in.

	The starting picture is left alone on purpose: it was reviewed and approved, and redrawing it from a changed prompt can
	swap the reference subject for a different-looking one. Redrawing a first frame is its own reviewed step in the frames panel.
	"""
	return with_corrections(shot.generation_prompt, _in_english(rows), fps)


@frappe.whitelist()
def apply_review_comments(project_name, shot_names=None):
	"""Write the open comments on each scene's current take into its video prompt and render a new take.

	Everything is checked and worded first, so a problem changes nothing; then each scene is rendered again (scenes can
	render at once). A scene that cannot be rendered keeps its old prompts and its comments stay Open.
	"""
	from joymedia.services.generation.takes import _ensure_scene_free, regenerate_scene_with_reason

	project = _project(project_name, write=True)
	wanted = set(frappe.parse_json(shot_names)) if isinstance(shot_names, str) and shot_names else set(shot_names or [])
	with _applying(project.name):
		fps = _project_fps(project.name)
		plans = []
		for shot in frappe.get_all(
			"Shot", filters={"media_project": project.name, "is_removed": 0}, order_by="shot_number asc",
			fields=["name", "shot_name", "selected_output_asset_version"],
		):
			if wanted and shot.name not in wanted:
				continue
			rows = frappe.get_all(
				"Review Comment", filters={"shot": shot.name, "status": ["in", ["Open", "Addressed"]]},
				fields=["name", "scope", "start_frame", "end_frame", "comment", "status", "output_asset_version", "creation"],
				order_by="creation asc",
			)
			opened = [row for row in rows if row["status"] == "Open" and row["output_asset_version"] == shot.selected_output_asset_version]
			if shot.selected_output_asset_version and opened:
				plans.append((frappe.get_doc("Shot", shot.name), opened, [row for row in rows if row["status"] == "Addressed"] + opened))
		if not plans:
			frappe.throw(_("There are no open comments to apply."))
		for shot, _opened, _all in plans:
			_ensure_scene_free(project, shot)
		wording = [revised_generation_prompt(shot, rows, fps) for shot, _opened, rows in plans]
		results = []
		for (shot, opened, _all), generation_prompt in zip(plans, wording):
			before = {field: shot.get(field) for field in ("generation_prompt", "motion_plan_json", "end_state", "handoff_type")}
			frappe.db.set_value("Shot", shot.name, {"generation_prompt": generation_prompt,
				"motion_plan_json": None, "end_state": None, "handoff_type": None}, update_modified=True)
			_reseal_approved_plan(project.name)
			try:
				regenerate_scene_with_reason(project.name, shot.name, retry_reason="QA Rejection")
			except Exception as exc:
				frappe.db.set_value("Shot", shot.name, before, update_modified=True)
				_reseal_approved_plan(project.name)
				results.append({"shot": shot.name, "shot_name": shot.shot_name, "applied": False, "error": str(exc), "comments": len(opened)})
				continue
			for row in opened:
				frappe.db.set_value("Review Comment", row["name"], {"status": "Addressed", "addressed_at": now_datetime()}, update_modified=True)
			results.append({"shot": shot.name, "shot_name": shot.shot_name, "applied": True, "comments": len(opened)})
		frappe.db.commit()
	publish_project_event(project.name, PROJECT_UPDATED, {"doctype": "Review Comment"})
	return {"scenes": results, "applied": sum(1 for row in results if row["applied"])}

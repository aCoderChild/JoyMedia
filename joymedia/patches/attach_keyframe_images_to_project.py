import frappe


def execute():
	"""Make existing keyframe pictures readable by their project's owner (see keyframes.stage.attach_keyframe_to_project)."""
	from joymedia.services.keyframes.stage import attach_keyframe_to_project

	for shot in frappe.get_all("Shot", filters={"keyframe_artifact": ["is", "set"]}, fields=["media_project", "keyframe_artifact"]):
		file_url = frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file")
		if file_url:
			attach_keyframe_to_project(file_url, shot.media_project)

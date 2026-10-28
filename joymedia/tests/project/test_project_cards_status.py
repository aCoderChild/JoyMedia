from unittest import TestCase
from unittest.mock import patch

from joymedia.api.projects import get_project_cards


class TestProjectCardStatus(TestCase):
	def test_failed_video_is_attention_not_review_or_working(self):
		rows = {"items": [{"name": "ROOT", "project_name": "Project", "open_project": "ROOT"}]}
		videos = {
			"videos": [
				{
					"name": "CHILD",
					"video": None,
					"stage": "Needs Attention",
					"status": "Draft",
					"is_working_edit": True,
				},
				{
					"name": "REVIEW",
					"video": None,
					"stage": "Pictures Ready",
					"status": "Draft",
					"is_working_edit": False,
				},
			]
		}
		with (
			patch("joymedia.services.project.versions.card_rows", return_value=rows),
			patch("joymedia.services.project.versions.get_videos", return_value=videos),
			patch("joymedia.api.projects._get_project_selected_assets", return_value=[]),
			patch("frappe.get_doc", return_value=object()),
		):
			card = get_project_cards()["items"][0]
		self.assertEqual(
			(1, 1, 0), (card["videos_attention"], card["videos_waiting"], card["videos_working"])
		)
		self.assertEqual("REVIEW", card["open_project"])

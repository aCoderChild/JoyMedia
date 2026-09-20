# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import json
import subprocess

from PIL import Image

import frappe
from frappe.model.document import Document


class AssetVersion(Document):
	def validate(self):
		self.set_file_metadata()

	def before_insert(self):
		latest_version = frappe.db.get_value(
			"Asset Version",
			{"media_asset": self.media_asset},
			[{"MAX": "version_number"}],
			order_by=None,
		)
		self.version_number = (latest_version or 0) + 1

	def set_file_metadata(self):
		self.width = None
		self.height = None
		self.duration_seconds = None
		self.fps = None

		if not self.file:
			return

		media_asset = frappe.get_doc("Media Asset", self.media_asset)
		if media_asset.media_type == "Image":
			self.set_image_metadata()
		elif media_asset.media_type == "Video":
			self.set_video_metadata()

	def set_image_metadata(self):
		file_doc = frappe.get_doc("File", {"file_url": self.file})
		with Image.open(file_doc.get_full_path()) as image:
			self.width, self.height = image.size

	def set_video_metadata(self):
		file_doc = frappe.get_doc("File", {"file_url": self.file})
		try:
			result = subprocess.run(
				[
					"ffprobe",
					"-v",
					"error",
					"-select_streams",
					"v:0",
					"-show_entries",
					"stream=width,height,r_frame_rate:format=duration",
					"-of",
					"json",
					file_doc.get_full_path(),
				],
				capture_output=True,
				text=True,
				check=True,
			)
			metadata = json.loads(result.stdout)
			stream = metadata.get("streams", [None])[0]
			if not stream:
				raise ValueError("no video stream found")

			self.width = int(stream["width"])
			self.height = int(stream["height"])
			self.duration_seconds = float(metadata["format"]["duration"])
			self.fps = self._frame_rate(stream["r_frame_rate"])
		except (
			KeyError,
			OSError,
			ValueError,
			ZeroDivisionError,
			json.JSONDecodeError,
			subprocess.CalledProcessError,
		) as exc:
			frappe.throw(f"Unable to read video metadata for Asset Version {self.name or '(new)'}: {exc}")

	@staticmethod
	def _frame_rate(value):
		numerator, denominator = str(value).split("/", 1)
		return int(numerator) / int(denominator)

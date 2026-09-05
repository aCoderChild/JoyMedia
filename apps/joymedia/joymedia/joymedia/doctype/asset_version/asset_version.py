# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import json
import subprocess
from fractions import Fraction
from pathlib import Path

import frappe
from frappe import _
from frappe.model.document import Document

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


class AssetVersion(Document):
	def validate(self):
		self._validate_immutable_identity()
		self._validate_unique_version_number()
		self.set_file_metadata()

	def _validate_immutable_identity(self):
		if self.is_new():
			return

		for fieldname, label in {
			"media_asset": "Media Asset",
			"version_number": "Version Number",
			"file": "File",
		}.items():
			if self.has_value_changed(fieldname):
				frappe.throw(_("{0} cannot be changed after an Asset Version is created.").format(label))

	def _validate_unique_version_number(self):
		if not self.media_asset or self.version_number is None:
			return

		filters = {"media_asset": self.media_asset, "version_number": self.version_number}
		if self.name:
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Asset Version", filters):
			frappe.throw(_("Asset Version Number must be unique within a Media Asset."))

	def before_insert(self):
		latest_version = frappe.db.get_value(
			"Asset Version",
			{"media_asset": self.media_asset},
			[{"MAX": "version_number"}],
		)
		self.version_number = (latest_version or 0) + 1

	def set_file_metadata(self):
		self.width = None
		self.height = None
		self.duration_seconds = None
		self.fps = None

		if not self.file:
			return

		file_doc = frappe.get_doc("File", {"file_url": self.file})
		file_path = Path(file_doc.get_full_path())
		if not file_path.exists():
			return

		if file_path.suffix.lower() in IMAGE_EXTENSIONS:
			self.set_image_metadata(file_path)
		elif file_path.suffix.lower() in VIDEO_EXTENSIONS:
			self.set_video_metadata(file_path)

	def set_image_metadata(self, file_path):
		from PIL import Image

		with Image.open(file_path) as image:
			self.width, self.height = image.size

	def set_video_metadata(self, file_path):
		command = [
			"ffprobe",
			"-v",
			"error",
			"-select_streams",
			"v:0",
			"-show_entries",
			"stream=width,height,avg_frame_rate",
			"-show_entries",
			"format=duration",
			"-of",
			"json",
			str(file_path),
		]

		try:
			result = subprocess.run(command, capture_output=True, text=True, check=True)
		except FileNotFoundError:
			frappe.throw("ffprobe is not installed on the Frappe server.")
		except subprocess.CalledProcessError as exc:
			frappe.throw(f"Unable to read video metadata: {exc.stderr}")

		metadata = json.loads(result.stdout)
		streams = metadata.get("streams", [])
		if not streams:
			return

		stream = streams[0]
		self.width = stream.get("width")
		self.height = stream.get("height")

		duration = metadata.get("format", {}).get("duration")
		if duration:
			self.duration_seconds = float(duration)

		frame_rate = stream.get("avg_frame_rate")
		if frame_rate and frame_rate != "0/0":
			self.fps = float(Fraction(frame_rate))

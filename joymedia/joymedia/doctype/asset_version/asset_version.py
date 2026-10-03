# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import hashlib
import json
import subprocess

from PIL import Image

import frappe
from frappe.model.document import Document


class AssetVersion(Document):
	IMMUTABLE_FIELDS = (
		"media_asset",
		"file",
		"source",
		"version_number",
		"derived_from",
		"content_hash",
		"width",
		"height",
		"duration_seconds",
		"fps",
	)

	def validate(self):
		if self.is_new():
			self.set_file_metadata()
			self.set_content_hash()
		else:
			self.validate_immutable_fields()

	def before_insert(self):
		# Lock the parent asset row while allocating the next number. This
		# serializes concurrent inserts for the same logical Media Asset.
		frappe.db.sql("SELECT name FROM `tabMedia Asset` WHERE name=%s FOR UPDATE", self.media_asset)
		latest_version = frappe.db.get_value(
			"Asset Version", {"media_asset": self.media_asset}, [{"MAX": "version_number"}], order_by=None
		)
		self.version_number = (latest_version or 0) + 1

	def validate_immutable_fields(self):
		previous = frappe.db.get_value(
			"Asset Version", self.name, list(self.IMMUTABLE_FIELDS), as_dict=True
		)
		if not previous:
			return
		for fieldname in self.IMMUTABLE_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(f"Asset Version {self.name} is immutable; create a new version instead of changing {fieldname}.")

	def set_content_hash(self):
		if not self.file:
			self.content_hash = None
			return
		file_doc = frappe.get_doc("File", {"file_url": self.file})
		digest = hashlib.sha256()
		with open(file_doc.get_full_path(), "rb") as file_handle:
			for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
				digest.update(chunk)
		self.content_hash = digest.hexdigest()

	def set_file_metadata(self):
		self.width = None
		self.height = None
		self.duration_seconds = None
		self.fps = 0

		if not self.file:
			return

		media_asset = frappe.get_doc("Media Asset", self.media_asset)
		if media_asset.media_type == "Image":
			self.set_image_metadata()
		elif media_asset.media_type == "Video":
			self.set_video_metadata()
		elif media_asset.media_type == "Audio":
			self.set_audio_metadata()

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

	def set_audio_metadata(self):
		file_doc = frappe.get_doc("File", {"file_url": self.file})
		try:
			result = subprocess.run(
				[
					"ffprobe",
					"-v",
					"error",
					"-show_entries",
					"format=duration",
					"-of",
					"json",
					file_doc.get_full_path(),
				],
				capture_output=True,
				text=True,
				check=True,
			)
			metadata = json.loads(result.stdout)
			duration = float(metadata["format"]["duration"])
			if duration <= 0:
				raise ValueError("audio duration must be positive")

			self.duration_seconds = duration
			self.fps = 0
		except (
			KeyError,
			OSError,
			ValueError,
			json.JSONDecodeError,
			subprocess.CalledProcessError,
		) as exc:
			frappe.throw(f"Unable to read audio metadata for Asset Version {self.name or '(new)'}: {exc}")

	@staticmethod
	def _frame_rate(value):
		numerator, denominator = str(value).split("/", 1)
		return int(numerator) / int(denominator)

# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MediaComposition(Document):
	def validate(self):
		sequence_orders = set()
		for item in self.composition_items or []:
			self._validate_item(item, sequence_orders)

	def _validate_item(self, item, sequence_orders):
		shot = frappe.get_doc("Shot Specification", item.shot_specification)
		if shot.media_specification != self.media_specification:
			frappe.throw(
				_("Composition Item Shot Specification must belong to the Media Composition's Media Specification.")
			)

		if item.sequence_order is None or item.sequence_order < 1:
			frappe.throw(_("Composition Item Sequence Order must be at least 1."))
		if item.sequence_order in sequence_orders:
			frappe.throw(_("Composition Item Sequence Order must be unique within a Media Composition."))
		sequence_orders.add(item.sequence_order)

		if item.trim_start is None or item.trim_start < 0:
			frappe.throw(_("Composition Item Trim Start must be zero or greater."))
		if item.trim_end is None or item.trim_end <= item.trim_start:
			frappe.throw(_("Composition Item Trim End must be greater than Trim Start."))

		asset_version = frappe.get_doc("Asset Version", item.asset_version)
		media_asset = frappe.get_doc("Media Asset", asset_version.media_asset)
		if media_asset.media_type != "Video":
			frappe.throw(_("Composition Item Asset Version must belong to a Video Media Asset."))
		if not asset_version.duration_seconds or item.trim_end > asset_version.duration_seconds:
			frappe.throw(_("Composition Item Trim End must not exceed the video duration."))

		attempts = frappe.get_all(
			"Generation Attempt",
			filters={"output_asset_version": asset_version.name},
			fields=["generation_job"],
		)
		if not any(
			frappe.db.get_value("Generation Job", attempt.generation_job, "shot_specification")
			== item.shot_specification
			for attempt in attempts
		):
			frappe.throw(
				_("Composition Item Asset Version must be generated for its Shot Specification.")
			)

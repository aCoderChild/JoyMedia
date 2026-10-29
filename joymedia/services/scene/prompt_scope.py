"""Reference inventory and observed appearance shared by image and video prompts."""

import re

ACTOR_ROLES = {"character", "person", "people", "talent"}


def sheet_material_instruction(action, *, opening=False):
	"""Keep explicitly handled paper separate from packaging graphics and objects."""
	text = str(action or "")
	if not re.search(
		r"\b(?:tissue|paper|napkin)\b(?!\s+(?:pack|package|box|carton|container|cup|bag)\b)", text, re.I
	) or not re.search(
		r"\b(?:extract\w*|pull\w*|pick\w*|unfold\w*|fold\w*|rub\w*|wip\w*|hold\w*|held|lift\w*|plac\w*|lay\w*|laid|tak\w*|took|remov\w*|carr\w*|handl\w*)\b",
		text,
		re.I,
	):
		return ""
	identity = (
		"Whenever the handled sheet is visible, it is the authored thin, lightweight, flexible paper or tissue sheet, "
		"with sheet edges, folds and creases visible. No unauthored text, logo, drawing or character artwork "
		"appears on this loose sheet. Reference figures and package graphics never transfer onto the sheet. "
	)
	if opening:
		return (
			identity
			+ "Future acquisition, folding or other handling need not have occurred in this opening frame."
		)
	return identity + (
		"Its visible material and identity persist through handling. "
		"If extraction is authored, only that sheet comes from the specified material source; "
		"the package, its printed graphics and all actor body parts remain their original objects."
	)


def roles(references):
	return {str(r.get("reference_role") or r.get("input_role") or "").lower() for r in references or []}


def product_only_instruction(references):
	if "product" not in roles(references) or roles(references) & ACTOR_ROLES:
		return ""
	return (
		"Product-only composition: the supplied product is the only physical foreground subject, "
		"resting untouched on its authored support. The setting contains no physical actors or toys. "
		"Figures on the package remain flat printed artwork attached to its surface throughout."
	)


def assert_product_only_direction(text):
	"""Reject explicit living-actor actions in an actor-free scene; never erase intent.

	This deliberately recognises concrete posture/action clauses, rather than
	guessing species from nouns or treating a printed illustration as live cast.
	Broader semantic contradictions remain part of script and visual review.
	"""
	for clause in re.split(r"[.!?;\n]+", str(text or "")):
		if re.search(r"\b(?:printed|artwork|illustration|depicts|depicting|logo)\b", clause, re.I):
			continue
		if re.search(
			r"\b(?:is|remains?)\s+(?:seated|sitting|kneeling)\b|\b(?:walks?|waves?|smiles?|kneels?)\b",
			clause,
			re.I,
		):
			raise ValueError(
				"Product-only scene declares no actor but directs one: "
				+ clause.strip()[:240]
				+ ". Remove the conflicting actor direction or bind the intended character reference."
			)


def reference_description(analysis, role):
	"""Separate fixed identity from pose captions and package artwork from cast."""
	analysis = analysis or {}
	appearance = analysis.get("identity_appearance") or ""
	if isinstance(appearance, dict):
		appearance = appearance.get("appearance") or ""
	if role in ACTOR_ROLES and appearance:
		return " ".join(str(appearance).split())
	description = " ".join(str(analysis.get("description") or "").split())
	if role == "product" and description:
		return (
			description
			+ " Any depicted characters are flat package artwork, not physical cast or separate objects."
		)
	return description

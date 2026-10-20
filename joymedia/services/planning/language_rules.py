"""Pure language, fidelity and camera vocabulary rules; no model calls or database access."""

import re

MIN_SENTENCE_COVERAGE = 0.5


def looks_english(text):
	"""Whether text is in English (Latin script without the accented letters of Vietnamese and similar languages).

	Punctuation such as arrows, dashes and curly quotes does not count against it: only letters do.
	"""
	import unicodedata

	decomposed = unicodedata.normalize("NFD", str(text or ""))
	return not any(
		unicodedata.combining(c) or c in "đĐ" or (c.isalpha() and ord(c) > 0x24F) for c in decomposed
	)


def _foreign_share(text):
	"""Share of a text's words written with letters English does not use (Vietnamese tone marks, đ, …)."""
	words = re.findall(r"[^\W\d_]+", str(text or ""))
	return sum(1 for word in words if not looks_english(word)) / len(words) if words else 0.0


def invented_names(english, source):
	"""Names in a translation that its source never mentions: words in the source language, or proper nouns.

	A translation adds no character, brand or place; a model that does is describing something else.
	"""
	source_words = {w.casefold() for w in re.findall(r"[^\W\d_]+", str(source or ""))}
	invented = set()
	# The first word of each sentence or clause is capitalised anyway; only later capitals can mark a name.
	for clause in re.split(r"(?<=[.!?:;])\s+|\n+", str(english or "")):
		for index, word in enumerate(re.findall(r"[^\W\d_]+", clause)):
			foreign = not looks_english(word)
			proper = index > 0 and word[:1].isupper() and not word.isupper() and len(word) > 2
			if (foreign or proper) and word.casefold() not in source_words:
				invented.add(word)
	# Capitalised ordinary words (sentence starts after a colon, "Close-up") are not names: keep only foreign words and
	# proper nouns the source language would also write with a capital letter.
	return {w for w in invented if not looks_english(w) or w.casefold() not in COMMON_CAPITALISED}


COMMON_CAPITALISED = {
	"camera",
	"close",
	"wide",
	"medium",
	"shot",
	"top",
	"down",
	"extreme",
	"slow",
	"motion",
	"eye",
	"level",
	"the",
	"a",
	"an",
	"sound",
	"light",
	"lighting",
	"effect",
	"effects",
	"angle",
	"movement",
	"split",
	"screen",
	"fast",
	"paced",
	"soft",
	"macro",
	"overhead",
	"front",
	"side",
	"view",
	"transition",
	"zoom",
	"pan",
	"tilt",
	"music",
	"voice",
	"over",
}


def is_english(text):
	"""English, allowing a few words in the source language such as a character's own name."""
	return bool(re.search(r"[A-Za-z]{2,}", str(text or ""))) and _foreign_share(text) < 0.25


def english_part(answer):
	"""The English in a translation answer, without the source text the model echoed around it.

	Small models often answer "<source>: <English>", "<source> translates to: <English>" or "<source> (<English>)".
	Every sentence or bracketed part that is mostly in the source language is dropped; English that merely names a
	character in the source language ("Gấu con knocks over…") is kept.
	"""
	text = re.sub(
		r"\btranslat(?:es|ed|ion)?\s+(?:in)?to\s*(?:english)?\s*:?", " : ", str(answer or ""), flags=re.I
	)
	pieces = re.split(r"(?<=[.!?])\s+|:\s+|\n+", text)
	kept = [piece.strip(" \t.:;,-\"'()[]") for piece in pieces]
	kept = [piece for piece in kept if piece and _foreign_share(piece) < 0.25]
	return ". ".join(kept).strip() + ("." if kept else "")


def _name_phrase(label):
	"""A character label's own name ("Gấu mẹ" from "Gấu mẹ (mother mascot…)"), as the sheet writes it."""
	return label.split(" (")[0].strip()


def keeps_every_sentence(source, rewrite):
	"""Whether the rewrite still says each sentence of the source: an overall share can hide a whole dropped sentence
	("Paper remains intact and unbroken, not torn", the scene's very claim, was lost at 82% overall)."""
	sentences = [
		part
		for part in re.split(r"(?<=[.!?;:])\s+", str(source or ""))
		if len(re.findall(r"[a-z]{4,}", part.lower())) >= 2
	]
	return all(beat_coverage(sentence, rewrite)[0] >= MIN_SENTENCE_COVERAGE for sentence in sentences)


def split_views(text):
	"""The numbered views a split-screen beat lists ("... qua 3 góc: 1. Bàn ăn gia đình 2. Trên thảm picnic 3. Trong
	túi xách"), in order; fewer than two is not a list."""
	views = [
		view.strip(" .;,\n")
		for view in re.findall(
			r"(?:^|[\s:;])\d[.)]\s*(.+?)(?=\s*(?:\n|;)?\s*\d[.)]\s|$)", str(text or ""), re.S
		)
	]
	return [view for view in views if view] if len(views) >= 2 else []


CAMERA_LABEL = re.compile(
	r"^\s*(?:camera(?:\s+(?:angle|movement|shot|move))?|shot|angle|góc quay|góc máy)\s*[:.]\s*", re.I
)


CAMERA_TERMS = (
	("siêu cận cảnh", "extreme close-up"),
	("cận cảnh", "close-up"),
	("trung cảnh", "medium shot"),
	("toàn cảnh", "wide shot"),
	("viễn cảnh", "long shot"),
	("góc nghiêng", "side angle"),
	("chính diện", "front view"),
	("ngang tầm mắt", "eye level"),
	("từ trên xuống", "top-down"),
	("từ dưới lên", "low angle"),
	("góc thấp", "low angle"),
	("góc cao", "high angle"),
	("chuyển động chậm", "slow motion"),
	("quay chậm", "slow motion"),
	("lia máy", "pan"),
	("đẩy máy", "push in"),
	("kéo máy", "pull out"),
	("máy đi theo", "tracking shot"),
	("xoay quanh", "orbit"),
	("cầm tay", "handheld"),
	("ánh sáng dịu nhẹ", "soft light"),
	("chia màn hình", "split screen"),
)


def camera_glossary(text):
	"""The camera terms of a Vietnamese camera direction, in order, with "->" read as "to": "wide shot to close-up"."""
	source = str(text or "").casefold()
	found = []
	for vietnamese, english in CAMERA_TERMS:
		for match in re.finditer(re.escape(vietnamese), source):
			if not any(start <= match.start() < end for start, end, _term in found):
				found.append((match.start(), match.end(), english))
	found.sort()
	parts = []
	for index, (start, _end, english) in enumerate(found):
		joined_by_arrow = index and re.search(r"->|→|=>", source[found[index - 1][1] : start])
		parts.append(("to " if joined_by_arrow else "") + english)
	return re.sub(r",\s+to ", " to ", ", ".join(parts))


FRAMING_WORDS = re.compile(
	r"\b(?:shot|close|wide|medium|angle|camera|zoom\w*|pan\w*|tilt\w*|view|slow|motion|top|down|macro|overhead|eye|level|"
	r"split|dolly|track\w*|push|pull)\b",
	re.I,
)


def with_glossary(translation, terms):
	"""The glossary's framing, then every clause of the translation the glossary does not restate.

	A clause naming the same framing in other words ("front angle" for "front view") is dropped; one the glossary does
	not cover ("very slight push-in", "hero packshot", "sparkling light around the pack") is kept."""
	covered = {word[:4] for word in re.findall(r"[a-z]{4,}", terms.casefold())} | {
		word for word in re.findall(r"\b[a-z]{2,3}\b", terms.casefold())
	}

	def restates(clause):
		words = {word[:4] for word in re.findall(r"[a-z]{4,}", clause.casefold())}
		return bool(FRAMING_WORDS.search(clause) and words & covered)

	clauses = [
		part.strip(" .")
		for part in re.split(r"(?<=[.!?])\s+|,\s*", str(translation or ""))
		if part.strip(" .")
	]
	kept = [clause[:1].upper() + clause[1:] for clause in clauses if not restates(clause)]
	return " ".join([terms[:1].upper() + terms[1:] + "."] + [f"{clause}." for clause in kept])


def camera_direction(text):
	"""The sheet's camera direction as one plain sentence: "Close-up of the table. Slow motion." (labels removed)."""
	parts = [
		CAMERA_LABEL.sub("", line + " ").strip(" .")
		for line in re.split(r"\n+|(?<=[.!?])\s+", str(text or ""))
	]
	parts = [part for part in parts if part and is_english(part)]
	return ". ".join(parts) + "." if parts else ""


def brand_words(product_name):
	"""The likely brand words in a product name, after its generic product words."""
	words = re.findall(r"[^\W\d_]+", str(product_name or ""))
	return {w.casefold() for w in words[1:] if w[:1].isupper() or (w.isupper() and len(w) > 1)}


COLOUR_TERMS = (
	("xanh lá cây", "green"),
	("xanh lá", "green"),
	("xanh lục", "green"),
	("xanh dương", "blue"),
	("xanh lam", "blue"),
	("xanh da trời", "sky blue"),
	("đỏ", "red"),
	("hồng", "pink"),
	("cam", "orange"),
	("vàng", "yellow"),
	("tím", "purple"),
	("nâu", "brown"),
	("đen", "black"),
	("trắng", "white"),
	("xám", "grey"),
	("ghi", "grey"),
	("kem", "cream"),
	("be", "beige"),
	# Paper products: "giấy lụa" is tissue paper (not lace), "rút" is pull-out.
	("giấy lụa rút", "pull-out tissue paper"),
	("giấy lụa", "tissue paper"),
	("khăn giấy rút", "pull-out tissues"),
	("khăn giấy", "tissues"),
	("giấy ăn", "paper napkins"),
	# "rút" is taking a sheet out of its pack; read as "draw" it puts a drawing on the paper.
	("vừa rút", "just pulled out of the pack"),
	("rút", "pull out of the pack (never draw)"),
)


def colour_terms(text):
	"""'hồng = pink' for each colour word the text uses (a word on its own, not inside another word)."""
	source, found = f" {str(text or '').casefold()} ", []
	for vietnamese, english in COLOUR_TERMS:
		if re.search(rf"(?<![\w]){re.escape(vietnamese)}(?![\w])", source) and not any(
			vietnamese in v for v, _e in found
		):
			found.append((vietnamese, english))
	return [f"{vietnamese} = {english}" for vietnamese, english in found]


STOPWORDS = frozenset(
	"this that with from into onto over under then than they them their there where while which will would "
	"each every some very much more most only just also have has had been being were what when who whom "
	"about after before above below between during through across along behind beside around against "
	"angle camera shot shots close closeup extreme medium wide macro super lighting light soft focus depth field "
	"smooth gentle slowly slow frame view scene style look feel image video".split()
)


def _words(text, minimum=4):
	"""Lower-case ASCII words (accents folded, so 'giấy' and 'giay' match) of at least `minimum` letters."""
	import re
	import unicodedata

	folded = (
		unicodedata.normalize("NFKD", str(text or "").replace("đ", "d").replace("Đ", "D"))
		.encode("ascii", "ignore")
		.decode()
	)
	return set(re.findall(r"[a-z]{%d,}" % minimum, folded.lower()))


def added_share(beat_text, rewrite, *allowed):
	"""Share of a rewrite's content words (by 4-letter stem) found neither in the beat nor in `allowed` (the cast)."""

	def stems(text):
		return {w[:4] for w in re.findall(r"[a-z]{4,}", str(text).lower()) if w not in STOPWORDS}

	have = stems(rewrite)
	return len(have - stems(" ".join((beat_text, *allowed)))) / len(have) if have else 0.0


def beat_coverage(beat_text, *texts):
	"""Fraction of the beat's content words (matched by 4-letter stem) that the plan still mentions.

	A rewrite that drops a required character, object or action scores low, so it can be held back for a
	person to review instead of silently replacing the advertiser's description.
	"""
	import re

	def stems(text):
		return {w[:4] for w in re.findall(r"[a-z]{4,}", str(text).lower()) if w not in STOPWORDS}

	wanted = stems(beat_text)
	if not wanted:
		return 1.0, []
	have = stems(" ".join(texts))
	missing = sorted(w for w in wanted if w not in have)
	return 1 - len(missing) / len(wanted), missing

"""Named prompt-service sampling profiles; creative/media inputs stay elsewhere."""

import json
import math
from pathlib import Path

PROFILE = Path(__file__).parents[2] / "workflow_adapters/graphs/prompt_sampling.json"


def _profiles():
	return json.loads(PROFILE.read_text())


def sampling(name):
	value = _profiles()[name]
	if set(value) != {"temperature", "max_tokens"}:
		raise ValueError("Prompt sampling requires temperature and max_tokens.")
	if (
		type(value["temperature"]) not in (int, float)
		or not math.isfinite(value["temperature"])
		or not 0 <= value["temperature"] <= 2
	):
		raise ValueError("Invalid sampling temperature.")
	if type(value["max_tokens"]) is not int or value["max_tokens"] <= 0:
		raise ValueError("Invalid sampling token budget.")
	return dict(value)

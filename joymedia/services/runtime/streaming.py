"""Streamed OpenAI-compatible chat completions.

The planner and vision models are reached through an SSH tunnel to the GPU host.
A request lost there leaves the local socket open with nothing to read, so a
plain request waits for its whole timeout (up to 600 s) before anyone notices.
A streamed answer is idle only when nothing arrives: the read timeout then
detects a lost request, while a long, healthy answer keeps flowing.
"""

import json
import time

import requests


def post_streamed(url, payload, *, idle_seconds, deadline_seconds):
	"""Return (response, content); content is None for a non-OK response."""
	response = requests.post(url, json={**payload, "stream": True}, timeout=(10, idle_seconds), stream=True)
	if not response.ok:
		return response, None
	with response:
		return response, read_chat_stream(response, time.monotonic() + deadline_seconds)


def read_chat_stream(response, deadline):
	"""Join the content deltas of a server-sent chat completion."""
	parts = []
	for line in response.iter_lines(decode_unicode=True):
		if time.monotonic() > deadline:
			raise requests.Timeout("The model answer exceeded its deadline.")
		if not line or not line.startswith("data:"):
			continue
		data = line[5:].strip()
		if data == "[DONE]":
			break
		choice = (json.loads(data).get("choices") or [{}])[0]
		parts.append((choice.get("delta") or {}).get("content") or "")
	return "".join(parts)

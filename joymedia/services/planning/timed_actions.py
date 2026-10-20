"""Authored action intervals in a workbook's Action cell (seconds within the shot)."""

import re

_LINE = re.compile(r"^\s*\[(\d+(?:\.\d+)?)\s*[-–→]\s*(\d+(?:\.\d+)?)\s*s?\]\s*(\S.*)$")


def read_timed_actions(text, duration):
    """Return explicit intervals, or None for legacy free prose. Never guess timing.

    Once any line starts a timed list, every nonempty line must be timed. Invalid
    lists fail planning rather than silently replacing the advertiser's pace.
    """
    lines = [line.strip() for line in str(text or '').splitlines() if line.strip()]
    if not any(re.match(r'^\s*\[\d', line) for line in lines):
        return None
    result, previous = [], 0.0
    for line in lines:
        match = _LINE.fullmatch(line)
        if not match:
            raise ValueError('Timed actions require one [start-end s] description per line.')
        start, end = float(match[1]), float(match[2])
        if start < previous - 1e-6 or end <= start or end > float(duration) + 1e-6:
            raise ValueError('Timed actions must be ordered, non-overlapping and inside the shot duration.')
        if abs(start - previous) > 1e-6:
            raise ValueError('Timed actions must cover the shot without gaps; describe any intended hold explicitly.')
        result.append({'start': start, 'end': end, 'action': match[3]})
        previous = end
    if abs(previous - float(duration)) > 1e-6:
        raise ValueError('Timed actions must finish at the shot duration.')
    if len(result) > 8 or any(len(row['action']) > 240 for row in result):
        raise ValueError('Use at most eight concise timed phases (240 characters each); split longer interactions into scenes.')
    return result

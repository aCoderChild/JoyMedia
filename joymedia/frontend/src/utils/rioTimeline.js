// Timeline order and clip identity belong to the edit, not to storyboard order.
export function orderTimelineClips(clips = []) {
  return [...clips].sort((a, b) =>
    Number(a.timeline_start_frame || 0) - Number(b.timeline_start_frame || 0) ||
    Number(a.clip_order || 0) - Number(b.clip_order || 0)
  );
}

export function shotIndexForClip(shots = [], clip) {
  return shots.findIndex((shot) => shot.name === clip?.shot);
}

export function clipAtSeconds(clips = [], seconds, fps) {
  const rate = Math.max(1, Number(fps) || 1);
  const ordered = orderTimelineClips(clips);
  return ordered.find((clip) => {
    const start = Number(clip.timeline_start_frame || 0) / rate;
    const end = start + Number(clip.duration_frames || 0) / rate;
    return start <= seconds && seconds < end;
  }) || ordered.filter((clip) => Number(clip.timeline_start_frame || 0) / rate <= seconds).at(-1) || ordered[0] || null;
}

export function sourceSecondsForTimeline(clip, seconds, fps) {
  const rate = Math.max(1, Number(fps) || 1);
  const start = Number(clip.timeline_start_frame || 0) / rate;
  const duration = Number(clip.duration_frames || 0) / rate;
  const offset = Math.max(0, Math.min(duration, seconds - start));
  return Number(clip.source_in_frame || 0) / rate + offset;
}

// The compact view groups audio by purpose. Separate backend track indices are
// preserved on each clip for editing/export; only the display lanes are packed.
export function layoutAudioLanes(clips = []) {
  const lanes = [];
  const roleOrder = { Voiceover: 0, BGM: 1, Music: 1, SFX: 2, Source: 3 };
  const roleFor = clip => clip.audio_role || 'Other';
  const ordered = [...clips].sort((a, b) =>
    (roleOrder[roleFor(a)] ?? 4) - (roleOrder[roleFor(b)] ?? 4) ||
    Number(a.timeline_start_frame || 0) - Number(b.timeline_start_frame || 0) ||
    Number(a.track_index || 0) - Number(b.track_index || 0)
  );
  for (const clip of ordered) {
    const role = roleFor(clip);
    const start = Number(clip.timeline_start_frame || 0);
    const end = start + Math.max(1, Number(clip.duration_frames || 0));
    let lane = lanes.find(row => row.role === role && row.end <= start);
    if (!lane) {
      lane = { role, end: 0, clips: [] };
      lanes.push(lane);
    }
    lane.clips.push(clip);
    lane.end = end;
  }
  return lanes;
}

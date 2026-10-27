/** Derive the next client action from current server facts, independent of providers. */
export function clientJourney({ hasStory, shots = [], approved, frames = null, framesError = false, busy, finishing, hasVideo }) {
  if (busy || finishing) return "working";
  if (!shots.length) return hasStory ? "plan" : "brief";
  if (!approved) return "approve";
  if (shots.every(hasVideo) && !frames?.some(frame=>frame.stale)) return "watch";
  if (framesError) return "retry";
  // Missing or incomplete responses must never imply preview approval.
  if (!frames || shots.some(shot => !frames.some(row => row.shot === shot.name))) return "loading";
  const needed = frames.filter(row => row.needs_keyframe);
  if (needed.some(row => !row.authored_frame && (!row.url || row.stale))) return "previews";
  if (needed.some(row => row.status !== "Approved")) return "review";
  return "render";
}

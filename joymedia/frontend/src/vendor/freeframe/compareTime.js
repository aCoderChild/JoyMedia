// Ported from FreeFrame (MIT, see LICENSE): apps/web/lib/compare-time.ts and
// apps/web/components/review/compare/use-synced-transport.ts @ 38298891.
// Pure time math for comparing two videos on one shared clock. Times in seconds.
import { onMounted, onUnmounted, ref } from 'vue';

export const tMax = (a, b) => Math.max(a.offset + a.duration, b.offset + b.duration);

/** Transport time -> this side's local media time (holds first/last frame). */
export const localTime = (t, side) => Math.min(Math.max(t - side.offset, 0), side.duration);

export const sideNotStarted = (t, side) => t < side.offset;

export const sideEnded = (t, side) => t >= side.offset + side.duration;

/** Seconds per frame; 0.04 (~25fps) when fps is unknown. */
export const frameStep = (fps) => (fps && fps > 0 ? 1 / fps : 0.04);

/** True when a slaved video has drifted past the correction threshold. */
export const driftedBeyond = (expected, actual, thresholdSec = 0.05) => Math.abs(actual - expected) > thresholdSec;

/**
 * Slave one side's <video> to transport time `t`.
 * Before its offset: paused on first frame. Past its end: paused on last frame.
 * Otherwise: playing (when the transport plays) with drift corrected past 50ms.
 * Paused drift is corrected only past ~one frame, so a paused seek does not thrash the decoder.
 */
export function applySideState(video, t, side, playing, pausedTol = frameStep()) {
  const expected = localTime(t, side);
  if (sideNotStarted(t, side) || sideEnded(t, side) || !playing) {
    if (!video.paused) video.pause();
    if (driftedBeyond(expected, video.currentTime, pausedTol)) video.currentTime = expected;
    return;
  }
  if (video.paused) Promise.resolve(video.play()).catch(() => {});
  if (driftedBeyond(expected, video.currentTime)) video.currentTime = expected;
}

/**
 * Next transport time: follow the audible video's own clock while it is active, else wall time.
 * Deriving T from the audible side makes its drift zero, so it is never seek-corrected (no crackle).
 */
export function computeNextT(prevT, dtWall, master, total) {
  const next = master ? master.mediaTime + master.offset : prevT + dtWall;
  return Math.min(Math.max(next, 0), total);
}

/** The audible side owns the clock only while live (not ended, no error) and inside its window. */
export const isMasterActive = (el, t, timing) =>
  !!el && !el.ended && !el.error && !sideNotStarted(t, timing) && !sideEnded(t, timing);

/**
 * One transport clock driving two <video> elements (Vue port of useSyncedTransport).
 * `videoA`/`videoB` are template refs; `audibleSide` is a ref of 'a' | 'b' | null.
 */
export function useSyncedTransport(videoA, videoB, audibleSide) {
  const t = ref(0);
  const total = ref(0);
  const isPlaying = ref(false);
  const timing = (el) => ({ offset: 0, duration: el && Number.isFinite(el.duration) ? el.duration : 0 });
  let raf = 0;
  let last = 0;

  const slaveBoth = (time, playing) => {
    if (videoA.value) applySideState(videoA.value, time, timing(videoA.value), playing);
    if (videoB.value) applySideState(videoB.value, time, timing(videoB.value), playing);
  };

  const tick = (now) => {
    const dt = last ? (now - last) / 1000 : 0;
    last = now;
    total.value = tMax(timing(videoA.value), timing(videoB.value));
    if (isPlaying.value) {
      const side = audibleSide.value;
      const el = side === 'a' ? videoA.value : side === 'b' ? videoB.value : null;
      const active = !!el && isMasterActive(el, t.value, timing(el));
      t.value = computeNextT(t.value, dt, active ? { mediaTime: el.currentTime, offset: 0 } : null, total.value);
      if (t.value >= total.value) isPlaying.value = false;
    }
    slaveBoth(t.value, isPlaying.value);
    raf = requestAnimationFrame(tick);
  };

  const seekTo = (time) => {
    t.value = Math.min(Math.max(time, 0), total.value);
    slaveBoth(t.value, isPlaying.value);
  };

  const toggle = () => {
    // Restart from 0 when toggling play at the very end.
    if (!isPlaying.value && t.value >= total.value) t.value = 0;
    isPlaying.value = !isPlaying.value;
  };

  onMounted(() => { raf = requestAnimationFrame(tick); });
  onUnmounted(() => cancelAnimationFrame(raf));
  return { t, total, isPlaying, toggle, seekTo };
}

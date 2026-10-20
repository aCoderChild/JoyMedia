// Browsers quantize media time to microseconds. Recover frame boundaries after
// seeking without assigning the previous frame due to floating-point truncation.
export function videoFrameIndex(seconds, fps, totalFrames) {
  return Math.max(0, Math.min(totalFrames - 1, Math.floor((Number(seconds) + 0.000001) * fps + 1e-7)));
}

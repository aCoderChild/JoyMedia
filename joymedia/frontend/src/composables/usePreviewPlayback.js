import { onBeforeUnmount } from 'vue';

// Client previews share one playback focus. The advanced editor keeps its own audio mixer.
let activePreview = null;
export function pausePreview() {
  activePreview?.pause();
  activePreview = null;
}
export function claimPreview(element) {
  if (activePreview && activePreview !== element) activePreview.pause();
  activePreview = element;
}
export function usePreviewPlayback() {
  const owned = new Set();
  function play(event) {
    const element = event?.target || event;
    if (!element?.pause) return;
    owned.add(element);
    claimPreview(element);
  }
  function pause() {
    for (const element of owned) element.pause();
    if (owned.has(activePreview)) activePreview = null;
  }
  const visibility = () => { if (document.hidden) pause(); };
  document.addEventListener('visibilitychange', visibility);
  onBeforeUnmount(() => {
    pause();
    document.removeEventListener('visibilitychange', visibility);
  });
  return { play, pause, pauseAll: pausePreview };
}

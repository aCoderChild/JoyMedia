import { onBeforeUnmount, unref, watch } from "vue";

function getRefValue(value) {
  return unref(value);
}

function getVideoElement(getVideo) {
  return getVideo?.() || null;
}

export function useTimelinePreviewEngine({ audioClips, fps, isPlaying, studioMode, getVideo }) {
  const audioElements = new Map();
  let animationFrame = null;

  function sourceFor(clip) {
    return clip?.source_file || clip?.source_url || "";
  }

  function ensureAudioElement(clip) {
    const source = sourceFor(clip);
    if (!source) return null;

    let audio = audioElements.get(clip.name);
    if (!audio) {
      audio = new Audio();
      audio.preload = "auto";
      audio.crossOrigin = "anonymous";
      audioElements.set(clip.name, audio);
    }
    if (audio.src !== source) {
      audio.src = source;
      audio.load();
    }
    return audio;
  }

  function gainFor(clip) {
    const gainDb = Number(clip?.gain_db || 0);
    return Math.max(0, Math.min(1, 10 ** (gainDb / 20)));
  }

  function syncAtFrame(frame) {
    if (getRefValue(studioMode) !== "edit") {
      pauseAll();
      return;
    }

    const currentFps = Math.max(1, Number(getRefValue(fps) || 24));
    const currentFrame = Math.max(0, Number(frame || 0));
    const clips = getRefValue(audioClips) || [];
    const activeNames = new Set();

    for (const clip of clips) {
      const audio = ensureAudioElement(clip);
      if (!audio) continue;
      activeNames.add(clip.name);

      const startFrame = Number(clip.timeline_start_frame || 0);
      const endFrame = Number(clip.timeline_end_frame || startFrame);
      const active = currentFrame >= startFrame && currentFrame < endFrame;
      if (!active) {
        audio.pause();
        continue;
      }

      const sourceFrame = Number(clip.source_in_frame || 0) + currentFrame - startFrame;
      const expectedTime = Math.max(0, sourceFrame / currentFps);
      audio.volume = gainFor(clip);
      if (!Number.isFinite(audio.currentTime) || Math.abs(audio.currentTime - expectedTime) > 0.08) {
        try {
          audio.currentTime = expectedTime;
        } catch (error) {
          console.warn("Unable to seek timeline audio:", error);
        }
      }
      if (getRefValue(isPlaying)) {
        audio.play().catch(() => {});
      } else {
        audio.pause();
      }
    }

    for (const [name, audio] of audioElements) {
      if (!activeNames.has(name)) {
        audio.pause();
        audioElements.delete(name);
      }
    }
  }

  function pauseAll() {
    for (const audio of audioElements.values()) audio.pause();
  }

  function tick() {
    animationFrame = null;
    const video = getVideoElement(getVideo);
    if (!video || getRefValue(studioMode) !== "edit") {
      pauseAll();
      return;
    }
    syncAtFrame(Math.round(Number(video.currentTime || 0) * Math.max(1, Number(getRefValue(fps) || 24))));
    if (getRefValue(isPlaying)) animationFrame = requestAnimationFrame(tick);
  }

  function start() {
    if (animationFrame == null) animationFrame = requestAnimationFrame(tick);
  }

  function stop() {
    if (animationFrame != null) cancelAnimationFrame(animationFrame);
    animationFrame = null;
    pauseAll();
  }

  watch([isPlaying, studioMode], ([playing, mode]) => {
    if (playing && mode === "edit") start();
    else stop();
  }, { immediate: true });

  watch(() => getRefValue(audioClips), () => {
    if (!getRefValue(isPlaying)) syncAtFrame(0);
  }, { deep: true });

  watch(() => getRefValue(isPlaying), (playing) => {
    if (playing) start();
    else pauseAll();
  });

  onBeforeUnmount(() => {
    stop();
    for (const audio of audioElements.values()) {
      audio.src = "";
    }
    audioElements.clear();
  });

  return { syncAtFrame, pauseAll };
}

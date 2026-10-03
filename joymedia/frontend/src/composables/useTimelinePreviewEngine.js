import { onBeforeUnmount, unref, watch } from "vue";

function getRefValue(value) {
  return unref(value);
}

function getVideoElement(getVideo) {
  return getVideo?.() || null;
}

function seekAudioSafely(audio, expectedTime) {
  if (audio.readyState >= 1) {
    audio.currentTime = expectedTime;
    return;
  }

  audio.addEventListener(
    "loadedmetadata",
    () => {
      audio.currentTime = expectedTime;
    },
    { once: true },
  );
}

export function useTimelinePreviewEngine({
  audioClips,
  fps,
  isPlaying,
  isMuted,
  studioMode,
  playheadFrame,
  timelineTotalFrames,
  renderTotalFrames,
  getVideo,
  onTimelineFrame,
  onTimelineEnd,
}) {
  const audioElements = new Map();
  let animationFrame = null;
  let timelineStartedAt = 0;
  let timelineStartFrame = 0;

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
      audioElements.set(clip.name, audio);
    }
    if (audio.dataset.joymediaSource !== source) {
      audio.pause();
      audio.src = source;
      audio.dataset.joymediaSource = source;
      audio.load();
    }
    return audio;
  }

  function gainFor(clip) {
    const gainDb = Number(clip?.gain_db || 0);
    return Math.max(0, Math.min(1, 10 ** (gainDb / 20)));
  }

  function syncAtFrame(frame) {
    if (getRefValue(studioMode) !== "edit" || getRefValue(isMuted)) {
      pauseAll();
      return;
    }

    const currentFps = Math.max(1, Number(getRefValue(fps) || 24));
    const currentFrame = Math.max(0, Number(frame || 0));
    const clips = getRefValue(audioClips) || [];
    const activeNames = new Set();

	for (const clip of clips) {
		if (!clip.enabled) continue;
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
          seekAudioSafely(audio, expectedTime);
        } catch (error) {
          console.warn("Unable to seek timeline audio:", error);
        }
      }
      if (getRefValue(isPlaying)) {
        if (audio.paused) {
          audio.play().catch((error) => {
            console.warn("Timeline audio playback failed", {
              clip: clip.name,
              source: sourceFor(clip),
              error,
            });
          });
        }
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

	function activeAudioClipsAtFrame(frame) {
		return (getRefValue(audioClips) || []).filter((clip) => {
			if (!clip.enabled) return false;
			const startFrame = Number(clip.timeline_start_frame || 0);
      const endFrame = Number(clip.timeline_end_frame || startFrame);
      return frame >= startFrame && frame < endFrame;
    });
  }

  function playAtFrame(frame) {
    if (getRefValue(studioMode) !== "edit" || getRefValue(isMuted)) return;

    const currentFps = Math.max(1, Number(getRefValue(fps) || 24));
    const currentFrame = Math.max(0, Number(frame || 0));

    for (const clip of activeAudioClipsAtFrame(currentFrame)) {
      const audio = ensureAudioElement(clip);
      if (!audio) continue;

      const sourceFrame =
        Number(clip.source_in_frame || 0) +
        currentFrame -
        Number(clip.timeline_start_frame || 0);

      const expectedTime = Math.max(0, sourceFrame / currentFps);
      seekAudioSafely(audio, expectedTime);
      audio.volume = gainFor(clip);
      audio.play().catch((error) => {
        console.warn("Unable to start timeline audio", clip.name, error);
      });
    }
    if (getRefValue(studioMode) === "edit") {
      timelineStartFrame = Math.max(0, Math.round(Number(frame || 0)));
      timelineStartedAt = performance.now();
    }
  }

  function syncTimelineVideo(frame) {
    const video = getVideoElement(getVideo);
    if (!video || getRefValue(studioMode) !== "edit" || video.readyState < 1) return;
    const currentFps = Math.max(1, Number(getRefValue(fps) || 24));
    const renderFrames = Math.max(0, Number(getRefValue(renderTotalFrames) || 0));
    const targetFrame = Math.min(Math.max(0, Number(frame || 0)), renderFrames);
    const targetTime = targetFrame / currentFps;
    if (Number.isFinite(targetTime) && Math.abs(Number(video.currentTime || 0) - targetTime) > 0.08) {
      video.currentTime = targetTime;
    }
  }

  function tickTimeline(now) {
    animationFrame = null;
    if (getRefValue(studioMode) !== "edit" || getRefValue(isMuted) || !getRefValue(isPlaying)) return;
    const currentFps = Math.max(1, Number(getRefValue(fps) || 24));
    const totalFrames = Math.max(
      0,
      Number(getRefValue(timelineTotalFrames) || getRefValue(renderTotalFrames) || 0),
    );
    const elapsedFrames = Math.round(((now - timelineStartedAt) / 1000) * currentFps);
    const frame = Math.min(totalFrames, timelineStartFrame + elapsedFrames);
    syncAtFrame(frame);
    syncTimelineVideo(frame);
    if (onTimelineFrame) onTimelineFrame(frame);
    if (frame >= totalFrames) {
      pauseAll();
      if (onTimelineEnd) onTimelineEnd();
      return;
    }
    animationFrame = requestAnimationFrame(tickTimeline);
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
    if (animationFrame != null) return;
    if (getRefValue(studioMode) === "edit") {
      timelineStartFrame = Math.max(0, Number(getRefValue(playheadFrame) || 0));
      timelineStartedAt = performance.now();
      animationFrame = requestAnimationFrame(tickTimeline);
    } else {
      animationFrame = requestAnimationFrame(tick);
    }
  }

  function stop() {
    if (animationFrame != null) cancelAnimationFrame(animationFrame);
    animationFrame = null;
    pauseAll();
  }

  watch([isPlaying, isMuted, studioMode], ([playing, muted, mode]) => {
    if (playing && !muted && mode === "edit") start();
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

  return { syncAtFrame, playAtFrame, pauseAll };
}

<template>
  <div class="playback-transport">
    <div class="flex items-center gap-2">
      <button type="button" class="transport-button" title="Previous frame" @click="$emit('step-frame', -1)">|◀</button>
      <button type="button" class="transport-button transport-play" :title="isPlaying ? 'Pause' : 'Play'" @click="$emit('toggle-play-pause')">
        {{ isPlaying ? '❚❚' : '▶' }}
      </button>
      <button type="button" class="transport-button" title="Next frame" @click="$emit('step-frame', 1)">▶|</button>
      <span class="font-mono text-[11px] font-semibold text-ink-primary">
        {{ currentTimelinePositionLabel }} / {{ formatSecondsLabel(timelineTotalSeconds) }}
      </span>
    </div>

    <input class="transport-scrubber" type="range" min="0" :max="Math.max(0, totalFrames)" step="1" :value="playheadFrame" aria-label="Seek video frame" @input="$emit('seek-frame', Number($event.target.value))" />

    <div class="flex items-center gap-1.5">
      <button type="button" class="transport-button" :title="isMuted ? 'Unmute' : 'Mute'" @click="$emit('toggle-mute')">{{ isMuted ? '🔇' : '🔊' }}</button>
      <button type="button" class="transport-button" title="Fullscreen" @click="$emit('fullscreen')">⛶</button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  activeSelectedShot: { type: Object, default: null },
  currentLang: { type: String, default: "vi" },
  currentTimelinePositionLabel: { type: String, default: "00:00" },
  isPlaying: { type: Boolean, default: false },
  isMuted: { type: Boolean, default: false },
  playheadFrame: { type: Number, default: 0 },
  totalFrames: { type: Number, default: 0 },
  timelineTotalSeconds: { type: Number, default: 0 },
});

defineEmits([
  "fullscreen",
  "seek-frame",
  "step-frame",
  "toggle-mute",
  "toggle-play-pause",
]);

function formatSecondsLabel(totalSeconds) {
  const safeSeconds = Math.max(0, Number(totalSeconds || 0));
  return `${String(Math.floor(safeSeconds / 60)).padStart(2, "0")}:${String(Math.floor(safeSeconds % 60)).padStart(2, "0")}`;
}
</script>

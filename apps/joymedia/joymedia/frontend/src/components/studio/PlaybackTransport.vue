<template>
  <div class="playback-transport">
    <div class="flex items-center gap-2">
      <button type="button" class="transport-button" title="Previous shot" @click="$emit('previous-shot')">|◀</button>
      <button type="button" class="transport-button transport-play" :title="isPlaying ? 'Pause' : 'Play'" @click="$emit('toggle-play-pause')">
        {{ isPlaying ? '❚❚' : '▶' }}
      </button>
      <button type="button" class="transport-button" title="Next shot" @click="$emit('next-shot')">▶|</button>
      <span class="font-mono text-[11px] font-semibold text-ink-primary">
        {{ currentTimelinePositionLabel }} / {{ formatSecondsLabel(timelineTotalSeconds) }}
      </span>
    </div>

    <div class="flex items-center gap-1.5">
      <button v-if="finalVideo?.file" type="button" class="transport-view-button" :class="{ active: previewSelection === 'full' }" @click="$emit('select-full-video')">Full</button>
      <button v-else-if="activeSelectedShot" type="button" class="transport-view-button" :class="{ active: previewSelection === 'shot' }" @click="$emit('select-shot-target', activeSelectedShot, selectedShotIndex)">
        {{ currentLang === 'vi' ? `Cảnh ${activeSelectedShot.shot_number}` : `Shot ${activeSelectedShot.shot_number}` }}
      </button>
      <button type="button" class="transport-button" title="Mute" @click="$emit('toggle-mute')">🔊</button>
      <button type="button" class="transport-button" title="Fullscreen" @click="$emit('fullscreen')">⛶</button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  activeSelectedShot: { type: Object, default: null },
  currentLang: { type: String, default: "vi" },
  currentTimelinePositionLabel: { type: String, default: "00:00" },
  finalVideo: { type: Object, default: null },
  isPlaying: { type: Boolean, default: false },
  previewSelection: { type: String, default: "full" },
  selectedShotIndex: { type: Number, default: 0 },
  timelineTotalSeconds: { type: Number, default: 0 },
});

defineEmits([
  "fullscreen",
  "next-shot",
  "previous-shot",
  "select-full-video",
  "select-shot-target",
  "toggle-mute",
  "toggle-play-pause",
]);

function formatSecondsLabel(totalSeconds) {
  const safeSeconds = Math.max(0, Number(totalSeconds || 0));
  return `${String(Math.floor(safeSeconds / 60)).padStart(2, "0")}:${String(Math.floor(safeSeconds % 60)).padStart(2, "0")}`;
}
</script>

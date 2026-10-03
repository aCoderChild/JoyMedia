<template>
  <div class="audio-timeline-tracks space-y-2">
    <div class="flex items-center justify-between px-1">
      <span class="text-[10px] font-mono font-bold text-ink-muted uppercase tracking-wider">Audio</span>
      <span class="text-[11px] text-ink-secondary">
        {{ audioTracks.length }} {{ currentLang === 'vi' ? 'track âm thanh' : 'audio tracks' }}
      </span>
    </div>

    <div class="audio-timeline-canvas" :style="{ width: `${timelineCanvasWidth}px` }">
        <div
          v-for="track in audioTracks"
          :key="track.trackIndex"
          class="audio-timeline-row"
        >
          <div class="audio-timeline-label">
            Audio {{ track.trackIndex + 1 }}<span v-if="track.trackIndex === 0"> · {{ currentLang === 'vi' ? 'Nguồn' : 'Source' }}</span>
          </div>
          <div class="audio-timeline-lane">
            <div v-if="!track.clips.length" class="audio-timeline-empty-label">
              {{ currentLang === 'vi' ? 'Không có audio nguồn' : 'No source audio' }}
            </div>
            <template v-for="clip in track.clips" :key="clip.name">
              <button
                v-if="clip.audio_role !== 'Source' || clip.source_has_audio"
                type="button"
                class="audio-timeline-clip"
                :class="[
                  clip.audio_role === 'Source' ? 'audio-timeline-source-clip' : 'audio-timeline-user-clip',
                  { selected: selectedClipName === clip.name }
                ]"
                :style="clipStyle(clip)"
                :title="clip.source_asset_name || clipLabel(clip)"
                @pointerdown="startMove(clip, $event)"
                @click="$emit('selectClip', clip)"
                @dblclick.stop="$emit('openInspector', clip)"
              >
                <span class="truncate">{{ clip.source_asset_name || clipLabel(clip) }}</span>
                <AudioWaveform :src="clip.source_file" />
                <span v-if="clip.audio_role !== 'Source'" class="audio-role-badge">{{ audioRoleLabel(clip.audio_role) }}</span>
              </button>
              <div v-else class="audio-timeline-empty-segment" :style="clipStyle(clip)">
                <span>{{ currentLang === 'vi' ? 'Không có audio nguồn' : 'No source audio' }}</span>
              </div>
            </template>
          </div>
        </div>

        <div
          v-if="audioTracks.length"
          class="audio-timeline-playhead"
          :style="{ left: `${playheadFrame * pixelsPerFrame}px` }"
          aria-hidden="true"
        />

    </div>

    <button type="button" class="audio-add-track" @click="$emit('openAudioPicker')">
      + {{ currentLang === 'vi' ? 'Thêm track âm thanh' : 'Add audio track' }}
    </button>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from "vue";
import AudioWaveform from "./AudioWaveform.vue";

const props = defineProps({
  audioClips: { type: Array, default: () => [] },
  selectedClipName: { type: String, default: null },
  totalFrames: { type: Number, default: 0 },
  playheadFrame: { type: Number, default: 0 },
  pixelsPerFrame: { type: Number, default: 2 },
  timelineCanvasWidth: { type: Number, default: 700 },
  currentLang: { type: String, default: "en" },
});

const emit = defineEmits(["selectClip", "openInspector", "openAudioPicker", "move"]);

const moveDrag = ref(null);

const audioTracks = computed(() => {
  const groups = new Map();
  for (const clip of props.audioClips) {
    const trackIndex = Math.max(0, Number(clip.track_index || 0));
    if (!groups.has(trackIndex)) groups.set(trackIndex, []);
    groups.get(trackIndex).push(clip);
  }
  const tracks = [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([trackIndex, clips]) => ({ trackIndex, clips }));
  if (!tracks.length) tracks.push({ trackIndex: 0, clips: [] });
  return tracks;
});

function clipStyle(clip) {
  return {
    left: `${Number(clip.timeline_start_frame || 0) * props.pixelsPerFrame}px`,
    width: `${Math.max(48, Number(clip.duration_frames || 0) * props.pixelsPerFrame)}px`,
  };
}

function clipLabel(clip) {
  if (clip?.shot_number) return props.currentLang === "vi" ? `Cảnh ${clip.shot_number}` : `Shot ${clip.shot_number}`;
  return `Clip ${clip?.clip_order || ""}`;
}

function audioRoleLabel(role) {
  if (role === "Voiceover") return props.currentLang === "vi" ? "LỜI" : "VOICE";
  if (role === "SFX") return props.currentLang === "vi" ? "HIỆU ỨNG" : "SFX";
  return props.currentLang === "vi" ? "NHẠC" : "MUSIC";
}

function startMove(clip, event) {
  if (clip.audio_role === "Source") return;
  event.currentTarget.setPointerCapture?.(event.pointerId);
  moveDrag.value = {
    clip,
    startX: event.clientX,
    originalStart: Number(clip.timeline_start_frame || 0),
  };
  window.addEventListener("pointermove", handleMove);
  window.addEventListener("pointerup", finishMove);
}

function handleMove(event) {
  if (!moveDrag.value) return;
  const delta = Math.round((event.clientX - moveDrag.value.startX) / props.pixelsPerFrame);
  moveDrag.value.nextStart = Math.max(0, moveDrag.value.originalStart + delta);
}

function finishMove() {
  const drag = moveDrag.value;
  moveDrag.value = null;
  window.removeEventListener("pointermove", handleMove);
  window.removeEventListener("pointerup", finishMove);
  if (drag && drag.nextStart != null && drag.nextStart !== drag.originalStart) {
    emit("move", {
      clip: drag.clip,
      timelineStartFrame: drag.nextStart,
      trackIndex: drag.clip.track_index,
    });
  }
}

onBeforeUnmount(() => {
  window.removeEventListener("pointermove", handleMove);
  window.removeEventListener("pointerup", finishMove);
});
</script>

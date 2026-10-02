<template>
  <div class="audio-timeline-tracks space-y-2">
    <div class="flex items-center justify-between px-1">
      <span class="text-[10px] font-mono font-bold text-ink-muted uppercase tracking-wider">Audio</span>
      <span class="text-[11px] text-ink-secondary">
        {{ audioTracks.length }} {{ currentLang === 'vi' ? 'track âm thanh' : 'audio tracks' }}
      </span>
    </div>

    <div class="audio-timeline-scroll">
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
                @click="$emit('selectClip', clip)"
              >
                <span class="truncate">{{ clip.source_asset_name || clipLabel(clip) }}</span>
                <span class="audio-waveform" aria-hidden="true">
                  <i v-for="bar in 16" :key="bar" :style="{ height: `${((bar * 5) % 9) + 3}px` }" />
                </span>
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

        <div v-if="!audioTracks.length" class="audio-timeline-empty-label">
          {{ currentLang === 'vi' ? 'Chưa có track âm thanh' : 'No audio tracks' }}
        </div>
      </div>
    </div>

    <button type="button" class="audio-add-track" @click="$emit('openAudioPicker')">
      + {{ currentLang === 'vi' ? 'Thêm track âm thanh' : 'Add audio track' }}
    </button>
  </div>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  audioClips: { type: Array, default: () => [] },
  selectedClipName: { type: String, default: null },
  totalFrames: { type: Number, default: 0 },
  playheadFrame: { type: Number, default: 0 },
  pixelsPerFrame: { type: Number, default: 2 },
  timelineCanvasWidth: { type: Number, default: 700 },
  currentLang: { type: String, default: "en" },
});

defineEmits(["selectClip", "openAudioPicker"]);

const audioTracks = computed(() => {
  const groups = new Map();
  for (const clip of props.audioClips) {
    const trackIndex = Math.max(0, Number(clip.track_index || 0));
    if (!groups.has(trackIndex)) groups.set(trackIndex, []);
    groups.get(trackIndex).push(clip);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([trackIndex, clips]) => ({ trackIndex, clips }));
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
</script>

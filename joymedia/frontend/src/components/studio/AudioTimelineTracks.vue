<template>
  <div class="audio-timeline-tracks space-y-2">
    <div class="flex items-center justify-between px-1">
      <span class="text-[10px] font-mono font-bold text-ink-muted uppercase tracking-wider">Audio</span>
      <span class="text-[11px] text-ink-secondary">
        {{ userAudioTracks.length }} {{ currentLang === 'vi' ? 'track âm thanh' : 'audio tracks' }}
      </span>
    </div>

    <div class="audio-timeline-row">
      <div class="audio-timeline-label">Audio 1 · {{ currentLang === 'vi' ? 'Nguồn' : 'Source' }}</div>
      <div class="audio-timeline-lane">
        <template v-for="clip in sourceVideoClips" :key="clip.name">
          <button
            v-if="clip.source_has_audio"
            type="button"
            class="audio-timeline-clip audio-timeline-source-clip"
            :class="{ selected: selectedClipName === clip.name }"
            :style="clipStyle(clip)"
            :title="clipLabel(clip)"
            @click="$emit('selectClip', clip)"
          >
            <span class="truncate">{{ clipLabel(clip) }}</span>
            <span class="audio-waveform" aria-hidden="true">
              <i v-for="bar in 12" :key="bar" :style="{ height: `${((bar * 5) % 9) + 3}px` }" />
            </span>
          </button>
          <div v-else class="audio-timeline-empty-segment" :style="clipStyle(clip)">
            <span v-if="sourceVideoClips.length === 1">{{ currentLang === 'vi' ? 'Không có audio nguồn' : 'No source audio' }}</span>
          </div>
        </template>
        <span v-if="!sourceVideoClips.length" class="audio-timeline-empty-label">
          {{ currentLang === 'vi' ? 'Chưa có audio nguồn' : 'No source audio' }}
        </span>
      </div>
    </div>

    <div
      v-for="track in userAudioTracks"
      :key="track.trackIndex"
      class="audio-timeline-row"
    >
      <div class="audio-timeline-label">Audio {{ track.trackIndex + 1 }}</div>
      <div class="audio-timeline-lane">
        <button
          v-for="clip in track.clips"
          :key="clip.name"
          type="button"
          class="audio-timeline-clip audio-timeline-user-clip"
          :class="{ selected: selectedClipName === clip.name }"
          :style="clipStyle(clip)"
          :title="clip.source_asset_name || clipLabel(clip)"
          @click="$emit('selectClip', clip)"
        >
          <span class="truncate">{{ clip.source_asset_name || clipLabel(clip) }}</span>
          <span class="audio-role-badge">{{ audioRoleLabel(clip.audio_role) }}</span>
        </button>
      </div>
    </div>

    <button
      type="button"
      class="audio-add-track"
      @click="$emit('openAudioPicker')"
    >
      + {{ currentLang === 'vi' ? 'Thêm track âm thanh' : 'Add audio track' }}
    </button>
  </div>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  sourceVideoClips: { type: Array, default: () => [] },
  audioClips: { type: Array, default: () => [] },
  selectedClipName: { type: String, default: null },
  totalFrames: { type: Number, default: 0 },
  currentLang: { type: String, default: "en" },
});

defineEmits(["selectClip", "openAudioPicker"]);

const userAudioTracks = computed(() => {
  const groups = new Map();
  for (const clip of props.audioClips) {
    const trackIndex = Math.max(1, Number(clip.track_index || 1));
    if (!groups.has(trackIndex)) groups.set(trackIndex, []);
    groups.get(trackIndex).push(clip);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([trackIndex, clips]) => ({ trackIndex, clips }));
});

function clipStyle(clip) {
  const total = Math.max(1, Number(props.totalFrames || 0));
  const start = Math.max(0, Number(clip.timeline_start_frame || 0));
  const duration = Math.max(1, Number(clip.duration_frames || 0));
  return {
    left: `${(start / total) * 100}%`,
    width: `${Math.max(2, (duration / total) * 100)}%`,
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

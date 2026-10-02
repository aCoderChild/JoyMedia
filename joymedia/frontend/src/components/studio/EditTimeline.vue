<template>
  <div class="edit-timeline-container rounded-2xl bg-surface-card border border-outline-border p-3 shadow-md select-none">
    <div class="flex items-center justify-between mb-2.5 px-1">
      <div class="flex items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider text-ink-primary flex items-center gap-1.5">
          <span>✂️</span>
          <span>{{ currentLang === 'vi' ? 'Trình dựng Video (Edit Timeline)' : 'Edit Timeline' }}</span>
        </span>
        <span class="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-muted text-indigo-400 border border-outline-border font-bold">
          {{ activeVideoClips.length }} {{ currentLang === 'vi' ? 'video' : 'video' }} · {{ totalSeconds?.toFixed(1) || 0 }}s
        </span>
      </div>

      <div class="flex items-center gap-2 text-xs">
        <span class="text-[11px] text-ink-muted">
          {{ currentLang === 'vi' ? 'Bấm clip để chỉnh sửa In/Out, tách hoặc chuyển cảnh trong Inspector.' : 'Click clip to adjust In/Out, split, or transitions in Inspector.' }}
        </span>
      </div>
    </div>

    <div class="w-full overflow-hidden rounded-xl border border-outline-border bg-surface-muted/40 p-2 space-y-3">
      <div>
        <div class="flex items-center gap-2 mb-1 px-1">
          <span class="text-[10px] font-mono font-bold text-ink-muted uppercase tracking-wider bg-surface-card px-2 py-0.5 rounded border border-outline-border flex items-center gap-1.5">
            <span>🎬</span>
            <span>Visuals</span>
            <span class="text-ink-secondary text-[9px] font-semibold border-l border-outline-border pl-1">Video</span>
          </span>
          <span class="text-[11px] text-ink-secondary">
            {{ activeVideoClips.length }} {{ currentLang === 'vi' ? 'phân đoạn hình ảnh' : 'video scenes' }}
          </span>
        </div>

        <EditTimelineTrack
          :clips="activeVideoClips"
          :fps="fps"
          :selected-clip-name="selectedClipName"
          :playhead-frame="playheadFrame"
          :busy="busy"
          :total-frames="totalFrames"
          :total-seconds="totalSeconds"
          :current-lang="currentLang"
          @select-clip="forwardSelectClip"
          @update:playhead-frame="$emit('update:playheadFrame', $event)"
          @trim="$emit('trim', $event)"
          @split="$emit('split', $event)"
          @duplicate="$emit('duplicate', $event)"
          @delete="$emit('delete', $event)"
          @reorder="$emit('reorder', $event)"
          @select-transition="$emit('selectTransition', $event)"
        />
      </div>

      <AudioTimelineTracks
        :source-video-clips="activeVideoClips"
        :audio-clips="activeAudioClips"
        :selected-clip-name="selectedClipName"
        :total-frames="totalFrames"
        :current-lang="currentLang"
        @select-clip="forwardSelectClip"
        @open-audio-picker="$emit('openAudioPicker')"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import AudioTimelineTracks from "./AudioTimelineTracks.vue";
import EditTimelineTrack from "./EditTimelineTrack.vue";

const props = defineProps({
  clips: { type: Array, default: () => [] },
  videoClips: { type: Array, default: () => [] },
  audioClips: { type: Array, default: () => [] },
  fps: { type: Number, default: 24 },
  selectedClipName: { type: String, default: null },
  playheadFrame: { type: Number, default: 0 },
  busy: { type: Boolean, default: false },
  totalFrames: { type: Number, default: 0 },
  totalSeconds: { type: Number, default: 0 },
  audioTrackAsset: { type: Object, default: null },
  currentLang: { type: String, default: "en" },
});

const emit = defineEmits([
  "selectClip",
  "update:playheadFrame",
  "trim",
  "split",
  "duplicate",
  "delete",
  "reorder",
  "selectTransition",
  "openAudioPicker",
]);

const activeVideoClips = computed(() => {
  if (props.videoClips?.length) return props.videoClips;
  return (props.clips || []).filter((clip) => (clip.track_type || "Video") === "Video");
});

const activeAudioClips = computed(() => {
  if (props.audioClips?.length) return props.audioClips;
  return (props.clips || []).filter((clip) => clip.track_type === "Audio");
});

function forwardSelectClip(...args) {
  emit("selectClip", ...args);
}
</script>

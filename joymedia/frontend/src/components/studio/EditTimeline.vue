<template>
  <div class="edit-timeline-container rounded-2xl bg-surface-card border border-outline-border p-3 shadow-md select-none">
    <!-- Header -->
    <div class="flex items-center justify-between mb-2.5 px-1">
      <div class="flex items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider text-ink-primary flex items-center gap-1.5">
          <span>✂️</span>
          <span>{{ currentLang === 'vi' ? 'Trình dựng Video (Edit Timeline)' : 'Edit Timeline' }}</span>
        </span>
        <span class="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-muted text-indigo-400 border border-outline-border font-bold">
          {{ activeVideoClips.length }} {{ currentLang === 'vi' ? 'Video Clips' : 'Video Clips' }} · {{ activeAudioClips.length }} {{ currentLang === 'vi' ? 'Audio' : 'Audio' }} · {{ totalSeconds?.toFixed(1) || 0 }}s
        </span>
      </div>

      <div class="flex items-center gap-2 text-xs">
        <span class="text-[11px] text-ink-muted">
          {{ currentLang === 'vi' ? 'Bấm clip để chỉnh sửa In/Out, tách hoặc chuyển cảnh trong Inspector.' : 'Click clip to adjust In/Out, split, or transitions in Inspector.' }}
        </span>
      </div>
    </div>

    <!-- Editorial Track Component -->
    <div class="w-full overflow-hidden rounded-xl border border-outline-border bg-surface-muted/40 p-2 space-y-3">
      <!-- 1. Video Track -->
      <div>
        <div class="flex items-center gap-2 mb-1 px-1">
          <span class="text-[10px] font-mono font-bold text-ink-muted uppercase tracking-wider bg-surface-card px-2 py-0.5 rounded border border-outline-border flex items-center gap-1">
            <span>🎬</span>
            <span>Video</span>
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
          @select-clip="$emit('selectClip', $event)"
          @update:playhead-frame="$emit('update:playheadFrame', $event)"
          @trim="$emit('trim', $event)"
          @split="$emit('split', $event)"
          @duplicate="$emit('duplicate', $event)"
          @delete="$emit('delete', $event)"
          @reorder="$emit('reorder', $event)"
          @select-transition="$emit('selectTransition', $event)"
        />
      </div>

      <!-- 2. Music / Audio Track Lane -->
      <div class="pt-2 border-t border-outline-border/60">
        <div class="flex items-center justify-between px-1 mb-1.5">
          <div class="flex items-center gap-2">
            <span class="text-[10px] font-mono font-bold text-indigo-400 uppercase tracking-wider bg-surface-card px-2 py-0.5 rounded border border-outline-border flex items-center gap-1">
              <span>🎵</span>
              <span>Music / Audio</span>
            </span>
            <span class="text-[11px] text-ink-secondary">
              {{ activeAudioClips.length ? `${activeAudioClips.length} ${currentLang === 'vi' ? 'bản âm thanh' : 'audio clips'}` : (currentLang === 'vi' ? 'Chưa có nhạc nền' : 'No music added') }}
            </span>
          </div>

          <button
            type="button"
            class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10.5px] font-semibold text-indigo-400 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 transition-colors cursor-pointer"
            @click="$emit('openAudioPicker')"
          >
            <span>+</span>
            <span>{{ currentLang === 'vi' ? 'Thêm Nhạc / Audio' : 'Add Music / Audio' }}</span>
          </button>
        </div>

        <!-- Real Audio Clips Container -->
        <div v-if="activeAudioClips.length" class="min-h-[44px] rounded-xl bg-surface-card border border-outline-border/80 p-1.5 flex items-center gap-2 overflow-x-auto">
          <div
            v-for="audioClip in activeAudioClips"
            :key="audioClip.name"
            class="timeline-audio-clip flex items-center justify-between gap-2 px-3 py-1.5 rounded-lg border transition-all cursor-pointer shrink-0 min-w-[200px]"
            :class="[
              selectedClipName === audioClip.name
                ? 'border-indigo-500 bg-indigo-500/20 ring-1 ring-indigo-500'
                : 'border-outline-border bg-surface-muted hover:border-indigo-400/60'
            ]"
            @click="$emit('selectClip', audioClip)"
          >
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-sm">🎵</span>
              <div class="min-w-0">
                <span class="block truncate text-xs font-semibold text-ink-primary">
                  {{ audioClip.source_asset_name || audioClip.audio_role || 'Audio Track' }}
                </span>
                <span class="block text-[10px] text-indigo-400 font-mono">
                  {{ audioClip.audio_role || 'BGM' }} · {{ audioClip.duration_seconds?.toFixed(1) || 0 }}s
                </span>
              </div>
            </div>

            <div class="flex items-center gap-1 shrink-0">
              <span v-if="audioClip.gain_db !== 0" class="text-[9px] font-mono px-1 py-0.2 rounded bg-surface-card border border-outline-border text-ink-muted">
                {{ audioClip.gain_db > 0 ? '+' : '' }}{{ audioClip.gain_db }}dB
              </span>
              <div class="flex items-end gap-0.5 h-3 opacity-60">
                <span v-for="i in 8" :key="i" class="w-0.5 bg-indigo-400 rounded-full" :style="{ height: `${((i * 7) % 10) + 2}px` }" />
              </div>
            </div>
          </div>
        </div>

        <!-- Empty Audio Track Placeholder with Add Action -->
        <div
          v-else
          class="h-10 rounded-xl bg-surface-card/60 border border-dashed border-outline-border flex items-center justify-between px-3 text-xs text-ink-muted cursor-pointer hover:border-indigo-500/50 hover:bg-surface-card transition-all"
          @click="$emit('openAudioPicker')"
        >
          <div class="flex items-center gap-2">
            <span class="text-sm opacity-60">🎵</span>
            <span class="text-[11px]">
              {{ currentLang === 'vi' ? 'Kéo thả file âm thanh hoặc bấm để chọn Nhạc nền / Voiceover' : 'Add background music or voiceover to the timeline' }}
            </span>
          </div>
          <span class="text-[11px] font-semibold text-indigo-400 hover:underline">
            + {{ currentLang === 'vi' ? 'Chọn Audio' : 'Browse Audio' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
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
</script>

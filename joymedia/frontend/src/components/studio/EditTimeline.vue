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
          {{ activeVideoClips.length }} {{ currentLang === 'vi' ? 'Video Clips' : 'Video Clips' }} · {{ activeAudioClips.length }} {{ currentLang === 'vi' ? 'Audio clips đã thêm' : 'added audio clips' }} · {{ totalSeconds?.toFixed(1) || 0 }}s
        </span>
      </div>

      <div class="flex items-center gap-2 text-xs">
        <span class="text-[11px] text-ink-muted">
          {{ currentLang === 'vi' ? 'Bấm clip để chỉnh sửa In/Out, tách hoặc chuyển cảnh trong Inspector.' : 'Click clip to adjust In/Out, split, or transitions in Inspector.' }}
        </span>
      </div>
    </div>

    <!-- Editorial Track Component with 4 Semantic Lanes -->
    <div class="w-full overflow-hidden rounded-xl border border-outline-border bg-surface-muted/40 p-2 space-y-3">
      <!-- 1. Visuals / Video Track -->
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

      <!-- 2. Voice Track (Voiceover) -->
      <div class="pt-2 border-t border-outline-border/60">
        <div class="flex items-center justify-between px-1 mb-1.5">
          <div class="flex items-center gap-2">
            <span class="text-[10px] font-mono font-bold text-sky-400 uppercase tracking-wider bg-surface-card px-2 py-0.5 rounded border border-outline-border flex items-center gap-1">
              <span>🎙️</span>
              <span>Voice</span>
            </span>
            <span class="text-[11px] text-ink-secondary">
              {{ voiceClips.length ? `${voiceClips.length} ${currentLang === 'vi' ? 'giọng đọc' : 'voiceover clips'}` : (currentLang === 'vi' ? 'Chưa có lời bình' : 'No voiceover') }}
            </span>
          </div>

          <button
            type="button"
            class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10.5px] font-semibold text-sky-400 bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/20 transition-colors cursor-pointer"
            @click="$emit('openAudioPicker', 'Voiceover')"
          >
            <span>+</span>
            <span>{{ currentLang === 'vi' ? 'Thêm Voice' : 'Add Voice' }}</span>
          </button>
        </div>

        <!-- Voice Clips Container -->
        <div v-if="voiceClips.length" class="min-h-[40px] rounded-xl bg-surface-card border border-outline-border/80 p-1.5 flex items-center gap-2 overflow-x-auto">
          <div
            v-for="audioClip in voiceClips"
            :key="audioClip.name"
            class="timeline-audio-clip flex items-center justify-between gap-2 px-3 py-1.5 rounded-lg border transition-all cursor-pointer shrink-0 min-w-[180px]"
            :class="[
              selectedClipName === audioClip.name
                ? 'border-sky-500 bg-sky-500/20 ring-1 ring-sky-500'
                : 'border-outline-border bg-surface-muted hover:border-sky-400/60'
            ]"
            @click="$emit('selectClip', audioClip)"
          >
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-sm">🎙️</span>
              <div class="min-w-0">
                <span class="block truncate text-xs font-semibold text-ink-primary">
                  {{ audioClip.source_asset_name || 'Voiceover' }}
                </span>
                <span class="block text-[10px] text-sky-400 font-mono">
                  Voice · {{ audioClip.duration_seconds?.toFixed(1) || 0 }}s
                </span>
              </div>
            </div>
            <span v-if="audioClip.gain_db !== 0" class="text-[9px] font-mono px-1 py-0.2 rounded bg-surface-card border border-outline-border text-ink-muted">
              {{ audioClip.gain_db > 0 ? '+' : '' }}{{ audioClip.gain_db }}dB
            </span>
          </div>
        </div>
      </div>

      <!-- 3. Effects Track (SFX) -->
      <div class="pt-2 border-t border-outline-border/60">
        <div class="flex items-center justify-between px-1 mb-1.5">
          <div class="flex items-center gap-2">
            <span class="text-[10px] font-mono font-bold text-amber-400 uppercase tracking-wider bg-surface-card px-2 py-0.5 rounded border border-outline-border flex items-center gap-1">
              <span>⚡</span>
              <span>Effects</span>
            </span>
            <span class="text-[11px] text-ink-secondary">
              {{ sfxClips.length ? `${sfxClips.length} ${currentLang === 'vi' ? 'hiệu ứng âm thanh' : 'sound effects'}` : (currentLang === 'vi' ? 'Chưa có SFX' : 'No sound effects') }}
            </span>
          </div>

          <button
            type="button"
            class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10.5px] font-semibold text-amber-400 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/20 transition-colors cursor-pointer"
            @click="$emit('openAudioPicker', 'SFX')"
          >
            <span>+</span>
            <span>{{ currentLang === 'vi' ? 'Thêm SFX' : 'Add SFX' }}</span>
          </button>
        </div>

        <!-- SFX Clips Container -->
        <div v-if="sfxClips.length" class="min-h-[40px] rounded-xl bg-surface-card border border-outline-border/80 p-1.5 flex items-center gap-2 overflow-x-auto">
          <div
            v-for="audioClip in sfxClips"
            :key="audioClip.name"
            class="timeline-audio-clip flex items-center justify-between gap-2 px-3 py-1.5 rounded-lg border transition-all cursor-pointer shrink-0 min-w-[180px]"
            :class="[
              selectedClipName === audioClip.name
                ? 'border-amber-500 bg-amber-500/20 ring-1 ring-amber-500'
                : 'border-outline-border bg-surface-muted hover:border-amber-400/60'
            ]"
            @click="$emit('selectClip', audioClip)"
          >
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-sm">⚡</span>
              <div class="min-w-0">
                <span class="block truncate text-xs font-semibold text-ink-primary">
                  {{ audioClip.source_asset_name || 'SFX' }}
                </span>
                <span class="block text-[10px] text-amber-400 font-mono">
                  SFX · {{ audioClip.duration_seconds?.toFixed(1) || 0 }}s
                </span>
              </div>
            </div>
            <span v-if="audioClip.gain_db !== 0" class="text-[9px] font-mono px-1 py-0.2 rounded bg-surface-card border border-outline-border text-ink-muted">
              {{ audioClip.gain_db > 0 ? '+' : '' }}{{ audioClip.gain_db }}dB
            </span>
          </div>
        </div>
      </div>

      <!-- 4. Music Track (Music / Audio BGM) -->
      <div class="pt-2 border-t border-outline-border/60">
        <div class="flex items-center justify-between px-1 mb-1.5">
          <div class="flex items-center gap-2">
            <span class="text-[10px] font-mono font-bold text-indigo-400 uppercase tracking-wider bg-surface-card px-2 py-0.5 rounded border border-outline-border flex items-center gap-1">
              <span>🎵</span>
              <span>Music / Audio</span>
            </span>
            <span class="text-[11px] text-ink-secondary">
              {{ musicClips.length ? `${musicClips.length} ${currentLang === 'vi' ? 'bản nhạc nền' : 'music tracks'}` : (currentLang === 'vi' ? 'Chưa có nhạc nền' : 'No music added') }}
            </span>
          </div>

          <button
            type="button"
            class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10.5px] font-semibold text-indigo-400 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 transition-colors cursor-pointer"
            @click="$emit('openAudioPicker', 'BGM')"
          >
            <span>+</span>
            <span>{{ currentLang === 'vi' ? 'Thêm Nhạc / Audio' : 'Add Music / Audio' }}</span>
          </button>
        </div>

        <!-- Music Clips Container -->
        <div v-if="musicClips.length" class="min-h-[44px] rounded-xl bg-surface-card border border-outline-border/80 p-1.5 flex items-center gap-2 overflow-x-auto">
          <div
            v-for="audioClip in musicClips"
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
                  {{ audioClip.source_asset_name || audioClip.audio_role || 'Background Music' }}
                </span>
                <span class="block text-[10px] text-indigo-400 font-mono">
                  Music · {{ audioClip.duration_seconds?.toFixed(1) || 0 }}s
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

        <!-- Empty Music Track Placeholder with Add Action -->
        <div
          v-else
          class="h-10 rounded-xl bg-surface-card/60 border border-dashed border-outline-border flex items-center justify-between px-3 text-xs text-ink-muted cursor-pointer hover:border-indigo-500/50 hover:bg-surface-card transition-all"
          @click="$emit('openAudioPicker', 'BGM')"
        >
          <div class="flex items-center gap-2">
            <span class="text-sm opacity-60">🎵</span>
            <span class="text-[11px]">
              {{ currentLang === 'vi' ? 'Kéo thả file âm thanh hoặc bấm để chọn Nhạc nền' : 'Add background music to the timeline' }}
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

const voiceClips = computed(() => {
  return activeAudioClips.value.filter((clip) => clip.audio_role === "Voiceover");
});

const sfxClips = computed(() => {
  return activeAudioClips.value.filter((clip) => clip.audio_role === "SFX");
});

const musicClips = computed(() => {
  return activeAudioClips.value.filter((clip) => clip.audio_role !== "Voiceover" && clip.audio_role !== "SFX");
});

function forwardSelectClip(...args) {
  emit("selectClip", ...args);
}
</script>

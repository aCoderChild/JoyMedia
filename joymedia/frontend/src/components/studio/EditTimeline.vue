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
          {{ clips.length }} {{ currentLang === 'vi' ? 'Clips' : 'Clips' }} · {{ totalSeconds?.toFixed(1) || 0 }}s
        </span>
      </div>

      <div class="flex items-center gap-2 text-xs">
        <span class="text-[11px] text-ink-muted">
          {{ currentLang === 'vi' ? 'Bấm clip để chỉnh sửa In/Out, tách hoặc chuyển cảnh trong Inspector.' : 'Click clip to adjust In/Out, split, or transitions in Inspector.' }}
        </span>
      </div>
    </div>

    <!-- Editorial Track Component -->
    <div class="w-full overflow-hidden rounded-xl border border-outline-border bg-surface-muted/40 p-2">
      <!-- Track Label: Video 0 -->
      <div class="flex items-center gap-2 mb-1 px-1">
        <span class="text-[10px] font-mono font-bold text-ink-muted uppercase tracking-wider bg-surface-card px-1.5 py-0.5 rounded border border-outline-border">
          Video 0
        </span>
      </div>

      <EditTimelineTrack
        :clips="clips"
        :fps="fps"
        :selected-clip-name="selectedClipName"
        :playhead-frame="playheadFrame"
        :busy="busy"
        :total-frames="totalFrames"
        :total-seconds="totalSeconds"
        @select-clip="$emit('selectClip', $event)"
        @update:playhead-frame="$emit('update:playheadFrame', $event)"
        @trim="$emit('trim', $event)"
        @split="$emit('split', $event)"
        @duplicate="$emit('duplicate', $event)"
        @delete="$emit('delete', $event)"
        @reorder="$emit('reorder', $event)"
        @select-transition="$emit('selectTransition', $event)"
      />

      <!-- Secondary Track Label: Audio 0 (Ambient / Music Track lane) -->
      <div class="mt-3 pt-2 border-t border-outline-border/60">
        <div class="flex items-center justify-between px-1 mb-1">
          <div class="flex items-center gap-2">
            <span class="text-[10px] font-mono font-bold text-ink-muted uppercase tracking-wider bg-surface-card px-1.5 py-0.5 rounded border border-outline-border">
              Audio 0
            </span>
            <span class="text-[11px] text-ink-secondary">
              {{ audioTrackAsset ? audioTrackAsset.asset_name : (currentLang === 'vi' ? 'Nhạc nền tự động / Mixed Audio' : 'Project Audio / Mixed') }}
            </span>
          </div>
          <span class="text-[10px] text-ink-muted font-mono">{{ totalSeconds?.toFixed(1) || 0 }}s</span>
        </div>

        <div class="h-8 rounded-lg bg-surface-card border border-outline-border/80 flex items-center px-3 gap-1 overflow-hidden">
          <div class="flex items-end gap-1 h-4 w-full opacity-60">
            <span v-for="i in 40" :key="i" class="w-1 bg-indigo-400 rounded-full" :style="{ height: `${((i * 17) % 14) + 4}px` }" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import EditTimelineTrack from "./EditTimelineTrack.vue";

const props = defineProps({
  clips: { type: Array, default: () => [] },
  fps: { type: Number, default: 24 },
  selectedClipName: { type: String, default: null },
  playheadFrame: { type: Number, default: 0 },
  busy: { type: Boolean, default: false },
  totalFrames: { type: Number, default: 0 },
  totalSeconds: { type: Number, default: 0 },
  audioTrackAsset: { type: Object, default: null },
  currentLang: { type: String, default: "en" },
});

defineEmits([
  "selectClip",
  "update:playheadFrame",
  "trim",
  "split",
  "duplicate",
  "delete",
  "reorder",
  "selectTransition",
]);
</script>

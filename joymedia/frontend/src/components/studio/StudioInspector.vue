<template>
  <aside
    class="studio-inspector shrink-0 overflow-hidden border-t xl:border-t-0 xl:border-l border-outline-border flex flex-col bg-surface-card transition-[width] duration-200 select-none z-10"
    :class="open ? 'w-full xl:w-[320px]' : 'w-0 border-0'"
  >
    <!-- Contextual Inspector Top Header (Derived from Selection) -->
    <div class="p-3 border-b border-outline-border flex items-center justify-between gap-2 bg-surface-muted/60">
      <div class="flex items-center gap-2 min-w-0">
        <span class="text-sm">{{ inspectorHeaderIcon }}</span>
        <h3 class="text-xs font-bold text-ink-primary truncate">{{ inspectorHeaderTitle }}</h3>
      </div>

      <div class="flex items-center gap-1">
        <button
          type="button"
          class="p-1 rounded-lg text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors cursor-pointer"
          :title="currentLang === 'vi' ? 'Đóng' : 'Close'"
          @click="$emit('update:open', false)"
        >
          ✕
        </button>
      </div>
    </div>

    <!-- Inspector Body (Driven purely by selection) -->
    <div class="p-3 overflow-y-auto flex-1 space-y-3">
      <!-- 1. EDIT MODE: Clip Inspector -->
      <template v-if="studioMode === 'edit' && selectedClip">
        <div class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-ink-primary flex items-center gap-1.5">
              <span>✂️</span>
              <span>{{ `Clip ${selectedClip.clip_order || 1}` }}</span>
            </span>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-card border border-outline-border text-indigo-400 font-bold">
              {{ selectedClip.duration_seconds?.toFixed(2) }}s · {{ selectedClip.duration_frames }}f
            </span>
          </div>

          <!-- IN / OUT Frames -->
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">IN FRAME</span>
              <span class="font-mono font-bold text-ink-primary text-sm">{{ selectedClip.source_in_frame }}</span>
            </div>
            <div class="p-2 rounded-xl bg-surface-card border border-outline-border">
              <span class="block text-[10px] text-ink-muted font-semibold">OUT FRAME</span>
              <span class="font-mono font-bold text-ink-primary text-sm">{{ selectedClip.source_out_frame }}</span>
            </div>
          </div>

          <!-- Transition to Next -->
          <div class="space-y-1.5 pt-1">
            <label class="block text-[11px] font-semibold text-ink-secondary">
              {{ currentLang === 'vi' ? 'Chuyển cảnh (Transition):' : 'Transition to next:' }}
            </label>
            <div class="flex items-center gap-2">
              <select
                :value="selectedClip.transition_to_next || 'Cut'"
                class="flex-1 px-2.5 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary cursor-pointer"
                :disabled="timelineBusy"
                @change="$emit('changeTransition', $event.target.value)"
              >
                <option value="Cut">Cut (Cắt)</option>
                <option value="Dissolve">Dissolve (Hòa tan)</option>
                <option value="Fade">Fade (Mờ dần)</option>
              </select>
              <input
                v-if="selectedClip.transition_to_next && selectedClip.transition_to_next !== 'Cut'"
                type="number"
                min="4"
                max="48"
                :value="selectedClip.transition_frames || 12"
                class="w-16 px-2 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary font-mono text-center"
                :title="currentLang === 'vi' ? 'Số khung hình chuyển tiếp' : 'Transition frames'"
                :disabled="timelineBusy"
                @change="$emit('changeTransitionFrames', Number($event.target.value))"
              />
            </div>
          </div>

          <!-- Actions: Split, Duplicate, Delete -->
          <div class="grid grid-cols-3 gap-1.5 pt-2 border-t border-outline-border">
            <button
              type="button"
              class="py-1.5 px-2 rounded-xl bg-surface-card hover:bg-surface-hover text-ink-primary border border-outline-border text-xs font-semibold flex items-center justify-center gap-1 cursor-pointer transition-colors"
              :disabled="timelineBusy"
              @click="$emit('splitClip')"
            >
              <span>✂</span>
              <span>{{ currentLang === 'vi' ? 'Tách' : 'Split' }}</span>
            </button>
            <button
              type="button"
              class="py-1.5 px-2 rounded-xl bg-surface-card hover:bg-surface-hover text-ink-primary border border-outline-border text-xs font-semibold flex items-center justify-center gap-1 cursor-pointer transition-colors"
              :disabled="timelineBusy"
              @click="$emit('duplicateClip', selectedClip)"
            >
              <span>⧉</span>
              <span>{{ currentLang === 'vi' ? 'Nhân đôi' : 'Duplicate' }}</span>
            </button>
            <button
              type="button"
              class="py-1.5 px-2 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 text-xs font-semibold flex items-center justify-center gap-1 cursor-pointer transition-colors"
              :disabled="timelineBusy"
              @click="$emit('deleteClip', selectedClip)"
            >
              <span>⌫</span>
              <span>{{ currentLang === 'vi' ? 'Xóa' : 'Delete' }}</span>
            </button>
          </div>
        </div>

        <!-- Source Shot Info & Outdated Sync -->
        <div v-if="selectedClipSourceShot" class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-2.5 text-xs">
          <div class="flex items-center justify-between">
            <span class="font-bold text-ink-primary">🎯 {{ currentLang === 'vi' ? 'Cảnh gốc' : 'Source Shot' }}</span>
            <span class="text-[10px] font-bold text-indigo-400 bg-surface-card px-2 py-0.5 rounded border border-outline-border">
              Cảnh {{ selectedClipSourceShot.shot_number }}
            </span>
          </div>

          <div v-if="selectedClipSourceShot.generation_prompt" class="p-2 rounded-xl bg-surface-card border border-outline-border">
            <span class="block text-[10px] font-semibold text-ink-muted mb-0.5">PROMPT</span>
            <p class="text-[11px] text-ink-secondary line-clamp-3 font-mono">{{ selectedClipSourceShot.generation_prompt }}</p>
          </div>

          <!-- Stale source update button -->
          <button
            v-if="selectedClip?.is_outdated"
            type="button"
            class="w-full py-2 px-3 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold flex items-center justify-center gap-1.5 shadow-sm transition-colors cursor-pointer"
            :disabled="timelineBusy"
            @click="$emit('updateSourceForSelectedClip')"
          >
            ↻ {{ currentLang === 'vi' ? 'Cập nhật clip từ cảnh mới' : 'Update clip from new shot output' }}
          </button>
          <button
            type="button"
            class="w-full py-2 px-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold flex items-center justify-center gap-1.5 shadow-sm transition-colors cursor-pointer"
            :disabled="timelineBusy || regeneratingSource"
            @click="$emit('regenerateSourceForSelectedClip')"
          >
            <span v-if="regeneratingSource" class="lucide-refresh-cw size-3 animate-spin" />
            <span v-else>↻</span>
            <span>{{ currentLang === 'vi' ? 'Tạo lại cảnh gốc' : 'Regenerate source' }}</span>
          </button>
        </div>
      </template>

      <!-- 2. ASSET SELECTED: Multimodal Asset Inspector -->
      <template v-else-if="selectedTarget === 'asset' && selectedAsset">
        <div class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-ink-primary">📦 {{ currentLang === 'vi' ? 'Chi tiết tư liệu' : 'Asset Details' }}</span>
            <span class="text-[10px] font-semibold px-2 py-0.5 rounded bg-surface-card text-indigo-400 border border-outline-border">
              {{ selectedAsset.media_type }}
            </span>
          </div>

          <!-- Multimodal MediaThumbnail Component -->
          <div class="w-full rounded-xl overflow-hidden border border-outline-border">
            <MediaThumbnail
              :src="selectedAsset.file"
              :media-type="selectedAsset.media_type"
              :alt="selectedAsset.asset_name"
              :duration="selectedAsset.duration_seconds"
              aspect="aspect-video"
            />
          </div>

          <div>
            <span class="block text-xs font-bold text-ink-primary">{{ selectedAsset.asset_name }}</span>
            <span class="block text-[11px] text-ink-muted mt-0.5">
              {{ selectedAsset.media_type }} · {{ selectedAsset.asset_category || 'Reference' }}
            </span>
          </div>

          <!-- Explicit Reference Role Selection -->
          <div class="space-y-1.5 pt-1">
            <label class="block text-[11px] font-semibold text-ink-secondary">
              {{ currentLang === 'vi' ? 'Vai trò trong dự án (Reference Role):' : 'Project Reference Role:' }}
            </label>
            <select
              :value="selectedAsset.reference_role || 'Product'"
              class="w-full px-2.5 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary cursor-pointer focus:outline-none focus:border-indigo-500"
              @change="$emit('updateAssetRole', selectedAsset, $event.target.value)"
            >
              <option value="Product">👟 Product (Sản phẩm)</option>
              <option value="Character">👤 Character (Nhân vật)</option>
              <option value="Environment">🏞️ Environment (Bối cảnh)</option>
              <option value="Style">🎨 Style (Phong cách)</option>
              <option value="Motion">🏃 Motion (Chuyển động)</option>
              <option value="Audio">🔊 Audio (Âm thanh)</option>
              <option value="General">📎 General (Chung)</option>
            </select>
          </div>

          <!-- Actions -->
          <div class="pt-2 border-t border-outline-border flex flex-col gap-2">
            <button
              v-if="activeSelectedShot && selectedAsset.media_type === 'Image'"
              type="button"
              class="w-full jm-btn-primary text-xs !py-1.5"
              @click="$emit('applyAssetToShot', selectedAsset, activeSelectedShot)"
            >
              {{ currentLang === 'vi' ? `Gán vào Cảnh ${activeSelectedShot.shot_number}` : `Apply to Shot ${activeSelectedShot.shot_number}` }}
            </button>
            <button
              type="button"
              class="w-full py-1.5 px-2.5 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 text-xs font-semibold transition-colors cursor-pointer"
              @click="$emit('removeAsset', selectedAsset)"
            >
              {{ currentLang === 'vi' ? 'Bỏ tư liệu khỏi dự án' : 'Remove from Project' }}
            </button>
          </div>
        </div>
      </template>

      <!-- 3. KEYFRAME SELECTED: Keyframe Reference Inspector -->
      <template v-else-if="(selectedTarget === 'keyframe-start' || selectedTarget === 'keyframe-end') && activeSelectedShot">
        <div class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-ink-primary flex items-center gap-1.5">
              <span class="text-indigo-400">◆</span>
              <span>{{ selectedTarget === 'keyframe-start' ? 'Start Reference' : (generationMode === 'Continuous' ? 'Continuity Frame' : 'End Reference') }}</span>
            </span>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-card border border-outline-border text-indigo-400 font-bold">
              {{ selectedTarget === 'keyframe-start' ? formatShotKeyframeTime(selectedShotIndex, 0) : formatShotKeyframeTime(selectedShotIndex, 1) }}
            </span>
          </div>

          <!-- Keyframe Preview Frame -->
          <div class="aspect-video w-full rounded-xl overflow-hidden bg-black border border-outline-border flex items-center justify-center relative group">
            <img
              v-if="selectedTarget === 'keyframe-start' && (selectedShotFrame?.file || activeSelectedShot.reference_image)"
              :src="selectedShotFrame?.file || activeSelectedShot.reference_image"
              class="w-full h-full object-cover"
            />
            <img
              v-else-if="selectedTarget === 'keyframe-end' && activeSelectedShot.last_frame_image"
              :src="activeSelectedShot.last_frame_image"
              class="w-full h-full object-cover"
            />
            <span v-else class="text-xs text-ink-muted font-mono">{{ currentLang === 'vi' ? 'Chưa có ảnh tham chiếu' : 'No reference image' }}</span>
          </div>

          <!-- Actions -->
          <div class="space-y-1.5 pt-1">
            <button
              type="button"
              class="w-full py-1.5 px-2.5 rounded-xl border border-outline-border bg-surface-card hover:bg-surface-hover text-ink-primary text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              @click="$emit('openMediaPicker')"
            >
              <span>🖼️</span>
              <span>{{ currentLang === 'vi' ? 'Chọn ảnh từ Thư viện' : 'Choose from Library' }}</span>
            </button>

            <button
              v-if="selectedTarget === 'keyframe-end'"
              type="button"
              class="w-full py-1.5 px-2.5 rounded-xl border text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              :class="generationMode === 'Continuous' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' : 'border-outline-border bg-surface-card hover:border-indigo-400 text-ink-secondary'"
              @click="$emit('toggleGenerationMode')"
            >
              <span>🔗</span>
              <span>{{ generationMode === 'Continuous' ? (currentLang === 'vi' ? '✓ Đang nối liền cảnh sau' : '✓ Chained to Next Shot') : (currentLang === 'vi' ? 'Nối khung với Cảnh sau' : 'Bridge to Next Shot') }}</span>
            </button>

            <button
              type="button"
              class="w-full jm-btn-secondary text-xs !py-1.5"
              @click="$emit('update:selectedTarget', 'scene')"
            >
              {{ currentLang === 'vi' ? '← Xem thuộc tính Cảnh' : '← Back to Shot' }}
            </button>
          </div>
        </div>
      </template>

      <!-- 4. SHOT SELECTED: Shot Details & Contextual AI Rewrite -->
      <template v-else-if="activeSelectedShot">
        <!-- Shot Info Card -->
        <div class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-ink-primary flex items-center gap-1.5">
              <span>🎞️</span>
              <span>{{ currentLang === 'vi' ? `Cảnh ${activeSelectedShot.shot_number}` : `Shot ${activeSelectedShot.shot_number}` }}</span>
            </span>
            <!-- Shot Duration Adjuster -->
            <div class="flex items-center gap-1">
              <button
                type="button"
                class="capcut-trim-button"
                :title="currentLang === 'vi' ? 'Giảm 0,5 giây' : 'Trim 0.5s'"
                @click="$emit('changeShotDuration', activeSelectedShot, -0.5)"
              >
                −
              </button>
              <span class="text-ink-primary font-mono text-xs font-bold min-w-[34px] text-center">
                {{ estimateShotDuration(activeSelectedShot) }}s
              </span>
              <button
                type="button"
                class="capcut-trim-button"
                :title="currentLang === 'vi' ? 'Tăng 0,5 giây' : 'Extend 0.5s'"
                @click="$emit('changeShotDuration', activeSelectedShot, 0.5)"
              >
                +
              </button>
            </div>
          </div>

          <!-- Miniature Keyframe Nodes -->
          <div class="p-2 rounded-xl bg-surface-card border border-outline-border flex items-center justify-between gap-2 text-xs">
            <button
              type="button"
              class="flex-1 p-1.5 rounded-lg border text-center transition-all cursor-pointer bg-surface-muted hover:border-indigo-400 text-ink-secondary"
              @click="$emit('selectKeyframeTarget', activeSelectedShot, selectedShotIndex, 'start')"
            >
              <span class="block text-[10px] font-bold">Start Frame</span>
              <span class="block text-[9px] text-ink-muted">0.0s</span>
            </button>
            <span class="text-ink-muted">──→</span>
            <button
              type="button"
              class="flex-1 p-1.5 rounded-lg border text-center transition-all cursor-pointer bg-surface-muted hover:border-emerald-400 text-ink-secondary"
              @click="$emit('selectKeyframeTarget', activeSelectedShot, selectedShotIndex, 'end')"
            >
              <span class="block text-[10px] font-bold">{{ generationMode === 'Continuous' ? 'Continuity' : 'End Frame' }}</span>
              <span class="block text-[9px] text-ink-muted">{{ estimateShotDuration(activeSelectedShot) }}s</span>
            </button>
          </div>

          <!-- Shot Prompt & Subject -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <label class="block text-[11px] font-semibold text-ink-secondary">
                {{ currentLang === 'vi' ? 'Mô tả phân cảnh (Prompt):' : 'Shot Prompt:' }}
              </label>
              <button
                type="button"
                class="text-[10px] text-indigo-400 hover:text-indigo-300 font-semibold cursor-pointer"
                @click="showAiRewrite = !showAiRewrite"
              >
                ✨ {{ currentLang === 'vi' ? 'Viết lại bằng AI' : 'Rewrite ✦' }}
              </button>
            </div>

            <textarea
              v-model="activeSelectedShot.generation_prompt"
              rows="3"
              class="w-full px-2.5 py-1.5 rounded-xl bg-surface-card border border-outline-border text-xs text-ink-primary focus:outline-none focus:border-indigo-500 font-mono resize-none leading-relaxed"
              @blur="$emit('saveActiveShot')"
            />
          </div>

          <!-- Contextual AI Rewrite Drawer/Box -->
          <div v-if="showAiRewrite" class="p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/30 space-y-2">
            <span class="text-[11px] font-bold text-indigo-400 block">✨ {{ currentLang === 'vi' ? 'Chỉ dẫn viết lại với AI:' : 'AI Rewrite Instruction:' }}</span>
            <input
              v-model="aiRewriteInstruction"
              type="text"
              :placeholder="currentLang === 'vi' ? 'VD: Thêm ánh sáng kịch tính, góc quay từ dưới lên...' : 'e.g. Add dramatic lighting, low angle camera...'"
              class="w-full px-2 py-1 rounded-lg bg-surface-card border border-outline-border text-xs text-ink-primary focus:outline-none focus:border-indigo-500"
              @keydown.enter="submitAiRewrite"
            />
            <div class="flex items-center justify-end gap-1.5">
              <button
                type="button"
                class="px-2 py-0.5 rounded text-[11px] text-ink-muted hover:text-ink-primary"
                @click="showAiRewrite = false"
              >
                {{ currentLang === 'vi' ? 'Đóng' : 'Close' }}
              </button>
              <button
                type="button"
                class="px-3 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold cursor-pointer"
                :disabled="aiRevisionLoading || !aiRewriteInstruction.trim()"
                @click="submitAiRewrite"
              >
                <span v-if="aiRevisionLoading" class="lucide-refresh-cw size-3 animate-spin inline-block mr-1" />
                <span>{{ currentLang === 'vi' ? 'Thực hiện ✦' : 'Rewrite ✦' }}</span>
              </button>
            </div>
          </div>

          <!-- Regenerate Shot Button -->
          <button
            type="button"
            class="w-full jm-btn-secondary !py-2 text-xs flex items-center justify-center gap-1.5 cursor-pointer"
            :disabled="isProductionActive"
            @click="$emit('regenerateCurrentShot')"
          >
            <span>↻</span>
            <span>{{ currentLang === 'vi' ? 'Tạo lại cảnh này' : 'Regenerate this Shot' }}</span>
          </button>
        </div>
      </template>

      <!-- 5. NOTHING SELECTED: Project Settings Overview (Default fallback) -->
      <template v-else>
        <div class="p-3 rounded-2xl bg-surface-muted border border-outline-border space-y-3">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-ink-primary">⚙ {{ currentLang === 'vi' ? 'Thông tin dự án' : 'Project Overview' }}</span>
            <span class="text-[10px] font-semibold px-2 py-0.5 rounded bg-surface-card text-ink-muted border border-outline-border">
              {{ currentDuration }}s
            </span>
          </div>

          <div class="space-y-2 text-xs">
            <div class="p-2.5 rounded-xl bg-surface-card border border-outline-border flex items-center justify-between">
              <span class="text-ink-muted">{{ currentLang === 'vi' ? 'Định dạng' : 'Format' }}</span>
              <span class="font-bold text-ink-primary">{{ currentPreset }}</span>
            </div>
            <div class="p-2.5 rounded-xl bg-surface-card border border-outline-border flex items-center justify-between">
              <span class="text-ink-muted">{{ currentLang === 'vi' ? 'Thời lượng' : 'Duration' }}</span>
              <span class="font-bold text-indigo-400 font-mono">{{ currentDuration }}s</span>
            </div>
            <div class="p-2.5 rounded-xl bg-surface-card border border-outline-border flex items-center justify-between">
              <span class="text-ink-muted">{{ currentLang === 'vi' ? 'Chế độ tạo' : 'Mode' }}</span>
              <span class="font-bold text-ink-primary">{{ generationMode }}</span>
            </div>
          </div>

          <button
            type="button"
            class="w-full jm-btn-secondary !py-2 text-xs flex items-center justify-center gap-1.5 cursor-pointer mt-2"
            @click="$emit('openSettings')"
          >
            <span>⚙</span>
            <span>{{ currentLang === 'vi' ? 'Tùy chỉnh cài đặt' : 'Configure Settings' }}</span>
          </button>
        </div>
      </template>
    </div>
  </aside>
</template>

<script setup>
import { computed, ref } from "vue";
import MediaThumbnail from "../MediaThumbnail.vue";

const props = defineProps({
  open: { type: Boolean, default: true },
  studioMode: { type: String, default: "scene" },
  selectedTarget: { type: String, default: "scene" },
  selectedAsset: { type: Object, default: null },
  activeSelectedShot: { type: Object, default: null },
  selectedShotIndex: { type: Number, default: 0 },
  selectedShotFrame: { type: Object, default: null },
  selectedClip: { type: Object, default: null },
  selectedClipSourceShot: { type: Object, default: null },
  timelineBusy: { type: Boolean, default: false },
  generationMode: { type: String, default: "Multi-shot" },
  currentDuration: { type: [Number, String], default: 15 },
  currentPreset: { type: String, default: "Landscape" },
  regeneratingSource: { type: Boolean, default: false },
  isProductionActive: { type: Boolean, default: false },
  aiRevisionLoading: { type: Boolean, default: false },
  currentLang: { type: String, default: "en" },
  estimateShotDuration: { type: Function, default: (s) => s?.duration_seconds || 5 },
  formatShotKeyframeTime: { type: Function, default: () => "0.0s" },
});

const emit = defineEmits([
  "update:open",
  "update:selectedTarget",
  "changeTransition",
  "changeTransitionFrames",
  "splitClip",
  "duplicateClip",
  "deleteClip",
  "updateSourceForSelectedClip",
  "regenerateSourceForSelectedClip",
  "applyAssetToShot",
  "removeAsset",
  "updateAssetRole",
  "selectKeyframeTarget",
  "toggleGenerationMode",
  "changeShotDuration",
  "regenerateCurrentShot",
  "saveActiveShot",
  "askAi",
  "openSettings",
  "openMediaPicker",
]);

const showAiRewrite = ref(false);
const aiRewriteInstruction = ref("");

function submitAiRewrite() {
  if (!aiRewriteInstruction.value.trim()) return;
  emit("askAi", aiRewriteInstruction.value.trim());
  aiRewriteInstruction.value = "";
  showAiRewrite.value = false;
}

const inspectorHeaderTitle = computed(() => {
  if (props.studioMode === "edit" && props.selectedClip) {
    return `Clip ${props.selectedClip.clip_order || 1}`;
  }
  if (props.selectedTarget === "asset" && props.selectedAsset) {
    return props.selectedAsset.asset_name || "Asset Details";
  }
  if (props.selectedTarget === "keyframe-start" || props.selectedTarget === "keyframe-end") {
    return props.selectedTarget === "keyframe-start" ? "Start Reference" : "End Reference";
  }
  if (props.activeSelectedShot) {
    return props.currentLang === "vi" ? `Cảnh ${props.activeSelectedShot.shot_number}` : `Shot ${props.activeSelectedShot.shot_number}`;
  }
  return props.currentLang === "vi" ? "Cài đặt dự án" : "Project Settings";
});

const inspectorHeaderIcon = computed(() => {
  if (props.studioMode === "edit" && props.selectedClip) return "✂️";
  if (props.selectedTarget === "asset") return "📦";
  if (props.selectedTarget === "keyframe-start" || props.selectedTarget === "keyframe-end") return "◆";
  if (props.activeSelectedShot) return "🎞️";
  return "⚙";
});
</script>

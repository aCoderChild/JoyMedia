<template>
  <div class="scene-strip-container rounded-2xl bg-surface-card border border-outline-border p-3 shadow-md select-none">
    <!-- Storyboard Header -->
    <div class="flex items-center justify-between mb-2.5 px-1 flex-wrap gap-2">
      <div class="flex items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider text-ink-primary flex items-center gap-1.5">
          <span>🎞️</span>
          <span>{{ currentLang === 'vi' ? 'Storyboard Phân cảnh' : 'Storyboard' }}</span>
        </span>
        <span v-if="syncError" class="text-rose-400 truncate">
          {{ syncError }}
        </span>
        <span class="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-muted text-indigo-400 border border-outline-border font-bold">
          {{ totalDurationSeconds }}s
        </span>
      </div>

      <!-- Right Actions: Lightweight AI Director revision prompt -->
      <div v-if="hasStoryboard" class="flex items-center gap-2">
        <form class="flex items-center gap-1.5" @submit.prevent="submitAiRevision">
          <div class="relative flex items-center">
            <span class="absolute left-2.5 text-xs text-indigo-400">✨</span>
            <input
              v-model="aiRevisionInput"
              type="text"
              :placeholder="currentLang === 'vi' ? 'Nhờ AI sửa kịch bản... (vd: thêm một cảnh cận sản phẩm)' : 'Ask the AI to change the storyboard... (e.g. add a product close-up)'"
              class="bg-surface-muted border border-outline-border focus:border-indigo-500 rounded-xl pl-7 pr-3 py-1 text-xs text-ink-primary placeholder:text-ink-muted w-48 sm:w-72 focus:outline-none transition-all"
              :disabled="isRevising || isGenerating"
            />
          </div>
          <button
            type="submit"
            class="px-3 py-1 rounded-xl text-xs font-semibold text-indigo-400 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 transition-all cursor-pointer shadow-xs disabled:opacity-50"
            :disabled="isRevising || isGenerating"
          >
            <span v-if="isRevising" class="lucide-refresh-cw size-3 animate-spin inline-block" />
            <span v-else>{{ currentLang === 'vi' ? 'Áp dụng' : 'Apply' }}</span>
          </button>
        </form>
      </div>
    </div>

    <!-- Active Clean Generation Progress (Only when generating - Shots oriented) -->
    <div
      v-if="isGenerating"
      class="mb-3 p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-between gap-3 text-xs"
    >
      <div class="flex items-center gap-2 min-w-0">
        <span class="lucide-refresh-cw size-3.5 text-indigo-400 animate-spin shrink-0" />
        <span class="font-bold text-ink-primary">
          {{ currentLang === 'vi' ? 'Đang tạo video:' : 'Generating video:' }}
        </span>
        <span v-if="shots.length || expectedShotCount" class="text-indigo-400 font-mono font-semibold">
          {{ completedShotsCount }} / {{ shots.length || expectedShotCount }} {{ currentLang === 'vi' ? 'cảnh hoàn thành' : 'scenes ready' }}
        </span>
        <span v-else class="text-indigo-400 font-mono font-semibold">
          {{ currentLang === 'vi' ? 'Đang lập storyboard…' : 'Planning storyboard…' }}
        </span>
      </div>

      <!-- Shot Progress Indicators -->
      <div v-if="shots.length || expectedShotCount" class="flex items-center gap-1.5 overflow-x-auto">
        <span
          v-for="(shot, idx) in (shots.length ? shots : expectedShotCount)"
          :key="idx"
          class="text-[10px] font-mono px-2 py-0.5 rounded-full flex items-center gap-1 shrink-0"
          :class="getShotBadgeClass(shot, idx)"
        >
          <span>{{ getShotStatusGlyph(shot, idx) }}</span>
          <span>S{{ idx + 1 }}</span>
        </span>
      </div>
    </div>

    <!-- Simplified Flow / OpenSlop Storyboard Shots Track -->
    <div v-if="shots.length" class="capcut-track flex items-stretch gap-2.5 overflow-x-auto pb-2">
      <template v-for="(shot, index) in shots" :key="shot.name || shot.shot_number || index">
        <!-- Simplified Shot Card Item -->
        <div
          class="capcut-clip relative flex-1 shrink-0 rounded-2xl border p-2.5 transition-all cursor-pointer bg-surface-muted select-none flex flex-col justify-between"
          :class="[
            selectedShotIndex === index && selectedTarget !== 'asset'
              ? 'border-indigo-500 bg-indigo-500/10 ring-2 ring-indigo-500/30'
              : 'border-outline-border hover:border-indigo-400'
          ]"
          :style="{ minWidth: '175px', maxWidth: '240px' }"
          draggable="true"
          @dragstart="onDragStart(shot, index, $event)"
          @dragover.prevent
          @drop.prevent="onDrop(shot, index)"
          @click="$emit('selectShot', shot, index)"
        >
          <!-- Top: Thumbnail / Video Preview -->
          <div class="relative w-full aspect-video rounded-xl overflow-hidden bg-black flex items-center justify-center mb-2">
            <MediaThumbnail
              :src="getShotVideoFile(shot) || getShotFirstFrame(shot)?.file || shot.reference_image"
              :media-type="getShotVideoFile(shot) ? 'Video' : 'Image'"
              :poster="getShotFirstFrame(shot)?.file || shot.last_frame_image"
              :alt="`Shot ${shot.shot_number}`"
              :show-play-overlay="false"
              aspect="aspect-video"
            />

            <button
              v-if="getShotVideoFile(shot)"
              type="button"
              class="absolute inset-0 z-20 flex items-center justify-center cursor-pointer"
              :aria-label="currentLang === 'vi' ? `Phát cảnh ${shot.shot_number}` : `Preview Scene ${shot.shot_number}`"
              @click.stop="$emit('previewShot', shot, index)"
            >
              <span class="size-9 rounded-full bg-white/90 flex items-center justify-center text-indigo-600 shadow-md hover:scale-110 transition-transform">
                <svg class="size-4 fill-current ml-0.5" viewBox="0 0 24 24" aria-hidden="true">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
              </span>
            </button>

            <!-- A new take is rendering; the current one stays visible underneath -->
            <div
              v-if="isRegenerating(shot)"
              class="absolute inset-0 z-30 bg-black/55 flex items-center justify-center text-center p-1"
            >
              <span class="text-xs text-white font-bold animate-pulse">
                ↻ {{ currentLang === 'vi' ? 'Đang tạo lại…' : 'Regenerating…' }}
              </span>
            </div>

            <!-- In-progress state overlay -->
            <div
              v-else-if="isGenerating && getShotState(shot) !== 'Ready'"
              class="absolute inset-0 bg-black/60 flex flex-col items-center justify-center text-center p-1"
            >
              <span v-if="getShotState(shot) === 'Generating'" class="text-xs text-indigo-400 font-bold animate-pulse">
                ● {{ currentLang === 'vi' ? 'Đang tạo' : 'Generating' }}
              </span>
              <span v-else class="text-[10px] text-zinc-400 font-mono">
                ○ {{ currentLang === 'vi' ? 'Đang chờ' : 'Waiting' }}
              </span>
            </div>
          </div>

          <!-- Middle: Scene Title & Clean Duration -->
          <div class="flex items-center justify-between text-xs font-bold text-ink-primary mb-1">
            <span class="truncate">
              {{ currentLang === 'vi' ? `Cảnh ${shot.shot_number}` : `Scene ${shot.shot_number}` }}<template v-if="sceneBeat(shot)"> · {{ sceneBeat(shot) }}</template>
            </span>
            <div class="flex items-center gap-1">
              <!-- Review status badge -->
              <span
                v-if="shot.review_status && shot.review_status !== 'Pending Review'"
                class="text-[9px] px-1.5 py-0.5 rounded-full font-semibold leading-none"
                :class="{
                  'bg-emerald-500/20 text-emerald-400': shot.review_status === 'Approved',
                  'bg-rose-500/20 text-rose-400': shot.review_status === 'Rejected',
                  'bg-amber-500/20 text-amber-400': shot.review_status === 'Needs Revision',
                }"
                :title="shot.review_status"
              >
                {{ shot.review_status === 'Approved' ? '✓' : shot.review_status === 'Rejected' ? '✕' : '~' }}
              </span>
              <span class="text-ink-secondary font-mono text-[11px] font-semibold bg-surface-card px-1.5 py-0.5 rounded border border-outline-border/60">
                {{ Number(estimateShotDuration(shot)).toFixed(1) }}s
              </span>
            </div>
          </div>

          <!-- Creative summary snippet -->
          <p
            class="text-[11px] text-ink-secondary line-clamp-2 leading-relaxed mb-1.5 min-h-[30px]"
            :title="shot.generation_prompt || ''"
          >
            {{ sceneSummary(shot) }}
          </p>

          <!-- On-screen caption: editable in place, saved when the field is left -->
          <input
            :value="shot.caption || ''"
            type="text"
            maxlength="120"
            class="w-full mb-2 px-2 py-1 rounded-lg bg-surface-card border border-outline-border/60 text-[11px] italic text-ink-primary placeholder:text-ink-muted placeholder:not-italic focus:outline-none focus:border-indigo-500"
            :placeholder="currentLang === 'vi' ? 'Chữ trên màn hình (không bắt buộc)' : 'On-screen text (optional)'"
            :title="currentLang === 'vi' ? 'Hiện ở cuối khung hình trong cảnh này' : 'Shown at the bottom of the frame during this scene'"
            @click.stop
            @keydown.enter="$event.target.blur()"
            @change="emit('updateCaption', shot, $event.target.value)"
          />

          <div
            v-if="shot.reference_image || shot.last_frame_image"
            class="flex items-center gap-1.5 mb-2 text-[10px] text-ink-muted"
          >
            <span class="font-semibold text-ink-secondary">
              {{ currentLang === 'vi' ? 'Ảnh tham chiếu:' : 'Reference:' }}
            </span>
            <span
              v-if="shot.reference_image_reference_key"
              class="rounded-full bg-indigo-500/10 border border-indigo-500/30 px-1.5 py-0.5 text-indigo-400 truncate"
            >
              @{{ shot.reference_image_reference_key }}
            </span>
            <span
              v-if="shot.last_frame_image_reference_key"
              class="rounded-full bg-amber-500/10 border border-amber-500/30 px-1.5 py-0.5 text-amber-400 truncate"
            >
              @{{ shot.last_frame_image_reference_key }}
            </span>
          </div>

          <!-- Bottom: Role Badge & Scene action menu -->
          <div class="flex items-center justify-between pt-1.5 border-t border-outline-border/60 text-xs">
            <!-- Takes, as in Google Flow: step through every render of this scene -->
            <div v-if="Number(shot.take_count) > 1" class="flex items-center gap-0.5 text-[10.5px] text-ink-secondary">
              <button
                type="button"
                class="px-1 rounded hover:bg-surface-hover cursor-pointer disabled:opacity-30 disabled:cursor-default"
                :disabled="isRegenerating(shot) || shot.take_index <= 1"
                :title="currentLang === 'vi' ? 'Phiên bản trước' : 'Previous take'"
                @click.stop="emit('selectTake', shot, shot.take_index - 1)"
              >‹</button>
              <span class="font-mono" :title="currentLang === 'vi' ? 'Phiên bản' : 'Take'">{{ shot.take_index || '–' }}/{{ shot.take_count }}</span>
              <button
                type="button"
                class="px-1 rounded hover:bg-surface-hover cursor-pointer disabled:opacity-30 disabled:cursor-default"
                :disabled="isRegenerating(shot) || shot.take_index >= shot.take_count"
                :title="currentLang === 'vi' ? 'Phiên bản sau' : 'Next take'"
                @click.stop="emit('selectTake', shot, shot.take_index + 1)"
              >›</button>
            </div>
            <span v-else />
            <div class="relative flex items-center gap-1">
              <button
                v-if="getShotVideoFile(shot)"
                type="button"
                class="px-2 py-0.5 rounded-lg text-[11px] font-semibold text-indigo-400 hover:bg-indigo-500/10 cursor-pointer disabled:opacity-40 disabled:cursor-default"
                :disabled="isRegenerating(shot) || Boolean(production?.planning)"
                :title="currentLang === 'vi'
                  ? 'Dựng lại cảnh này với mô tả hiện tại. Bản cũ vẫn được giữ.'
                  : 'Render this scene again from its current description. The old take is kept.'"
                @click.stop="emit('regenerateShot', shot)"
              >
                ↻ {{ currentLang === 'vi' ? 'Tạo lại' : 'Redo' }}
              </button>
              <button
                type="button"
                class="px-2 py-0.5 rounded-lg text-sm font-semibold text-indigo-400 hover:text-indigo-300 hover:bg-surface-hover cursor-pointer transition-colors"
                :title="currentLang === 'vi' ? 'Tùy chọn cảnh' : 'Scene options'"
                :aria-expanded="menuOpenIndex === index"
                @click.stop="toggleSceneMenu(index)"
              >
                ⋯
              </button>
              <div
                v-if="menuOpenIndex === index"
                class="absolute right-0 bottom-8 z-30 w-36 rounded-xl border border-outline-border bg-surface-card p-1.5 shadow-xl"
                @click.stop
              >
                <button
                  type="button"
                  class="w-full rounded-lg px-2.5 py-1.5 text-left text-[11px] text-ink-primary hover:bg-surface-hover cursor-pointer"
                  @click="emit('editShot', shot, index); menuOpenIndex = null"
                >
                  {{ currentLang === 'vi' ? 'Sửa cảnh' : 'Edit Scene' }}
                </button>
                <button
                  type="button"
                  class="w-full rounded-lg px-2.5 py-1.5 text-left text-[11px] text-rose-400 hover:bg-rose-500/10 cursor-pointer disabled:opacity-50"
                  :disabled="isGenerating"
                  @click="emit('deleteShot', shot, index); menuOpenIndex = null"
                >
                  {{ currentLang === 'vi' ? 'Xóa cảnh' : 'Delete Scene' }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Clean Cut indicator between shots -->
        <div v-if="index < shots.length - 1" class="self-center shrink-0 text-ink-muted text-xs opacity-60">
          |
        </div>
      </template>
    </div>

    <div v-if="shots.length" class="relative flex justify-end pt-1">
      <button
        type="button"
        class="rounded-xl border border-dashed border-indigo-500/50 bg-indigo-500/10 px-3 py-2 text-xs font-semibold text-indigo-400 hover:bg-indigo-500/20 cursor-pointer"
        @click="$emit('addScene', shots[shots.length - 1])"
      >
        + {{ currentLang === 'vi' ? 'Thêm cảnh' : 'Add Scene' }}
      </button>
    </div>

    <!-- Empty Storyboard State -->
    <div v-else class="text-center py-6 text-xs text-ink-muted">
      {{ currentLang === 'vi' ? 'Nhập ý tưởng video bên trên và bấm Tạo Video để sinh phân cảnh tự động.' : 'Enter your video idea above and click Generate Video to create storyboard scenes.' }}
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import MediaThumbnail from "../MediaThumbnail.vue";

const props = defineProps({
  shots: { type: Array, default: () => [] },
  selectedShotIndex: { type: Number, default: 0 },
  selectedTarget: { type: String, default: "scene" },
  generationMode: { type: String, default: "Multi-shot" },
  totalDurationSeconds: { type: [Number, String], default: 15 },
  hasStoryboard: { type: Boolean, default: false },
  isGenerating: { type: Boolean, default: false },
  isRevising: { type: Boolean, default: false },
  expectedShotCount: { type: Number, default: 0 },
  production: { type: Object, default: null },
  generationPhase: { type: String, default: "idle" },
  syncError: { type: String, default: "" },
  currentLang: { type: String, default: "en" },
  // Scenes with a render in progress (several scenes can be regenerated at once).
  busyShots: { type: Array, default: () => [] },
  estimateShotDuration: { type: Function, default: (s) => s?.duration_seconds || 5 },
  formatShotKeyframeTime: { type: Function, default: () => "0.0s" },
  getShotVideoFile: { type: Function, default: () => "" },
  getShotFirstFrame: { type: Function, default: () => ({}) },
});

const emit = defineEmits([
  "selectShot",
  "previewShot",
  "editShot",
  "deleteShot",
  "addScene",
  "selectKeyframe",
  "changeShotDuration",
  "toggleContinuityMode",
  "reviseStoryboard",
  "reorderShots",
  "regenerateShot",
  "selectTake",
  "updateCaption",
]);

const aiRevisionInput = ref("");
const menuOpenIndex = ref(null);

function toggleSceneMenu(index) {
  menuOpenIndex.value = menuOpenIndex.value === index ? null : index;
}

function submitAiRevision() {
  if (!aiRevisionInput.value?.trim()) {
    emit("reviseStoryboard");
    return;
  }
  emit("reviseStoryboard", aiRevisionInput.value.trim());
  aiRevisionInput.value = "";
}

const draggedIndex = ref(null);

function onDragStart(shot, index, event) {
  draggedIndex.value = index;
  event.dataTransfer.effectAllowed = "move";
}

function onDrop(shot, index) {
  if (draggedIndex.value !== null && draggedIndex.value !== index) {
    emit("reorderShots", draggedIndex.value, index);
  }
  draggedIndex.value = null;
}

const completedShotsCount = computed(() => {
  if (!props.shots?.length) return 0;
  return props.shots.filter((s) => Boolean(props.getShotVideoFile(s))).length;
});

// Story roles the AI director gives each scene ("CLIMAX: Sunset on the terrace").
const SCENE_BEATS = {
  OPENING: ["Opening", "Mở đầu"],
  BUILD: ["Build-up", "Phát triển"],
  CLIMAX: ["Climax", "Cao trào"],
  RESOLUTION: ["Wind-down", "Lắng đọng"],
  CLOSING: ["Ending", "Kết thúc"],
};

function sceneBeat(shot) {
  const beat = SCENE_BEATS[String(shot.shot_name || "").split(":")[0].trim().toUpperCase()];
  return beat ? beat[props.currentLang === "vi" ? 1 : 0] : "";
}

function sceneSummary(shot) {
  const name = String(shot.shot_name || "");
  const title = name.includes(":") ? name.slice(name.indexOf(":") + 1).trim() : name.trim();
  if (title && !/^(scene|shot)\s*\d+$/i.test(title)) return title;
  const picture = props.currentLang === "vi" ? "ảnh" : "picture";
  // The full prompt is for the AI; show it without its <Picture N> markup.
  const prompt = String(shot.generation_prompt || "").replace(/<Picture\s*(\d+)>/gi, `${picture} $1`);
  return prompt || (props.currentLang === "vi" ? "Cảnh giới thiệu sản phẩm" : "Product showcase");
}

function isRegenerating(shot) {
  return Boolean(props.getShotVideoFile(shot) && props.busyShots.includes(shot.name));
}

function getShotState(shot) {
  if (props.getShotVideoFile(shot)) return "Ready";
  if (props.isGenerating) {
    return "Generating";
  }
  return "Waiting";
}

function getShotBadgeClass(shot, idx) {
  const ready = typeof shot === "object" && props.getShotVideoFile(shot);
  if (ready) return "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
  if (props.isGenerating && idx === completedShotsCount.value) {
    return "bg-indigo-500/20 text-indigo-400 border border-indigo-500/40 animate-pulse";
  }
  return "bg-surface-muted text-ink-muted border border-outline-border";
}

function getShotStatusGlyph(shot, idx) {
  const ready = typeof shot === "object" && props.getShotVideoFile(shot);
  if (ready) return "✓";
  if (props.isGenerating && idx === completedShotsCount.value) return "●";
  return "○";
}
</script>

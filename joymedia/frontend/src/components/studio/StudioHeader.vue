<template>
  <header class="studio-header flex items-center justify-between gap-3 h-12 px-3 border-b border-outline-border bg-surface-card shrink-0 select-none z-10">
    <!-- Left: Back to Projects, Project Title & Status -->
    <div class="flex items-center gap-2 min-w-0">
      <button
        type="button"
        class="text-xs text-ink-muted hover:text-ink-primary flex items-center gap-1 font-semibold shrink-0 cursor-pointer px-2 py-1 rounded-lg hover:bg-surface-hover transition-colors"
        :title="currentLang === 'vi' ? 'Quay lại danh sách dự án' : 'Back to projects'"
        @click="$emit('goBack')"
      >
        <span>←</span>
        <span>{{ currentLang === 'vi' ? 'Dự án' : 'Projects' }}</span>
      </button>

      <div class="h-4 w-px bg-outline-border shrink-0" />

      <!-- Editable Project Title -->
      <div class="flex items-center gap-1.5 min-w-0">
        <input
          v-if="isEditingName"
          ref="titleInputRef"
          v-model="nameDraft"
          type="text"
          maxlength="140"
          class="bg-surface-muted border border-indigo-500 rounded px-2 py-0.5 text-xs sm:text-sm font-bold text-ink-primary focus:outline-none"
          @keydown.enter="saveName"
          @keydown.esc="cancelName"
          @blur="saveName"
        />
        <button
          v-else
          type="button"
          class="text-xs sm:text-sm font-bold text-ink-primary truncate cursor-text hover:text-indigo-400 transition-colors text-left"
          :title="currentLang === 'vi' ? 'Bấm để đổi tên dự án' : 'Click to rename'"
          @click="startNameEdit"
        >
          {{ projectTitle || "Untitled Project" }}
        </button>

        <!-- Project Status Badge -->
        <span
          v-if="projectStatus"
          class="text-[10px] px-2 py-0.5 rounded-md font-semibold tracking-wide border shrink-0"
          :class="statusBadgeClass"
        >
          {{ formattedStatus }}
        </span>
      </div>
    </div>

    <!-- Center / Right: Studio Mode Switch, Actions & Controls -->
    <div class="flex items-center gap-2">
      <!-- Studio Mode Switch: Scenes vs Edit -->
      <div class="flex items-center p-0.5 rounded-xl bg-surface-muted border border-outline-border text-xs">
        <button
          type="button"
          class="px-3 py-1 rounded-lg font-semibold transition-all flex items-center gap-1 cursor-pointer"
          :class="studioMode === 'scene'
            ? 'bg-indigo-600 text-white shadow-xs'
            : 'text-ink-secondary hover:text-ink-primary'"
          @click="$emit('update:studioMode', 'scene')"
        >
          <span>▤</span>
          <span>Scenes</span>
        </button>

        <button
          type="button"
          class="px-3 py-1 rounded-lg font-semibold transition-all flex items-center gap-1 cursor-pointer"
          :class="[
            studioMode === 'edit'
              ? 'bg-indigo-600 text-white shadow-xs'
              : 'text-ink-secondary hover:text-ink-primary',
            { 'opacity-50 cursor-not-allowed': !timelineReady }
          ]"
          :disabled="!timelineReady"
          :title="!timelineReady ? (currentLang === 'vi' ? 'Cần tạo video xong để mở trình chỉnh sửa Edit' : 'Generate video to enable Edit mode') : ''"
          @click="$emit('update:studioMode', 'edit')"
        >
          <span>✂</span>
          <span>Edit</span>
        </button>
      </div>

      <!-- In Edit Mode: Export Button & Edit Status -->
      <template v-if="studioMode === 'edit'">
        <div class="hidden sm:flex items-center gap-1.5">
          <span
            v-if="hasUnexportedEdits"
            class="text-[10px] font-semibold text-amber-400 px-2 py-0.5 rounded-md bg-amber-500/10 border border-amber-500/20"
          >
            ● {{ currentLang === 'vi' ? 'Chưa xuất bản dựng mới' : 'Unsaved edits' }}
          </span>
          <span
            v-else-if="currentOutputAssetVersion"
            class="text-[10px] font-semibold text-emerald-400 px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20"
          >
            ✓ {{ currentLang === 'vi' ? 'Đã xuất video' : 'Exported' }}
          </span>
        </div>

        <button
          type="button"
          class="jm-btn-primary !py-1 !px-3 text-xs flex items-center gap-1.5 shadow-sm transition-all"
          :class="{
            '!bg-emerald-600 hover:!bg-emerald-500': !hasUnexportedEdits && !isExporting && currentOutputAssetVersion
          }"
          :disabled="isExporting"
          @click="$emit('exportTimeline')"
        >
          <span v-if="isExporting" class="lucide-refresh-cw size-3 animate-spin" />
          <span v-else>💾</span>
          <span>
            {{ isExporting
              ? (currentLang === 'vi' ? 'Đang xuất video...' : 'Exporting...')
              : (currentLang === 'vi' ? 'Xuất video' : 'Export video') }}
          </span>
        </button>
      </template>

      <!-- Settings Modal Button (Gear) -->
      <button
        type="button"
        class="text-xs text-ink-muted hover:text-ink-primary px-2.5 py-1 rounded-xl hover:bg-surface-hover border border-outline-border transition-colors cursor-pointer flex items-center gap-1.5 font-semibold bg-surface-muted shadow-xs"
        :title="currentLang === 'vi' ? 'Cài đặt video (Tỉ lệ, Thời lượng, Phong cách)' : 'Video settings'"
        @click="$emit('openSettings')"
      >
        <span>⚙</span>
        <span class="hidden sm:inline">{{ currentLang === 'vi' ? 'Cài đặt' : 'Settings' }}</span>
      </button>

      <!-- Inspector Toggle Button -->
      <button
        type="button"
        class="p-1.5 rounded-xl border border-outline-border bg-surface-muted hover:bg-surface-hover text-ink-muted hover:text-ink-primary transition-colors cursor-pointer"
        :title="inspectorOpen ? (currentLang === 'vi' ? 'Thu gọn Inspector' : 'Collapse inspector') : (currentLang === 'vi' ? 'Mở Inspector' : 'Open inspector')"
        @click="$emit('update:inspectorOpen', !inspectorOpen)"
      >
        <span class="text-xs font-mono font-bold">{{ inspectorOpen ? '→' : '←' }}</span>
      </button>
    </div>
  </header>
</template>

<script setup>
import { computed, nextTick, ref } from "vue";

const props = defineProps({
  projectName: { type: String, default: "" },
  projectTitle: { type: String, default: "" },
  projectStatus: { type: String, default: "Draft" },
  studioMode: { type: String, default: "scene" },
  timelineReady: { type: Boolean, default: false },
  hasUnexportedEdits: { type: Boolean, default: false },
  isExporting: { type: Boolean, default: false },
  exportStatus: { type: String, default: "Idle" },
  currentOutputAssetVersion: { type: String, default: "" },
  inspectorOpen: { type: Boolean, default: true },
  currentLang: { type: String, default: "en" },
});

const emit = defineEmits([
  "goBack",
  "saveProjectName",
  "update:studioMode",
  "update:inspectorOpen",
  "openSettings",
  "exportTimeline",
]);

const isEditingName = ref(false);
const nameDraft = ref("");
const titleInputRef = ref(null);

function startNameEdit() {
  nameDraft.value = props.projectTitle || "";
  isEditingName.value = true;
  nextTick(() => {
    if (titleInputRef.value) {
      titleInputRef.value.focus();
      titleInputRef.value.select();
    }
  });
}

function saveName() {
  if (!isEditingName.value) return;
  isEditingName.value = false;
  const val = nameDraft.value.trim();
  if (val && val !== props.projectTitle) {
    emit("saveProjectName", val);
  }
}

function cancelName() {
  isEditingName.value = false;
}

const formattedStatus = computed(() => {
  const s = props.projectStatus || "Draft";
  if (props.currentLang === "vi") {
    if (s === "Draft") return "Bản nháp";
    if (s === "Generating") return "Đang tạo";
    if (s === "Completed") return "Đã hoàn thành";
    if (s === "Needs Attention") return "Cần chú ý";
    return s;
  }
  return s;
});

const statusBadgeClass = computed(() => {
  const s = props.projectStatus;
  if (s === "Generating") return "bg-indigo-500/10 text-indigo-400 border-indigo-500/30 animate-pulse";
  if (s === "Completed") return "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
  if (s === "Needs Attention") return "bg-rose-500/10 text-rose-400 border-rose-500/30";
  return "bg-surface-muted text-ink-muted border-outline-border";
});
</script>

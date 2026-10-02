<template>
  <header class="studio-header flex items-center justify-between gap-3 h-12 px-3 sm:px-4 border-b border-outline-border bg-surface-card shrink-0 select-none z-10">
    <!-- Left: Back to Projects, Project Title & Status -->
    <div class="flex items-center gap-2 sm:gap-3 min-w-0">
      <button
        type="button"
        class="text-xs text-ink-muted hover:text-ink-primary flex items-center gap-1.5 font-semibold shrink-0 cursor-pointer px-2 py-1 rounded-lg hover:bg-surface-hover transition-colors"
        :title="currentLang === 'vi' ? 'Quay lại danh sách dự án' : 'Back to projects'"
        @click="$emit('goBack')"
      >
        <span class="text-sm">←</span>
        <span>{{ currentLang === 'vi' ? 'Dự án' : 'Projects' }}</span>
      </button>

      <div class="h-4 w-px bg-outline-border shrink-0" />

      <!-- Editable Project Title -->
      <div class="flex items-center gap-2 min-w-0">
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
          class="text-xs sm:text-sm font-bold text-ink-primary truncate cursor-text hover:text-indigo-400 transition-colors text-left max-w-[160px] sm:max-w-xs"
          :title="currentLang === 'vi' ? 'Bấm để đổi tên dự án' : 'Click to rename'"
          @click="startNameEdit"
        >
          {{ projectTitle || "Untitled Project" }}
        </button>

        <!-- Project Status Badge -->
        <span
          v-if="projectStatus"
          class="text-[10px] px-2 py-0.5 rounded-md font-semibold tracking-wide border shrink-0 hidden sm:inline-block"
          :class="statusBadgeClass"
        >
          {{ formattedStatus }}
        </span>
      </div>
    </div>

    <!-- Right: Media Drawer Toggle + Export Button + Language + User Avatar -->
    <div class="flex items-center gap-2">
      <!-- Media Drawer Quick Toggle -->
      <button
        type="button"
        class="text-xs text-ink-muted hover:text-ink-primary px-2.5 py-1 rounded-xl hover:bg-surface-hover border border-outline-border transition-colors cursor-pointer flex items-center gap-1.5 font-medium bg-surface-muted"
        :class="{ '!border-indigo-500 !text-indigo-400': mediaDrawerOpen }"
        :title="currentLang === 'vi' ? 'Xem tư liệu dự án' : 'Project Media'"
        @click="$emit('toggleMediaDrawer')"
      >
        <span>▧</span>
        <span class="hidden sm:inline">Media</span>
        <span
          v-if="projectAssetsCount"
          class="size-4 rounded-full bg-indigo-600 text-white text-[9px] font-mono font-bold flex items-center justify-center"
        >
          {{ projectAssetsCount }}
        </span>
      </button>

      <!-- Export Button (when timeline / video is ready) -->
      <button
        v-if="timelineReady"
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
            : (currentLang === 'vi' ? 'Xuất video' : 'Export') }}
        </span>
      </button>

      <!-- Language Switcher -->
      <button
        type="button"
        class="p-1 px-1.5 rounded-lg text-[11px] font-mono font-bold text-ink-muted hover:text-ink-primary hover:bg-surface-hover border border-outline-border/60 transition-colors cursor-pointer select-none"
        :title="currentLang === 'vi' ? 'Switch to English' : 'Chuyển sang Tiếng Việt'"
        @click="$emit('toggleLang')"
      >
        {{ currentLang.toUpperCase() }}
      </button>

      <!-- User Avatar -->
      <div
        class="size-7 rounded-full bg-gradient-to-tr from-indigo-600 to-purple-600 text-white flex items-center justify-center text-xs font-bold shadow-xs select-none"
        :title="user || 'Creator'"
      >
        {{ (user || 'C').charAt(0).toUpperCase() }}
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed, nextTick, ref } from "vue";

const props = defineProps({
  projectName: { type: String, default: "" },
  projectTitle: { type: String, default: "" },
  projectStatus: { type: String, default: "Draft" },
  timelineReady: { type: Boolean, default: false },
  hasUnexportedEdits: { type: Boolean, default: false },
  isExporting: { type: Boolean, default: false },
  exportStatus: { type: String, default: "Idle" },
  currentOutputAssetVersion: { type: String, default: "" },
  mediaDrawerOpen: { type: Boolean, default: false },
  projectAssetsCount: { type: Number, default: 0 },
  currentLang: { type: String, default: "en" },
  user: { type: String, default: "" },
});

const emit = defineEmits([
  "goBack",
  "saveProjectName",
  "toggleMediaDrawer",
  "toggleLang",
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

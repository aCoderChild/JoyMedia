<template>
  <div class="generation-composer rounded-2xl bg-surface-card border border-outline-border p-3.5 sm:p-4 shadow-lg transition-all focus-within:border-indigo-500/80 focus-within:ring-2 focus-within:ring-indigo-500/20">
    <!-- Top Row: Reference Ingredients Chips -->
    <div class="flex items-center gap-2 mb-2.5 overflow-x-auto pb-1 text-xs">
      <span class="text-[11px] font-bold text-ink-muted uppercase tracking-wider shrink-0 flex items-center gap-1">
        <span>📎</span>
        <span>{{ currentLang === 'vi' ? 'Tham chiếu:' : 'Ingredients:' }}</span>
      </span>

      <!-- Existing Reference Chips with Real @reference_key -->
      <template v-if="projectAssets.length">
        <span
          v-for="asset in projectAssets"
          :key="asset.asset_version || asset.name"
          class="relative inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-surface-muted hover:bg-surface-hover border border-outline-border transition-colors shrink-0 text-ink-primary group"
        >
          <button
            type="button"
            class="inline-flex items-center gap-1.5 cursor-pointer"
            :title="currentLang === 'vi' ? `Chèn @${asset.asset_name} vào mô tả` : `Insert @${asset.asset_name} into prompt`"
            @click="insertReferenceTag(asset)"
          >
            <span class="text-xs">{{ getRoleIcon(asset.reference_role || asset.asset_category) }}</span>
            <span class="text-[11px] text-indigo-400 font-bold">@</span>
            <span class="font-semibold truncate max-w-[130px]">{{ asset.asset_name }}</span>
            <span class="text-[10px] text-ink-muted">· {{ roleLabel(asset.reference_role || asset.asset_category) }}</span>
          </button>
          <button
            type="button"
            class="absolute -top-1.5 -right-1.5 size-4 rounded-full bg-surface-card border border-outline-border text-ink-muted hover:text-rose-400 hover:border-rose-400 transition-colors cursor-pointer text-[10px] leading-none flex items-center justify-center opacity-0 group-hover:opacity-100"
            :title="currentLang === 'vi' ? 'Gỡ khỏi dự án' : 'Remove from project'"
            @click.stop="$emit('removeReference', asset)"
          >✕</button>
        </span>
      </template>

      <span v-else class="text-xs text-ink-muted italic">
        {{ currentLang === 'vi' ? 'Chưa có ảnh/video tham chiếu.' : 'No references selected.' }}
      </span>

      <!-- Add Reference Button -->
      <button
        type="button"
        class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold text-indigo-400 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 transition-colors cursor-pointer shrink-0"
        @click="$emit('openMediaPicker')"
      >
        <span>+</span>
        <span>{{ currentLang === 'vi' ? 'Thêm tư liệu' : 'Add Reference' }}</span>
      </button>
    </div>

    <!-- Main Textarea Composer with @mention Autocomplete -->
    <div class="relative">
      <textarea
        ref="textareaRef"
        v-model="modelPrompt"
        rows="2"
        :placeholder="currentLang === 'vi'
          ? 'Mô tả video bạn muốn tạo... (Gõ @ để chèn tư liệu tham chiếu)'
          : 'Describe the video you want... (Type @ to mention reference ingredients)'"
        class="w-full bg-surface-muted/60 hover:bg-surface-muted focus:bg-surface-base border border-outline-border rounded-xl px-3.5 py-2.5 text-xs sm:text-sm text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-indigo-500 transition-all resize-none font-sans leading-relaxed"
        :disabled="isGenerating"
        @input="handleInput"
        @keydown="handleKeydown"
      />

      <!-- Autocomplete Dropdown for @mention -->
      <div
        v-if="showMentionMenu && matchingMentionAssets.length"
        class="absolute bottom-full left-2 mb-2 w-72 max-h-52 overflow-y-auto bg-surface-card border border-outline-border rounded-xl shadow-2xl p-1.5 z-30 space-y-0.5"
      >
        <div class="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-ink-muted border-b border-outline-border mb-1">
          {{ currentLang === 'vi' ? 'Chọn tư liệu (@)' : 'Select ingredient (@)' }}
        </div>
        <button
          v-for="(asset, idx) in matchingMentionAssets"
          :key="asset.name || asset.asset_name"
          type="button"
          class="w-full text-left px-2.5 py-1.5 rounded-lg text-xs flex items-center justify-between cursor-pointer transition-colors"
          :class="mentionActiveIndex === idx ? 'bg-indigo-600 text-white font-bold' : 'hover:bg-surface-hover text-ink-primary'"
          @click="selectMention(asset)"
        >
          <div class="flex items-center gap-2 min-w-0">
            <span class="text-xs">{{ getRoleIcon(asset.reference_role || asset.asset_category) }}</span>
            <span class="truncate">{{ asset.asset_name }}</span>
          </div>
          <span class="text-[10px] font-mono px-1 py-0.2 rounded bg-surface-muted text-indigo-400 font-bold shrink-0">
            @{{ getCleanKey(asset) }}
          </span>
        </button>
      </div>
    </div>

    <!-- Bottom Actions Row -->
    <div class="flex items-center justify-between gap-3 mt-2.5 pt-2 border-t border-outline-border/60">
      <!-- Left: AI Contextual Assistant & Settings Shortcut -->
      <div class="flex items-center gap-2">
        <!-- Contextual AI Action: Improve Idea with Qwen -->
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-indigo-400 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 transition-all cursor-pointer shadow-xs"
          :disabled="isImprovingPrompt || isImprovingLocal || isGenerating || !modelPrompt?.trim()"
          :title="currentLang === 'vi' ? 'Qwen AI nâng tầm ý tưởng thành kịch bản điện ảnh' : 'Refine and enrich your idea with Qwen AI'"
          @click="improvePromptWithAi"
        >
          <span v-if="isImprovingPrompt || isImprovingLocal" class="lucide-refresh-cw size-3 animate-spin" />
          <span v-else>✨</span>
          <span>{{ currentLang === 'vi' ? 'Hoàn thiện ý tưởng' : 'Improve Idea' }}</span>
        </button>

        <!-- Settings Quick Pill: 10s · Landscape ▾ -->
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-ink-primary hover:text-indigo-400 bg-surface-muted hover:bg-surface-hover border border-outline-border transition-colors cursor-pointer shadow-xs"
          :title="currentLang === 'vi' ? 'Cài đặt thời lượng & định dạng' : 'Video settings'"
          @click="$emit('openSettings')"
        >
          <span>{{ durationSeconds }}s · {{ deliveryPreset }}</span>
          <span class="text-[10px] text-ink-muted">▾</span>
        </button>
      </div>

      <!-- Right: Main Generate Button -->
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="jm-btn-primary !py-2 !px-4 text-xs font-bold flex items-center gap-2 shadow-lg shadow-indigo-600/25 transition-all cursor-pointer"
          :class="{ 'animate-pulse': isGenerating }"
          :disabled="isGenerating"
          @click="$emit('generate')"
        >
          <span v-if="isGenerating" class="lucide-refresh-cw size-3.5 animate-spin" />
          <span v-else class="text-sm">✦</span>
          <span>{{ generateButtonLabel }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";

const props = defineProps({
  prompt: { type: String, default: "" },
  projectAssets: { type: Array, default: () => [] },
  isGenerating: { type: Boolean, default: false },
  isImprovingPrompt: { type: Boolean, default: false },
  hasStoryboard: { type: Boolean, default: false },
  durationSeconds: { type: [Number, String], default: 15 },
  deliveryPreset: { type: String, default: "Landscape" },
  currentLang: { type: String, default: "en" },
});

const emit = defineEmits(["update:prompt", "generate", "openMediaPicker", "openSettings", "improvePrompt", "removeReference"]);

const textareaRef = ref(null);
const isImprovingLocal = ref(false);
const showMentionMenu = ref(false);
const mentionQuery = ref("");
const mentionActiveIndex = ref(0);

const modelPrompt = computed({
  get: () => props.prompt,
  set: (val) => emit("update:prompt", val),
});

const generateButtonLabel = computed(() => {
  if (props.isGenerating) {
    return props.currentLang === "vi" ? "Đang tạo video..." : "Generating...";
  }
  if (props.hasStoryboard) {
    return props.currentLang === "vi" ? "Tạo bản mới ✦" : "Generate Version ✦";
  }
  return props.currentLang === "vi" ? "Tạo Video ✦" : "Generate Video ✦";
});

function getCleanKey(asset) {
  if (asset?.reference_key) return asset.reference_key;
  const name = asset?.asset_name || asset?.reference_role || "item";
  return name.toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/^_+|_+$/g, "").slice(0, 24);
}

const ROLE_LABELS = {
  Product: ["Product", "Sản phẩm"],
  Character: ["Character", "Nhân vật"],
  Environment: ["Place", "Bối cảnh"],
  Background: ["Place", "Bối cảnh"],
  Style: ["Style", "Phong cách"],
  Motion: ["Motion", "Chuyển động"],
  Audio: ["Audio", "Âm thanh"],
  General: ["Automatic", "Tự động"],
};

function roleLabel(role) {
  const labels = ROLE_LABELS[role];
  if (!labels) return role || (props.currentLang === "vi" ? "Tư liệu" : "Reference");
  return labels[props.currentLang === "vi" ? 1 : 0];
}

function getRoleIcon(role) {
  const r = (role || "").toLowerCase();
  if (r.includes("product")) return "👟";
  if (r.includes("character")) return "👤";
  if (r.includes("environment") || r.includes("background")) return "🏞️";
  if (r.includes("style")) return "🎨";
  if (r.includes("motion")) return "🏃";
  if (r.includes("audio")) return "🔊";
  return "📎";
}

const matchingMentionAssets = computed(() => {
  if (!showMentionMenu.value) return [];
  const q = mentionQuery.value.toLowerCase();
  return (props.projectAssets || []).filter((a) => {
    const key = getCleanKey(a).toLowerCase();
    const name = (a.asset_name || "").toLowerCase();
    return key.includes(q) || name.includes(q);
  });
});

function handleInput() {
  const text = modelPrompt.value || "";
  const pos = textareaRef.value?.selectionStart || text.length;
  const beforeCursor = text.slice(0, pos);
  const match = beforeCursor.match(/@([a-zA-Z0-9_-]*)$/);
  if (match) {
    showMentionMenu.value = true;
    mentionQuery.value = match[1];
    mentionActiveIndex.value = 0;
  } else {
    showMentionMenu.value = false;
  }
}

function handleKeydown(e) {
  if (showMentionMenu.value && matchingMentionAssets.value.length) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      mentionActiveIndex.value = (mentionActiveIndex.value + 1) % matchingMentionAssets.value.length;
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      mentionActiveIndex.value = (mentionActiveIndex.value - 1 + matchingMentionAssets.value.length) % matchingMentionAssets.value.length;
      return;
    }
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      selectMention(matchingMentionAssets.value[mentionActiveIndex.value]);
      return;
    }
    if (e.key === "Escape") {
      showMentionMenu.value = false;
      return;
    }
  }
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    onCtrlEnter();
  }
}

function selectMention(asset) {
  if (!asset) return;
  const key = `@${getCleanKey(asset)} `;
  const text = modelPrompt.value || "";
  const pos = textareaRef.value?.selectionStart || text.length;
  const beforeCursor = text.slice(0, pos);
  const afterCursor = text.slice(pos);
  const newBefore = beforeCursor.replace(/@([a-zA-Z0-9_-]*)$/, key);
  modelPrompt.value = newBefore + afterCursor;
  showMentionMenu.value = false;
  if (textareaRef.value) {
    textareaRef.value.focus();
  }
}

function insertReferenceTag(asset) {
  const tag = `@${getCleanKey(asset)} `;
  const current = (modelPrompt.value || "").trim();
  modelPrompt.value = current ? `${current} ${tag}` : tag;
  if (textareaRef.value) {
    textareaRef.value.focus();
  }
}

function onCtrlEnter() {
  if (!props.isGenerating) {
    emit("generate");
  }
}

async function improvePromptWithAi() {
  if (props.isImprovingPrompt || isImprovingLocal.value || !modelPrompt.value?.trim()) return;
  isImprovingLocal.value = true;
  try {
    emit("improvePrompt", modelPrompt.value);
  } finally {
    setTimeout(() => {
      isImprovingLocal.value = false;
    }, 1500);
  }
}
</script>

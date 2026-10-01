<template>
  <div class="generation-composer rounded-2xl bg-surface-card border border-outline-border p-3.5 sm:p-4 shadow-lg transition-all focus-within:border-indigo-500/80 focus-within:ring-2 focus-within:ring-indigo-500/20">
    <!-- Top Row: Reference Ingredients Chips -->
    <div class="flex items-center gap-2 mb-2.5 overflow-x-auto pb-1 text-xs">
      <span class="text-[11px] font-bold text-ink-muted uppercase tracking-wider shrink-0 flex items-center gap-1">
        <span>📎</span>
        <span>{{ currentLang === 'vi' ? 'Tham chiếu:' : 'Ingredients:' }}</span>
      </span>

      <!-- Existing Reference Chips -->
      <template v-if="projectAssets.length">
        <button
          v-for="asset in projectAssets"
          :key="asset.asset_version || asset.name"
          type="button"
          class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-surface-muted hover:bg-surface-hover border border-outline-border transition-colors cursor-pointer shrink-0 text-ink-primary group"
          :title="currentLang === 'vi' ? 'Bấm để chèn tham chiếu vào prompt' : 'Click to mention in prompt'"
          @click="insertReferenceTag(asset)"
        >
          <span class="text-xs">{{ getRoleIcon(asset.reference_role || asset.asset_category) }}</span>
          <span class="font-bold truncate max-w-[120px]">{{ asset.asset_name }}</span>
          <span class="text-[10px] font-mono px-1.5 py-0.2 rounded bg-surface-card text-indigo-400 font-bold border border-outline-border">
            {{ asset.reference_role || asset.asset_category || 'General' }}
          </span>
        </button>
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

    <!-- Main Textarea Composer -->
    <div class="relative">
      <textarea
        ref="textareaRef"
        v-model="modelPrompt"
        rows="2"
        :placeholder="currentLang === 'vi'
          ? 'Mô tả video bạn muốn tạo... (VD: Cận cảnh sang trọng với chuyển động máy bay nhẹ, ánh sáng vàng ấm áp chiếu lên sản phẩm)'
          : 'Describe the video you want... (e.g. Luxury reveal with slow orbit camera, warm backlight glowing on the product)'"
        class="w-full bg-surface-muted/60 hover:bg-surface-muted focus:bg-surface-base border border-outline-border rounded-xl px-3.5 py-2.5 text-xs sm:text-sm text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-indigo-500 transition-all resize-none font-sans leading-relaxed"
        :disabled="isGenerating"
        @keydown.enter.ctrl="onCtrlEnter"
        @keydown.enter.meta="onCtrlEnter"
      />
    </div>

    <!-- Bottom Actions Row -->
    <div class="flex items-center justify-between gap-3 mt-2.5 pt-2 border-t border-outline-border/60">
      <!-- Left: AI Contextual Assistant & Settings Shortcut -->
      <div class="flex items-center gap-2">
        <!-- Contextual AI Action: Improve Idea -->
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-indigo-400 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 transition-all cursor-pointer shadow-xs"
          :disabled="isImproving || isGenerating || !modelPrompt?.trim()"
          :title="currentLang === 'vi' ? 'AI hoàn thiện và mở rộng ý tưởng thành chi tiết điện ảnh' : 'Refine and enrich your idea with AI'"
          @click="improvePromptWithAi"
        >
          <span v-if="isImproving" class="lucide-refresh-cw size-3 animate-spin" />
          <span v-else>✨</span>
          <span>{{ currentLang === 'vi' ? 'Hoàn thiện ý tưởng' : 'Improve Idea' }}</span>
        </button>

        <!-- Settings Quick Pill -->
        <button
          type="button"
          class="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-medium text-ink-secondary hover:text-ink-primary bg-surface-muted hover:bg-surface-hover border border-outline-border transition-colors cursor-pointer"
          :title="currentLang === 'vi' ? 'Cài đặt thời lượng & định dạng' : 'Video settings'"
          @click="$emit('openSettings')"
        >
          <span>⚙</span>
          <span>{{ durationSeconds }}s · {{ deliveryPreset }}</span>
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
  hasStoryboard: { type: Boolean, default: false },
  durationSeconds: { type: [Number, String], default: 15 },
  deliveryPreset: { type: String, default: "Landscape" },
  currentLang: { type: String, default: "en" },
});

const emit = defineEmits(["update:prompt", "generate", "openMediaPicker", "openSettings", "improvePrompt"]);

const textareaRef = ref(null);
const isImproving = ref(false);

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

function insertReferenceTag(asset) {
  const tag = `@${asset.reference_role || asset.asset_category || asset.asset_name}`;
  const current = modelPrompt.value || "";
  modelPrompt.value = current ? `${current.trim()} ${tag} ` : `${tag} `;
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
  if (isImproving.value || !modelPrompt.value?.trim()) return;
  isImproving.value = true;
  try {
    emit("improvePrompt", modelPrompt.value);
  } finally {
    // will be settled by parent
    setTimeout(() => {
      isImproving.value = false;
    }, 1500);
  }
}
</script>

<template>
  <div class="generation-composer rounded-2xl bg-surface-card border border-outline-border p-3.5 sm:p-4 shadow-lg transition-all focus-within:border-rio-500/80 focus-within:ring-2 focus-within:ring-rio-500/20">
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
            <span class="text-[11px] text-rio-400 font-bold">@</span>
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
        class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold text-rio-400 bg-rio-500/10 hover:bg-rio-500/20 border border-rio-500/20 transition-colors cursor-pointer shrink-0"
        @click="$emit('openMediaPicker')"
      >
        <span>+</span>
        <span>{{ currentLang === 'vi' ? 'Thêm tư liệu' : 'Add Reference' }}</span>
      </button>
    </div>

    <!-- Main Textarea Composer with @mention Autocomplete -->
    <div class="relative">
      <div class="mb-1.5 flex items-center justify-between gap-3 px-0.5">
        <label for="video-idea" class="text-xs font-semibold text-ink-primary">
          {{ currentLang === 'vi' ? 'Ý tưởng video' : 'Video idea' }}
        </label>
        <span class="text-[10px] text-ink-muted text-right" data-test="video-idea-note">
          {{ fromSheet
            ? (currentLang === 'vi' ? 'Lấy từ file kịch bản. Muốn sửa, hãy sửa file rồi nhập lại.' : 'From your sheet. To change it, edit the sheet and import it again.')
            : (currentLang === 'vi' ? 'Mô tả này là brief cho AI lập cảnh và tạo video.' : 'This brief guides AI storyboard planning and video generation.') }}
        </span>
      </div>
      <textarea
        id="video-idea"
        ref="textareaRef"
        v-model="modelPrompt"
        :rows="fromSheet ? 5 : 2"
        :placeholder="currentLang === 'vi'
          ? 'Mô tả video bạn muốn tạo... (Gõ @ để chèn tư liệu tham chiếu)'
          : 'Describe the video you want... (Type @ to mention reference ingredients)'"
        class="w-full bg-surface-muted/60 hover:bg-surface-muted focus:bg-surface-base border border-outline-border rounded-xl px-3.5 py-2.5 text-xs sm:text-sm text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-rio-500 transition-all resize-none font-sans leading-relaxed"
        :disabled="isGenerating"
        :readonly="fromSheet"
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
          :class="mentionActiveIndex === idx ? 'bg-rio-600 text-white font-bold' : 'hover:bg-surface-hover text-ink-primary'"
          @click="selectMention(asset)"
        >
          <div class="flex items-center gap-2 min-w-0">
            <span class="text-xs">{{ getRoleIcon(asset.reference_role || asset.asset_category) }}</span>
            <span class="truncate">{{ asset.asset_name }}</span>
          </div>
          <span class="text-[10px] font-mono px-1 py-0.2 rounded bg-surface-muted text-rio-400 font-bold shrink-0">
            @{{ getCleanKey(asset) }}
          </span>
        </button>
      </div>
    </div>

    <!-- Bottom Actions Row -->
    <div class="flex flex-wrap items-center justify-between gap-3 mt-2.5 pt-2 border-t border-outline-border/60">
      <!-- Left: AI Contextual Assistant & Settings Shortcut -->
      <div class="flex flex-wrap items-center gap-2">
		<label
		  class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-ink-primary hover:text-rio-400 bg-surface-muted hover:bg-surface-hover border border-outline-border transition-colors cursor-pointer"
		  :title="currentLang === 'vi' ? 'Nhập file kịch bản Excel' : 'Import storyboard workbook'"
		>
		  <span>⇧</span>
		  <span>{{ currentLang === 'vi' ? 'Nhập kịch bản' : 'Import storyboard' }}</span>
		  <input class="hidden" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" @change="importStoryboard" />
		</label>
        <!-- Contextual AI Action: Improve Idea (a sheet's brief is the sheet's) -->
        <button
          v-if="!fromSheet"
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-rio-400 bg-rio-500/10 hover:bg-rio-500/20 border border-rio-500/30 transition-all cursor-pointer shadow-xs"
          :disabled="isImprovingPrompt || isGenerating || !modelPrompt?.trim()"
          :title="currentLang === 'vi' ? 'AI nâng tầm ý tưởng thành kịch bản điện ảnh' : 'Refine and enrich your idea with AI'"
          @click="improvePromptWithAi"
        >
          <span v-if="isImprovingPrompt" class="lucide-refresh-cw size-3 animate-spin" />
          <span v-else>✨</span>
          <span>{{ currentLang === 'vi' ? 'Hoàn thiện ý tưởng' : 'Improve Idea' }}</span>
        </button>

        <!-- Settings Quick Pill: 10s · Landscape ▾ -->
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-ink-primary hover:text-rio-400 bg-surface-muted hover:bg-surface-hover border border-outline-border transition-colors cursor-pointer shadow-xs"
          :title="currentLang === 'vi' ? 'Cài đặt thời lượng & định dạng' : 'Video settings'"
          @click="$emit('openSettings')"
        >
          <span>{{ durationSeconds }}s · {{ deliveryPreset }}</span>
          <span class="text-[10px] text-ink-muted">▾</span>
        </button>
      </div>

      <!-- One next step, based on current project readiness. -->
      <div class="flex items-center gap-2">
        <span v-if="isSavingPrompt" class="text-[10px] text-ink-muted">
          {{ currentLang === 'vi' ? 'Đang lưu…' : 'Saving…' }}
        </span>
		<span v-else-if="!modelPrompt?.trim()" class="text-[10px] text-amber-400">
		  {{ currentLang === 'vi' ? 'Nhập ý tưởng video để tiếp tục.' : 'Enter a video idea to continue.' }}
		</span>
        <button
          type="button"
          class="jm-btn-primary !py-2 !px-4 text-xs font-bold flex items-center gap-2 shadow-lg shadow-rio-600/25 transition-all cursor-pointer"
          :class="{ 'animate-pulse': isGenerating }"
          :disabled="actionBusy || ['brief', 'loading', 'working'].includes(nextAction)"
          data-test="client-next-action"
          @click="$emit('continue')"
        >
          <span v-if="isGenerating" class="lucide-refresh-cw size-3.5 animate-spin" />
          <span v-else class="text-sm">✦</span>
          <span>{{ nextActionLabel }}</span>
        </button>
      </div>
    </div>
    <p class="mt-2 text-xs text-ink-muted" aria-live="polite" data-test="client-next-hint">{{ nextActionHint }}</p>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";

const props = defineProps({
  prompt: { type: String, default: "" },
  nextAction: { type: String, default: "brief" },
  actionBusy: { type: Boolean, default: false },
  projectAssets: { type: Array, default: () => [] },
  isGenerating: { type: Boolean, default: false },
  isImprovingPrompt: { type: Boolean, default: false },
  isSavingPrompt: { type: Boolean, default: false },
  durationSeconds: { type: [Number, String], default: 15 },
  deliveryPreset: { type: String, default: "Landscape" },
  currentLang: { type: String, default: "en" },
  fromSheet: { type: Boolean, default: false },
});

const emit = defineEmits(["continue", "update:prompt", "importStoryboard", "openMediaPicker", "openSettings", "improvePrompt", "removeReference"]);

const textareaRef = ref(null);
const showMentionMenu = ref(false);
const mentionQuery = ref("");
const mentionActiveIndex = ref(0);

const modelPrompt = computed({
  get: () => props.prompt,
  set: (val) => emit("update:prompt", val),
});

const journeyCopy = {
  brief: ["Add your story", "Thêm kịch bản", "Write a brief or upload a storyboard. Add product and character references above.", "Viết mô tả hoặc tải bảng kịch bản. Thêm ảnh sản phẩm và nhân vật phía trên."],
  plan: ["Plan my video", "Lập kế hoạch video", "We will draft scenes for you to review before any video is created.", "Hệ thống sẽ lập cảnh để bạn duyệt trước khi tạo video."],
  approve: ["Approve Storyboard & prepare previews", "Duyệt kịch bản và tạo ảnh xem trước", "Review the scenes below, then continue. Preparing previews starts automatically after approval.", "Xem lại các cảnh bên dưới rồi tiếp tục. Ảnh xem trước sẽ được tạo sau khi duyệt."],
  retry: ["Retry preview check", "Kiểm tra lại ảnh", "We could not check your previews. Try again; existing work is kept.", "Chưa kiểm tra được ảnh. Hãy thử lại; kết quả hiện có vẫn được giữ."],
  loading: ["Checking previews…", "Đang kiểm tra ảnh…", "Checking the current preview approvals.", "Đang kiểm tra trạng thái duyệt ảnh hiện tại."],
  previews: ["Prepare previews", "Tạo ảnh xem trước", "Create the missing or updated previews before rendering.", "Tạo các ảnh còn thiếu hoặc đã thay đổi trước khi dựng video."],
  review: ["Review previews below", "Duyệt ảnh bên dưới", "Check each preview for product, logo and character accuracy, then approve it on its scene.", "Kiểm tra sản phẩm, logo và nhân vật trên từng ảnh rồi duyệt tại cảnh đó."],
  render: ["Create video", "Tạo video", "Your previews are approved. We will render the scenes and assemble the film.", "Các ảnh đã được duyệt. Hệ thống sẽ dựng cảnh và ghép phim."],
  working: ["Creating…", "Đang tạo…", "Work is in progress. Follow Progress above; you can leave and return to this project.", "Đang xử lý. Theo dõi Tiến trình phía trên; bạn có thể rời trang và quay lại dự án."],
  watch: ["Watch & edit video", "Xem và chỉnh sửa video", "Play the film, make any edits, then download it above. Review selected takes before release.", "Xem phim, chỉnh sửa nếu cần rồi tải xuống phía trên. Duyệt các phiên bản cảnh trước khi xuất bản."],
};
const nextActionLabel = computed(() => (journeyCopy[props.nextAction] || journeyCopy.loading)[props.currentLang === "vi" ? 1 : 0]);
const nextActionHint = computed(() => (journeyCopy[props.nextAction] || journeyCopy.loading)[props.currentLang === "vi" ? 3 : 2]);

function importStoryboard(event) {
	const file = event.target?.files?.[0];
	if (file) emit("importStoryboard", file);
	event.target.value = "";
}

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
  if (props.fromSheet) return;
  const tag = `@${getCleanKey(asset)} `;
  const current = (modelPrompt.value || "").trim();
  modelPrompt.value = current ? `${current} ${tag}` : tag;
  if (textareaRef.value) {
    textareaRef.value.focus();
  }
}

function onCtrlEnter() {
  if (!props.isGenerating) {
    primaryAction();
  }
}

function improvePromptWithAi() {
  if (props.isImprovingPrompt || !modelPrompt.value?.trim()) return;
  emit("improvePrompt", modelPrompt.value);
}
</script>

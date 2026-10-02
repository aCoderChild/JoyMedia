<template>
  <div v-if="open" class="add-scene-popover w-[320px] rounded-2xl border border-outline-border bg-surface-card p-3 shadow-2xl">
    <div class="flex items-center justify-between mb-3">
      <div>
        <h3 class="text-xs font-bold text-ink-primary">{{ currentLang === 'vi' ? 'Thêm cảnh' : 'Add Scene' }}</h3>
        <p class="text-[10px] text-ink-muted mt-0.5">
          {{ afterShot ? (currentLang === 'vi' ? `Thêm sau Cảnh ${afterShot.shot_number}` : `Add after Scene ${afterShot.shot_number}`) : (currentLang === 'vi' ? 'Thêm vào storyboard' : 'Append to storyboard') }}
        </p>
      </div>
      <button type="button" class="text-ink-muted hover:text-ink-primary cursor-pointer" @click="$emit('close')">✕</button>
    </div>

    <form class="space-y-3" @submit.prevent="submit">
      <div>
        <label class="block text-[11px] font-semibold text-ink-secondary mb-1">
          {{ currentLang === 'vi' ? 'Thời lượng thêm' : 'Additional duration' }}
        </label>
        <div class="relative">
          <input
            v-model="durationInput"
            type="number"
            min="1"
            max="120"
            step="0.5"
            inputmode="decimal"
            class="w-full rounded-xl border border-outline-border bg-surface-muted px-3 py-2 pr-10 text-sm text-ink-primary focus:border-indigo-500 focus:outline-none"
            placeholder="15"
          />
          <span class="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-ink-muted">sec</span>
        </div>
        <p class="mt-1 text-[10px] text-ink-muted">
          {{ currentLang === 'vi' ? 'AI Director sẽ tự chia thành số cảnh phù hợp.' : 'AI Director will divide longer durations into suitable scenes.' }}
        </p>
      </div>

      <p v-if="error || formError" class="text-[11px] text-rose-400 whitespace-pre-wrap">{{ error || formError }}</p>

      <div>
        <label class="block text-[11px] font-semibold text-ink-secondary mb-1">
          {{ currentLang === 'vi' ? 'Mô tả diễn biến tiếp theo' : 'Describe what happens next' }}
          <span class="text-ink-muted">({{ currentLang === 'vi' ? 'tùy chọn' : 'optional' }})</span>
        </label>
        <textarea
          v-model="instruction"
          rows="3"
          :placeholder="currentLang === 'vi' ? 'Để trống để AI Director tự tiếp tục câu chuyện...' : 'Leave blank and AI Director will continue naturally...'"
          class="w-full resize-none rounded-xl border border-outline-border bg-surface-muted px-2.5 py-2 text-xs text-ink-primary placeholder:text-ink-muted focus:border-indigo-500 focus:outline-none"
        />
      </div>

      <label class="flex items-start gap-2 rounded-xl border border-outline-border bg-surface-muted p-2 text-[11px] text-ink-secondary cursor-pointer">
        <input v-model="continuity" type="checkbox" class="mt-0.5 accent-indigo-600" />
        <span>
          <span class="block font-semibold text-ink-primary">{{ currentLang === 'vi' ? 'Tiếp nối cảnh trước' : 'Continue from previous shot' }}</span>
          <span class="block text-ink-muted mt-0.5">{{ currentLang === 'vi' ? 'Dùng khung cuối của cảnh trước khi workflow hỗ trợ.' : 'Use the previous shot’s last frame when supported.' }}</span>
        </span>
      </label>

      <div class="flex justify-end gap-2 pt-1">
        <button type="button" class="rounded-lg px-3 py-1.5 text-xs text-ink-secondary hover:bg-surface-hover cursor-pointer" @click="$emit('close')">{{ currentLang === 'vi' ? 'Hủy' : 'Cancel' }}</button>
        <button
          type="submit"
          class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 cursor-pointer disabled:opacity-50"
          :disabled="busy"
        >
          {{ busy ? (currentLang === 'vi' ? 'Đang lập kế hoạch…' : 'Planning…') : (currentLang === 'vi' ? 'Tạo' : 'Generate') }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, watch } from "vue";

const props = defineProps({
  open: { type: Boolean, default: false },
  afterShot: { type: Object, default: null },
  currentLang: { type: String, default: "en" },
  busy: { type: Boolean, default: false },
  error: { type: String, default: "" },
});

const emit = defineEmits(["close", "submit"]);
const durationInput = ref("5");
const instruction = ref("");
const continuity = ref(true);
const formError = ref("");

watch(() => props.open, (open) => {
  if (open) {
    durationInput.value = "5";
    instruction.value = "";
    continuity.value = true;
    formError.value = "";
  }
});

function submit() {
  const duration = Number(durationInput.value);
  if (!Number.isFinite(duration) || duration <= 0 || duration > 120) {
    formError.value = props.currentLang === "vi"
      ? "Thời lượng phải từ 1 đến 120 giây."
      : "Duration must be between 1 and 120 seconds.";
    return;
  }
  formError.value = "";
  emit("submit", {
    afterShot: props.afterShot,
    durationSeconds: duration,
    instruction: instruction.value.trim(),
    continuity: continuity.value,
  });
}
</script>

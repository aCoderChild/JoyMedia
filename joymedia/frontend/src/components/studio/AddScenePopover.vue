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
        <label class="block text-[11px] font-semibold text-ink-secondary mb-1">{{ currentLang === 'vi' ? 'Tổng thời lượng' : 'Total duration' }}</label>
        <div class="grid grid-cols-4 gap-1.5">
          <button
            v-for="seconds in [5, 10, 15, 20]"
            :key="seconds"
            type="button"
            class="rounded-lg border px-2 py-1.5 text-xs font-semibold cursor-pointer transition-colors"
            :class="durationSeconds === seconds ? 'border-indigo-500 bg-indigo-500/15 text-indigo-400' : 'border-outline-border bg-surface-muted text-ink-secondary hover:border-indigo-400'"
            @click="durationSeconds = seconds"
          >
            {{ seconds }}s
          </button>
        </div>
      </div>

      <div>
        <label class="block text-[11px] font-semibold text-ink-secondary mb-1">{{ currentLang === 'vi' ? 'Mô tả diễn biến tiếp theo' : 'Describe what happens next' }}</label>
        <textarea
          v-model="instruction"
          rows="3"
          required
          :placeholder="currentLang === 'vi' ? 'VD: Người mẫu thoa son và nhìn vào máy quay...' : 'e.g. Model applies lipstick and turns to camera...'"
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
        <button type="submit" class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 cursor-pointer">{{ currentLang === 'vi' ? 'Tạo' : 'Generate' }}</button>
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
});

const emit = defineEmits(["close", "submit"]);
const durationSeconds = ref(5);
const instruction = ref("");
const continuity = ref(true);

watch(() => props.open, (open) => {
  if (open) {
    durationSeconds.value = 5;
    instruction.value = "";
    continuity.value = true;
  }
});

function submit() {
  if (!instruction.value.trim()) return;
  emit("submit", {
    afterShot: props.afterShot,
    durationSeconds: durationSeconds.value,
    instruction: instruction.value.trim(),
    continuity: continuity.value,
  });
}
</script>

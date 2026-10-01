<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-xs" @click.self="$emit('close')">
    <div class="w-full max-w-lg bg-surface-card border border-outline-border rounded-2xl p-6 shadow-2xl space-y-4 text-xs">
      <!-- Modal Header -->
      <div class="flex items-center justify-between pb-3 border-b border-outline-border">
        <div>
          <h3 class="text-sm font-bold text-ink-primary flex items-center gap-2">
            <span>⚙</span>
            <span>{{ currentLang === 'vi' ? 'Cài đặt Dự án Video' : 'Video Project Settings' }}</span>
          </h3>
          <p class="text-xs text-ink-muted mt-0.5">
            {{ currentLang === 'vi' ? 'Định dạng, thời lượng và thông số AI cho video.' : 'Format, duration, and AI generation parameters.' }}
          </p>
        </div>
        <button
          type="button"
          class="text-ink-muted hover:text-ink-primary p-1 rounded-lg hover:bg-surface-hover cursor-pointer"
          @click="$emit('close')"
        >
          ✕
        </button>
      </div>

      <!-- Settings Form -->
      <div class="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
        <!-- 1. Format / Aspect Ratio Preset -->
        <div class="space-y-1.5">
          <label class="block font-bold text-ink-primary">
            {{ currentLang === 'vi' ? 'Định dạng & Tỉ lệ khung hình (Format):' : 'Delivery Format & Aspect Ratio:' }}
          </label>
          <div class="grid grid-cols-3 gap-2">
            <button
              v-for="preset in formatPresets"
              :key="preset.value"
              type="button"
              class="p-2.5 rounded-xl border text-center transition-all cursor-pointer flex flex-col items-center justify-center gap-1"
              :class="form.delivery_preset === preset.value
                ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400 font-bold shadow-xs'
                : 'border-outline-border bg-surface-muted hover:border-indigo-400 text-ink-secondary'"
              @click="form.delivery_preset = preset.value"
            >
              <span class="text-base">{{ preset.icon }}</span>
              <span class="text-xs font-semibold">{{ preset.label }}</span>
              <span class="text-[10px] text-ink-muted">{{ preset.sub }}</span>
            </button>
          </div>
        </div>

        <!-- 2. Target Duration -->
        <div class="space-y-1.5">
          <div class="flex items-center justify-between">
            <label class="font-bold text-ink-primary">
              {{ currentLang === 'vi' ? 'Thời lượng video (Giây):' : 'Video Duration (Seconds):' }}
            </label>
            <span class="font-mono font-bold text-indigo-400 text-xs">{{ form.total_duration_seconds }}s</span>
          </div>
          <div class="flex items-center gap-3">
            <input
              v-model.number="form.total_duration_seconds"
              type="range"
              min="5"
              max="60"
              step="1"
              class="flex-1 accent-indigo-600 cursor-pointer"
            />
            <div class="flex items-center gap-1">
              <button
                v-for="d in [10, 15, 30, 45]"
                :key="d"
                type="button"
                class="px-2 py-0.5 rounded text-[11px] font-mono border transition-colors cursor-pointer"
                :class="form.total_duration_seconds === d ? 'border-indigo-500 bg-indigo-500/20 text-indigo-400 font-bold' : 'border-outline-border bg-surface-muted text-ink-muted'"
                @click="form.total_duration_seconds = d"
              >
                {{ d }}s
              </button>
            </div>
          </div>
        </div>

        <!-- 3. Generation Mode (Continuous vs Multi-shot) -->
        <div class="space-y-1.5">
          <label class="block font-bold text-ink-primary">
            {{ currentLang === 'vi' ? 'Chế độ tạo cảnh (Generation Mode):' : 'Generation Continuity Mode:' }}
          </label>
          <div class="grid grid-cols-2 gap-2">
            <button
              type="button"
              class="p-2.5 rounded-xl border text-left transition-all cursor-pointer"
              :class="form.generation_mode === 'Continuous'
                ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400 font-bold shadow-xs'
                : 'border-outline-border bg-surface-muted hover:border-indigo-400 text-ink-secondary'"
              @click="form.generation_mode = 'Continuous'"
            >
              <div class="flex items-center gap-1.5">
                <span>🔗</span>
                <span class="text-xs font-semibold">Continuous</span>
              </div>
              <p class="text-[10.5px] text-ink-muted mt-1 leading-normal font-normal">
                {{ currentLang === 'vi' ? 'Chuyển động mượt mà, khung cuối cảnh trước là khung đầu cảnh sau.' : 'Chained continuity from last frames of preceding shots.' }}
              </p>
            </button>

            <button
              type="button"
              class="p-2.5 rounded-xl border text-left transition-all cursor-pointer"
              :class="form.generation_mode === 'Multi-shot'
                ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400 font-bold shadow-xs'
                : 'border-outline-border bg-surface-muted hover:border-indigo-400 text-ink-secondary'"
              @click="form.generation_mode = 'Multi-shot'"
            >
              <div class="flex items-center gap-1.5">
                <span>⧉</span>
                <span class="text-xs font-semibold">Multi-shot</span>
              </div>
              <p class="text-[10.5px] text-ink-muted mt-1 leading-normal font-normal">
                {{ currentLang === 'vi' ? 'Cắt cảnh độc lập theo nhịp quảng cáo, gán keyframe riêng từng cảnh.' : 'Independent shot keyframing and cuts.' }}
              </p>
            </button>
          </div>
        </div>

        <!-- 4. Video Style / Workflow Selection -->
        <div v-if="videoStyles.length" class="space-y-1.5">
          <label class="block font-bold text-ink-primary">
            {{ currentLang === 'vi' ? 'Phong cách Video (Style):' : 'Video Style / Workflow:' }}
          </label>
          <select
            v-model="form.video_style"
            class="w-full px-3 py-2 rounded-xl bg-surface-muted border border-outline-border text-xs text-ink-primary cursor-pointer focus:outline-none focus:border-indigo-500"
          >
            <option :value="null">{{ currentLang === 'vi' ? 'Mặc định (Default System Workflow)' : 'Default System Workflow' }}</option>
            <option
              v-for="s in videoStyles"
              :key="s.workflow_key"
              :value="s.workflow_key"
            >
              {{ s.client_name || s.workflow_key }}
            </option>
          </select>
        </div>

        <!-- 5. Global Instructions -->
        <div class="space-y-1.5">
          <label class="block font-bold text-ink-primary">
            {{ currentLang === 'vi' ? 'Chỉ dẫn chung toàn video (Global Instructions):' : 'Global Instructions:' }}
          </label>
          <textarea
            v-model="form.global_instructions"
            rows="2"
            :placeholder="currentLang === 'vi'
              ? 'Áp dụng cho mọi cảnh: Tông màu ấm, không gian hiện đại, màu sắc tự nhiên...'
              : 'Applies to all scenes: Warm tones, minimalist modern studio, cinematic lighting...'"
            class="w-full px-3 py-2 rounded-xl bg-surface-muted border border-outline-border text-xs text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-indigo-500 resize-none"
          />
        </div>
      </div>

      <!-- Modal Footer -->
      <div class="pt-3 border-t border-outline-border flex items-center justify-end gap-2">
        <button
          type="button"
          class="jm-btn-secondary text-xs !py-1.5 !px-3 cursor-pointer"
          @click="$emit('close')"
        >
          {{ currentLang === 'vi' ? 'Huỷ' : 'Cancel' }}
        </button>
        <button
          type="button"
          class="jm-btn-primary text-xs !py-1.5 !px-4 cursor-pointer"
          :disabled="saving"
          @click="submitSave"
        >
          <span v-if="saving" class="lucide-refresh-cw size-3 animate-spin inline-block mr-1" />
          <span>{{ currentLang === 'vi' ? 'Lưu cài đặt' : 'Save Settings' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, watch } from "vue";

const props = defineProps({
  settings: { type: Object, default: () => ({}) },
  videoStyles: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
  currentLang: { type: String, default: "en" },
});

const emit = defineEmits(["close", "save"]);

const formatPresets = [
  { value: "Landscape", label: "Landscape", sub: "16:9 · 1920x1080", icon: "🖥️" },
  { value: "Portrait", label: "Portrait", sub: "9:16 · 1080x1920", icon: "📱" },
  { value: "Square", label: "Square", sub: "1:1 · 1080x1080", icon: "⏹️" },
];

const form = reactive({
  delivery_preset: "Landscape",
  total_duration_seconds: 15,
  generation_mode: "Multi-shot",
  video_style: null,
  global_instructions: "",
});

watch(
  () => props.settings,
  (s) => {
    if (s) {
      form.delivery_preset = s.delivery_preset || "Landscape";
      form.total_duration_seconds = Number(s.duration || s.total_duration_seconds) || 15;
      form.generation_mode = s.generation_mode || "Multi-shot";
      form.video_style = s.video_style || s.workflow_key || null;
      form.global_instructions = s.global_instructions || "";
    }
  },
  { immediate: true }
);

function submitSave() {
  emit("save", { ...form });
}
</script>

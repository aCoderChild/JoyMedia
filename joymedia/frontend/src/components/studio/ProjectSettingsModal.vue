<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-xs" @click.self="$emit('close')">
    <div class="w-full max-w-lg bg-surface-card border border-outline-border rounded-2xl p-6 shadow-2xl space-y-4 text-xs">
      <!-- Modal Header -->
      <div class="flex items-center justify-between pb-3 border-b border-outline-border">
        <div>
          <h3 class="text-sm font-bold text-ink-primary flex items-center gap-2">
            <span>⚙</span>
            <span>{{ currentLang === 'vi' ? 'Cài đặt video' : 'Video settings' }}</span>
          </h3>
          <p class="text-xs text-ink-muted mt-0.5">
            {{ currentLang === 'vi' ? 'Khung hình, độ dài, nhạc nền và chữ kết thúc.' : 'Shape, length, music and closing title.' }}
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
            {{ currentLang === 'vi' ? 'Khung hình:' : 'Shape:' }}
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
              <span class="text-xs font-semibold">{{ currentLang === 'vi' ? preset.vi : preset.label }}</span>
              <span class="text-[10px] text-ink-muted">{{ preset.sub }}</span>
            </button>
          </div>
        </div>

        <!-- 2. Target Duration -->
        <div class="space-y-1.5">
          <div class="flex items-center justify-between">
            <label class="font-bold text-ink-primary">
              {{ currentLang === 'vi' ? 'Độ dài video:' : 'Video length:' }}
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

        <!-- Music -->
        <div class="space-y-1.5">
          <label class="block font-bold text-ink-primary">
            {{ currentLang === 'vi' ? 'Nhạc nền:' : 'Music:' }}
          </label>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="mood in musicMoods"
              :key="mood.key"
              type="button"
              class="px-2.5 py-1 rounded-full border text-[11px] cursor-pointer transition-colors"
              :class="form.soundtrack_prompt === mood.prompt
                ? 'border-indigo-500 bg-indigo-500/20 text-indigo-400 font-bold'
                : 'border-outline-border bg-surface-muted text-ink-secondary hover:border-indigo-400'"
              @click="form.soundtrack_prompt = mood.prompt; customMusic = false"
            >
              {{ currentLang === 'vi' ? mood.vi : mood.en }}
            </button>
            <button
              type="button"
              class="px-2.5 py-1 rounded-full border text-[11px] cursor-pointer transition-colors"
              :class="showCustomMusic
                ? 'border-indigo-500 bg-indigo-500/20 text-indigo-400 font-bold'
                : 'border-dashed border-outline-border text-ink-muted hover:border-indigo-400'"
              @click="customMusic = true"
            >
              {{ currentLang === 'vi' ? 'Tự mô tả…' : 'Describe my own…' }}
            </button>
          </div>
          <textarea
            v-if="showCustomMusic"
            v-model="form.soundtrack_prompt"
            rows="2"
            :placeholder="currentLang === 'vi'
              ? 'Viết bằng tiếng Việt hoặc tiếng Anh, vd: guitar mộc vui tươi, trống nhẹ'
              : 'Any language, e.g. uplifting acoustic guitar and soft drums'"
            class="w-full px-3 py-2 rounded-xl bg-surface-muted border border-outline-border text-xs text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-indigo-500 resize-none"
          />
        </div>

        <!-- End card -->
        <div class="space-y-1.5">
          <label class="block font-bold text-ink-primary">
            {{ currentLang === 'vi' ? 'Chữ kết thúc video:' : 'Closing title:' }}
          </label>
          <input
            v-model="form.end_card_title"
            type="text"
            maxlength="60"
            :placeholder="currentLang === 'vi' ? 'Tên thương hiệu hoặc sản phẩm' : 'Brand or product name'"
            class="w-full px-3 py-2 rounded-xl bg-surface-muted border border-outline-border text-xs text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-indigo-500"
          />
          <input
            v-model="form.end_card_tagline"
            type="text"
            maxlength="80"
            :placeholder="currentLang === 'vi' ? 'Câu khẩu hiệu ngắn' : 'A short slogan'"
            class="w-full px-3 py-2 rounded-xl bg-surface-muted border border-outline-border text-xs text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-indigo-500"
          />
          <p class="text-[10.5px] text-ink-muted">
            {{ currentLang === 'vi' ? 'Không bắt buộc. Hiện ở cuối video.' : 'Optional. Shown at the end of the video.' }}
          </p>
        </div>

        <!-- Export quality -->
        <div class="space-y-1.5">
          <label class="block font-bold text-ink-primary">
            {{ currentLang === 'vi' ? 'Chất lượng tải xuống:' : 'Download quality:' }}
          </label>
          <div class="grid grid-cols-2 gap-2">
            <button
              v-for="option in exportQualities"
              :key="option.value"
              type="button"
              class="text-left px-3 py-2 rounded-xl border text-xs cursor-pointer"
              :class="form.export_quality === option.value
                ? 'border-indigo-500 bg-indigo-500/20 text-ink-primary'
                : 'border-outline-border bg-surface-muted hover:border-indigo-400 text-ink-secondary'"
              @click="form.export_quality = option.value"
            >
              <span class="block font-semibold">{{ currentLang === 'vi' ? option.vi : option.en }}</span>
              <span class="block text-[10.5px] text-ink-muted mt-0.5">{{ currentLang === 'vi' ? option.viSub : option.enSub }}</span>
            </button>
          </div>
        </div>

        <!-- Collapsible Advanced Settings -->
        <div class="pt-2 border-t border-outline-border">
          <button
            type="button"
            class="text-xs text-ink-muted hover:text-ink-primary font-semibold flex items-center gap-1.5 cursor-pointer py-1"
            @click="showAdvanced = !showAdvanced"
          >
            <span>{{ showAdvanced ? '▾' : '▸' }}</span>
            <span>{{ currentLang === 'vi' ? 'Cài đặt nâng cao (cho người dùng kỹ thuật)' : 'Advanced settings (for technical users)' }}</span>
          </button>

          <div v-if="showAdvanced" class="space-y-3 pt-2">
            <!-- 3. Scene Continuity -->
            <div class="space-y-1.5">
              <label class="block font-semibold text-ink-primary">
                {{ currentLang === 'vi' ? 'Liên kết giữa các cảnh:' : 'Scene continuity:' }}
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
                    <span class="text-xs font-semibold">{{ currentLang === 'vi' ? 'Nối tiếp liền mạch' : 'Keep scenes consistent' }}</span>
                  </div>
                  <p class="text-[10.5px] text-ink-muted mt-1 leading-normal font-normal">
                    {{ currentLang === 'vi' ? 'Cảnh sau tiếp nối trực tiếp chuyển động của cảnh trước.' : 'Smooth visual transitions chaining consecutive scenes.' }}
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
                    <span class="text-xs font-semibold">{{ currentLang === 'vi' ? 'Các cảnh độc lập' : 'Independent scenes' }}</span>
                  </div>
                  <p class="text-[10.5px] text-ink-muted mt-1 leading-normal font-normal">
                    {{ currentLang === 'vi' ? 'Cắt cảnh linh hoạt theo từng góc quay riêng biệt.' : 'Dynamic commercial cuts with distinct camera angles.' }}
                  </p>
                </button>
              </div>
            </div>

            <!-- User-facing profile controls; backend workflows remain internal. -->
            <div class="space-y-1.5">
              <label class="block font-semibold text-ink-primary">
                {{ currentLang === 'vi' ? 'Ảnh tham chiếu mỗi cảnh:' : 'References per shot:' }}
              </label>
              <div class="grid grid-cols-2 gap-2">
                <button
                  v-for="mode in referenceModes"
                  :key="mode.value"
                  type="button"
                  class="p-2.5 rounded-xl border text-left transition-all cursor-pointer"
                  :class="form.reference_mode === mode.value
                    ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400 font-bold shadow-xs'
                    : 'border-outline-border bg-surface-muted hover:border-indigo-400 text-ink-secondary'"
                  @click="setReferenceMode(mode.value)"
                >
                  <span class="text-xs font-semibold">{{ currentLang === 'vi' ? mode.viLabel : mode.label }}</span>
                  <p class="text-[10.5px] text-ink-muted mt-1 leading-normal font-normal">{{ currentLang === 'vi' ? mode.viSub : mode.sub }}</p>
                </button>
              </div>
            </div>

            <div class="space-y-1.5">
              <label class="block font-semibold text-ink-primary">
                {{ currentLang === 'vi' ? 'Chất lượng:' : 'Quality:' }}
              </label>
              <div class="grid grid-cols-2 gap-2">
                <button
                  v-for="quality in qualityModes"
                  :key="quality.value"
                  type="button"
                  class="p-2.5 rounded-xl border text-left transition-all cursor-pointer"
                  :class="form.quality_mode === quality.value
                    ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400 font-bold shadow-xs'
                    : 'border-outline-border bg-surface-muted hover:border-indigo-400 text-ink-secondary'
                    + (form.reference_mode === 'Single Image' && quality.value === 'Draft'
                      ? ' opacity-50 cursor-not-allowed'
                      : '')"
                  :disabled="form.reference_mode === 'Single Image' && quality.value === 'Draft'"
                  @click="form.quality_mode = quality.value"
                >
                  <span class="text-xs font-semibold">{{ currentLang === 'vi' ? quality.viLabel : quality.label }}</span>
                  <p class="text-[10.5px] text-ink-muted mt-1 leading-normal font-normal">{{ currentLang === 'vi' ? quality.viSub : quality.sub }}</p>
                </button>
              </div>
            </div>

            <!-- Global Instructions -->
            <div class="space-y-1.5">
              <label class="block font-semibold text-ink-primary">
                {{ currentLang === 'vi' ? 'Chỉ dẫn chung toàn video (Instructions):' : 'Additional Instructions:' }}
              </label>
              <textarea
                v-model="form.global_instructions"
                rows="2"
                :placeholder="currentLang === 'vi'
                  ? 'Tông màu ấm, không gian hiện đại, màu sắc tự nhiên...'
                  : 'Warm tones, minimalist modern studio, cinematic lighting...'"
                class="w-full px-3 py-2 rounded-xl bg-surface-muted border border-outline-border text-xs text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-indigo-500 resize-none"
              />
            </div>
          </div>
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
import { computed, reactive, ref, watch } from "vue";

const props = defineProps({
  settings: { type: Object, default: () => ({}) },
  videoStyles: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
  currentLang: { type: String, default: "en" },
});

const emit = defineEmits(["close", "save"]);
const showAdvanced = ref(false);

const formatPresets = [
  { value: "Landscape", label: "Landscape", vi: "Ngang", sub: "16:9 · YouTube, Web", icon: "🖥️" },
  { value: "Portrait", label: "Portrait", vi: "Dọc", sub: "9:16 · TikTok, Reels", icon: "📱" },
  { value: "Square", label: "Square", vi: "Vuông", sub: "1:1 · Facebook, Instagram", icon: "⏹️" },
];

const referenceModes = [
  { value: "Single Image", label: "Single image", sub: "One starting image per scene.", viLabel: "Một ảnh", viSub: "Mỗi cảnh bắt đầu từ một ảnh." },
  { value: "Multi-reference", label: "Person + place", sub: "Two reference images per scene.", viLabel: "Người + địa điểm", viSub: "Hai ảnh tham chiếu cho mỗi cảnh." },
];

const qualityModes = [
  { value: "Draft", label: "Draft", sub: "Faster previews.", viLabel: "Nháp", viSub: "Xem trước nhanh hơn." },
  { value: "Production", label: "Final", sub: "Best rendering quality.", viLabel: "Hoàn chỉnh", viSub: "Chất lượng dựng tốt nhất." },
];

// The prompts are English for the AI; the labels are what marketers see.
const musicMoods = [
  { key: "gentle", en: "Gentle", vi: "Nhẹ nhàng", prompt: "a gentle cinematic instrumental score, soft piano melody over warm strings, slowly building with emotion, then resolving softly at the end" },
  { key: "uplifting", en: "Uplifting", vi: "Tươi vui", prompt: "an uplifting modern instrumental, bright acoustic guitar and light claps over warm pads, positive and hopeful, steady medium tempo" },
  { key: "energetic", en: "Energetic", vi: "Sôi động", prompt: "an energetic upbeat electronic pop instrumental, punchy drums, driving bass and bright synth hooks, fast tempo" },
  { key: "inspiring", en: "Inspiring", vi: "Truyền cảm hứng", prompt: "an inspiring cinematic instrumental, steady piano pulse and soaring strings building to a hopeful, confident climax" },
  { key: "calm", en: "Calm", vi: "Thư giãn", prompt: "a calm ambient instrumental, soft airy pads, gentle felt piano and light textures, slow and relaxing" },
  { key: "modern", en: "Modern", vi: "Hiện đại", prompt: "a clean modern instrumental, plucked synths and soft electronic beat with a light, confident groove" },
];
const customMusic = ref(false);
// The text box appears for "Describe my own" or a prompt that is not one of the moods.
const showCustomMusic = computed(
  () => customMusic.value || Boolean(form.soundtrack_prompt && !musicMoods.some((mood) => mood.prompt === form.soundtrack_prompt))
);

const form = reactive({
  delivery_preset: "Landscape",
  total_duration_seconds: 15,
  generation_mode: "Multi-shot",
  reference_mode: "Single Image",
  quality_mode: "Production",
  global_instructions: "",
  end_card_title: "",
  end_card_tagline: "",
  soundtrack_prompt: "",
  export_quality: "Standard 1080p",
});

const exportQualities = [
  { value: "Standard 1080p", vi: "Tiêu chuẩn · 1080p", en: "Standard · 1080p", viSub: "24 khung/giây, vài phút", enSub: "24 fps, a few minutes" },
  { value: "Studio 1440p60", vi: "Studio · 1440p 60fps", en: "Studio · 1440p 60fps", viSub: "AI làm nét và làm mượt, ~25 phút cho 30 giây", enSub: "AI sharpened and smoothed, ~25 min per 30 s" },
];

watch(
  () => props.settings,
  (s) => {
    if (s) {
      form.delivery_preset = s.delivery_preset || "Landscape";
      form.total_duration_seconds = Number(s.duration || s.total_duration_seconds) || 15;
      form.generation_mode = s.generation_mode || "Multi-shot";
      form.reference_mode = s.reference_mode || "Single Image";
      form.quality_mode = s.quality_mode || "Production";
      if (form.reference_mode === "Single Image") {
        form.quality_mode = "Production";
      }
      form.global_instructions = s.global_instructions || "";
      form.end_card_title = s.end_card_title || "";
      form.end_card_tagline = s.end_card_tagline || "";
      form.soundtrack_prompt = s.soundtrack_prompt || "";
      form.export_quality = s.export_quality || "Standard 1080p";
    }
  },
  { immediate: true }
);

function submitSave() {
	emit("save", { ...form });
}

function setReferenceMode(mode) {
  form.reference_mode = mode;
  if (mode === "Single Image") {
    form.quality_mode = "Production";
  }
}
</script>

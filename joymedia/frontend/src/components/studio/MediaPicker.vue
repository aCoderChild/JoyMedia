<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs" @click.self="$emit('close')">
    <div class="w-full max-w-3xl max-h-[85vh] overflow-hidden bg-surface-card border border-outline-border rounded-2xl shadow-2xl flex flex-col">
      <!-- Modal Header -->
      <div class="flex items-center justify-between p-4 border-b border-outline-border">
        <div>
          <h3 class="text-sm font-bold text-ink-primary">
            {{ isKeyframeTarget
              ? (currentLang === 'vi' ? 'Chọn ảnh tham chiếu Frame' : 'Select Keyframe Reference')
              : (currentLang === 'vi' ? 'Thêm tư liệu vào Dự án' : 'Add Project Reference') }}
          </h3>
          <p class="text-xs text-ink-muted mt-0.5">
            {{ isKeyframeTarget
              ? (currentLang === 'vi' ? 'Chọn ảnh làm frame đầu hoặc cuối cho cảnh này.' : 'Choose an image to guide start or end of this scene.')
              : (currentLang === 'vi' ? 'Chọn tư liệu và vai trò (Role) trong video (Sản phẩm, Nhân vật, Bối cảnh...).' : 'Choose media and specify its role (Product, Character, Environment...).') }}
          </p>
        </div>
        <button
          type="button"
          class="text-ink-muted hover:text-ink-primary p-1.5 rounded-lg hover:bg-surface-hover transition-colors cursor-pointer"
          @click="$emit('close')"
        >
          ✕
        </button>
      </div>

      <!-- Filter / Search / Upload Bar -->
      <div class="px-4 py-3 border-b border-outline-border bg-surface-muted/50 flex flex-wrap items-center justify-between gap-3 text-xs">
        <div class="flex items-center gap-2">
          <!-- Type Filter -->
          <div class="flex items-center gap-1 p-0.5 rounded-lg bg-surface-card border border-outline-border">
            <button
              v-for="t in ['All', 'Image', 'Video', 'Audio']"
              :key="t"
              type="button"
              class="px-2.5 py-1 rounded-md font-semibold transition-colors"
              :class="activeTypeFilter === t ? 'bg-indigo-600 text-white shadow-xs' : 'text-ink-secondary hover:text-ink-primary'"
              @click="activeTypeFilter = t"
            >
              {{ t }}
            </button>
          </div>

          <!-- Search Input -->
          <input
            v-model="searchQuery"
            type="text"
            :placeholder="currentLang === 'vi' ? 'Tìm theo tên...' : 'Search by name...'"
            class="px-3 py-1 rounded-lg bg-surface-card border border-outline-border text-xs text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-indigo-500"
          />
        </div>

        <!-- Quick Upload Button -->
        <label class="jm-btn-secondary !py-1 !px-3 text-xs flex items-center gap-1.5 cursor-pointer">
          <span>⬆</span>
          <span>{{ currentLang === 'vi' ? 'Tải tệp lên' : 'Upload file' }}</span>
          <input
            type="file"
            accept="image/*,video/*,audio/*"
            multiple
            class="hidden"
            :disabled="uploading"
            @change="handleFileUpload"
          />
        </label>
      </div>

      <!-- Main Body: Two Columns if an asset is selected for role configuration, or Full Grid -->
      <div class="flex-1 overflow-y-auto p-4 flex flex-col md:flex-row gap-4">
        <!-- Asset Grid -->
        <div class="flex-1 overflow-y-auto">
          <div v-if="loading" class="py-16 text-center text-xs text-ink-muted">
            <span class="lucide-refresh-cw size-5 animate-spin inline-block mb-2" />
            <p>{{ currentLang === 'vi' ? 'Đang tải thư viện...' : 'Loading media library...' }}</p>
          </div>

          <div v-else-if="filteredCandidates.length" class="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <button
              v-for="asset in filteredCandidates"
              :key="asset.name"
              type="button"
              class="text-left p-2 rounded-xl border transition-all cursor-pointer relative group"
              :class="[
                selectedCandidate?.name === asset.name
                  ? 'border-indigo-500 bg-indigo-500/10 ring-2 ring-indigo-500/40'
                  : asset.selected && !isKeyframeTarget
                    ? 'border-emerald-500/50 bg-emerald-500/5 hover:border-emerald-500'
                    : 'border-outline-border bg-surface-muted hover:border-indigo-400'
              ]"
              @click="onCandidateClick(asset)"
            >
              <MediaThumbnail
                :src="asset.file"
                :media-type="asset.media_type"
                :alt="asset.asset_name"
                :duration="asset.duration_seconds"
                aspect="aspect-video"
              />

              <div class="mt-2 min-w-0">
                <span class="block truncate text-xs font-semibold text-ink-primary">{{ asset.asset_name }}</span>
                <div class="flex items-center justify-between text-[10px] text-ink-muted mt-0.5">
                  <span class="capitalize">{{ asset.asset_category || asset.media_type }}</span>
                  <span v-if="asset.selected && !isKeyframeTarget" class="text-emerald-400 font-bold">✓ {{ currentLang === 'vi' ? 'Đã thêm' : 'In project' }}</span>
                </div>
              </div>
            </button>
          </div>

          <div v-else class="py-16 text-center text-xs text-ink-muted">
            {{ currentLang === 'vi' ? 'Không có tư liệu phù hợp.' : 'No matching media assets found.' }}
          </div>
        </div>

        <!-- Role Configuration Panel (Explicit Project Reference Roles) -->
        <div
          v-if="!isKeyframeTarget && selectedCandidate"
          class="w-full md:w-72 shrink-0 p-4 rounded-xl bg-surface-muted border border-outline-border flex flex-col justify-between space-y-4"
        >
          <div class="space-y-3">
            <div class="flex items-center justify-between border-b border-outline-border pb-2">
              <span class="text-xs font-bold text-ink-primary">{{ currentLang === 'vi' ? 'Cấu hình tư liệu' : 'Use Reference As' }}</span>
              <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-card text-indigo-400 font-bold border border-outline-border">
                {{ selectedCandidate.media_type }}
              </span>
            </div>

            <div class="flex items-center gap-2.5">
              <div class="size-12 shrink-0 rounded-lg overflow-hidden bg-black border border-outline-border">
                <MediaThumbnail
                  :src="selectedCandidate.file"
                  :media-type="selectedCandidate.media_type"
                  :alt="selectedCandidate.asset_name"
                  aspect="aspect-square"
                />
              </div>
              <div class="min-w-0">
                <span class="block truncate text-xs font-bold text-ink-primary">{{ selectedCandidate.asset_name }}</span>
                <span class="block text-[11px] text-ink-muted">{{ currentLang === 'vi' ? 'Chọn vai trò cho AI' : 'Assign role for AI generation' }}</span>
              </div>
            </div>

            <!-- Role Selector Radio List -->
            <div class="space-y-1.5 pt-1">
              <label class="block text-[11px] font-semibold text-ink-secondary">
                {{ currentLang === 'vi' ? 'Vai trò trong video (Role):' : 'Reference Role:' }}
              </label>

              <div class="space-y-1 text-xs">
                <label
                  v-for="role in roleOptions"
                  :key="role.value"
                  class="flex items-center justify-between p-2 rounded-lg border cursor-pointer transition-colors"
                  :class="selectedRole === role.value ? 'border-indigo-500 bg-indigo-500/15 text-ink-primary font-bold' : 'border-outline-border bg-surface-card hover:bg-surface-hover text-ink-secondary'"
                >
                  <div class="flex items-center gap-2">
                    <input
                      v-model="selectedRole"
                      type="radio"
                      :value="role.value"
                      class="text-indigo-600 focus:ring-indigo-500"
                    />
                    <span>{{ role.label }}</span>
                  </div>
                  <span class="text-xs">{{ role.icon }}</span>
                </label>
              </div>
            </div>
          </div>

          <!-- Add Action Button -->
          <div class="pt-2 border-t border-outline-border">
            <button
              type="button"
              class="w-full jm-btn-primary !py-2 text-xs flex items-center justify-center gap-1.5 shadow-md cursor-pointer"
              :disabled="saving"
              @click="confirmAddReference"
            >
              <span v-if="saving" class="lucide-refresh-cw size-3 animate-spin" />
              <span v-else>+</span>
              <span>
                {{ selectedCandidate.selected
                  ? (currentLang === 'vi' ? 'Cập nhật vai trò' : 'Update Role')
                  : (currentLang === 'vi' ? 'Thêm vào Dự án' : 'Add to Project') }}
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import MediaThumbnail from "../MediaThumbnail.vue";

const props = defineProps({
  candidates: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  uploading: { type: Boolean, default: false },
  isKeyframeTarget: { type: Boolean, default: false },
  currentLang: { type: String, default: "en" },
});

const emit = defineEmits(["close", "selectReference", "setKeyframe", "uploadFiles"]);

const searchQuery = ref("");
const activeTypeFilter = ref("All");
const selectedCandidate = ref(null);
const selectedRole = ref("Product");

const roleOptions = [
  { value: "Product", label: "Product (Sản phẩm)", icon: "👟" },
  { value: "Character", label: "Character (Nhân vật / Người mẫu)", icon: "👤" },
  { value: "Environment", label: "Environment (Bối cảnh / Không gian)", icon: "🏞️" },
  { value: "Style", label: "Style (Phong cách nghệ thuật / Tone màu)", icon: "🎨" },
  { value: "Motion", label: "Motion (Chuyển động mẫu)", icon: "🏃" },
  { value: "Audio", label: "Audio (Nhạc nền / Voiceover)", icon: "🔊" },
  { value: "General", label: "General (Tham khảo chung)", icon: "📎" },
];

function suggestRole(asset) {
  if (!asset) return "General";
  const cat = (asset.asset_category || "").toLowerCase();
  const type = (asset.media_type || "").toLowerCase();
  if (type === "audio") return "Audio";
  if (cat.includes("product") || cat.includes("sản phẩm")) return "Product";
  if (cat.includes("character") || cat.includes("model") || cat.includes("nhân vật")) return "Character";
  if (cat.includes("background") || cat.includes("environment") || cat.includes("bối cảnh")) return "Environment";
  if (cat.includes("style") || cat.includes("phong cách")) return "Style";
  if (cat.includes("motion") || cat.includes("chuyển động")) return "Motion";
  return "General";
}

function onCandidateClick(asset) {
  if (props.isKeyframeTarget) {
    emit("setKeyframe", asset);
    return;
  }
  selectedCandidate.value = asset;
  selectedRole.value = asset.reference_role || suggestRole(asset);
}

function confirmAddReference() {
  if (!selectedCandidate.value) return;
  emit("selectReference", {
    asset: selectedCandidate.value,
    role: selectedRole.value,
  });
}

function handleFileUpload(event) {
  const files = Array.from(event.target.files || []);
  if (files.length) {
    emit("uploadFiles", files);
  }
}

const filteredCandidates = computed(() => {
  return (props.candidates || []).filter((item) => {
    if (activeTypeFilter.value !== "All" && item.media_type !== activeTypeFilter.value) {
      return false;
    }
    if (searchQuery.value) {
      const q = searchQuery.value.toLowerCase();
      const name = (item.asset_name || "").toLowerCase();
      const cat = (item.asset_category || "").toLowerCase();
      if (!name.includes(q) && !cat.includes(q)) return false;
    }
    return true;
  });
});

watch(
  () => props.candidates,
  (cands) => {
    if (cands?.length && !selectedCandidate.value && !props.isKeyframeTarget) {
      const unselected = cands.find((c) => !c.selected) || cands[0];
      if (unselected) {
        selectedCandidate.value = unselected;
        selectedRole.value = unselected.reference_role || suggestRole(unselected);
      }
    }
  },
  { immediate: true }
);
</script>

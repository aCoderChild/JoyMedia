<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-xs" @click.self="$emit('close')">
    <div class="w-full max-w-4xl max-h-[85vh] overflow-hidden bg-surface-card border border-outline-border rounded-2xl shadow-2xl flex flex-col">
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
              : (currentLang === 'vi' ? 'Chọn ảnh, video hoặc âm thanh để AI làm tư liệu tham chiếu.' : 'Select image, video, or audio for AI reference context.') }}
          </p>
        </div>
        <button
          type="button"
          data-testid="close-media-picker"
          aria-label="Close Media Picker"
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
              class="px-2.5 py-1 rounded-md font-semibold transition-colors cursor-pointer"
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

      <div v-if="uploadError" class="mx-4 mt-3 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
        {{ uploadError }}
      </div>

      <!-- Main Body: Clean Responsive Grid -->
      <div class="flex-1 overflow-y-auto p-4">
        <div v-if="loading" class="py-20 text-center text-xs text-ink-muted">
          <span class="lucide-refresh-cw size-5 animate-spin inline-block mb-2" />
          <p>{{ currentLang === 'vi' ? 'Đang tải thư viện...' : 'Loading media library...' }}</p>
        </div>

        <div v-else-if="filteredCandidates.length" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
          <div
            v-for="asset in filteredCandidates"
            :key="asset.name"
            class="relative"
          >
            <button
              type="button"
              class="media-candidate-card w-full text-left p-2 rounded-xl border transition-all cursor-pointer relative group flex flex-col justify-between"
              :class="[
                selectedCandidate?.name === asset.name
                  ? 'border-indigo-500 bg-indigo-500/10 ring-2 ring-indigo-500/40 shadow-sm'
                  : asset.selected && !isKeyframeTarget
                    ? 'border-emerald-500/50 bg-emerald-500/5 hover:border-emerald-500'
                    : 'border-outline-border bg-surface-muted hover:border-indigo-400'
              ]"
              @click="onCandidateClick(asset)"
              @dblclick="confirmAddReference"
            >
              <MediaThumbnail
                :src="asset.file"
                :media-type="asset.media_type"
                :alt="asset.asset_name"
                :duration="asset.duration_seconds"
                aspect="aspect-video"
              />

              <div class="mt-2 min-w-0 w-full">
                <span class="block truncate text-xs font-semibold text-ink-primary">{{ asset.asset_name }}</span>
                <div class="flex items-center justify-between text-[10px] text-ink-muted mt-0.5">
                  <span class="capitalize">{{ asset.asset_category || asset.media_type }}</span>
                  <span v-if="asset.selected && !isKeyframeTarget" class="text-emerald-400 font-bold">✓ {{ currentLang === 'vi' ? 'Đã thêm' : 'In project' }}</span>
                  <span v-else-if="selectedCandidate?.name === asset.name" class="text-indigo-400 font-medium">{{ suggestRole(asset) }}</span>
                </div>
              </div>
            </button>
            <button
              type="button"
              class="absolute top-2 right-2 z-10 size-7 rounded-lg bg-black/60 text-white hover:bg-black/80 cursor-pointer"
              :aria-label="`Actions for ${asset.asset_name}`"
              @click.stop="toggleAssetMenu(asset.name)"
            >
              ⋯
            </button>
            <div
              v-if="assetMenuName === asset.name"
              class="absolute top-10 right-2 z-20 w-44 rounded-xl bg-surface-card border border-outline-border shadow-xl p-1.5"
              @click.stop
            >
              <button
                type="button"
                class="w-full text-left px-2.5 py-2 rounded-lg text-xs text-ink-primary hover:bg-surface-hover cursor-pointer"
                @click="selectFromMenu(asset)"
              >
                {{ asset.selected ? (currentLang === 'vi' ? 'Đổi vai trò' : 'Change role') : (currentLang === 'vi' ? 'Thêm vào dự án' : 'Add to project') }}
              </button>
              <button
                v-if="asset.selected"
                type="button"
                class="w-full text-left px-2.5 py-2 rounded-lg text-xs text-ink-primary hover:bg-surface-hover cursor-pointer"
                @click="emitRemoveFromProject(asset)"
              >
                {{ currentLang === 'vi' ? 'Gỡ khỏi dự án' : 'Remove from project' }}
              </button>
              <button
                type="button"
                class="w-full text-left px-2.5 py-2 rounded-lg text-xs text-rose-400 hover:bg-rose-500/10 cursor-pointer"
                @click="emitArchiveAsset(asset)"
              >
                {{ currentLang === 'vi' ? 'Lưu trữ khỏi thư viện' : 'Archive from library' }}
              </button>
            </div>
          </div>
        </div>

        <div v-else class="py-20 text-center text-xs text-ink-muted">
          {{ currentLang === 'vi' ? 'Không có tư liệu phù hợp.' : 'No matching media assets found.' }}
        </div>
      </div>

      <!-- Bottom Action Dock: Streamlined [ Asset ] Suggested: Role [ Add ] Change role ▾ -->
      <div
        v-if="!isKeyframeTarget && selectedCandidate"
        class="p-3.5 px-4 bg-surface-muted border-t border-outline-border flex flex-wrap items-center justify-between gap-3 text-xs"
      >
        <!-- Left: Selected Asset Info & Inferred Role -->
        <div class="flex items-center gap-2.5 min-w-0">
          <div class="size-9 rounded-lg overflow-hidden bg-black border border-outline-border shrink-0">
            <MediaThumbnail
              :src="selectedCandidate.file"
              :media-type="selectedCandidate.media_type"
              :alt="selectedCandidate.asset_name"
              aspect="aspect-square"
            />
          </div>
          <div class="min-w-0">
            <span class="block truncate text-xs font-bold text-ink-primary max-w-[200px] sm:max-w-xs">
              {{ selectedCandidate.asset_name }}
            </span>
            <div class="flex items-center gap-1.5 text-[11px] mt-0.5">
              <span class="text-ink-muted">{{ currentLang === 'vi' ? 'Đề xuất:' : 'Suggested:' }}</span>
              <span class="font-bold text-indigo-400 flex items-center gap-1">
                <span>{{ getRoleIcon(selectedRole) }}</span>
                <span>{{ selectedRole }}</span>
              </span>
            </div>
          </div>
        </div>

        <!-- Right: Actions (Change Role Dropdown + Quick Add Button) -->
        <div class="flex items-center gap-2 relative">
          <!-- Compact Change Role Dropdown Trigger -->
          <div class="relative">
            <button
              type="button"
              class="px-2.5 py-1.5 rounded-xl border border-outline-border bg-surface-card hover:bg-surface-hover text-ink-secondary hover:text-ink-primary font-medium text-xs flex items-center gap-1.5 transition-colors cursor-pointer"
              @click="showRoleDropdown = !showRoleDropdown"
            >
              <span>{{ currentLang === 'vi' ? 'Đổi vai trò' : 'Change role' }}</span>
              <span class="text-[10px]">▾</span>
            </button>

            <!-- Role Dropdown Menu -->
            <div
              v-if="showRoleDropdown"
              class="absolute bottom-full right-0 mb-1.5 w-56 rounded-xl bg-surface-card border border-outline-border shadow-xl p-1.5 space-y-0.5 z-20"
            >
              <button
                v-for="role in roleOptions"
                :key="role.value"
                type="button"
                class="w-full text-left px-2.5 py-1.5 rounded-lg text-xs flex items-center justify-between cursor-pointer transition-colors"
                :class="selectedRole === role.value ? 'bg-indigo-600 text-white font-bold' : 'hover:bg-surface-hover text-ink-primary'"
                @click="selectedRole = role.value; showRoleDropdown = false"
              >
                <div class="flex items-center gap-2">
                  <span>{{ role.icon }}</span>
                  <span>{{ role.label }}</span>
                </div>
                <span v-if="selectedRole === role.value">✓</span>
              </button>
            </div>
          </div>

          <!-- Add / Update Action Button -->
          <button
            type="button"
            data-testid="confirm-add-reference"
            class="jm-btn-primary !py-1.5 !px-4 text-xs font-bold flex items-center gap-1.5 shadow-md cursor-pointer"
            :disabled="saving"
            @click="confirmAddReference"
          >
            <span v-if="saving" class="lucide-refresh-cw size-3.5 animate-spin" />
            <span v-else class="text-sm">+</span>
            <span>
              {{ selectedCandidate.selected
                ? (currentLang === 'vi' ? 'Cập nhật' : 'Update')
                : (currentLang === 'vi' ? 'Thêm tư liệu' : 'Add Reference') }}
            </span>
          </button>
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
  uploadError: { type: String, default: "" },
  lastUploadedAssetVersion: { type: String, default: "" },
  isKeyframeTarget: { type: Boolean, default: false },
  initialTypeFilter: { type: String, default: "All" },
  currentLang: { type: String, default: "en" },
});

const emit = defineEmits(["close", "selectReference", "setKeyframe", "uploadFiles", "removeReference", "archiveAsset"]);

const searchQuery = ref("");
const activeTypeFilter = ref(props.initialTypeFilter || "All");
const selectedCandidate = ref(null);
const selectedRole = ref("Product");
const showRoleDropdown = ref(false);
const assetMenuName = ref("");

watch(
  () => props.initialTypeFilter,
  (val) => {
    if (val) activeTypeFilter.value = val;
  }
);

const roleOptions = [
  { value: "Product", label: "Product", icon: "👟" },
  { value: "Character", label: "Character", icon: "👤" },
  { value: "Environment", label: "Environment", icon: "🏞️" },
  { value: "Style", label: "Style", icon: "🎨" },
  { value: "Motion", label: "Motion", icon: "🏃" },
  { value: "Audio", label: "Audio", icon: "🔊" },
  { value: "General", label: "General", icon: "📎" },
];

function getRoleIcon(role) {
  const match = roleOptions.find((r) => r.value === role);
  return match?.icon || "📎";
}

function suggestRole(asset) {
  if (!asset) return "Product";
  const type = (asset.media_type || "").toLowerCase();
  const cat = (asset.asset_category || "").toLowerCase();
  if (type === "audio") return "Audio";
  if (cat.includes("character") || cat.includes("model") || cat.includes("nhân vật")) return "Character";
  if (cat.includes("background") || cat.includes("environment") || cat.includes("bối cảnh")) return "Environment";
  if (cat.includes("style") || cat.includes("phong cách")) return "Style";
  if (cat.includes("motion") || cat.includes("chuyển động")) return "Motion";
  return "Product";
}

function onCandidateClick(asset) {
  if (props.isKeyframeTarget) {
    emit("setKeyframe", asset);
    return;
  }
  selectedCandidate.value = asset;
  selectedRole.value = asset.reference_role || suggestRole(asset);
  showRoleDropdown.value = false;
  assetMenuName.value = "";
}

function toggleAssetMenu(assetName) {
  assetMenuName.value = assetMenuName.value === assetName ? "" : assetName;
}

function selectFromMenu(asset) {
  onCandidateClick(asset);
  assetMenuName.value = "";
}

function emitRemoveFromProject(asset) {
  assetMenuName.value = "";
  emit("removeReference", asset);
}

function emitArchiveAsset(asset) {
  assetMenuName.value = "";
  emit("archiveAsset", asset);
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
  [filteredCandidates, activeTypeFilter],
  () => {
    if (props.isKeyframeTarget) return;

    const visible = filteredCandidates.value;
    if (!visible.length) {
      selectedCandidate.value = null;
      showRoleDropdown.value = false;
      return;
    }

    const uploaded = props.lastUploadedAssetVersion
      ? visible.find((item) => item.asset_version === props.lastUploadedAssetVersion)
      : null;
    const selectedIsVisible = visible.some(
      (item) => item.name === selectedCandidate.value?.name
    );
    const next = uploaded
      || (selectedIsVisible ? selectedCandidate.value : null)
      || visible.find((item) => !item.selected)
      || visible[0];

    selectedCandidate.value = next;
    selectedRole.value = next.reference_role || suggestRole(next);
  },
  { immediate: true }
);
</script>

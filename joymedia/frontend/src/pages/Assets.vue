<template>
  <section class="page-section">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ t('assets_eyebrow') }}</p>
        <h1>{{ t('assets_title') }}</h1>
        <p class="subtitle">{{ t('assets_subtitle') }}</p>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="solid" class="!bg-indigo-600 hover:!bg-indigo-500 !text-white" @click="showUploadModal = true">
          <template #prefix>
            <span class="lucide-plus size-4" />
          </template>
          {{ t('btn_add_media') }}
        </Button>
        <Button variant="subtle" @click="openCampaigns">
          <template #prefix>
            <span class="lucide-clapperboard size-4" />
          </template>
          {{ t('btn_view_campaigns') }}
        </Button>
      </div>
    </div>

    <!-- Single Clean Filter Row: Types + Filter Dropdown + Search -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-2.5 sm:p-3 rounded-2xl bg-surface-card border border-outline-border shadow-xs mb-6">
      <div class="flex flex-wrap items-center gap-2">
        <!-- Media Type Filter Pills -->
        <div class="flex items-center gap-1 p-0.5 rounded-xl bg-surface-muted border border-outline-border text-xs">
          <button
            v-for="opt in typeOptions"
            :key="opt.value"
            type="button"
            class="px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer"
            :class="activeType === opt.value
              ? 'bg-indigo-600 text-white shadow-xs'
              : 'text-ink-secondary hover:text-ink-primary'"
            @click="activeType = opt.value"
          >
            {{ opt.label }}
          </button>
        </div>

        <!-- Category Dropdown Filter: Filter ▾ -->
        <div class="relative">
          <select
            v-model="activeCategory"
            class="text-xs font-semibold px-3 py-1.5 rounded-xl bg-surface-muted border border-outline-border text-ink-secondary hover:text-ink-primary cursor-pointer focus:outline-none focus:border-indigo-500"
          >
            <option value="All">{{ currentLang === 'vi' ? 'Mọi danh mục ▾' : 'All Categories ▾' }}</option>
            <option value="Product">👟 Product</option>
            <option value="Character">👤 Character</option>
            <option value="Background">🏞️ Environment</option>
            <option value="Brand">🏷️ Brand</option>
            <option value="Style">🎨 Style</option>
            <option value="Reference">📎 Reference</option>
          </select>
        </div>
      </div>

      <div class="flex items-center gap-2.5">
        <span class="text-xs font-medium text-ink-muted">
          {{ filteredAssets.length }} {{ filteredAssets.length === 1 ? t('asset_singular') : t('asset_plural') }}
        </span>
        <FormControl
          v-model="search"
          type="text"
          :placeholder="t('asset_search_placeholder')"
          class="w-full sm:w-52"
        >
          <template #prefix>
            <span class="lucide-search size-4 text-ink-muted" />
          </template>
        </FormControl>
      </div>
    </div>

    <div v-if="assetsResource.loading" class="empty-state">
      <div class="empty-state-icon">
        <span class="lucide-refresh-cw size-6 animate-spin" />
      </div>
      <h2>{{ t('assets_loading_title') }}</h2>
      <p>{{ t('assets_loading_desc') }}</p>
    </div>

    <!-- Asset Cards Grid (Clean Flow-like minimal cards) -->
    <div v-else-if="filteredAssets.length" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3.5">
      <article
        v-for="asset in filteredAssets"
        :key="asset.name"
        class="group relative p-2 rounded-2xl bg-surface-card hover:bg-surface-hover border border-outline-border hover:border-indigo-500/50 shadow-xs hover:shadow-md transition-all cursor-pointer select-none flex flex-col gap-2"
        @click="openAssetModal(asset)"
      >
        <button
          type="button"
          class="absolute top-2 right-2 z-20 size-7 rounded-lg bg-black/60 text-white hover:bg-black/80 transition-colors cursor-pointer"
          :aria-label="`Actions for ${asset.asset_name}`"
          @click.stop="toggleAssetMenu(asset.name)"
        >
          ⋯
        </button>
        <div
          v-if="assetMenuName === asset.name"
          class="absolute top-10 right-2 z-30 w-44 rounded-xl bg-surface-card border border-outline-border shadow-xl p-1.5"
          @click.stop
        >
          <button
            type="button"
            class="w-full text-left px-2.5 py-2 rounded-lg text-xs text-rose-400 hover:bg-rose-500/10 cursor-pointer"
            @click="archiveAsset(asset)"
          >
            Archive from library
          </button>
        </div>
        <MediaThumbnail
          :src="asset.file"
          :media-type="asset.media_type"
          :alt="asset.asset_name"
          :badge="asset.asset_category || 'Reference'"
          :duration="asset.duration_seconds"
          aspect="aspect-square"
        />

        <div class="px-1 pb-0.5">
          <h3 class="text-xs font-semibold text-ink-primary truncate" :title="asset.asset_name">
            {{ asset.asset_name }}
          </h3>
        </div>
      </article>
    </div>

    <div v-else class="empty-state">
      <div class="empty-state-icon">
        <span class="lucide-image size-7" />
      </div>
      <h2>{{ t('assets_empty_title') }}</h2>
      <p>{{ t('assets_empty_desc') }}</p>
      <Button variant="solid" class="!bg-indigo-600 hover:!bg-indigo-500 !text-white" @click="resetFilters">
        {{ t('asset_reset_filters') }}
      </Button>
    </div>

    <!-- Interactive Media Asset Viewer Modal -->
    <div
      v-if="selectedAsset"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs"
      @click.self="selectedAsset = null"
      @keydown.esc="selectedAsset = null"
    >
      <div class="w-full max-w-2xl bg-surface-card rounded-2xl border border-outline-border shadow-2xl overflow-hidden flex flex-col max-h-[90vh] animate-in fade-in zoom-in-95 duration-150">
        <!-- Modal Header -->
        <div class="p-4 border-b border-outline-border flex items-center justify-between gap-3 bg-surface-hover/50">
          <div class="min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span
                class="text-[10px] px-2 py-0.5 rounded font-bold uppercase tracking-wider bg-indigo-600 text-white"
              >
                {{ selectedAsset.asset_category || 'Reference' }}
              </span>
            </div>
            <h2 class="text-base font-bold text-ink-primary truncate" :title="selectedAsset.asset_name">
              {{ selectedAsset.asset_name }}
            </h2>
          </div>

          <button
            type="button"
            class="p-1.5 rounded-lg text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors"
            @click="selectedAsset = null"
          >
            <span class="lucide-x size-5" />
          </button>
        </div>

        <!-- Modal Media Area -->
        <div class="p-4 bg-black/5 dark:bg-black/40 flex items-center justify-center overflow-hidden flex-1 min-h-[260px] max-h-[55vh]">
          <!-- Video Player -->
          <video
            v-if="selectedAsset.file && (selectedAsset.media_type === 'Video' || isVideoUrl(selectedAsset.file))"
            :src="selectedAsset.file"
            controls
            autoplay
            preload="metadata"
            class="max-h-[52vh] w-full rounded-xl bg-black object-contain shadow-lg"
          />

          <!-- Audio Player -->
          <audio
            v-else-if="selectedAsset.file && selectedAsset.media_type === 'Audio'"
            :src="selectedAsset.file"
            controls
            autoplay
            class="w-full"
          />

          <!-- Image Viewer -->
          <img
            v-else-if="selectedAsset.file"
            :src="selectedAsset.file"
            :alt="selectedAsset.asset_name"
            class="max-h-[52vh] max-w-full rounded-xl object-contain shadow-lg"
          />

          <!-- Fallback Placeholder -->
          <div v-else class="text-center p-8 text-ink-muted">
            <span class="lucide-file-question size-10 mx-auto mb-2 opacity-50" />
            <p class="text-sm font-medium">{{ t('asset_preview_unavailable') }}</p>
            <p class="text-xs mt-1 text-ink-muted">{{ t('asset_id_label') }}: {{ selectedAsset.name }}</p>
          </div>
        </div>

        <!-- Modal Footer & Metadata Details -->
        <div class="p-4 bg-surface-card border-t border-outline-border flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-3 text-xs text-ink-secondary">
            <span>{{ t('asset_type_label') }}: <strong>{{ selectedAsset.media_type || t('type_images') }}</strong></span>
            <span>·</span>
            <span>{{ t('asset_modified_label') }}: <strong>{{ formatDate(selectedAsset.modified) }}</strong></span>
          </div>

          <div class="flex items-center gap-2">
            <!-- Open in Campaign / Project button -->
            <Button
              v-if="selectedAsset.media_project"
              variant="subtle"
              class="text-xs"
              @click="openProject(selectedAsset.media_project)"
            >
              {{ t('asset_open_project') }}
            </Button>

            <!-- Download Button -->
            <a
              v-if="selectedAsset.file"
              :href="selectedAsset.file"
              download
              class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-700 text-white shadow-xs transition-colors"
            >
              <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
              <span>{{ t('asset_download') }}</span>
            </a>

          <Button variant="subtle" @click="selectedAsset = null">{{ t('asset_close') }}</Button>
          </div>
        </div>
      </div>
    </div>

    <!-- Reference Asset Upload Modal (Frappe Data Model) -->
    <div
      v-if="showUploadModal"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-xs"
      @click.self="showUploadModal = false"
    >
      <div class="w-full max-w-md bg-surface-card border border-outline-border rounded-2xl p-6 shadow-2xl text-xs space-y-4 text-ink-primary">
        <div class="flex items-center justify-between pb-3 border-b border-outline-border">
          <div>
            <h3 class="text-sm font-bold text-ink-primary">{{ t('upload_modal_title') }}</h3>
            <p class="text-ink-secondary text-[11px] mt-0.5">{{ t('upload_modal_sub') }}</p>
          </div>
          <button type="button" class="text-ink-secondary hover:text-ink-primary" @click="showUploadModal = false">✕</button>
        </div>

        <div>
          <label class="block text-ink-secondary font-semibold mb-1">{{ t('upload_category_label') }}</label>
          <FormControl
            v-model="uploadCategory"
            type="select"
            :options="[
              { label: t('cat_product'), value: 'Product' },
              { label: t('cat_character'), value: 'Character' },
              { label: t('cat_background'), value: 'Background' },
              { label: t('cat_brand'), value: 'Brand' },
              { label: t('cat_style'), value: 'Style' },
              { label: t('cat_reference'), value: 'Reference' },
            ]"
          />
        </div>

        <div>
          <label class="block text-ink-secondary font-semibold mb-1">{{ t('upload_file_label') }}</label>
          <input
            type="file"
            accept="image/*,video/*,audio/*"
            class="w-full text-xs text-ink-secondary file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-surface-muted file:text-ink-primary hover:file:bg-surface-hover cursor-pointer"
            @change="onFileChange"
          />
        </div>

        <div class="flex items-center justify-end gap-2 pt-3 border-t border-outline-border">
          <Button variant="subtle" @click="showUploadModal = false">{{ t('btn_cancel') }}</Button>
          <Button variant="solid" :loading="isUploading" @click="handleUploadAsset">{{ t('btn_upload') }}</Button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { Button, FormControl, call, createResource, upload as uploadFile } from "frappe-ui";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";
import { useI18n } from "../stores/i18n";
import MediaThumbnail from "../components/MediaThumbnail.vue";

const { t } = useI18n();
const route = useRoute();
const search = ref("");
const activeType = ref("All");
const activeCategory = ref(route.query?.category || "All");
const selectedAsset = ref(null);
const assetMenuName = ref("");

const showUploadModal = ref(false);
const isUploading = ref(false);
const uploadCategory = ref("Product");
const selectedFile = ref(null);

const typeOptions = computed(() => [
  { label: t('type_all_assets'), value: "All" },
  { label: t('type_images'), value: "Images" },
  { label: t('type_videos'), value: "Videos" },
  { label: t('type_audio'), value: "Audio" },
]);

const categoryOptions = computed(() => [
  { label: t('all_categories'), value: "All" },
  { label: t('cat_product'), value: "Product" },
  { label: t('cat_character'), value: "Character" },
  { label: t('cat_background'), value: "Background" },
  { label: t('cat_brand'), value: "Brand" },
  { label: t('cat_style'), value: "Style" },
  { label: t('cat_reference'), value: "Reference" },
]);

const assetsResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_library_assets",
  params: {
    asset_type: activeType.value,
  },
  auto: true,
});

watch(activeType, () => {
  assetsResource.params = {
    asset_type: activeType.value,
  };
  assetsResource.reload();
});

watch(() => route.query?.category, (newCat) => {
  if (newCat) {
    activeCategory.value = newCat;
  }
});

const filteredAssets = computed(() => {
  let list = assetsResource.data || [];
  if (activeCategory.value !== "All") {
    list = list.filter((a) => a.asset_category === activeCategory.value);
  }
  const q = search.value.trim().toLowerCase();
  if (!q) return list;
  return list.filter((a) => `${a.asset_name} ${a.asset_category}`.toLowerCase().includes(q));
});

function openAssetModal(asset) {
  selectedAsset.value = asset;
  assetMenuName.value = "";
}

function toggleAssetMenu(assetName) {
  assetMenuName.value = assetMenuName.value === assetName ? "" : assetName;
}

async function archiveAsset(asset) {
  assetMenuName.value = "";
  try {
    const result = await call("joymedia.services.media_asset_service.archive_media_asset", {
      media_asset: asset.name,
    });
    if (result?.in_use) {
      const projectCount = result.projects?.length || 0;
      const confirmed = window.confirm(
        `${asset.asset_name} is used by ${projectCount} project(s). Archive it and remove it from those projects?`
      );
      if (!confirmed) return;
      await call("joymedia.services.media_asset_service.archive_media_asset", {
        media_asset: asset.name,
        detach_projects: 1,
      });
    }
    notify({ title: "Asset archived", text: `${asset.asset_name} was removed from the library.`, type: "success" });
    if (selectedAsset.value?.name === asset.name) selectedAsset.value = null;
    await assetsResource.reload();
  } catch (err) {
    notify({ title: "Error", text: errorMessage(err, "Failed to archive asset."), type: "error" });
  }
}

function isVideoUrl(url) {
  if (!url) return false;
  return /\.(mp4|webm|mov|m4v)(\?.*)?$/i.test(url);
}

function formatDate(dateStr) {
  if (!dateStr) return "Recent";
  try {
    const d = new Date(dateStr.replace(" ", "T"));
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return dateStr;
  }
}

function resetFilters() {
  search.value = "";
  activeType.value = "All";
  activeCategory.value = "All";
}

function onFileChange(e) {
  const file = e.target.files?.[0];
  selectedFile.value = file || null;
}

async function handleUploadAsset() {
  if (!selectedFile.value) {
    notify({ title: "Chưa chọn file", text: "Vui lòng chọn một file ảnh.", type: "error" });
    return;
  }
  isUploading.value = true;
  try {
    const uploaded = await uploadFile(selectedFile.value, { private: true });
    if (!uploaded?.file_url || !uploaded?.name) throw new Error("Không thể tải lên file.");

    await call("joymedia.services.media_asset_service.create_media_asset", {
      asset_name: selectedFile.value.name.replace(/\.[^/.]+$/, ""),
      asset_category: uploadCategory.value,
      file_url: uploaded.file_url,
      file_name: uploaded.name,
    });

    notify({ title: "Đã tải lên tư liệu", text: "Đã thêm vào thư viện Media.", type: "success" });
    showUploadModal.value = false;
    selectedFile.value = null;
    await assetsResource.reload();
  } catch (err) {
    notify({ title: "Lỗi tải tư liệu", text: errorMessage(err, "Vui lòng thử lại."), type: "error" });
  } finally {
    isUploading.value = false;
  }
}

function openProject(projectName) {
  window.location.href = `/joymedia/projects/${encodeURIComponent(projectName)}`;
}

function openCampaigns() {
  window.location.href = "/joymedia/campaigns";
}
</script>

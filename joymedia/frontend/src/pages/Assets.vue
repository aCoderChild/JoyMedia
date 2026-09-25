<template>
  <section class="page-section">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ t('assets_eyebrow') }}</p>
        <h1>{{ t('assets_title') }}</h1>
        <p class="subtitle">{{ t('assets_subtitle') }}</p>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="solid" @click="showUploadModal = true">
          <template #prefix>
            <span class="lucide-plus size-4" />
          </template>
          {{ t('btn_add_asset') }}
        </Button>
        <Button appearance="subtle" @click="openCampaigns">
          <template #prefix>
            <span class="lucide-clapperboard size-4" />
          </template>
          {{ t('btn_view_projects') }}
        </Button>
      </div>
    </div>

    <!-- Toolbar: Scope & Type Categorisation Filters -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-2xl bg-surface-card border border-outline-border shadow-xs mb-6">
      <div class="flex flex-wrap items-center gap-3">
        <!-- Type Filter (Inputs vs Outputs) -->
        <div class="flex items-center gap-1.5 p-1 rounded-xl bg-surface-hover border border-outline-border">
          <button
            v-for="opt in typeOptions"
            :key="opt.value"
            type="button"
            class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
            :class="activeType === opt.value
              ? 'bg-indigo-600 text-white shadow-xs'
              : 'text-ink-secondary hover:text-ink-primary'"
            @click="activeType = opt.value"
          >
            {{ opt.label }}
          </button>
        </div>

        <!-- Scope Filter (All, Campaign, Project) -->
        <div class="flex items-center gap-1.5 p-1 rounded-xl bg-surface-hover border border-outline-border">
          <button
            v-for="scope in ['All', 'Campaign', 'Project']"
            :key="scope"
            type="button"
            class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
            :class="activeScope === scope
              ? 'bg-surface-card text-ink-primary shadow-xs border border-outline-border'
              : 'text-ink-secondary hover:text-ink-primary'"
            @click="activeScope = scope"
          >
            {{ scope === 'All' ? 'All Scopes' : `${scope} Scope` }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-3">
        <span class="text-xs font-medium text-ink-muted">
          {{ filteredAssets.length }} {{ filteredAssets.length === 1 ? 'asset' : 'assets' }}
        </span>
        <FormControl
          v-model="search"
          type="text"
          placeholder="Search by name..."
          class="w-full sm:w-56"
        >
          <template #prefix>
            <span class="lucide-search size-4 text-ink-muted" />
          </template>
        </FormControl>
      </div>
    </div>

    <!-- Category Filter Chips (Frappe INPUT_ASSET_CATEGORIES) -->
    <div class="flex items-center gap-2 mb-6 overflow-x-auto pb-1">
      <button
        v-for="cat in categoryOptions"
        :key="cat.value"
        type="button"
        class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0"
        :class="activeCategory === cat.value
          ? 'bg-indigo-600 text-white shadow-xs'
          : 'bg-surface-card hover:bg-surface-hover text-ink-secondary hover:text-ink-primary border border-outline-border'"
        @click="activeCategory = cat.value"
      >
        {{ cat.label }}
      </button>
    </div>

    <div v-if="assetsResource.loading" class="empty-state">
      <div class="empty-state-icon">
        <span class="lucide-refresh-cw size-6 animate-spin" />
      </div>
      <h2>Loading assets...</h2>
      <p>Fetching media items from your workspace.</p>
    </div>

    <!-- Asset Cards Grid -->
    <div v-else-if="filteredAssets.length" class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      <article
        v-for="asset in filteredAssets"
        :key="asset.name"
        class="group p-3 rounded-xl bg-surface-card hover:bg-surface-hover border border-outline-border hover:border-indigo-500/60 shadow-xs hover:shadow-md transition-all flex flex-col justify-between cursor-pointer select-none"
        @click="openAssetModal(asset)"
      >
        <div class="relative rounded-lg overflow-hidden bg-black/10 aspect-video flex items-center justify-center mb-2.5 group-hover:opacity-95 transition-opacity">
          <!-- Category Pill -->
          <span
            class="absolute top-2 left-2 z-10 text-[10px] px-2 py-0.5 rounded font-bold uppercase tracking-wider backdrop-blur-md shadow-xs"
            :class="asset.is_output ? 'bg-purple-600/90 text-white' : 'bg-indigo-600/90 text-white'"
          >
            {{ asset.asset_category || (asset.is_output ? 'Output' : 'Reference') }}
          </span>

          <!-- Scope Pill -->
          <span
            class="absolute top-2 right-2 z-10 text-[10px] px-2 py-0.5 rounded font-medium backdrop-blur-md shadow-xs bg-black/50 text-white/95"
          >
            {{ asset.asset_scope }}
          </span>

          <!-- Play overlay icon for videos -->
          <div
            v-if="asset.media_type === 'Video' || isVideoUrl(asset.file) || asset.is_output"
            class="absolute inset-0 z-10 flex items-center justify-center bg-black/20 group-hover:bg-black/30 transition-colors pointer-events-none"
          >
            <div class="size-9 rounded-full bg-white/90 dark:bg-slate-900/90 flex items-center justify-center text-indigo-600 shadow-md group-hover:scale-110 transition-transform">
              <svg class="size-4 fill-current ml-0.5" viewBox="0 0 24 24">
                <polygon points="5 3 19 12 5 21 5 3"/>
              </svg>
            </div>
          </div>

          <!-- Video thumbnail if video -->
          <video
            v-if="asset.file && (asset.media_type === 'Video' || isVideoUrl(asset.file))"
            :src="asset.file"
            class="w-full h-full object-cover pointer-events-none"
            preload="metadata"
          />
          <!-- Image preview if image -->
          <img
            v-else-if="asset.file"
            :src="asset.file"
            :alt="asset.asset_name"
            class="w-full h-full object-cover"
          />
          <div v-else class="flex flex-col items-center justify-center text-ink-muted">
            <span class="lucide-image size-7 mb-1 opacity-70" />
            <span class="text-xs">{{ asset.media_type || "Media" }}</span>
          </div>
        </div>

        <div>
          <h3 class="text-xs font-semibold text-ink-primary truncate mb-1" :title="asset.asset_name">
            {{ asset.asset_name }}
          </h3>
          <div class="flex items-center justify-between pt-1 border-t border-outline-subtle text-[11px] text-ink-muted">
            <span class="capitalize">{{ asset.is_output ? 'Project Output' : 'Reference Input' }}</span>
            <span class="font-medium text-indigo-600 hover:text-indigo-700 dark:text-indigo-400 flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
              <span>View</span>
              <svg class="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="9 18 15 12 9 6"/>
              </svg>
            </span>
          </div>
        </div>
      </article>
    </div>

    <div v-else class="empty-state">
      <div class="empty-state-icon">
        <span class="lucide-image size-7" />
      </div>
      <h2>No assets match your filters</h2>
      <p>Try clearing your search query or switching between Reference Inputs and Project Outputs.</p>
      <Button variant="solid" @click="resetFilters">
        Reset Filters
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
                class="text-[10px] px-2 py-0.5 rounded font-bold uppercase tracking-wider"
                :class="selectedAsset.is_output ? 'bg-purple-600 text-white' : 'bg-indigo-600 text-white'"
              >
                {{ selectedAsset.asset_category || (selectedAsset.is_output ? 'Output' : 'Reference') }}
              </span>
              <span class="text-[10px] px-2 py-0.5 rounded font-medium bg-surface-hover border border-outline-border text-ink-secondary">
                {{ selectedAsset.asset_scope }} Scope
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
            v-if="selectedAsset.file && (selectedAsset.media_type === 'Video' || isVideoUrl(selectedAsset.file) || selectedAsset.is_output)"
            :src="selectedAsset.file"
            controls
            autoplay
            preload="metadata"
            class="max-h-[52vh] w-full rounded-xl bg-black object-contain shadow-lg"
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
            <p class="text-sm font-medium">Media file preview is not available.</p>
            <p class="text-xs mt-1 text-ink-muted">ID: {{ selectedAsset.name }}</p>
          </div>
        </div>

        <!-- Modal Footer & Metadata Details -->
        <div class="p-4 bg-surface-card border-t border-outline-border flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-3 text-xs text-ink-secondary">
            <span>Type: <strong>{{ selectedAsset.media_type || (selectedAsset.is_output ? 'Video' : 'Image') }}</strong></span>
            <span>·</span>
            <span>Modified: <strong>{{ formatDate(selectedAsset.modified) }}</strong></span>
          </div>

          <div class="flex items-center gap-2">
            <!-- Open in Campaign / Project button -->
            <Button
              v-if="selectedAsset.media_project"
              appearance="subtle"
              class="text-xs"
              @click="openProject(selectedAsset.media_project)"
            >
              Open Project Cockpit
            </Button>
            <Button
              v-else-if="selectedAsset.campaign"
              appearance="subtle"
              class="text-xs"
              @click="openCampaign(selectedAsset.campaign)"
            >
              Open Campaign
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
              <span>Download</span>
            </a>

            <Button appearance="subtle" @click="selectedAsset = null">Close</Button>
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
      <div class="w-full max-w-md bg-zinc-900 border border-zinc-800 rounded-2xl p-6 shadow-2xl text-xs space-y-4">
        <div class="flex items-center justify-between pb-3 border-b border-zinc-800">
          <div>
            <h3 class="text-sm font-bold text-white">{{ t('upload_modal_title') }}</h3>
            <p class="text-zinc-400 text-[11px] mt-0.5">{{ t('upload_modal_sub') }}</p>
          </div>
          <button type="button" class="text-zinc-400 hover:text-white" @click="showUploadModal = false">✕</button>
        </div>

        <div>
          <label class="block text-zinc-300 font-semibold mb-1">{{ t('upload_campaign_label') }}</label>
          <FormControl
            v-model="uploadTargetCampaign"
            type="select"
            :options="campaignOptions"
            placeholder="Select campaign..."
          />
        </div>

        <div>
          <label class="block text-zinc-300 font-semibold mb-1">{{ t('upload_category_label') }}</label>
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
          <label class="block text-zinc-300 font-semibold mb-1">{{ t('upload_file_label') }}</label>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            class="w-full text-xs text-zinc-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-zinc-800 file:text-zinc-200 hover:file:bg-zinc-700 cursor-pointer"
            @change="onFileChange"
          />
        </div>

        <div class="flex items-center justify-end gap-2 pt-3 border-t border-zinc-800">
          <Button appearance="subtle" @click="showUploadModal = false">{{ t('btn_cancel') }}</Button>
          <Button variant="solid" :loading="isUploading" @click="handleUploadAsset">{{ t('btn_upload') }}</Button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { Button, FormControl, call, createResource, toast, upload as uploadFile } from "frappe-ui";
import { useI18n } from "../stores/i18n";

const { t } = useI18n();
const route = useRoute();
const search = ref("");
const activeScope = ref("All");
const activeType = ref("All");
const activeCategory = ref(route.query?.category || "All");
const selectedAsset = ref(null);

const showUploadModal = ref(false);
const isUploading = ref(false);
const uploadTargetCampaign = ref("");
const uploadCategory = ref("Product");
const selectedFile = ref(null);

const typeOptions = computed(() => [
  { label: t('type_all'), value: "All" },
  { label: t('type_inputs'), value: "Inputs" },
  { label: t('type_outputs'), value: "Outputs" },
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
    scope: activeScope.value,
    asset_type: activeType.value,
  },
  auto: true,
});

const campaignsResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_cards",
  auto: true,
});

const campaignOptions = computed(() => {
  const list = campaignsResource.data || [];
  return list.map((c) => ({
    label: `${c.campaign_name || c.product_name} (${c.campaign || c.name})`,
    value: c.campaign || c.name,
  }));
});

watch(campaignOptions, (opts) => {
  if (opts.length && !uploadTargetCampaign.value) {
    uploadTargetCampaign.value = opts[0].value;
  }
}, { immediate: true });

watch([activeScope, activeType], () => {
  assetsResource.params = {
    scope: activeScope.value,
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
  activeScope.value = "All";
  activeType.value = "All";
  activeCategory.value = "All";
}

function onFileChange(e) {
  const file = e.target.files?.[0];
  selectedFile.value = file || null;
}

async function handleUploadAsset() {
  if (!selectedFile.value) {
    toast({ title: "Chưa chọn file", text: "Vui lòng chọn một file ảnh.", type: "error" });
    return;
  }
  if (!uploadTargetCampaign.value) {
    toast({ title: "Chưa chọn chiến dịch", text: "Vui lòng chọn một chiến dịch để đính kèm tư liệu.", type: "error" });
    return;
  }

  isUploading.value = true;
  try {
    const uploaded = await uploadFile(selectedFile.value, { private: true });
    if (!uploaded?.file_url) throw new Error("Không thể tải lên file.");

    await call("joymedia.joymedia.doctype.media_project.media_project.create_campaign_shared_asset", {
      campaign: uploadTargetCampaign.value,
      asset_name: selectedFile.value.name.replace(/\.[^/.]+$/, ""),
      asset_category: uploadCategory.value,
      file_url: uploaded.file_url,
    });

    toast({ title: "Đã tải lên tư liệu", text: `Đã thêm vào chiến dịch ${uploadTargetCampaign.value}.`, type: "success" });
    showUploadModal.value = false;
    selectedFile.value = null;
    await assetsResource.reload();
  } catch (err) {
    toast({ title: "Lỗi tải tư liệu", text: err.message || "Vui lòng thử lại.", type: "error" });
  } finally {
    isUploading.value = false;
  }
}

function openProject(projectName) {
  window.location.href = `/joymedia/projects/${encodeURIComponent(projectName)}`;
}

function openCampaign(campaignName) {
  window.location.href = `/joymedia/campaigns/${encodeURIComponent(campaignName)}`;
}

function openCampaigns() {
  window.location.href = "/joymedia/campaigns";
}
</script>

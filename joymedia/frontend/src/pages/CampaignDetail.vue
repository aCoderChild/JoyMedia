<template>
  <section class="page-section">
    <div class="mb-4">
      <Button appearance="subtle" @click="goBack">
        <template #prefix>
          <span class="lucide-arrow-left size-4" />
        </template>
        Back to Campaigns
      </Button>
    </div>

    <div class="page-heading">
      <div>
        <p class="eyebrow">Marketing Campaign</p>
        <h1>{{ campaignData?.campaign?.campaign_name || "Campaign Workspace" }}</h1>
        <p class="subtitle">{{ campaignData?.campaign?.product_name || "Commercial Video Campaign" }}</p>
      </div>

      <div class="flex items-center gap-3">
        <Button appearance="subtle" :loading="campaignResource.loading" @click="refresh" title="Refresh campaign data">
          <template #prefix>
            <span class="lucide-refresh-cw size-4" :class="{ 'animate-spin': campaignResource.loading }" />
          </template>
          Refresh
        </Button>
        <Button variant="solid" @click="showNewProjectModal = true">
          <template #prefix>
            <span class="lucide-plus size-4" />
          </template>
          New Video Project
        </Button>
      </div>
    </div>

    <div v-if="campaignResource.loading && !campaignData" class="empty-state">
      <div class="empty-state-icon">
        <span class="lucide-refresh-cw size-6 animate-spin" />
      </div>
      <h2>Loading campaign workspace...</h2>
      <p>Retrieving campaign deliverables, shared assets, and creative brief.</p>
    </div>

    <div v-else-if="campaignData" class="workspace-stack">
      <!-- 1. Creative Brief & Intent -->
      <section class="workspace-card">
        <div class="section-heading mb-4">
          <div>
            <p class="eyebrow">Marketing Strategy</p>
            <h2>Creative Brief</h2>
            <p class="text-xs text-ink-secondary mt-1">Core intent and product positioning inherited by all video projects.</p>
          </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <!-- Product Name -->
          <div class="p-4 rounded-xl bg-surface-hover border border-outline-border flex flex-col justify-between">
            <div>
              <div class="flex items-center gap-2 mb-2 text-xs font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
                <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="m7.5 4.27 9 5.15"/>
                  <path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>
                  <path d="m3.3 7 8.7 5 8.7-5"/>
                  <path d="M12 22V12"/>
                </svg>
                <span>Featured Product</span>
              </div>
              <p class="text-sm text-ink-primary font-semibold leading-relaxed">
                {{ campaignData.campaign.product_name || "Featured Offering" }}
              </p>
            </div>
            <span class="text-[11px] text-ink-muted mt-2">Core subject offering</span>
          </div>

          <!-- Target Audience -->
          <div class="p-4 rounded-xl bg-surface-hover border border-outline-border flex flex-col justify-between">
            <div>
              <div class="flex items-center gap-2 mb-2 text-xs font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
                <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
                  <circle cx="9" cy="7" r="4"/>
                  <path d="M22 21v-2a4 4 0 0 0-3-3.87"/>
                  <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                </svg>
                <span>Target Audience</span>
              </div>
              <p class="text-sm text-ink-primary font-medium leading-relaxed">
                {{ campaignData.campaign.target_audience || "No specific target audience defined." }}
              </p>
            </div>
            <span class="text-[11px] text-ink-muted mt-2">Ideal viewer & customer persona</span>
          </div>

          <!-- Campaign Brief -->
          <div class="p-4 rounded-xl bg-surface-hover border border-outline-border flex flex-col justify-between">
            <div>
              <div class="flex items-center gap-2 mb-2 text-xs font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
                <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                  <line x1="16" y1="13" x2="8" y2="13"/>
                  <line x1="16" y1="17" x2="8" y2="17"/>
                  <polyline points="10 9 9 9 8 9"/>
                </svg>
                <span>Campaign Brief</span>
              </div>
              <p class="text-sm text-ink-primary font-medium leading-relaxed line-clamp-3">
                {{ campaignData.campaign.campaign_brief || "No detailed campaign brief provided." }}
              </p>
            </div>
            <span class="text-[11px] text-ink-muted mt-2">Overarching narrative & goals</span>
          </div>
        </div>
      </section>

      <!-- 2. Video Deliverables (Projects) -->
      <section class="workspace-card">
        <div class="section-heading">
          <div>
            <p class="eyebrow">Video Deliverables</p>
            <h2>Campaign Projects</h2>
            <p class="text-xs text-ink-secondary mt-1">
              {{ campaignData.projects?.length || 0 }} video deliverables produced for this campaign
            </p>
          </div>

          <Button variant="solid" @click="showNewProjectModal = true">
            <template #prefix>
              <span class="lucide-plus size-4" />
            </template>
            New Video Project
          </Button>
        </div>

        <div v-if="campaignData.projects?.length" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <article
            v-for="project in campaignData.projects"
            :key="project.name"
            class="group p-5 rounded-2xl bg-surface-card hover:bg-surface-hover border border-outline-border hover:border-indigo-400/50 shadow-xs hover:shadow-md transition-all cursor-pointer flex flex-col justify-between"
            @click="openProject(project.name)"
          >
            <div>
              <div class="flex items-center justify-between mb-3">
                <span class="status-badge" :class="projectStatusClass(project.status)">
                  <span class="status-dot" />
                  <span>{{ project.status }}</span>
                </span>
                <span class="text-xs font-semibold px-2 py-0.5 rounded-md bg-surface-hover border border-outline-border text-ink-secondary">
                  {{ project.delivery_preset || "Landscape" }}
                </span>
              </div>

              <h3 class="text-base font-bold text-ink-primary group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors mb-1.5">
                {{ project.project_name }}
              </h3>

              <p class="text-xs text-ink-secondary line-clamp-2 mb-4 leading-relaxed">
                {{ project.video_idea || "No concept summary provided." }}
              </p>
            </div>

            <div>
              <div class="flex flex-wrap items-center gap-2 pt-3 border-t border-outline-subtle text-xs text-ink-muted">
                <span class="flex items-center gap-1 font-medium text-ink-secondary">
                  <span class="lucide-clapperboard size-3.5 text-indigo-500" />
                  <span>{{ project.shot_count || 0 }} shots</span>
                </span>
                <span>·</span>
                <span class="font-medium text-ink-secondary">{{ project.duration }}s</span>
                <span>·</span>
                <span class="truncate max-w-[120px]">{{ project.video_style_name }}</span>

                <span class="ml-auto font-semibold text-indigo-600 dark:text-indigo-400 flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
                  <span>Open Studio</span>
                  <span class="lucide-chevron-right size-3.5" />
                </span>
              </div>
            </div>
          </article>
        </div>

        <div v-else class="empty-panel">
          <span class="lucide-clapperboard size-8 text-ink-muted opacity-60" />
          <p>No video projects created yet for this campaign.</p>
          <span class="text-xs text-ink-muted">Add deliverables like a 30s Hero Commercial, 15s Instagram Reel, or 6s Bumper Ad.</span>
          <Button variant="solid" class="mt-2" @click="showNewProjectModal = true">
            <template #prefix>
              <span class="lucide-plus size-4" />
            </template>
            Create Video Project
          </Button>
        </div>
      </section>

      <!-- 3. Shared Visual Assets (Reference Inputs Only) -->
      <section class="workspace-card">
        <div class="section-heading">
          <div>
            <p class="eyebrow">Visual References</p>
            <h2>Shared Campaign Assets</h2>
            <p class="text-xs text-ink-secondary mt-1">
              {{ campaignData.shared_assets?.length || 0 }} reference inputs shared across all deliverables in this campaign
            </p>
          </div>

          <div class="flex flex-wrap items-center gap-2.5">
            <div class="flex items-center gap-1.5 text-xs text-ink-secondary">
              <span class="hidden sm:inline">Category:</span>
              <FormControl
                v-model="selectedUploadCategory"
                type="select"
                :options="categoryUploadOptions"
                class="w-32"
              />
            </div>

            <div class="asset-upload">
              <label class="upload-button" :class="{ disabled: uploadingImages }">
                <span class="lucide-upload-cloud size-4" />
                <span>{{ uploadingImages ? `Uploading ${uploadProgress}/${uploadTotal}...` : "Add Shared Asset" }}</span>
                <input
                  ref="fileInput"
                  class="file-input-hidden"
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  multiple
                  :disabled="uploadingImages"
                  @change="uploadSelectedImages"
                />
              </label>
            </div>
          </div>
        </div>

        <!-- Category Filter Tabs -->
        <div v-if="campaignData.shared_assets?.length" class="flex items-center gap-2 mb-4 overflow-x-auto pb-1">
          <button
            v-for="tab in assetCategoryTabs"
            :key="tab.value"
            type="button"
            class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0"
            :class="activeAssetCategory === tab.value
              ? 'bg-indigo-600 text-white shadow-xs'
              : 'bg-surface-hover text-ink-secondary hover:bg-surface-active hover:text-ink-primary border border-outline-border'"
            @click="activeAssetCategory = tab.value"
          >
            {{ tab.label }}
          </button>
        </div>

        <!-- Asset Grid -->
        <div v-if="filteredAssets?.length" class="asset-grid">
          <div v-for="asset in filteredAssets" :key="asset.name" class="asset-tile group">
            <span class="asset-category-pill" :class="categoryBadgeClass(asset.asset_category)">
              {{ asset.asset_category || 'Reference' }}
            </span>
            <img v-if="asset.file" :src="asset.file" :alt="asset.asset_name" />
            <div v-else class="asset-placeholder">
              <span class="lucide-image size-6 mb-1 opacity-70" />
              <span>Reference</span>
            </div>
            <span class="asset-name-label" :title="asset.asset_name">{{ asset.asset_name }}</span>
          </div>
        </div>
        <div v-else-if="campaignData.shared_assets?.length" class="empty-panel">
          <span class="lucide-image size-8 text-ink-muted opacity-60" />
          <p>No reference assets found in "{{ activeAssetCategory }}" category.</p>
          <button type="button" class="text-xs text-indigo-600 font-semibold" @click="activeAssetCategory = 'All'">
            View all reference assets
          </button>
        </div>
        <div v-else class="empty-panel">
          <span class="lucide-image size-8 text-ink-muted opacity-60" />
          <p>No shared reference assets uploaded yet.</p>
          <span class="text-xs text-ink-muted">Upload product photos, backgrounds, character references, or brand style guides.</span>
        </div>
        <p v-if="uploadError" class="action-message error-text">{{ uploadError }}</p>
      </section>
    </div>

    <!-- + New Project Modal -->
    <div
      v-if="showNewProjectModal"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs"
      @click.self="showNewProjectModal = false"
    >
      <div class="w-full max-w-lg bg-surface-card rounded-2xl border border-outline-border shadow-2xl p-6 overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-bold text-ink-primary">New Video Project</h2>
            <p class="text-xs text-ink-secondary mt-0.5">Create a video deliverable under this campaign.</p>
          </div>
          <button
            type="button"
            class="p-1 rounded-lg text-ink-muted hover:text-ink-primary hover:bg-surface-hover"
            @click="showNewProjectModal = false"
          >
            <span class="lucide-x size-5" />
          </button>
        </div>

        <div class="space-y-4">
          <FormControl
            v-model="newProjectForm.project_name"
            type="text"
            label="Project Name"
            placeholder="e.g. 30s Hero Commercial, 15s Instagram Story..."
            required
          />

          <FormControl
            v-model="newProjectForm.video_idea"
            type="textarea"
            label="Video Concept / Idea"
            placeholder="Describe what happens in this deliverable, key moments, hook, call to action..."
            rows="3"
          />

        </div>

        <div class="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-outline-border">
          <Button appearance="subtle" @click="showNewProjectModal = false">Cancel</Button>
          <Button
            variant="solid"
            :loading="creatingProject"
            :disabled="!newProjectForm.project_name.trim()"
            @click="submitNewProject"
          >
            Create Project
          </Button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { Button, FormControl, call, createResource, toast, upload as uploadFile } from "frappe-ui";
import { computed, reactive, ref } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const campaignName = computed(() => route.params.name);

const campaignResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_detail",
  params: { name: campaignName.value },
  auto: true,
});

const campaignData = computed(() => campaignResource.data);

// Shared asset upload & filter state
const activeAssetCategory = ref("All");
const selectedUploadCategory = ref("Product");
const categoryUploadOptions = [
  "Product",
  "Character",
  "Background",
  "Brand",
  "Style",
  "Reference",
];

const uploadingImages = ref(false);
const uploadProgress = ref(0);
const uploadTotal = ref(0);
const uploadError = ref("");
const fileInput = ref(null);

// New project modal state
const showNewProjectModal = ref(false);
const creatingProject = ref(false);
const newProjectForm = reactive({
  project_name: "",
  video_idea: "",
});

const assetCategoryTabs = computed(() => {
  const assets = campaignData.value?.shared_assets || [];
  const tabs = [{ label: `All (${assets.length})`, value: "All" }];
  const counts = {};
  for (const a of assets) {
    const cat = a.asset_category || "Reference";
    counts[cat] = (counts[cat] || 0) + 1;
  }
  for (const cat of Object.keys(counts).sort()) {
    tabs.push({ label: `${cat} (${counts[cat]})`, value: cat });
  }
  return tabs;
});

const filteredAssets = computed(() => {
  const assets = campaignData.value?.shared_assets || [];
  if (activeAssetCategory.value === "All") return assets;
  return assets.filter((a) => (a.asset_category || "Reference") === activeAssetCategory.value);
});

function categoryBadgeClass(category) {
  const cat = String(category || "reference").toLowerCase().replace(/\s+/g, "-");
  return `category-${cat}`;
}

function projectStatusClass(status) {
  return `cover-${String(status || "draft").toLowerCase().replaceAll(" ", "-")}`;
}

function openProject(projectName) {
  window.location.href = `/joymedia/projects/${encodeURIComponent(projectName)}`;
}

function goBack() {
  window.location.href = "/joymedia/campaigns";
}

async function refresh() {
  await campaignResource.reload();
}

function assetNameFromFile(fileName) {
  return fileName.replace(/\.[^/.]+$/, "");
}

async function uploadSelectedImages(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;

  const realCampaignName = campaignData.value?.campaign?.name;
  if (!realCampaignName) return;

  uploadingImages.value = true;
  uploadError.value = "";
  uploadProgress.value = 0;
  uploadTotal.value = files.length;
  try {
    for (const file of files) {
      const uploadedFile = await uploadFile(file, { private: true });
      if (!uploadedFile?.file_url) throw new Error(`Upload did not return a file URL for ${file.name}.`);
      await call("joymedia.joymedia.doctype.media_project.media_project.create_campaign_shared_asset", {
        campaign: realCampaignName,
        asset_name: assetNameFromFile(file.name),
        asset_category: selectedUploadCategory.value || "Product",
        file_url: uploadedFile.file_url,
      });
      uploadProgress.value += 1;
    }
    await refresh();
    toast({ title: "Assets attached", text: `${files.length} shared reference asset(s) saved.`, type: "success" });
  } catch (error) {
    uploadError.value = error?.messages?.join(" ") || error?.message || "The asset could not be uploaded.";
    toast({ title: "Unable to save asset", text: uploadError.value, type: "error" });
  } finally {
    uploadingImages.value = false;
  }
}

async function submitNewProject() {
  if (!newProjectForm.project_name.trim()) return;
  const realCampaignName = campaignData.value?.campaign?.name;
  if (!realCampaignName) return;

  creatingProject.value = true;
  try {
    const res = await call("joymedia.joymedia.doctype.media_project.media_project.create_campaign_project", {
      campaign: realCampaignName,
      project_name: newProjectForm.project_name.trim(),
      video_idea: newProjectForm.video_idea.trim(),
    });

    toast({ title: "Project created", text: `Created ${newProjectForm.project_name}.`, type: "success" });
    showNewProjectModal.value = false;
    // Navigate directly to the newly created project cockpit
    window.location.href = `/joymedia/projects/${encodeURIComponent(res.project)}`;
  } catch (error) {
    toast({ title: "Unable to create project", text: error.message || "Please check inputs and try again.", type: "error" });
  } finally {
    creatingProject.value = false;
  }
}
</script>

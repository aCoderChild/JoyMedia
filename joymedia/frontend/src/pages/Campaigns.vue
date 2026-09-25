<template>
  <section class="page-section">
    <div class="page-heading">
      <div>
        <p class="eyebrow">Production Studio</p>
        <h1>Your Campaigns</h1>
        <p class="subtitle">Create, generate, and review your product commercial videos.</p>
      </div>
      <Button variant="solid" @click="createCampaign">
        <template #prefix>
          <span class="lucide-plus size-4" />
        </template>
        Create Campaign
      </Button>
    </div>

    <div class="toolbar">
      <TabButtons v-model="activeStatus" :options="statusOptions" />
      <div class="flex items-center gap-3">
        <span class="text-xs font-medium text-ink-muted hidden sm:inline">
          {{ filteredCampaigns.length }} {{ filteredCampaigns.length === 1 ? 'campaign' : 'campaigns' }}
        </span>
        <FormControl
          v-model="search"
          type="text"
          placeholder="Search campaigns or products..."
          class="toolbar-search"
        >
          <template #prefix>
            <span class="lucide-search size-4 text-ink-muted" />
          </template>
        </FormControl>
      </div>
    </div>

    <div v-if="campaigns.loading" class="empty-state">
      <div class="empty-state-icon">
        <span class="lucide-refresh-cw size-6 animate-spin" />
      </div>
      <h2>Loading campaigns...</h2>
      <p>Fetching your video projects from the server.</p>
    </div>

    <div v-else-if="filteredCampaigns.length" class="card-grid">
      <article
        v-for="campaign in filteredCampaigns"
        :key="campaign.name"
        class="campaign-card group"
        @click="openCampaign(campaign.name)"
      >
        <div
          class="card-cover"
          :class="coverClass(campaign.status)"
          :style="campaign.cover_image ? {
            backgroundImage: `linear-gradient(to bottom, rgba(15, 23, 42, 0.4), rgba(15, 23, 42, 0.85)), url('${encodeURI(campaign.cover_image)}')`,
            backgroundSize: 'cover',
            backgroundPosition: 'center'
          } : undefined"
        >
          <div class="flex items-center justify-between w-full">
            <span class="status-badge">
              <span class="status-dot" />
              <span>{{ campaign.status || 'Active' }}</span>
            </span>
            <div class="flex items-center gap-1.5">
              <span v-if="campaign.asset_categories?.length" class="text-xs px-2 py-0.5 rounded-md bg-black/40 backdrop-blur-xs font-medium text-white/90">
                {{ campaign.asset_categories.slice(0, 2).join(' · ') }}
              </span>
            </div>
          </div>
          <h2 class="card-cover-title">{{ campaign.campaign_name || campaign.project_name }}</h2>
        </div>

        <div class="card-body">
          <div class="card-product">
            <span class="lucide-sparkles size-4 text-indigo-500 shrink-0" />
            <span class="truncate font-semibold">{{ campaign.product_name }}</span>
          </div>

          <div class="card-meta">
            <span class="meta-chip" title="Video projects">
              <span class="lucide-clapperboard size-3.5 text-indigo-500" />
              <span>{{ campaign.project_count || 0 }} {{ campaign.project_count === 1 ? 'project' : 'projects' }}</span>
            </span>

            <span class="meta-chip" title="Shared reference assets">
              <span class="lucide-image size-3.5 text-indigo-500" />
              <span>{{ campaign.asset_count || 0 }} shared {{ campaign.asset_count === 1 ? 'asset' : 'assets' }}</span>
            </span>

            <span class="meta-chip ml-auto text-indigo-600 dark:text-indigo-400 font-semibold group-hover:translate-x-0.5 transition-transform">
              <span>Open Campaign</span>
              <span class="lucide-chevron-right size-3.5" />
            </span>
          </div>
        </div>
      </article>
    </div>

    <div v-else class="empty-state">
      <div class="empty-state-icon">
        <span class="lucide-clapperboard size-7" />
      </div>
      <h2>No campaigns yet</h2>
      <p>Create your first campaign to plan storyboards and generate product videos with AI.</p>
      <Button variant="solid" @click="createCampaign">
        <template #prefix>
          <span class="lucide-plus size-4" />
        </template>
        Create Campaign
      </Button>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from "vue";
import { Button, FormControl, TabButtons, createResource } from "frappe-ui";

const search = ref("");
const activeStatus = ref("All");
const statusOptions = ["All", "Draft", "Generating", "Review", "Completed"];
const campaigns = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_cards",
  auto: true,
});

const filteredCampaigns = computed(() => {
  const records = campaigns.data || [];
  const query = search.value.trim().toLowerCase();
  return records.filter((campaign) => {
    const statusMatches = activeStatus.value === "All" || campaign.status === activeStatus.value;
    const searchMatches = !query || `${campaign.campaign_name || campaign.project_name} ${campaign.product_name}`.toLowerCase().includes(query);
    return statusMatches && searchMatches;
  });
});

function openCampaign(name) {
  window.location.href = `/joymedia/campaigns/${encodeURIComponent(name)}`;
}

function createCampaign() {
  window.location.href = "/joymedia/campaigns/new";
}

function coverClass(status) {
  return `cover-${String(status || "draft").toLowerCase().replaceAll(" ", "-")}`;
}
</script>

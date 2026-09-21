<template>
  <section class="page-section">
    <div class="page-heading">
      <div>
        <p class="eyebrow">JoyMedia</p>
        <h1>Your Campaigns</h1>
        <p class="subtitle">Create, generate, and review your product videos.</p>
      </div>
      <Button label="Create Campaign" @click="createCampaign" />
    </div>

    <div class="toolbar">
      <TabButtons v-model="activeStatus" :options="statusOptions" />
      <FormControl v-model="search" type="text" placeholder="Search campaigns" />
    </div>

    <div v-if="campaigns.loading" class="empty-state">Loading campaigns...</div>
    <div v-else-if="filteredCampaigns.length" class="card-grid">
      <article
        v-for="campaign in filteredCampaigns"
        :key="campaign.name"
        class="campaign-card"
        @click="openCampaign(campaign.name)"
      >
        <div class="card-cover" :class="coverClass(campaign.status)">
          <span class="status-label">{{ campaign.status }}</span>
          <h2>{{ campaign.project_name }}</h2>
        </div>
        <div class="card-body">
          <p class="card-product">{{ campaign.product_name }}</p>
          <div class="card-meta">
            <span>{{ campaign.shots || 0 }} scenes</span>
            <span>{{ campaign.duration || "—" }} sec</span>
            <span>{{ campaign.delivery_preset || "Video" }}</span>
          </div>
        </div>
      </article>
    </div>
    <div v-else class="empty-state">
      <h2>No campaigns yet</h2>
      <p>Create a campaign to start your next product video.</p>
      <Button label="Create Campaign" @click="createCampaign" />
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
    const searchMatches = !query || `${campaign.project_name} ${campaign.product_name}`.toLowerCase().includes(query);
    return statusMatches && searchMatches;
  });
});

function openCampaign(name) {
  window.location.href = `/joymedia/campaigns/${encodeURIComponent(name)}`;
}

function createCampaign() {
  window.location.href = "/app/media-project/new-media-project";
}

function coverClass(status) {
  return `cover-${String(status || "draft").toLowerCase().replaceAll(" ", "-")}`;
}
</script>

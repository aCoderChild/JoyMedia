<template>
  <section class="page-section">
    <div class="page-heading"><div><p class="eyebrow">Library</p><h1>Assets</h1><p class="subtitle">Product images and generated media for your campaigns.</p></div><Button label="View campaigns" @click="openCampaigns" /></div>
    <div v-if="assets.loading" class="empty-state">Loading assets...</div>
    <div v-else-if="assets.data?.length" class="simple-grid">
      <article v-for="asset in assets.data" :key="asset.name" class="simple-card">
        <div class="asset-placeholder">{{ asset.media_type }}</div>
        <div><h2>{{ asset.asset_name }}</h2><p>{{ asset.asset_category }} · {{ asset.status }}</p></div>
      </article>
    </div>
    <div v-else class="empty-state"><h2>Your media library</h2><p>Open a campaign to upload product images.</p><Button label="View campaigns" @click="openCampaigns" /></div>
  </section>
</template>
<script setup>
import { Button, createResource } from "frappe-ui";
const assets = createResource({
  url: "frappe.client.get_list",
  params: { doctype: "Media Asset", fields: ["name", "asset_name", "media_type", "asset_category", "status"], order_by: "modified desc", limit_page_length: 48 },
  auto: true,
});
function openCampaigns() { window.location.href = "/joymedia/campaigns"; }
</script>

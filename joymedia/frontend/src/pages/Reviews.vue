<template>
  <section class="page-section">
    <div class="page-heading"><div><p class="eyebrow">Production</p><h1>Review Videos</h1><p class="subtitle">Review generated clips before approving them.</p></div><Button label="View campaigns" @click="openCampaigns" /></div>
    <div v-if="reviews.loading" class="empty-state">Loading reviews...</div>
    <div v-else-if="reviews.data?.length" class="simple-grid">
      <article v-for="review in reviews.data" :key="review.name" class="simple-card">
        <div class="review-placeholder">{{ review.status }}</div>
        <div><h2>{{ review.name }}</h2><p>{{ review.asset_version || "Generated video" }}</p></div>
      </article>
    </div>
    <div v-else class="empty-state"><h2>No videos waiting for review</h2><p>Generated clips will appear here when they are ready.</p><Button label="View campaigns" @click="openCampaigns" /></div>
  </section>
</template>
<script setup>
import { Button, createResource } from "frappe-ui";
const reviews = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_pending_review_cards",
  auto: true,
});
function openCampaigns() { window.location.href = "/joymedia/campaigns"; }
</script>

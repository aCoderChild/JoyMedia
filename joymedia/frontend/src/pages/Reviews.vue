<template>
  <section class="page-section">
    <div class="page-heading"><div><p class="eyebrow">Production</p><h1>Review Videos</h1><p class="subtitle">Review generated clips before approving them.</p></div><Button label="Open Reviews" @click="openDesk" /></div>
    <div v-if="reviews.loading" class="empty-state">Loading reviews...</div>
    <div v-else-if="reviews.data?.length" class="simple-grid">
      <article v-for="review in reviews.data" :key="review.name" class="simple-card">
        <div class="review-placeholder">{{ review.status }}</div>
        <div><h2>{{ review.name }}</h2><p>{{ review.asset_version || "Generated video" }}</p></div>
      </article>
    </div>
    <div v-else class="empty-state"><h2>No videos waiting for review</h2><p>Generated clips will appear here when they are ready.</p><Button label="Open Reviews" @click="openDesk" /></div>
  </section>
</template>
<script setup>
import { Button, createResource } from "frappe-ui";
const reviews = createResource({
  url: "frappe.client.get_list",
  params: { doctype: "Quality Review", fields: ["name", "status", "asset_version"], filters: { status: "Pending" }, order_by: "modified desc", limit_page_length: 48 },
  auto: true,
});
function openDesk() { window.location.href = "/app/quality-review"; }
</script>

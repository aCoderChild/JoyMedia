<template>
  <section class="page-section">
    <Button appearance="minimal" label="← Back to campaigns" @click="goBack" />
    <div v-if="campaign.loading" class="empty-state">Loading campaign...</div>
    <div v-else-if="campaign.data" class="detail-card">
      <div class="detail-cover cover-generating">
        <span class="status-label">{{ campaign.data.status }}</span>
        <h1>{{ campaign.data.project_name }}</h1>
      </div>
      <div class="detail-body">
        <div>
          <p class="eyebrow">Product</p>
          <h2>{{ campaign.data.product_name }}</h2>
        </div>
        <div>
          <p class="eyebrow">Target audience</p>
          <p>{{ campaign.data.target_audience || "Not provided" }}</p>
        </div>
        <div>
          <p class="eyebrow">Video idea</p>
          <p>{{ campaign.data.video_idea || "Not provided" }}</p>
        </div>
      </div>
    </div>
    <div v-else class="empty-state">Campaign not found.</div>
  </section>
</template>

<script setup>
import { Button, createResource } from "frappe-ui";
import { useRoute } from "vue-router";

const route = useRoute();
const campaign = createResource({
  url: "frappe.client.get",
  params: { doctype: "Media Project", name: route.params.name },
  auto: true,
});

function goBack() {
  window.location.href = "/joymedia/campaigns";
}
</script>

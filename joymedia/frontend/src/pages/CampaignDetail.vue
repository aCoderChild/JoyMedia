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
      <div class="detail-section">
        <div class="section-heading"><div><p class="eyebrow">Assets</p><h2>Product images</h2></div><FileUploader file-types="image/*" @success="uploadAsset"><template #default="{ openFileSelector, uploading }"><Button :label="uploading ? 'Uploading...' : 'Upload image'" :loading="uploading" @click="openFileSelector" /></template></FileUploader></div>
        <FormControl v-model="assetName" label="Asset name" placeholder="Product image" />
        <div v-if="campaign.data.assets?.length" class="asset-grid"><div v-for="asset in campaign.data.assets" :key="asset.name" class="asset-tile"><img v-if="asset.file" :src="asset.file" :alt="asset.asset_name" /><div v-else class="asset-placeholder">Image</div><span>{{ asset.asset_name }}</span></div></div>
        <p v-else class="muted">No product images uploaded yet.</p>
      </div>
    </div>
    <div v-else class="empty-state">Campaign not found.</div>
  </section>
</template>

<script setup>
import { Button, FileUploader, FormControl, call, createResource, toast } from "frappe-ui";
import { useRoute } from "vue-router";
import { ref } from "vue";

const route = useRoute();
const campaign = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_detail",
  params: { name: route.params.name },
  auto: true,
});
const assetName = ref("");

async function uploadAsset(file) {
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.create_campaign_asset", {
      media_project: route.params.name,
      asset_name: assetName.value.trim() || file.file_name || file.name,
      asset_category: "Product",
      file_url: file.file_url,
    });
    assetName.value = "";
    await campaign.reload();
  } catch (error) {
    toast({ title: "Unable to save image", text: error.message || "Please try again.", type: "error" });
  }
}

function goBack() {
  window.location.href = "/joymedia/campaigns";
}
</script>

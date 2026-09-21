<template>
  <section class="page-section narrow-page">
    <Button appearance="minimal" label="← Campaigns" @click="goBack" />
    <div class="form-card">
      <p class="eyebrow">New campaign</p>
      <h1>Create Campaign</h1>
      <p class="subtitle">Start a product video campaign.</p>

      <div class="form-stack">
        <FormControl v-model="form.project_name" label="Campaign Name" required placeholder="Summer launch" />
        <div class="field-row">
          <FormControl v-model="form.client_organization" type="select" label="Business" required :options="businessOptions" />
          <Button appearance="minimal" label="New business" @click="showBusinessForm = true" />
        </div>
        <FormControl v-model="form.product_name" label="Product" required placeholder="Cold brew bottle" />
        <FormControl v-model="form.target_audience" type="textarea" label="Target Audience" required placeholder="Young professionals aged 20–35" />
        <FormControl v-model="form.video_idea" type="textarea" label="Video Idea" placeholder="Describe the video you want to create" />
      </div>

      <div v-if="showBusinessForm" class="nested-form">
        <FormControl v-model="business.name" label="Business name" required />
        <FormControl v-model="business.industry" label="Industry" />
        <div class="button-row">
          <Button appearance="minimal" label="Cancel" @click="showBusinessForm = false" />
          <Button label="Create business" :loading="creatingBusiness" @click="createBusiness" />
        </div>
      </div>

      <div class="button-row form-actions">
        <Button appearance="minimal" label="Cancel" @click="goBack" />
        <Button label="Create Campaign" :loading="creatingCampaign" @click="createCampaign" />
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import { Button, FormControl, call, createResource, toast } from "frappe-ui";

const form = reactive({ project_name: "", client_organization: "", product_name: "", target_audience: "", video_idea: "" });
const business = reactive({ name: "", industry: "" });
const showBusinessForm = ref(false);
const creatingBusiness = ref(false);
const creatingCampaign = ref(false);
const businesses = createResource({ url: "joymedia.joymedia.doctype.media_project.media_project.get_businesses", auto: true });
const businessOptions = computed(() => (businesses.data || []).map((item) => ({ label: item.organization_name, value: item.name })));

async function createBusiness() {
  creatingBusiness.value = true;
  try {
    const created = await call("joymedia.joymedia.doctype.media_project.media_project.create_business", { organization_name: business.name, industry: business.industry });
    form.client_organization = created.name;
    business.name = "";
    business.industry = "";
    showBusinessForm.value = false;
    await businesses.reload();
  } finally { creatingBusiness.value = false; }
}

async function createCampaign() {
  creatingCampaign.value = true;
  try {
    const campaign = await call("joymedia.joymedia.doctype.media_project.media_project.create_campaign", form);
    window.location.href = `/joymedia/campaigns/${encodeURIComponent(campaign.name)}`;
  } catch (error) {
    toast({ title: "Unable to create campaign", text: error.message || "Please check the form.", type: "error" });
  } finally { creatingCampaign.value = false; }
}

function goBack() { window.location.href = "/joymedia/campaigns"; }
</script>

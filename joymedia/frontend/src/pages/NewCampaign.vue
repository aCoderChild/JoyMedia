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
          <FormControl v-if="hasBusinesses" v-model="form.client_organization" type="select" label="Business" required :options="businessOptions" />
          <div v-else class="empty-field">
            <label>Business <span>*</span></label>
            <p>No business has been created yet.</p>
          </div>
          <Button appearance="minimal" :label="hasBusinesses ? 'New business' : 'Create business'" @click="showBusinessForm = true" />
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
const hasBusinesses = computed(() => businessOptions.value.length > 0);

async function createBusiness() {
  if (!business.name.trim()) {
    toast({ title: "Business name is required", type: "error" });
    return;
  }

  creatingBusiness.value = true;
  try {
    const created = await call("joymedia.joymedia.doctype.media_project.media_project.create_business", { organization_name: business.name, industry: business.industry });
    form.client_organization = created.name;
    business.name = "";
    business.industry = "";
    showBusinessForm.value = false;
    await businesses.reload();
  } catch (error) {
    toast({ title: "Unable to create business", text: error.message || "Please try again.", type: "error" });
  } finally { creatingBusiness.value = false; }
}

async function createCampaign() {
  if (!form.project_name.trim() || !form.client_organization || !form.product_name.trim() || !form.target_audience.trim()) {
    toast({ title: "Complete the required fields", text: "Campaign name, Business, Product, and Target Audience are required.", type: "error" });
    if (!hasBusinesses.value) showBusinessForm.value = true;
    return;
  }

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

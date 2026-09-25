<template>
  <section class="page-section narrow-page">
    <div class="mb-4">
      <Button appearance="subtle" @click="goBack">
        <template #prefix>
          <span class="lucide-arrow-left size-4" />
        </template>
        Back to Campaigns
      </Button>
    </div>

    <div class="form-card">
      <p class="eyebrow">New Campaign</p>
      <h1>Create Campaign</h1>
      <p class="subtitle">Set up the shared commercial context and your first video project.</p>

      <div class="form-stack">
        <FormControl
          v-model="form.campaign_name"
          label="Campaign Name"
          required
          placeholder="e.g. Summer Refresh Launch"
        />

        <FormControl
          v-model="form.project_name"
          label="First Video Project"
          required
          placeholder="e.g. 30s Hero Commercial"
        />

        <div class="field-row">
          <FormControl
            v-if="hasBusinesses"
            v-model="form.client_organization"
            type="select"
            label="Business Organization"
            required
            :options="businessOptions"
          />
          <div v-else class="empty-field">
            <label>Business Organization <span>*</span></label>
            <p>No business has been created yet.</p>
          </div>
          <Button
            appearance="subtle"
            @click="showBusinessForm = !showBusinessForm"
          >
            <template #prefix>
              <span class="lucide-plus size-3.5" />
            </template>
            {{ hasBusinesses ? 'New business' : 'Create business' }}
          </Button>
        </div>

        <div v-if="showBusinessForm" class="nested-form">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm font-semibold text-ink-primary">Add New Business</span>
            <button type="button" class="text-ink-muted hover:text-ink-primary" @click="showBusinessForm = false">
              <span class="lucide-x size-4" />
            </button>
          </div>
          <FormControl v-model="business.name" label="Business name" required placeholder="e.g. Acme Coffee Co." />
          <FormControl v-model="business.industry" label="Industry" placeholder="e.g. Food & Beverage, Retail, Tech" />
          <div class="button-row">
            <Button appearance="subtle" label="Cancel" @click="showBusinessForm = false" />
            <Button variant="solid" label="Save Business" :loading="creatingBusiness" @click="createBusiness" />
          </div>
        </div>

        <FormControl
          v-model="form.product_name"
          label="Product Name"
          required
          placeholder="e.g. Cold Brew Bottle 500ml"
        />

        <FormControl
          v-model="form.target_audience"
          type="textarea"
          label="Target Audience"
          required
          placeholder="e.g. Young professionals and students aged 20–35 seeking premium artisanal refreshment."
        />

        <FormControl
          v-model="form.video_idea"
          type="textarea"
          label="Video Idea & Creative Direction"
          placeholder="e.g. Fast-paced, dynamic cuts highlighting morning energy, icy splashes, and sleek packaging design."
        />
      </div>

      <div class="button-row form-actions">
        <Button appearance="subtle" label="Cancel" @click="goBack" />
        <Button variant="solid" :loading="creatingCampaign" @click="createCampaign">
          <template #prefix>
            <span class="lucide-sparkles size-4" />
          </template>
          Create Campaign
        </Button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { Button, FormControl, call, createResource, toast } from "frappe-ui";

const route = useRoute();

const form = reactive({
  campaign_name: "",
  project_name: "",
  client_organization: "",
  product_name: "",
  target_audience: "",
  video_idea: "",
});

onMounted(() => {
  const q = route.query;
  if (q.preset) {
    if (q.preset === "Reel") {
      form.campaign_name = "TikTok & Reels Launch";
      form.project_name = "15s Vertical Commercial";
      form.video_idea = "Dynamic fast-paced cuts highlighting product hook, viral music sync, and call to action.";
    } else if (q.preset === "Hero") {
      form.campaign_name = "Brand Hero Commercial";
      form.project_name = "30s Cinematic Commercial";
      form.video_idea = "Widescreen cinematic narrative highlighting craftsmanship, premium texture, and brand quality.";
    } else if (q.preset === "Teaser") {
      form.campaign_name = "Product Drop Teaser";
      form.project_name = "10s Square Teaser";
      form.video_idea = "High-energy product reveal with icy water splash and bold typography.";
    }
  }
});

const business = reactive({ name: "", industry: "" });
const showBusinessForm = ref(false);
const creatingBusiness = ref(false);
const creatingCampaign = ref(false);
const businesses = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_businesses",
  auto: true,
});
const businessOptions = computed(() => (businesses.data || []).map((item) => ({ label: item.organization_name, value: item.name })));
const hasBusinesses = computed(() => businessOptions.value.length > 0);

watch(businessOptions, (opts) => {
  if (opts?.length && !form.client_organization) {
    form.client_organization = opts[0].value;
  }
}, { immediate: true });

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
  if (!form.campaign_name.trim() || !form.project_name.trim() || !form.client_organization || !form.product_name.trim() || !form.target_audience.trim()) {
    toast({ title: "Complete the required fields", text: "Campaign name, project name, Business, Product, and Target Audience are required.", type: "error" });
    if (!hasBusinesses.value) showBusinessForm.value = true;
    return;
  }

  creatingCampaign.value = true;
  try {
    const campaign = await call("joymedia.joymedia.doctype.media_project.media_project.create_campaign", { ...form, project_name: form.project_name, campaign_name: form.campaign_name });
    window.location.href = `/joymedia/campaigns/${encodeURIComponent(campaign.name)}`;
  } catch (error) {
    toast({ title: "Unable to create campaign", text: error.message || "Please check the form.", type: "error" });
  } finally { creatingCampaign.value = false; }
}

function goBack() { window.location.href = "/joymedia/campaigns"; }
</script>

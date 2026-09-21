<template>
  <section class="page-section">
    <div class="page-heading">
      <div>
        <Button appearance="minimal" label="← Campaigns" @click="goBack" />
        <p class="eyebrow">Campaign</p>
        <h1>{{ workspace?.campaign?.project_name || "Campaign" }}</h1>
        <p class="subtitle">{{ workspace?.campaign?.product_name }}</p>
      </div>
      <span v-if="workspace?.campaign" class="status-label">{{ workspace.campaign.status }}</span>
    </div>

    <div v-if="campaign.loading" class="empty-state">Loading campaign...</div>
    <div v-else-if="workspace" class="workspace-stack">
      <section class="workspace-card campaign-summary">
        <div><p class="eyebrow">Target audience</p><p>{{ workspace.campaign.target_audience || "Not provided" }}</p></div>
        <div><p class="eyebrow">Video idea</p><p>{{ workspace.campaign.video_idea || "Not provided" }}</p></div>
      </section>

      <section class="workspace-card">
        <div class="section-heading"><div><p class="eyebrow">Assets</p><h2>Product images</h2></div><FileUploader file-types="image/*" @success="uploadAsset"><template #default="{ openFileSelector, uploading }"><Button :label="uploading ? 'Uploading...' : 'Upload image'" :loading="uploading" @click="openFileSelector" /></template></FileUploader></div>
        <FormControl v-model="assetName" label="Asset name" placeholder="Product image" />
        <div v-if="workspace.assets?.length" class="asset-grid"><div v-for="asset in workspace.assets" :key="asset.name" class="asset-tile"><img v-if="asset.file" :src="asset.file" :alt="asset.asset_name" /><div v-else class="asset-placeholder">Image</div><span>{{ asset.asset_name }}</span></div></div>
        <p v-else class="muted">No product images uploaded yet.</p>
      </section>

      <section class="workspace-card">
        <div class="section-heading"><div><p class="eyebrow">Video settings</p><h2>{{ settings ? `${settings.duration} sec · ${settings.delivery_preset}` : "Set up your video" }}</h2></div><Button :label="settings ? 'Edit' : 'Set video settings'" @click="showSettings = true" /></div>
        <div v-if="showSettings || !settings" class="inline-form"><FormControl v-model="settingsForm.duration" type="number" label="Duration (seconds)" /><FormControl v-model="settingsForm.format" type="select" label="Format" :options="['Landscape', 'Portrait', 'Square']" /><Button label="Save settings" :loading="savingSettings" @click="saveSettings" /></div>
      </section>

      <section class="workspace-card">
        <div class="section-heading"><div><p class="eyebrow">Storyboard</p><h2>{{ storyboardTitle }}</h2></div><div class="button-row"><FormControl v-model="sceneCount" type="number" label="Scenes" /><Button label="Generate storyboard" :loading="generatingPlan" :disabled="!settings" @click="generatePlan" /></div></div>
        <div v-if="plan?.shots?.length" class="storyboard-grid"><article v-for="shot in plan.shots" :key="shot.shot_number" class="storyboard-card"><div class="storyboard-number">Shot {{ shot.shot_number }}</div><p><strong>Camera</strong>{{ shot.camera }}</p><p><strong>Subject</strong>{{ shot.subject }}</p><p><strong>Motion</strong>{{ shot.motion }}</p><p><strong>Lighting</strong>{{ shot.lighting }}</p><p><strong>Audio</strong>{{ shot.audio }}</p></article></div>
        <div v-else-if="workspace.storyboard?.length" class="storyboard-grid"><article v-for="shot in workspace.storyboard" :key="shot.name" class="storyboard-card"><div class="storyboard-number">Shot {{ shot.shot_number }}</div><p><strong>Camera</strong>{{ shot.camera_direction }}</p><p><strong>Subject</strong>{{ shot.subject_identity }}</p><p><strong>Motion</strong>{{ shot.action_plot }}</p><p><strong>Lighting</strong>{{ shot.environment }}</p><p><strong>Audio</strong>{{ shot.audio_direction }}</p></article></div>
        <div v-else class="empty-panel"><p>No storyboard has been generated yet.</p><Button label="Generate storyboard" :disabled="!settings" @click="generatePlan" /></div>
        <div v-if="plan?.shots?.length" class="button-row"><Button appearance="minimal" label="Discard plan" @click="plan = null" /><Button label="Apply storyboard" :loading="applyingPlan" @click="applyPlan" /></div>
      </section>

      <section class="workspace-card">
        <div class="section-heading"><div><p class="eyebrow">Production</p><h2>{{ production?.status || "Ready to generate" }}</h2></div><Button label="Generate video" :loading="generatingVideo" :disabled="!workspace.storyboard?.length || !settings || Boolean(production && production.status !== 'Draft')" @click="generateVideo" /></div>
        <div v-if="production" class="progress-panel"><div class="progress-label"><span>{{ production.completed_jobs || 0 }} / {{ production.total_jobs || 0 }} scenes complete</span><span>{{ production.progress || 0 }}%</span></div><div class="progress-track"><div class="progress-value" :style="{ width: `${production.progress || 0}%` }" /></div><p v-if="production.error_summary" class="error-text">{{ production.error_summary }}</p></div>
      </section>

      <section class="workspace-card">
        <div class="section-heading"><div><p class="eyebrow">Review</p><h2>Generated clips</h2></div></div>
        <div v-if="workspace.reviews?.length" class="review-grid"><article v-for="review in workspace.reviews" :key="review.name" class="review-card"><video v-if="review.preview_url" :src="review.preview_url" controls preload="metadata" /><div class="review-actions"><span>{{ review.name }} · {{ review.status }}</span><Button v-if="review.status === 'Pending'" label="Approve" @click="reviewAction('approve', review)" /><Button v-if="review.status === 'Pending'" appearance="minimal" label="Reject" @click="reviewAction('reject', review)" /><Button v-if="review.status === 'Rejected'" label="Regenerate" @click="reviewAction('regenerate', review)" /></div></article></div>
        <div v-else class="empty-panel">No clips are waiting for review.</div>
      </section>

      <section v-if="workspace.final_video?.file" class="workspace-card"><p class="eyebrow">Final video</p><h2>Approved campaign video</h2><video class="final-video" :src="workspace.final_video.file" controls /></section>
    </div>
    <div v-else class="empty-state">Campaign not found.</div>
  </section>
</template>

<script setup>
import { Button, FileUploader, FormControl, call, createResource, toast } from "frappe-ui";
import { computed, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const campaign = createResource({ url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_workspace", params: { name: route.params.name }, auto: true });
const assetName = ref("");
const sceneCount = ref(3);
const plan = ref(null);
const showSettings = ref(false);
const savingSettings = ref(false);
const generatingPlan = ref(false);
const applyingPlan = ref(false);
const generatingVideo = ref(false);
const settingsForm = reactive({ duration: 8, format: "Landscape" });
const workspace = computed(() => campaign.data);
const settings = computed(() => workspace.value?.video_settings);
const production = computed(() => workspace.value?.production);
const storyboardTitle = computed(() => workspace.value?.storyboard?.length ? `${workspace.value.storyboard.length} scenes` : "Plan your scenes");
watch(settings, (value) => {
  if (!value) return;
  settingsForm.duration = value.duration;
  settingsForm.format = value.delivery_preset;
}, { immediate: true });

async function refresh() { plan.value = null; await campaign.reload(); }
async function uploadAsset(file) {
  try { await call("joymedia.joymedia.doctype.media_project.media_project.create_campaign_asset", { media_project: route.params.name, asset_name: assetName.value.trim() || file.file_name || file.name, asset_category: "Product", file_url: file.file_url }); assetName.value = ""; await refresh(); }
  catch (error) { toast({ title: "Unable to save image", text: error.message || "Please try again.", type: "error" }); }
}
async function saveSettings() {
  savingSettings.value = true;
  try { await call("joymedia.joymedia.doctype.media_project.media_project.save_campaign_video_settings", { campaign_name: route.params.name, total_duration_seconds: settingsForm.duration, delivery_preset: settingsForm.format }); showSettings.value = false; await refresh(); }
  catch (error) { toast({ title: "Unable to save settings", text: error.message || "Please try again.", type: "error" }); }
  finally { savingSettings.value = false; }
}
async function generatePlan() {
  generatingPlan.value = true;
  try { plan.value = await call("joymedia.joymedia.doctype.media_project.media_project.generate_campaign_video_plan", { campaign_name: route.params.name, scene_count: sceneCount.value }); }
  catch (error) { toast({ title: "Unable to generate storyboard", text: error.message || "Please try again.", type: "error" }); }
  finally { generatingPlan.value = false; }
}
async function applyPlan() {
  applyingPlan.value = true;
  try { await call("joymedia.joymedia.doctype.media_project.media_project.apply_campaign_video_plan", { campaign_name: route.params.name, plan_json: JSON.stringify(plan.value) }); await refresh(); }
  catch (error) { toast({ title: "Unable to apply storyboard", text: error.message || "Please try again.", type: "error" }); }
  finally { applyingPlan.value = false; }
}
async function generateVideo() {
  generatingVideo.value = true;
  try { await call("joymedia.joymedia.doctype.media_project.media_project.generate_campaign_video", { campaign_name: route.params.name }); await refresh(); }
  catch (error) { toast({ title: "Unable to generate video", text: error.message || "Please try again.", type: "error" }); }
  finally { generatingVideo.value = false; }
}
async function reviewAction(action, review) {
  const method = action === "approve" ? "approve_campaign_review" : action === "regenerate" ? "regenerate_campaign_review" : "reject_campaign_review";
  try { await call(`joymedia.joymedia.doctype.media_project.media_project.${method}`, { campaign_name: route.params.name, review_name: review.name }); await refresh(); }
  catch (error) { toast({ title: "Unable to update review", text: error.message || "Please try again.", type: "error" }); }
}
function goBack() { window.location.href = "/joymedia/campaigns"; }
</script>

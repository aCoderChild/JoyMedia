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
        <div class="section-heading"><div><p class="eyebrow">Assets</p><h2>Product images</h2></div><div class="asset-upload"><input ref="fileInput" class="file-input-hidden" type="file" accept="image/*" multiple @change="uploadSelectedImages" /><Button :label="uploadingImages ? `Uploading ${uploadProgress} / ${uploadTotal}` : 'Add images'" :loading="uploadingImages" :disabled="uploadingImages" @click="openImagePicker" /></div></div>
        <div v-if="workspace.assets?.length" class="asset-grid"><div v-for="asset in workspace.assets" :key="asset.name" class="asset-tile"><img v-if="asset.file" :src="asset.file" :alt="asset.asset_name" /><div v-else class="asset-placeholder">Image</div><span>{{ asset.asset_name }}</span></div></div>
        <p v-else class="muted">No product images uploaded yet.</p>
      </section>

      <section class="workspace-card">
        <div class="section-heading"><div><p class="eyebrow">Video settings</p><h2>{{ settings ? `${settings.duration} sec · ${settings.delivery_preset}` : "Set up your video" }}</h2><p v-if="settings?.video_style_name" class="muted">{{ settings.video_style_name }}</p></div><Button :label="settings ? 'Edit' : 'Set video settings'" @click="showSettings = true" /></div>
        <div v-if="showSettings || !settings" class="settings-form">
          <div class="inline-form"><FormControl v-model="settingsForm.duration" type="number" label="Duration (seconds)" /><FormControl v-model="settingsForm.format" type="select" label="Format" :options="['Landscape', 'Portrait', 'Square']" /></div>
          <div class="style-picker"><div><p class="eyebrow">Video style</p><p class="muted">Choose the creative direction. JoyMedia selects the matching generation workflow automatically.</p></div><div v-if="videoStyles.loading" class="muted">Loading styles...</div><div v-else-if="videoStyles.data?.length" class="style-grid"><button v-for="style in videoStyles.data" :key="style.workflow_key" type="button" class="style-card" :class="{ selected: settingsForm.video_style === style.workflow_key }" @click="settingsForm.video_style = style.workflow_key"><strong>{{ style.client_name }}</strong><span>{{ style.client_description }}</span></button></div><p v-else class="error-text">No video styles are currently available.</p></div>
          <Button label="Save settings" :loading="savingSettings" :disabled="!settingsForm.video_style" @click="saveSettings" />
        </div>
      </section>

      <section class="workspace-card">
        <div class="section-heading storyboard-heading"><div><p class="eyebrow">Storyboard</p><h2>{{ storyboardTitle }}</h2><p v-if="settings" class="muted">{{ automaticShotCount }} shots will be planned automatically<span v-if="referenceAssetCount"> · {{ referenceAssetCount }} usable references available</span></p></div><div class="storyboard-controls"><Button label="Generate storyboard" :loading="generatingPlan" :disabled="!settings" @click="generatePlan" /></div></div>
        <div v-if="plan?.shots?.length" class="storyboard-grid"><article v-for="shot in plan.shots" :key="shot.shot_number" class="storyboard-card"><div class="storyboard-card-heading"><div class="storyboard-number">Shot {{ shot.shot_number }}</div><span v-if="referenceAssetForShot(shot)" class="reference-label">Reference: {{ referenceAssetForShot(shot).asset_name }}</span></div><img v-if="referenceAssetForShot(shot)?.file" class="storyboard-reference-image" :src="referenceAssetForShot(shot).file" :alt="referenceAssetForShot(shot).asset_name" /><div v-else-if="shot.reference_image_index != null" class="storyboard-reference-placeholder">Reference image {{ shot.reference_image_index }}</div><FormControl v-if="shot.reference_image_index != null" v-model="shot.reference_image_index" type="number" label="Reference image" /><FormControl v-model="shot.camera" type="textarea" label="Camera & framing" /><FormControl v-model="shot.subject" type="textarea" label="What appears on screen" /><FormControl v-model="shot.motion" type="textarea" label="Movement" /><FormControl v-model="shot.lighting" type="textarea" label="Look & setting" /><FormControl v-model="shot.audio" type="textarea" label="Sound" /><FormControl v-model="shot.generation_prompt" type="textarea" label="MiniMax H3 generation prompt" /></article></div>
        <div v-else-if="workspace.storyboard?.length" class="storyboard-grid"><article v-for="shot in workspace.storyboard" :key="shot.name" class="storyboard-card"><div class="storyboard-card-heading"><div class="storyboard-number">Shot {{ shot.shot_number }}</div><span v-if="shot.reference_asset_name" class="reference-label">Reference: {{ shot.reference_asset_name }}</span></div><img v-if="shot.reference_image" class="storyboard-reference-image" :src="shot.reference_image" :alt="shot.reference_asset_name || `Shot ${shot.shot_number} reference`" /><p><strong>Camera & framing</strong>{{ shot.camera_direction }}</p><p><strong>What appears on screen</strong>{{ shot.subject_identity }}</p><p><strong>Movement</strong>{{ shot.action_plot }}</p><p><strong>Look & setting</strong>{{ shot.environment }}</p><p><strong>Sound</strong>{{ shot.audio_direction }}</p></article></div>
        <div v-else class="empty-panel"><p>No storyboard has been generated yet.</p><Button label="Generate storyboard" :disabled="!settings" @click="generatePlan" /></div>
        <div v-if="plan?.shots?.length" class="button-row storyboard-actions"><Button appearance="minimal" label="Discard plan" :disabled="applyingPlan" @click="plan = null" /><Button appearance="minimal" label="Regenerate storyboard" :loading="generatingPlan" :disabled="applyingPlan || generatingPlan || !settings" @click="generatePlan" /><Button label="Apply storyboard" :loading="applyingPlan" @click.stop="applyPlan" /></div>
        <p v-if="applyError" class="action-message error-text">{{ applyError }}</p>
        <p v-if="applySuccess" class="action-message success-text">Storyboard applied successfully.</p>
      </section>

      <section class="workspace-card">
        <div class="section-heading"><div><p class="eyebrow">Production</p><h2>{{ production?.status || "Ready to generate" }}</h2></div><div class="button-row"><Button v-if="canRetryProduction" label="Retry failed shots" :loading="retryingFailedScenes" @click="retryFailedScenes" /><Button label="Generate video" :loading="generatingVideo" :disabled="!workspace.storyboard?.length || !settings || Boolean(production && production.status !== 'Draft')" @click="generateVideo" /></div></div>
        <div v-if="production" class="progress-panel"><div class="progress-label"><span>{{ production.completed_jobs || 0 }} / {{ production.total_jobs || 0 }} shots complete</span><span>{{ production.progress || 0 }}%</span></div><div class="progress-track"><div class="progress-value" :style="{ width: `${production.progress || 0}%` }" /></div><p v-if="production.error_summary" class="error-text">{{ production.error_summary }}</p><p v-if="workflowSetupInvalid" class="muted">Update the selected Workflow Version before trying again.</p><Button v-if="requiresStoryboardRevision" label="Revise storyboard" :loading="revisingStoryboard" @click="reviseForGeneration" /></div>
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
import { Button, FormControl, call, createResource, toast, upload as uploadFile } from "frappe-ui";
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const campaign = createResource({ url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_workspace", params: { name: route.params.name }, auto: true });
const videoStyles = createResource({ url: "joymedia.joymedia.doctype.media_project.media_project.get_video_styles", auto: true });
const plan = ref(null);
const showSettings = ref(false);
const savingSettings = ref(false);
const generatingPlan = ref(false);
const applyingPlan = ref(false);
const applyError = ref("");
const applySuccess = ref(false);
const generatingVideo = ref(false);
const retryingFailedScenes = ref(false);
const revisingStoryboard = ref(false);
const uploadingImages = ref(false);
const uploadProgress = ref(0);
const uploadTotal = ref(0);
const fileInput = ref(null);
const settingsForm = reactive({ duration: 8, format: "Landscape", video_style: "" });
const workspace = computed(() => campaign.data);
const settings = computed(() => workspace.value?.video_settings);
const production = computed(() => workspace.value?.production);
const automaticShotCount = computed(() => workspace.value?.video_settings?.automatic_shot_count || 1);
const referenceAssetCount = computed(() => workspace.value?.video_settings?.reference_asset_count || 0);
const requiresStoryboardRevision = computed(() => {
  const status = production.value?.status;
  return ["Failed", "Needs Attention"].includes(status) && (
    workflowSetupInvalid.value || !(production.value?.total_jobs || 0)
  );
});
const workflowSetupInvalid = computed(() => production.value?.error_summary?.startsWith("Invalid Workflow Binding"));
const canRetryProduction = computed(() => (
  production.value &&
  production.value.failed_jobs > 0 &&
  ["Failed", "Partially Completed"].includes(production.value.status) &&
  !workflowSetupInvalid.value
));
const storyboardTitle = computed(() => {
  const count = plan.value?.shots?.length || workspace.value?.storyboard?.length || 0;
  return count ? `${count} shot${count === 1 ? "" : "s"}` : "Plan your shots";
});
watch(settings, (value) => {
  if (!value) return;
  settingsForm.duration = value.duration;
  settingsForm.format = value.delivery_preset;
  settingsForm.video_style = value.video_style || settingsForm.video_style;
}, { immediate: true });

const ACTIVE_PRODUCTION_STATUSES = new Set(["Queued", "Running", "Finalizing", "Ready for Composition"]);
let pollTimer = null;
watch(() => production.value?.status, (status) => {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  if (ACTIVE_PRODUCTION_STATUSES.has(status)) {
    pollTimer = setInterval(() => campaign.reload(), 4000);
  }
}, { immediate: true });
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer);
});

async function refresh() { plan.value = null; await campaign.reload(); }
function openImagePicker() {
  fileInput.value?.click();
}
function assetNameFromFile(fileName) {
  return fileName.replace(/\.[^/.]+$/, "");
}
async function uploadSelectedImages(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;

  uploadingImages.value = true;
  uploadProgress.value = 0;
  uploadTotal.value = files.length;
  try {
    for (const file of files) {
      const uploadedFile = await uploadFile(file, { private: true });
      await call("joymedia.joymedia.doctype.media_project.media_project.create_campaign_asset", {
        media_project: route.params.name,
        asset_name: assetNameFromFile(file.name),
        asset_category: "Product",
        file_url: uploadedFile.file_url,
      });
      uploadProgress.value += 1;
    }
    await refresh();
  } catch (error) {
    toast({ title: "Unable to save image", text: error.message || "Please try again.", type: "error" });
  } finally {
    uploadingImages.value = false;
  }
}
async function saveSettings() {
  savingSettings.value = true;
  try { await call("joymedia.joymedia.doctype.media_project.media_project.save_campaign_video_settings", { campaign_name: route.params.name, total_duration_seconds: settingsForm.duration, delivery_preset: settingsForm.format, video_style: settingsForm.video_style }); showSettings.value = false; await refresh(); }
  catch (error) { toast({ title: "Unable to save settings", text: error.message || "Please try again.", type: "error" }); }
  finally { savingSettings.value = false; }
}
async function generatePlan() {
  generatingPlan.value = true;
  plan.value = null;
  try {
    const generatedPlan = await call("joymedia.joymedia.doctype.media_project.media_project.generate_campaign_video_plan", { campaign_name: route.params.name });
    plan.value = normalizePlanForEditor(generatedPlan);
  }
  catch (error) { toast({ title: "Unable to generate storyboard", text: error.message || "Please try again.", type: "error" }); }
  finally { generatingPlan.value = false; }
}
async function retryFailedScenes() {
  retryingFailedScenes.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.retry_campaign_failed_jobs", { campaign_name: route.params.name });
    await campaign.reload();
  } catch (error) {
    toast({ title: "Unable to retry video", text: error.message || "Please try again.", type: "error" });
  } finally {
    retryingFailedScenes.value = false;
  }
}
async function reviseForGeneration() {
  revisingStoryboard.value = true;
  plan.value = null;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.revise_campaign_storyboard", { campaign_name: route.params.name, use_current_workflow_defaults: workflowSetupInvalid.value });
    await campaign.reload();
    await generatePlan();
  } catch (error) {
    toast({ title: "Unable to create storyboard revision", text: error.message || "Please try again.", type: "error" });
  } finally {
    revisingStoryboard.value = false;
  }
}
function referenceAssetForShot(shot) {
  const index = Number(shot.reference_image_index);
  return index > 0 ? workspace.value?.assets?.[index - 1] : null;
}
function readablePlanValue(value) {
  if (value == null) return "";
  if (typeof value !== "string") {
    return Object.entries(value).map(([key, item]) => `${humanizeKey(key)}: ${item}`).join(". ");
  }
  const text = value.trim();
  if (!text.startsWith("{") || !text.endsWith("}")) return value;
  try {
    return readablePlanValue(JSON.parse(text));
  } catch {
    return text.slice(1, -1).replace(/[\'"]([^\'"]+)[\'"]\s*:\s*[\'"]([^\'"]*)[\'"]/g, (_, key, item) => `${humanizeKey(key)}: ${item}`).replace(/,\s*/g, ". ");
  }
}
function humanizeKey(key) {
  return key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
function normalizePlanForEditor(value) {
  return {
    ...value,
    shots: (value?.shots || []).map((shot) => ({
      ...shot,
      camera: readablePlanValue(shot.camera),
      subject: readablePlanValue(shot.subject),
      motion: readablePlanValue(shot.motion),
      lighting: readablePlanValue(shot.lighting),
      audio: readablePlanValue(shot.audio),
    })),
  };
}
async function applyPlan() {
  if (!plan.value?.shots?.length) return;
  applyingPlan.value = true;
  applyError.value = "";
  applySuccess.value = false;
  try {
    const payload = {
      ...plan.value,
      shots: plan.value.shots.map((shot) => ({
        ...shot,
        ...(shot.reference_image_index != null
          ? { reference_image_index: Number(shot.reference_image_index) }
          : {}),
      })),
    };
    const result = await call("joymedia.joymedia.doctype.media_project.media_project.apply_campaign_video_plan", { campaign_name: route.params.name, plan_json: JSON.stringify(payload) });
    if (!result?.shots?.length) throw new Error("No shots were created.");
    applySuccess.value = true;
    await campaign.reload();
    plan.value = null;
    toast({ title: "Storyboard applied", text: `${result.shots.length} shot${result.shots.length === 1 ? "" : "s"} created.`, type: "success" });
  }
  catch (error) {
    applyError.value = error.message || "The storyboard could not be applied.";
    toast({ title: "Unable to apply storyboard", text: applyError.value, type: "error" });
  }
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

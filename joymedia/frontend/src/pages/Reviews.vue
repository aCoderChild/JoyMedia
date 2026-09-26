<template>
  <section class="page-section">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ t('reviews_eyebrow') }}</p>
        <h1>{{ t('reviews_title') }}</h1>
        <p class="subtitle">{{ t('reviews_subtitle') }}</p>
      </div>
      <Button appearance="subtle" @click="openCampaigns">
        <template #prefix><span class="lucide-clapperboard size-4" /></template>
        {{ t('reviews_view_campaigns') }}
      </Button>
    </div>

    <div v-if="reviews.data?.length" class="flex items-center justify-between gap-4 p-4 rounded-2xl bg-surface-card border border-outline-border shadow-xs mb-6">
      <div class="flex items-center gap-1.5 p-1 rounded-xl bg-surface-hover border border-outline-border">
        <button v-for="filter in filters" :key="filter.value" type="button" class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all" :class="activeFilter === filter.value ? 'bg-indigo-600 text-white shadow-xs' : 'text-ink-secondary hover:text-ink-primary'" @click="activeFilter = filter.value">
          {{ filter.label }}
        </button>
      </div>
      <span class="text-xs font-medium text-ink-muted">{{ filteredReviews.length }} {{ filteredReviews.length === 1 ? t('review_video_singular') : t('review_video_plural') }}</span>
    </div>

    <div v-if="reviews.loading" class="empty-state">
      <div class="empty-state-icon"><span class="lucide-refresh-cw size-6 animate-spin text-indigo-500" /></div>
      <h2>{{ t('reviews_loading_title') }}</h2>
      <p>{{ t('reviews_loading_desc') }}</p>
    </div>

    <div v-else-if="filteredReviews.length" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
      <article v-for="review in filteredReviews" :key="review.name" class="group bg-surface-card border border-outline-border hover:border-indigo-500/60 rounded-2xl p-4 shadow-xs hover:shadow-md transition-all flex flex-col justify-between">
        <div>
          <div class="flex items-start justify-between gap-3 mb-3">
            <div class="min-w-0">
              <h2 class="text-base font-bold text-ink-primary truncate" :title="review.campaign_name">{{ review.campaign_name }}</h2>
              <p class="text-xs text-ink-secondary truncate mt-0.5">{{ review.product_name }}</p>
            </div>
            <span class="shrink-0 text-[11px] px-2.5 py-0.5 rounded-full font-semibold" :class="statusClass(review.status)">{{ statusLabel(review.status) }}</span>
          </div>

          <div class="relative rounded-xl overflow-hidden bg-black aspect-video mb-3 border border-outline-border flex items-center justify-center">
            <video v-if="review.preview_url" :src="review.preview_url" preload="metadata" class="w-full h-full object-cover pointer-events-none" />
            <div v-else class="text-center p-4 text-ink-muted"><span class="lucide-film size-8 mx-auto mb-2 opacity-50" /><span class="text-xs">{{ t('reviews_preview_unavailable') }}</span></div>
            <button v-if="review.preview_url" type="button" class="absolute inset-0 flex items-center justify-center bg-black/20 hover:bg-black/35 transition-colors" :aria-label="t('reviews_play')" @click="openReviewModal(review)">
              <span class="size-12 rounded-full bg-white/90 flex items-center justify-center text-indigo-600 shadow-lg"><svg class="size-5 fill-current ml-0.5" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3" /></svg></span>
            </button>
          </div>

          <div class="flex items-center gap-3 text-xs text-ink-secondary mb-3 px-1">
            <span v-if="review.duration">{{ review.duration }}s</span>
            <span v-if="review.delivery_preset">· {{ review.delivery_preset }}</span>
            <span v-if="review.shot_count">· {{ review.shot_count }} {{ review.shot_count === 1 ? t('review_scene_singular') : t('review_scene_plural') }}</span>
          </div>
        </div>

        <div class="pt-3 border-t border-outline-border flex items-center justify-between gap-2">
          <a v-if="review.preview_url" :href="review.preview_url" download class="text-xs font-semibold text-ink-secondary hover:text-ink-primary">{{ t('reviews_download') }}</a>
          <Button v-if="review.status !== 'Approved'" variant="solid" class="!bg-indigo-600 hover:!bg-indigo-500 !text-white text-xs" @click="openReviewModal(review)">{{ t('reviews_review_video') }}</Button>
          <span v-else class="text-xs font-semibold text-emerald-600 dark:text-emerald-400">✓ {{ t('reviews_approved') }}</span>
        </div>
      </article>
    </div>

    <div v-else class="empty-state">
      <div class="empty-state-icon"><span class="lucide-film size-8 text-indigo-500" /></div>
      <h2>{{ t('reviews_empty_title') }}</h2>
      <p class="max-w-md mx-auto text-ink-secondary text-sm mb-4">{{ t('reviews_empty_desc') }}</p>
      <Button variant="solid" class="!bg-indigo-600 hover:!bg-indigo-500 !text-white" @click="openCampaigns">{{ t('reviews_view_campaigns') }}</Button>
    </div>

    <div v-if="selectedReview" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs" @click.self="selectedReview = null" @keydown.esc="selectedReview = null">
      <div class="w-full max-w-3xl bg-surface-card rounded-2xl border border-outline-border shadow-2xl overflow-hidden flex flex-col max-h-[92vh]">
        <div class="p-4 border-b border-outline-border flex items-center justify-between gap-3">
          <div class="min-w-0"><span class="text-[10px] px-2 py-0.5 rounded font-bold uppercase" :class="statusClass(selectedReview.status)">{{ statusLabel(selectedReview.status) }}</span><h2 class="text-lg font-bold text-ink-primary truncate mt-2">{{ selectedReview.campaign_name }}</h2><p class="text-xs text-ink-secondary">{{ selectedReview.product_name }}</p></div>
          <button type="button" class="p-1.5 text-ink-muted hover:text-ink-primary" @click="selectedReview = null"><span class="lucide-x size-5" /></button>
        </div>
        <div class="p-4 bg-black flex items-center justify-center min-h-[300px] max-h-[60vh]"><video v-if="selectedReview.preview_url" :src="selectedReview.preview_url" controls autoplay preload="metadata" class="w-full max-h-[56vh] rounded-xl object-contain" /><p v-else class="text-sm text-white">{{ t('reviews_preview_unavailable') }}</p></div>
        <div class="p-4 border-t border-outline-border flex flex-wrap items-center justify-between gap-3">
          <div class="text-xs text-ink-secondary">{{ selectedReview.duration }}s<span v-if="selectedReview.delivery_preset"> · {{ selectedReview.delivery_preset }}</span><span v-if="selectedReview.shot_count"> · {{ selectedReview.shot_count }} {{ t('review_scene_plural') }}</span></div>
          <div class="flex items-center gap-2">
            <Button v-if="selectedReview.status !== 'Approved'" variant="solid" class="!bg-emerald-600 hover:!bg-emerald-700 !text-white text-xs" :loading="actionLoading" @click="handleFinalReview('Approved')">{{ t('reviews_approve') }}</Button>
            <Button v-if="selectedReview.status !== 'Changes Requested'" appearance="subtle" class="!text-amber-700 dark:!text-amber-300 text-xs" :loading="actionLoading" @click="handleFinalReview('Changes Requested')">{{ t('reviews_request_changes') }}</Button>
            <a v-if="selectedReview.preview_url" :href="selectedReview.preview_url" download class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-surface-hover text-ink-primary border border-outline-border">{{ t('reviews_download') }}</a>
            <Button appearance="subtle" class="text-xs" @click="selectedReview = null">{{ t('btn_close') }}</Button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from "vue";
import { Button, call, createResource, toast } from "frappe-ui";
import { useI18n } from "../stores/i18n";

const { t, currentLang } = useI18n();
const activeFilter = ref("All");
const selectedReview = ref(null);
const actionLoading = ref(false);
const reviews = createResource({ url: "joymedia.joymedia.doctype.media_project.media_project.get_pending_review_cards", auto: true });
const filters = computed(() => [
  { value: "All", label: t("reviews_filter_all") },
  { value: "Pending Review", label: t("reviews_filter_pending") },
  { value: "Approved", label: t("reviews_filter_approved") },
  { value: "Changes Requested", label: t("reviews_filter_changes") },
]);
const filteredReviews = computed(() => {
  const list = reviews.data || [];
  return activeFilter.value === "All" ? list : list.filter((item) => item.status === activeFilter.value);
});

function statusClass(status) {
  if (status === "Approved") return "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20";
  if (status === "Changes Requested") return "bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/20";
  return "bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border border-indigo-500/20";
}
function statusLabel(status) {
  if (status === "Approved") return t("reviews_approved");
  if (status === "Changes Requested") return t("reviews_changes_requested");
  return t("reviews_pending");
}
function openReviewModal(review) { selectedReview.value = review; }
async function handleFinalReview(decision) {
  if (!selectedReview.value) return;
  actionLoading.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.review_final_video", { project_name: selectedReview.value.campaign, decision });
    toast({ title: decision === "Approved" ? t("reviews_approved") : t("reviews_changes_requested"), text: currentLang.value === "vi" ? "Đã cập nhật trạng thái video cuối." : "Final video status updated.", type: "success" });
    selectedReview.value = null;
    await reviews.reload();
  } catch (error) {
    toast({ title: t("reviews_update_failed"), text: error.message || t("reviews_update_failed"), type: "error" });
  } finally { actionLoading.value = false; }
}
function openCampaigns() { window.location.href = "/joymedia/campaigns"; }
</script>

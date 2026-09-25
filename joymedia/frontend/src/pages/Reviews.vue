<template>
  <section class="page-section">
    <div class="page-heading">
      <div>
        <p class="eyebrow">Quality Control · Final Delivery</p>
        <h1>Review Videos</h1>
        <p class="subtitle">
          Inspect, play, and approve generated AI video clips and assembled deliverables. Click any video to inspect.
        </p>
      </div>
      <Button appearance="subtle" @click="openCampaigns">
        <template #prefix>
          <span class="lucide-clapperboard size-4" />
        </template>
        View Campaigns
      </Button>
    </div>

    <!-- Status filter toolbar -->
    <div v-if="reviews.data?.length" class="flex items-center justify-between gap-4 p-4 rounded-2xl bg-surface-card border border-outline-border shadow-xs mb-6">
      <div class="flex items-center gap-1.5 p-1 rounded-xl bg-surface-hover border border-outline-border">
        <button
          v-for="status in ['All', 'Pending', 'Approved', 'Rejected']"
          :key="status"
          type="button"
          class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
          :class="activeFilter === status
            ? 'bg-indigo-600 text-white shadow-xs'
            : 'text-ink-secondary hover:text-ink-primary'"
          @click="activeFilter = status"
        >
          {{ status }}
        </button>
      </div>

      <span class="text-xs font-medium text-ink-muted">
        {{ filteredReviews.length }} {{ filteredReviews.length === 1 ? 'video' : 'videos' }}
      </span>
    </div>

    <!-- Loading State -->
    <div v-if="reviews.loading" class="empty-state">
      <div class="empty-state-icon">
        <span class="lucide-refresh-cw size-6 animate-spin text-indigo-500" />
      </div>
      <h2>Loading video reviews...</h2>
      <p>Fetching completed clips and assembled deliverables ready for inspection.</p>
    </div>

    <!-- Review Videos Grid -->
    <div v-else-if="filteredReviews.length" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
      <article
        v-for="review in filteredReviews"
        :key="review.name"
        class="group bg-surface-card border border-outline-border hover:border-indigo-500/60 rounded-2xl p-4 shadow-xs hover:shadow-md transition-all flex flex-col justify-between cursor-pointer select-none"
        @click="openReviewModal(review)"
      >
        <div>
          <!-- Card Header -->
          <div class="flex items-start justify-between gap-3 mb-3">
            <div class="min-w-0">
              <h2 class="text-base font-bold text-ink-primary truncate group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors" :title="review.campaign_name || review.name">
                {{ review.campaign_name || review.name }}
              </h2>
              <p class="text-xs text-ink-secondary truncate mt-0.5">
                {{ review.product_name || "Commercial Video Clip" }}
              </p>
            </div>

            <!-- Video Type Badge -->
            <span
              class="shrink-0 text-[11px] px-2.5 py-0.5 rounded-full font-semibold"
              :class="review.is_single_shot ? 'bg-teal-500/15 text-teal-700 dark:text-teal-300 border border-teal-500/20' : 'bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border border-indigo-500/20'"
            >
              {{ review.video_type || "Generated Video" }}
            </span>
          </div>

          <!-- Video Preview Box with Play Overlay -->
          <div class="relative rounded-xl overflow-hidden bg-black aspect-video mb-3 border border-outline-border flex items-center justify-center group-hover:opacity-95 transition-opacity">
            <!-- Play Button Overlay -->
            <div class="absolute inset-0 z-10 flex items-center justify-center bg-black/20 group-hover:bg-black/35 transition-colors">
              <div class="size-12 rounded-full bg-white/90 dark:bg-slate-900/90 flex items-center justify-center text-indigo-600 shadow-lg group-hover:scale-110 transition-transform">
                <svg class="size-5 fill-current ml-0.5" viewBox="0 0 24 24">
                  <polygon points="5 3 19 12 5 21 5 3"/>
                </svg>
              </div>
            </div>

            <!-- Video Thumbnail -->
            <video
              v-if="review.preview_url"
              :src="review.preview_url"
              preload="metadata"
              class="w-full h-full object-cover pointer-events-none"
            />
            <div v-else class="text-center p-4 text-ink-muted">
              <span class="lucide-film size-8 mx-auto mb-2 opacity-50" />
              <span class="text-xs font-medium">Click to inspect video stream</span>
            </div>

            <!-- Status tag in corner -->
            <span
              class="absolute top-2.5 right-2.5 z-20 px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider backdrop-blur-md shadow-xs"
              :class="{
                'bg-amber-500/90 text-white': review.status === 'Pending' || review.status === 'Ready for Review',
                'bg-emerald-600/90 text-white': review.status === 'Approved' || review.status === 'Completed',
                'bg-rose-600/90 text-white': review.status === 'Rejected',
              }"
            >
              {{ review.status || "Pending" }}
            </span>
          </div>

          <!-- Video Metadata -->
          <div class="flex items-center justify-between text-xs text-ink-secondary mb-3 px-1">
            <span v-if="review.duration" class="font-medium">
              Duration: <strong>{{ review.duration }}s</strong>
            </span>
            <span v-if="review.shot_count" class="font-medium">
              {{ review.shot_count }} {{ review.shot_count === 1 ? 'shot' : 'shots' }}
            </span>
            <span class="text-[11px] font-mono text-ink-muted">
              {{ review.name }}
            </span>
          </div>
        </div>

        <!-- Card Footer -->
        <div class="pt-3 border-t border-outline-border flex items-center justify-between">
          <span class="text-xs text-ink-muted truncate" :title="review.campaign">
            {{ review.campaign || "Project Deliverable" }}
          </span>
          <span class="text-xs font-semibold text-indigo-600 dark:text-indigo-400 flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
            <span>Play & Inspect</span>
            <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </span>
        </div>
      </article>
    </div>

    <!-- Empty State -->
    <div v-else class="empty-state">
      <div class="empty-state-icon">
        <span class="lucide-check-circle size-8 text-emerald-500" />
      </div>
      <h2>No review videos matching filter</h2>
      <p class="max-w-md mx-auto text-ink-secondary text-sm mb-4">
        Videos generated during production runs will appear here for inspection, playback, and sign-off.
      </p>
      <Button variant="solid" @click="openCampaigns">
        Go to Campaigns
      </Button>
    </div>

    <!-- Interactive Review Inspection Modal -->
    <div
      v-if="selectedReview"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs"
      @click.self="selectedReview = null"
      @keydown.esc="selectedReview = null"
    >
      <div class="w-full max-w-3xl bg-surface-card rounded-2xl border border-outline-border shadow-2xl overflow-hidden flex flex-col max-h-[92vh] animate-in fade-in zoom-in-95 duration-150">
        <!-- Modal Header -->
        <div class="p-4 border-b border-outline-border flex items-center justify-between gap-3 bg-surface-hover/50">
          <div class="min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span
                class="text-[10px] px-2 py-0.5 rounded font-bold uppercase tracking-wider"
                :class="{
                  'bg-amber-500 text-white': selectedReview.status === 'Pending' || selectedReview.status === 'Ready for Review',
                  'bg-emerald-600 text-white': selectedReview.status === 'Approved' || selectedReview.status === 'Completed',
                  'bg-rose-600 text-white': selectedReview.status === 'Rejected',
                }"
              >
                {{ selectedReview.status || 'Pending' }}
              </span>
              <span class="text-[10px] px-2 py-0.5 rounded font-semibold bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 border border-indigo-500/20">
                {{ selectedReview.video_type || 'Video Deliverable' }}
              </span>
              <span class="text-[10px] text-ink-muted font-mono">
                {{ selectedReview.name }}
              </span>
            </div>
            <h2 class="text-lg font-bold text-ink-primary truncate" :title="selectedReview.campaign_name || selectedReview.name">
              {{ selectedReview.campaign_name || selectedReview.name }}
            </h2>
            <p class="text-xs text-ink-secondary mt-0.5">
              {{ selectedReview.product_name || "Featured Product Video" }}
            </p>
          </div>

          <button
            type="button"
            class="p-1.5 rounded-lg text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors"
            @click="selectedReview = null"
          >
            <span class="lucide-x size-5" />
          </button>
        </div>

        <!-- Modal Media Area (Large Video Player) -->
        <div class="p-4 bg-black flex items-center justify-center overflow-hidden flex-1 min-h-[300px] max-h-[60vh]">
          <video
            v-if="selectedReview.preview_url"
            :src="selectedReview.preview_url"
            controls
            autoplay
            preload="metadata"
            class="w-full max-h-[56vh] rounded-xl object-contain shadow-2xl"
          />
          <div v-else class="text-center p-8 text-ink-muted">
            <span class="lucide-film size-12 mx-auto mb-2 opacity-50 text-white" />
            <p class="text-sm font-medium text-white">Video stream preview is processing.</p>
            <p class="text-xs mt-1 text-slate-400">Review ID: {{ selectedReview.name }}</p>
          </div>
        </div>

        <!-- Modal Actions & Footer -->
        <div class="p-4 bg-surface-card border-t border-outline-border flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-3 text-xs text-ink-secondary">
            <span v-if="selectedReview.duration">Duration: <strong>{{ selectedReview.duration }}s</strong></span>
            <span v-if="selectedReview.duration">·</span>
            <span>Target: <strong>{{ selectedReview.campaign || "Project" }}</strong></span>
          </div>

          <div class="flex items-center gap-2">
            <!-- Approve Button -->
            <Button
              v-if="selectedReview.status !== 'Approved'"
              variant="solid"
              class="!bg-emerald-600 hover:!bg-emerald-700 !text-white text-xs font-semibold"
              :loading="actionLoading"
              @click="handleReviewAction('approve')"
            >
              <template #prefix>
                <span class="lucide-check size-3.5" />
              </template>
              Approve Video
            </Button>

            <!-- Reject Button -->
            <Button
              v-if="selectedReview.status !== 'Rejected'"
              appearance="subtle"
              class="!text-rose-600 hover:!bg-rose-50 dark:hover:!bg-rose-950/30 text-xs font-semibold"
              :loading="actionLoading"
              @click="handleReviewAction('reject')"
            >
              <template #prefix>
                <span class="lucide-x size-3.5" />
              </template>
              Reject
            </Button>

            <!-- Download Button -->
            <a
              v-if="selectedReview.preview_url"
              :href="selectedReview.preview_url"
              download
              class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-surface-hover hover:bg-surface-active text-ink-primary border border-outline-border transition-colors"
            >
              <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
              <span>Download</span>
            </a>

            <!-- Open in Project Cockpit -->
            <Button
              appearance="subtle"
              class="text-xs"
              @click="openCockpit(selectedReview.campaign)"
            >
              Open Cockpit
            </Button>

            <Button appearance="subtle" class="text-xs" @click="selectedReview = null">Close</Button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from "vue";
import { Button, call, createResource, toast } from "frappe-ui";

const activeFilter = ref("All");
const selectedReview = ref(null);
const actionLoading = ref(false);

const reviews = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_pending_review_cards",
  auto: true,
});

const filteredReviews = computed(() => {
  const list = reviews.data || [];
  if (activeFilter.value === "All") return list;
  return list.filter((r) => r.status === activeFilter.value);
});

function openReviewModal(review) {
  selectedReview.value = review;
}

async function handleReviewAction(action) {
  if (!selectedReview.value) return;
  actionLoading.value = true;
  const endpoint = action === "approve"
    ? "joymedia.joymedia.doctype.media_project.media_project.approve_review"
    : "joymedia.joymedia.doctype.media_project.media_project.reject_review";

  try {
    await call(endpoint, {
      review_name: selectedReview.value.name,
      campaign_name: selectedReview.value.campaign,
    });
    toast({
      title: action === "approve" ? "Video Approved" : "Video Rejected",
      text: `Review ${selectedReview.value.name} marked as ${action === "approve" ? "Approved" : "Rejected"}.`,
      type: "success",
    });
    selectedReview.value.status = action === "approve" ? "Approved" : "Rejected";
    await reviews.reload();
  } catch (err) {
    toast({
      title: "Update Failed",
      text: err.message || "Could not update review status.",
      type: "error",
    });
  } finally {
    actionLoading.value = false;
  }
}

function openCockpit(campaignName) {
  if (!campaignName || campaignName === "Project") {
    window.location.href = "/joymedia/campaigns";
    return;
  }
  if (campaignName.startsWith("PRJ-")) {
    window.location.href = `/joymedia/projects/${encodeURIComponent(campaignName)}`;
  } else {
    window.location.href = `/joymedia/campaigns/${encodeURIComponent(campaignName)}`;
  }
}

function openCampaigns() {
  window.location.href = "/joymedia/campaigns";
}
</script>

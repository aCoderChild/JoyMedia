<template>
  <div class="page-section">
    <!-- 1. Page Header -->
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ t('campaigns_count', { n: filteredCampaigns.length }) }} · JoyMedia</p>
        <h1>{{ t('campaigns_page_title') }}</h1>
        <p class="subtitle">{{ t('campaigns_page_subtitle') }}</p>
      </div>

      <div class="flex items-center gap-3">
        <button
          type="button"
          class="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold bg-surface-card hover:bg-surface-hover text-ink-primary border border-outline-border transition-all shadow-xs cursor-pointer"
          :disabled="campaigns.loading"
          @click="campaigns.reload()"
        >
          <span class="lucide-refresh-cw size-3.5" :class="{ 'animate-spin': campaigns.loading }" />
          <span>{{ currentLang === 'vi' ? 'Làm mới' : 'Refresh' }}</span>
        </button>

        <button
          type="button"
          class="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-600/20 transition-all cursor-pointer"
          @click="showCreateModal = true"
        >
          <span class="lucide-plus size-4" />
          <span>{{ t('new_campaign_btn') }}</span>
        </button>
      </div>
    </div>

    <!-- 2. Statistics Summary Strip -->
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
      <div class="p-4 rounded-2xl bg-surface-card border border-outline-border shadow-xs flex items-center justify-between transition-all hover:border-indigo-500/30">
        <div>
          <span class="text-xs font-semibold text-ink-muted uppercase tracking-wider block">
            {{ t('total_campaigns_stat') }}
          </span>
          <span class="text-2xl font-extrabold text-ink-primary block mt-1">
            {{ allCampaigns.length }}
          </span>
        </div>
        <div class="size-11 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center text-lg shadow-xs">
          🎯
        </div>
      </div>

      <div class="p-4 rounded-2xl bg-surface-card border border-outline-border shadow-xs flex items-center justify-between transition-all hover:border-emerald-500/30">
        <div>
          <span class="text-xs font-semibold text-ink-muted uppercase tracking-wider block">
            {{ t('total_projects_stat') }}
          </span>
          <span class="text-2xl font-extrabold text-ink-primary block mt-1">
            {{ totalProjectsCount }}
          </span>
        </div>
        <div class="size-11 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center text-lg shadow-xs">
          🎬
        </div>
      </div>

      <div class="p-4 rounded-2xl bg-surface-card border border-outline-border shadow-xs flex items-center justify-between transition-all hover:border-amber-500/30">
        <div>
          <span class="text-xs font-semibold text-ink-muted uppercase tracking-wider block">
            {{ t('total_assets_stat') }}
          </span>
          <span class="text-2xl font-extrabold text-ink-primary block mt-1">
            {{ totalAssetsCount }}
          </span>
        </div>
        <div class="size-11 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-center justify-center text-lg shadow-xs">
          📁
        </div>
      </div>
    </div>

    <!-- 3. Toolbar: Status Filter Tabs & Search -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-3 rounded-2xl bg-surface-card border border-outline-border shadow-xs mb-6">
      <!-- Status Tabs -->
      <div class="flex items-center gap-1.5 p-1 rounded-xl bg-surface-muted border border-outline-border">
        <button
          type="button"
          class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer"
          :class="statusFilter === 'all'
            ? 'bg-indigo-600 text-white shadow-xs'
            : 'text-ink-secondary hover:text-ink-primary'"
          @click="statusFilter = 'all'"
        >
          <span>{{ t('filter_all') }}</span>
          <span
            class="text-[10px] px-1.5 py-0.5 rounded-full font-mono font-bold"
            :class="statusFilter === 'all' ? 'bg-indigo-700/80 text-white' : 'bg-surface-hover text-ink-muted'"
          >
            {{ allCampaigns.length }}
          </span>
        </button>

        <button
          type="button"
          class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer"
          :class="statusFilter === 'active'
            ? 'bg-indigo-600 text-white shadow-xs'
            : 'text-ink-secondary hover:text-ink-primary'"
          @click="statusFilter = 'active'"
        >
          <span class="size-1.5 rounded-full bg-emerald-400 inline-block" />
          <span>{{ t('filter_active') }}</span>
          <span
            class="text-[10px] px-1.5 py-0.5 rounded-full font-mono font-bold"
            :class="statusFilter === 'active' ? 'bg-indigo-700/80 text-white' : 'bg-surface-hover text-ink-muted'"
          >
            {{ activeCampaignsCount }}
          </span>
        </button>

        <button
          type="button"
          class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer"
          :class="statusFilter === 'draft'
            ? 'bg-indigo-600 text-white shadow-xs'
            : 'text-ink-secondary hover:text-ink-primary'"
          @click="statusFilter = 'draft'"
        >
          <span class="size-1.5 rounded-full bg-zinc-400 inline-block" />
          <span>{{ t('filter_draft') }}</span>
          <span
            class="text-[10px] px-1.5 py-0.5 rounded-full font-mono font-bold"
            :class="statusFilter === 'draft' ? 'bg-indigo-700/80 text-white' : 'bg-surface-hover text-ink-muted'"
          >
            {{ draftCampaignsCount }}
          </span>
        </button>
      </div>

      <!-- Search Input -->
      <div class="w-full sm:w-80 relative flex items-center">
        <span class="lucide-search size-3.5 text-ink-muted absolute left-3 pointer-events-none" />
        <input
          v-model="searchQuery"
          type="text"
          :placeholder="t('search_campaigns_placeholder')"
          class="w-full bg-surface-muted border border-outline-border rounded-xl pl-9 pr-3.5 py-1.5 text-xs text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-xs transition-all"
        />
      </div>
    </div>

    <!-- 4. Loading Skeleton -->
    <div v-if="campaigns.loading && !allCampaigns.length" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
      <div v-for="i in 3" :key="i" class="p-5 rounded-2xl bg-surface-card border border-outline-border animate-pulse space-y-4">
        <div class="aspect-video bg-surface-hover rounded-xl" />
        <div class="h-4 bg-surface-hover rounded w-3/4" />
        <div class="h-3 bg-surface-hover rounded w-1/2" />
      </div>
    </div>

    <!-- 5. Campaign Cards Grid -->
    <div v-else-if="filteredCampaigns.length" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
      <article
        v-for="campaign in filteredCampaigns"
        :key="campaign.name"
        class="group rounded-2xl bg-surface-card hover:bg-surface-hover border border-outline-border hover:border-indigo-500/50 shadow-xs hover:shadow-xl transition-all duration-200 cursor-pointer flex flex-col justify-between overflow-hidden"
        @click="openStudio(campaign.name)"
      >
        <!-- Top Media Thumbnail -->
        <div>
          <div class="relative aspect-video overflow-hidden bg-surface-muted border-b border-outline-border">
            <img
              v-if="campaign.cover_image"
              :src="campaign.cover_image"
              :alt="campaign.campaign_name"
              class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            />
            <div
              v-else
              class="w-full h-full flex flex-col items-center justify-center p-6 text-center"
              :class="campaign.status === 'Active' ? 'cover-generating' : 'cover-draft'"
            >
              <div class="size-11 rounded-2xl bg-white/10 backdrop-blur-md border border-white/20 flex items-center justify-center text-white mb-2 shadow-sm group-hover:scale-110 transition-transform">
                <span class="lucide-clapperboard size-5 text-white" />
              </div>
              <span class="text-xs font-semibold text-white/90 drop-shadow-sm">JoyMedia Studio</span>
            </div>

            <!-- Top Left Status Badge -->
            <div class="absolute top-3 left-3 z-10 status-badge">
              <span
                class="status-dot"
                :class="campaign.status === 'Active' ? 'bg-emerald-400' : 'bg-zinc-400'"
              />
              <span>{{ campaign.status === 'Active' ? (currentLang === 'vi' ? 'Đang chạy' : 'Active') : (currentLang === 'vi' ? 'Bản nháp' : 'Draft') }}</span>
            </div>

            <!-- Top Right Project Count Pill -->
            <span class="absolute top-3 right-3 z-10 text-[11px] font-mono font-medium px-2 py-0.5 rounded-md backdrop-blur-md shadow-xs bg-black/60 text-white/90 border border-white/15">
              {{ t('card_projects_label', { n: campaign.project_count || 1 }) }}
            </span>
          </div>

          <!-- Card Body -->
          <div class="p-5 space-y-2.5">
            <div class="flex items-center gap-2 text-xs font-medium text-ink-muted">
              <span class="text-indigo-400 font-semibold truncate">{{ campaign.client_organization || 'JoyMedia' }}</span>
              <span>•</span>
              <span class="truncate">{{ t('campaign_audience_label') }}: {{ campaign.target_audience || 'Khách hàng mục tiêu' }}</span>
            </div>

            <h3 class="text-base font-bold text-ink-primary group-hover:text-indigo-400 transition-colors line-clamp-1">
              {{ campaign.campaign_name || campaign.project_name }}
            </h3>

            <div class="flex items-center gap-1.5 text-xs text-ink-secondary font-medium">
              <span class="text-indigo-400">🏷️</span>
              <span class="truncate">{{ campaign.product_name || "Sản phẩm thương mại" }}</span>
            </div>

            <p v-if="campaign.campaign_brief" class="text-xs text-ink-muted line-clamp-2 leading-relaxed pt-1">
              {{ campaign.campaign_brief }}
            </p>
            <p v-else class="text-xs text-ink-muted italic pt-1">
              {{ currentLang === 'vi' ? 'Bấm để mở kịch bản và sản xuất video quảng cáo với AI Director.' : 'Click to launch storyboard and produce video ads with AI Director.' }}
            </p>
          </div>
        </div>

        <!-- Card Footer -->
        <div class="px-5 py-3.5 bg-surface-muted/50 border-t border-outline-border flex items-center justify-between text-xs">
          <span class="text-ink-muted font-mono text-[11px] flex items-center gap-1.5">
            <span>📁</span>
            <span>{{ t('card_assets_label', { n: campaign.asset_count || 0 }) }}</span>
          </span>

          <button
            type="button"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-xs transition-all cursor-pointer group-hover:shadow-md"
            @click.stop="openStudio(campaign.name)"
          >
            <span>{{ currentLang === 'vi' ? 'Mở JoyMedia Studio' : 'Open JoyMedia Studio' }}</span>
            <span class="transition-transform group-hover:translate-x-1">→</span>
          </button>
        </div>
      </article>
    </div>

    <!-- 6. Empty State -->
    <div v-else class="empty-state">
      <div class="empty-state-icon">
        <span class="lucide-clapperboard size-8 text-indigo-500" />
      </div>
      <h2>{{ t('no_campaigns_found') }}</h2>
      <p>{{ t('no_campaigns_desc') }}</p>
      <button
        type="button"
        class="mt-4 flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-600/20 transition-all cursor-pointer"
        @click="showCreateModal = true"
      >
        <span class="lucide-plus size-4" />
        <span>{{ t('create_first_campaign') }}</span>
      </button>
    </div>

    <!-- 7. Quick Creation Modal -->
    <div
      v-if="showCreateModal"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs"
      @click.self="showCreateModal = false"
    >
      <div class="w-full max-w-md bg-surface-card border border-outline-border rounded-2xl p-6 shadow-2xl text-xs space-y-4 animate-in fade-in zoom-in-95 duration-150">
        <div class="flex items-center justify-between pb-3 border-b border-outline-border">
          <div>
            <h3 class="text-sm font-bold text-ink-primary">{{ t('create_modal_title') }}</h3>
            <p class="text-ink-secondary text-[11px] mt-0.5">{{ t('create_modal_subtitle') }}</p>
          </div>
          <button type="button" class="text-ink-muted hover:text-ink-primary cursor-pointer p-1" @click="showCreateModal = false">✕</button>
        </div>

        <div>
          <label class="block text-ink-primary font-semibold mb-1">{{ t('field_product_name') }}</label>
          <FormControl v-model="quickProductName" type="text" :placeholder="t('product_name_placeholder')" required />
        </div>

        <div>
          <label class="block text-ink-primary font-semibold mb-1">{{ t('field_campaign_name') }}</label>
          <FormControl v-model="quickCampaignName" type="text" :placeholder="t('campaign_name_placeholder')" />
        </div>

        <div>
          <label class="block text-ink-primary font-semibold mb-1">{{ t('field_target_audience') }}</label>
          <FormControl v-model="quickAudience" type="text" :placeholder="t('audience_placeholder')" />
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-ink-primary font-semibold mb-1">{{ t('field_duration') }}</label>
            <FormControl
              v-model="quickDuration"
              type="select"
              :options="[
                { label: '15s (Reels/TikTok)', value: 15 },
                { label: '30s (Commercial)', value: 30 },
                { label: '10s (Teaser)', value: 10 }
              ]"
            />
          </div>
          <div>
            <label class="block text-ink-primary font-semibold mb-1">{{ t('field_format') }}</label>
            <FormControl
              v-model="quickFormat"
              type="select"
              :options="['Portrait', 'Landscape', 'Square']"
            />
          </div>
        </div>

        <div>
          <label class="block text-ink-primary font-semibold mb-1">{{ t('field_continuity') }}</label>
          <FormControl
            v-model="quickContinuityMode"
            type="select"
            :options="[
              { label: t('opt_multishot'), value: 'Multi-shot' },
              { label: t('opt_continuous'), value: 'Continuous' },
            ]"
          />
        </div>

        <div class="flex items-center justify-end gap-2.5 pt-3 border-t border-outline-border">
          <button
            type="button"
            class="px-3.5 py-2 rounded-xl text-xs font-semibold bg-surface-muted hover:bg-surface-hover text-ink-primary border border-outline-border transition-all cursor-pointer"
            @click="showCreateModal = false"
          >
            {{ t('btn_cancel') }}
          </button>
          <button
            type="button"
            class="px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-600/20 transition-all cursor-pointer flex items-center gap-1.5"
            :disabled="creatingProject"
            @click="submitQuickCreate"
          >
            <span v-if="creatingProject" class="lucide-refresh-cw size-3 animate-spin" />
            <span>{{ t('btn_start_studio') }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { Button, FormControl, call, createResource, toast } from "frappe-ui";
import { useI18n } from "../stores/i18n";

const router = useRouter();
const { t, currentLang } = useI18n();

const showCreateModal = ref(false);
const creatingProject = ref(false);
const searchQuery = ref("");
const statusFilter = ref("all"); // 'all' | 'active' | 'draft'

const quickProductName = ref("");
const quickCampaignName = ref("");
const quickAudience = ref("Khách hàng trẻ tuổi và người tiêu dùng trực tuyến");
const quickDuration = ref(15);
const quickFormat = ref("Portrait");
const quickContinuityMode = ref("Multi-shot");

const campaigns = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_cards",
  auto: true,
});

const businesses = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_businesses",
  auto: true,
});

const allCampaigns = computed(() => campaigns.data || []);

const activeCampaignsCount = computed(() => {
  return allCampaigns.value.filter((c) => (c.status || "Active").toLowerCase() === "active").length;
});

const draftCampaignsCount = computed(() => {
  return allCampaigns.value.filter((c) => (c.status || "").toLowerCase() === "draft").length;
});

const totalProjectsCount = computed(() => {
  return allCampaigns.value.reduce((acc, c) => acc + (c.project_count || 1), 0);
});

const totalAssetsCount = computed(() => {
  return allCampaigns.value.reduce((acc, c) => acc + (c.asset_count || 0), 0);
});

const filteredCampaigns = computed(() => {
  let list = allCampaigns.value;

  // Status Filter
  if (statusFilter.value === "active") {
    list = list.filter((c) => (c.status || "Active").toLowerCase() === "active");
  } else if (statusFilter.value === "draft") {
    list = list.filter((c) => (c.status || "").toLowerCase() === "draft");
  }

  // Search Filter
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase();
    list = list.filter((c) => {
      const name = (c.campaign_name || c.project_name || "").toLowerCase();
      const prod = (c.product_name || "").toLowerCase();
      const org = (c.client_organization || "").toLowerCase();
      const aud = (c.target_audience || "").toLowerCase();
      const brief = (c.campaign_brief || "").toLowerCase();
      return name.includes(q) || prod.includes(q) || org.includes(q) || aud.includes(q) || brief.includes(q);
    });
  }

  return list;
});

function openStudio(projectName) {
  if (!projectName) return;
  router.push(`/projects/${encodeURIComponent(projectName)}`);
}

async function submitQuickCreate() {
  const prod = quickProductName.value.trim();
  if (!prod) {
    toast({
      title: currentLang.value === "vi" ? "Thiếu tên sản phẩm" : "Missing Product Name",
      text: currentLang.value === "vi" ? "Vui lòng nhập tên sản phẩm để bắt đầu." : "Please enter a product name to continue.",
      type: "error"
    });
    return;
  }

  creatingProject.value = true;
  try {
    let org = businesses.data?.[0]?.name;
    if (!org) {
      const createdOrg = await call("joymedia.joymedia.doctype.media_project.media_project.create_business", {
        organization_name: "Cửa hàng của tôi",
        industry: "Bán lẻ",
      });
      org = createdOrg.name;
    }

    // 1. Create Campaign and Media Project in Frappe DB
    const campTitle = quickCampaignName.value.trim() || `Quảng cáo ${prod}`;
    const projectDoc = await call("joymedia.joymedia.doctype.media_project.media_project.create_campaign", {
      campaign_name: campTitle,
      project_name: `${prod} (${quickDuration.value}s)`,
      client_organization: org,
      product_name: prod,
      target_audience: quickAudience.value,
      video_idea: `Video quảng cáo hiện đại, làm nổi bật chi tiết sản phẩm ${prod}, màu sắc tươi sáng và bắt mắt.`,
    });

    // 2. Immediately initialize Media Specification in Frappe DB
    await call("joymedia.joymedia.doctype.media_project.media_project.save_campaign_video_settings", {
      campaign_name: projectDoc.name,
      total_duration_seconds: quickDuration.value,
      delivery_preset: quickFormat.value,
      video_style: null,
      continuity_mode: quickContinuityMode.value || "Multi-shot",
    });

    toast({
      title: currentLang.value === "vi" ? "Đã tạo chiến dịch!" : "Campaign Created!",
      text: currentLang.value === "vi" ? "Đang mở JoyMedia Studio..." : "Opening JoyMedia Studio...",
      type: "success"
    });
    showCreateModal.value = false;
    router.push(`/projects/${encodeURIComponent(projectDoc.name)}`);
  } catch (error) {
    toast({
      title: currentLang.value === "vi" ? "Lỗi tạo chiến dịch" : "Creation Error",
      text: error.message || "Vui lòng thử lại.",
      type: "error"
    });
  } finally {
    creatingProject.value = false;
  }
}
</script>

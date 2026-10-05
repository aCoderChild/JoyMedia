<template>
  <div class="page-section max-w-7xl mx-auto w-full p-4 sm:p-6 space-y-6">
    <!-- 1. Page Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl sm:text-3xl font-extrabold tracking-tight text-ink-primary">
          {{ currentLang === 'vi' ? 'Dự án của bạn' : 'Your Projects' }}
        </h1>
        <p class="text-xs sm:text-sm text-ink-secondary mt-1">
          {{ currentLang === 'vi' ? 'Sản xuất và quản lý các video quảng cáo sản phẩm với AI Studio.' : 'Create and manage your AI product video projects.' }}
        </p>
      </div>

      <!-- New Project Action -->
        <div v-if="projectsList.length" class="flex items-center gap-2">
          <button
            type="button"
            class="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-600/20 transition-all cursor-pointer"
            :disabled="creatingProject"
            @click="handleNewProject"
          >
            <span v-if="creatingProject" class="lucide-refresh-cw size-4 animate-spin" />
            <span v-else class="text-sm font-bold">+</span>
            <span>{{ currentLang === 'vi' ? 'Dự án mới' : 'New Project' }}</span>
          </button>
        </div>
      </div>

    <!-- 2. Toolbar: Clean Status Filters & Search Bar -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-2.5 rounded-2xl bg-surface-card border border-outline-border shadow-xs">
      <!-- Status Tabs: All, Draft, Generating, Completed -->
      <div class="flex items-center gap-1 p-1 rounded-xl bg-surface-muted border border-outline-border text-xs">
        <button
          type="button"
          class="px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer flex items-center gap-1.5"
          :class="statusFilter === 'all'
            ? 'bg-indigo-600 text-white shadow-xs'
            : 'text-ink-secondary hover:text-ink-primary'"
          @click="statusFilter = 'all'"
        >
          <span>{{ currentLang === 'vi' ? 'Tất cả' : 'All' }}</span>
          <span class="text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold" :class="statusFilter === 'all' ? 'bg-indigo-700 text-white' : 'bg-surface-card text-ink-muted'">
            {{ projectTotal }}
          </span>
        </button>

        <button
          type="button"
          class="px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer flex items-center gap-1.5"
          :class="statusFilter === 'Needs Attention'
            ? 'bg-indigo-600 text-white shadow-xs'
            : 'text-ink-secondary hover:text-ink-primary'"
          @click="statusFilter = 'Needs Attention'"
        >
          <span class="size-1.5 rounded-full bg-rose-400 inline-block" />
          <span>{{ currentLang === 'vi' ? 'Cần chú ý' : 'Needs attention' }}</span>
          <span class="text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold" :class="statusFilter === 'Needs Attention' ? 'bg-indigo-700 text-white' : 'bg-surface-card text-ink-muted'">
            {{ countByStatus('Needs Attention') }}
          </span>
        </button>

        <button
          type="button"
          class="px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer flex items-center gap-1.5"
          :class="statusFilter === 'Draft'
            ? 'bg-indigo-600 text-white shadow-xs'
            : 'text-ink-secondary hover:text-ink-primary'"
          @click="statusFilter = 'Draft'"
        >
          <span class="size-1.5 rounded-full bg-zinc-400 inline-block" />
          <span>{{ currentLang === 'vi' ? 'Bản nháp' : 'Draft' }}</span>
          <span class="text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold" :class="statusFilter === 'Draft' ? 'bg-indigo-700 text-white' : 'bg-surface-card text-ink-muted'">
            {{ countByStatus('Draft') }}
          </span>
        </button>

        <button
          type="button"
          class="px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer flex items-center gap-1.5"
          :class="statusFilter === 'Generating'
            ? 'bg-indigo-600 text-white shadow-xs'
            : 'text-ink-secondary hover:text-ink-primary'"
          @click="statusFilter = 'Generating'"
        >
          <span class="size-1.5 rounded-full bg-indigo-400 inline-block animate-pulse" />
          <span>{{ currentLang === 'vi' ? 'Đang tạo' : 'Generating' }}</span>
          <span class="text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold" :class="statusFilter === 'Generating' ? 'bg-indigo-700 text-white' : 'bg-surface-card text-ink-muted'">
            {{ countByStatus('Generating') }}
          </span>
        </button>

        <button
          type="button"
          class="px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer flex items-center gap-1.5"
          :class="statusFilter === 'Completed'
            ? 'bg-indigo-600 text-white shadow-xs'
            : 'text-ink-secondary hover:text-ink-primary'"
          @click="statusFilter = 'Completed'"
        >
          <span class="size-1.5 rounded-full bg-emerald-400 inline-block" />
          <span>{{ currentLang === 'vi' ? 'Đã hoàn thành' : 'Completed' }}</span>
          <span class="text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold" :class="statusFilter === 'Completed' ? 'bg-indigo-700 text-white' : 'bg-surface-card text-ink-muted'">
            {{ countByStatus('Completed') }}
          </span>
        </button>
      </div>

      <!-- Search Input -->
      <div class="w-full sm:w-72 relative flex items-center">
        <span class="lucide-search size-3.5 text-ink-muted absolute left-3 pointer-events-none" />
        <input
          v-model="searchQuery"
          type="text"
          :placeholder="currentLang === 'vi' ? 'Tìm theo tên dự án, sản phẩm...' : 'Search projects or products...'"
          class="w-full bg-surface-muted border border-outline-border rounded-xl pl-9 pr-3.5 py-1.5 text-xs text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-indigo-500 shadow-xs"
        />
      </div>
    </div>

    <!-- 3. Loading Skeleton -->
    <div v-if="projectsResource.loading && !projectsList.length" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
      <div v-for="i in 3" :key="i" class="p-4 rounded-2xl bg-surface-card border border-outline-border animate-pulse space-y-3">
        <div class="aspect-video bg-surface-hover rounded-xl" />
        <div class="h-4 bg-surface-hover rounded w-2/3" />
        <div class="h-3 bg-surface-hover rounded w-1/2" />
      </div>
    </div>

    <!-- 4. Projects Cards Grid (1 Card = 1 Media Project) -->
    <div v-else-if="filteredProjects.length" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
      <article
        v-for="project in filteredProjects"
        :key="project.name"
        class="group relative rounded-2xl bg-surface-card hover:bg-surface-hover border border-outline-border hover:border-indigo-500/50 shadow-xs hover:shadow-xl transition-all duration-200 cursor-pointer flex flex-col justify-between overflow-hidden"
        @click="openStudio(project.name)"
      >
        <button
          type="button"
          class="absolute top-2.5 right-2.5 z-20 size-7 rounded-lg bg-black/60 text-white hover:bg-rose-600 transition-colors cursor-pointer flex items-center justify-center"
          :title="currentLang === 'vi' ? 'Xoá dự án' : 'Delete project'"
          :aria-label="`${currentLang === 'vi' ? 'Xoá' : 'Delete'} ${project.project_name}`"
          @click.stop="archiveProject(project)"
        >
          <span class="lucide-trash-2 size-3.5" />
        </button>
        <div>
          <!-- Thumbnail via MediaThumbnail Component -->
          <div class="relative aspect-video overflow-hidden bg-surface-muted border-b border-outline-border">
            <MediaThumbnail
              :src="project.cover_image"
              :alt="project.project_name"
              aspect="aspect-video"
            />

            <!-- Top Left Status Badge -->
            <div class="absolute top-2.5 left-2.5 z-10">
              <span
                class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider backdrop-blur-md shadow-xs border"
                :class="statusBadgeClass(project.status)"
              >
                <span class="size-1.5 rounded-full" :class="statusDotClass(project.status)" />
                <span>{{ formatStatus(project.status) }}</span>
              </span>
            </div>
          </div>

          <!-- Card Body -->
          <div class="p-4 space-y-2">
            <!-- Project Title -->
            <h3 class="text-sm sm:text-base font-bold text-ink-primary group-hover:text-indigo-400 transition-colors line-clamp-1">
              {{ project.project_name || "Untitled Project" }}
            </h3>

            <!-- Product Tag -->
            <div v-if="project.product_name" class="flex items-center gap-1.5 text-xs text-ink-secondary">
              <span>🏷️</span>
              <span class="font-medium truncate">{{ project.product_name }}</span>
            </div>

            <!-- Video Idea snippet -->
            <p v-if="project.video_idea" class="text-xs text-ink-muted line-clamp-2 leading-relaxed pt-0.5">
              {{ project.video_idea }}
            </p>
            <p v-else class="text-xs text-ink-muted italic pt-0.5">
              {{ currentLang === 'vi' ? 'Bấm để mở Studio và sản xuất video với AI.' : 'Click to launch studio and produce video with AI.' }}
            </p>
          </div>
        </div>

        <!-- Card Footer -->
        <div class="px-4 py-3 bg-surface-muted/40 border-t border-outline-border flex items-center justify-between text-xs">
          <span class="text-ink-muted font-mono text-[11px] flex items-center gap-1">
            <span>📎</span>
            <span>{{ project.asset_count || 0 }} {{ currentLang === 'vi' ? 'tư liệu' : 'references' }}</span>
          </span>

          <span class="text-xs font-semibold text-indigo-400 group-hover:text-indigo-300 flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
            <span>{{ currentLang === 'vi' ? 'Mở Studio' : 'Open Studio' }}</span>
            <span>→</span>
          </span>
        </div>
      </article>
    </div>

    <!-- 5. Empty State -->
    <div v-else class="py-16 text-center text-xs text-ink-muted p-8 rounded-2xl bg-surface-card border border-outline-border space-y-3">
      <span class="text-4xl block mb-2 opacity-50">🎬</span>
      <h3 class="text-base font-bold text-ink-primary">
        {{ currentLang === 'vi' ? 'Chưa có dự án video nào' : 'No projects found' }}
      </h3>
      <p class="max-w-md mx-auto text-xs text-ink-muted">
        {{ currentLang === 'vi' ? 'Tạo dự án video đầu tiên để tải lên hình ảnh sản phẩm và sản xuất video quảng cáo tự động.' : 'Create your first project to upload product references and generate video ads automatically.' }}
      </p>
      <button
        type="button"
        class="jm-btn-primary !py-2 !px-4 text-xs font-bold shadow-md cursor-pointer"
        :disabled="creatingProject"
        @click="handleNewProject"
      >
        <span v-if="creatingProject" class="lucide-refresh-cw size-3.5 animate-spin mr-1 inline-block" />
        <span>+ {{ currentLang === 'vi' ? 'Tạo dự án mới' : 'Create New Project' }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { call, createResource } from "frappe-ui";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";
import { useI18n } from "../stores/i18n";
import MediaThumbnail from "../components/MediaThumbnail.vue";

const { currentLang } = useI18n();
const router = useRouter();

const statusFilter = ref("all");
const searchQuery = ref("");
const creatingProject = ref(false);

const projectsResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_project_cards",
  auto: true,
});

const projectsList = computed(() => projectsResource.data?.items || []);
const projectTotal = computed(() => projectsResource.data?.total || 0);
const projectCounts = computed(() => projectsResource.data?.counts_by_status || {});

function countByStatus(status) {
  return projectCounts.value[status] || 0;
}

const filteredProjects = computed(() => projectsList.value);
watch([searchQuery, statusFilter], () => {
  projectsResource.fetch({
    search: searchQuery.value,
    status: statusFilter.value === "all" ? null : statusFilter.value,
    start: 0,
    page_length: 24,
  });
});

function openStudio(projectName) {
  router.push(`/projects/${projectName}`);
}

async function handleNewProject() {
  if (creatingProject.value) return;
  creatingProject.value = true;
  try {
    const created = await call("joymedia.joymedia.doctype.media_project.media_project.create_project", {
      project_name: currentLang.value === "vi" ? "Dự án mới" : "Untitled Project",
      product_name: "",
      video_idea: null,
    });
    const targetName = created?.name || created?.project;
    if (targetName) {
      router.push(`/projects/${targetName}`);
    } else {
      await projectsResource.fetch();
    }
  } catch (err) {
    notify({
      title: "Error",
      text: errorMessage(err, "Failed to create project."),
      type: "error",
    });
  } finally {
    creatingProject.value = false;
  }
}

async function archiveProject(project) {
  const vi = currentLang.value === "vi";
  // Deleting archives the project: it disappears for everyone but an administrator can restore it.
  const confirmed = window.confirm(
    vi
      ? `Xoá dự án “${project.project_name}”? Dự án sẽ không còn hiện trong danh sách.`
      : `Delete “${project.project_name}”? It will no longer appear in your projects.`
  );
  if (!confirmed) return;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.archive_project", {
      project_name: project.name,
    });
    notify({
      title: vi ? "Đã xoá dự án" : "Project deleted",
      text: project.project_name,
      type: "success",
    });
    await projectsResource.reload();
  } catch (err) {
    notify({
      title: vi ? "Không thể xoá dự án" : "Could not delete the project",
      text: errorMessage(err, ""),
      type: "error",
    });
  }
}

function formatStatus(status) {
  const s = status || "Draft";
  if (currentLang.value === "vi") {
    if (s === "Draft") return "Bản nháp";
    if (s === "Generating") return "Đang tạo";
    if (s === "Completed") return "Hoàn thành";
    if (s === "Needs Attention") return "Cần chú ý";
  }
  return s;
}

function statusBadgeClass(status) {
  if (status === "Generating") return "bg-indigo-600/90 text-white border-indigo-500";
  if (status === "Completed") return "bg-emerald-600/90 text-white border-emerald-500";
  if (status === "Needs Attention") return "bg-rose-600/90 text-white border-rose-500";
  return "bg-black/60 text-white/90 border-white/20";
}

function statusDotClass(status) {
  if (status === "Generating") return "bg-amber-300 animate-pulse";
  if (status === "Completed") return "bg-emerald-300";
  if (status === "Needs Attention") return "bg-rose-300";
  return "bg-zinc-400";
}
</script>

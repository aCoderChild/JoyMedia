<template>
  <main v-if="access.role==='unassigned'" class="jm-gallery" data-test="access-unassigned"><h1>{{ currentLang==='vi'?'Chưa được cấp quyền':'Access not assigned' }}</h1><p>{{ currentLang==='vi'?'Liên hệ quản trị viên để được cấp vai trò phù hợp.':'Contact your administrator to assign your account a role.' }}</p></main>
  <PartnerReviewHome v-else-if="access.reviewer" />
  <main v-else class="jm-gallery" data-test="client-projects">
    <header class="jm-gallery-heading">
      <div><h1 class="text-2xl font-bold text-ink-primary">{{ currentLang==='vi'?'Video của bạn':'Your videos' }}</h1>
        <p class="mt-2 text-sm text-ink-secondary">{{ currentLang==='vi'?'Thêm sản phẩm và ý tưởng. Duyệt cảnh, rồi xem video.':'Add your product and idea. Review the scenes, then watch your video.' }}</p></div>
      <div v-if="access.can_manage_reviewers" class="flex flex-wrap gap-4 text-sm text-indigo-500"><a href="/app/partner-access" class="underline">{{ currentLang==='vi'?'Quản lý người duyệt':'Manage reviewers' }}</a><a href="/app/video-review-feedback" class="underline">{{ currentLang==='vi'?'Phản hồi video':'Review reports' }}</a></div>
      <button v-if="access.can_create" class="jm-button-primary" @click="handleNewProject">+ {{ currentLang==='vi'?'Tạo video':'Create video' }}</button>
    </header>
    <p v-if="access.administrator || access.role==='production'" class="jm-access-summary" data-test="role-purpose">{{ access.administrator ? (currentLang==='vi'?'Quản trị: quản lý người duyệt, phiên bản chia sẻ và phản hồi.':'Administration: manage reviewers, shared versions and feedback.') : access.role==='production' ? (currentLang==='vi'?'Sản xuất: tạo video và sử dụng trình chỉnh sửa nâng cao.':'Production: create videos and use the advanced editor.') : (currentLang==='vi'?'Thêm sản phẩm → duyệt cảnh → xem và góp ý video của bạn.':'Add your product → review scenes → watch and comment on your video.') }}</p>
    <div class="jm-gallery-toolbar">
      <label class="jm-search"><span aria-hidden="true">⌕</span><input v-model="searchQuery" type="search" :aria-label="currentLang==='vi'?'Tìm video':'Search videos'" :placeholder="currentLang==='vi'?'Tìm video…':'Search videos…'" /></label>
      <div class="jm-view-switch" role="group" :aria-label="currentLang==='vi'?'Kiểu hiển thị':'Gallery layout'"><button type="button" :aria-pressed="galleryView==='grid'" @click="galleryView='grid'">{{ currentLang==='vi'?'Lưới':'Grid' }}</button><button type="button" :aria-pressed="galleryView==='list'" @click="galleryView='list'">{{ currentLang==='vi'?'Danh sách':'List' }}</button></div>
      <button class="jm-archive-filter text-xs text-ink-secondary" @click="statusFilter=statusFilter==='Archived'?'all':'Archived'">{{ statusFilter==='Archived' ? (currentLang==='vi'?'← Quay lại video':'← Back to videos') : (currentLang==='vi'?'Đã lưu trữ':'Archived') }}</button>
    </div>
    <p v-if="projectsResource.loading&&!projectsList.length" role="status">{{ currentLang==='vi'?'Đang tải…':'Loading…' }}</p>
    <p v-else-if="projectsResource.error" role="alert">{{ currentLang==='vi'?'Không tải được video.':'Could not load your videos.' }} <button class="underline" @click="projectsResource.reload()">{{ currentLang==='vi'?'Thử lại':'Try again' }}</button></p>
    <div v-else-if="filteredProjects.length" class="jm-media-grid" :class="{'is-list':galleryView==='list'}" :aria-busy="projectsResource.loading">
      <article v-for="project in filteredProjects" :key="project.name" :data-project="project.name" class="jm-media-card">
        <button class="jm-project-open w-full block text-left" :disabled="projectsResource.loading" @click="openStudio(project.open_project || project.name)">
          <MediaThumbnail :src="project.cover_image" :alt="project.project_name" aspect="aspect-video" contain />
          <div class="jm-project-copy p-4 space-y-2"><h2 class="font-semibold text-ink-primary line-clamp-2">{{ project.project_name }}</h2>
            <p class="text-xs text-ink-secondary">{{ project.status==='Archived' ? (currentLang==='vi'?'Đã lưu trữ · chỉ xem':'Archived · view only') : project.status==='Generating' ? (currentLang==='vi'?'Đang tạo video…':'Making your video…') : project.has_video ? (currentLang==='vi'?'Có video để xem':'Video available to watch') : (currentLang==='vi'?'Tiếp tục tạo video':'Continue creating your video') }}</p>
            <span class="inline-block pt-2 text-sm font-semibold text-indigo-500">{{ currentLang==='vi'?'Mở video →':'Open video →' }}</span>
          </div>
        </button>
        <details class="border-t border-outline-border px-4 py-2 text-xs" @click.stop>
          <summary class="cursor-pointer text-ink-muted">{{ currentLang==='vi'?'Thêm':'More' }}</summary>
          <div class="flex flex-wrap gap-4 py-3">
            <button data-test="card-history" class="text-indigo-500" @click="historyProject=project.name">{{ currentLang==='vi'?'Lịch sử phiên bản':'Version history' }}</button>
            <button :aria-label="`${statusFilter==='Archived'?'Restore':'Archive'} ${project.project_name}`" @click="statusFilter==='Archived'?restoreProject(project):archiveProject(project)">{{ statusFilter==='Archived'?(currentLang==='vi'?'Khôi phục':'Restore'):(currentLang==='vi'?'Lưu trữ':'Archive') }}</button>
          </div>
        </details>
      </article>
    </div>
    <p v-else class="jm-empty-library">{{ currentLang==='vi'?'Chưa có video trong mục này.':'No videos here yet.' }}</p>
    <button v-if="projectsList.length<projectTotal" class="jm-button-secondary self-center" :disabled="projectsResource.loading" @click="projectsResource.more()">{{ currentLang==='vi'?'Xem thêm video':'Load more videos' }}</button>
  </main>
  <NewProjectDialog v-model="showNewProject" @created="onProjectCreated" />
  <ProjectHistory @review="version=>{const name=historyProject;historyProject='';router.push({path:'/projects/'+name,query:{review:version}});}" v-if="historyProject" :project="historyProject" :current-lang="currentLang" :simple="true" @close="historyProject=''" @changed="projectsResource.reload()" @open="name => {historyProject='';openStudio(name);}" />
</template>

<script setup>
import PartnerReviewHome from "../components/studio/PartnerReviewHome.vue";
import {useSession} from "../stores/session";
import {useLibraryCollection} from "../composables/useLibraryCollection";
import {useGalleryView} from "../composables/useGalleryView";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { call } from "frappe-ui";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";
import { useI18n } from "../stores/i18n";
import MediaThumbnail from "../components/MediaThumbnail.vue";
import NewProjectDialog from "../components/NewProjectDialog.vue";
import ProjectHistory from "../components/studio/ProjectHistory.vue";

const { currentLang } = useI18n();
const router = useRouter();
const {access}=useSession();

const statusFilter = ref("all");
const searchQuery = ref("");
const creatingProject = ref(false);
const showNewProject = ref(false);
const historyProject = ref('');

const projectsResource = useLibraryCollection("joymedia.api.projects.get_project_cards", !access.value.reviewer && access.value.role!=='unassigned');
const galleryView=useGalleryView('joymedia_project_gallery');

const projectsList = computed(() => projectsResource.data?.items || []);
const projectTotal = computed(() => projectsResource.data?.total || 0);

const filteredProjects = computed(() => projectsList.value);
let searchTimer;
watch([searchQuery,statusFilter],([search,status],previous)=>{
  clearTimeout(searchTimer);
  projectsResource.invalidate();
  searchTimer=setTimeout(()=>projectsResource.fetch({search,status:status==='all'?null:status,start:0,page_length:24}),previous?.[1]===status?180:0);
});
onBeforeUnmount(()=>clearTimeout(searchTimer));

function openStudio(projectName) {
  router.push(`/projects/${projectName}`);
}

function handleNewProject() {
  showNewProject.value = true;
}

function onProjectCreated(name) {
  router.push(`/projects/${name}`);
}

async function archiveProject(project) {
  const vi = currentLang.value === "vi";
  // Deleting archives the project: it disappears for everyone but an administrator can restore it.
  const confirmed = window.confirm(
    vi
      ? `Lưu trữ “${project.project_name}”? Video và lịch sử vẫn được giữ, bạn có thể khôi phục sau.`
      : `Archive “${project.project_name}”? Videos and history are kept. You can restore it later.`
  );
  if (!confirmed) return;
  try {
    await call("joymedia.api.projects.archive_project", {
      project_name: project.name,
    });
    notify({
      title: vi ? "Đã lưu trữ" : "Project archived",
      text: project.project_name,
      type: "success",
    });
    await projectsResource.reload();
  } catch (err) {
    notify({
      title: vi ? "Không thể lưu trữ" : "Could not archive the project",
      text: errorMessage(err, ""),
      type: "error",
    });
  }
}

async function restoreProject(project) {
  try { await call('joymedia.api.projects.restore_project', {project_name:project.name}); await projectsResource.reload(); }
  catch(error) { notify({title:'Error',text:errorMessage(error,'Could not restore project'),type:'error'}); }
}

</script>

<template>
  <main v-if="access.role==='unassigned'" class="jm-gallery" data-test="access-unassigned"><h1>{{ currentLang==='vi'?'Chưa được cấp quyền':'Access not assigned' }}</h1><p>{{ currentLang==='vi'?'Liên hệ quản trị viên để được cấp vai trò phù hợp.':'Contact your administrator to assign your account a role.' }}</p></main>
  <PartnerReviewHome v-else-if="access.reviewer" />
  <main v-else class="jm-gallery" data-test="client-projects">
    <header class="jm-gallery-heading">
      <div><h1 class="text-2xl font-bold text-ink-primary">{{ currentLang==='vi'?'Video của bạn':'Your videos' }}</h1>
        <p class="mt-2 text-sm text-ink-secondary">{{ currentLang==='vi'?'Thêm sản phẩm và ý tưởng. Duyệt cảnh, rồi xem video.':'Add your product and idea. Review the scenes, then watch your video.' }}</p></div>
      <div v-if="access.can_manage_reviewers" class="flex flex-wrap gap-4 text-sm text-rio-500"><a href="/app/partner-access" class="underline">{{ currentLang==='vi'?'Quản lý người duyệt':'Manage reviewers' }}</a><a href="/app/video-review-feedback" class="underline">{{ currentLang==='vi'?'Phản hồi video':'Review reports' }}</a></div>
      <button v-if="access.can_create" class="jm-button-primary" @click="handleNewProject">+ {{ currentLang==='vi'?'Tạo video':'Create video' }}</button>
    </header>
    <p v-if="access.administrator || access.role==='production'" class="jm-access-summary" data-test="role-purpose">{{ access.administrator ? (currentLang==='vi'?'Quản trị: quản lý người duyệt, phiên bản chia sẻ và phản hồi.':'Administration: manage reviewers, shared versions and feedback.') : access.role==='production' ? (currentLang==='vi'?'Sản xuất: tạo video và sử dụng trình chỉnh sửa nâng cao.':'Production: create videos and use the advanced editor.') : (currentLang==='vi'?'Thêm sản phẩm → duyệt cảnh → xem và góp ý video của bạn.':'Add your product → review scenes → watch and comment on your video.') }}</p>
    <div class="jm-gallery-toolbar">
      <label class="jm-search"><span aria-hidden="true">⌕</span><input v-model="searchQuery" type="search" :aria-label="currentLang==='vi'?'Tìm video':'Search videos'" :placeholder="currentLang==='vi'?'Tìm video…':'Search videos…'" /></label>
      <div class="jm-view-switch" role="group" :aria-label="currentLang==='vi'?'Kiểu hiển thị':'Gallery layout'"><button type="button" :aria-pressed="galleryView==='grid'" @click="galleryView='grid'">{{ currentLang==='vi'?'Lưới':'Grid' }}</button><button type="button" :aria-pressed="galleryView==='list'" @click="galleryView='list'">{{ currentLang==='vi'?'Danh sách':'List' }}</button></div>
      <button class="jm-archive-filter text-xs text-ink-secondary" @click="statusFilter=statusFilter==='Archived'?'all':'Archived'">{{ statusFilter==='Archived' ? (currentLang==='vi'?'← Quay lại video':'← Back to videos') : (currentLang==='vi'?'🗑 Thùng rác':'🗑 Trash') }}</button>
    </div>
    <p v-if="projectsResource.loading && projectsList.length" class="text-xs text-ink-secondary" role="status">{{ currentLang==='vi'?'Đang cập nhật danh sách…':'Updating the list…' }}</p>
    <p v-if="statusFilter==='Archived'" class="text-sm text-ink-secondary" data-test="trash-note">{{ currentLang==='vi'?'Video trong thùng rác sẽ tự xóa vĩnh viễn sau 30 ngày. Bạn có thể khôi phục trước khi hết hạn.':'Videos in the trash are deleted for good after 30 days. You can restore them before then.' }}</p>
    <p v-if="projectsResource.loading&&!projectsList.length" role="status">{{ currentLang==='vi'?'Đang tải…':'Loading…' }}</p>
    <p v-else-if="projectsResource.error" role="alert">{{ currentLang==='vi'?'Không tải được video.':'Could not load your videos.' }} <button class="underline" @click="projectsResource.reload()">{{ currentLang==='vi'?'Thử lại':'Try again' }}</button></p>
    <div v-else-if="filteredProjects.length" class="jm-media-grid" :class="{'is-list':galleryView==='list'}" :aria-busy="projectsResource.loading">
      <article v-for="project in filteredProjects" :key="project.name" :data-project="project.name" class="jm-media-card">
        <button class="jm-project-open w-full block text-left" :disabled="projectsResource.loading" @click="openStudio(project.open_project || project.name)">
          <MediaThumbnail :src="project.cover_image" :alt="project.project_name" aspect="aspect-video" contain />
          <div class="jm-project-copy p-4 space-y-2"><h2 class="font-semibold text-ink-primary line-clamp-2">{{ project.project_name || (currentLang==='vi'?'Một video':'A video') }}</h2>
            <p v-if="duplicateNames.has((project.project_name || '').trim().toLocaleLowerCase())" class="text-xs text-ink-secondary">{{ currentLang==='vi'?'Mã dự án':'Project ID' }}: {{ project.name }}</p>
            <p v-if="project.in_project" class="text-xs text-ink-secondary">{{ currentLang==='vi'?`Video trong “${project.in_project}”`:`Video in “${project.in_project}”` }}</p>
            <p v-if="project.status==='Archived'" class="text-xs" :class="project.days_left<=3?'text-rose-600 dark:text-rose-300':'text-ink-secondary'">{{ daysLeftText(project) }}</p>
            <div v-else class="flex flex-wrap gap-1.5 text-[11px]" data-test="video-states">
			  <span v-if="project.videos_attention" class="rounded-full bg-rose-100 px-2 py-0.5 text-rose-900 dark:bg-rose-900/40 dark:text-rose-200">{{ project.videos_attention }} {{ currentLang==='vi'?'cần xử lý':'need attention' }}</span>
              <span v-if="project.videos_waiting" class="rounded-full bg-amber-100 px-2 py-0.5 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200">{{ project.videos_waiting }} {{ currentLang==='vi'?'chờ bạn xem':'waiting for you' }}</span>
              <span v-if="project.videos_ready" class="rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200">{{ project.videos_ready }} {{ currentLang==='vi'?'sẵn sàng xem':'ready to watch' }}</span>
              <span v-if="project.videos_working" class="rounded-full bg-rio-100 px-2 py-0.5 text-rio-800 dark:bg-rio-900/40 dark:text-rio-200">{{ project.videos_working }} {{ currentLang==='vi'?'đang làm':'in progress' }}</span>
              <span v-if="!project.videos_attention && !project.videos_waiting && !project.videos_ready && !project.videos_working" class="text-ink-secondary">{{ project.has_video ? (currentLang==='vi'?'Có video để xem':'Video available to watch') : (currentLang==='vi'?'Chưa có video':'No video yet') }}</span>
            </div>
            <span class="inline-block pt-2 text-sm font-semibold text-rio-500">{{ project.video_count > 1 ? (currentLang==='vi'?'Xem các phiên bản →':'See versions →') : project.has_video ? (currentLang==='vi'?'Xem video →':'Watch video →') : (currentLang==='vi'?'Mở dự án →':'Open project →') }}</span>
          </div>
        </button>
        <div class="flex justify-end gap-4 border-t border-outline-border px-4 py-2 text-xs" @click.stop>
          <template v-if="statusFilter==='Archived'">
            <button class="font-semibold text-rio-500 hover:underline" :aria-label="`Restore ${project.project_name}`" @click="restoreProject(project)">{{ currentLang==='vi'?'Khôi phục':'Restore' }}</button>
            <button class="text-rose-600 hover:underline dark:text-rose-300" data-test="delete-forever" :aria-label="`Delete ${project.project_name} forever`" @click="deleteForever(project)">{{ currentLang==='vi'?'Xóa vĩnh viễn':'Delete forever' }}</button>
          </template>
          <button v-if="statusFilter!=='Archived' && access.can_create" type="button" class="font-semibold text-rio-500 hover:underline" data-test="create-another-video" @click="newVideoProject=project">{{ currentLang==='vi'?'Tạo video khác':'Create another video' }}</button>
          <button v-if="statusFilter!=='Archived'" class="text-ink-secondary hover:text-ink-primary" :aria-label="currentLang==='vi'?`Chuyển ${project.project_name} vào thùng rác`:`Move ${project.project_name} to trash`" @click="archiveProject(project)">{{ currentLang==='vi'?'Chuyển vào thùng rác':'Move to trash' }}</button>
        </div>
      </article>
    </div>
    <div v-else class="jm-empty-library">
      <p>{{ searchQuery.trim() ? (currentLang==='vi'?'Không tìm thấy dự án phù hợp.':'No matching projects found.') : statusFilter==='Archived' ? (currentLang==='vi'?'Thùng rác trống.':'The trash is empty.') : (currentLang==='vi'?'Chưa có video trong mục này.':'No videos here yet.') }}</p>
      <button v-if="searchQuery.trim()" type="button" class="jm-button-secondary" @click="searchQuery=''">{{ currentLang==='vi'?'Xóa từ khóa tìm kiếm':'Clear search' }}</button>
      <button v-else-if="statusFilter!=='Archived' && access.can_create" type="button" class="jm-button-primary" @click="handleNewProject">{{ currentLang==='vi'?'Tạo video đầu tiên':'Create your first video' }}</button>
    </div>
    <button v-if="projectsList.length<projectTotal" class="jm-button-secondary self-center" :disabled="projectsResource.loading" @click="projectsResource.more()">{{ currentLang==='vi'?'Xem thêm video':'Load more videos' }}</button>
  </main>
  <NewProjectDialog v-model="showNewProject" @created="onProjectCreated" />
  <CreateProjectVideoDialog v-if="newVideoProject" :project="newVideoProject" @close="newVideoProject=null" @started="projectsResource.reload()" @created="openCreatedVideo" />
</template>

<script setup>
import PartnerReviewHome from "../components/studio/PartnerReviewHome.vue";
import {useSession} from "../stores/session";
import {useLibraryCollection} from "../composables/useLibraryCollection";
import {useGalleryView} from "../composables/useGalleryView";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { call } from "frappe-ui";
import { rioConfirm } from "../utils/rioDialog";
import { notify } from "../utils/notify";
import { errorMessage } from "../utils/errors";
import { useI18n } from "../stores/i18n";
import MediaThumbnail from "../components/MediaThumbnail.vue";
import NewProjectDialog from "../components/NewProjectDialog.vue";
import CreateProjectVideoDialog from "../components/CreateProjectVideoDialog.vue";

const { currentLang } = useI18n();
const router = useRouter();
const route = useRoute();
const {access}=useSession();

// The trash is part of the address, so the sidebar link and the browser's Back button leave it.
const statusFilter = computed({
  get: () => (route.query.view === "trash" ? "Archived" : "all"),
  set: (value) => router.push({ path: "/projects", query: value === "Archived" ? { view: "trash" } : {} }),
});
const searchQuery = ref("");
const creatingProject = ref(false);
const showNewProject = ref(false);
const newVideoProject = ref(null);
function openCreatedVideo(name) { newVideoProject.value = null; router.push(`/projects/${name}`); }

const projectsResource = useLibraryCollection("joymedia.api.projects.get_project_cards", !access.value.reviewer && access.value.role!=='unassigned');
const galleryView=useGalleryView('joymedia_project_gallery');

const projectsList = computed(() => projectsResource.data?.items || []);
const duplicateNames = computed(() => {
  const counts = new Map();
  for (const project of projectsList.value) {
    const name = (project.project_name || '').trim().toLocaleLowerCase();
    if (name) counts.set(name, (counts.get(name) || 0) + 1);
  }
  return new Set([...counts].filter(([, count]) => count > 1).map(([name]) => name));
});
const projectTotal = computed(() => projectsResource.data?.total || 0);

const filteredProjects = computed(() => projectsList.value);
let searchTimer;
watch([searchQuery,statusFilter],([search,status],previous)=>{
  clearTimeout(searchTimer);
  projectsResource.invalidate();
  if (previous?.[1] !== status) projectsResource.data = null;
  searchTimer=setTimeout(()=>projectsResource.fetch({search,status:status==='all'?null:status,start:0,page_length:24}),previous?.[1]===status?180:0);
});
onBeforeUnmount(()=>clearTimeout(searchTimer));
if (statusFilter.value === "Archived") projectsResource.fetch({ status: "Archived", start: 0, page_length: 24 });

function openStudio(projectName) {
  router.push(`/projects/${projectName}`);
}

function handleNewProject() {
  showNewProject.value = true;
}

function onProjectCreated(name) {
  router.push(`/projects/${name}`);
}

const daysLeftText = (project) => {
  const days = project.days_left ?? 30;
  if (currentLang.value === 'vi') return days ? `Tự xóa sau ${days} ngày · chỉ xem` : 'Sẽ bị xóa hôm nay';
  return days ? `Deleted for good in ${days} day${days === 1 ? '' : 's'} · view only` : 'Will be deleted today';
};

// Deleting moves the project to the trash, like a file manager: restorable for 30 days.
async function archiveProject(project) {
  const vi = currentLang.value === "vi";
  const confirmed = await rioConfirm(
    vi
      ? `Chuyển “${project.project_name}” vào thùng rác? Bạn có thể khôi phục trong 30 ngày, sau đó sẽ bị xóa vĩnh viễn.`
      : `Move “${project.project_name}” to the trash? You can restore it within 30 days; after that it is deleted for good.`
  );
  if (!confirmed) return;
  try {
    await call("joymedia.api.projects.archive_project", {
      project_name: project.name,
    });
    notify({
      title: vi ? "Đã chuyển vào thùng rác" : "Moved to the trash",
      text: project.project_name,
      type: "success",
    });
    await projectsResource.reload();
  } catch (err) {
    notify({
      title: vi ? "Không thể xóa" : "Could not delete the project",
      text: errorMessage(err, ""),
      type: "error",
    });
  }
}

async function restoreProject(project) {
  const vi = currentLang.value === "vi";
  try {
    await call('joymedia.api.projects.restore_project', {project_name:project.name});
    notify({title: vi ? 'Đã khôi phục' : 'Restored', text: project.project_name || project.in_project, type: 'success'});
    await projectsResource.reload();
  }
  catch(error) { notify({title: vi ? 'Không thể khôi phục' : 'Could not restore', text:errorMessage(error,''),type:'error'}); }
}

async function deleteForever(project) {
  const vi = currentLang.value === "vi";
  const name = project.project_name || project.in_project;
  const others = project.in_project ? 0 : Math.max(0, (project.video_count || 1) - 1);
  const confirmed = await rioConfirm(
    vi
      ? `Xóa vĩnh viễn “${name}”${others ? ` cùng ${others} video bên trong` : ''}? Không thể hoàn tác.`
      : `Delete “${name}”${others ? ` and the ${others} videos inside it` : ''} forever? This cannot be undone.`
  );
  if (!confirmed) return;
  try {
    await call('joymedia.api.projects.delete_project_forever', {project_name: project.name});
    notify({title: vi ? 'Đã xóa vĩnh viễn' : 'Deleted for good', text: name, type: 'success'});
    await projectsResource.reload();
  } catch (error) {
    notify({title: vi ? 'Không thể xóa' : 'Could not delete', text: errorMessage(error, ''), type: 'error'});
  }
}

</script>

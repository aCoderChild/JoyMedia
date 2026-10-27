<template>
  <main class="jm-gallery" data-test="partner-home">
    <header class="jm-gallery-heading"><div><h1 class="text-2xl font-bold">{{ t('Partner review','Duyệt video đối tác') }}</h1><p class="text-sm text-ink-secondary mt-2">{{ t('Watch the versions shared with you and tell us what needs improving.','Xem các phiên bản được chia sẻ và góp ý những chi tiết cần cải thiện.') }}</p></div></header>
    <p v-if="access.enabled" class="jm-access-summary" data-test="reviewer-access-summary">{{ access.allow_generation ? t('Review shared videos · Test creation enabled for your own projects','Duyệt video được chia sẻ · Được phép tạo dự án thử riêng') : t('Review shared videos · Video creation is disabled','Duyệt video được chia sẻ · Không có quyền tạo video') }}{{ access.allow_feedback ? t(' · Comments enabled',' · Có thể góp ý') : t(' · Viewing only',' · Chỉ xem') }}</p>
    <p v-if="!access.enabled" class="text-sm">{{ t('Your access is not enabled. Contact your administrator.','Quyền truy cập chưa được bật. Vui lòng liên hệ quản trị viên.') }}</p>
    <template v-else>
      <p v-if="library.error" role="alert">{{ t('Could not load your shared videos.','Không tải được video chia sẻ.') }} <button class="underline" @click="library.reload()">{{ t('Try again','Thử lại') }}</button></p>
      <p v-else-if="library.loading" role="status">{{ t('Loading…','Đang tải…') }}</p>
      <p v-else-if="!library.data?.items?.length" class="text-sm text-ink-muted">{{ t('No videos have been shared with you yet.','Chưa có video nào được chia sẻ với bạn.') }}</p>
      <div v-if="library.data?.items?.length" class="jm-gallery-toolbar"><label class="jm-search"><span aria-hidden="true">⌕</span><input v-model="search" type="search" :aria-label="t('Search shared videos','Tìm video chia sẻ')" :placeholder="t('Search shared videos…','Tìm video chia sẻ…')" /></label><div class="jm-view-switch" role="group" :aria-label="t('Gallery layout','Kiểu hiển thị')"><button :aria-pressed="galleryView==='grid'" @click="galleryView='grid'">{{ t('Grid','Lưới') }}</button><button :aria-pressed="galleryView==='list'" @click="galleryView='list'">{{ t('List','Danh sách') }}</button></div></div>
      <p v-if="search&&!filteredVideos.length" class="jm-empty-library">{{ t('No shared videos match your search.','Không tìm thấy video chia sẻ phù hợp.') }}</p>
      <div class="jm-media-grid jm-partner-grid" :class="{'is-list':galleryView==='list'}">
        <article v-for="item in filteredVideos" :key="item.asset_version" :data-published-version="item.asset_version" class="jm-media-card">
          <video :src="item.file" controls playsinline preload="metadata" @play="playback.play" />
          <div class="p-4 space-y-3"><h2 class="font-semibold">{{ item.title }}</h2><div class="flex gap-4 items-center"><button class="jm-button-primary" @click="openReview(item)">{{ library.data.allow_feedback?t('Review & comment','Duyệt và góp ý'):t('Watch video','Xem video') }}</button><a v-if="item.download_url" :href="item.download_url" download class="text-sm underline">{{ t('Download','Tải xuống') }}</a></div></div>
        </article>
      </div>
      <section v-if="access.allow_generation" class="jm-sandbox" data-test="partner-generation">
        <h2 class="text-lg font-bold">{{ t('Try creating a video','Thử tạo video') }}</h2><p class="text-sm text-ink-secondary">{{ t('Test with your own images and brief. Shared administrator videos stay unchanged.','Thử với hình ảnh và ý tưởng của bạn. Video do quản trị viên chia sẻ được giữ nguyên.') }}</p>
        <button class="jm-button-secondary self-start" @click="creating=true">+ {{ t('Create test video','Tạo video thử nghiệm') }}</button>
        <div v-for="item in projects.data?.items || []" :key="item.name" class="text-sm"><button class="underline text-rio-500" @click="router.push(`/projects/${item.open_project || item.name}`)">{{ item.project_name }} →</button></div>
      </section>
    </template>
    <NewProjectDialog v-if="access.allow_generation" v-model="creating" @created="name=>router.push(`/projects/${name}`)" />
    <VideoReviewDialog v-if="review" :key="review.asset_version" :project="review.project" :asset-version="review.asset_version" @close="review=null" />
  </main>
</template>
<script setup>
import {computed,ref} from 'vue';
import {usePreviewPlayback} from '../../composables/usePreviewPlayback';
import {useGalleryView} from '../../composables/useGalleryView';
import {useRouter} from 'vue-router';
import {createResource} from 'frappe-ui';
import {useSession} from '../../stores/session';
import {useI18n} from '../../stores/i18n';
import VideoReviewDialog from './VideoReviewDialog.vue';
import NewProjectDialog from '../NewProjectDialog.vue';
const {access}=useSession();
const {currentLang}=useI18n();
const t=(en,vi)=>currentLang.value==='vi'?vi:en;
const router=useRouter(),creating=ref(false),review=ref(null);
const library=createResource({url:'joymedia.services.partners.get_review_library',auto:access.value.enabled});
const search=ref(''),galleryView=useGalleryView('joymedia_partner_gallery');
const playback=usePreviewPlayback();
const filteredVideos=computed(()=>(library.data?.items||[]).filter(item=>item.title.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())));
function openReview(item){playback.pauseAll();review.value=item;}
const projects=createResource({url:'joymedia.api.projects.get_project_cards',auto:access.value.allow_generation});
</script>

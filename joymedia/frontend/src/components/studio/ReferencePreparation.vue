<template>
  <details v-if="plan || bridges?.length" class="rounded-lg border border-outline-border p-3 text-xs" data-test="reference-preparation">
    <summary class="font-semibold">{{ tr('Reference preparation plan', 'Kế hoạch chuẩn bị tham chiếu') }}</summary>
    <div v-if="plan" class="mt-3 space-y-3">
      <p>{{ tr('Script → required subjects, poses, actions, places and product views → qualified references → storyboard.', 'Kịch bản → chủ thể, tư thế, hành động, bối cảnh và góc sản phẩm → tham chiếu đạt kiểm tra → storyboard.') }}</p>
      <article v-for="actor in plan.characters" :key="actor.identity">
        <strong>{{ actor.label || actor.identity }}</strong>
        <p v-for="item in actor.requirements" :key="item.scene">{{ tr('Scene', 'Cảnh') }} {{ item.scene }} · {{ item.support }} · {{ item.opening }}<br>{{ item.action }}</p>
      </article>
      <article v-for="product in plan.products" :key="product.identity">
        <strong>{{ product.label || product.identity }}</strong>
        <p v-for="item in product.requirements" :key="item.scene">{{ tr('Scene', 'Cảnh') }} {{ item.scene }} · {{ item.view }}</p>
      </article>
      <article v-for="room in plan.environments" :key="room.key">
        <strong>{{ room.setting }}</strong>
        <p>{{ tr('Empty environment: no physical cast', 'Bối cảnh trống: không có nhân vật') }}</p>
        <ul><li v-for="(object, index) in room.objects" :key="index">{{ object.kind }} · {{ object.name }} · {{ tr('Scene', 'Cảnh') }} {{ object.scene }}</li></ul>
      </article>
      <div v-if="plan.pose_requirements?.length">
        <strong>{{ tr('Planned body poses', 'Tư thế cơ thể đã lên kế hoạch') }}</strong>
        <p v-for="(pose, index) in plan.pose_requirements" :key="index">{{ tr('Scene', 'Cảnh') }} {{ pose.scene_index + 1 }} · {{ pose.opening_pose }} · {{ pose.view }}</p>
      </div>
      <p class="text-ink-muted">{{ tr('Generated angles remain inferred. Original images own identity and printed artwork. Prepared poses do not certify product contact or a completed action.', 'Góc sinh bởi AI vẫn là suy diễn. Ảnh gốc quyết định danh tính và nhãn in. Tư thế đã chuẩn bị chưa chứng nhận tiếp xúc sản phẩm hoặc hành động hoàn tất.') }}</p>
    </div>
    <div v-if="bridges?.length" class="mt-3 grid grid-cols-2 gap-2">
      <figure v-for="clip in bridges" :key="clip.file_url">
        <video :src="clip.file_url" controls playsinline preload="none" class="max-h-48 w-full rounded bg-black" />
        <figcaption>{{ tr('Preparation candidate · not final footage', 'Ứng viên tham chiếu · không phải video cuối') }}</figcaption>
      </figure>
    </div>
  </details>
</template>
<script setup>
import { tr } from '../../stores/i18n';
defineProps({ plan: Object, bridges: Array });
</script>

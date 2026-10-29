<template>
  <section v-if="registry?.length" class="space-y-3 rounded-lg border border-outline-border p-3" data-test="reference-registry">
    <h3 class="font-semibold">{{ tr('Cast, products & reference views', 'Nhân vật, sản phẩm & góc tham chiếu') }}</h3>
    <p class="text-xs text-ink-muted">{{ tr('Each subject has one identity. Poses and angles are views of that same subject. Empty room plates have no cast.', 'Mỗi chủ thể có một danh tính. Tư thế và góc nhìn thuộc cùng chủ thể đó. Ảnh không gian trống không có nhân vật.') }}</p>
    <article v-for="subject in registry" :key="subject.role + subject.identity" class="rounded border border-outline-border p-2" data-test="registry-subject">
      <div class="flex items-center gap-3">
        <img v-if="subject.original?.file" :src="subject.original.file" :alt="subject.label" class="h-16 w-16 rounded object-contain" />
        <div><strong>{{ subject.label }}</strong><p class="text-xs text-ink-muted">{{ subject.role === 'product' ? tr('Product', 'Sản phẩm') : tr('Character / mascot', 'Nhân vật / linh vật') }} · {{ subject.identity }}</p></div>
      </div>
      <p v-if="subject.appearance" class="mt-2 text-xs">{{ subject.appearance }}</p>
      <ul class="mt-2 space-y-2">
        <li v-for="view in subject.views" :key="view.asset_version" class="flex items-start gap-2 text-xs" data-test="registry-view">
          <img v-if="view.file" :src="view.file" :alt="view.reference_key" class="h-12 w-12 rounded object-contain" />
          <div><strong>{{ view.reference_key }}</strong><p>{{ view.angle === 'source' ? tr('Source view', 'Góc ảnh gốc') : view.angle }}<span v-if="view.pose"> · {{ view.pose }}</span></p><p class="text-ink-muted">{{ statusLabel(view.status) }}</p></div>
        </li>
      </ul>
    </article>
    <details v-if="scenes?.length" data-test="scene-reference-map">
      <summary>{{ tr('Scene reference mapping', 'Ánh xạ tư liệu theo cảnh') }}</summary>
      <ol class="mt-2 space-y-2 text-xs">
        <li v-for="scene in scenes" :key="scene.shot" class="rounded border border-outline-border p-2">
          <strong>{{ tr('Scene', 'Cảnh') }} {{ scene.scene }}</strong>
          <p v-if="scene.error" class="text-rose-500">{{ scene.error }}</p>
          <p v-if="!scene.error && !scene.bindings?.some(b => b.role !== 'product')">{{ tr('No physical cast', 'Không có nhân vật vật lý') }}</p>
          <p v-for="binding in scene.bindings" :key="binding.role + binding.view.asset_version">{{ binding.identity }} → {{ binding.view.reference_key }} · {{ binding.view.angle }}<span v-if="binding.view.pose"> · {{ binding.view.pose }}</span></p>
          <p v-for="pose in scene.requested_poses || []" :key="pose">{{ tr('Required opening pose', 'Tư thế đầu cảnh yêu cầu') }}: {{ pose }}</p>
          <p v-if="scene.requested_product_view">{{ tr('Required product view', 'Góc sản phẩm yêu cầu') }}: {{ scene.requested_product_view }}</p>
        </li>
      </ol>
    </details>
  </section>
</template>

<script setup>
import { tr } from '../../stores/i18n';
defineProps({ registry: Array, scenes: Array });
function statusLabel(status) {
  if (status === 'supplied') return tr('Provided source image', 'Ảnh gốc được cung cấp');
  if (status === 'qualified_pose') return tr('Verified reference pose', 'Tư thế tham chiếu đã xác minh');
  if (status === 'ai_extrapolated_candidate') return tr('Inferred angle — needs verification', 'Góc suy diễn — cần xác minh');
  return tr('Needs verification', 'Cần xác minh');
}
</script>

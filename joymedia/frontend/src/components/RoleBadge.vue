<template>
  <span class="jm-role-badge" :class="{'jm-role-compact':compact}" data-test="account-role" :data-role="access.role" :title="description">{{ label }}</span>
</template>
<script setup>
import {computed} from 'vue';
import {useSession} from '../stores/session';
import {useI18n} from '../stores/i18n';
defineProps({compact:Boolean});
const {access}=useSession(),{currentLang}=useI18n();
const roles={
 administrator:['Administrator','Quản trị viên','Manage access, shared versions and review reports.','Quản lý quyền, phiên bản chia sẻ và phản hồi.'],
 production:['Production team','Đội sản xuất','Create and edit videos with production tools.','Tạo và chỉnh sửa video bằng công cụ sản xuất.'],
 client:['Client','Khách hàng','Create your videos with the guided workspace.','Tạo video của bạn theo các bước hướng dẫn.'],
 reviewer:['Reviewer','Người duyệt','Review only shared versions. Test generation requires administrator access.','Chỉ duyệt phiên bản được chia sẻ. Tạo video thử cần được quản trị viên cho phép.'],
 unassigned:['No role assigned','Chưa có vai trò','Contact your administrator to assign access.','Liên hệ quản trị viên để được cấp quyền.'],
};
const details=computed(()=>roles[access.value.role]||roles.unassigned);
const label=computed(()=>details.value[currentLang.value==='vi'?1:0]);
const description=computed(()=>details.value[currentLang.value==='vi'?3:2]);
</script>

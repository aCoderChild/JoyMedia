import { createApp, h } from 'vue';
import '../../src/style.css';
import { useI18n } from '../../src/stores/i18n';
import CreateProjectVideoDialog from '../../src/components/CreateProjectVideoDialog.vue';
useI18n().currentLang.value = 'vi';
window.fixtureEvents = [];
createApp({ render: () => h(CreateProjectVideoDialog, {
  project: { name: 'root-project', project_name: 'Shera', video_idea: 'Original idea' },
  onCreated: name => window.fixtureEvents.push(`created:${name}`),
  onClose: () => window.fixtureEvents.push('close'),
}) }).mount('#app');

import { createApp, defineComponent, h, ref } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';
import '../../src/style.css';
import RioStudioWorkspace from '../../src/components/studio/RioStudioWorkspace.vue';

const shots = Array.from({ length: 8 }, (_, index) => ({ name: `shot-${index + 1}`, shot_number: index + 1, shot_name: `Cảnh ${index + 1}`, duration_seconds: 2 }));
shots[1].shot_name = 'Gấu nhìn hộp giấy';
shots[1].storyboard_action = 'Gấu nhìn về phía hộp giấy trên bàn.';
shots[1].references = [{ reference_key: 'bear' }, { reference_key: 'pack' }];
const assets = [
  { asset_version: 'bear-version', reference_key: 'bear', label: 'Gấu mẫu', reference_role: 'Character', media_type: 'Image' },
  { asset_version: 'pack-version', reference_key: 'pack', label: 'Hộp giấy mẫu', reference_role: 'Product', media_type: 'Image' },
];
const clips = Array.from({ length: 8 }, (_, index) => ({ name: `clip-${index + 1}`, shot: `shot-${index === 0 ? 8 : index + 1}`, clip_order: index + 1, track_type: 'Video', timeline_start_frame: index * 48, duration_frames: 48, source_in_frame: index === 0 ? 24 : 0, source_file: `/fixture-clip-${index + 1}.mp4` }));
const initialAudioClips = [
  { name: 'voice', track_type: 'Audio', audio_role: 'Voiceover', track_index: 1, timeline_start_frame: 0, duration_frames: 384, enabled: 1 },
  { name: 'effect', track_type: 'Audio', audio_role: 'SFX', track_index: 1, timeline_start_frame: 48, duration_frames: 48, enabled: 1 },
];
window.fixtureEvents = [];
const App = defineComponent({
  setup() {
    const selectedShotIndex = ref(0);
    const audioClips = ref(initialAudioClips);
    return () => h(RioStudioWorkspace, {
      projectName: 'FIXTURE', projectTitle: 'Timeline fixture', projectStatus: 'Completed', currentLang: 'vi',
      shots, clips, audioClips: audioClips.value, selectedShotIndex: selectedShotIndex.value, assets, frames: [],
      timeline: { total_seconds: 16 }, fps: 24, canEdit: true, canWork: true, storyboardApproved: true,
      onSelectShot: (_shot, index) => { selectedShotIndex.value = index; window.fixtureEvents.push(`shot:${index + 1}`); },
      onOpenTimeline: (clip) => window.fixtureEvents.push(`edit:${clip?.name || 'all'}`),
      onAddAudio: (role) => window.fixtureEvents.push(`add:${role}`),
      onToggleAudio: (clip, enabled) => { audioClips.value = audioClips.value.map(item => item.name === clip.name ? { ...item, enabled: Number(enabled) } : item); window.fixtureEvents.push(`toggle:${clip.name}:${enabled}`); },
      onRemoveAudio: (clip) => { audioClips.value = audioClips.value.filter(item => item.name !== clip.name); window.fixtureEvents.push(`remove:${clip.name}`); },
    });
  },
});
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: App }] });
createApp(App).use(router).mount('#app');

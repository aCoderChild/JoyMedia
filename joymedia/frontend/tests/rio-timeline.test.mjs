import assert from 'node:assert/strict';
import test from 'node:test';
import { clipAtSeconds, layoutAudioLanes, orderTimelineClips, shotIndexForClip, sourceSecondsForTimeline } from '../src/utils/rioTimeline.js';

const clips = [
  { name: 'later', shot: 'shot-2', clip_order: 2, timeline_start_frame: 120, duration_frames: 120, source_in_frame: 24 },
  { name: 'first', shot: 'shot-8', clip_order: 1, timeline_start_frame: 0, duration_frames: 120, source_in_frame: 48 },
  { name: 'repeat', shot: 'shot-8', clip_order: 3, timeline_start_frame: 240, duration_frames: 60, source_in_frame: 0 },
];

test('RIO orders the edit by timeline placement while retaining source-scene identity', () => {
  assert.deepEqual(orderTimelineClips(clips).map((clip) => clip.name), ['first', 'later', 'repeat']);
  assert.equal(shotIndexForClip([{ name: 'shot-2' }, { name: 'shot-8' }], clips[1]), 1);
  assert.equal(shotIndexForClip([{ name: 'shot-2' }], clips[1]), -1);
});

test('RIO seek uses timeline placement and source trim', () => {
  assert.equal(clipAtSeconds(clips, 2, 24)?.name, 'first');
  assert.equal(clipAtSeconds(clips, 7, 24)?.name, 'later');
  assert.equal(clipAtSeconds(clips, 11, 24)?.name, 'repeat');
  assert.equal(sourceSecondsForTimeline(clips[0], 6, 24), 2);
  assert.equal(sourceSecondsForTimeline(clips[0], 50, 24), 6);
});

test('overlapping audio stays visible in separate overview lanes', () => {
  const rows = layoutAudioLanes([
    {name:'music',audio_role:'BGM',track_index:1,timeline_start_frame:0,duration_frames:240},
    {name:'voice',audio_role:'Voiceover',track_index:2,timeline_start_frame:0,duration_frames:120},
    {name:'effect',audio_role:'SFX',track_index:3,timeline_start_frame:60,duration_frames:24},
    {name:'next',audio_role:'BGM',track_index:4,timeline_start_frame:240,duration_frames:120},
  ]);
  assert.equal(rows.length,3);
  assert.deepEqual(rows.flatMap(row=>row.clips.map(clip=>clip.name)).sort(),['effect','music','next','voice']);
  assert.deepEqual(rows.find(row=>row.clips[0].name==='music').clips.map(clip=>clip.name),['music','next']);
});

test('sequential voiceovers from different backend tracks share one display line', () => {
  const rows = layoutAudioLanes([
    {name:'voice-1',audio_role:'Voiceover',track_index:1,timeline_start_frame:0,duration_frames:20},
    {name:'voice-2',audio_role:'Voiceover',track_index:2,timeline_start_frame:20,duration_frames:20},
    {name:'voice-3',audio_role:'Voiceover',track_index:3,timeline_start_frame:40,duration_frames:20},
  ]);
  assert.equal(rows.length,1);
  assert.deepEqual(rows[0].clips.map(clip=>clip.name),['voice-1','voice-2','voice-3']);
  assert.deepEqual(rows[0].clips.map(clip=>clip.track_index),[1,2,3]);
});

test('simultaneous voiceovers remain separate and do not obscure each other', () => {
  const rows = layoutAudioLanes([
    {name:'voice-1',audio_role:'Voiceover',track_index:1,timeline_start_frame:0,duration_frames:30},
    {name:'voice-2',audio_role:'Voiceover',track_index:2,timeline_start_frame:20,duration_frames:30},
    {name:'voice-3',audio_role:'Voiceover',track_index:3,timeline_start_frame:50,duration_frames:20},
  ]);
  assert.equal(rows.length,2);
  assert.deepEqual(rows.flatMap(row=>row.clips.map(clip=>clip.name)).sort(),['voice-1','voice-2','voice-3']);
});

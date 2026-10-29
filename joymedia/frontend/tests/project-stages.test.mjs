import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildStages, currentStage } from '../src/utils/projectStages.js';

test('a stopped automatic run displays attention rather than waiting for an idea', () => {
  const stage = currentStage(buildStages({ automatic: {status: 'Needs Attention'}, lang: 'vi' }));
  assert.equal(stage.state, 'attention');
  assert.match(stage.detail, /đã dừng/);
});

test('automatic planning is reported as in progress before shots exist', () => {
  const stage = currentStage(buildStages({ automatic: {status: 'Planning'}, lang: 'vi' }));
  assert.equal(stage.state, 'running');
  assert.match(stage.detail, /kịch bản và tư liệu/);
});

test('an ordinary empty draft still waits for an idea', () => {
  const stage = currentStage(buildStages({ lang: 'vi' }));
  assert.equal(stage.state, 'waiting');
  assert.match(stage.detail, /ý tưởng/);
});

test('a failed first-frame run is reported on scene images, not scene video', () => {
  const stages = buildStages({
    shots: [{}],
    frames: [{ needs_keyframe: true }],
    production: { status: 'Failed', stage: 'keyframe', failed_tasks: 1, total_tasks: 1, error_summary: 'Một tư liệu đã chọn không dùng được cho cảnh này.' },
    lang: 'vi',
  });
  const images = stages.find((stage) => stage.key === 'images');
  const video = stages.find((stage) => stage.key === 'video');
  assert.equal(images.state, 'attention');
  assert.match(images.reason, /tư liệu/);
  assert.equal(video.state, 'waiting');
});

test('preparing poses again shows scene images as in progress, not idle', () => {
  const images = buildStages({ shots: [{}], frames: [{ needs_keyframe: true }], automatic: { status: 'Rewriting' }, lang: 'vi' })
    .find((stage) => stage.key === 'images');
  assert.equal(images.state, 'running');
  assert.match(images.reason, /tư thế nhân vật/);
});

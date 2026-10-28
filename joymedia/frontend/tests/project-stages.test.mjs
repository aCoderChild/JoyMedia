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

const assert = require('node:assert/strict');
const {test} = require('node:test');
const {CameraFreshness} = require('../software/sim/camera_freshness.js');

test('no image is unavailable, not live', () => {
  assert.equal(new CameraFreshness().snapshot(100).state, 'unavailable');
});
test('publication age, transport and time since receipt count toward age', () => {
  const camera = new CameraFreshness();
  camera.accept('8', '100', 1000, 25);
  assert.equal(camera.snapshot(1200).ageMs, 325);
  assert.equal(camera.snapshot(1200).state, 'live');
  assert.equal(camera.snapshot(1400).state, 'stale');
});
test('a failed poll marks even a recent image stale immediately', () => {
  const camera = new CameraFreshness();
  camera.accept('8', '0', 1000, 2);
  camera.fail('HTTP 500');
  assert.equal(camera.snapshot(1001).state, 'stale');
});
test('repeated IDs cannot reset stale age even if source age is wrong', () => {
  const camera = new CameraFreshness();
  camera.accept('8', '0', 1000, 0);
  camera.accept('8', '0', 1600, 0);
  assert.equal(camera.snapshot(1600).state, 'stale');
});
test('a new frame after a process restart can restore freshness', () => {
  const camera = new CameraFreshness();
  camera.accept('80', '700', 1000, 0);
  camera.accept('0', '10', 1100, 0);
  assert.equal(camera.snapshot(1100).state, 'live');
});
test('missing, negative and malformed metadata never certifies a frame', () => {
  for (const [id, age] of [[null, '0'], ['1', null], ['', '0'], ['1', '-1'], ['x', '0']]) {
    const camera = new CameraFreshness();
    camera.accept(id, age, 1000, 0);
    assert.equal(camera.snapshot(1000).state, 'unavailable');
  }
});

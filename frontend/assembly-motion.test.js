import test from 'node:test';
import assert from 'node:assert/strict';
import {sampleTransition} from './assembly-motion.js';

test('generic motion respects intermediate trajectory and time spacing', () => {
  const frame = (t, z, angle) => ({t, motions: [
    {parts: ['slider'], translation_mm: [0, 0, z]},
    {parts: ['wheel'], rotation_deg: [0, 0, angle]},
  ]});
  const transition = {keyframes: [frame(0, 0, 0), frame(.25, -6, 40), frame(1, -3, 60)]};
  const press = sampleTransition(transition, .125);
  assert.deepEqual(press[0].translation_mm, [0, 0, -3]);
  assert.deepEqual(press[1].rotation_deg, [0, 0, 20]);
  assert.equal(sampleTransition(transition, .625)[0].translation_mm[2], -4.5);
  assert.deepEqual(sampleTransition(transition, 2), transition.keyframes[2].motions);
  assert.deepEqual(sampleTransition(transition, -1), transition.keyframes[0].motions);
});

test('scale interpolates about its declared pivot and unrelated tracks cannot merge', () => {
  const start = {parts: ['elastic'], scale_axis: 'z', scale: 1, pivot_mm: [0, 0, 12]};
  const end = {...start, scale: .6};
  const transition = {keyframes: [{t: 0, motions: [start]}, {t: 1, motions: [end]}]};
  assert.equal(sampleTransition(transition, .5)[0].scale, .8);
  assert.deepEqual(sampleTransition(transition, .5)[0].pivot_mm, [0, 0, 12]);
  transition.keyframes[1].motions[0] = {...end, parts: ['different']};
  assert.throws(() => sampleTransition(transition, .5), /same parts/);
});

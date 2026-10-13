// Assembly-local millimeters and degrees. The viewer interpolates supplied
// evidence; it does not solve physics or select a product-specific motion.
export function sampleTransition(transition, progress) {
  const frames = transition.keyframes;
  if (!Array.isArray(frames) || frames.length < 2) throw new Error('A transition needs at least two keyframes');
  const t = Math.max(0, Math.min(1, progress));
  if (t <= frames[0].t) return frames[0].motions;
  if (t >= frames.at(-1).t) return frames.at(-1).motions;
  const right = frames.findIndex(frame => frame.t >= t);
  const a = frames[right - 1], b = frames[right];
  if (!(b.t > a.t) || a.motions.length !== b.motions.length) throw new Error('Incompatible assembly keyframes');
  const fraction = (t - a.t) / (b.t - a.t);
  const mix = (x, y) => x + (y - x) * fraction;
  return a.motions.map((left, index) => {
    const other = b.motions[index];
    if (JSON.stringify(left.parts) !== JSON.stringify(other.parts) || left.scale_axis !== other.scale_axis)
      throw new Error('Assembly keyframes must address the same parts and axes');
    const result = {...left};
    for (const key of ['translation_mm', 'rotation_deg', 'pivot_mm']) {
      if (left[key] || other[key]) {
        const x = left[key] || [0, 0, 0], y = other[key] || [0, 0, 0];
        result[key] = x.map((value, axis) => mix(value, y[axis]));
      }
    }
    if (left.scale_axis) result.scale = mix(left.scale ?? 1, other.scale ?? 1);
    return result;
  });
}

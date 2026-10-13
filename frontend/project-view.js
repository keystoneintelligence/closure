// Project capabilities come from contracts and available evidence, never IDs.
export function producedArtifacts(data) {
  return data.report.analyses.flatMap(a => Object.entries(a.record?.outputs || {})
    .filter(([, value]) => value.type === 'artifact')
    .map(([key, value]) => ({...value, key, analysis: a.id, output: `${a.id}.${key}`})));
}

export function modelArtifacts(data) {
  return producedArtifacts(data).filter(a => a.media_type === 'model/gltf-binary' || /\.glb$/i.test(a.name || ''));
}

export function partDetails(part) {
  const rows = [];
  if (part.material) rows.push(['Material', part.material]);
  if (Number.isFinite(part.volume_mm3)) rows.push(['Solid volume', `${part.volume_mm3.toLocaleString()} mm³`]);
  if (typeof part.valid === 'boolean') rows.push(['Geometry check', part.valid ? 'PASS' : 'ERROR']);
  for (const [label, value] of Object.entries(part.properties || {})) {
    if (['string', 'number', 'boolean'].includes(typeof value)) rows.push([label, String(value)]);
  }
  return rows;
}

export function metadataMatches(metadata, artifact, model) {
  if (artifact.analysis !== model.analysis) return false;
  return metadata.model_output === model.key || metadata.model_output === model.output;
}

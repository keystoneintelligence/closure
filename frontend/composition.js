// The saved assessment is the authority for the tree, scopes and decisions.
export function projectTree(report, escape, badge) {
  if (!report.projects) return '';
  const displayed = new Set();
  function project(name, alias) {
    const item = report.projects[name];
    const label = alias && alias !== item.name ? `${escape(alias)} → ${escape(item.name)}` : escape(item.name);
    if (displayed.has(name)) return `<li><a href="#project-tree-${encodeURIComponent(name)}">${label}</a></li>`;
    displayed.add(name);
    const gate = report.gates[name];
    const children = Object.entries(item.children).map(([alias, child]) => project(child, alias)).join('');
    const excluded = item.excluded_children.map(child => `<li>${escape(child)} · excluded</li>`).join('');
    const requirements = (gate?.scope || []).map(id =>
      `<li><button class="ghost small" data-explain="${escape(id)}">${escape(id)}</button></li>`);
    const imports = Object.entries(item.imports).map(([alias, id]) => {
      const action = report.requirements.some(row => row.id === id) ? 'data-explain' : 'data-variable';
      return `<li>${escape(alias)} from <button class="ghost small" ${action}="${escape(id)}">${escape(id)}</button></li>`;
    });
    const reasons = (gate?.reasons || []).map(reason => `<li>${escape(reason)}</li>`).join('');
    return `<li><details ${name === report.project ? 'open' : ''}><summary>${label}
      ${gate ? badge(gate.gate ? 'PASS' : 'OPEN') : ' · input supplier'}</summary>
      <p id="project-tree-${escape(name)}" tabindex="-1" class="subtext">${escape(item.source)}</p>${reasons ? '<ul>' + reasons + '</ul>' : ''}
      ${requirements.length ? '<strong>Requirements</strong><ul>' + requirements.join('') + '</ul>' : ''}
      ${imports.length ? '<strong>Inputs from other projects</strong><ul>' + imports.join('') + '</ul>' : ''}
      ${children || excluded ? '<ul>' + children + excluded + '</ul>' : ''}</details></li>`;
  }
  const root = project(report.project);
  const suppliers = Object.keys(report.projects).filter(name => !displayed.has(name)).map(name => project(name));
  return `<section class="card composition"><h2>Project structure</h2><ul>${root}</ul>
    ${suppliers.length ? '<h3>Input suppliers</h3><ul>' + suppliers.join('') + '</ul>' : ''}</section>`;
}

export function assessmentChanges(report, escape) {
  const comparison = report.comparison;
  if (!comparison && !report.baseline_changes?.length) return '';
  const items = lines => lines.map(line => `<li>${escape(line)}</li>`).join('');
  const decisions = comparison?.decisions.map(row => `<li><strong>${escape(row.analysis)}</strong>
    ${escape(row.reason)} ${row.run ? `<button class="ghost small" data-record="${escape(row.analysis)}">Inspect run</button>` : ''}</li>`).join('');
  const revision = report.revision;
  return `<section class="card composition"><h2>Assessment changes</h2>
    ${comparison ? `<p>${comparison.previous_date ? 'Compared with ' + escape(new Date(comparison.previous_date).toLocaleString()) : 'First assessment for this scope and context'}</p>
    <ul>${items(comparison.changes)}</ul>` : ''}
    ${decisions ? '<details><summary>Execution and reuse</summary><ul>' + decisions + '</ul></details>' : ''}
    ${report.baseline_changes?.length ? '<details><summary>Changes since obligation review</summary><ul>' + items(report.baseline_changes) + '</ul></details>' : ''}
    ${revision ? `<details><summary>Source · ${escape(revision.state)}</summary><code>${escape(revision.commit || report.source_hash)}</code><ul>${items(revision.files)}</ul></details>` : ''}</section>`;
}


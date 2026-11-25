import {test as base, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {existsSync, readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('../../',import.meta.url));
const localPython=fileURLToPath(new URL(process.platform==='win32'?'../../.venv/Scripts/python.exe':'../../.venv/bin/python',import.meta.url));
const test=base.extend({
  invalidCurrent: [false, {option: true}],
  serviceURL:async ({invalidCurrent}, use)=>{
    const python=process.env.CLOSURE_TEST_PYTHON||(existsSync(localPython)?localPython:'python');
    const args = ['tools/viewer_test_server.py'];
    if (invalidCurrent) args.push('--invalid-current');
    const child=spawn(python,args,{cwd:root,stdio:['ignore','pipe','pipe'],windowsHide:true});
    let errors='';child.stderr.on('data',data=>errors+=data);
    const lines=createInterface({input:child.stdout});
    try {
      const url=await new Promise((resolve,reject)=>{
        const timeout=setTimeout(()=>reject(Error(`Server timeout: ${errors}`)),20000);
        child.once('error',error=>{clearTimeout(timeout);reject(error);});
        child.once('exit',code=>{clearTimeout(timeout);reject(Error(`Server exited ${code}: ${errors}`));});
        lines.once('line',line=>{clearTimeout(timeout);resolve(JSON.parse(line).url);});
      });
      await use(url);
    } finally {
      lines.close();
      if(child.exitCode===null){child.kill();await new Promise(resolve=>child.once('exit',resolve));}
    }
  },
});

test.describe('saved evidence with invalid current source', () => {
  test.use({invalidCurrent: true});

  test('opens a sealed report and its records after a broken edit', async ({page, serviceURL}) => {
    await page.goto(serviceURL);
    await expect(page.getByRole('heading', {name: 'Current project unavailable'})).toBeVisible();
    const snapshot = page.getByRole('button', {name: 'Open snapshot'});
    await expect(snapshot).toBeVisible();
    const reportId = await snapshot.getAttribute('data-snapshot');
    await page.getByRole('button', {name: 'Inspect run'}).first().click();
    await expect(page.getByRole('dialog')).toContainText('Recorded outputs');
    await page.keyboard.press('Escape');
    await snapshot.click();
    await expect(page.getByText('Recorded scope closed')).toBeVisible();
    expect(new URL(page.url()).searchParams.get('report')).toBe(reportId);
    await page.reload();
    await expect(page.getByRole('button', {name: 'Verify', exact: true})).toBeDisabled();
    await page.getByRole('button', {name: 'Requirements'}).first().click();
    await page.locator('[data-explain="operations.CAP-001"]').first().click();
    await expect(page.getByRole('dialog')).toContainText('workload.arrival_rate');
    await expect(page.getByRole('region', {name: 'Obligation baseline'})).toContainText('Browser fixture');
    await page.keyboard.press('Escape');
    await page.getByRole('button', {name: 'Return to current project'}).click();
    await expect(page.getByRole('heading', {name: 'Current project unavailable'})).toBeVisible();
    await expect(snapshot).toBeVisible();
  });
});

test('a rejected context change keeps the previous report and selectors', async ({page, serviceURL}) => {
  await page.goto(serviceURL);
  const scenario = page.getByLabel('Scenario', {exact: true});
  const configuration = page.getByLabel('Configuration', {exact: true});
  await expect(scenario).toHaveValue('routine');
  await page.route('**/api/project?scenario=surge&configuration=balanced', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('scenario', 'unavailable');
    await route.fulfill({response: await route.fetch({url: url.href})});
  });
  await scenario.selectOption('surge');
  await expect(page.locator('#toast')).toContainText(/scenario|context/i);
  await expect(scenario).toHaveValue('routine');
  await expect(configuration).toHaveValue('balanced');
  await expect(page.getByRole('button', {name: 'Verify', exact: true})).toBeEnabled();
  await configuration.selectOption('expanded');
  await expect(configuration).toBeEnabled();
  await expect(configuration).toHaveValue('expanded');
});

test('edit → selective Verify → explanation → immutable history, using keyboard dialogs',async({page,serviceURL})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(serviceURL);
  await expect(page.getByRole('button',{name:'Verify',exact:true})).toBeEnabled();
  const verify=async()=>{
    const response=page.waitForResponse(r=>r.url().endsWith('/api/verify')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'Verify',exact:true}).click();
    const report=await (await response).json();
    await expect(page.getByRole('button',{name:'Return to current project'})).toBeVisible();
    return report;
  };
  const first=await verify();
  expect(first.gate).toBe(true);expect(first.executed).toHaveLength(2);
  await page.getByRole('button',{name:'Return to current project'}).click();
  await page.getByRole('button',{name:'Variables',exact:true}).click();
  const input=page.locator('[data-variable="workload.arrival_rate"]').first();
  await input.focus();await page.keyboard.press('Enter');
  const dialog=page.getByRole('dialog',{name:'workload.arrival_rate'});
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Shift+Tab');
  await expect(dialog.getByRole('button',{name:'Save change'})).toBeFocused();
  await page.keyboard.press('Escape');await expect(input).toBeFocused();
  await page.keyboard.press('Enter');
  await dialog.getByLabel('Value (1/s)').fill('250');
  await dialog.getByRole('button',{name:'Save change'}).click();
  await expect(dialog).not.toBeVisible();
  const failed=await verify();
  expect(failed.gate).toBe(false);expect(failed.executed).toEqual(['platform.capacity']);
  expect(failed.values['platform.energy.total'].value).toBe(180);
  expect(failed.values['platform.capacity.headroom'].value).toBeLessThan(0);
  await page.getByRole('button',{name:'Requirements',exact:false}).first().click();
  await page.locator('[data-explain="operations.CAP-001"]').first().click();
  await expect(page.getByRole('dialog')).toContainText('workload.arrival_rate');
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Return to current project'}).click();
  await page.getByRole('button',{name:'Evidence',exact:true}).click();
  await page.locator(`[data-snapshot="${first.id}"]`).click();
  await expect(page.getByText('Saved verification snapshot',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Verify',exact:true})).toBeDisabled();
  expect(errors).toEqual([]);
});

test('composed power history and project navigation', async ({page, serviceURL}, testInfo) => {
  await page.goto(serviceURL);
  await page.getByLabel('Load project').selectOption({label: 'Assembly power budget'});
  await expect(page.getByRole('heading', {name: 'Project structure'})).toBeVisible();
  async function verify() {
    const response = page.waitForResponse(r => r.url().endsWith('/api/verify'));
    await page.getByRole('button', {name: 'Verify', exact: true}).click();
    const report = await (await response).json();
    await expect(page.getByText('Saved verification snapshot', {exact:true})).toBeVisible();
    return report;
  }
  const first = await verify();
  expect(first.gate).toBe(true);
  expect(first.executed).not.toContain('electronics::load.scale');
  const structure = page.locator('.composition').filter({has: page.getByRole('heading', {name: 'Project structure'})});
  await structure.locator('summary').filter({hasText:/electronics/i}).click();
  await structure.locator('[data-explain="electronics::load.local_budget"]').click();
  const baseline = page.getByRole('region', {name: 'Obligation baseline'});
  await expect(baseline.getByText('electronics', {exact: true})).toBeVisible();
  await expect(baseline.getByText('current', {exact: true})).toBeVisible();
  const childBaseline = JSON.parse(readFileSync(new URL('../../examples/composed-power/electronics/reviews/baseline.json', import.meta.url), 'utf8'));
  await expect(baseline.getByText(childBaseline.reviewer, {exact: true})).toBeVisible();
  await expect(page.getByRole('dialog')).toContainText('Electronics reviewer');
  await expect(page.getByRole('dialog')).toContainText('Checked the component allocation.');
  await page.keyboard.press('Escape');
  await page.getByRole('button', {name:'Return to current project'}).click();
  await page.getByRole('button', {name:'Variables',exact:true}).click();
  await page.locator('[data-variable="system::budget.maximum"]').click();
  await page.getByLabel('Value (W)').fill('100');
  await page.getByRole('button', {name:'Save change'}).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  // The root now needs a new approval; the child's live explanation still uses its own baseline.
  await page.getByRole('button', {name: 'Overview', exact: true}).click();
  await structure.locator('summary').filter({hasText: /electronics/i}).click();
  await structure.locator('[data-explain="electronics::load.local_budget"]').click();
  await expect(baseline.getByText('current', {exact: true})).toBeVisible();
  await page.keyboard.press('Escape');
  const second = await verify();
  expect(second.gate).toBe(false);
  expect(second.executed).toEqual([]);
  await page.getByRole('button', {name:'Overview',exact:true}).click();
  await expect(page.getByText(/limit changed from 110 W to 100 W/i)).toBeVisible();
  const panel = page.locator('.composition').first();
  await panel.getByText('Execution and reuse').click();
  await expect(panel.getByText(/Reused the verified run/).first()).toBeVisible();
  await page.screenshot({path:testInfo.outputPath('composed-power.png')});
  await page.locator('.composition [data-explain="system::budget.power"]').click();
  await expect(baseline.getByText('system', {exact: true})).toBeVisible();
  await expect(baseline.getByText('changed', {exact: true})).toBeVisible();
  await expect(page.getByRole('dialog')).toContainText('104');
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Evidence',exact:true}).click();
  await page.locator('[data-snapshot="' + first.id + '"]').click();
  await expect(page.getByText('Recorded scope closed')).toBeVisible();
});

test('child explanation remains available when an older snapshot lacks its baseline', async ({page, serviceURL}) => {
  await page.goto(serviceURL);
  await page.getByLabel('Load project').selectOption({label: 'Assembly power budget'});
  await expect(page.getByRole('heading', {name: 'Project structure'})).toBeVisible();
  await page.getByRole('button', {name: 'Verify', exact: true}).click();
  await expect(page.getByText('Saved verification snapshot', {exact: true})).toBeVisible();
  await page.route('**/api/explain?**', async route => {
    const response = await route.fetch();
    const explanation = await response.json();
    await route.fulfill({response, json: {...explanation, baseline: null}});
  });
  await page.locator('.composition summary').filter({hasText: /electronics/i}).click();
  await page.locator('.composition [data-explain="electronics::load.local_budget"]').click();
  const baseline = page.getByRole('region', {name: 'Obligation baseline'});
  await expect(baseline).toContainText('electronics');
  await expect(baseline).toContainText('Owner baseline unavailable for this assessment.');
  await expect(page.getByRole('dialog')).toContainText('Electronics reviewer');
});

test('child aliases open shared project details through either relationship', async ({page, serviceURL}) => {
  await page.goto(serviceURL);
  await page.route('**/api/open', async route => {
    const response = await route.fetch();
    const data = await response.json();
    const {system, cooling, electronics} = data.report.projects;
    system.children = {thermal: 'cooling', controller: 'electronics', wiring: 'electronics'};
    cooling.children = {board: 'electronics'};
    electronics.children = {ratings: 'reference'};
    await route.fulfill({response, json: data});
  });
  await page.getByLabel('Load project').selectOption({label: 'Assembly power budget'});
  const tree = page.locator('.composition').filter({has: page.getByRole('heading', {name: 'Project structure'})});
  const thermal = tree.locator('summary').filter({hasText: 'thermal → cooling'});
  const board = tree.locator('summary').filter({hasText: 'board → electronics'});
  const target = tree.locator('[data-explain="electronics::load.local_budget"]');
  await expect(thermal).toBeVisible();
  await expect(board).toBeHidden();
  await expect(target).toHaveCount(1);
  for (const alias of ['controller', 'wiring']) {
    const link = tree.getByRole('link', {name: `${alias} → electronics`});
    await link.focus();
    await page.keyboard.press('Enter');
    await expect(tree.locator('#project-tree-electronics')).toBeFocused();
    await expect(board).toBeVisible();
    await expect(target).toBeVisible();
    await expect(tree.locator('summary').filter({hasText: 'ratings → reference'})).toBeVisible();
    await target.click();
    await expect(page.getByRole('dialog', {name: 'electronics::load.local_budget'})).toBeVisible();
    await page.keyboard.press('Escape');
    await board.click();
    await thermal.click();
  }
});

import {test as base, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('../../',import.meta.url));
const localPython=fileURLToPath(new URL(process.platform==='win32'?'../../.venv/Scripts/python.exe':'../../.venv/bin/python',import.meta.url));
const test=base.extend({
  serviceURL:async ({}, use)=>{
    const python=process.env.CLOSURE_TEST_PYTHON||(existsSync(localPython)?localPython:'python');
    const child=spawn(python,['tools/viewer_test_server.py'],{cwd:root,stdio:['ignore','pipe','pipe'],windowsHide:true});
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

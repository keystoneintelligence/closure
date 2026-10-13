import {defineConfig} from '@playwright/test';

export default defineConfig({
  testDir:'./e2e',
  timeout:60000,
  workers:1,
  fullyParallel:false,
  reporter:[['list'], ['json',{outputFile:'../docs/verification/preview-browser.json'}]],
  outputDir:'../.closure/browser-results',
  use:{headless:true, viewport:{width:1440,height:1000}, trace:'retain-on-failure'},
  projects:[{name:'chromium',use:{browserName:'chromium'}}, {name:'firefox',use:{browserName:'firefox'}}],
});

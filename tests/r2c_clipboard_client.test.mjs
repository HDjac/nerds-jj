/* No network, no backend changes. Exercise released browser helper and telemetry. */
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const repo = process.env.NERDS_REPO || join(process.env.HOME, 'nerds-r2c-provenance');
const dir = await mkdtemp(join(tmpdir(), 'nerds-r2c-client-'));
const oldNow = Date.now;
let fakeNow = 10_000_000;
Date.now = () => fakeNow;
try {
  let src = await readFile(resolve(repo, 'instance/app/src/internalClipboard.js'), 'utf8');
  src = src.replace('from "./clipboardActivity"', 'from "./mockActivity.mjs"');
  assert(src.includes('mockActivity.mjs'), 'clipboard helper import shape changed');
  await writeFile(join(dir, 'internalClipboard.mjs'), src);
  await writeFile(join(dir, 'mockActivity.mjs'), 'export function recordClipboardActivity() { return true; }\n');
  globalThis.window = {
    localStorage: { removeItem() {} },
    dispatchEvent() {},
    addEventListener() {},
    setInterval() {},
    location: { pathname: '/proxy/0123456789ab/nb/' },
  };
  globalThis.CustomEvent = class { constructor(type, opts) { this.type=type; this.detail=opts?.detail; } };
  const internal = await import(pathToFileURL(join(dir, 'internalClipboard.mjs')).href);
  const { getNerdsObservedClipboardText: observed, setNerdsInternalClipboard: set } = internal;
  set('SYNTH_CLI', 'internal_cli', { observedFromVnc: true });
  assert.equal(observed('internal_cli', 'SYNTH_CLI'), 'SYNTH_CLI');
  assert.equal(observed('internal_browser', 'SYNTH_CLI'), undefined);
  assert.equal(observed('internal_cli', 'WRONG'), undefined);
  fakeNow += 15_001;
  assert.equal(observed('internal_cli', 'SYNTH_CLI'), undefined, 'stale observation rejected');
  set('SYNTH_BROWSER', 'internal_browser', { observedFromVnc: true });
  assert.equal(observed('internal_browser', 'SYNTH_BROWSER'), 'SYNTH_BROWSER');
  set('SYNTH_BROWSER', 'internal_browser');
  assert.equal(observed('internal_browser', 'SYNTH_BROWSER'), undefined, 'cached fallback revoked');
  set('GUIDE_CODE', 'fuzzing_guide_command');
  assert.equal(observed('fuzzing_guide', 'GUIDE_CODE'), undefined, 'guide text not eligible');
  console.log('PASS: Recent observation, stale fallback, source mismatch, and guide exclusion');

  await writeFile(join(dir, 'clipboardTelemetry.mjs'),
    await readFile(resolve(repo, 'instance/app/src/clipboardTelemetry.js'), 'utf8'));
  const posts=[];
  const taskId='00000000-0000-4000-8000-000000000123';
  globalThis.fetch=async (url, options) => {
    if (url.endsWith('api/pilot1/browser-context'))
      return {ok:true, json:async()=>({task_run_id:taskId})};
    if (url.endsWith('log-clipboard-event')) {
      posts.push(JSON.parse(options.body));
      return {ok:true};
    }
    throw new Error('Unexpected test URL');
  };
  process.env.REACT_APP_NERDS_CLIPBOARD_INGEST='1';
  process.env.REACT_APP_NERDS_CLIPBOARD_TEXT='1';
  const telemetry = await import(pathToFileURL(join(dir,'clipboardTelemetry.mjs')).href+'?on');
  await telemetry.refreshClipboardTaskContext();
  const candidate='SYNTHETIC_SAMPLE_TEXT';
  const meta=(source,surface,method='shift_insert',kind='paste_requested')=>({
    kind, source, surface, method, occurred_at:new Date().toISOString(),
  });
  const cases=[
    ['internal_cli','internal_cli','shift_insert',true],
    ['internal_browser','internal_cli','shift_insert',true],
    ['internal_cli','internal_browser','ctrl_shortcut',true],
    ['task_sidebar','internal_cli','shift_insert',false],
    ['fuzzing_guide','internal_cli','shift_insert',false],
    ['internal_browser','internal_browser','ctrl_shortcut',false],
    ['unknown','internal_cli','shift_insert',false],
  ];
  for (const [source,surface,method,eligible] of cases) {
    await telemetry.sendClipboardTelemetry(meta(source,surface,method),candidate);
    const last=posts.at(-1);
    assert.equal('text' in last,eligible,`${source}->${surface}`);
    assert.equal(last.expected_task_run_id,taskId);
  }
  await telemetry.sendClipboardTelemetry(meta('internal_cli','internal_cli','shift_insert','clipboard_observed'),candidate);
  assert.equal('text' in posts.at(-1),false,'observation is not a paste');
  console.log('PASS: Browser telemetry includes text only for three internal paste directions');

  process.env.REACT_APP_NERDS_CLIPBOARD_TEXT='0';
  const disabled = await import(pathToFileURL(join(dir,'clipboardTelemetry.mjs')).href+'?off');
  await disabled.refreshClipboardTaskContext();
  await disabled.sendClipboardTelemetry(meta('internal_cli','internal_cli'),candidate);
  assert.equal('text' in posts.at(-1),false,'capture off by build flag');
  console.log('PASS: Browser disabled-by-default text gate');
} finally {
  Date.now=oldNow;
  await rm(dir,{recursive:true,force:true});
}

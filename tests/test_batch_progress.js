const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('extension/injects/ui.js', 'utf8');
function extract(name) {
  const declarations = [...source.matchAll(/^  (?:async )?function (\w+)\(/gm)];
  const index = declarations.findIndex(match => match[1] === name);
  assert.ok(index >= 0, name);
  return source.slice(declarations[index].index, declarations[index + 1]?.index || source.length);
}
function setup() {
  const task = () => ({ text: 'Test prompt', status: ['waiting'], message: [''], downloaded: [false], interval: 0 });
  const state = { tasks: [task(), task()], settings: { interval: 0 }, presets: [], currentIndex: 0, currentLineIndex: 0 };
  const context = vm.createContext({
    state, batchPromise: null, console: { log() {}, warn() {}, error() {} },
    getStorageKey: () => 'project', downloadedUrlsSet: new Set(),
    saveState: async () => {}, hostedStatusHook: null,
    document: { querySelectorAll: () => [], querySelector: () => ({}),
      getElementById: () => ({ style: { setProperty() {} } }) },
    location: { href: 'https://flow.google.com/project/project' },
    window: {}, isStopRequested: false, alarmDialogEl: null, alarmTimer: null,
    isVidsPage: () => false, enableTabKeepAlive() {}, startActivityCheck() {},
    splitTextToLines: text => text.split('\n').filter(Boolean), getTasksNeedingUpload: () => [],
    normalizeDuration: () => 8, calculateDuration: () => 8, parsePreset: () => ({ before: '', after: '' }),
    showToast() {}, findCurrentBatchContainer: () => null, cleanupPageOverlays: async () => {},
    mediaIdFromVideoUrl: url => url.split('/').at(-1),
    onBatchFinished: () => { state.isRunning = false; },
  });
  for (const name of ['loadState', 'updateLineStatus', 'runBatch']) vm.runInContext(extract(name), context);
  return context;
}
async function run() {
  // Panel opened while the batch is active: no storage read or task replacement.
  const active = setup();
  const live = active.state.tasks;
  active.batchPromise = Promise.resolve();
  active.sendToExtension = async () => { throw new Error('Active queue must retain live state'); };
  await active.loadState();
  assert.equal(active.state.tasks, live);

  // Queue starts before an outstanding storage read returns.
  const race = setup();
  const original = race.state.tasks;
  let release;
  race.sendToExtension = () => new Promise(resolve => { release = resolve; });
  const loading = race.loadState();
  race.batchPromise = Promise.resolve();
  release({ tasks_project: [{ text: 'stale snapshot' }] });
  await loading;
  assert.equal(race.state.tasks, original);

  // Two real queue iterations, with the download-complete event arriving before
  // the download-start request returns. The late progress update must not undo it.
  const queue = setup();
  queue.batchPromise = Promise.resolve();
  const submitted = [];
  let delays = 0;
  let downloads = 0;
  queue.delay = async () => { assert.ok(++delays < 10, 'Queue stalled after confirmed download'); };
  queue.submitTaskToPage = async params => {
    submitted.push(params.rowIndex);
    await queue.loadState(); // same operation as reopening the panel
    queue.state.tasks[params.rowIndex].mediaBindings = [{
      schema: 2, mediaIds: ['video-' + params.rowIndex], readyIds: ['video-' + params.rowIndex],
      urls: { ['video-' + params.rowIndex]: 'https://flow-content.google/video/video-' + params.rowIndex },
    }];
  };
  queue.triggerAutoDownload = async () => {
    downloads++;
    const row = queue.state.currentIndex;
    queue.state.tasks[row].downloaded[0] = true;
    queue.updateLineStatus(row, 0, 'success', 'Download confirmed');
    return true;
  };
  await queue.runBatch();
  assert.deepEqual(submitted, [0, 1]);
  assert.equal(downloads, 2);
  assert.ok(queue.state.tasks.every(task => task.status[0] === 'success' && task.downloaded[0]));
  assert.equal(queue.state.isRunning, false);
  console.log('Batch progression passed: live task identity, storage race, fast completion, and next task.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });

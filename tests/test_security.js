const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch { ({ JSDOM } = require('../scratch/flow-dom-runtime/node_modules/jsdom')); }
const source = fs.readFileSync(path.join(__dirname, '../extension/injects/ui.js'), 'utf8');
function extract(name) {
  const declarations = [...source.matchAll(/^  (?:async )?function (\w+)\(/gm)];
  const index = declarations.findIndex(match => match[1] === name);
  assert.ok(index >= 0, name);
  return source.slice(declarations[index].index, declarations[index + 1]?.index || source.length);
}
async function run() {
  const dom = new JSDOM('<div id="presets-list-container"></div><table><tr><td class="status-cell-container"></td></tr></table>',
    { url: 'https://labs.google/fx/tools/flow/project/test', runScripts: 'outside-only' });
  const w = dom.window;
  const attack = '"><img src=x onerror="window.compromised=true"><svg onload="window.compromised=true">';
  w.flowTrustedPolicy = null;
  w.state = { presets: [{ name: attack }] };
  w.splitTextToLines = text => [text];
  for (const name of ['setSafeHTML', 'escapeHTML', 'renderPresetsList', 'renderTableStatusCell']) w.eval(extract(name));
  w.renderPresetsList();
  w.renderTableStatusCell(w.document.querySelector('tr'), { text: attack, status: ['failed'], message: [attack] }, 0);
  assert.equal(w.document.querySelectorAll('img,svg,script,[onerror],[onload]').length, 0);
  assert.equal(w.document.querySelector('.status-line-text').title, attack);
  assert.equal(w.document.querySelector('.status-badge').title, attack);
  assert.ok(w.document.querySelector('#presets-list-container').textContent.includes(attack));
  dom.window.close();

  let listener;
  const quiet = { log() {}, warn() {}, error() {} };
  const chrome = { runtime: { id: 'test-extension', getManifest: () => ({ version: 'test' }),
    onMessage: { addListener(fn) { listener = fn; } } },
    downloads: { onDeterminingFilename: { addListener() {} }, onChanged: { addListener() {} } } };
  const context = vm.createContext({ chrome, URL, console: quiet, setTimeout });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../extension/background.js'), 'utf8'), context);
  for (const url of ['http://labs.google/a', 'https://labs.google.evil/a', 'https://docs.google.com/document/a', 'file:///a']) {
    let response;
    listener({ action: 'getBgVersion' }, { id: 'test-extension', frameId: 0, url, tab: { id: 1, url } }, r => { response = r; });
    assert.match(response.error, /来源/);
  }
  let response;
  const url = 'https://labs.google/fx/tools/flow';
  listener({ action: 'getBgVersion' }, { id: 'test-extension', frameId: 0, url, tab: { id: 1, url } }, r => { response = r; });
  assert.equal(response.version, 'test');
  for (const paths of [['\\\\server\\share\\a.png'], ['C:\\a.png:secret.png'], ['C:\\..\\a.png'], ['relative.png'], ['C:\\bad.exe']]) {
    await assert.rejects(context.dispatchNativeFileDrag(1, paths, 0, 0), /安全拦截/);
  }
  const result = await context.handleDownload('http://flow-content.google/video/test', 'Flow/test/01.mp4', {
    mediaId: 'test', submissionId: 's', taskId: 't', download_path: 'Flow/test/01.mp4' });
  assert.match(result.error, /HTTPS/);
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '../extension/manifest.json')));
  assert.ok(manifest.content_scripts.every(item => item.all_frames === false && item.matches.every(m => m.startsWith('https://'))));
  console.log('Security checks passed: stored HTML injection, sender validation, HTTPS, local path validation, and manifest scope.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });

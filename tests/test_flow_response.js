const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('extension/injects/flow-proxy.js', 'utf8');
const start = source.indexOf('  function cleanBoQResponseText(');
const end = source.indexOf('  function getUrlString(', start);
const context = vm.createContext({ console });
vm.runInContext(source.slice(start, end), context);
async function run() {
  for (const type of ['application/json', 'text/plain', 'application/x-javascript']) {
    const records = [[['wrb.fr', 'rpc-id', JSON.stringify({ media: [] })]], [['di', 42]]];
    const body = ")]}'\n\n" + records.map(record => {
      const text = JSON.stringify(record);
      return Buffer.byteLength(text) + '\n' + text;
    }).join('\n');
    const result = await context.parseFetchResponse(new Response(body, { headers: { 'Content-Type': type } }));
    assert.deepEqual(JSON.parse(JSON.stringify(result)), records);
  }
  assert.equal(context.decodeBoQResponseText('unrecognized response'), 'unrecognized response');
  assert.equal(JSON.stringify(context.decodeBoQResponseText('{"ok":true}')), '{"ok":true}');
  console.log('Flow response decoding passed: JSON, XSSI prefixes, multiple length-framed records.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });

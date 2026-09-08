const {test} = require('node:test');
const assert = require('node:assert/strict');
const {ManualDrive} = require('../software/sim/manual_drive.js');
function deferred() {
  let resolve;
  const promise = new Promise(r => {resolve=r;});
  return {promise, resolve};
}
const flush = () => new Promise(r => setImmediate(r));

test('release while disarm is pending cannot issue late forward', async () => {
  const gate=deferred(), calls=[];
  const drive=new ManualDrive(() => gate.promise, async motion => calls.push(motion));
  const started=drive.start('forward', .5);
  await drive.stop(); gate.resolve(); await started;
  assert.deepEqual(calls, ['stop']);
});
test('stop is repeated after an already transmitted command completes', async () => {
  const gate=deferred(), calls=[];
  const drive=new ManualDrive(async()=>{}, async motion => {
    calls.push(motion);
    if(motion!=='stop') await gate.promise;
  });
  const started=drive.start('forward', .5); await flush();
  const stopped=drive.stop(); await flush();
  assert.deepEqual(calls, ['forward','stop']);
  gate.resolve(); await started; await stopped;
  assert.deepEqual(calls, ['forward','stop','stop']);
});
test('repeated pointer down cannot create competing command loops', async () => {
  const gate=deferred(), calls=[];
  const drive=new ManualDrive(()=>gate.promise, async motion=>calls.push(motion));
  const first=drive.start('forward', .5);
  await drive.start('reverse', .5);
  gate.resolve(); await first; await drive.stop();
  assert.deepEqual(calls, ['forward','stop']);
});
test('disarm failure never starts the motors', async () => {
  const calls=[], errors=[];
  const drive=new ManualDrive(async()=>{throw Error('offline');},
    async motion=>calls.push(motion), error=>errors.push(error.message));
  await drive.start('forward', .5);
  assert.deepEqual(calls, ['stop']);
  assert.deepEqual(errors, ['offline']);
});
test('new press waits for old stop to finish and can be cancelled meanwhile', async () => {
  const gate=deferred(), calls=[];
  const drive=new ManualDrive(async()=>{}, async motion=>{
    calls.push(motion); if(motion==='stop') await gate.promise;
  });
  const stopping=drive.stop();
  const starting=drive.start('forward',.5);
  drive.stop(); gate.resolve(); await stopping; await starting;
  assert.deepEqual(calls,['stop']);
});

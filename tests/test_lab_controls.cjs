const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname,'../software/sim/lab.html'),'utf8');
const renderer = html.match(/function renderLive\(\)[\s\S]*?(?=\nfunction drawLive\()/)[0];

function render(connected, fresh) {
  const nodes=new Map(), buttons=Array.from({length:4},()=>({}));
  const context={
    live:{status:connected?{motor_active:false}:{error:'unreachable'}, telemetry:{},
      jetson:{target:'sports ball', mission_timeout_s:45, detector_ready:true,
        armed:false, monitoring:false, state:'disarmed'}},
    $:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);},
    $$:()=>buttons, n:(v,_d,suffix='')=>v==null?'--':String(v)+suffix,
    cameraFreshness:{snapshot:()=>({state:fresh?'live':'stale'})},
    performance:{now:()=>100}, drawLive:()=>{},
  };
  vm.runInNewContext(renderer+'\nrenderLive();',context);
  return {nodes,buttons};
}

test('unreachable Pi disables movement without claiming motors are stopped',()=>{
  const {nodes,buttons}=render(false,false);
  assert.equal(nodes.get('#sideMotors').textContent,'unknown');
  assert.equal(nodes.get('#selectedTarget').textContent,'sports ball');
  assert.equal(nodes.get('#missionBudget').textContent,'45 s limit');
  assert.equal(nodes.get('#arm').disabled,true);
  assert.equal(nodes.get('#missionReason').textContent,'Pi connection unavailable');
  assert.ok(buttons.every(button=>button.disabled));
});
test('fresh camera and ready devices enable controls, stale video blocks arming',()=>{
  assert.equal(render(true,true).nodes.get('#arm').disabled,false);
  assert.equal(render(true,false).nodes.get('#arm').disabled,true);
  assert.ok(render(true,true).buttons.every(button=>!button.disabled));
});

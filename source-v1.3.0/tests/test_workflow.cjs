// Exercise shipped page steps in a DOM fixture; no browser profiles or uploads.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const path = require('path');
const nodes = JSON.parse(fs.readFileSync(path.join(__dirname, '../Resources/payload/通用流程-无凭据.automa.json'), 'utf8')).drawflow.nodes;
async function step(index, cfg) {
  const fields = new Map(), submitted = [];
  let tagsLookups = 0;
  const get = sel => {
    if (sel.includes('#tags-container')) tagsLookups++;
    if (!fields.has(sel)) fields.set(sel, {textContent: '', disabled:false, getAttribute:()=>null, focus(){}, click(){}, dispatchEvent(e){submitted.push([sel,e.type,this.value]);}});
    return fields.get(sel);
  };
  class Input { }
  Object.defineProperty(Input.prototype, 'value', {set(v){this.value=v;}});
  let resolve;
  const done = new Promise(r=>resolve=r);
  const errors=[];
  vm.runInNewContext(nodes[index].data.code, {
    automaRefData:()=>cfg, automaNextBlock:()=>resolve(), automaSetVariable:(k,v)=>errors.push(v),
    document:{body:{innerText:''}, querySelector:get, querySelectorAll:()=>[{innerText:'Music',getClientRects:()=>[1],click(){}}]},
    HTMLInputElement:Input, InputEvent:class {constructor(type){this.type=type;}}, Event:class {constructor(type){this.type=type;}}, KeyboardEvent:class {constructor(type){this.type=type;}},
    setTimeout:fn=>{fn();}, console:{error:e=>errors.push(e.message)}
  });
  await done; assert.deepEqual(errors,[]);
  return {fields,submitted,tagsLookups};
}
(async()=>{
  let r=await step(7,{title:'Title',description:'Body #Inside',hashtags:'#MustNotAppend'});
  assert.equal(r.fields.get('ytcp-video-metadata-editor #title-textarea #textbox').textContent,'Title');
  assert.equal(r.fields.get('ytcp-video-metadata-editor #description-textarea #textbox').textContent,'Body #Inside');
  r=await step(7,{title:'Title',description:'#Fallback\n#Second',hashtags:'#Fallback\n#Second'});
  assert.equal(r.fields.get('ytcp-video-metadata-editor #description-textarea #textbox').textContent,'#Fallback\n#Second');
  r=await step(10,{tags:[]}); assert.equal(r.tagsLookups,0);
  r=await step(10,{tags:['one','two words']});
  assert.equal(r.fields.get('ytcp-video-metadata-editor-advanced #tags-container input').value,'one,two words,');
  assert.ok(r.submitted.some(([sel,type])=>sel.includes('#tags-container')&&type==='keydown'));
  console.log('PASS: title, description priority, multiline fallback, empty Tags skip, populated Tags submission (5 checks)');
})().catch(e=>{console.error(e);process.exit(1);});

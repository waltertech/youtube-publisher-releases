const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {spawn}=require('child_process');
const {chromium}=require('playwright');
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'smoke_server.py')],{env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'},stdio:['ignore','pipe','pipe']});
 let stderr='';server.stderr.on('data',c=>stderr+=c);
 let browser;
 try {
  const url=await new Promise((resolve,reject)=>{let s='';server.stdout.on('data',c=>{s+=c;if(s.includes('\n')){try{resolve(JSON.parse(s.split('\n')[0]).url);}catch(e){reject(e);}}});server.on('exit',code=>reject(Error('server exit '+code+': '+stderr)));setTimeout(()=>reject(Error('server timeout')),15000).unref();});
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.waitForFunction(()=>document.querySelector('#connection').textContent==='本机看板已连接');
  assert.equal(await page.locator('#appVersion').innerText(),'v1.3.0');
  assert.equal(await page.locator('#materialRulesPanel').isVisible(),false);
  await page.locator('#openMaterialSettings').click();
  assert.ok(await page.locator('#copyKeywords').isVisible());
  assert.equal(await page.locator('#copyKeywords').inputValue(),'发布文案\n新文案');
  await page.locator('#copyKeywords').fill('Caption\n发布文案');await page.locator('#coverKeywords').fill('Artwork\n封面');
  await page.locator('#fallbackDescription').fill('测试兜底详情\n第二行');
  await page.locator('#saveMaterialRules').click();await page.waitForFunction(()=>document.querySelector('#materialRulesResult').textContent.includes('已保存'));
  await page.reload();await page.waitForFunction(()=>document.querySelector('#copyKeywords').value==='Caption\n发布文案');
  await page.locator('#openMaterialSettings').click();assert.equal(await page.locator('#fallbackDescription').inputValue(),'测试兜底详情\n第二行');await page.locator('#closeMaterialSettings').click();
  await page.locator('#windows input[value="fixture-window"]').check();await page.waitForFunction(()=>document.querySelector('#selectedWindowCount').textContent.includes('1 个'));assert.match(await page.locator('#selectedWindowList').innerText(),/GM001/);assert.match(await page.locator('#publishableChannelTotal').innerText(),/1 个/);
  await page.locator('#installPanel summary').first().click();assert.equal(await page.locator('[data-action="initialize_selected"]').last().isDisabled(),false);
  await page.locator('#selectedWindowList [data-remove-window]').click();await page.waitForFunction(()=>document.querySelector('#selectedWindowCount').textContent.includes('0 个'));assert.equal(await page.locator('[data-action="initialize_selected"]').last().isDisabled(),true);
  await page.locator('[data-tab="assets"]').click();assert.match(await page.locator('#table').innerText(),/封面匹配多个文件/);assert.match(await page.locator('#table').innerText(),/来源：兜底配置/);await page.locator('[data-asset-desc]').click();assert.match(await page.locator('#table').innerText(),/测试兜底详情/);
  // HTTP validation and same-origin token guard, through the running application handler.
  const checks=await page.evaluate(async()=>{
    const html=await(await fetch('/')).text();const token=html.match(/const TOKEN='([^']+)'/)[1];
    const call=(body,t=token)=>fetch('/api/material-rules',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':t},body:JSON.stringify(body)});
    return {invalid:(await call({copy_keywords:[],cover_keywords:['封面']})).status,emptySelection:(await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':token},body:JSON.stringify({action:'initialize_selected',gms:[]})})).status,unauthorized:(await call({copy_keywords:['文案'],cover_keywords:['封面']},'wrong')).status,health:await(await fetch('/health')).json()};
  });
  assert.equal(checks.emptySelection,409);assert.equal(checks.invalid,409);assert.equal(checks.unauthorized,403);assert.equal(checks.health.version,'1.3.0');
  assert.deepEqual(errors,[]);
  await page.locator('#openMaterialSettings').click();
  await page.locator('#copyKeywords').fill('发布文案\n新文案');await page.locator('#coverKeywords').fill('封面\ncover');await page.locator('#saveMaterialRules').click();await page.locator('#closeMaterialSettings').click();await page.evaluate(()=>window.scrollTo(0,0));
  const out=process.env.YPP_VERIFICATION_DIR||path.join(__dirname,'../../verification');fs.mkdirSync(out,{recursive:true});
  await page.screenshot({path:path.join(out,'素材识别设置-1.3.0.png'),fullPage:true});
  await page.locator('#openMaterialSettings').click();await page.screenshot({path:path.join(out,'素材设置弹窗-1.3.0.png'),fullPage:false});await page.setViewportSize({width:390,height:750});assert.ok(await page.locator('#appVersion').isVisible());assert.ok(await page.locator('#copyKeywords').isVisible());await page.screenshot({path:path.join(out,'素材识别设置-窄窗口-1.3.0.png'),fullPage:false});
  console.log('PASS: fallback persistence and list provenance, selected account list/cancel, publishable count, empty selected configuration guard; app HTTP/UI settings defaults, save, reload persistence, specific errors, invalid values, token guard, version and console; homepage settings visibility and prominent version badge');
 } finally {if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exit(1);});

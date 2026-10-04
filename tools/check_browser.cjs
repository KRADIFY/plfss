// Disposable browser; no personal profile or production traffic.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.PLFSS_TEST_URL || 'http://127.0.0.1:18895';
const root = path.resolve(__dirname, '..');
const checks = [], errors = [];
async function main() {
  const browser = await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-background-networking']});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1050},acceptDownloads:true});
    page.on('pageerror', error => errors.push(String(error)));
    page.on('response', r => {if(r.url().startsWith(base) && r.status()>=500)errors.push(`${r.status()} ${r.url()}`);});
    await page.goto(base);
    const capturedVersion=(await (await page.request.get(base+'/api/meta')).json()).data_version;
    await page.locator('#matrix table').waitFor();
    async function idle(){await page.locator('#busy').waitFor({state:'hidden'});await assert.equal(await page.locator('#error').isVisible(),false,await page.locator('#error').textContent());}
    async function select(id,value){const response=page.waitForResponse(r=>r.url().includes('/api/matrix?')&&r.request().method()==='GET');await page.locator('#'+id).selectOption(value);await response;await idle();}
    async function view(name){const response=page.waitForResponse(r=>r.url().includes('/api/'+(name==='DOCUMENTS'?'documents':name==='COVERAGE'?'coverage':'matrix')));await page.locator(`[data-view="${name}"]`).click();await response;await idle();}
    async function verify(label){
      const control=await page.evaluate(()=>({domain:document.querySelector('[data-view].active').dataset.view,perimeter:document.getElementById('perimeter').value,start:document.getElementById('start').value,end:document.getElementById('end').value,metric:document.getElementById('metric').value,stages:document.getElementById('stage-mode').value,exclude:[...document.querySelectorAll('[data-entity]')].filter(n=>!n.checked).map(n=>n.dataset.entity).join(',')}));
      const response=await page.request.get(base+'/api/matrix?'+new URLSearchParams(control));assert.equal(response.status(),200);
      const m=await response.json();const rows=[m.total,...(m.selection?[m.selection]:[]),...m.rows];const rendered=await page.locator('#matrix tbody tr').count();assert.equal(rendered,rows.length);
      const unit=Number(await page.locator('#unit').inputValue());const fmt=new Intl.NumberFormat('fr-FR',{minimumFractionDigits:unit===1?2:1,maximumFractionDigits:unit===1?2:1});let cells=0;
      for(let ri=0;ri<rows.length;ri++)for(let ci=0;ci<m.columns.length;ci++){
        const c=rows[ri].cells[ci],td=page.locator('#matrix tbody tr').nth(ri).locator('td').nth(ci+1);
        if(c.amount_cents==null)assert.equal(await td.locator('.matrix-missing').count(),1);
        else {const text=await td.locator('.amount').textContent();assert.equal(text,(c.status==='partial'?'* ':'')+fmt.format(c.amount_cents/100/unit));}cells++;
      }
      checks.push({label,cells,...control});
    }
    await idle();await verify('initial');
    await select('start','2019');await select('end','2019');
    for(const perimeter of ['ROBSS','RG','ROBSS_FSV','RG_FSV','FSV']){
      await select('perimeter',perimeter);
      for(const metric of ['RECETTES','DEPENSES','SOLDE']){await select('metric',metric);await verify(`${perimeter} ${metric}`);}
    }
    await select('perimeter','ROBSS');await select('metric','DEPENSES');
    for(let year=2017;year<=2027;year++){await select('start',String(year));await select('end',String(year));await verify('exercice '+year);}
    for(const stages of ['PLFSS_RECTIF,LFSS_RECTIF','PROJECTION','PLFSS,LFSS,CONSTATE']){await select('stage-mode',stages);await verify('étapes '+stages);}
    for(const unit of ['1','1000000','1000000000']){await page.locator('#unit').selectOption(unit);await verify('unité '+unit);}
    // Proposed figure and absent voted figure each have a usable explanation.
    await page.locator('#matrix tbody tr').first().locator('.amount').first().click();await page.locator('#proof').waitFor({state:'visible'});assert.match(await page.locator('#proof-content').textContent(),/2027/);await page.locator('#close-proof').click();
    await page.locator('#matrix tbody tr').first().locator('.matrix-missing').first().click();await page.locator('#proof').waitFor({state:'visible'});assert.match(await page.locator('#proof-content').textContent(),/pas encore votée/);await page.locator('#close-proof').click();
    await select('start','2018');await select('end','2018');await select('perimeter','RG_FSV');await select('metric','SOLDE');
    await page.locator('#matrix .source-warning').first().click();await page.locator('#proof').waitFor({state:'visible'});
    assert.match(await page.locator('#proof-content').textContent(),/394,6.*395,8.*Rapprochement/s);await page.locator('#close-proof').click();checks.push({label:'écart publié visible et expliqué'});
    await select('perimeter','ROBSS');
    await view('ONDAM');
    for(let year=2017;year<=2027;year++){await select('start',String(year));await select('end',String(year));await verify('ONDAM '+year);}
    await select('start','2019');await select('end','2019');
    await page.locator('#matrix tbody tr').first().locator('.amount').last().click();await page.locator('#proof').waitFor({state:'visible'});assert.match(await page.locator('#proof-content').textContent(),/PDF, page 74/);assert.match(await page.locator('#proof-content a').last().getAttribute('href'),/#page=74$/);await page.locator('#close-proof').click();
    // Simulated delays check the visible central timer for both proofs and exports.
    await page.route('**/api/proof?*',async route=>{await new Promise(r=>setTimeout(r,1300));await route.continue();});
    await page.locator('#matrix tbody tr').first().locator('.amount').last().click();await page.locator('#busy').waitFor({state:'visible'});await page.waitForTimeout(1050);assert.notEqual(await page.locator('#elapsed').textContent(),'00:00');const box=await page.locator('#busy').boundingBox();assert.ok(Math.abs(box.x+box.width/2-720)<3);await page.locator('#proof').waitFor({state:'visible'});await page.locator('#close-proof').click();await page.unroute('**/api/proof?*');checks.push({label:'compteur central des preuves'});
    const checked=page.locator('#matrix [data-entity]').first();const matrixResponse=page.waitForResponse(r=>r.url().includes('/api/matrix?'));await checked.uncheck();await matrixResponse;await idle();await verify('exclusion ONDAM');
    await page.route('**/api/export?*',async route=>{await new Promise(r=>setTimeout(r,1300));await route.continue();});
    const downloading=page.waitForEvent('download');await page.locator('#export').click();await page.locator('#busy').waitFor({state:'visible'});const download=await downloading;await download.saveAs(path.join(root,'reports/browser-export.xlsx'));await idle();await page.unroute('**/api/export?*');checks.push({label:'export Excel et compteur'});
    await view('DOCUMENTS');const before=await page.locator('.doc-row').count();await page.locator('#more-docs').click();await idle();assert.ok(await page.locator('.doc-row').count()>before);checks.push({label:'pagination documentaire'});
    for(const year of ['2017','2026','2027']){const response=page.waitForResponse(r=>r.url().includes('/api/documents?'));await page.locator('#doc-year').selectOption(year);await response;await idle();const text=await page.locator('.doc-row .hint').allTextContents();assert.ok(text.length>0);assert.ok(text.every(t=>t.includes('Millésime '+year)));checks.push({label:'documents '+year});}
    const titlesResponse=page.waitForResponse(r=>r.url().includes('/api/documents?'));await page.locator('#doc-mode').selectOption('titles');await titlesResponse;await idle();
    const queryResponse=page.waitForResponse(r=>r.url().includes('/api/documents?'));await page.locator('#doc-query').fill('aucune-reference-inexistante-xyz');await page.locator('#doc-search button').click();await queryResponse;await idle();assert.equal(await page.locator('.doc-row').count(),0);checks.push({label:'aucun résultat documentaire expliqué'});
    await page.locator('#doc-query').fill('ONDAM');
    const hybridResponse=page.waitForResponse(r=>r.url().includes('/api/search?'));await page.locator('#doc-mode').selectOption('hybrid');await hybridResponse;await idle();assert.ok(await page.locator('.search-hit').count()>0);assert.ok((await page.locator('.search-hit .hint').allTextContents()).every(t=>t.startsWith('Millésime 2027')));checks.push({label:'recherche vectorielle dans les documents 2027'});
    const passageResponse=page.waitForResponse(r=>r.url().includes('/api/passage/'));await page.locator('[data-passage]').first().click();await passageResponse;await page.locator('#proof').waitFor({state:'visible'});assert.ok((await page.locator('.passage-text').textContent()).length>20);assert.match(await page.locator('#proof-title').textContent(),/Passage documentaire/);await page.locator('#close-proof').click();checks.push({label:'passage complet avec repères'});
    const oldYearResponse=page.waitForResponse(r=>r.url().includes('/api/search?'));await page.locator('#doc-year').selectOption('2017');await oldYearResponse;await idle();assert.ok(await page.locator('.search-hit').count()>0);assert.ok((await page.locator('.search-hit .hint').allTextContents()).every(t=>t.startsWith('Millésime 2017')));checks.push({label:'filtre documentaire 2017 après recherche 2027'});
    await view('COVERAGE');assert.match(await page.locator('#coverage').textContent(),/ne signifie pas que tous ses tableaux/);assert.match(await page.locator('#coverage-summary').textContent(),/311\s*791/);checks.push({label:'couverture et limites'});
    await page.locator('#reset').click();await idle();await page.locator('#matrix table').waitFor();await verify('réinitialisation depuis couverture');
    await page.screenshot({path:path.join(root,'reports/plfss-desktop.png'),fullPage:false});
    await page.setViewportSize({width:390,height:900});await page.screenshot({path:path.join(root,'reports/plfss-mobile.png'),fullPage:false});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Page déborde sur mobile');
    const brand=await page.locator('.brand img').boundingBox();assert.ok(brand.width<100,'Logo mobile agrandi');
    checks.push({label:'présentation ordinateur et téléphone'});
    assert.deepEqual(errors,[]);
    assert.equal((await (await page.request.get(base+'/api/meta')).json()).data_version,capturedVersion,'Base modifiée pendant les parcours');
    fs.writeFileSync(path.join(root,'reports/browser-check.json'),JSON.stringify({passed:true,data_version:capturedVersion,checks,errors,base},null,2));
    console.log(JSON.stringify({passed:true,scenarios:checks.length,cells:checks.reduce((n,c)=>n+(c.cells||0),0),errors}));
  } catch(error) {
    fs.writeFileSync(path.join(root,'reports/browser-check.json'),JSON.stringify({passed:false,checks,errors,error:String(error)},null,2));
    throw error;
  } finally {await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});

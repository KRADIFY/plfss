'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const demoBase = new URL('.', document.currentScript.src);
  const baseline = {view:'EQUILIBRE',perimeter:'ROBSS',metric:'DEPENSES',start:2026,end:2027,unit:1000000000,entity:'',panel:null};
  let snapshot, config, narration, player, driver, activeJourney, frenchVoice;
  let state = {...baseline}, lastTarget = null, frame = null, demoEnabled = true;
  const cells = new Map();
  const money = (cents, exact = false) => cents == null ? '' : new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits:exact || state.unit === 1 ? 2 : 1,
    maximumFractionDigits:exact || state.unit === 1 ? 2 : 1
  }).format(cents / 100 / (exact ? 1 : state.unit));
  const fold = s => String(s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const safe = value => { try { const u=new URL(value); return ['http:','https:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } };
  const matrix = () => snapshot.matrices[state.view === 'ONDAM' ? 'ONDAM|ROBSS|DEPENSES' : `EQUILIBRE|${state.perimeter}|${state.metric}`];
  const columns = () => matrix().columns.map((col,index)=>({...col,index})).filter(c=>c.year>=state.start&&c.year<=state.end);
  const selectedRow = () => matrix().rows.find(r=>r.entity===state.entity) || matrix().total;
  const observed = new ResizeObserver(() => scheduleFit());

  function visible(enabled) {
    demoEnabled=enabled;
    document.body.classList.toggle('demo-closed',!enabled);
    $('demo-player').hidden=!enabled; $('exit-demo').hidden=!enabled; $('welcome').hidden=!enabled;
    $('reopen-demo').setAttribute('aria-expanded',String(enabled));
  }
  function returnToSite() {
    player.stop();
    if (window.parent!==window) {
      window.parent.postMessage({type:'plfss-demo:close'},window.location.origin);
      visible(false);
    } else window.location.assign(snapshot.source+'/?demo=off');
  }
  function amount(cell,col,entity) {
    const key=`${entity}|${col.year}|${col.stage}`;
    cells.set(key,{cell,col,entity});
    const missing=cell.amount_cents==null;
    return `<td><button type="button" class="amount demo-cell ${missing?'demo-missing':''}" data-cell="${esc(key)}" aria-haspopup="dialog">${missing?(cell.status==='divergence'?'Écart entre sources<br>Consulter ⓘ':'Donnée non renseignée<br>Pourquoi ? ⓘ'):(cell.status==='partial'?'* ':'')+esc(money(cell.amount_cents))}</button>${cell.source_notices?.length?'<span class="source-warning">Écart dans la publication · consulter</span>':''}</td>`;
  }
  function renderTable() {
    cells.clear();
    const m=matrix(), cols=columns();
    const rows=state.entity ? [selectedRow()] : [m.total,...m.rows];
    $('matrix').innerHTML='<table><thead><tr><th>Poste</th>'+cols.map(c=>`<th>${c.year}<br>${esc(c.label)}</th>`).join('')+'</tr></thead><tbody>'+rows.map((r,index)=>`<tr class="${!state.entity&&index===0?'total':''}"><td>${r.entity===m.total.entity?esc(r.label):`<button class="demo-row" data-entity="${esc(r.entity)}">${esc(r.label)}</button>`}</td>${cols.map(c=>amount(r.cells[c.index],c,r.entity)).join('')}</tr>`).join('')+'</tbody></table>';
    $('matrix-note').textContent=m.note;
    $('scope-title').textContent=state.entity?selectedRow().label:state.view==='ONDAM'?'Les sous-objectifs, en détail':'Les branches, en détail';
    $('unit-label').textContent=({1:'€',1000000:'M€',1000000000:'Md€'})[state.unit];
  }
  function proofHtml(item) {
    if (!item) return '<p>Choisissez un montant pour consulter ses références.</p>';
    const {cell,col,entity}=item;
    const refs=cell.references.map(id=>snapshot.proofs[String(id)]).filter(Boolean);
    const heading=`${col.year} · ${col.label} · ${snapshot.meta.perimeters[state.perimeter]} · ${snapshot.meta.metrics[state.metric]}`;
    return `<p>${esc(heading)}</p><p class="demo-exact">${cell.amount_cents==null?'Donnée non renseignée':esc(money(cell.amount_cents,true))+' €'}</p>${cell.reason?`<p class="demo-source-status">${esc(cell.reason)}</p>`:''}`+refs.map(p=>{
      const suffix=p.page_number?'#page='+p.page_number:'';
      const position=p.sheet?`${p.sheet} ! ${p.cell}`:`${p.page_number?'PDF, page '+p.page_number+' · ':''}Tableau ${p.table_index+1}, ligne ${p.row_index+1}, colonne ${p.column_index+1}`;
      const official=safe(p.source.url.split('#')[0]+suffix);
      return `<article class="proof-card"><strong>${esc(p.exercise)} · ${esc(snapshot.meta.stages[p.stage])} · ${esc(p.row_label)}</strong>${(p.source_notices||[]).map(n=>`<p class="source-notice">${esc(n.explanation)}</p>`).join('')}<dl><dt>Valeur publiée</dt><dd>${esc(p.raw)} × ${esc(new Intl.NumberFormat('fr-FR').format(p.unit_eur))} €</dd><dt>Document</dt><dd>${esc(p.source.title)}</dd><dt>Position</dt><dd>${esc(position)}</dd><dt>Contexte</dt><dd>${esc(p.context)}</dd></dl><div class="proof-links">${official?`<a href="${esc(official)}" target="_blank" rel="noopener noreferrer">Publication officielle ↗</a>`:''}<a href="${esc(snapshot.source)}/documents/${encodeURIComponent(p.source_id)}${suffix}" target="_blank" rel="noopener noreferrer">Copie conservée ↗</a></div></article>`;
    }).join('')+(!refs.length&&cell.amount_cents!=null?'<p>Les identifiants de preuve sont conservés dans cet exemple. Leur consultation complète se fait sur <a href="'+esc(snapshot.source)+'/?demo=off">PLFSS ↗</a>.</p>':'')+'<p class="demo-proof-note">Copie datée du '+esc(new Date(snapshot.captured_at).toLocaleDateString('fr-FR'))+'. Les publications futures restent distinctes des montants nuls.</p>';
  }
  function currentProof() {
    const m=matrix(), r=selectedRow(), col=m.columns.findIndex(c=>c.year===2027&&c.stage==='PLFSS');
    return {cell:r.cells[col],col:m.columns[col],entity:r.entity};
  }
  function exportHtml() {
    return '<p>Sur PLFSS, choisissez Excel ou CSV pour exporter les montants du périmètre affiché et leurs références.</p><p>Gardez l’exercice, le périmètre, la branche ou le sous-objectif, l’indicateur et l’étape avec chaque montant. L’export conserve les blancs et les zéros distincts.</p><p class="demo-source-status">Cette démonstration fournit uniquement un petit CSV de son exemple daté.</p><button type="button" class="secondary" id="download-example">Télécharger l’exemple CSV</button>';
  }
  function renderDocuments() {
    const query=fold($('doc-query').value),year=$('doc-year').value,family=$('doc-family').value;
    const docs=snapshot.documents.items.filter(d=>(!year||String(d.publication_year)===year)&&(!family||d.family===family)&&fold(d.title).includes(query));
    $('document-count').textContent=docs.length+' documents dans l’exemple';
    $('documents').innerHTML='<p class="doc-mode-note">Exemple daté : recherche dans les titres des pièces présentées. La recherche complète dans le contenu reste disponible sur PLFSS.</p>'+docs.map(d=>`<article class="doc-row"><div><p><strong>${esc(d.title)}</strong></p><p class="hint">Millésime ${d.publication_year} · ${esc(d.family)}</p></div><div class="doc-links">${safe(d.url)?`<a href="${esc(safe(d.url))}" target="_blank" rel="noopener noreferrer">Source ↗</a>`:''}<a href="${esc(snapshot.source)}/documents/${encodeURIComponent(d.id)}" target="_blank" rel="noopener noreferrer">Copie conservée ↗</a></div></article>`).join('')+(docs.length?'':'<p class="empty">Aucun titre retrouvé dans cet exemple. Consultez la bibliothèque complète sur PLFSS.</p>');
  }
  function renderCoverage() {
    const meta=snapshot.meta;
    $('coverage-summary').innerHTML=[['Fichiers récupérés',meta.files],['Observations chiffrées',meta.facts],['Passages indexés',meta.indexed_passages]].map(([label,count])=>`<div class="metric"><span>${label}</span><strong>${count.toLocaleString('fr-FR')}</strong></div>`).join('');
    $('coverage').innerHTML='<div id="coverage-explanation"><h3>Des sources visibles, des limites explicites</h3><p>'+esc(meta.publication_note)+'</p><dl><dt><strong>Zéro publié</strong></dt><dd>La source établit un montant nul.</dd><dt><strong>Donnée non renseignée</strong></dt><dd>La case garde une explication ; elle ne devient pas zéro.</dd><dt><strong>Écart entre publications</strong></dt><dd>Consulter les valeurs et leurs notices avant de conclure.</dd><dt><strong>Détail d’annexe</strong></dt><dd>Un document collecté ou indexé n’implique pas que tous ses tableaux sont qualifiés.</dd></dl><p>Le millésime d’un document et l’exercice d’un montant sont distincts. L’ONDAM n’est pas ajouté aux comptes des branches.</p></div>';
  }
  function render() {
    for (const id of ['perimeter','metric','start','end','unit']) $(id).value=String(state[id]);
    $('stage-mode').value='PLFSS,LFSS,CONSTATE';
    const ondam=state.view==='ONDAM';
    $('perimeter').disabled=ondam; $('metric').disabled=ondam;
    document.querySelectorAll('[data-view]').forEach(b=>{const active=b.dataset.view===state.view;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    $('numbers-view').hidden=!['EQUILIBRE','ONDAM'].includes(state.view);
    $('documents-view').hidden=state.view!=='DOCUMENTS'; $('coverage-view').hidden=state.view!=='COVERAGE';
    $('export').disabled=!['EQUILIBRE','ONDAM'].includes(state.view);
    $('view-title').textContent=({EQUILIBRE:'L’évolution des comptes sociaux.',ONDAM:'Les dépenses sous ONDAM.',DOCUMENTS:'Les documents derrière les comptes.',COVERAGE:'Les sources et leur couverture.'})[state.view];
    $('branch').innerHTML='<option value="">Tous les postes</option>'+matrix().rows.map(r=>`<option value="${esc(r.entity)}">${esc(r.label)}</option>`).join(''); $('branch').value=state.entity;
    renderTable(); renderDocuments(); renderCoverage();
    $('automatic-panel').hidden=!state.panel;
    if(state.panel){$('automatic-title').textContent=state.panel==='proof'?'La preuve du montant':'Préparer un export';$('automatic-content').innerHTML=state.panel==='proof'?proofHtml(currentProof()):exportHtml();}
  }
  const captionLayout = placeTourPopover.createController();
  function fitPopover() {
    const popover=document.querySelector('.driver-popover');
    if(!popover || !lastTarget?.isConnected) return;
    captionLayout.fit({target:lastTarget,popover,player:$('demo-player'),exit:$('exit-demo'),refresh:()=>driver.refresh()});
  }
  function scheduleFit(){if(frame!=null)return;frame=requestAnimationFrame(()=>{frame=null;fitPopover();});}
  function showStep(step,index,total){
    captionLayout.reset();
    if($('proof').open)$('proof').close();
    $('welcome').hidden=true;
    state={...baseline,...step.state};
    if(state.view==='ONDAM'){state.metric='DEPENSES';state.perimeter='ROBSS';}
    render();
    const target=document.querySelector(step.target);
    if(!target||target.closest('[hidden]'))throw new Error('Cible absente : '+step.id);
    lastTarget=target;
    target.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
    driver.highlight({element:target,popover:{title:step.title,description:`<p>${esc(step.text)}</p><p class="demo-tour-hint">${index+1} / ${total} · ${esc(activeJourney.title)}<br>Lecture, pause, stop et déplacements : commandes dans le lecteur flottant.</p>`,side:state.panel?'left':'bottom',align:'start'}});
    requestAnimationFrame(()=>{driver.refresh();fitPopover();});
    document.documentElement.dataset.currentStep=step.id;
  }

  const recorded=new RecordedVoice({createAudio:src=>new Audio(src)});
  let utterance=null,voiceMode=null;
  const voiceAdapter={
    speak(text,callbacks,step){
      const item=narration.steps[step.id];
      if(item&&item.text===text){voiceMode='recorded';return recorded.speak({...item,src:new URL(item.src.replace(/^\//,''),demoBase).href},callbacks);}
      if(!window.speechSynthesis||!frenchVoice)return false;
      voiceMode='browser';window.speechSynthesis.cancel();window.speechSynthesis.resume();
      const speech=new SpeechSynthesisUtterance(text);utterance=speech;speech.lang='fr-FR';speech.voice=frenchVoice;speech.rate=.95;
      speech.onend=()=>{if(utterance===speech){utterance=null;callbacks.end();}};
      speech.onerror=()=>{if(utterance===speech){utterance=null;callbacks.error();}};
      window.speechSynthesis.speak(speech);return true;
    },
    cancel(){utterance=null;voiceMode=null;recorded.cancel();window.speechSynthesis?.cancel();},
    pause(){if(voiceMode==='recorded')recorded.pause();else window.speechSynthesis?.pause();},
    resume(){if(voiceMode==='recorded')recorded.resume();else window.speechSynthesis?.resume();}
  };
  function voiceList(){
    const voices=window.speechSynthesis?.getVoices().filter(v=>/^fr[-_]/i.test(v.lang))||[];
    frenchVoice=voices.find(v=>v.localService&&/natural|naturel/i.test(v.name))||voices.find(v=>v.localService&&v.lang.toLowerCase()==='fr-fr')||voices.find(v=>v.localService);
    const complete=config.steps.every(s=>narration.steps[s.id]?.text===s.text);
    $('voice-status').textContent=complete?'Les trois parcours utilisent la voix enregistrée. Les explications restent visibles.':frenchVoice?'Voix provisoire du navigateur ; la voix enregistrée pourra la remplacer. Vous pouvez couper le son.':'Les explications restent visibles. Les textes sont prêts pour l’enregistrement de la voix.';
  }
  function updateControls(info){
    document.body.dataset.playback=info.status;
    $('tour-progress').max=info.total;$('tour-progress').value=info.status==='stopped'?0:info.index+1;
    $('start-tour').disabled=info.status==='playing';$('start-tour').textContent=info.status==='paused'?'▶ Reprendre':info.status==='ended'?'▶ Rejouer':'▶ Lecture';
    $('pause').disabled=info.status!=='playing';$('stop').disabled=info.status==='stopped';$('previous').disabled=info.index===0;$('next').disabled=info.index===info.total-1;
    $('voice').innerHTML='<svg class="voice-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4Z"/>'+(info.muted?'<path d="m16 9 6 6m0-6-6 6"/>':'<path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>')+'</svg><span>'+(info.muted?'Voix coupée':'Voix activée')+'</span>';
    $('voice').setAttribute('aria-pressed',String(!info.muted));$('voice').title=info.muted?'Activer la voix':'Couper la voix';
    $('player-status').textContent=info.status==='stopped'?'Prêt · '+activeJourney.title:info.status==='ended'?'Parcours terminé · rejouer ou ouvrir PLFSS':`${info.status==='paused'?'En pause':'Lecture'} · ${info.index+1} / ${info.total} · ${activeJourney.title}`;
  }
  function chooseJourney(id,index=0){
    const journey=config.journeys.find(j=>j.id===id);if(!journey)return;
    visible(true);activeJourney=journey;player.setSteps(journey.steps.map(id=>config.steps.find(s=>s.id===id)));player.seek(index,true);
  }
  function stopForInteraction(){player.pause();captionLayout.reset(); driver.destroy();state.panel=null;}
  function dialog(title,content){stopForInteraction();$('automatic-panel').hidden=true;$('proof-title').textContent=title;$('proof-content').innerHTML=content;$('proof').showModal();}
  function csvDownload(){
    const quote=v=>'"'+String(v??'').replace(/^[=+@]/,"'$&").replace(/"/g,'""')+'"';
    const r=selectedRow(),cols=columns();
    const rows=[['EXEMPLE DATE',snapshot.captured_at],['Exercice','Étape','Périmètre','Poste','Indicateur','Montant EUR','Statut','Preuves']];
    for(const c of cols){const cell=r.cells[c.index];rows.push([c.year,c.label,snapshot.meta.perimeters[state.perimeter],r.label,snapshot.meta.metrics[state.metric],cell.amount_cents==null?'':(cell.amount_cents/100).toFixed(2).replace('.',','),cell.status,cell.references.join(',')]);}
    const url=URL.createObjectURL(new Blob(['\ufeff'+rows.map(row=>row.map(quote).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download='PLFSS-DEMO-exemple-date.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function initialize(){
    const responses=await Promise.all(['snapshot.json','parcours.json','narration.json'].map(p=>fetch(new URL(p,demoBase))));
    if(responses.some(r=>!r.ok))throw new Error('Fichiers de démonstration indisponibles.');
    [snapshot,config,narration]=await Promise.all(responses.map(r=>r.json()));
    const ids=new Set(config.steps.map(s=>s.id));
    if(ids.size!==config.steps.length||config.journeys.some(j=>j.steps.some(id=>!ids.has(id))))throw new Error('Parcours incohérent.');
    for(const year of [2023,2024,2025,2026,2027])for(const id of ['start','end'])$(id).add(new Option(String(year),String(year)));
    $('doc-year').add(new Option('2027','2027'));$('doc-year').value='2027';
    for(const family of new Set(snapshot.documents.items.map(d=>d.family)))$('doc-family').add(new Option(family,family));
    $('doc-mode').value='titles';for(const option of $('doc-mode').options)option.disabled=option.value!=='titles';
    for(const option of $('stage-mode').options)option.disabled=option.value!=='PLFSS,LFSS,CONSTATE';
    $('headline').textContent=`${snapshot.meta.indexed_passages.toLocaleString('fr-FR')} passages indexés et sourçables dans ${snapshot.meta.indexed_documents.toLocaleString('fr-FR')} documents`;
    $('snapshot-date').textContent='Exemple capturé le '+new Date(snapshot.captured_at).toLocaleDateString('fr-FR')+'. Les données actualisées se consultent sur PLFSS.';
    driver=window.driver.js.driver({animate:!matchMedia('(prefers-reduced-motion:reduce)').matches,smoothScroll:false,allowClose:false,allowKeyboardControl:false,disableActiveInteraction:true,overlayColor:'#08183f',overlayOpacity:.28,popoverClass:'demo-popover',stagePadding:7,stageRadius:8,showButtons:[],overlayClickBehavior:'none',onPopoverRender:p=>{observed.disconnect();observed.observe(p.wrapper);observed.observe($('demo-player'));scheduleFit();}});
    activeJourney=config.journeys[0];
    player=new DemoPlayer({steps:activeJourney.steps.map(id=>config.steps.find(s=>s.id===id)),voice:voiceAdapter,onStep:showStep,onState:updateControls,onVoiceError:()=>{$('player-status').textContent+=' · lecture du texte';},onExit:reason=>{captionLayout.reset(); driver.destroy();observed.disconnect();state={...baseline};if($('proof').open)$('proof').close();render();$('welcome').hidden=!demoEnabled;document.documentElement.dataset.currentStep=reason;}});
    const icons=['<path d="m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6Z"/>','<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6m-14-11 2 2 4-4"/>','<path d="M12 3v18M3 12h18"/><path d="M7 5h10v14H7Z"/>'];
    $('journeys').innerHTML=config.journeys.map((j,i)=>`<button class="demo-journey" data-journey="${esc(j.id)}"><span class="journey-top"><span class="journey-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[i]}</svg></span><span class="journey-number">0${i+1}</span></span><strong>${esc(j.title)}</strong><span class="journey-summary">${esc(j.summary)}</span><span class="journey-bottom"><small>${j.steps.length} étapes</small><b aria-hidden="true">▶</b></span></button>`).join('');
    for(const id of ['start','end','unit','perimeter','metric','branch'])$(id).addEventListener('change',()=>{stopForInteraction();const key=id==='branch'?'entity':id;state[key]=['start','end','unit'].includes(key)?Number($(id).value):$(id).value;if(state.start>state.end)state[id==='start'?'end':'start']=state[id];if(id==='perimeter')state.entity='';render();});
    $('document-filters').addEventListener('submit',event=>{event.preventDefault();renderDocuments();});
    for(const id of ['doc-year','doc-family'])$(id).addEventListener('change',renderDocuments);
    $('reset').addEventListener('click',()=>{stopForInteraction();state={...baseline};render();});
    $('start-tour').addEventListener('click',()=>{visible(true);$('welcome').hidden=true;player.play();});
    $('pause').addEventListener('click',()=>player.pause());$('stop').addEventListener('click',()=>player.stop());$('previous').addEventListener('click',()=>player.previous());$('next').addEventListener('click',()=>player.next());
    $('voice').addEventListener('click',()=>player.setMuted(!player.muted));
    $('exit-demo').addEventListener('click',returnToSite);$('reopen-demo').addEventListener('click',()=>{player.stop();visible(true);});
    $('close-proof').addEventListener('click',()=>{$('proof').close();if(player.status==='paused')player.seek(player.index,false);});
    $('export').addEventListener('click',()=>dialog('Exporter les données',exportHtml()));
    $('chapters').disabled=false;$('chapters').addEventListener('click',()=>{player.stop();visible(true);});
    document.addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;if(b.dataset.journey)chooseJourney(b.dataset.journey);else if(b.dataset.view){stopForInteraction();state.view=b.dataset.view;state.entity='';if(state.view==='ONDAM'){state.perimeter='ROBSS';state.metric='DEPENSES';}render();}else if(b.dataset.cell)dialog('Traçabilité du montant',proofHtml(cells.get(b.dataset.cell)));else if(b.dataset.entity){stopForInteraction();state.entity=b.dataset.entity;render();}else if(b.id==='download-example')csvDownload();});
    document.addEventListener('keydown',event=>{if(!demoEnabled||$('proof').open||/INPUT|SELECT|TEXTAREA/.test(event.target.tagName))return;if(event.key==='Escape')player.stop();if(event.key==='ArrowRight'&&player.status!=='stopped'){event.preventDefault();player.next();}if(event.key==='ArrowLeft'&&player.status!=='stopped'){event.preventDefault();player.previous();}if(event.key===' '&&event.target===document.body){event.preventDefault();player.status==='playing'?player.pause():player.play();}});
    document.addEventListener('visibilitychange',()=>{if(document.hidden)player.pause();});window.addEventListener('pagehide',()=>player.stop());
    window.addEventListener('resize',()=>{if(driver.isActive()){driver.refresh();fitPopover();}});window.addEventListener('scroll',scheduleFit,{capture:true,passive:true});window.visualViewport?.addEventListener('resize',scheduleFit);
    window.speechSynthesis?.addEventListener('voiceschanged',voiceList);voiceList();render();player.emit();document.documentElement.dataset.demoReady='true';
  }
  initialize().catch(error=>{$('error').hidden=false;$('error').textContent='La démo n’a pas pu être chargée : '+error.message;});
})();

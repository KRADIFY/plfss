/* Anonymous audience aggregates shared by PLF and PLFSS; no persistent visitor ID. */
(() => {
 'use strict';
 if(window.top!==window)return; // PLF's embedded demo is already counted by its parent.
 let optedOut=false;
 try { optedOut=localStorage.getItem('nos-deniers-audience-off')==='1'; } catch {}
 if(optedOut || navigator.doNotTrack==='1' || navigator.webdriver || !crypto.getRandomValues) return;
 const social=location.hostname==='plfss.lexmachine.net';
 const aliases={credits:'credits',ecologie:'ecology',maprimerenov:'maprimerenov',movements:'movements',documents:'documents',coverage:'coverage',EQUILIBRE:'credits',ONDAM:'credits',DOCUMENTS:'documents',COVERAGE:'coverage'};
 const handoffKey='nos-deniers-audience-demo-handoff';
 function readHandoff(){
  if(!social || location.pathname!=='/' || new URL(location.href).searchParams.get('demo')!=='off')return null;
  try{
   const raw=sessionStorage.getItem(handoffKey);sessionStorage.removeItem(handoffKey);
   if(!raw)return null;const h=JSON.parse(raw),age=Date.now()-h.saved_at;
   if(age<0||age>120000||!(/^[a-f0-9]{32}$/).test(h.id)||!Number.isInteger(h.seq)||h.seq<0||h.seq>10000000)return null;
   if(!['direct','parliament','search','social','other'].includes(h.origin)||!Object.values(aliases).includes(h.view))return null;
   if(!h.counters||!Object.keys(h.counters).length||!Object.entries(h.counters).every(([key,v])=>Object.values(aliases).includes(key)&&Array.isArray(v)&&v.length===2&&v.every(n=>Number.isInteger(n)&&n>=0)&&v[0]<=100000&&v[1]<=3000000000))return null;
   return h;
  }catch{return null;}
 }
 function inheritedExclusion(){
  if(!social)return Promise.resolve(false);
  return new Promise(resolve=>{
   const frame=document.createElement('iframe');frame.hidden=true;frame.title='Préférence de mesure d’audience';
   const source='https://budget.lexmachine.net';let finished=false;
   const finish=(excluded,knownPreference=false)=>{
    if(finished)return;finished=true;clearTimeout(timer);removeEventListener('message',receive);frame.remove();
    if(excluded&&knownPreference)try{localStorage.setItem('nos-deniers-audience-off','1');}catch{}
    resolve(excluded);
   };
   const receive=event=>{
    if(event.origin!==source||event.source!==frame.contentWindow||event.data?.type!=='nos-deniers-audience:preference')return;
    if(typeof event.data.excluded!=='boolean'||typeof event.data.available!=='boolean')return;
    finish(!event.data.available||event.data.excluded,event.data.available&&event.data.excluded);
   };
   const timer=setTimeout(()=>finish(true),5000); // Never count before the exclusion is known.
   addEventListener('message',receive);
   frame.addEventListener('load',()=>{if(!finished)frame.contentWindow.postMessage({type:'nos-deniers-audience:request'},source);});
   frame.addEventListener('error',()=>finish(true));
   frame.src=source+'/activity/exclusion-bridge';document.body.append(frame);
  });
 }
 const start=()=>{
  const resumed=readHandoff(),bytes=crypto.getRandomValues(new Uint8Array(16));
  const id=resumed?.id||Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');
  const counters=resumed?.counters||{};
  let current=resumed?.view||'credits',seq=resumed?.seq||0,last=performance.now(),lastInput=last,stopped=false,visible=document.visibilityState==='visible';
  const origin=resumed?.origin||(()=>{
   let host='';try{host=new URL(document.referrer).hostname;}catch{}
   if(!host||host===location.hostname)return 'direct';
   if(/(^|\.)(assemblee-nationale\.fr|senat\.fr|europarl\.europa\.eu)$/.test(host))return 'parliament';
   if(/(^|\.)(google\.[a-z.]+|bing\.com|duckduckgo\.com|yahoo\.com)$/.test(host))return 'search';
   if(/(^|\.)(linkedin\.com|facebook\.com|t\.co|x\.com|bsky\.app)$/.test(host))return 'social';
   return 'other';
  })();
  const selected=()=>{const b=document.querySelector('.nav button.active');return aliases[b?.dataset.pilot||b?.dataset.view]||'credits';};
  const active=()=>visible&&performance.now()-lastInput<120000;
  const tick=()=>{
   const now=performance.now(),elapsed=now-last;
   if(!stopped&&active()&&elapsed>=0&&elapsed<=15000)counters[current][1]+=Math.round(elapsed);
   last=now;
  };
  const change=()=>{
   const next=selected();if(next===current)return;
   tick();current=next;counters[current]??=[0,0];counters[current][0]++;
  };
  const send=(closing=false)=>{
   if(stopped)return;tick();change();
   const body=JSON.stringify({id,seq:seq++,view:current,active:!closing&&active(),origin,counters});
   if(closing&&navigator.sendBeacon){navigator.sendBeacon('/activity/event',new Blob([body],{type:'application/json'}));return;}
   fetch('/activity/event',{method:'POST',body,headers:{'Content-Type':'application/json'},credentials:'omit',keepalive:true}).catch(()=>{});
  };
  if(resumed)change();else{current=selected();counters[current]=[1,0];}
  ['pointerdown','keydown','scroll','touchstart','mousemove'].forEach(type=>addEventListener(type,()=>{tick();lastInput=performance.now();},{passive:true}));
  const nav=document.querySelector('.nav');
  if(nav)new MutationObserver(change).observe(nav,{subtree:true,attributes:true,attributeFilter:['class','aria-current']});
  document.addEventListener('visibilitychange',()=>{tick();visible=document.visibilityState==='visible';last=performance.now();if(visible)lastInput=last;send(!visible);});
  addEventListener('pagehide',()=>send(true));
  addEventListener('pageshow',e=>{if(e.persisted){last=performance.now();lastInput=last;send();}});
  addEventListener('storage',e=>{if(e.key==='nos-deniers-audience-off'&&e.newValue==='1'){send(true);stopped=true;}});
  if(social && location.pathname==='/demo/')addEventListener('click',e=>{
   if(!e.target.closest('#exit-demo, a[href="https://plfss.lexmachine.net/?demo=off"]'))return;
   send(true);stopped=true;
   try{sessionStorage.setItem(handoffKey,JSON.stringify({id,seq,view:current,origin,counters,saved_at:Date.now()}));}catch{}
  },true);
  setInterval(tick,5000);
  setInterval(()=>{if(document.visibilityState==='visible')send();},30000);
  send();
 };
 const ready=async()=>{
  if(await inheritedExclusion())return;
  try{if(localStorage.getItem('nos-deniers-audience-off')==='1')return;}catch{}
  start();
 };
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready,{once:true});else ready();
})();

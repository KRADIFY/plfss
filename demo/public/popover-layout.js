/* Keep tour captions inside the viewport area above the floating player. */
(function (root) {
  function placePopover({anchorTop, anchorBottom, height, playerTop, viewportHeight, side = 'bottom'}) {
    const gap = 14;
    const bottom = Math.max(gap + 1, Math.min(playerTop, viewportHeight) - gap);
    const maxHeight = Math.max(1, bottom - gap);
    const visibleHeight = Math.min(height, maxHeight);
    let top = side === 'left' ? anchorTop : anchorBottom + gap;
    if (top + visibleHeight > bottom && anchorTop - gap - visibleHeight >= gap) {
      top = anchorTop - gap - visibleHeight;
    }
    top = Math.max(gap, Math.min(top, bottom - visibleHeight));
    return {top, maxHeight};
  }
  // Measure the actual rendered text; widen only when the available height needs it.
  placePopover.fitWidth = function ({viewportWidth, maxHeight, measure}) {
    const maximum = Math.max(1, Math.min(640, viewportWidth - 28));
    let width = Math.min(380, maximum);
    let height = measure(width);
    while (height > maxHeight && width < maximum) {
      width = Math.min(maximum, width + 40);
      height = measure(width);
    }
    return {width, height};
  };

  const gap = 14;
  const intersects = (a,b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  const box = (left,top,width,height) => ({left,top,right:left+width,bottom:top+height,width,height});
  // Try every outside edge, not just a vertical clamp through the example.
  placePopover.findSpace = function ({anchor,width,height,bounds,obstacles=[]}) {
    const clamp=(n,min,max)=>Math.max(min,Math.min(n,max));
    const xs=[clamp(anchor.left,bounds.left,bounds.right-width),bounds.right-width,bounds.left];
    const ys=[clamp(anchor.top,bounds.top,bounds.bottom-height),bounds.top,bounds.bottom-height];
    const candidates=[];
    for(const x of xs) {candidates.push(box(x,anchor.bottom+gap,width,height),box(x,anchor.top-gap-height,width,height));}
    for(const y of ys) {candidates.push(box(anchor.right+gap,y,width,height),box(anchor.left-gap-width,y,width,height));}
    for(const x of xs)for(const y of ys)candidates.push(box(x,y,width,height));
    return candidates.find(r=>r.left>=bounds.left && r.right<=bounds.right && r.top>=bounds.top && r.bottom<=bounds.bottom && ![anchor,...obstacles].some(a=>intersects(r,a))) || null;
  };
  // A temporary layout belongs to one step. All inline properties are restored
  // before the next step, when stopping, or when opening an interactive dialog.
  placePopover.createController = function () {
    let current=null,host=null,docked=false,initialWidth=0,originalScroll=null,lastSize=null;
    const saved=new Map();
    function set(el,name,value) {
      if(!saved.has(el))saved.set(el,new Map());
      const props=saved.get(el);
      if(!props.has(name))props.set(name,[el.style.getPropertyValue(name),el.style.getPropertyPriority(name)]);
      if(el.style.getPropertyValue(name)!==value || el.style.getPropertyPriority(name)!=='important')el.style.setProperty(name,value,'important');
    }
    function reset() {
      for(const [el,props] of saved)for(const [name,[value,priority]] of props){if(value)el.style.setProperty(name,value,priority);else el.style.removeProperty(name);}
      if(host&&originalScroll){host.scrollLeft=originalScroll.left;host.scrollTop=originalScroll.top;}
      saved.clear();current=null;host=null;docked=false;originalScroll=null;lastSize=null;
    }
    function fit({target,popover,player,exit,refresh}) {
      if(current!==target){reset();current=target;}
      const vw=document.documentElement.clientWidth,vh=window.visualViewport?.height||window.innerHeight;
      const playerRect=player.getBoundingClientRect();
      const exitRect=exit&&!exit.hidden?exit.getBoundingClientRect():null;
      const top=exitRect?Math.max(gap,exitRect.bottom+gap):gap;
      const bottom=Math.min(vh,playerRect.top)-gap;
      const bounds={left:gap,right:vw-gap,top,bottom};
      const description=popover.querySelector('.driver-popover-description');
      popover.style.removeProperty('--tour-description-max-height');
      const measure=w=>{popover.style.setProperty('--tour-caption-width',w+'px');return popover.getBoundingClientRect().height;};
      let {width,height}=placePopover.fitWidth({viewportWidth:vw,maxHeight:bottom-top,measure});
      function constrain(maxHeight){
        if(description && height>maxHeight){
          popover.style.setProperty('--tour-description-max-height',Math.max(40,description.getBoundingClientRect().height-(height-maxHeight))+'px');
          description.tabIndex=0;height=popover.getBoundingClientRect().height;
        }else if(description)description.removeAttribute('tabindex');
      }
      constrain(bottom-top);
      let anchor=target.getBoundingClientRect();
      let placement=!docked && placePopover.findSpace({anchor,width,height,bounds,obstacles:exitRect?[exitRect]:[]});
      if(!placement){
        if(!host){host=target.closest('.demo-auto-panel')||target.closest('.table-scroll')||target;initialWidth=host.getBoundingClientRect().width;originalScroll={left:host.scrollLeft,top:host.scrollTop};}
        docked=true;
        const horizontal=vw>=900;
        width=horizontal?380:vw-2*gap;height=measure(width);
        constrain(horizontal?bottom-top:Math.max(180,bottom-top-134));
        const exampleWidth=horizontal?Math.min(Math.max(initialWidth,480),vw-width-3*gap):vw-2*gap;
        const exampleHeight=horizontal?bottom-top:Math.max(80,bottom-top-height-gap);
        // The highlighted element stays live (no copy): tables, source links and
        // scrollable proofs retain their original contents and event handlers.
        for(const [name,value] of Object.entries({position:'fixed',left:gap+'px',top:top+'px',right:'auto',bottom:'auto',transform:'none',margin:'0',width:exampleWidth+'px','min-width':'0','max-width':exampleWidth+'px',height:'auto','max-height':exampleHeight+'px',overflow:'auto','box-sizing':'border-box','pointer-events':host.matches('button,select,input,a')?'none':'auto','z-index':'10000'}))set(host,name,value);
        if(!host.matches('.panel'))set(host,'background-color','#fff');
        const size=exampleWidth+':'+exampleHeight;
        if(lastSize!==size && host!==target && target.matches('button,select,input,a')) {
          const a=target.getBoundingClientRect(),h=host.getBoundingClientRect();
          host.scrollTop+=a.top-h.top-(h.height-a.height)/2;
          host.scrollLeft+=a.left-h.left-(h.width-a.width)/2;
        }
        lastSize=size;
        // Keep a clipped table/header highlight within the actual reading area.
        // Driver uses its own target; the host contains every original row.
        placement=box(horizontal?vw-width-gap:gap,horizontal?Math.max(top,Math.min(host.getBoundingClientRect().top,bottom-height)):bottom-height,width,height);
        popover.dataset.tourPlacement=horizontal?'beside':'stacked';
        refresh();
      }else popover.dataset.tourPlacement='outside';
      popover.style.setProperty('--tour-caption-left',placement.left+'px');
      popover.style.setProperty('--tour-caption-top',placement.top+'px');
    }
    return {fit,reset};
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = placePopover;
  else root.placeTourPopover = placePopover;
})(typeof window !== 'undefined' ? window : globalThis);

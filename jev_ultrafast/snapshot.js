(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const safe = e => !['password','file','hidden'].includes(e.type);
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(document.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (['INPUT','SELECT'].includes(e.tagName) ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const short=(value,cap=160)=>String(value??'').slice(0,cap);
  const destination=e=>{
    try { const u=new URL(e.getAttribute('href'),location.href); return short(u.origin+u.pathname,200); }
    catch { return ''; }
  };
  const linkRevision=e=>{
    const links=cache.links ||= new WeakMap(), href=e.getAttribute('href'), prior=links.get(e);
    if (!prior || prior.href!==href) links.set(e,{href,revision:(prior?.revision||0)+1});
    return links.get(e).revision;
  };
  const controlState=e=>[e.value??null,e.checked??null,e.selectedIndex??null,e.disabled,e.readOnly,
    ...['checked','selected','expanded','pressed','disabled','readonly'].map(k=>e.getAttribute('aria-'+k)),
    e.isContentEditable ? short(e.innerText,400) : null];
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  const semanticValue = (e,rname) => e.tagName==='SELECT'
    ? [...e.selectedOptions].map(o=>o.label).join(', ')
    : !['INPUT','TEXTAREA'].includes(e.tagName) && ['option','tab','combobox'].includes(rname)
      ? (e.innerText ?? e.textContent ?? '').trim()
      : 'value' in e ? String(e.value) : e.isContentEditable ? (e.innerText ?? e.textContent ?? '').trim() : '';
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    [...document.querySelectorAll('input,textarea,select')].filter(safe).map(e=>[identity(e),...controlState(e)])];
  cache.guard=e=>{
    if (!e?.isConnected || !visible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),e.value??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('aria-pressed'),
      linkRevision(e),scope?.innerText?.slice(0,6000)||''];
  };
  const actions=[], reveals=[], formNames=new Map();
  for (const e of document.querySelectorAll(selector)) {
    if (!safe(e) || !visible(e)) continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2, rname=role(e);
    if (!rname || r.width<=0 || r.height<=0) continue;
    const outside=x<0 || y<0 || x>=innerWidth || y>=innerHeight;
    // Offer a control only if the act guard in browser.py would accept it: the same test,
    // `e.contains(document.elementFromPoint(point))`. Otherwise a control clipped by a scroll
    // container, under a consent iframe or cookie banner, or laid out behind other content is
    // offered, refused at act time ("Target changed or is covered"), and chosen again after
    // every re-observe. A link that wraps onto two lines has its box centre on the text between
    // its fragments, so the centre of each visible fragment is tried next; the act guard uses
    // the same fallback, so what is offered is what can be hit. A covered control is dropped
    // from the offer below, after the marker is built: occlusion is geometry, and the marker
    // deliberately compares meaning and identity only.
    const covered=!e.contains(document.elementFromPoint(x,y)) &&
      ![...e.getClientRects()].some(q => { const fx=q.x+q.width/2, fy=q.y+q.height/2;
        return q.width>0 && q.height>0 && fx>=0 && fy>=0 && fx<innerWidth && fy<innerHeight &&
          e.contains(document.elementFromPoint(fx,fy)); });
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
    const base={node:identity(e),role:rname,label:short(name(e)||
      (e.type==='radio' && e.getAttribute('value') ? 'radio ('+short(e.getAttribute('value'),80)+')' : rname)),
      rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
    const form=e.form || e.closest('form,dialog,[role="dialog"]');
    if (form) {
      if (!formNames.has(form)) formNames.set(form,[...form.querySelectorAll('input,textarea,select')]
        .filter(f=>safe(f) && visible(f)).map(f=>short(name(f)||role(f),60)).filter(Boolean).join('; ').slice(0,60));
      base.scope=formNames.get(form);
    }
    if (rname==='link') base.destination=destination(e);
    const region=e.closest('nav,[role="navigation"]');
    if (region) base.navigation=short(region.getAttribute('aria-label') ||
      (region.getAttribute('aria-labelledby') ? name(region) : ''),60);
    if (covered) base.covered=true;
    for (const key of ['checked','selected','expanded','pressed']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    if ((e.type==='radio' && e.hasAttribute('value')) || (e.type==='checkbox' && e.hasAttribute('value') && !name(e)))
      base.submission_value=short(e.value,80);
    const value=base.checked ?? base.pressed ?? short(semanticValue(e,rname));
    const disabled=e.matches(':disabled') || !!e.closest('[aria-disabled="true"]');
    if (disabled) continue;
    if (outside) {
      let clipped=false;
      for (let p=e.parentElement; p && p!==document.body; p=p.parentElement) {
        const style=getComputedStyle(p), box=p.getBoundingClientRect();
        if (/(hidden|clip)/.test(style.overflowY) && (y<box.top || y>=box.bottom)) clipped=true;
      }
      if (clipped) continue;
      reveals.push({...base,covered:false,kind:'reveal',value});
      continue;
    }
    if (e.tagName==='SELECT') {
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base,kind:'select',value:o.value,
          current_value:short([...e.selectedOptions].map(o=>o.label).join(', ')),label:short(base.label+' → '+o.label)});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      // A checkbox/radio's DOM value is its form-submission token (often "true" even
      // when unchecked). Describe the observed state, not the token, as its value.
      const value=base.checked ?? base.pressed ?? short(semanticValue(e,rname));
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  actions.push(...reveals);
  const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const range=document.createRange(); let node,length=0;
  while ((node=walker.nextNode()) && length<6000) {
    const value=node.textContent.trim(), parent=node.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
    range.selectNodeContents(node); const r=range.getBoundingClientRect();
    if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
      words.push(value); length+=value.length;
    }
  }
  const text=words.join('\n').slice(0,6000), height=document.documentElement.scrollHeight;
  const landmark=[...document.querySelectorAll('main,[role="main"]')].find(visible);
  const hasText=root=>{
    const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT); let n;
    while ((n=w.nextNode())) {
      const p=n.parentElement;
      if (!n.textContent.trim() || !p || p.closest('script,style,noscript,template')) continue;
      // Navigation inside main (an app shell's sidebar) stays while the route's content loads; it is not content.
      const nav=p.closest('nav,[role="navigation"]');
      if (nav && nav!==root && root.contains(nav)) continue;
      if (!visible(p)) continue;
      // Screen-reader-only text (sr-only) sits in a box clipped to 1px and is not content.
      const r=p.getBoundingClientRect();
      if (r.width>1 && r.height>1) return true;
    }
    return false;
  };
  const main=landmark ? hasText(landmark) : null;
  // Compare meaning and identity. Geometry and scroll-region hit testing happen just before input.
  const semantics=actions.map(({rect,covered,...action})=>action);
  actions.splice(0,actions.length,...actions.filter(a=>!a.covered));
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,main,semantics,page_key[6]];
  // Sample hit-tested ancestor chains instead of scanning and styling the whole DOM. This exposes
  // visible nested feeds and sidebars without site-specific selectors or model-generated coordinates.
  const scrollRegions=[], seenScrollRegions=new Set();
  for (const fx of [0.1,0.3,0.5,0.7,0.9]) for (const fy of [0.2,0.5,0.8]) {
    const hit=document.elementFromPoint(innerWidth*fx,innerHeight*fy);
    if (!hit || hit.closest('input,select,textarea')) continue;
    let e=hit;
    while (e && e!==document.body && e!==document.documentElement) {
      const style=getComputedStyle(e);
      if (/(auto|scroll)/.test(style.overflowY) && e.scrollHeight>e.clientHeight+2) {
        const r=e.getBoundingClientRect();
        const visibleWidth=Math.max(0,Math.min(innerWidth,r.right)-Math.max(0,r.left));
        const visibleHeight=Math.max(0,Math.min(innerHeight,r.bottom)-Math.max(0,r.top));
        if (!seenScrollRegions.has(e) && visibleWidth>20 && visibleHeight>20 && visible(e)) {
          seenScrollRegions.add(e);
          scrollRegions.push({e,r,score:visibleWidth*visibleHeight});
        }
        // Only the nearest scrollable ancestor can consume a wheel event at this point.
        break;
      }
      e=e.parentElement;
    }
  }
  scrollRegions.sort((a,b)=>b.score-a.score).slice(0,4).forEach(({e,r},i)=>{
    const labelled=e.getAttribute('aria-label') ||
      (e.getAttribute('aria-labelledby') ? name(e) : '') || e.getAttribute('role') || 'scrollable region';
    const regionName=labelled.trim().slice(0,120) || 'scrollable region';
    const delta=Math.max(120,Math.min(560,Math.round(e.clientHeight*0.75)));
    const base={node:identity(e),kind:'scroll',rect:{x:r.x,y:r.y,w:r.width,h:r.height},
      scroll_top:e.scrollTop,scroll_height:e.scrollHeight,client_height:e.clientHeight};
    const down=Math.max(0,e.scrollHeight-e.clientHeight-e.scrollTop);
    if (down>2)
      actions.push({...base,id:'scroll_region_down_'+(i+1),label:'Scroll down '+regionName,
        delta:Math.min(delta,down)});
    if (e.scrollTop>1)
      actions.push({...base,id:'scroll_region_up_'+(i+1),label:'Scroll up '+regionName,
        delta:-Math.min(delta,e.scrollTop)});
  });
  // Page scrolling sends a wheel at this point; the action carries it so input uses the same point.
  // Offer a direction only when that wheel would move the document: the viewport must allow scrolling,
  // and no scroll region under the point may take the wheel first (one that can still move that way,
  // or one at its end that stops scroll chaining with overscroll-behavior contain/none).
  const wheel={x:Math.min(550,innerWidth-1),y:Math.min(650,innerHeight-1)};
  const viewportOverflow=(o=>o!=='visible' ? o : getComputedStyle(document.body).overflowY)(
    getComputedStyle(document.documentElement).overflowY);
  const wheelHit=document.elementFromPoint(wheel.x,wheel.y);
  const reachesDocument=down=>{
    if (/(hidden|clip)/.test(viewportOverflow)) return false;
    for (let n=wheelHit; n && n!==document.body && n!==document.documentElement; n=n.parentElement) {
      const style=getComputedStyle(n);
      if (!/(auto|scroll)/.test(style.overflowY) || n.scrollHeight<=n.clientHeight+2) continue;
      if (down ? n.scrollTop+n.clientHeight<n.scrollHeight-1 : n.scrollTop>0) return false;
      if (/(contain|none)/.test(style.overscrollBehaviorY)) return false;
    }
    return true;
  };
  if (scrollY+innerHeight<height-2 && reachesDocument(true))
    actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560,...wheel});
  if (scrollY>0 && reachesDocument(false))
    actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560,...wheel});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  // Retain bounded controls even on pages whose interactive elements fill the candidate budget.
  const controls=actions.filter(a=>a.kind==='scroll' || a.kind==='wait');
  const elements=actions.filter(a=>a.kind!=='scroll' && a.kind!=='wait');
  const visibleElements=elements.filter(a=>a.kind!=='reveal'), offscreen=elements.filter(a=>a.kind==='reveal');
  const retained=[...visibleElements.filter(a=>a.kind!=='select').slice(0,100),
    ...visibleElements.filter(a=>a.kind==='select').slice(0,100),...offscreen.slice(0,20),...controls];
  const omitted_actions=actions.length-retained.length;
  retained.forEach((a,i)=>{ if (a.kind!=='scroll' && a.kind!=='wait') a.id='e'+(i+1); });
  actions.splice(0,actions.length,...retained);
  // Read-only facts include disabled controls and fields outside the viewport.
  // They never become executable targets; password/file/hidden inputs stay excluded.
  const observed_controls=[]; let omitted_controls=0, clipped_values=false;
  for (const e of document.querySelectorAll(selector)) {
    if (!safe(e) || !visible(e)) continue;
    const rname=role(e), r=e.getBoundingClientRect();
    if (!rname || !r.width || !r.height) continue;
    const states={};
    for (const key of ['checked','selected','expanded','pressed']) {
      const v=e.getAttribute('aria-'+key); if (v!==null) states[key]=v;
    }
    if (['checkbox','radio'].includes(e.type)) states.checked=String(e.checked);
    if (!['INPUT','TEXTAREA','SELECT'].includes(e.tagName) && !e.isContentEditable && !Object.keys(states).length &&
        !['tab','option','combobox','textbox','searchbox','spinbutton'].includes(rname)) continue;
    if (observed_controls.length>=120) { omitted_controls++; continue; }
    const raw=states.checked ?? states.pressed ?? semanticValue(e,rname);
    const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true';
    const in_view=r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth;
    const value=short(raw,200);
    if (raw.length>200) clipped_values=true;
    const form=e.form || e.closest('form,dialog,[role="dialog"]');
    const label=short(name(e)||rname), scope=short(form?.querySelector('h1,h2,h3,h4,legend')?.innerText||'',100);
    const fact={role:rname,label,value,...states,
      key:short(e.id || e.getAttribute('name') || scope+'|'+rname+'|'+label,180),
      disabled:e.matches(':disabled') || !!e.closest('[aria-disabled="true"]'),in_view,scope,
      ...(!in_view && !editable && !states.checked && !states.pressed ? {value:'',has_value:!!raw,value_unobserved:!!raw} : {})};
    observed_controls.push(fact);
  }
  // Duplicate labels remain separate preservation baselines, independent of transient node ids.
  const occurrences=new Map();
  for (const fact of observed_controls) {
    const n=occurrences.get(fact.key)||0; occurrences.set(fact.key,n+1); fact.key+='|'+n;
  }
  marker.push(observed_controls);
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,main,
    scroll:{y:scrollY,height},actions,marker,page_key,guards,omitted_actions,observed_controls,
    observation_limits:{omitted_actions,omitted_controls,
      clipped_values,text_at_limit:text.length>=6000}};
})()

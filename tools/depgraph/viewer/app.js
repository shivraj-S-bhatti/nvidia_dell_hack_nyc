const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const G=window.__GRAPH__, P=window.__PARTS__, CHANGE=window.__DEMO_CHANGE__;
const nodeById=new Map(G.nodes.map(n=>[n.id,n]));
const fast=new Map(); const contains=new Map();
function push(m,k,v){ (m.get(k)||m.set(k,[]).get(k)).push(v); }
G.edges.forEach(e=>{ if(e.t==='FASTENS'){push(fast,e.a,e);push(fast,e.b,e);} else {push(contains,e.a,e);push(contains,e.b,e);} });

// ---------- three.js scene ----------
const cv=$('#cv');
const renderer=new THREE.WebGLRenderer({canvas:cv,antialias:true,alpha:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
const scene=new THREE.Scene();
const cam=new THREE.PerspectiveCamera(38,1,1,4000);
const controls=new THREE.OrbitControls(cam,cv);
controls.enableDamping=true; controls.dampingFactor=.08;
scene.add(new THREE.HemisphereLight(0xdfe8f5,0x2a2f38,1.15));
const key=new THREE.DirectionalLight(0xffffff,1.5); key.position.set(320,520,300); scene.add(key);
const rim=new THREE.DirectionalLight(0x9fc4ff,.55); rim.position.set(-280,140,-320); scene.add(rim);

const MIN=P.min, SC=P.scale;
const posRaw=new Uint16Array(b64(window.__POS__)), nrmView=new Int8Array(posRaw.buffer);
const idxRaw=b64(window.__IDX__);
function b64(s){const bin=atob(s);const u=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);return u.buffer;}
const meshes=[]; const group=new THREE.Group(); scene.add(group);
const BASE=new THREE.Color(0x7d8894), FADE=new THREE.Color(0x39414c);
P.parts.forEach(p=>{
  const n=p.pCount, pv=new Uint16Array(posRaw.buffer,p.pOff,n*3);
  const pos=new Float32Array(n*3);
  for(let k=0;k<n;k++)for(let a=0;a<3;a++) pos[k*3+a]=pv[k*3+a]*SC[a]+MIN[a];
  const g=new THREE.BufferGeometry();
  g.setAttribute('position',new THREE.BufferAttribute(pos,3));
  if(p.nrm){ const nv=new Int8Array(posRaw.buffer,p.pOff+n*6,n*3); const nn=new Float32Array(n*3);
    for(let k=0;k<n*3;k++) nn[k]=nv[k]/127; g.setAttribute('normal',new THREE.BufferAttribute(nn,3)); }
  else g.computeVertexNormals();
  const IA=p.i32? new Uint32Array(idxRaw,p.iOff,p.iCount): new Uint16Array(idxRaw,p.iOff,p.iCount);
  g.setIndex(new THREE.BufferAttribute(IA.slice(),1));
  const mat=new THREE.MeshStandardMaterial({color:BASE.clone(),roughness:.62,metalness:.28,transparent:true,opacity:1});
  const m=new THREE.Mesh(g,mat); m.userData.part=p; m.userData.occ=p.occ;
  m.userData.basePosition=pos.slice(); group.add(m); meshes.push(m);
});
const box=new THREE.Box3().setFromObject(group), ctr=box.getCenter(new THREE.Vector3()), sz=box.getSize(new THREE.Vector3());
group.position.sub(ctr);
const radius=Math.max(sz.x,sz.y,sz.z);
cam.position.set(radius*.75,radius*.62,radius*.95); cam.lookAt(0,0,0); controls.update();
function resize(){const r=cv.parentElement.getBoundingClientRect();renderer.setSize(r.width,r.height,false);cam.aspect=r.width/r.height;cam.updateProjectionMatrix();}
new ResizeObserver(resize).observe(cv.parentElement); resize();
(function loop(){requestAnimationFrame(loop);controls.update();renderer.render(scene,cam);})();

// ---------- propagation ----------
const HOPCOL=['#e8913a','#e0b04e','#8fbf7a','#5fa8c9','#7d8db8'];
function propagate(anchorDef, anchorOccs, maxHops){
  const hop=new Map(), why=new Map();
  anchorOccs.forEach(o=>{hop.set(o,0);why.set(o,[{t:'ANCHOR',s:'selected for change'}]);});
  let frontier=[...anchorOccs];
  // Close each definition at most once for the whole traversal. Re-scanning the
  // definition group per reached node is quadratic and dominates at corpus scale
  // (measured: 273ms vs 1.2ms at 12.6k nodes).
  const closed=new Set();
  for(let h=1;h<=maxHops;h++){
    const next=[];
    frontier.forEach(a=>{ (fast.get(a)||[]).forEach(e=>{
        const b = e.a===a? e.b : e.a;
        if(hop.has(b)) return;
        hop.set(b,h); why.set(b,[{t:'FASTENS',s:e.why,clr:e.clr,off:e.off,via:a}]); next.push(b);
    });});
    // definition closure: a spec change hits every occurrence of that definition
    for(let i=0,L=next.length;i<L;i++){
      const def=nodeById.get(next[i])?.def; if(!def||closed.has(def)) continue;
      closed.add(def);
      (G.defs[def]||[]).forEach(sib=>{ if(hop.has(sib))return;
        hop.set(sib,h); why.set(sib,[{t:'INSTANCE_OF',s:`shared part definition ${def} — a spec change applies to all ${G.defs[def].length} occurrences`}]); next.push(sib); });
    }
    frontier=next; if(!next.length) break;
  }
  return {hop,why};
}
let current=null;
function render(anchorLabel, anchorDef, anchorOccs, maxHops){
  const {hop,why}=propagate(anchorDef,anchorOccs,maxHops);
  current={hop,why,anchorLabel};
  const occHop=new Map(); hop.forEach((h,o)=>occHop.set(o,h));
  meshes.forEach(m=>{
    const h=occHop.get(m.userData.occ);
    if(h===undefined){ m.material.color.set(FADE); m.material.opacity=$('#iso').checked?0.045:0.22; }
    else { m.material.color.set(HOPCOL[Math.min(h,HOPCOL.length-1)]); m.material.opacity=1; }
    m.material.needsUpdate=true;
  });
  // group by definition
  const byDef=new Map();
  hop.forEach((h,o)=>{ const d=nodeById.get(o)?.def||'?';
    if(!byDef.has(d)) byDef.set(d,{def:d,hop:h,occs:[],why:why.get(o)});
    const g=byDef.get(d); g.occs.push(o); g.hop=Math.min(g.hop,h); });
  const rows=[...byDef.values()].sort((a,b)=>a.hop-b.hop || b.occs.length-a.occs.length);
  const totalOcc=hop.size, totalDef=byDef.size;
  $('#anchorName').textContent=anchorLabel;
  $('#sumDef').textContent=totalDef; $('#sumOcc').textContent=totalOcc;
  $('#sumHop').textContent=Math.max(...[...hop.values()]);
  $('#work').innerHTML=rows.map(r=>{
    const w=r.why?.[0]||{}; const isAnchor=r.hop===0;
    return `<article class="row${isAnchor?' is-anchor':''}">
      <div class="rowhead">
        <span class="hopdot" style="--c:${HOPCOL[Math.min(r.hop,4)]}"></span>
        <span class="rowname">${esc(r.def)}</span>
        <span class="qty">×${r.occs.length}</span>
      </div>
      <div class="rowmeta">
        <span class="chip chip-hop">hop ${r.hop}</span>
        <span class="chip chip-${w.t==='INSTANCE_OF'?'inst':'geo'}">${w.t==='ANCHOR'?'anchor':(w.t==='INSTANCE_OF'?'INSTANCE_OF':'FASTENS')}</span>
        <span class="chip chip-tier">geometry</span>
      </div>
      <p class="why">${esc(w.s||'')}</p>
    </article>`;}).join('');
}
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// ---------- bounded candidate change ----------
let changePreviewed=false;
function targetMeshes(){ return meshes.filter(m=>m.userData.part.name===CHANGE.target); }
function setCandidateGeometry(active){
  targetMeshes().forEach(m=>{
    const p=m.userData.part, base=m.userData.basePosition;
    const spans=p.max.map((v,i)=>v-p.min[i]);
    const axis=spans.indexOf(Math.min(...spans));
    const mid=(p.min[axis]+p.max[axis])/2;
    const ratio=(spans[axis]+CHANGE.deltaMm)/spans[axis];
    const out=m.geometry.getAttribute('position').array;
    out.set(base);
    if(active) for(let i=axis;i<out.length;i+=3) out[i]=mid+(base[i]-mid)*ratio;
    m.geometry.getAttribute('position').needsUpdate=true;
    m.geometry.deleteAttribute('normal'); m.geometry.computeVertexNormals();
    m.geometry.computeBoundingBox(); m.geometry.computeBoundingSphere();
  });
  changePreviewed=active;
  $('#changeState').textContent=active?'proposed · local preview':'candidate ready';
  $('#changeState').classList.toggle('active',active);
  $('#changeState').dataset.previewed=String(active);
  $('#previewChange').textContent=active?'Previewing':'Preview change';
  $('#previewChange').disabled=active; $('#resetChange').disabled=!active;
}
function focusTarget(){
  const b=new THREE.Box3(); targetMeshes().forEach(m=>b.expandByObject(m));
  const c=b.getCenter(new THREE.Vector3()), s=b.getSize(new THREE.Vector3());
  const span=Math.max(s.x,s.y,s.z);
  controls.target.copy(c);
  const distance=span*1.55/Math.min(cam.aspect,1);
  const view=new THREE.Vector3(.78,.56,.9).normalize().multiplyScalar(distance);
  cam.position.copy(c).add(view);
  cam.near=Math.max(span/1000,.1); cam.far=span*20; cam.updateProjectionMatrix(); controls.update();
}
function selectTarget(){
  const b=$(`.defbtn[data-def="${CSS.escape(CHANGE.target)}"]`); if(b) b.click();
}
function previewChange(){ selectTarget(); setCandidateGeometry(true); focusTarget(); }
function resetChange(){ setCandidateGeometry(false); focusTarget(); }
$('#changeActions').innerHTML=CHANGE.actions.map(a=>
  `<div class="change-action"><span>${esc(a.action)}</span><b>×${a.count}</b></div>`).join('');
$('#previewChange').onclick=previewChange; $('#resetChange').onclick=resetChange;

// ---------- anchors ----------
const defCounts=Object.entries(G.defs).map(([d,o])=>({def:d,n:o.length}))
  .filter(x=>P.parts.some(p=>p.name===x.def)).sort((a,b)=>b.n-a.n||a.def.localeCompare(b.def));
$('#defs').innerHTML=defCounts.map(x=>`<button class="defbtn" data-def="${esc(x.def)}"><span>${esc(x.def)}</span><em>×${x.n}</em></button>`).join('');
$$('.defbtn').forEach(b=>b.onclick=()=>{ $$('.defbtn').forEach(x=>x.classList.remove('on')); b.classList.add('on');
  const d=b.dataset.def; render(d, d, G.defs[d]||[], +$('#hops').value); });
$('#hops').oninput=e=>{ $('#hopsv').textContent=e.target.value; if(current) { const b=$('.defbtn.on'); if(b) b.click(); } };
$('#iso').onchange=()=>{ const b=$('.defbtn.on'); if(b) b.click(); };
// click part in 3D
const ray=new THREE.Raycaster(), m2=new THREE.Vector2();
cv.addEventListener('click',ev=>{
  const r=cv.getBoundingClientRect();
  m2.x=((ev.clientX-r.left)/r.width)*2-1; m2.y=-((ev.clientY-r.top)/r.height)*2+1;
  ray.setFromCamera(m2,cam); const hit=ray.intersectObjects(meshes,false)[0];
  if(!hit) return; const d=hit.object.userData.part.name;
  const b=$(`.defbtn[data-def="${CSS.escape(d)}"]`); if(b) b.click();
});
$('#stat-nodes').textContent=G.nodes.length;
$('#stat-edges').textContent=G.edges.length;
$('#stat-fast').textContent=G.edges.filter(e=>e.t==='FASTENS').length;
$('#stat-defs').textContent=Object.keys(G.defs).length;
// default demo
const first=$(`.defbtn[data-def="${CSS.escape(CHANGE.target)}"]`)||$('.defbtn'); if(first) first.click();
window.__S500_VIEWER__={previewChange,resetChange,getState:()=>({
  previewed:changePreviewed,target:CHANGE.target,deltaMm:CHANGE.deltaMm,
  targetMeshes:targetMeshes().length,impactedOccurrences:current?.hop.size||0
})};

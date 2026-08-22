// step_to_mesh.mjs — tessellate a STEP assembly ONCE, offline.
//
// Emits three artifacts consumed by the rest of the pipeline:
//   mesh_pos.bin   quantized Uint16 positions (+ Int8 normals), 4-byte aligned
//   mesh_idx.bin   Uint16/Uint32 indices, 4-byte aligned
//   mesh.json      per-part manifest: name, parent, offsets, world bbox, centroid
//
// Why offline: OCCT tessellation of S500-C1_ASM.step costs ~6.4s and yields
// ~110k triangles. Rendering that is free; re-tessellating per page load is not.
// occt-import-js is pure WASM, so this runs on ARM64/GB10 with no native build.
//
//   node tools/depgraph/step_to_mesh.mjs <in.step> <outDir>

import occtimportjs from 'occt-import-js';
import fs from 'fs';
import path from 'path';

const [,, inPath='S500-C1_ASM.step', outDir='.artifacts/depgraph'] = process.argv;
fs.mkdirSync(outDir, {recursive:true});

const occt = await occtimportjs();
const t0 = Date.now();
const r = occt.ReadStepFile(new Uint8Array(fs.readFileSync(inPath)), {
  linearUnit:'millimeter', linearDeflectionType:'bounding_box_ratio',
  linearDeflection:0.01, angularDeflection:1.0,
});
if (!r.success) { console.error('STEP read failed'); process.exit(1); }
console.error(`tessellated ${r.meshes.length} meshes in ${Date.now()-t0} ms`);

// occt flattens below the second level, so a mesh's owner is its nearest named ancestor.
const owner = {};
(function walk(n, p){ const nm=n.name||null; const q=nm?[...p,nm]:p;
  (n.meshes||[]).forEach(m=>owner[m]=q); (n.children||[]).forEach(c=>walk(c,q)); })(r.root, []);

let MN=[1e30,1e30,1e30], MX=[-1e30,-1e30,-1e30];
r.meshes.forEach(m=>{ const P=m.attributes.position.array;
  for(let k=0;k<P.length;k+=3) for(let a=0;a<3;a++){ if(P[k+a]<MN[a])MN[a]=P[k+a]; if(P[k+a]>MX[a])MX[a]=P[k+a]; } });
const SC=[(MX[0]-MN[0])/65534,(MX[1]-MN[1])/65534,(MX[2]-MN[2])/65534];

const pad4 = n => (4-(n%4))%4;
const parts=[], posChunks=[], idxChunks=[], vertChunks=[];
let pOff=0, iOff=0, vOff=0;

r.meshes.forEach((m,i)=>{
  const P=m.attributes.position.array, I=m.index.array, n=P.length/3;
  // quantized copy for the viewer
  const q=new Uint16Array(P.length);
  for(let k=0;k<P.length;k+=3) for(let a=0;a<3;a++)
    q[k+a]=Math.max(0,Math.min(65534,Math.round((P[k+a]-MN[a])/SC[a])));
  const N=m.attributes.normal
    ? new Int8Array(m.attributes.normal.array.map(v=>Math.max(-127,Math.min(127,Math.round(v*127)))))
    : null;
  const idx = n<65536 ? new Uint16Array(I) : new Uint32Array(I);

  // full-precision world vertices for the grip-stack solver
  const fv=new Float32Array(P);

  const plen=q.byteLength+(N?N.byteLength:0), pp=pad4(plen);
  posChunks.push(Buffer.from(q.buffer)); if(N) posChunks.push(Buffer.from(N.buffer));
  if(pp) posChunks.push(Buffer.alloc(pp));
  const ip=pad4(idx.byteLength);
  idxChunks.push(Buffer.from(idx.buffer)); if(ip) idxChunks.push(Buffer.alloc(ip));
  vertChunks.push(Buffer.from(fv.buffer));

  let mn=[1e30,1e30,1e30], mx=[-1e30,-1e30,-1e30], c=[0,0,0];
  for(let k=0;k<P.length;k+=3) for(let a=0;a<3;a++){
    const v=P[k+a]; if(v<mn[a])mn[a]=v; if(v>mx[a])mx[a]=v; c[a]+=v; }
  c=c.map(v=>v/n);

  parts.push({ i, name:m.name, parent:(owner[i]||['ROOT']).slice(-1)[0],
    pOff, pCount:n, nrm:!!N, iOff, iCount:I.length, i32:!(n<65536),
    vOff, vCount:n,
    min:mn.map(v=>+v.toFixed(4)), max:mx.map(v=>+v.toFixed(4)), centroid:c.map(v=>+v.toFixed(4)),
    color:(m.color||[0.6,0.6,0.6]).map(v=>+v.toFixed(3)) });
  pOff+=plen+pp; iOff+=idx.byteLength+ip; vOff+=fv.byteLength;
});

fs.writeFileSync(path.join(outDir,'mesh_pos.bin'), Buffer.concat(posChunks));
fs.writeFileSync(path.join(outDir,'mesh_idx.bin'), Buffer.concat(idxChunks));
fs.writeFileSync(path.join(outDir,'mesh_vert.bin'), Buffer.concat(vertChunks));
fs.writeFileSync(path.join(outDir,'mesh.json'), JSON.stringify({min:MN,scale:SC,parts}));
console.error(`wrote ${parts.length} parts -> ${outDir}`);

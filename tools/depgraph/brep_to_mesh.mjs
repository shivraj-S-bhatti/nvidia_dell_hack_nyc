// brep_to_mesh.mjs — tessellate a list of OpenCascade BREP shapes, offline.
//
//   node tools/depgraph/brep_to_mesh.mjs <manifest.json> <outDir>
//
// manifest.json: [{"def": "<definition name>", "path": "<file.brp>"}, ...]
// Emits localmesh.json + localmesh_vert.bin — per-DEFINITION vertices in that
// definition's own frame. The caller applies each occurrence's world transform.
//
// Why this exists: occt-import-js reads AP214 edition-3 STEP well enough to report
// the face topology and then triangulates none of it (measured on
// neoracer-full-vehicle.step: 1136 meshes, 0 vertices, exit 0). The same geometry
// arrives as BREP through ReadBrepFile and meshes normally, so when a STEP file
// refuses to tessellate we take the shapes from the FreeCAD source instead.
//
// Still pure WASM, so this runs on ARM64/GB10 with no native build.

import occtimportjs from 'occt-import-js';
import fs from 'fs';
import path from 'path';

const [,, manifestPath, outDir='.artifacts/depgraph'] = process.argv;
if (!manifestPath) { console.error('usage: brep_to_mesh.mjs <manifest.json> <outDir>'); process.exit(2); }
fs.mkdirSync(outDir, {recursive:true});

const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const occt = await occtimportjs();

const defs = [];
const chunks = [];
let vOff = 0, failed = 0, t0 = Date.now();

for (const [i, entry] of manifest.entries()) {
  let r;
  try {
    r = occt.ReadBrepFile(new Uint8Array(fs.readFileSync(entry.path)), {
      linearUnit:'millimeter', linearDeflectionType:'bounding_box_ratio',
      linearDeflection:0.01, angularDeflection:1.0,
    });
  } catch (e) {
    console.error(`  ${entry.def}: threw ${e && e.message ? e.message : e}`);
    failed++; continue;
  }
  if (!r.success || !r.meshes?.length) { failed++; continue; }

  // A definition may tessellate to several meshes (one per solid in a compound);
  // they share one frame, so they concatenate into one vertex block.
  const pts = [];
  for (const m of r.meshes) {
    const P = m.attributes?.position?.array;
    if (P?.length) for (let k = 0; k < P.length; k++) pts.push(P[k]);
  }
  if (!pts.length) { failed++; continue; }

  const fv = new Float32Array(pts);
  chunks.push(Buffer.from(fv.buffer));
  let mn=[1e30,1e30,1e30], mx=[-1e30,-1e30,-1e30];
  for (let k = 0; k < pts.length; k += 3) for (let a = 0; a < 3; a++) {
    const v = pts[k+a]; if (v < mn[a]) mn[a] = v; if (v > mx[a]) mx[a] = v;
  }
  defs.push({ def: entry.def, vOff, vCount: pts.length/3,
              min: mn.map(v=>+v.toFixed(4)), max: mx.map(v=>+v.toFixed(4)),
              color: (r.meshes[0].color || [0.6,0.6,0.6]).map(v=>+v.toFixed(3)) });
  vOff += fv.byteLength;

  if ((i+1) % 50 === 0) console.error(`  ${i+1}/${manifest.length} tessellated`);
}

fs.writeFileSync(path.join(outDir, 'localmesh_vert.bin'), Buffer.concat(chunks));
fs.writeFileSync(path.join(outDir, 'localmesh.json'), JSON.stringify({defs}));
const verts = defs.reduce((s,d)=>s+d.vCount, 0);
console.error(`tessellated ${defs.length}/${manifest.length} definitions, ` +
              `${verts} vertices in ${Date.now()-t0} ms` + (failed ? ` (${failed} failed)` : ''));
if (!defs.length) { console.error('ERROR: nothing tessellated'); process.exit(2); }

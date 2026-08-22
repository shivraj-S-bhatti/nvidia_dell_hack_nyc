// STEP -> GLB converter for the EasyRC car parts using occt-import-js (WASM OpenCASCADE).
//
// Input : a checkout of TRD-B/EasyRC. Point EASYRC_CAR at its "CAD files/Car" folder
//         (default: ../EasyRC/CAD files/Car relative to this repo's examples/easyrc).
// Output: one GLB per part in ../viewer/assets and a ../viewer/parts.json manifest.
//
//   npm install                # installs occt-import-js
//   EASYRC_CAR="/path/to/EasyRC/CAD files/Car" node convert.mjs
import occtimportjs from 'occt-import-js';
import { readFileSync, writeFileSync, readdirSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CAR = process.env.EASYRC_CAR || path.join(HERE, '..', 'EasyRC', 'CAD files', 'Car');
const OUT = path.join(HERE, '..', 'viewer', 'assets');
mkdirSync(OUT, { recursive: true });

const slug = (n) => 'part-easyrc-' + n.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const subsystem = (n) => {
  n = n.toLowerCase();
  if (/gear|differential|bearing mount/.test(n)) return 'drivetrain';
  if (/chassis|battery lid/.test(n)) return 'chassis';
  if (/rim|tire|tyre/.test(n)) return 'wheels';
  if (/wheel mount|axle|steering/.test(n)) return 'suspension-steering';
  if (/body|bumper|wing|window|led|light|servo horn/.test(n)) return 'body-exterior';
  return 'other';
};

// Minimal single-mesh GLB writer (positions FLOAT vec3 + indices UINT scalar).
function writeGLB(positions, indices, outPath) {
  const pos = new Float32Array(positions);
  const idx = new Uint32Array(indices);
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < pos.length; i += 3)
    for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], pos[i + k]); max[k] = Math.max(max[k], pos[i + k]); }

  const pad4 = (n) => (n + 3) & ~3;
  const posBytes = pos.byteLength;
  const idxOffset = pad4(posBytes);
  const binLen = pad4(idxOffset + idx.byteLength);
  const bin = Buffer.alloc(binLen);
  Buffer.from(pos.buffer, pos.byteOffset, pos.byteLength).copy(bin, 0);
  Buffer.from(idx.buffer, idx.byteOffset, idx.byteLength).copy(bin, idxOffset);

  const gltf = {
    asset: { version: '2.0', generator: 'easyrc-step-convert' },
    scenes: [{ nodes: [0] }], scene: 0, nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 }, indices: 1, mode: 4 }] }],
    buffers: [{ byteLength: binLen }],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: posBytes, target: 34962 },
      { buffer: 0, byteOffset: idxOffset, byteLength: idx.byteLength, target: 34963 },
    ],
    accessors: [
      { bufferView: 0, componentType: 5126, count: pos.length / 3, type: 'VEC3', min, max },
      { bufferView: 1, componentType: 5125, count: idx.length, type: 'SCALAR' },
    ],
  };
  const jsonBuf = Buffer.from(JSON.stringify(gltf), 'utf8');
  const jsonPad = Buffer.alloc(pad4(jsonBuf.length) - jsonBuf.length, 0x20);
  const jsonChunk = Buffer.concat([jsonBuf, jsonPad]);
  const header = Buffer.alloc(12);
  header.writeUInt32LE(0x46546c67, 0); header.writeUInt32LE(2, 4);
  header.writeUInt32LE(12 + 8 + jsonChunk.length + 8 + bin.length, 8);
  const jsonHdr = Buffer.alloc(8); jsonHdr.writeUInt32LE(jsonChunk.length, 0); jsonHdr.writeUInt32LE(0x4e4f534a, 4);
  const binHdr = Buffer.alloc(8); binHdr.writeUInt32LE(bin.length, 0); binHdr.writeUInt32LE(0x004e4942, 4);
  writeFileSync(outPath, Buffer.concat([header, jsonHdr, jsonChunk, binHdr, bin]));
  return { min, max, tris: idx.length / 3, verts: pos.length / 3 };
}

const occt = await occtimportjs();
const files = readdirSync(CAR).filter((f) => f.toLowerCase().endsWith('.step'));
const manifest = [];
let failures = 0;

for (const file of files) {
  const name = file.replace(/\.step$/i, '');
  const content = new Uint8Array(readFileSync(path.join(CAR, file)));
  let result;
  try { result = occt.ReadStepFile(content, null); }
  catch (e) { console.error('FAIL read', name, e.message); failures++; continue; }
  if (!result || !result.success || !result.meshes || result.meshes.length === 0) {
    console.error('NO MESH', name); failures++; continue;
  }
  const positions = []; const indices = []; let base = 0;
  for (const m of result.meshes) {
    const p = m.attributes.position.array;
    for (let i = 0; i < p.length; i++) positions.push(p[i]);
    for (let i = 0; i < m.index.array.length; i++) indices.push(m.index.array[i] + base);
    base += p.length / 3;
  }
  const s = slug(name);
  const info = writeGLB(positions, indices, path.join(OUT, `${s}.glb`));
  const size = [info.max[0] - info.min[0], info.max[1] - info.min[1], info.max[2] - info.min[2]].map((v) => Math.round(v * 100) / 100);
  manifest.push({
    partId: s, name, subsystem: subsystem(name),
    material: /tpu/i.test(name) ? 'TPU-flex' : 'PLA-rigid',
    glb: `assets/${s}.glb`, bboxMm: size, tris: info.tris, verts: info.verts,
    center: info.min.map((mn, k) => Math.round((mn + info.max[k]) / 2 * 100) / 100),
  });
  console.log(`ok  ${name.padEnd(32)} tris=${info.tris}`);
}

manifest.sort((a, b) => a.name.localeCompare(b.name));
writeFileSync(path.join(OUT, '..', 'parts.json'), JSON.stringify({ count: manifest.length, parts: manifest }, null, 2));
console.log(`\nconverted ${manifest.length}/${files.length} parts, ${failures} failures`);

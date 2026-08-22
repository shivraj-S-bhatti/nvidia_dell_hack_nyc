import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const SUB_COLORS = {
  'drivetrain': 0xffb454,
  'suspension-steering': 0xff6b6b,
  'wheels': 0x4fb0a5,
  'chassis': 0x6aa9ff,
  'body-exterior': 0xb98cff,
  'other': 0x8a94a6,
};

const CELL = 46;            // grid-mode cell size (world units)
const FIT = 34;             // grid-mode target size per part

// ---- explode tuning ---------------------------------------------------------
// Autodesk-style hierarchical explode. Subsystem clusters separate first, then
// individual parts spread inside their cluster. Both phases are pure
// translation, so every part keeps its assembled orientation.
const GROUP_SPREAD = 0.95;  // cluster travel, in model radii, at slider = 1
const PART_SPREAD = 1.15;   // part travel inside its cluster, in cluster radii
const PART_PHASE_START = 0.30;  // parts stay coherent until the slider passes this

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1117);
const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.1, 20000);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
document.getElementById('view').appendChild(renderer.domElement);

scene.add(new THREE.HemisphereLight(0xbcd0e6, 0x202832, 1.05));
const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(120, 200, 140); scene.add(key);
const rim = new THREE.DirectionalLight(0x88aaff, 0.5); rim.position.set(-160, 80, -120); scene.add(rim);

const grid = new THREE.GridHelper(1200, 60, 0x24304a, 0x18202f);
scene.add(grid);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let colorMode = 'subsystem';
let layout = 'assembled';       // 'assembled' | 'grid'
let explode = 0;                // 0..1
const entries = [];             // { part, group, mesh, baseColor, home, dirGroup, dirPart, groupRadius, gridPos }
let selected = null;

const root = new THREE.Group();     // everything sits under here so we can scale once
scene.add(root);

const model = { center: new THREE.Vector3(), radius: 1 };

function makeLabel(text) {
  const c = document.createElement('canvas');
  const ctx = c.getContext('2d');
  ctx.font = '600 28px system-ui, sans-serif';
  c.width = Math.ceil(ctx.measureText(text).width) + 24; c.height = 44;
  const g = c.getContext('2d');
  g.font = '600 28px system-ui, sans-serif';
  g.fillStyle = 'rgba(200,211,224,0.92)';
  g.textBaseline = 'middle';
  g.fillText(text, 12, 24);
  const tex = new THREE.CanvasTexture(c);
  tex.minFilter = THREE.LinearFilter;
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
  spr.scale.set(c.width * 0.12, c.height * 0.12, 1);
  return spr;
}

const loader = new GLTFLoader();
const loadGLB = (url) => new Promise((res, rej) => loader.load(url, (g) => res(g), undefined, rej));

// Deterministic fallback direction (golden-angle sphere) for parts sitting exactly
// on their cluster centre, so they still separate instead of freezing in place.
function fallbackDir(i) {
  const ga = Math.PI * (3 - Math.sqrt(5));
  const y = 1 - (i + 0.5) / 64 * 2;
  const r = Math.sqrt(Math.max(0, 1 - y * y));
  const th = ga * i;
  return new THREE.Vector3(Math.cos(th) * r, y, Math.sin(th) * r).normalize();
}

function smoothstep(edge0, edge1, x) {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

async function main() {
  const data = await (await fetch('parts.json')).json();
  const parts = data.parts;
  document.getElementById('count').textContent = `${parts.length} parts`;

  const order = ['drivetrain', 'suspension-steering', 'wheels', 'chassis', 'body-exterior', 'other'];
  parts.sort((a, b) => (order.indexOf(a.subsystem) - order.indexOf(b.subsystem)) || a.name.localeCompare(b.name));
  const cols = Math.ceil(Math.sqrt(parts.length));

  const loaded = [];
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    let gltf;
    try { gltf = await loadGLB(part.glb); } catch (e) { console.warn('load fail', part.name); continue; }
    const geo = [];
    gltf.scene.traverse((o) => { if (o.isMesh) geo.push(o.geometry); });
    if (!geo.length) continue;
    const geometry = geo[0];
    geometry.computeVertexNormals();
    geometry.computeBoundingBox();
    const bb = geometry.boundingBox;
    const size = new THREE.Vector3(); bb.getSize(size);
    const worldCenter = new THREE.Vector3(); bb.getCenter(worldCenter);
    loaded.push({ part, geometry, size, worldCenter, index: i });
  }

  // ---- assembly extents, straight from the geometry (already in shared CAD space)
  const box = new THREE.Box3();
  for (const L of loaded) {
    box.expandByPoint(L.worldCenter.clone().sub(L.size.clone().multiplyScalar(0.5)));
    box.expandByPoint(L.worldCenter.clone().add(L.size.clone().multiplyScalar(0.5)));
  }
  box.getCenter(model.center);
  const span = new THREE.Vector3(); box.getSize(span);
  model.radius = Math.max(span.x, span.y, span.z) * 0.5 || 1;

  // ---- cluster (subsystem) centres
  const clusters = new Map();
  for (const L of loaded) {
    const k = L.part.subsystem || 'other';
    if (!clusters.has(k)) clusters.set(k, { sum: new THREE.Vector3(), n: 0, center: new THREE.Vector3(), radius: 1 });
    const c = clusters.get(k);
    c.sum.add(L.worldCenter); c.n++;
  }
  for (const c of clusters.values()) c.center.copy(c.sum).divideScalar(Math.max(1, c.n));
  for (const L of loaded) {
    const c = clusters.get(L.part.subsystem || 'other');
    c.radius = Math.max(c.radius, L.worldCenter.distanceTo(c.center));
  }

  for (const L of loaded) {
    const { part, geometry, worldCenter, index } = L;
    const baseColor = new THREE.Color(SUB_COLORS[part.subsystem] || 0x8a94a6);
    const mat = new THREE.MeshStandardMaterial({
      color: baseColor.clone(), metalness: 0.15, roughness: 0.65,
    });
    const mesh = new THREE.Mesh(geometry, mat);

    // Assembled: geometry keeps its CAD coordinates, so the parts self-assemble.
    // We only ever translate the wrapper group - never the geometry.
    const group = new THREE.Group();
    group.add(mesh);
    root.add(group);

    const cluster = clusters.get(part.subsystem || 'other');
    const dGroup = cluster.center.clone().sub(model.center);
    if (dGroup.lengthSq() < 1e-8) dGroup.copy(fallbackDir(index));
    const dPart = worldCenter.clone().sub(cluster.center);
    if (dPart.lengthSq() < 1e-8) dPart.copy(fallbackDir(index + 7));

    // grid-mode slot, so the catalog view still works
    const col = index % cols, row = Math.floor(index / cols);
    const gridPos = new THREE.Vector3(
      (col - (cols - 1) / 2) * CELL,
      0,
      (row - Math.ceil(parts.length / cols - 1) / 2) * CELL,
    );
    const gridScale = FIT / (Math.max(L.size.x, L.size.y, L.size.z) || 1);

    mesh.userData = { part, baseColor, mat };
    entries.push({
      part, group, mesh, baseColor,
      worldCenter,
      dirGroup: dGroup.normalize(),
      dirPart: dPart.normalize(),
      clusterRadius: cluster.radius,
      gridPos, gridScale,
      label: null,
    });
  }

  // scale the whole assembly to a comfortable on-screen size, and sit it on the grid
  const s = 260 / (model.radius * 2);
  root.scale.setScalar(s);
  grid.position.y = (box.min.y - model.center.y) * s;

  applyLayout();
  buildSidebar(parts);
  homeView();
  animate();
}

// ---- the explode algorithm --------------------------------------------------
// offset(part) = dirToClusterFromModel * (s * GROUP_SPREAD * modelRadius)
//              + dirToPartFromCluster  * (phase2 * PART_SPREAD * clusterRadius)
// Two levels means subassemblies read as units before their parts separate,
// which is what makes an Autodesk explode legible instead of a particle cloud.
function offsetFor(e, s) {
  const groupMag = s * GROUP_SPREAD * model.radius;
  const phase2 = smoothstep(PART_PHASE_START, 1.0, s);
  return e.dirGroup.clone().multiplyScalar(groupMag)
    .add(e.dirPart.clone().multiplyScalar(phase2 * PART_SPREAD * e.clusterRadius));
}

function setExplode(s, updateUi = true) {
  explode = s;
  if (layout === 'assembled') {
    for (const e of entries) e.group.position.copy(offsetFor(e, s));
  }
  if (updateUi) {
    const out = document.getElementById('explodeVal');
    if (out) out.textContent = `${Math.round(s * 100)}%`;
  }
}

function applyExplode() { setExplode(explode); }

// Bounds of the widest state the slider can reach, so Home/Fit frame the whole
// explode range and parts never sail out of view mid-drag (Autodesk keeps the
// camera still; that only reads well if the initial framing already allows for it).
function envelopeBounds() {
  const saved = explode;
  setExplode(1, false);
  root.updateMatrixWorld(true);
  const b = boundsOfScene();
  setExplode(saved, false);
  root.updateMatrixWorld(true);
  return b;
}

function applyLayout() {
  for (const e of entries) {
    if (layout === 'assembled') {
      e.mesh.scale.setScalar(1);
      e.mesh.position.set(0, 0, 0);
      if (e.label) { e.group.remove(e.label); e.label = null; }
    } else {
      // catalog grid: normalise each part into its own cell
      e.mesh.scale.setScalar(e.gridScale);
      e.mesh.position.copy(e.worldCenter).multiplyScalar(-e.gridScale);
      e.group.position.copy(e.gridPos);
      if (!e.label) {
        const l = makeLabel(e.part.name);
        l.position.set(0, -FIT / 2 - 6, 0);
        e.group.add(l); e.label = l;
      }
    }
  }
  grid.visible = layout === 'assembled';
  if (layout === 'assembled') applyExplode();
  const btn = document.getElementById('layoutBtn');
  if (btn) btn.textContent = layout === 'assembled' ? 'Layout: assembled' : 'Layout: grid';
  const ex = document.getElementById('explodeWrap');
  if (ex) ex.style.opacity = layout === 'assembled' ? '1' : '0.35';
}

function boundsOfScene() {
  const b = new THREE.Box3();
  for (const e of entries) b.expandByObject(e.mesh);
  return b;
}

function frame(box, factor = 1.6) {
  const c = new THREE.Vector3(); box.getCenter(c);
  const sz = new THREE.Vector3(); box.getSize(sz);
  const r = Math.max(sz.x, sz.y, sz.z) * 0.5 || 1;
  const dist = (r * factor) / Math.tan((camera.fov * Math.PI / 180) / 2);
  const dir = new THREE.Vector3(1, 0.55, 1).normalize();
  camera.position.copy(c).add(dir.multiplyScalar(dist));
  controls.target.copy(c);
  camera.near = Math.max(0.1, dist / 500); camera.far = dist * 50;
  camera.updateProjectionMatrix();
  controls.update();
}

// Home frames the full explode envelope in assembled mode, so dragging the slider
// never pushes geometry off screen. Fit frames whatever is on screen right now.
function homeView() {
  frame(layout === 'assembled' ? envelopeBounds() : boundsOfScene(), 1.12);
}
function fitView() { frame(boundsOfScene(), 1.25); }

function applyColors() {
  for (const e of entries) {
    const p = e.part;
    const col = colorMode === 'subsystem'
      ? (SUB_COLORS[p.subsystem] || 0x8a94a6)
      : (p.material === 'TPU-flex' ? 0x4fb0a5 : 0xb0b8c6);
    e.mesh.material.color.setHex(col);
    e.baseColor = new THREE.Color(col);
  }
  if (selected) selected.material.color.setHex(0xffd166);
}

function select(mesh) {
  if (selected) selected.material.color.copy(selected.userData.baseColor);
  selected = mesh;
  const info = document.getElementById('info');
  if (!mesh) { info.innerHTML = '<div class="hint">Click a part to inspect</div>'; return; }
  mesh.material.color.setHex(0xffd166);
  const p = mesh.userData.part;
  info.innerHTML = `
    <div class="pill" style="background:#${(SUB_COLORS[p.subsystem]||0x8a94a6).toString(16).padStart(6,'0')}">${p.subsystem}</div>
    <h2>${p.name}</h2>
    <table>
      <tr><td>Material</td><td>${p.material}</td></tr>
      <tr><td>Size (mm)</td><td>${p.bboxMm.map(v=>(+v).toFixed(1)).join(' x ')}</td></tr>
      <tr><td>Triangles</td><td>${p.tris.toLocaleString()}</td></tr>
      <tr><td>Part ID</td><td style="word-break:break-all;font-size:12px">${p.partId}</td></tr>
    </table>`;
  document.querySelectorAll('.pnav').forEach((n) => n.classList.toggle('active', n.dataset.id === p.partId));
}

function focusOn(mesh) {
  const b = new THREE.Box3().setFromObject(mesh);
  frame(b, 2.2);
}

function buildSidebar(parts) {
  const nav = document.getElementById('nav'); const groups = {};
  for (const p of parts) (groups[p.subsystem] ??= []).push(p);
  for (const [sub, list] of Object.entries(groups)) {
    const h = document.createElement('div'); h.className = 'ghead';
    h.innerHTML = `<span class="dot" style="background:#${(SUB_COLORS[sub]||0x8a94a6).toString(16).padStart(6,'0')}"></span>${sub}<em>${list.length}</em>`;
    nav.appendChild(h);
    for (const p of list) {
      const d = document.createElement('div'); d.className = 'pnav'; d.textContent = p.name; d.dataset.id = p.partId;
      d.onclick = () => { const e = entries.find((x) => x.part.partId === p.partId); if (e) { select(e.mesh); focusOn(e.mesh); } };
      nav.appendChild(d);
    }
  }
}

renderer.domElement.addEventListener('pointerdown', (ev) => {
  pointer.x = (ev.clientX / innerWidth) * 2 - 1;
  pointer.y = -(ev.clientY / innerHeight) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(entries.map((e) => e.mesh), false)[0];
  select(hit ? hit.object : null);
});

document.getElementById('colorBtn').onclick = () => {
  colorMode = colorMode === 'subsystem' ? 'material' : 'subsystem';
  document.getElementById('colorBtn').textContent = `Color: ${colorMode}`;
  applyColors();
};
document.getElementById('resetBtn').onclick = () => homeView();
const fitBtn = document.getElementById('fitBtn'); if (fitBtn) fitBtn.onclick = () => fitView();
const layoutBtn = document.getElementById('layoutBtn');
if (layoutBtn) layoutBtn.onclick = () => { layout = layout === 'assembled' ? 'grid' : 'assembled'; applyLayout(); homeView(); };
const slider = document.getElementById('explodeSlider');
if (slider) slider.oninput = () => setExplode((+slider.value) / 100);
const clearBtn = document.getElementById('explodeClear');
if (clearBtn) clearBtn.onclick = () => { if (slider) slider.value = 0; setExplode(0); };

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

function animate() { requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }
main();

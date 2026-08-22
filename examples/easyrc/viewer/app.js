import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const SUB_COLORS = {
  'drivetrain': 0xe0a458,
  'chassis': 0x6b7f95,
  'wheels': 0x4fb0a5,
  'suspension-steering': 0xa78bfa,
  'body-exterior': 0xe07a8b,
  'other': 0x8a94a6,
};
const CELL = 46;            // grid cell size (world units)
const FIT = 34;             // target size each part is scaled to fill

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1117);
const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.1, 5000);
camera.position.set(160, 150, 260);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(innerWidth, innerHeight);
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
document.getElementById('view').appendChild(renderer.domElement);

scene.add(new THREE.HemisphereLight(0xbcd0e6, 0x202832, 1.05));
const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(120, 200, 140); scene.add(key);
const rim = new THREE.DirectionalLight(0x88aaff, 0.5); rim.position.set(-160, 80, -120); scene.add(rim);

const grid = new THREE.GridHelper(1200, 60, 0x24304a, 0x18202f);
grid.position.y = -30; scene.add(grid);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.target.set(0, 0, 0);

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let colorMode = 'subsystem';
const entries = [];         // { part, group, mesh, baseColor }
let selected = null;

function makeLabel(text) {
  const c = document.createElement('canvas'); const s = 256; c.width = s; c.height = 64;
  const ctx = c.getContext('2d');
  ctx.fillStyle = 'rgba(13,17,23,0.0)'; ctx.fillRect(0, 0, s, 64);
  ctx.font = '600 22px system-ui, sans-serif'; ctx.fillStyle = '#c8d3e0';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(text.length > 22 ? text.slice(0, 21) + '…' : text, s / 2, 34);
  const tex = new THREE.CanvasTexture(c); tex.anisotropy = 4;
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
  spr.scale.set(30, 7.5, 1);
  return spr;
}

const loader = new GLTFLoader();
const loadGLB = (url) => new Promise((res, rej) => loader.load(url, (g) => res(g), undefined, rej));

async function main() {
  const data = await (await fetch('parts.json')).json();
  const parts = data.parts;
  document.getElementById('count').textContent = `${parts.length} parts`;

  // grid ordered by subsystem then name
  const order = ['drivetrain', 'suspension-steering', 'wheels', 'chassis', 'body-exterior', 'other'];
  parts.sort((a, b) => (order.indexOf(a.subsystem) - order.indexOf(b.subsystem)) || a.name.localeCompare(b.name));
  const cols = Math.ceil(Math.sqrt(parts.length));

  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    let gltf;
    try { gltf = await loadGLB(part.glb); } catch (e) { console.warn('load fail', part.name); continue; }
    const geo = [];
    gltf.scene.traverse((o) => { if (o.isMesh) geo.push(o.geometry); });
    if (!geo.length) continue;
    const geometry = geo[0].index ? geo[0] : geo[0];
    geometry.computeVertexNormals();
    geometry.computeBoundingBox();
    const bb = geometry.boundingBox; const size = new THREE.Vector3(); bb.getSize(size);
    const center = new THREE.Vector3(); bb.getCenter(center);
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    const scale = FIT / maxDim;

    const baseColor = new THREE.Color(SUB_COLORS[part.subsystem] || 0x8a94a6);
    const mat = new THREE.MeshStandardMaterial({
      color: baseColor.clone(), metalness: 0.15, roughness: 0.65, flatShading: false,
    });
    const mesh = new THREE.Mesh(geometry, mat);
    mesh.geometry.translate(-center.x, -center.y, -center.z);   // center the part
    mesh.scale.setScalar(scale);

    const group = new THREE.Group();
    group.add(mesh);
    const col = i % cols, row = Math.floor(i / cols);
    group.position.set((col - (cols - 1) / 2) * CELL, 0, (row - Math.ceil(parts.length / cols - 1) / 2) * CELL);
    const label = makeLabel(part.name); label.position.set(0, -FIT / 2 - 6, 0); group.add(label);
    scene.add(group);

    mesh.userData = { part, baseColor, mat };
    entries.push({ part, group, mesh, baseColor });
  }
  buildSidebar(parts);
  animate();
}

function applyColors() {
  for (const e of entries) {
    const c = colorMode === 'material'
      ? (e.part.material === 'TPU-flex' ? new THREE.Color(0x33383f) : new THREE.Color(0xb9c2cf))
      : e.baseColor;
    e.mesh.material.color.copy(e.mesh === selected ? new THREE.Color(0xffd166) : c);
    e.mesh.material.emissive.setHex(e.mesh === selected ? 0x5a4200 : 0x000000);
  }
}

function select(mesh) {
  selected = mesh; applyColors();
  const p = mesh?.userData.part;
  const info = document.getElementById('info');
  if (!p) { info.innerHTML = '<div class="hint">Click a part to inspect</div>'; return; }
  info.innerHTML = `
    <div class="pill" style="background:#${(SUB_COLORS[p.subsystem]||0x8a94a6).toString(16).padStart(6,'0')}">${p.subsystem}</div>
    <h2>${p.name}</h2>
    <table>
      <tr><td>Material</td><td>${p.material}</td></tr>
      <tr><td>Size (mm)</td><td>${p.bboxMm.join(' × ')}</td></tr>
      <tr><td>Triangles</td><td>${p.tris.toLocaleString()}</td></tr>
      <tr><td>Source</td><td>${p.glb.replace('assets/','')} (STEP→GLB)</td></tr>
    </table>`;
  [...document.querySelectorAll('.pnav')].forEach((el) => el.classList.toggle('active', el.dataset.id === p.partId));
}

function focusOn(mesh) {
  const wp = new THREE.Vector3(); mesh.parent.getWorldPosition(wp);
  controls.target.copy(wp);
  const dir = new THREE.Vector3().subVectors(camera.position, wp).normalize();
  camera.position.copy(wp).add(dir.multiplyScalar(70));
}

function buildSidebar(parts) {
  const groups = {};
  for (const p of parts) (groups[p.subsystem] ??= []).push(p);
  const nav = document.getElementById('nav');
  nav.innerHTML = '';
  for (const sub of Object.keys(groups)) {
    const h = document.createElement('div'); h.className = 'ghead';
    h.innerHTML = `<span class="dot" style="background:#${(SUB_COLORS[sub]||0x8a94a6).toString(16).padStart(6,'0')}"></span>${sub} <em>${groups[sub].length}</em>`;
    nav.appendChild(h);
    for (const p of groups[sub]) {
      const d = document.createElement('div'); d.className = 'pnav'; d.dataset.id = p.partId;
      d.textContent = p.name;
      d.onclick = () => { const e = entries.find((x) => x.part.partId === p.partId); if (e) { select(e.mesh); focusOn(e.mesh); } };
      nav.appendChild(d);
    }
  }
}

renderer.domElement.addEventListener('pointerdown', (ev) => {
  pointer.x = (ev.clientX / innerWidth) * 2 - 1;
  pointer.y = -((ev.clientY / innerHeight) * 2 - 1);
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(entries.map((e) => e.mesh), false);
  if (hits.length) select(hits[0].object);
});

document.getElementById('colorBtn').onclick = () => {
  colorMode = colorMode === 'subsystem' ? 'material' : 'subsystem';
  document.getElementById('colorBtn').textContent = `Color: ${colorMode}`;
  applyColors();
};
document.getElementById('resetBtn').onclick = () => {
  camera.position.set(160, 150, 260); controls.target.set(0, 0, 0); selected = null; applyColors(); select(null);
};

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

function animate() { requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }
main();

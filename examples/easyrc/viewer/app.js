const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const COLORS = {
  background: 0x0b0f14,
  base: 0x737f8f,
  hardware: 0x4f5967,
  selected: 0xc8f44c,
  neighbor: 0x3f8cff,
  thread: 0xc8f44c,
};

const ASSEMBLY_DATA_ROOT = '/.artifacts/easyrc-ui/data';
const GROUP_SPREAD = 0.27;
const PART_SPREAD = 0.4;
const PART_PHASE_START = 0.28;
const MAX_CLUSTER_RADIUS = 0.48;
const EXPLODED_MODEL_SCALE = 0.7;

const state = {
  mode: 'assembled',
  selected: null,
  neighbors: [],
  components: [],
  componentByName: new Map(),
  catalogByName: new Map(),
  carCenter: new THREE.Vector3(),
  carRadius: 1,
  worldCarBox: null,
  explodeProgress: 0,
  explodeTarget: 0,
  modelScale: 1,
  modelScaleTarget: 1,
};

const viewport = $('#viewport');
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.25;
viewport.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(COLORS.background);
scene.fog = new THREE.FogExp2(COLORS.background, 0.00045);

const camera = new THREE.PerspectiveCamera(38, 1, 0.5, 4000);
const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.075;
controls.zoomToCursor = true;

scene.add(new THREE.HemisphereLight(0xdde7f5, 0x202832, 1.35));
const keyLight = new THREE.DirectionalLight(0xffffff, 2.25);
keyLight.position.set(300, 420, 280);
scene.add(keyLight);
const rimLight = new THREE.DirectionalLight(0x3f8cff, 0.8);
rimLight.position.set(-260, 160, -220);
scene.add(rimLight);

const ground = new THREE.GridHelper(900, 45, 0x223049, 0x172131);
ground.position.y = -82;
scene.add(ground);

const modelRoot = new THREE.Group();
const threadRoot = new THREE.Group();
modelRoot.add(threadRoot);
scene.add(modelRoot);

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const interactiveMeshes = [];
const relationLines = [];

function normalizedName(name) {
  return String(name || '')
    .trim()
    .replace(/\s+\(\d+\)$/i, '')
    .replace(/\s+/g, ' ')
    .toLowerCase();
}

function componentName(part) {
  return String(part.name || part.parent || `Mesh ${part.i + 1}`).trim();
}

function subsystemFor(name) {
  return state.catalogByName.get(normalizedName(name))?.subsystem || 'assembly hardware';
}

function createComponent(name) {
  const group = new THREE.Group();
  group.name = name;
  modelRoot.add(group);
  const component = {
    name,
    group,
    meshes: [],
    box: new THREE.Box3(),
    center: new THREE.Vector3(),
    size: new THREE.Vector3(),
    target: new THREE.Vector3(),
    motionTarget: new THREE.Vector3(),
    groupDirection: new THREE.Vector3(),
    partDirection: new THREE.Vector3(),
    clusterRadius: 1,
    subsystem: subsystemFor(name),
  };
  state.components.push(component);
  state.componentByName.set(name, component);
  return component;
}

function geometryFromPart(part, posBuffer, idxBuffer, packed) {
  const vertexCount = part.pCount;
  const quantized = new Uint16Array(posBuffer, part.pOff, vertexCount * 3);
  const positions = new Float32Array(vertexCount * 3);
  for (let i = 0; i < vertexCount; i += 1) {
    positions[i * 3] = quantized[i * 3] * packed.scale[0] + packed.min[0];
    positions[i * 3 + 1] = quantized[i * 3 + 1] * packed.scale[1] + packed.min[1];
    positions[i * 3 + 2] = quantized[i * 3 + 2] * packed.scale[2] + packed.min[2];
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

  if (part.nrm) {
    const packedNormals = new Int8Array(posBuffer, part.pOff + vertexCount * 6, vertexCount * 3);
    const normals = new Float32Array(vertexCount * 3);
    for (let i = 0; i < normals.length; i += 1) normals[i] = packedNormals[i] / 127;
    geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
  } else {
    geometry.computeVertexNormals();
  }

  const indexArray = part.i32
    ? new Uint32Array(idxBuffer, part.iOff, part.iCount)
    : new Uint16Array(idxBuffer, part.iOff, part.iCount);
  geometry.setIndex(new THREE.BufferAttribute(indexArray.slice(), 1));
  return geometry;
}

function baseColorFor(component) {
  return component.subsystem === 'assembly hardware' ? COLORS.hardware : COLORS.base;
}

function applyComponentStyle(component, color, opacity) {
  for (const mesh of component.meshes) {
    mesh.material.color.setHex(color);
    mesh.material.emissive.setHex(color === COLORS.selected ? 0x334a00 : color === COLORS.neighbor ? 0x071d42 : 0x000000);
    mesh.material.opacity = opacity;
    mesh.material.transparent = opacity < 1;
    mesh.material.depthWrite = opacity > 0.18;
    mesh.material.needsUpdate = true;
  }
}

function boxDistance(a, b) {
  const dx = Math.max(0, a.min.x - b.max.x, b.min.x - a.max.x);
  const dy = Math.max(0, a.min.y - b.max.y, b.min.y - a.max.y);
  const dz = Math.max(0, a.min.z - b.max.z, b.min.z - a.max.z);
  return Math.hypot(dx, dy, dz);
}

function nearestComponents(component, limit = 5) {
  return state.components
    .filter((candidate) => candidate !== component && candidate.name !== 'EasyRC Rx V1.3 v3')
    .map((candidate) => ({ component: candidate, distance: boxDistance(component.box, candidate.box) }))
    .sort((a, b) => a.distance - b.distance || a.component.name.localeCompare(b.component.name))
    .slice(0, limit)
    .map((item) => item.component);
}

function fallbackDirection(index) {
  const angle = Math.PI * (3 - Math.sqrt(5)) * index;
  const y = 1 - ((index + 0.5) / Math.max(state.components.length, 1)) * 2;
  const radius = Math.sqrt(Math.max(0, 1 - y * y));
  return new THREE.Vector3(Math.cos(angle) * radius, y, Math.sin(angle) * radius).normalize();
}

function smoothstep(edge0, edge1, value) {
  const amount = Math.min(1, Math.max(0, (value - edge0) / (edge1 - edge0)));
  return amount * amount * (3 - 2 * amount);
}

function prepareExplodeVectors() {
  const clusters = new Map();
  for (const component of state.components) {
    if (!clusters.has(component.subsystem)) {
      clusters.set(component.subsystem, { center: new THREE.Vector3(), count: 0, radius: 1 });
    }
    const cluster = clusters.get(component.subsystem);
    cluster.center.add(component.center);
    cluster.count += 1;
  }

  for (const cluster of clusters.values()) cluster.center.divideScalar(cluster.count);

  for (const component of state.components) {
    const cluster = clusters.get(component.subsystem);
    cluster.radius = Math.max(
      cluster.radius,
      component.center.distanceTo(cluster.center) + component.size.length() * 0.25,
    );
  }

  state.components.forEach((component, index) => {
    const cluster = clusters.get(component.subsystem);
    component.groupDirection.copy(cluster.center).sub(state.carCenter);
    if (component.groupDirection.lengthSq() < 0.01) component.groupDirection.copy(fallbackDirection(index));
    component.groupDirection.normalize();

    component.partDirection.copy(component.center).sub(cluster.center);
    if (component.partDirection.lengthSq() < 0.01) component.partDirection.copy(fallbackDirection(index + 17));
    component.partDirection.normalize();
    component.clusterRadius = Math.min(cluster.radius, state.carRadius * MAX_CLUSTER_RADIUS);
  });
}

function explodeOffset(component, progress, target) {
  const groupPhase = smoothstep(0, 0.64, progress);
  const partPhase = smoothstep(PART_PHASE_START, 1, progress);
  target.copy(component.groupDirection).multiplyScalar(groupPhase * GROUP_SPREAD * state.carRadius);
  target.addScaledVector(component.partDirection, partPhase * PART_SPREAD * component.clusterRadius);
  return target;
}

function clearThreads() {
  while (threadRoot.children.length) {
    const child = threadRoot.children.pop();
    child.geometry.dispose();
    child.material.dispose();
  }
  relationLines.length = 0;
}

function buildThreads() {
  clearThreads();
  if (!state.selected) return;
  for (const neighbor of state.neighbors) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(18), 3));
    const material = new THREE.LineBasicMaterial({
      color: COLORS.thread,
      transparent: true,
      opacity: 0.68,
      depthTest: false,
    });
    const line = new THREE.Line(geometry, material);
    line.renderOrder = 50;
    threadRoot.add(line);
    relationLines.push({ line, from: state.selected, to: neighbor });
  }
}

function updateThreads() {
  for (const relation of relationLines) {
    const start = relation.from.center.clone().add(relation.from.group.position);
    const end = relation.to.center.clone().add(relation.to.group.position);
    const middle = start.clone().add(end).multiplyScalar(0.5);
    middle.z += Math.max(8, start.distanceTo(end) * 0.14);
    const curve = new THREE.QuadraticBezierCurve3(start, middle, end);
    const points = curve.getPoints(5);
    const attribute = relation.line.geometry.getAttribute('position');
    points.forEach((point, index) => attribute.setXYZ(index, point.x, point.y, point.z));
    attribute.needsUpdate = true;
  }
}

function setMode(mode) {
  state.mode = mode;
  state.explodeTarget = mode === 'exploded' ? 1 : 0;
  state.modelScaleTarget = mode === 'exploded' ? EXPLODED_MODEL_SCALE : 1;
  $$('.mode-button').forEach((button) => button.classList.toggle('active', button.dataset.mode === mode));

  const titles = {
    assembled: 'Complete assembly',
    focus: 'Focus',
    exploded: 'Exploded assembly',
  };
  $('#modeTitle').textContent = titles[mode];

  for (const component of state.components) {
    component.target.set(0, 0, 0);
    let opacity = 1;
    let color = baseColorFor(component);

    if (state.selected) {
      if (component === state.selected) {
        color = COLORS.selected;
        opacity = 1;
      } else if (state.neighbors.includes(component)) {
        color = COLORS.neighbor;
        opacity = 1;
        if (mode === 'focus') {
          const direction = component.center.clone().sub(state.selected.center);
          if (direction.lengthSq() < 0.01) direction.set(1, 0, 0);
          component.target.copy(direction.normalize().multiplyScalar(26));
        }
      } else if (mode === 'focus') {
        opacity = 0.035;
      } else {
        opacity = 0.34;
      }
    }

    applyComponentStyle(component, color, opacity);
  }

  buildThreads();
}

function dimensions(component) {
  const longest = Math.max(component.size.x, component.size.y, component.size.z);
  return `${longest.toFixed(1)} mm`;
}

function updateInspector() {
  const selected = state.selected;
  $('#selectionName').textContent = selected?.name || 'Nothing selected';
  $('#selectionMeshes').textContent = selected ? selected.meshes.length.toLocaleString() : '0';
  $('#selectionSize').textContent = selected ? dimensions(selected) : '0 mm';
  $('#selectionStats').hidden = !selected;
  $('#relatedHeading').hidden = !selected;

  const list = $('#neighborList');
  if (!selected) {
    list.innerHTML = '';
    return;
  }
  list.innerHTML = state.neighbors.map((component) => `
    <button class="neighbor-button" type="button" data-component="${escapeAttribute(component.name)}">
      <i></i><span>${escapeHtml(component.name)}</span>
    </button>
  `).join('');
  $$('.neighbor-button').forEach((button) => {
    button.onclick = () => selectComponent(state.componentByName.get(button.dataset.component));
  });
}

function selectComponent(component) {
  if (!component) return;
  state.selected = component;
  state.neighbors = nearestComponents(component);
  $$('.part-button').forEach((button) => button.classList.toggle('active', button.dataset.component === component.name));
  updateInspector();
  setMode(state.mode);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function escapeAttribute(value) {
  return escapeHtml(value);
}

function buildPartsList(filter = '') {
  const needle = filter.trim().toLowerCase();
  const groups = new Map();
  for (const component of state.components) {
    const catalog = state.catalogByName.get(normalizedName(component.name));
    if (!catalog) continue;
    if (needle && !component.name.toLowerCase().includes(needle)) continue;
    const subsystem = catalog.subsystem || 'other';
    if (!groups.has(subsystem)) groups.set(subsystem, []);
    groups.get(subsystem).push(component);
  }

  $('#partsList').innerHTML = [...groups.entries()].map(([subsystem, components]) => `
    <div class="group-title"><i class="group-dot"></i>${escapeHtml(subsystem)}<span>${components.length}</span></div>
    ${components.sort((a, b) => a.name.localeCompare(b.name)).map((component) => `
      <button class="part-button${state.selected === component ? ' active' : ''}" type="button" data-component="${escapeAttribute(component.name)}">${escapeHtml(component.name)}</button>
    `).join('')}
  `).join('');

  $$('.part-button').forEach((button) => {
    button.onclick = () => selectComponent(state.componentByName.get(button.dataset.component));
  });
}

function fitCamera(box) {
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z);
  const halfFov = THREE.MathUtils.degToRad(camera.fov * 0.5);
  const verticalDistance = size.y / (2 * Math.tan(halfFov));
  const horizontalDistance = size.x / (2 * Math.tan(halfFov) * Math.max(camera.aspect, 0.2));
  const distance = Math.max(verticalDistance, horizontalDistance, size.z * 1.4) * 2;
  const direction = new THREE.Vector3(1, 0.72, 1.14).normalize();
  camera.position.copy(center).addScaledVector(direction, distance);
  camera.lookAt(center);
  controls.target.copy(center);
  controls.minDistance = radius * 0.18;
  controls.maxDistance = radius * 3;
  controls.update();
  controls.saveState();
}

async function loadScene() {
  const [packed, posBuffer, idxBuffer, catalog] = await Promise.all([
    fetch(`${ASSEMBLY_DATA_ROOT}/mesh.json`).then((response) => response.json()),
    fetch(`${ASSEMBLY_DATA_ROOT}/mesh_pos.bin`).then((response) => response.arrayBuffer()),
    fetch(`${ASSEMBLY_DATA_ROOT}/mesh_idx.bin`).then((response) => response.arrayBuffer()),
    fetch('/examples/easyrc/viewer/parts.json').then((response) => response.json()),
  ]);

  for (const part of catalog.parts) state.catalogByName.set(normalizedName(part.name), part);

  for (const part of packed.parts) {
    const name = componentName(part);
    const component = state.componentByName.get(name) || createComponent(name);
    const geometry = geometryFromPart(part, posBuffer, idxBuffer, packed);
    const material = new THREE.MeshStandardMaterial({
      color: baseColorFor(component),
      roughness: 0.57,
      metalness: 0.22,
      transparent: true,
      opacity: 0.9,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.userData.component = component;
    mesh.userData.sourcePart = part;
    component.meshes.push(mesh);
    component.group.add(mesh);
    interactiveMeshes.push(mesh);
  }

  for (const component of state.components) {
    component.box.setFromObject(component.group);
    component.box.getCenter(component.center);
    component.box.getSize(component.size);
    component.subsystem = subsystemFor(component.name);
  }

  const localCarBox = new THREE.Box3();
  for (const component of state.components) localCarBox.union(component.box);
  localCarBox.getCenter(state.carCenter);
  const localCarSize = localCarBox.getSize(new THREE.Vector3());
  state.carRadius = Math.max(localCarSize.x, localCarSize.y, localCarSize.z) * 0.5;
  prepareExplodeVectors();

  // The STEP assembly uses Z as up. Rotate the complete scene once so every
  // view mode and relationship line shares the same upright coordinate frame.
  modelRoot.rotation.x = -Math.PI / 2;
  const rotatedCenter = state.carCenter.clone().applyEuler(modelRoot.rotation);
  modelRoot.position.copy(rotatedCenter).multiplyScalar(-1);

  const worldCarBox = new THREE.Box3().setFromObject(modelRoot);
  state.worldCarBox = worldCarBox.clone();
  ground.position.y = worldCarBox.min.y - 8;
  fitCamera(worldCarBox);
  buildPartsList();
  setMode('assembled');

  $('#loading').remove();
}

renderer.domElement.addEventListener('pointerdown', (event) => {
  if (event.button !== 0) return;
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(interactiveMeshes, false);
  const hit = hits.find((candidate) => candidate.object.material.opacity > 0.12);
  if (hit) selectComponent(hit.object.userData.component);
});

$$('.mode-button').forEach((button) => {
  button.onclick = () => setMode(button.dataset.mode);
});

$('#resetButton').onclick = () => state.worldCarBox && fitCamera(state.worldCarBox);
$('#partSearch').addEventListener('input', (event) => buildPartsList(event.target.value));

function resize() {
  const width = viewport.clientWidth;
  const height = viewport.clientHeight;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(viewport);
resize();

let lastFrame = performance.now();

function animate(now = performance.now()) {
  requestAnimationFrame(animate);
  const delta = Math.min((now - lastFrame) / 1000, 0.05);
  lastFrame = now;
  state.explodeProgress = THREE.MathUtils.damp(
    state.explodeProgress,
    state.explodeTarget,
    5.2,
    delta,
  );
  state.modelScale = THREE.MathUtils.damp(
    state.modelScale,
    state.modelScaleTarget,
    5.2,
    delta,
  );
  modelRoot.scale.setScalar(state.modelScale);
  const motionAlpha = 1 - Math.exp(-9 * delta);
  for (const component of state.components) {
    if (state.mode === 'exploded') {
      explodeOffset(component, state.explodeProgress, component.motionTarget);
    } else {
      component.motionTarget.copy(component.target);
    }
    component.group.position.lerp(component.motionTarget, motionAlpha);
  }
  updateThreads();
  controls.update();
  renderer.render(scene, camera);
}
animate();

loadScene().catch((error) => {
  console.error(error);
  $('#loading').innerHTML = '<b>Assembly unavailable</b>';
});

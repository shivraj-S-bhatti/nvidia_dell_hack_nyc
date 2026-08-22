(() => {
  'use strict';

  const SELECTED = 0xc9f64d;

  function materialColor(name) {
    const value = String(name || '').toUpperCase();
    if (/TIRE|TYRE|GUMI|RUBBER/.test(value)) return 0x171c22;
    if (/PCB|BOARD|EASYEDA/.test(value)) return 0x315b4a;
    if (/SCREW|BOLT|NUT|WASHER|ISO_|DIN_|ASME_|BEARING/.test(value)) return 0x424b56;
    if (/WING|BODY|COVER|SHELL|SST/.test(value)) return 0x9aabbc;
    if (/RIM|WHEEL/.test(value)) return 0x687788;
    return 0x748293;
  }

  function geometryFromPart(part, packed, positionBuffer, indexBuffer, computeNormals = false) {
    const quantized = new Uint16Array(positionBuffer, part.pOff, part.pCount * 3);
    const positions = new Float32Array(part.pCount * 3);
    for (let index = 0; index < part.pCount; index += 1) {
      positions[index * 3] = quantized[index * 3] * packed.scale[0] + packed.min[0];
      positions[index * 3 + 1] = quantized[index * 3 + 1] * packed.scale[1] + packed.min[1];
      positions[index * 3 + 2] = quantized[index * 3 + 2] * packed.scale[2] + packed.min[2];
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const indices = part.i32
      ? new Uint32Array(indexBuffer, part.iOff, part.iCount)
      : new Uint16Array(indexBuffer, part.iOff, part.iCount);
    geometry.setIndex(new THREE.BufferAttribute(indices.slice(), 1));
    if (computeNormals) geometry.computeVertexNormals();
    geometry.computeBoundingBox();
    return geometry;
  }

  class VehicleViewer {
    constructor(options) {
      this.container = options.container;
      this.asset = options.asset;
      this.onSelect = options.onSelect || (() => {});
      this.onDisplayReady = options.onDisplayReady || (() => {});
      this.onReady = options.onReady || (() => {});
      this.onError = options.onError || (() => {});
      this.fallbackImage = options.fallbackImage || '';
      this.meshes = [];
      this.meshesByOccurrence = new Map();
      this.meshesByComponent = new Map();
      this.selectedMeshes = [];
      this.selectedSet = new Set();
      this.pendingSelection = null;
      this.pointerStart = null;
      this.explodeProgress = 0;
      this.explodeTarget = 0;
      this.mode = 'assembled';
      this.lastFrame = performance.now();
      this.ready = false;
      this.displayReady = false;
      this.visible = true;
      this.initialize();
    }

    initialize() {
      this.container.innerHTML = '<div class="vehicle-loading"><span></span><b>Loading selectable assembly</b><small>647 occurrence identities · local mesh</small></div>';
      try {
        this.renderer = new THREE.WebGLRenderer({antialias: true, alpha: true, powerPreference: 'high-performance'});
      } catch (error) {
        this.fail(error);
        return;
      }
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
      this.renderer.outputColorSpace = THREE.SRGBColorSpace;
      this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
      this.renderer.toneMappingExposure = 1.18;
      this.renderer.domElement.className = 'vehicle-canvas';
      this.renderer.domElement.setAttribute('aria-label', 'Interactive selectable NeoRacer assembly');
      this.container.prepend(this.renderer.domElement);

      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 5000);
      this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.075;
      this.controls.zoomToCursor = true;
      this.controls.screenSpacePanning = true;
      this.controls.minPolarAngle = 0.04;
      this.controls.maxPolarAngle = Math.PI * 0.96;

      this.scene.add(new THREE.HemisphereLight(0xdce8f5, 0x18212c, 1.5));
      const keyLight = new THREE.DirectionalLight(0xffffff, 2.45);
      keyLight.position.set(360, 480, 320);
      this.scene.add(keyLight);
      const fillLight = new THREE.DirectionalLight(0x6fa7ff, 1.2);
      fillLight.position.set(-310, 120, -280);
      this.scene.add(fillLight);
      const rimLight = new THREE.DirectionalLight(0xc9f64d, 0.42);
      rimLight.position.set(40, 260, -380);
      this.scene.add(rimLight);

      this.model = new THREE.Group();
      this.scene.add(this.model);
      this.raycaster = new THREE.Raycaster();
      this.pointer = new THREE.Vector2();

      this.renderer.domElement.addEventListener('contextmenu', (event) => event.preventDefault());
      this.renderer.domElement.addEventListener('pointerdown', (event) => {
        if (event.button === 0) this.pointerStart = {x: event.clientX, y: event.clientY};
      });
      this.renderer.domElement.addEventListener('pointerup', (event) => this.pick(event));
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(this.container);
      this.resize();
      this.animate = this.animate.bind(this);
      requestAnimationFrame(this.animate);
      this.load();
    }

    async load() {
      try {
        const [packed, positionBuffer, indexBuffer] = await Promise.all([
          fetch(this.asset.meshUrl).then((response) => {
            if (!response.ok) throw new Error(`mesh manifest HTTP ${response.status}`);
            return response.json();
          }),
          fetch(this.asset.positionUrl).then((response) => {
            if (!response.ok) throw new Error(`position mesh HTTP ${response.status}`);
            return response.arrayBuffer();
          }),
          fetch(this.asset.indexUrl).then((response) => {
            if (!response.ok) throw new Error(`index mesh HTTP ${response.status}`);
            return response.arrayBuffer();
          }),
        ]);
        if (packed.schemaVersion !== 'autoauto.interactive-mesh/v1') throw new Error('unsupported interactive mesh');

        if (!packed.display) throw new Error('complete root-assembly display mesh is missing');
        this.displayMaterial = new THREE.MeshStandardMaterial({
          color: 0x8797a8,
          roughness: 0.5,
          metalness: 0.2,
          transparent: true,
          side: THREE.DoubleSide,
        });
        this.displayMesh = new THREE.Mesh(
          geometryFromPart(packed.display, packed, positionBuffer, indexBuffer, true),
          this.displayMaterial,
        );
        this.displayMesh.name = packed.display.name;
        this.model.add(this.displayMesh);

        this.bounds = new THREE.Box3().setFromObject(this.displayMesh);
        const size = this.bounds.getSize(new THREE.Vector3());
        this.radius = Math.max(size.x, size.y, size.z) * 0.5;
        this.grid = new THREE.GridHelper(Math.max(size.x, size.z) * 1.8, 48, 0x2d4058, 0x182333);
        this.grid.position.y = this.bounds.min.y - Math.max(5, size.y * 0.035);
        this.scene.add(this.grid);
        this.fitCamera();
        this.updateStyles();
        this.renderer.render(this.scene, this.camera);
        this.displayReady = true;
        this.onDisplayReady({triangles: this.asset.counts.triangles});
        const loading = this.container.querySelector('.vehicle-loading');
        loading?.remove();
        await new Promise((resolve) => requestAnimationFrame(resolve));

        for (let partIndex = 0; partIndex < packed.parts.length; partIndex += 1) {
          const part = packed.parts[partIndex];
          const baseColor = materialColor(part.name);
          const material = new THREE.MeshBasicMaterial({
            color: baseColor,
            transparent: true,
            side: THREE.DoubleSide,
            opacity: 0,
            depthWrite: false,
            colorWrite: false,
          });
          const mesh = new THREE.Mesh(geometryFromPart(part, packed, positionBuffer, indexBuffer), material);
          mesh.userData.part = part;
          mesh.userData.baseColor = baseColor;
          this.meshes.push(mesh);
          this.meshesByOccurrence.set(part.occurrenceId, mesh);
          for (const componentId of part.ancestorComponentIds) {
            if (!this.meshesByComponent.has(componentId)) this.meshesByComponent.set(componentId, []);
            this.meshesByComponent.get(componentId).push(mesh);
          }
          this.model.add(mesh);
          if (partIndex > 0 && partIndex % 24 === 0) await new Promise((resolve) => requestAnimationFrame(resolve));
        }

        this.prepareExplosion();
        this.updateStyles();
        this.renderer.render(this.scene, this.camera);
        this.container.querySelector('.vehicle-loading')?.remove();
        this.ready = true;
        if (this.pendingSelection) {
          const {kind, id} = this.pendingSelection;
          this.pendingSelection = null;
          if (kind === 'component') this.selectComponent(id);
          else this.selectOccurrence(id);
        }
        this.onReady({parts: this.meshes.length, triangles: this.asset.counts.triangles});
      } catch (error) {
        this.fail(error);
      }
    }

    fail(error) {
      const loading = this.container.querySelector('.vehicle-loading');
      if (this.displayReady) {
        loading?.remove();
      } else if (loading && this.fallbackImage) {
        loading.innerHTML = `<img class="vehicle-fallback" src="${this.fallbackImage}" alt="Verified NeoRacer assembly">`;
      } else if (loading) {
        loading.innerHTML = '<b>Interactive assembly unavailable</b><small>Verified static fallback unavailable</small>';
      }
      this.onError(error);
    }

    fitCamera(box = this.bounds) {
      if (!box) return;
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      const halfFov = THREE.MathUtils.degToRad(this.camera.fov * 0.5);
      const vertical = size.y / (2 * Math.tan(halfFov));
      const horizontal = size.x / (2 * Math.tan(halfFov) * Math.max(this.camera.aspect, 0.2));
      const sphereDistance = size.length() * 0.5 / Math.sin(halfFov);
      const distance = Math.max(vertical, horizontal, sphereDistance) * 1.08;
      const direction = new THREE.Vector3(1.18, 0.52, 0.82).normalize();
      this.camera.position.copy(center).addScaledVector(direction, distance);
      this.camera.lookAt(center);
      this.controls.target.copy(center);
      const localRadius = Math.max(size.x, size.y, size.z) * 0.5;
      this.controls.minDistance = Math.max(localRadius * 0.12, 0.5);
      this.controls.maxDistance = Math.max(this.radius * 6, localRadius * 5);
      this.controls.update();
      this.controls.saveState();
    }

    prepareExplosion() {
      const carCenter = this.bounds.getCenter(new THREE.Vector3());
      const clusters = new Map();
      for (const mesh of this.meshes) {
        const center = mesh.geometry.boundingBox.getCenter(new THREE.Vector3());
        mesh.userData.center = center;
        const clusterId = mesh.userData.part.ancestorOccurrenceIds[0] || mesh.userData.part.occurrenceId;
        if (!clusters.has(clusterId)) clusters.set(clusterId, {center: new THREE.Vector3(), meshes: [], radius: 1});
        const cluster = clusters.get(clusterId);
        cluster.center.add(center);
        cluster.meshes.push(mesh);
      }
      for (const cluster of clusters.values()) {
        cluster.center.divideScalar(cluster.meshes.length);
        for (const mesh of cluster.meshes) {
          cluster.radius = Math.max(cluster.radius, mesh.userData.center.distanceTo(cluster.center));
        }
      }
      let fallbackIndex = 0;
      for (const cluster of clusters.values()) {
        const groupDirection = cluster.center.clone().sub(carCenter);
        if (groupDirection.lengthSq() < 0.001) {
          const angle = fallbackIndex * 2.399963;
          groupDirection.set(Math.cos(angle), ((fallbackIndex % 5) - 2) * 0.22, Math.sin(angle));
        }
        groupDirection.normalize();
        for (const mesh of cluster.meshes) {
          const partDirection = mesh.userData.center.clone().sub(cluster.center);
          if (partDirection.lengthSq() < 0.001) partDirection.copy(groupDirection);
          partDirection.normalize();
          mesh.userData.explodeOffset = groupDirection.clone().multiplyScalar(this.radius * 0.31)
            .addScaledVector(partDirection, Math.min(cluster.radius, this.radius * 0.28) * 0.52);
        }
        fallbackIndex += 1;
      }
    }

    setExploded(expanded) {
      this.setMode(expanded ? 'exploded' : 'assembled');
    }

    setMode(mode) {
      if (!['assembled', 'focus', 'exploded'].includes(mode)) return;
      this.mode = mode;
      this.explodeTarget = mode === 'exploded' ? 1 : 0;
      if (mode === 'focus') this.focusSelection();
      if (mode === 'assembled') this.fitCamera();
      this.updateStyles();
    }

    focusSelection() {
      if (!this.selectedMeshes.length) return;
      const box = new THREE.Box3();
      for (const mesh of this.selectedMeshes) {
        box.union(mesh.geometry.boundingBox.clone().translate(mesh.position));
      }
      if (!box.isEmpty()) this.fitCamera(box.expandByScalar(Math.max(2, box.getSize(new THREE.Vector3()).length() * 0.18)));
    }

    reset() {
      this.mode = 'assembled';
      this.explodeTarget = 0;
      this.clearSelection();
      this.fitCamera();
    }

    clearSelection(notify = false) {
      this.selectedMeshes = [];
      this.selectedSet = new Set();
      this.updateStyles();
      if (notify) this.onSelect(null);
    }

    applySelection(meshes) {
      this.selectedMeshes = meshes;
      this.selectedSet = new Set(meshes);
      this.updateStyles();
      if (this.mode === 'focus') this.focusSelection();
    }

    updateStyles() {
      if (!this.displayMaterial) return;
      const progress = this.explodeProgress;
      const hasSelection = this.selectedSet.size > 0;
      this.displayMaterial.opacity = progress > 0.002
        ? Math.max(0.07, 1 - progress * 0.93)
        : this.mode === 'focus' ? 0.045 : hasSelection ? 0.22 : 1;
      this.displayMaterial.depthWrite = progress < 0.002 && !hasSelection;
      this.displayMesh.renderOrder = 0;
      for (const mesh of this.meshes) {
        if (this.selectedSet.has(mesh)) {
          mesh.material.color.setHex(SELECTED);
          mesh.material.opacity = 1;
          mesh.material.colorWrite = true;
          mesh.material.depthWrite = false;
          mesh.material.depthTest = false;
          mesh.renderOrder = 3;
        } else {
          mesh.material.color.setHex(mesh.userData.baseColor);
          mesh.material.opacity = progress;
          mesh.material.colorWrite = progress > 0.002;
          mesh.material.depthWrite = progress > 0.72;
          mesh.material.depthTest = true;
          mesh.renderOrder = progress > 0.002 ? 2 : 0;
        }
      }
    }

    selectOccurrence(occurrenceId) {
      if (!this.ready) {
        this.pendingSelection = {kind: 'occurrence', id: occurrenceId};
        return;
      }
      const mesh = this.meshesByOccurrence.get(occurrenceId);
      if (!mesh) return;
      this.applySelection([mesh]);
    }

    selectComponent(componentId) {
      if (!this.ready) {
        this.pendingSelection = {kind: 'component', id: componentId};
        return;
      }
      const meshes = [...new Set(this.meshesByComponent.get(componentId) || [])];
      if (!meshes.length) {
        this.clearSelection();
        return;
      }
      this.applySelection(meshes);
    }

    pick(event) {
      if (!this.ready || event.button !== 0 || !this.pointerStart) return;
      const distance = Math.hypot(event.clientX - this.pointerStart.x, event.clientY - this.pointerStart.y);
      this.pointerStart = null;
      if (distance > 5) return;
      const rect = this.renderer.domElement.getBoundingClientRect();
      this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      this.raycaster.setFromCamera(this.pointer, this.camera);
      const hit = this.raycaster.intersectObjects(this.meshes, false)[0];
      if (!hit) {
        this.clearSelection(true);
        return;
      }
      this.applySelection([hit.object]);
      this.onSelect(hit.object.userData.part);
    }

    setVisible(visible) {
      this.visible = Boolean(visible);
      this.container.hidden = !this.visible;
      if (this.visible) this.resize();
    }

    resize() {
      if (!this.renderer) return;
      const width = Math.max(1, this.container.clientWidth);
      const height = Math.max(1, this.container.clientHeight);
      this.renderer.setSize(width, height, false);
      this.camera.aspect = width / height;
      this.camera.updateProjectionMatrix();
    }

    animate(now = performance.now()) {
      requestAnimationFrame(this.animate);
      if (!this.visible || !this.renderer) return;
      const delta = Math.min((now - this.lastFrame) / 1000, 0.05);
      this.lastFrame = now;
      this.explodeProgress = THREE.MathUtils.damp(this.explodeProgress, this.explodeTarget, 5.4, delta);
      for (const mesh of this.meshes) {
        if (mesh.userData.explodeOffset) mesh.position.copy(mesh.userData.explodeOffset).multiplyScalar(this.explodeProgress);
      }
      this.updateStyles();
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    }
  }

  window.AutoAutoVehicleViewer = {
    create(options) {
      return new VehicleViewer(options);
    },
  };
})();

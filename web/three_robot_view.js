import * as THREE from './vendor/three/three.module.js';
import { OrbitControls } from './vendor/three/examples/jsm/controls/OrbitControls.js';

const modelParams = {
  h1: 0.71,
  l1: 0.58,
  l2: 0.229,
  h2: 0.06,
  k2Drop: 0.08,
  k2AxisLength: 0.18,
  k3AxisLength: 0.16,
  // K4 stays inside the confirmed 85 mm-wide small-arm envelope.
  k4AxisLength: 0.085,
  wristForwardOffset: 0.119,
  massageLength: 0.1531,
  largeArmShellLength: 0.72,
  smallArmEnvelopeHeight: 0.107,
};
const enclosurePreview = {
  rearY: -0.1155,
  frontY: 0.65,
  width: 0.361,
  bottomZ: -0.0125,
  topZ: 0.7475,
  slotRearY: -0.1,
  slotWidth: 0.15,
  stopRearY: 0.351,
  stopFrontY: 0.58,
  stopWidth: 0.085,
  stopThickness: 0.02,
  stopTopZ: 0.5745,
};
const viewer = {
  initialized: false,
  scene: null,
  camera: null,
  renderer: null,
  controls: null,
  links: {},
  labels: {},
  collisionLoaded: false,
  collisionGroup: null,
  enclosurePreviewGroup: null,
  previewLabels: {},
  renderRequested: false,
};

function requestRender() {
  if (!viewer.initialized || viewer.renderRequested) return;
  viewer.renderRequested = true;
  requestAnimationFrame(() => {
    viewer.renderRequested = false;
    viewer.renderer.render(viewer.scene, viewer.camera);
  });
}

function material(color) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.52, metalness: 0.16 });
}

function label(text) {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 64;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(15,23,42,0.74)';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#dbeafe';
  ctx.font = 'bold 28px system-ui, sans-serif';
  ctx.fillText(text, 16, 42);
  const texture = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true }));
  sprite.scale.set(0.18, 0.045, 1);
  return sprite;
}

function addPreviewBox(group, size, center, options) {
  const geometry = new THREE.BoxGeometry(size.x, size.y, size.z);
  const surface = new THREE.Mesh(
    geometry,
    new THREE.MeshStandardMaterial({
      color: options.color,
      transparent: true,
      opacity: options.opacity,
      roughness: 0.72,
      metalness: 0.08,
      depthWrite: false,
    }),
  );
  surface.position.set(center.x, center.y, center.z);
  surface.name = options.name;
  surface.renderOrder = options.renderOrder || 0;
  group.add(surface);

  if (options.edgeColor !== undefined) {
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry),
      new THREE.LineBasicMaterial({
        color: options.edgeColor,
        transparent: true,
        opacity: options.edgeOpacity ?? 1,
      }),
    );
    edges.position.copy(surface.position);
    edges.name = `${options.name}:edges`;
    edges.renderOrder = (options.renderOrder || 0) + 1;
    group.add(edges);
  }
}

function addEnclosurePreview() {
  if (!viewer.scene || viewer.enclosurePreviewGroup) return;

  const preview = new THREE.Group();
  preview.name = 'enclosure-preview-only';
  viewer.enclosurePreviewGroup = preview;
  viewer.scene.add(preview);

  const enclosureLength = enclosurePreview.frontY - enclosurePreview.rearY;
  const enclosureHeight = enclosurePreview.topZ - enclosurePreview.bottomZ;
  const enclosureCenterY = (enclosurePreview.frontY + enclosurePreview.rearY) * 0.5;
  const enclosureCenterZ = (enclosurePreview.topZ + enclosurePreview.bottomZ) * 0.5;
  const sideWidth = (enclosurePreview.width - enclosurePreview.slotWidth) * 0.5;
  const sideCenterX = (enclosurePreview.slotWidth + sideWidth) * 0.5;
  const rearBandLength = enclosurePreview.slotRearY - enclosurePreview.rearY;

  for (const x of [-sideCenterX, sideCenterX]) {
    addPreviewBox(
      preview,
      { x: sideWidth, y: enclosureLength, z: enclosureHeight },
      { x, y: enclosureCenterY, z: enclosureCenterZ },
      {
        name: 'enclosure-side',
        color: 0x64748b,
        opacity: 0.10,
        edgeColor: 0x94a3b8,
        edgeOpacity: 0.55,
      },
    );
  }

  addPreviewBox(
    preview,
    { x: enclosurePreview.slotWidth, y: rearBandLength, z: enclosureHeight },
    {
      x: 0,
      y: (enclosurePreview.slotRearY + enclosurePreview.rearY) * 0.5,
      z: enclosureCenterZ,
    },
    {
      name: 'enclosure-rear-band',
      color: 0x64748b,
      opacity: 0.10,
      edgeColor: 0x94a3b8,
      edgeOpacity: 0.55,
    },
  );

  addPreviewBox(
    preview,
    {
      x: enclosurePreview.slotWidth,
      y: enclosurePreview.frontY - enclosurePreview.slotRearY,
      z: enclosureHeight,
    },
    {
      x: 0,
      y: (enclosurePreview.frontY + enclosurePreview.slotRearY) * 0.5,
      z: enclosureCenterZ,
    },
    {
      name: 'enclosure-active-slot',
      color: 0x0ea5e9,
      opacity: 0.018,
      edgeColor: 0x38bdf8,
      edgeOpacity: 0.95,
      renderOrder: 2,
    },
  );

  addPreviewBox(
    preview,
    {
      x: enclosurePreview.stopWidth,
      y: enclosurePreview.stopFrontY - enclosurePreview.stopRearY,
      z: enclosurePreview.stopThickness,
    },
    {
      x: 0,
      y: (enclosurePreview.stopFrontY + enclosurePreview.stopRearY) * 0.5,
      z: enclosurePreview.stopTopZ - enclosurePreview.stopThickness * 0.5,
    },
    {
      name: 'small-arm-travel-stop-preview',
      color: 0xec4899,
      opacity: 0.72,
      edgeColor: 0xfbcfe8,
      edgeOpacity: 1,
      renderOrder: 4,
    },
  );

  viewer.previewLabels.slot = label('750x150 空槽');
  viewer.previewLabels.slot.position.set(-0.13, 0.08, 0.16);
  preview.add(viewer.previewLabels.slot);
  viewer.previewLabels.stop = label('229mm 限位');
  viewer.previewLabels.stop.position.set(-0.10, 0.47, 0.61);
  preview.add(viewer.previewLabels.stop);
}

async function loadCollisionModel() {
  if (viewer.collisionLoaded || !viewer.scene) return;
  viewer.collisionLoaded = true;
  viewer.collisionGroup = new THREE.Group();
  viewer.collisionGroup.name = 'enclosure-collision-model';
  viewer.scene.add(viewer.collisionGroup);
  try {
    const response = await fetch('/api/collision/model');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const model = await response.json();
    for (const obstacle of model.obstacles || []) {
      const min = obstacle.min || [];
      const max = obstacle.max || [];
      if (min.length !== 3 || max.length !== 3) continue;
      const size = new THREE.Vector3(max[0] - min[0], max[1] - min[1], max[2] - min[2]);
      if (size.x <= 0 || size.y <= 0 || size.z <= 0) continue;
      const geometry = new THREE.BoxGeometry(size.x, size.y, size.z);
      const surface = new THREE.Mesh(
        geometry,
        new THREE.MeshStandardMaterial({
          color: model.enabled ? 0xef4444 : 0x64748b,
          transparent: true,
          opacity: model.enabled ? 0.20 : 0.10,
          roughness: 0.8,
        }),
      );
      surface.position.set(
        (min[0] + max[0]) * 0.5,
        (min[1] + max[1]) * 0.5,
        (min[2] + max[2]) * 0.5,
      );
      surface.name = `collision:${obstacle.name || 'box'}`;
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry),
        new THREE.LineBasicMaterial({ color: model.enabled ? 0xdc2626 : 0x64748b }),
      );
      surface.add(edges);
      viewer.collisionGroup.add(surface);

      const margin = Number(model.safety_margin_m || 0);
      if (model.enabled && margin > 0) {
        const expanded = new THREE.BoxGeometry(
          size.x + margin * 2,
          size.y + margin * 2,
          size.z + margin * 2,
        );
        const marginEdges = new THREE.LineSegments(
          new THREE.EdgesGeometry(expanded),
          new THREE.LineDashedMaterial({ color: 0xf59e0b, dashSize: 0.025, gapSize: 0.015 }),
        );
        marginEdges.position.copy(surface.position);
        marginEdges.computeLineDistances();
        viewer.collisionGroup.add(marginEdges);
      }
    }
  } catch (error) {
    console.warn('collision model unavailable', error);
  }
}

function init(container) {
  if (viewer.initialized) return;
  viewer.scene = new THREE.Scene();
  viewer.scene.background = new THREE.Color(0x07111f);
  viewer.camera = new THREE.PerspectiveCamera(48, 1, 0.01, 100);
  viewer.camera.up.set(0, 0, 1);
  viewer.camera.position.set(0.7, -1.15, 1.65);
  viewer.camera.lookAt(0.1, 0.2, 0.55);

  viewer.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'low-power' });
  viewer.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
  viewer.renderer.shadowMap.enabled = false;
  container.appendChild(viewer.renderer.domElement);

  viewer.controls = new OrbitControls(viewer.camera, viewer.renderer.domElement);
  viewer.controls.target.set(0.1, 0.2, 0.55);
  viewer.controls.enableDamping = false;
  viewer.controls.minPolarAngle = 0.15;
  viewer.controls.maxPolarAngle = Math.PI * 0.48;

  viewer.scene.add(new THREE.HemisphereLight(0xdbeafe, 0x0f172a, 1.9));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(1.7, -2.1, 2.6);
  viewer.scene.add(key);
  const fill = new THREE.DirectionalLight(0x60a5fa, 0.85);
  fill.position.set(-1.4, 1.2, 1.6);
  viewer.scene.add(fill);

  const grid = new THREE.GridHelper(1.9, 19, 0x334155, 0x1e293b);
  grid.rotation.x = Math.PI / 2;
  viewer.scene.add(grid);
  const axes = new THREE.AxesHelper(0.35);
  axes.position.set(0, 0, 0.001);
  viewer.scene.add(axes);
  addEnclosurePreview();
  loadCollisionModel();

  viewer.links.k1 = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 1, 18), material(0xef4444));
  viewer.links.k2 = new THREE.Mesh(new THREE.BoxGeometry(1, 0.12, 0.075), material(0x22c55e));
  viewer.links.k2drop = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.16, 12), material(0x64748b));
  viewer.links.k3 = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.16, 18), material(0x3b82f6));
  viewer.links.k3axis = new THREE.Mesh(new THREE.CylinderGeometry(0.046, 0.046, 0.16, 18), material(0x06b6d4));
  viewer.links.k4 = new THREE.Mesh(new THREE.BoxGeometry(1, 0.085, modelParams.smallArmEnvelopeHeight), material(0xeab308));
  viewer.links.k5 = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.18, 18), material(0xa855f7));
  viewer.links.wrist = new THREE.Mesh(new THREE.BoxGeometry(1, 0.065, 0.055), material(0xf97316));
  viewer.links.massage = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 1, 18), material(0xef4444));

  for (const mesh of Object.values(viewer.links)) {
    viewer.scene.add(mesh);
  }

  for (const name of ['K0', 'K1', 'K2', 'K3', 'K4']) {
    viewer.labels[name] = label(name);
    viewer.scene.add(viewer.labels[name]);
  }

  const resize = () => {
    const rect = container.getBoundingClientRect();
    const width = Math.max(320, Math.floor(rect.width));
    const height = Math.max(380, Math.floor(rect.height));
    viewer.camera.aspect = width / height;
    viewer.camera.updateProjectionMatrix();
    viewer.renderer.setSize(width, height, false);
    requestRender();
  };
  resize();
  window.addEventListener('resize', resize);

  viewer.initialized = true;
  viewer.controls.addEventListener('change', requestRender);
  requestRender();
}

function cylinderBetween(mesh, a, b) {
  const start = new THREE.Vector3(a.x, a.y, a.z);
  const end = new THREE.Vector3(b.x, b.y, b.z);
  const center = start.clone().add(end).multiplyScalar(0.5);
  const direction = end.clone().sub(start);
  mesh.position.copy(center);
  mesh.scale.set(1, direction.length(), 1);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize());
}

function boxBetween(mesh, a, b, length) {
  const start = new THREE.Vector3(a.x, a.y, a.z);
  const end = new THREE.Vector3(b.x, b.y, b.z);
  const center = start.clone().add(end).multiplyScalar(0.5);
  const direction = end.clone().sub(start).normalize();
  mesh.position.copy(center);
  mesh.scale.set(length, 1, 1);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), direction);
}

function boxBetweenWithRoll(mesh, a, b, length, roll) {
  boxBetween(mesh, a, b, length);
  const rollQuat = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), roll);
  mesh.quaternion.multiply(rollQuat);
}

export function updateThreeRobot(container, state) {
  init(container);
  const axisMap = state.axis_map || [];
  const readDisplay = (globalAxis) => {
    const map = axisMap.find((axis) => axis.global_axis === globalAxis);
    const motorNative = state.groups?.[map?.group]?.motors?.[map?.axis]?.actual_motor_native || 0;
    return motorNative * (map?.motor_native_to_gui_display || 0.01);
  };
  const lift = state.groups?.[0]?.motors?.[0]?.actual_axis_si || 0;
  const q1 = THREE.MathUtils.degToRad(readDisplay(1));
  const q2 = THREE.MathUtils.degToRad(readDisplay(2));
  const q3 = THREE.MathUtils.degToRad(readDisplay(3));
  const q4 = THREE.MathUtils.degToRad(readDisplay(4));
  const dir = (angle) => ({ x: Math.sin(angle), y: Math.cos(angle), z: 0 });
  const k2AxisDir = () => ({ x: 0, y: 0, z: 1 });
  const smallArmSideDir = (yaw) => ({ x: Math.cos(yaw), y: -Math.sin(yaw), z: 0 });
  const add = (a, b) => ({ x: a.x + b.x, y: a.y + b.y, z: a.z + b.z });
  const mul = (v, s) => ({ x: v.x * s, y: v.y * s, z: v.z * s });
  const rotateAroundAxis = (v, axis, angle) => {
    const result = new THREE.Vector3(v.x, v.y, v.z).applyAxisAngle(new THREE.Vector3(axis.x, axis.y, axis.z).normalize(), angle);
    return { x: result.x, y: result.y, z: result.z };
  };

  const p0 = { x: 0, y: 0, z: 0 };
  const p1 = { x: 0, y: 0, z: modelParams.h1 + lift };
  const p2 = add(p1, mul(dir(q1), modelParams.l1));
  const p3top = p2;
  const p3bottom = { x: p2.x, y: p2.y, z: p2.z - modelParams.k2Drop };
  const smallArmYaw = q1 + q2 + Math.PI;
  const smallArmForward = dir(smallArmYaw);
  const p4 = add(p3bottom, mul(smallArmForward, modelParams.l2));
  const k2Axis = mul(k2AxisDir(q2), modelParams.k2AxisLength * 0.5);
  const p2axisA = { x: p2.x - k2Axis.x, y: p2.y - k2Axis.y, z: p2.z - k2Axis.z };
  const p2axisB = add(p2, k2Axis);
  const k3Axis = mul(smallArmForward, modelParams.k3AxisLength * 0.5);
  const p3axisA = { x: p3bottom.x - k3Axis.x, y: p3bottom.y - k3Axis.y, z: p3bottom.z - k3Axis.z };
  const p3axisB = add(p3bottom, k3Axis);
  const k4AxisDirection = rotateAroundAxis(smallArmSideDir(smallArmYaw), smallArmForward, q3);
  const k4Axis = mul(k4AxisDirection, modelParams.k4AxisLength * 0.5);
  const p5a = { x: p4.x - k4Axis.x, y: p4.y - k4Axis.y, z: p4.z - k4Axis.z };
  const p5b = add(p4, k4Axis);
  const massageAxis = rotateAroundAxis(
    rotateAroundAxis({ x: 0, y: 0, z: 1 }, smallArmForward, q3),
    k4AxisDirection,
    q4,
  );
  const wristForward = rotateAroundAxis(smallArmForward, k4AxisDirection, q4);
  const wristEnd = add(p4, mul(wristForward, modelParams.wristForwardOffset));
  const p6a = wristEnd;
  const p6b = { x: wristEnd.x - massageAxis.x * modelParams.massageLength, y: wristEnd.y - massageAxis.y * modelParams.massageLength, z: wristEnd.z - massageAxis.z * modelParams.massageLength };

  cylinderBetween(viewer.links.k1, p0, p1);
  boxBetween(viewer.links.k2, p1, p2, modelParams.largeArmShellLength);
  cylinderBetween(viewer.links.k2drop, p3bottom, p3top);
  cylinderBetween(viewer.links.k3, p2axisA, p2axisB);
  cylinderBetween(viewer.links.k3axis, p3axisA, p3axisB);
  boxBetweenWithRoll(viewer.links.k4, p3bottom, p4, modelParams.l2, q3);
  cylinderBetween(viewer.links.k5, p5a, p5b);
  boxBetween(viewer.links.wrist, p4, wristEnd, modelParams.wristForwardOffset);
  cylinderBetween(viewer.links.massage, p6a, p6b);

  const labels = { K0: p0, K1: p1, K2: p2, K3: p3bottom, K4: p4 };
  for (const [name, p] of Object.entries(labels)) viewer.labels[name].position.set(p.x, p.y, p.z + 0.035);
  requestRender();
  return {
    x_m: p6b.x,
    y_m: p6b.y,
    z_m: p6b.z,
    source: 'absolute_encoder_feedback',
  };
}

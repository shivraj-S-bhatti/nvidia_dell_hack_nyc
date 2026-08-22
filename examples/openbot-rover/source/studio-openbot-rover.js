// Native PartMode schema-5 proxy for an OpenBot-style Blocky rover.
//
// This is newly authored demonstrator geometry. It uses OpenBot only as a
// visual and BOM reference; it is not a conversion of OpenBot's production
// CAD and does not claim recovered mates, dimensions, or engineering intent.

const round3 = (value) => Math.round(value * 1000) / 1000;

const translation = (x = 0, y = 0, z = 0) => [
  1, 0, 0, 0,
  0, 1, 0, 0,
  0, 0, 1, 0,
  x, y, z, 1,
];

const rotateX90 = (x, y, z) => [
  1, 0, 0, 0,
  0, 0, 1, 0,
  0, -1, 0, 0,
  x, y, z, 1,
];

const rotateXMinus90 = (x, y, z) => [
  1, 0, 0, 0,
  0, 0, -1, 0,
  0, 1, 0, 0,
  x, y, z, 1,
];

const rotateY90 = (x, y, z) => [
  0, 0, -1, 0,
  0, 1, 0, 0,
  1, 0, 0, 0,
  x, y, z, 1,
];

const rect = (x, y, w, h) => ({ kind: 'rect', x, y, w, h });
const circle = (x, y, r) => ({ kind: 'circle', x, y, r });
const poly = (pts) => ({ kind: 'poly', pts });

function material(slug, name, densityKgM3, baseColor, metallic, roughness) {
  return {
    id: `material-rover-${slug}`,
    name,
    densityKgM3,
    description: 'Conceptual material and appearance for the rover demonstrator.',
    source: 'Team-authored demo assumption; verify production materials independently.',
    appearanceId: `appearance-rover-${slug}`,
    extensions: {
      studioAppearance: {
        baseColor,
        metallic,
        roughness,
        opacity: 1,
        edgeColor: '#1b2430',
      },
    },
  };
}

const MATERIALS = Object.freeze([
  material('body-red', 'Printed red polymer', 1240, '#d83b32', 0.08, 0.38),
  material('accent-yellow', 'Printed yellow polymer', 1240, '#f2c94c', 0.06, 0.4),
  material('tire', 'Flexible black tire', 1120, '#20252b', 0.02, 0.72),
  material('tray-cyan', 'Printed cyan polymer', 1240, '#32a9b8', 0.06, 0.42),
  material('metal', 'Conceptual aluminum', 2700, '#a8b3bd', 0.7, 0.28),
  material('sensor', 'Sensor lens', 1180, '#ecf5ff', 0.18, 0.2),
]);

function identifiedShape(featureId, shape, index) {
  const id = `${featureId}:profile:${index + 1}`;
  return {
    ...shape,
    id,
    ...(shape.kind === 'poly'
      ? { edgeIds: shape.pts.map((_point, edgeIndex) => `${id}:edge:${edgeIndex + 1}`) }
      : {}),
  };
}

function makePart({ slug, name, role, materialSlug, parameters, operations, catalogOnly = false }) {
  const partId = `part-rover-${slug}`;
  const bodyId = `${partId}:body`;
  const featureIds = operations.map((operation) => `${partId}:feature:${operation.slug}`);
  const features = operations.map((operation, index) => {
    const featureId = featureIds[index];
    const isCut = operation.type === 'cut';
    return {
      id: featureId,
      name: operation.name,
      type: operation.type,
      sketch: {
        shapes: operation.shapes.map((shape, shapeIndex) => identifiedShape(featureId, shape, shapeIndex)),
        z: operation.z ?? 0,
      },
      through: operation.through === true,
      h: operation.h,
      suppressed: false,
      inputRefs: [],
      resultPolicy: index === 0
        ? { kind: 'new-body', bodyName: name }
        : isCut
          ? { kind: 'subtract', targetBodyIds: [bodyId], keepTools: false }
          : { kind: 'add', targetBodyIds: [bodyId] },
      ...(index === 0 ? { createdBodyId: bodyId } : {}),
    };
  });

  return {
    id: partId,
    name,
    parameters: parameters.map(({ name: parameterName, value, description }) => ({
      id: `${partId}:parameter:${parameterName}`,
      name: parameterName,
      value,
      ...(description ? { description } : {}),
    })),
    referenceGeometry: [],
    sketches: [],
    sketchBlockDefinitions: [],
    bodies: [{
      id: bodyId,
      name,
      kind: 'solid',
      createdByFeatureId: featureIds[0],
      featureIds,
      visible: true,
      suppressed: false,
      materialId: `material-rover-${materialSlug}`,
      appearanceId: `appearance-rover-${materialSlug}`,
    }],
    bodyPatterns: [],
    features,
    featureOrder: featureIds,
    metadata: {
      activeBodyId: bodyId,
      partNumber: `ROVER-${slug.toUpperCase()}`,
      revision: 'A',
      designStatus: 'concept-demonstrator',
    },
    extensions: {
      roverRole: role,
      agentCatalogOnly: catalogOnly,
    },
  };
}

function occurrence(id, name, partId, baseTransform, extensions = {}) {
  return {
    id,
    name,
    definition: { kind: 'part', partId },
    baseTransform,
    fixed: true,
    suppressed: false,
    visible: true,
    extensions,
  };
}

export function createOpenBotRoverProject(options = {}) {
  const wheelDiameterMm = Number(options.wheelDiameterMm ?? 65);
  if (!Number.isFinite(wheelDiameterMm) || wheelDiameterMm < 55 || wheelDiameterMm > 90) {
    throw new Error('wheelDiameterMm must be between 55 and 90.');
  }

  const bodyClearanceMm = 8;
  const groundClearanceMm = 12;
  const axleHeightMm = round3(wheelDiameterMm / 2);
  const wheelBaseMm = 110;
  const chassisLengthMm = 170;
  const chassisWidthMm = 100;
  const wheelTreadWidthMm = 18;
  const wheelInnerFaceY = chassisWidthMm / 2 + bodyClearanceMm;
  const panelCenterZ = 61;

  const chassis = makePart({
    slug: 'chassis',
    name: 'Blocky rover chassis',
    role: 'primary-structure',
    materialSlug: 'body-red',
    parameters: [
      { name: 'length', value: chassisLengthMm },
      { name: 'width', value: chassisWidthMm },
      { name: 'thickness', value: 6 },
    ],
    operations: [{ slug: 'base', name: 'Extrude chassis', type: 'extrude', shapes: [rect(0, 0, 'length', 'width')], h: 'thickness' }],
  });

  const topDeck = makePart({
    slug: 'top-deck',
    name: 'Blocky top deck',
    role: 'upper-structure',
    materialSlug: 'accent-yellow',
    parameters: [
      { name: 'length', value: 150 },
      { name: 'width', value: 86 },
      { name: 'thickness', value: 4 },
      { name: 'hole_dia', value: 4 },
    ],
    operations: [
      { slug: 'base', name: 'Extrude top deck', type: 'extrude', shapes: [rect(0, 0, 'length', 'width')], h: 'thickness' },
      {
        slug: 'holes', name: 'Cut deck mounting holes', type: 'cut', z: 'thickness', h: 'thickness*2', through: true,
        shapes: [circle(-60, -35, 'hole_dia/2'), circle(60, -35, 'hole_dia/2'), circle(-60, 35, 'hole_dia/2'), circle(60, 35, 'hole_dia/2')],
      },
    ],
  });

  const wheel = makePart({
    slug: 'wheel',
    name: 'Rover wheel',
    role: 'wheel',
    materialSlug: 'tire',
    parameters: [
      { name: 'wheel_dia', value: 'wheel_diameter_mm', description: 'Driven by the project wheel-size request.' },
      { name: 'tread_width', value: wheelTreadWidthMm },
      { name: 'bore_dia', value: 8 },
    ],
    operations: [
      { slug: 'tire', name: 'Extrude wheel', type: 'extrude', shapes: [circle(0, 0, 'wheel_dia/2')], h: 'tread_width' },
      { slug: 'bore', name: 'Cut axle bore', type: 'cut', z: 'tread_width', h: 'tread_width*2', through: true, shapes: [circle(0, 0, 'bore_dia/2')] },
    ],
  });

  const wheelGuard = makePart({
    slug: 'wheel-guard',
    name: 'Two-wheel side guard',
    role: 'wheel-well',
    materialSlug: 'body-red',
    parameters: [
      { name: 'length', value: 160 },
      { name: 'height', value: 98 },
      { name: 'thickness', value: 4 },
      { name: 'wheel_dia', value: 'wheel_diameter_mm' },
      { name: 'clearance', value: 'body_clearance_mm' },
      { name: 'axle_height', value: 'axle_height_mm' },
      { name: 'panel_center_z', value: panelCenterZ },
      { name: 'wheel_base', value: wheelBaseMm },
    ],
    operations: [
      { slug: 'panel', name: 'Extrude side guard', type: 'extrude', shapes: [rect(0, 0, 'length', 'height')], h: 'thickness' },
      {
        slug: 'wheel-wells', name: 'Cut wheel wells', type: 'cut', z: 'thickness', h: 'thickness*2', through: true,
        shapes: [
          circle('-wheel_base/2', 'axle_height-panel_center_z', 'wheel_dia/2+clearance'),
          circle('wheel_base/2', 'axle_height-panel_center_z', 'wheel_dia/2+clearance'),
        ],
      },
    ],
  });

  const motorMount = makePart({
    slug: 'motor-mount',
    name: 'Motor mount block',
    role: 'motor-mount',
    materialSlug: 'metal',
    parameters: [
      { name: 'length', value: 34 },
      { name: 'width', value: 24 },
      { name: 'height', value: 24 },
    ],
    operations: [{ slug: 'block', name: 'Extrude motor mount', type: 'extrude', shapes: [rect(0, 0, 'length', 'width')], h: 'height' }],
  });

  const batteryTray = makePart({
    slug: 'battery-tray',
    name: 'Battery tray',
    role: 'battery-tray',
    materialSlug: 'tray-cyan',
    parameters: [
      { name: 'width', value: 74 }, { name: 'depth', value: 46 }, { name: 'height', value: 12 }, { name: 'wall', value: 3 },
    ],
    operations: [
      { slug: 'outer', name: 'Extrude battery tray platform', type: 'extrude', shapes: [rect(0, 0, 'width', 'depth')], h: 'height' },
    ],
  });

  const electronicsTray = makePart({
    slug: 'electronics-tray',
    name: 'Electronics tray',
    role: 'electronics-tray',
    materialSlug: 'tray-cyan',
    parameters: [
      { name: 'width', value: 72 }, { name: 'depth', value: 52 }, { name: 'height', value: 12 }, { name: 'wall', value: 3 },
    ],
    operations: [
      { slug: 'outer', name: 'Extrude electronics tray platform', type: 'extrude', shapes: [rect(0, 0, 'width', 'depth')], h: 'height' },
    ],
  });

  const standoff = makePart({
    slug: 'deck-standoff',
    name: 'Deck standoff',
    role: 'standoff',
    materialSlug: 'metal',
    parameters: [
      { name: 'outer_dia', value: 12 }, { name: 'bore_dia', value: 4 }, { name: 'length', value: 77 },
    ],
    operations: [
      { slug: 'body', name: 'Extrude standoff', type: 'extrude', shapes: [circle(0, 0, 'outer_dia/2')], h: 'length' },
      { slug: 'bore', name: 'Cut standoff bore', type: 'cut', z: 'length', h: 'length*2', through: true, shapes: [circle(0, 0, 'bore_dia/2')] },
    ],
  });

  const cameraPlate = makePart({
    slug: 'camera-plate',
    name: 'Phone and camera plate',
    role: 'phone-camera-mount',
    materialSlug: 'accent-yellow',
    parameters: [
      { name: 'width', value: 64 }, { name: 'height', value: 46 }, { name: 'thickness', value: 4 },
    ],
    operations: [
      { slug: 'plate', name: 'Extrude camera plate', type: 'extrude', shapes: [rect(0, 0, 'width', 'height')], h: 'thickness' },
      { slug: 'lens', name: 'Cut lens opening', type: 'cut', z: 'thickness', h: 'thickness*2', through: true, shapes: [circle(0, 8, 8), rect(-20, -8, 5, 22), rect(20, -8, 5, 22)] },
    ],
  });

  const bumper = makePart({
    slug: 'front-bumper',
    name: 'Front eye bumper',
    role: 'bumper',
    materialSlug: 'accent-yellow',
    parameters: [{ name: 'length', value: 12 }, { name: 'width', value: 92 }, { name: 'height', value: 14 }],
    operations: [{ slug: 'beam', name: 'Extrude bumper', type: 'extrude', shapes: [rect(0, 0, 'length', 'width')], h: 'height' }],
  });

  const sensorEye = makePart({
    slug: 'sensor-eye',
    name: 'Sensor eye pod',
    role: 'sensor-pod',
    materialSlug: 'sensor',
    parameters: [{ name: 'outer_dia', value: 16 }, { name: 'length', value: 10 }],
    operations: [{ slug: 'pod', name: 'Extrude sensor eye', type: 'extrude', shapes: [circle(0, 0, 'outer_dia/2')], h: 'length' }],
  });

  const perforatedBeam = makePart({
    slug: 'catalog-perforated-beam',
    name: 'Catalog perforated beam',
    role: 'agent-catalog-beam',
    materialSlug: 'accent-yellow',
    catalogOnly: true,
    parameters: [{ name: 'length', value: 100 }, { name: 'width', value: 14 }, { name: 'thickness', value: 8 }, { name: 'hole_dia', value: 5 }],
    operations: [
      { slug: 'beam', name: 'Extrude beam', type: 'extrude', shapes: [rect(0, 0, 'length', 'width')], h: 'thickness' },
      { slug: 'holes', name: 'Cut beam holes', type: 'cut', z: 'thickness', h: 'thickness*2', through: true, shapes: [-40, -20, 0, 20, 40].map((x) => circle(x, 0, 'hole_dia/2')) },
    ],
  });

  const angleBracket = makePart({
    slug: 'catalog-angle-bracket',
    name: 'Catalog right-angle bracket',
    role: 'agent-catalog-bracket',
    materialSlug: 'metal',
    catalogOnly: true,
    parameters: [{ name: 'thickness', value: 10 }],
    operations: [{
      slug: 'bracket', name: 'Extrude angle bracket', type: 'extrude', h: 'thickness',
      shapes: [poly([[-18, -18], [18, -18], [18, -10], [-10, -10], [-10, 18], [-18, 18]])],
    }],
  });

  const axleSpacer = makePart({
    slug: 'catalog-axle-spacer',
    name: 'Catalog axle spacer',
    role: 'agent-catalog-spacer',
    materialSlug: 'metal',
    catalogOnly: true,
    parameters: [{ name: 'outer_dia', value: 16 }, { name: 'bore_dia', value: 8 }, { name: 'length', value: 10 }],
    operations: [
      { slug: 'body', name: 'Extrude axle spacer', type: 'extrude', shapes: [circle(0, 0, 'outer_dia/2')], h: 'length' },
      { slug: 'bore', name: 'Cut axle bore', type: 'cut', z: 'length', h: 'length*2', through: true, shapes: [circle(0, 0, 'bore_dia/2')] },
    ],
  });

  const occurrences = [
    occurrence('occ-rover-chassis', '01 Chassis', chassis.id, translation(0, 0, groundClearanceMm), { itemNumber: '01' }),
    occurrence('occ-rover-top-deck', '02 Top deck', topDeck.id, translation(0, 0, 95), { itemNumber: '02' }),
    occurrence('occ-rover-wheel-fore-left', '03 Front-left wheel', wheel.id, rotateX90(wheelBaseMm / 2, -wheelInnerFaceY, axleHeightMm), { itemNumber: '03', side: 'left', axle: 'front' }),
    occurrence('occ-rover-wheel-fore-right', '04 Front-right wheel', wheel.id, rotateXMinus90(wheelBaseMm / 2, wheelInnerFaceY, axleHeightMm), { itemNumber: '04', side: 'right', axle: 'front' }),
    occurrence('occ-rover-wheel-aft-left', '05 Rear-left wheel', wheel.id, rotateX90(-wheelBaseMm / 2, -wheelInnerFaceY, axleHeightMm), { itemNumber: '05', side: 'left', axle: 'rear' }),
    occurrence('occ-rover-wheel-aft-right', '06 Rear-right wheel', wheel.id, rotateXMinus90(-wheelBaseMm / 2, wheelInnerFaceY, axleHeightMm), { itemNumber: '06', side: 'right', axle: 'rear' }),
    occurrence('occ-rover-motor-left', '07 Left motor mount', motorMount.id, translation(0, -38, axleHeightMm - 12), { itemNumber: '07', side: 'left' }),
    occurrence('occ-rover-motor-right', '08 Right motor mount', motorMount.id, translation(0, 38, axleHeightMm - 12), { itemNumber: '08', side: 'right' }),
    occurrence('occ-rover-wheel-guard-left', '09 Left wheel guard', wheelGuard.id, rotateX90(0, -50, panelCenterZ), { itemNumber: '09', side: 'left' }),
    occurrence('occ-rover-wheel-guard-right', '10 Right wheel guard', wheelGuard.id, rotateX90(0, 54, panelCenterZ), { itemNumber: '10', side: 'right' }),
    occurrence('occ-rover-battery-tray', '11 Battery tray', batteryTray.id, translation(-42, 0, 20), { itemNumber: '11' }),
    occurrence('occ-rover-electronics-tray', '12 Electronics tray', electronicsTray.id, translation(42, 0, 20), { itemNumber: '12' }),
    occurrence('occ-rover-standoff-fore-left', '13 Front-left deck standoff', standoff.id, translation(60, -35, 18), { itemNumber: '13' }),
    occurrence('occ-rover-standoff-fore-right', '14 Front-right deck standoff', standoff.id, translation(60, 35, 18), { itemNumber: '14' }),
    occurrence('occ-rover-standoff-aft-left', '15 Rear-left deck standoff', standoff.id, translation(-60, -35, 18), { itemNumber: '15' }),
    occurrence('occ-rover-standoff-aft-right', '16 Rear-right deck standoff', standoff.id, translation(-60, 35, 18), { itemNumber: '16' }),
    occurrence('occ-rover-camera-plate', '17 Phone and camera plate', cameraPlate.id, rotateX90(44, 2, 106), { itemNumber: '17' }),
    occurrence('occ-rover-bumper', '18 Front bumper', bumper.id, translation(83, 0, 20), { itemNumber: '18' }),
    occurrence('occ-rover-eye-left', '19 Left sensor eye', sensorEye.id, rotateY90(89, -22, 38), { itemNumber: '19', side: 'left' }),
    occurrence('occ-rover-eye-right', '20 Right sensor eye', sensorEye.id, rotateY90(89, 22, 38), { itemNumber: '20', side: 'right' }),
  ];

  const explodedViewId = 'exploded-rover-service-layout';
  const rootAssembly = {
    id: 'assembly-openbot-blocky-rover',
    name: 'OpenBot-style Blocky rover',
    parameters: [],
    occurrences,
    mates: [],
    occurrencePatterns: [],
    explodedViews: [{
      id: explodedViewId,
      name: 'Blocky exploded layout',
      steps: [
        { occurrenceIds: ['occ-rover-top-deck'], deltaTransform: translation(0, 0, 42) },
        { occurrenceIds: ['occ-rover-wheel-fore-left', 'occ-rover-wheel-aft-left'], deltaTransform: translation(0, -38, 0) },
        { occurrenceIds: ['occ-rover-wheel-fore-right', 'occ-rover-wheel-aft-right'], deltaTransform: translation(0, 38, 0) },
        { occurrenceIds: ['occ-rover-wheel-guard-left'], deltaTransform: translation(0, -20, 0) },
        { occurrenceIds: ['occ-rover-wheel-guard-right'], deltaTransform: translation(0, 20, 0) },
        { occurrenceIds: ['occ-rover-battery-tray', 'occ-rover-electronics-tray'], deltaTransform: translation(0, 0, 24) },
        { occurrenceIds: ['occ-rover-camera-plate'], deltaTransform: translation(18, 0, 28) },
        { occurrenceIds: ['occ-rover-bumper', 'occ-rover-eye-left', 'occ-rover-eye-right'], deltaTransform: translation(24, 0, 0) },
      ],
      extensions: { studioDisplayOnly: true, purpose: 'agent-demo-exploded-view' },
    }],
    sectionViews: [],
    metadata: {
      activeExplodedViewId: explodedViewId,
      displayMode: 'shaded-edges',
      placementPolicy: 'deterministic-base-transforms',
      expectedExactBodyCount: occurrences.length,
    },
    extensions: { openBotStyleProxy: true },
  };

  const partDefinitions = [
    chassis, topDeck, wheel, wheelGuard, motorMount, batteryTray, electronicsTray,
    standoff, cameraPlate, bumper, sensorEye, perforatedBeam, angleBracket, axleSpacer,
  ];

  return {
    schemaVersion: 5,
    projectId: options.projectId || `project-openbot-blocky-rover-${Math.round(wheelDiameterMm)}mm`,
    name: options.name || `OpenBot-style Blocky rover - ${wheelDiameterMm} mm wheels`,
    units: 'mm',
    parameters: [
      { id: 'parameter-rover-wheel-diameter', name: 'wheel_diameter_mm', value: wheelDiameterMm, description: 'Shared wheel and wheel-well diameter.' },
      { id: 'parameter-rover-body-clearance', name: 'body_clearance_mm', value: bodyClearanceMm, description: 'Required radial wheel-to-body clearance.' },
      { id: 'parameter-rover-ground-clearance', name: 'ground_clearance_mm', value: groundClearanceMm, description: 'Chassis-bottom clearance above the ground plane.' },
      { id: 'parameter-rover-axle-height', name: 'axle_height_mm', value: 'wheel_diameter_mm/2', description: 'Keeps every wheel tangent to the same ground plane.' },
    ],
    materials: MATERIALS.map((entry) => structuredClone(entry)),
    partDefinitions,
    assemblyDefinitions: [rootAssembly],
    rootDocument: { kind: 'assembly', assemblyId: rootAssembly.id },
    resources: [],
    metadata: {
      templateId: 'openbot-blocky-rover-proxy',
      expectedExactBodyCount: occurrences.length,
      instantiatedPartDefinitionCount: partDefinitions.filter((part) => !part.extensions.agentCatalogOnly).length,
      catalogOnlyPartDefinitionCount: partDefinitions.filter((part) => part.extensions.agentCatalogOnly).length,
      openBotReference: 'https://github.com/ob-f/OpenBot/tree/master/body/diy/cad/block_body',
      modelPolicy: 'team-authored-parametric-proxy',
      limitations: [
        'This is a visual and dependency-graph demonstrator, not the official OpenBot body.',
        'Transforms are deterministic but are not recovered mates or kinematic constraints.',
        'No structural, collision-safety, manufacturability, or vehicle-performance claim is made.',
      ],
    },
    extensions: {
      agentContract: {
        operation: 'resize_wheels',
        allowedWheelDiametersMm: [65, 82],
        requiresTransformUpdates: [
          'occ-rover-wheel-fore-left', 'occ-rover-wheel-fore-right',
          'occ-rover-wheel-aft-left', 'occ-rover-wheel-aft-right',
          'occ-rover-motor-left', 'occ-rover-motor-right',
        ],
      },
    },
    partConfigurationSets: [],
  };
}

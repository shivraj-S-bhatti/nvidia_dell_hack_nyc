// Native schema-5 conceptual turbofan assembly.
//
// Every body is an exact feature result built through the ordinary typed
// document surface. Bodies of revolution (spinner, disks, shafts, drums,
// liners, cases with wall thickness and flanges) are advanced 360-degree
// Revolve features of closed profile sketches around an authored axis datum.
// Every blade, vane, and strut row is a Loft of staggered airfoil sections on
// authored section planes, so fan, compressor, and turbine rows carry real
// chord, camber, and twist rather than extruded slabs. One exact seed body per
// row is placed by authored mates and multiplied by an assembly circular
// occurrence pattern around the engine axis.
//
// No component relies on unconstrained fixed placement: each subassembly
// grounds exactly one anchor component with an authored Fixed mate and places
// every other component with concentric, distance, and angular mates (or three
// coincident plane mates for the off-axis fuel injector), and the root
// assembly mates its modules the same way. The template also ships a saved
// named exploded layout with axial separation, a saved longitudinal section
// view, and an initialized drawing book sheet whose assembly drawing carries
// the deterministic BOM and balloon plan.
//
// The model is intentionally a demonstrator, not an aerodynamic, structural,
// manufacturing, certification, or airworthiness definition.

const translationMatrix = (x = 0, y = 0, z = 0) => [
  1, 0, 0, 0,
  0, 1, 0, 0,
  0, 0, 1, 0,
  x, y, z, 1,
];

const round3 = (value) => Math.round(value * 1000) / 1000;

const material = (slug, name, densityKgM3, appearance, description) => ({
  id: `material-jet-${slug}`,
  name,
  densityKgM3,
  description,
  source: 'Conceptual PartMode material assignment; select and verify the production grade before engineering use.',
  appearanceId: `appearance-jet-${slug}`,
  extensions: {
    studioAppearance: {
      baseColor: appearance.baseColor,
      metallic: appearance.metallic,
      roughness: appearance.roughness,
      opacity: appearance.opacity ?? 1,
      edgeColor: appearance.edgeColor ?? '#263746',
    },
  },
});

const MATERIALS = Object.freeze([
  material('steel', 'Alloy steel', 7850, {
    baseColor: '#4d5d6c', metallic: 0.82, roughness: 0.32, edgeColor: '#141e28',
  }, 'Conceptual shafts, bearings, frames, and structural hardware.'),
  material('titanium', 'Titanium alloy', 4430, {
    baseColor: '#93a3af', metallic: 0.78, roughness: 0.26, edgeColor: '#2a3640',
  }, 'Conceptual fan and compressor blade and disk material.'),
  material('nickel', 'Nickel superalloy', 8200, {
    baseColor: '#8d7a68', metallic: 0.7, roughness: 0.33, edgeColor: '#33281f',
  }, 'Conceptual hot-section disk, blade, vane, and nozzle material.'),
  material('combustor', 'Nickel alloy combustor liner', 8250, {
    baseColor: '#a56a3e', metallic: 0.58, roughness: 0.38, edgeColor: '#3a2417',
  }, 'Conceptual annular combustor liner, dome, and injector material.'),
  material('aluminum', 'Aluminum alloy', 2780, {
    baseColor: '#b7c2cc', metallic: 0.74, roughness: 0.3, edgeColor: '#39485a',
  }, 'Conceptual fan case, inlet, and cold-section housing material.'),
]);

// ---------------------------------------------------------------------------
// Datum helpers. Every part carries the same authored mate frame set:
// the engine axis (local +X), a YZ station plane for axial distance mates,
// an XY plane and a ZX plane for angular clocking mates.
// ---------------------------------------------------------------------------

const datumId = (partId, suffix) => `${partId}:datum:${suffix}`;

function mateFrameDatums(partId) {
  return [
    {
      id: datumId(partId, 'axis'),
      name: 'Engine axis',
      kind: 'axis',
      suppressed: false,
      definition: { origin: [0, 0, 0], direction: [1, 0, 0] },
    },
    {
      id: datumId(partId, 'station-yz'),
      name: 'Axial station plane',
      kind: 'plane',
      suppressed: false,
      definition: { origin: [0, 0, 0], normal: [1, 0, 0], xDirection: [0, 1, 0] },
    },
    {
      id: datumId(partId, 'clock-xy'),
      name: 'Clocking XY plane',
      kind: 'plane',
      suppressed: false,
      definition: { origin: [0, 0, 0], normal: [0, 0, 1], xDirection: [1, 0, 0] },
    },
    {
      id: datumId(partId, 'clock-zx'),
      name: 'Clocking ZX plane',
      kind: 'plane',
      suppressed: false,
      definition: { origin: [0, 0, 0], normal: [0, 1, 0], xDirection: [0, 0, 1] },
    },
  ];
}

// Profile plane for bodies of revolution: sketch u maps to axial X and
// sketch v maps to radial +Z, so profile points are authored as (x, r).
function revolveProfilePlane(partId) {
  return {
    id: datumId(partId, 'profile-plane'),
    name: 'Revolve profile plane',
    kind: 'plane',
    suppressed: false,
    definition: { origin: [0, 0, 0], normal: [0, -1, 0], xDirection: [1, 0, 0] },
  };
}

// Airfoil section plane at blade span station z: sketch u maps to axial X
// and sketch v maps to tangential Y.
function bladeSectionPlane(partId, index, z) {
  return {
    id: datumId(partId, `section-${index + 1}`),
    name: `Airfoil section plane ${index + 1}`,
    kind: 'plane',
    suppressed: false,
    definition: { origin: [0, 0, round3(z)], normal: [0, 0, 1], xDirection: [1, 0, 0] },
  };
}

function bodyRecord(id, name, featureIds, materialSlug) {
  return {
    id,
    name,
    kind: 'solid',
    createdByFeatureId: featureIds[0],
    featureIds: [...featureIds],
    visible: true,
    suppressed: false,
    materialId: `material-jet-${materialSlug}`,
    appearanceId: `appearance-jet-${materialSlug}`,
  };
}

function partMetadata(partNumber, description) {
  return {
    activeBodyId: null,
    partNumber,
    revision: 'A',
    description,
    designStatus: 'concept-demonstrator',
  };
}

// ---------------------------------------------------------------------------
// Bodies of revolution.
// ---------------------------------------------------------------------------

function revolvePart({ slug, name, materialSlug, profile, description, role, extraDatums = () => [] }) {
  const partId = `part-jet-${slug}`;
  const bodyId = `${partId}:body`;
  const sketchId = `${partId}:sketch:profile`;
  const featureId = `${partId}:feature:revolve`;
  const metadata = partMetadata(`PM-JET-${slug.toUpperCase()}`, description);
  metadata.activeBodyId = bodyId;
  return {
    id: partId,
    name,
    parameters: [],
    referenceGeometry: [...mateFrameDatums(partId), revolveProfilePlane(partId), ...extraDatums(partId)],
    sketches: [{
      id: sketchId,
      name: `${name} revolve profile`,
      support: {
        ownerKind: 'datum',
        ownerId: datumId(partId, 'profile-plane'),
        semanticPath: { role: 'revolve-profile-plane' },
        signature: { role: 'plane' },
      },
      entities: [{
        id: `${sketchId}:outline`,
        kind: 'polyline',
        points: profile.map(([x, r]) => [round3(x), round3(r)]),
      }],
      groups: [],
      constraints: [],
      extensions: { studioRole: 'profile' },
    }],
    bodies: [bodyRecord(bodyId, name, [featureId], materialSlug)],
    bodyPatterns: [],
    features: [{
      id: featureId,
      name: `Revolve ${name}`,
      type: 'revolve',
      profileSketchId: sketchId,
      axisDatumId: datumId(partId, 'axis'),
      angle: 360,
      startAngle: 0,
      symmetric: false,
      resultPolicy: { kind: 'new-body', bodyName: name },
      createdBodyId: bodyId,
      suppressed: false,
      inputRefs: [],
    }],
    featureOrder: [featureId],
    metadata,
    extensions: { jetEngineRole: role || 'revolved-body' },
  };
}

// Thin conical case shell with wall thickness and bolt flanges at both ends.
// Front is the higher local x. Points run inner surface front-to-back, then
// rear flange, outer surface, and front flange.
function caseProfile(xFront, rFront, xRear, rRear, thickness, flangeHeight = 3.5, flangeWidth = 4) {
  const slope = (rFront - rRear) / (xFront - xRear);
  const outer = (x) => rRear + slope * (x - xRear) + thickness;
  return [
    [xFront, rFront],
    [xRear, rRear],
    [xRear, rRear + thickness + flangeHeight],
    [xRear + flangeWidth, rRear + thickness + flangeHeight],
    [xRear + flangeWidth, outer(xRear + flangeWidth)],
    [xFront - flangeWidth, outer(xFront - flangeWidth)],
    [xFront - flangeWidth, rFront + thickness + flangeHeight],
    [xFront, rFront + thickness + flangeHeight],
  ];
}

// Disk with a bored hub, thin web, and full-width rim, authored as one closed
// I-section profile of revolution.
function diskProfile(halfWidth, bore, rimInner, rimOuter, webHalfWidth) {
  return [
    [-halfWidth, bore],
    [halfWidth, bore],
    [halfWidth, bore + (rimInner - bore) * 0.35],
    [webHalfWidth, bore + (rimInner - bore) * 0.35],
    [webHalfWidth, rimInner],
    [halfWidth, rimInner],
    [halfWidth, rimOuter],
    [-halfWidth, rimOuter],
    [-halfWidth, rimInner],
    [-webHalfWidth, rimInner],
    [-webHalfWidth, bore + (rimInner - bore) * 0.35],
    [-halfWidth, bore + (rimInner - bore) * 0.35],
  ];
}

// ---------------------------------------------------------------------------
// Airfoil blade rows.
// ---------------------------------------------------------------------------

// Closed airfoil outline: NACA-style thickness distribution over a circular
// arc camber line, rotated by the stagger angle about mid-chord. Points are
// (axial, tangential) millimetres. camber and thickness are fractions of
// chord; a negative camber mirrors the section for vanes and turbine rows.
function airfoilSectionPoints({ chord, camber, thickness, staggerDeg }) {
  const halfThickness = (s) => {
    const t = thickness * chord;
    return (t / 0.2) * (0.2969 * Math.sqrt(s) - 0.126 * s - 0.3516 * s ** 2 + 0.2843 * s ** 3 - 0.1036 * s ** 4);
  };
  const camberLine = (s) => 4 * camber * chord * s * (1 - s);
  const upperStations = [0.1, 0.3, 0.55, 0.8];
  const lowerStations = [...upperStations].reverse();
  const raw = [
    [0, 0],
    ...upperStations.map((s) => [s * chord, camberLine(s) + halfThickness(s)]),
    [chord, 0],
    ...lowerStations.map((s) => [s * chord, camberLine(s) - halfThickness(s)]),
  ];
  const angle = (staggerDeg * Math.PI) / 180;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return raw.map(([u, v]) => {
    const centered = u - chord / 2;
    return [round3(centered * cos - v * sin), round3(centered * sin + v * cos)];
  });
}

// One blade or vane seed body: a Loft of staggered airfoil sections on
// authored span-station planes. Sections are ordered root to tip.
function bladePart({ slug, name, materialSlug, sections, description, role }) {
  const partId = `part-jet-${slug}`;
  const bodyId = `${partId}:body`;
  const featureId = `${partId}:feature:loft`;
  const sectionDatums = sections.map((section, index) => bladeSectionPlane(partId, index, section.z));
  const sketches = sections.map((section, index) => {
    const sketchId = `${partId}:sketch:section-${index + 1}`;
    return {
      id: sketchId,
      name: `${name} airfoil section ${index + 1}`,
      support: {
        ownerKind: 'datum',
        ownerId: sectionDatums[index].id,
        semanticPath: { role: `airfoil-section-${index + 1}` },
        signature: { role: 'plane' },
      },
      entities: [{
        id: `${sketchId}:airfoil`,
        kind: 'spline',
        points: airfoilSectionPoints(section),
      }],
      groups: [],
      constraints: [],
      extensions: { studioRole: 'profile' },
    };
  });
  const metadata = partMetadata(`PM-JET-${slug.toUpperCase()}`, description);
  metadata.activeBodyId = bodyId;
  return {
    id: partId,
    name,
    parameters: [],
    referenceGeometry: [...mateFrameDatums(partId), ...sectionDatums],
    sketches,
    bodies: [bodyRecord(bodyId, name, [featureId], materialSlug)],
    bodyPatterns: [],
    features: [{
      id: featureId,
      name: `Loft ${name}`,
      type: 'loft',
      sections: sketches.map((sketch) => ({ sketchId: sketch.id, startIndex: 0, reversed: false })),
      guideSketchIds: [],
      mapping: 'explicit',
      continuity: { start: 'free', end: 'free' },
      ruled: false,
      closed: false,
      resultPolicy: { kind: 'new-body', bodyName: name },
      createdBodyId: bodyId,
      suppressed: false,
      inputRefs: [],
    }],
    featureOrder: [featureId],
    metadata,
    extensions: {
      jetEngineRole: role || 'airfoil-row-seed',
      airfoil: {
        sections: sections.map((section) => ({
          spanZ: round3(section.z),
          chord: section.chord,
          staggerDeg: section.staggerDeg,
          camber: section.camber,
        })),
      },
    },
  };
}

// ---------------------------------------------------------------------------
// Occurrences, mates, and patterns.
// ---------------------------------------------------------------------------

function partOccurrence(id, name, partId, station = {}, extensions = {}) {
  return {
    id,
    name,
    definition: { kind: 'part', partId },
    baseTransform: translationMatrix(station.x ?? 0, station.y ?? 0, station.z ?? 0),
    fixed: false,
    suppressed: false,
    visible: true,
    extensions: { engineStationX: round3(station.x ?? 0), ...extensions },
  };
}

function datumReference(occurrencePath, partId, suffix, role, signatureRole) {
  return {
    ownerKind: 'datum',
    ownerId: datumId(partId, suffix),
    occurrencePath: [...occurrencePath],
    semanticPath: { role },
    signature: { role: signatureRole },
  };
}

function groundMate(scope, occurrenceId, name) {
  return {
    id: `${scope}:mate:ground`,
    name,
    kind: 'fixed',
    occurrenceIds: [occurrenceId],
    references: [],
    suppressed: false,
    extensions: { authoredGround: true },
  };
}

// Concentric on the engine axis, axial distance between station planes, and a
// 90-degree angular mate that removes the remaining clocking rotation.
function axialPlacementMates(scope, anchor, target, axialOffset) {
  const base = `${scope}:mate:${target.occurrenceId}`;
  return [
    {
      id: `${base}:concentric`,
      name: `${target.shortName} concentric to engine axis`,
      kind: 'concentric',
      occurrenceIds: [anchor.occurrenceId, target.occurrenceId],
      references: [
        datumReference([anchor.occurrenceId], anchor.partId, 'axis', 'anchor-axis', 'axis'),
        datumReference([target.occurrenceId], target.partId, 'axis', 'target-axis', 'axis'),
      ],
      suppressed: false,
    },
    {
      id: `${base}:distance`,
      name: `${target.shortName} axial station`,
      kind: 'distance',
      occurrenceIds: [anchor.occurrenceId, target.occurrenceId],
      references: [
        datumReference([anchor.occurrenceId], anchor.partId, 'station-yz', 'anchor-station', 'plane'),
        datumReference([target.occurrenceId], target.partId, 'station-yz', 'target-station', 'plane'),
      ],
      value: round3(axialOffset),
      suppressed: false,
    },
    {
      id: `${base}:clocking`,
      name: `${target.shortName} clocking angle`,
      kind: 'angle',
      occurrenceIds: [anchor.occurrenceId, target.occurrenceId],
      references: [
        datumReference([anchor.occurrenceId], anchor.partId, 'clock-xy', 'anchor-clock', 'plane'),
        datumReference([target.occurrenceId], target.partId, 'clock-zx', 'target-clock', 'plane'),
      ],
      value: 90,
      suppressed: false,
    },
  ];
}

function circularOccurrencePattern(assemblyId, occurrenceId, occurrenceName, totalMembers) {
  return {
    id: `${assemblyId}:pattern:${occurrenceId}`,
    name: `${occurrenceName} circular occurrence pattern`,
    kind: 'circular',
    sourceOccurrenceIds: [occurrenceId],
    generatedCount: totalMembers - 1,
    definition: { axis: [1, 0, 0], center: [0, 0, 0], totalAngle: 360 },
    suppressed: false,
    extensions: { engineAxis: 'X', totalMembers, exactSeedOccurrence: true },
  };
}

// Builds one module subassembly. Components are declared with their engine
// stations; the first component grounds the module and every other component
// is placed by authored mates relative to it.
function moduleAssembly(id, name, components, metadata = {}) {
  const occurrences = [];
  const mates = [];
  const occurrencePatterns = [];
  const anchorComponent = components[0];
  for (const [index, component] of components.entries()) {
    const occurrence = partOccurrence(
      component.occurrenceId,
      component.name,
      component.part.id,
      { x: component.x, z: component.z ?? 0 },
      component.patternMembers ? { patternMembers: component.patternMembers } : {},
    );
    occurrences.push(occurrence);
    if (index === 0) {
      mates.push(groundMate(id, component.occurrenceId, `${component.shortName} grounded anchor`));
    } else if (component.mates === 'planar') {
      mates.push(...component.buildMates(id, anchorComponent, component));
    } else {
      mates.push(...axialPlacementMates(
        id,
        { occurrenceId: anchorComponent.occurrenceId, partId: anchorComponent.part.id },
        { occurrenceId: component.occurrenceId, partId: component.part.id, shortName: component.shortName },
        component.x - anchorComponent.x,
      ));
    }
    if (component.patternMembers) {
      occurrencePatterns.push(circularOccurrencePattern(id, component.occurrenceId, component.name, component.patternMembers));
    }
  }
  return {
    id,
    name,
    parameters: [],
    occurrences,
    mates,
    occurrencePatterns,
    explodedViews: [],
    sectionViews: [],
    metadata: { ...metadata, placementPolicy: 'authored-mates' },
    extensions: { jetEngineSubsystem: true },
  };
}

function rootOccurrence(sequence, slug, label, assemblyId, elevationZ) {
  const itemNumber = String(sequence).padStart(2, '0');
  return {
    id: `occ-jet-root-${itemNumber}-${slug}`,
    name: `${itemNumber} · ${label}`,
    definition: { kind: 'assembly', assemblyId },
    baseTransform: translationMatrix(0, 0, elevationZ),
    fixed: false,
    suppressed: false,
    visible: true,
    extensions: {
      enumeration: itemNumber,
      itemNumber,
      initiallyExpanded: false,
      jetEngineSubsystem: slug,
    },
  };
}

// ---------------------------------------------------------------------------
// Drawing book: one ISO A3 sheet whose assembly drawing carries the exact
// BOM and balloon plan produced by the drawing pipeline.
// ---------------------------------------------------------------------------

function shippedDrawingBook() {
  return {
    schema: 'partmode.drawing-book/v1',
    sequence: 1,
    title: 'Turbofan demonstrator drawing set',
    activeSheetId: 'sheet-000001',
    sheets: [{
      id: 'sheet-000001',
      name: 'Engine assembly',
      format: {
        kind: 'template',
        templateId: 'iso-a3-landscape',
        id: 'iso-a3-landscape',
        name: 'ISO A3 landscape',
        standard: 'ISO',
        size: 'A3',
        widthMm: 420,
        heightMm: 297,
        projection: 'third-angle',
        titleBlock: 'iso-default',
      },
      scale: 'fit',
      views: ['front', 'top', 'right', 'iso'],
      tangentEdges: 'visible',
      alignments: [],
      description: 'Assembly sheet with the deterministic BOM and balloon plan.',
    }],
  };
}

// ---------------------------------------------------------------------------
// The engine.
// ---------------------------------------------------------------------------

export function createJetEngineAssemblyProject(options = {}) {
  // Engine axis runs along +X with the inlet forward (+X). All stations are
  // millimetres. Document +Z is the viewport up axis, so the whole engine is
  // elevated along +Z and the modeling grid reads as a floor below the
  // assembly instead of construction geometry slicing it.
  const ELEVATION_Z = 100;

  // Blade row plan: distinct counts, chords, and stagger angles per stage.
  const bladeRowPlan = {
    fanBlades: 16,
    outletGuideVanes: 14,
    compressorRotors: [20, 22, 24, 26, 28],
    compressorStators: [17, 19, 21, 23],
    fuelInjectors: 12,
    turbineNozzleVanes: [14, 16, 18],
    turbineRotors: [20, 22, 24],
    exhaustStruts: 6,
  };

  // Gas-path cones. Blade tips, vane roots, and embed depths are derived from
  // these instead of hand-typed so rows always hug their cases without
  // clearance or poke-through mistakes.
  const compCaseInnerAt = (x) => 36.5 + ((45.5 - 36.5) * (x - 20)) / 66;
  const turbCaseInnerAt = (x) => 42 + ((54.5 - 42) * (-16 - x)) / 48;
  const exhCaseInnerAt = (x) => 40 + ((54.5 - 40) * (x + 108)) / 44;
  const tailConeRadiusAt = (x) => {
    const local = x + 98;
    const pts = [[-20, 8], [0, 17], [20, 24], [32, 26]];
    for (let i = 0; i < pts.length - 1; i += 1) {
      const [x0, r0] = pts[i];
      const [x1, r1] = pts[i + 1];
      if (local >= x0 && local <= x1) return r0 + ((r1 - r0) * (local - x0)) / (x1 - x0);
    }
    return local < pts[0][0] ? pts[0][1] : pts.at(-1)[1];
  };
  const TIP_CLEARANCE = 1;
  const CASE_EMBED = 1.2;

  // ---- Fan and LP spool parts -------------------------------------------
  const spinner = revolvePart({
    slug: 'spinner-cone',
    name: 'Spinner cone',
    materialSlug: 'aluminum',
    role: 'spinner',
    description: 'Spinner cone covering the fan hub, revolved with a service bore.',
    profile: [
      [-16, 3], [-16, 33], [-8, 29.4], [2, 21.2], [11, 10.4], [16, 3],
    ],
  });
  const fanDisk = revolvePart({
    slug: 'fan-disk',
    name: 'Fan disk',
    materialSlug: 'titanium',
    role: 'rotor-disk',
    description: 'Fan disk with bored hub, thin web, and blade-carrying rim.',
    profile: diskProfile(10, 8, 26, 32, 2.2),
  });
  const fanBlade = bladePart({
    slug: 'fan-blade',
    name: 'Fan blade',
    materialSlug: 'titanium',
    role: 'fan-blade-seed',
    description: 'Wide-chord fan blade lofted from three staggered airfoil sections.',
    sections: [
      { z: 29, chord: 22, staggerDeg: 20, camber: 0.14, thickness: 0.17 },
      { z: 58, chord: 27, staggerDeg: 38, camber: 0.12, thickness: 0.11 },
      { z: 85, chord: 24, staggerDeg: 52, camber: 0.09, thickness: 0.07 },
    ],
  });
  const lpShaft = revolvePart({
    slug: 'lp-shaft',
    name: 'Low-pressure shaft',
    materialSlug: 'steel',
    role: 'shaft',
    description: 'Hollow low-pressure shaft with a stepped fan-disk seat.',
    profile: [
      [-99, 2.5], [-99, 6], [69, 6], [71, 8], [89, 8], [89, 2.5],
    ],
  });
  const bearing = revolvePart({
    slug: 'bearing-ring',
    name: 'Shaft bearing ring',
    materialSlug: 'steel',
    role: 'bearing',
    description: 'Shaft support bearing ring with inner and outer race grooves.',
    profile: [
      [-4, 6], [4, 6], [4, 8.6], [1.6, 8.6], [1.6, 10.4], [4, 10.4], [4, 12], [-4, 12],
      [-4, 10.4], [-1.6, 10.4], [-1.6, 8.6], [-4, 8.6],
    ],
  });

  // ---- Compressor parts -------------------------------------------------
  const compCase = revolvePart({
    slug: 'compressor-case',
    name: 'Compressor case',
    materialSlug: 'steel',
    role: 'case',
    description: 'Conical compressor case with wall thickness and bolt flanges.',
    profile: caseProfile(33, 45.5, -33, 36.5, 2.5),
  });
  const hpDrum = revolvePart({
    slug: 'hp-drum',
    name: 'High-pressure spool drum',
    materialSlug: 'steel',
    role: 'shaft',
    description: 'High-pressure spool drum carrying the compressor disks.',
    profile: [
      [-55, 10], [57, 10], [57, 12], [-55, 12],
    ],
  });
  const compDisk = revolvePart({
    slug: 'compressor-disk',
    name: 'Compressor rotor disk',
    materialSlug: 'titanium',
    role: 'rotor-disk',
    description: 'Compressor rotor disk with bored hub, web, and rim.',
    profile: diskProfile(3.5, 12, 24.5, 28, 1.6),
  });
  const compressorRotorStations = [78, 65, 52, 39, 26];
  const compressorRotorTips = compressorRotorStations.map((x) => round3(compCaseInnerAt(x) - TIP_CLEARANCE));
  const compressorRotorChords = [10, 9.5, 9, 8.5, 8];
  const compRotorBlades = compressorRotorStations.map((_, index) => bladePart({
    slug: `compressor-rotor-blade-${index + 1}`,
    name: `Compressor rotor blade stage ${index + 1}`,
    materialSlug: 'titanium',
    role: 'compressor-blade-seed',
    description: `Stage ${index + 1} compressor rotor blade lofted with stagger and twist.`,
    sections: [
      { z: 26.5, chord: compressorRotorChords[index], staggerDeg: 33, camber: 0.11, thickness: 0.16 },
      { z: compressorRotorTips[index], chord: compressorRotorChords[index] - 1.2, staggerDeg: 46, camber: 0.08, thickness: 0.1 },
    ],
  }));
  const compressorStatorStations = [71.5, 58.5, 45.5, 32.5];
  const compressorStatorOuter = compressorStatorStations.map((x) => round3(compCaseInnerAt(x) + CASE_EMBED));
  const compressorStatorChords = [9, 8.5, 8, 7.5];
  const compStatorVanes = compressorStatorStations.map((_, index) => bladePart({
    slug: `compressor-stator-vane-${index + 1}`,
    name: `Compressor stator vane stage ${index + 1}`,
    materialSlug: 'steel',
    role: 'compressor-vane-seed',
    description: `Stage ${index + 1} compressor stator vane lofted with reverse stagger.`,
    sections: [
      { z: 30, chord: compressorStatorChords[index], staggerDeg: -32, camber: -0.12, thickness: 0.15 },
      { z: compressorStatorOuter[index], chord: compressorStatorChords[index] - 0.8, staggerDeg: -40, camber: -0.09, thickness: 0.1 },
    ],
  }));
  const statorShroud = revolvePart({
    slug: 'stator-shroud',
    name: 'Stator inner shroud ring',
    materialSlug: 'steel',
    role: 'shroud',
    description: 'Inner shroud ring closing the stator vane row.',
    profile: [
      [-2, 28.6], [2, 28.6], [2, 30.5], [-2, 30.5],
    ],
  });

  // ---- Combustor parts --------------------------------------------------
  const combCase = revolvePart({
    slug: 'combustor-case',
    name: 'Combustor outer case',
    materialSlug: 'steel',
    role: 'case',
    description: 'Combustor outer case shell with wall thickness and flanges.',
    profile: caseProfile(18, 48, -18, 46, 2.5),
  });
  const combDome = revolvePart({
    slug: 'combustor-dome',
    name: 'Combustor dome ring',
    materialSlug: 'combustor',
    role: 'combustor-liner',
    description: 'Annular combustor dome carrying the fuel injector ring.',
    extraDatums: (partId) => [
      {
        id: datumId(partId, 'injector-yz'),
        name: 'Injector station plane',
        kind: 'plane',
        suppressed: false,
        definition: { origin: [2.5, 0, 0], normal: [1, 0, 0], xDirection: [0, 1, 0] },
      },
      {
        id: datumId(partId, 'injector-xy'),
        name: 'Injector orbit XY plane',
        kind: 'plane',
        suppressed: false,
        definition: { origin: [0, 0, 37], normal: [0, 0, 1], xDirection: [1, 0, 0] },
      },
      {
        id: datumId(partId, 'injector-zx'),
        name: 'Injector orbit ZX plane',
        kind: 'plane',
        suppressed: false,
        definition: { origin: [0, 0, 37], normal: [0, 1, 0], xDirection: [0, 0, 1] },
      },
    ],
    profile: [
      [-1.5, 28], [1.5, 28], [1.5, 45.5], [-1.5, 45.5],
    ],
  });
  const linerOuter = revolvePart({
    slug: 'combustor-liner-outer',
    name: 'Combustor outer liner',
    materialSlug: 'combustor',
    role: 'combustor-liner',
    description: 'Outer annular combustor liner shell.',
    profile: [
      [-16, 43.5], [16, 43.5], [16, 45.5], [-16, 45.5],
    ],
  });
  const linerInner = revolvePart({
    slug: 'combustor-liner-inner',
    name: 'Combustor inner liner',
    materialSlug: 'combustor',
    role: 'combustor-liner',
    description: 'Inner annular combustor liner shell.',
    profile: [
      [-16, 28], [16, 28], [16, 30], [-16, 30],
    ],
  });
  const injector = revolvePart({
    slug: 'fuel-injector',
    name: 'Fuel injector',
    materialSlug: 'combustor',
    role: 'injector',
    description: 'Fuel injector nozzle revolved about its own feed axis.',
    profile: [
      [-4, 1.5], [-4, 5], [0, 5], [4, 2.5], [4, 1.5],
    ],
  });

  // ---- Turbine parts ----------------------------------------------------
  const turbCase = revolvePart({
    slug: 'turbine-case',
    name: 'Turbine case',
    materialSlug: 'nickel',
    role: 'case',
    description: 'Diverging turbine case with wall thickness and flanges.',
    profile: caseProfile(24, 42, -24, 54.5, 2.5),
  });
  const hptDisk = revolvePart({
    slug: 'hpt-disk',
    name: 'High-pressure turbine disk',
    materialSlug: 'nickel',
    role: 'rotor-disk',
    description: 'High-pressure turbine disk bored for the spool drum.',
    profile: diskProfile(4, 12, 23.5, 27, 1.8),
  });
  const lptDisk = revolvePart({
    slug: 'lpt-disk',
    name: 'Low-pressure turbine disk',
    materialSlug: 'nickel',
    role: 'rotor-disk',
    description: 'Low-pressure turbine disk bored for the LP shaft.',
    profile: diskProfile(4, 6, 23.5, 27, 1.8),
  });
  const turbineRotorStations = [-27, -44, -60];
  const turbineRotorTips = turbineRotorStations.map((x) => round3(turbCaseInnerAt(x) - TIP_CLEARANCE));
  const turbineRotorChords = [9, 9.5, 10];
  const turbRotorBlades = turbineRotorStations.map((_, index) => bladePart({
    slug: `turbine-rotor-blade-${index + 1}`,
    name: `Turbine rotor blade stage ${index + 1}`,
    materialSlug: 'nickel',
    role: 'turbine-blade-seed',
    description: `Stage ${index + 1} turbine rotor blade with high-camber reaction sections.`,
    sections: [
      { z: 25.5, chord: turbineRotorChords[index], staggerDeg: -38, camber: -0.16, thickness: 0.2 },
      { z: turbineRotorTips[index], chord: turbineRotorChords[index] - 1, staggerDeg: -28, camber: -0.13, thickness: 0.12 },
    ],
  }));
  const turbineVaneStations = [-18, -36, -52];
  const turbineVaneOuter = turbineVaneStations.map((x) => round3(turbCaseInnerAt(x) + CASE_EMBED));
  const turbineVaneChords = [11, 12, 13];
  const turbNozzleVanes = turbineVaneStations.map((_, index) => bladePart({
    slug: `turbine-nozzle-vane-${index + 1}`,
    name: `Turbine nozzle vane row ${index + 1}`,
    materialSlug: 'nickel',
    role: 'turbine-vane-seed',
    description: `Row ${index + 1} turbine nozzle vane with opposing camber to its rotor.`,
    sections: [
      { z: 27.5, chord: turbineVaneChords[index], staggerDeg: 38, camber: 0.16, thickness: 0.2 },
      { z: turbineVaneOuter[index], chord: turbineVaneChords[index] - 1, staggerDeg: 28, camber: 0.13, thickness: 0.13 },
    ],
  }));
  const vaneRing = revolvePart({
    slug: 'nozzle-vane-ring',
    name: 'Nozzle vane inner ring',
    materialSlug: 'nickel',
    role: 'shroud',
    description: 'Inner sealing ring closing each turbine nozzle vane row.',
    profile: [
      [-2.5, 26.5], [2.5, 26.5], [2.5, 28.4], [-2.5, 28.4],
    ],
  });

  // ---- Exhaust parts ----------------------------------------------------
  const exhCase = revolvePart({
    slug: 'exhaust-case',
    name: 'Exhaust case',
    materialSlug: 'nickel',
    role: 'case',
    description: 'Converging exhaust case with wall thickness and flanges.',
    profile: caseProfile(22, 54.5, -22, 40, 2.5),
  });
  const tailCone = revolvePart({
    slug: 'tail-cone',
    name: 'Exhaust tail cone',
    materialSlug: 'nickel',
    role: 'tail-cone',
    description: 'Exhaust tail cone plug revolved with a vent bore.',
    profile: [
      [-32, 3], [32, 3], [32, 26], [20, 24], [0, 17], [-20, 8],
    ],
  });
  const nozzleRing = revolvePart({
    slug: 'exhaust-nozzle',
    name: 'Exhaust nozzle ring',
    materialSlug: 'nickel',
    role: 'nozzle',
    description: 'Converging exhaust nozzle ring with an attachment flange.',
    profile: [
      [8, 40], [-8, 34], [-8, 36.5], [4, 41], [4, 44], [8, 44],
    ],
  });
  const exhStrut = bladePart({
    slug: 'exhaust-strut',
    name: 'Exhaust frame strut',
    materialSlug: 'nickel',
    role: 'strut-seed',
    description: 'Symmetric airfoil strut tying the tail cone to the exhaust case.',
    sections: [
      { z: round3(Math.min(tailConeRadiusAt(-80.5), tailConeRadiusAt(-67.5)) - CASE_EMBED), chord: 13, staggerDeg: 0, camber: 0, thickness: 0.21 },
      { z: round3(exhCaseInnerAt(-74) + CASE_EMBED), chord: 13, staggerDeg: 0, camber: 0, thickness: 0.21 },
    ],
  });

  // ---- Fan case parts ---------------------------------------------------
  const fanCase = revolvePart({
    slug: 'fan-case',
    name: 'Fan case',
    materialSlug: 'aluminum',
    role: 'case',
    description: 'Fan case with rolled inlet lip, wall thickness, and rear flange.',
    profile: [
      [-32, 88], [28, 88], [30.8, 88.4], [32, 89.9], [30.8, 91.4], [28, 91.8],
      [-26, 91.8], [-26, 95.2], [-32, 95.2],
    ],
  });
  const ogv = bladePart({
    slug: 'outlet-guide-vane',
    name: 'Fan outlet guide vane',
    materialSlug: 'aluminum',
    role: 'ogv-seed',
    description: 'Bypass outlet guide vane straightening the fan stream.',
    sections: [
      { z: 33.5, chord: 13, staggerDeg: -12, camber: -0.06, thickness: 0.15 },
      { z: 89, chord: 12, staggerDeg: -18, camber: -0.05, thickness: 0.11 },
    ],
  });
  const splitter = revolvePart({
    slug: 'splitter-ring',
    name: 'Core splitter ring',
    materialSlug: 'aluminum',
    role: 'shroud',
    description: 'Bypass splitter ring carrying the outlet guide vane roots.',
    profile: [
      [-4, 30], [4, 30], [4, 34], [-4, 34],
    ],
  });

  // ---- Modules ----------------------------------------------------------
  const component = (occurrenceId, name, shortName, part, x, patternMembers, z = 0) => ({
    occurrenceId, name, shortName, part, x, z, ...(patternMembers ? { patternMembers } : {}),
  });

  const fanModule = moduleAssembly('assembly-jet-01-fan-spool', '01 Fan and LP Spool', [
    component('occ-jet-01-fan-disk', 'Fan disk', 'Fan disk', fanDisk, 111),
    component('occ-jet-01-spinner', 'Spinner cone', 'Spinner', spinner, 134),
    component('occ-jet-01-fan-blades', `${bladeRowPlan.fanBlades} fan blades`, 'Fan blade row', fanBlade, 111, bladeRowPlan.fanBlades),
    component('occ-jet-01-lp-shaft', 'Low-pressure shaft', 'LP shaft', lpShaft, 29),
    component('occ-jet-01-front-bearing', 'Front shaft bearing', 'Front bearing', bearing, 88),
    component('occ-jet-01-rear-bearing', 'Rear shaft bearing', 'Rear bearing', bearing, -64),
  ], { subsystemRole: 'fan-and-low-pressure-spool' });

  const compressorComponents = [
    component('occ-jet-02-comp-case', 'Compressor case', 'Compressor case', compCase, 53),
    component('occ-jet-02-hp-drum', 'HP spool drum', 'HP drum', hpDrum, 25),
  ];
  compressorRotorStations.forEach((station, index) => {
    compressorComponents.push(
      component(`occ-jet-02-rotor-disk-${index + 1}`, `Rotor disk stage ${index + 1}`, `Rotor disk ${index + 1}`, compDisk, station),
      component(
        `occ-jet-02-rotor-blades-${index + 1}`,
        `${bladeRowPlan.compressorRotors[index]} rotor blades stage ${index + 1}`,
        `Rotor row ${index + 1}`,
        compRotorBlades[index],
        station,
        bladeRowPlan.compressorRotors[index],
      ),
    );
  });
  compressorStatorStations.forEach((station, index) => {
    compressorComponents.push(
      component(
        `occ-jet-02-stator-vanes-${index + 1}`,
        `${bladeRowPlan.compressorStators[index]} stator vanes stage ${index + 1}`,
        `Stator row ${index + 1}`,
        compStatorVanes[index],
        station,
        bladeRowPlan.compressorStators[index],
      ),
      component(`occ-jet-02-stator-shroud-${index + 1}`, `Stator shroud stage ${index + 1}`, `Stator shroud ${index + 1}`, statorShroud, station),
    );
  });
  const compressorModule = moduleAssembly('assembly-jet-02-axial-compressor', '02 Axial Compressor', compressorComponents, {
    subsystemRole: 'five-stage-axial-compressor',
    rotorStages: compressorRotorStations.length,
    statorStages: compressorStatorStations.length,
  });

  const injectorComponent = {
    ...component('occ-jet-03-injectors', `${bladeRowPlan.fuelInjectors} fuel injectors`, 'Injector ring', injector, 19, bladeRowPlan.fuelInjectors, 37),
    mates: 'planar',
    buildMates(scope, anchor, self) {
      // The injector sits off the engine axis, so it is placed by three
      // coincident plane mates against injector-station datums on the dome.
      const domeOccurrenceId = 'occ-jet-03-dome';
      const domePartId = combDome.id;
      const base = `${scope}:mate:${self.occurrenceId}`;
      const coincident = (suffix, name, domeSuffix, injectorSuffix) => ({
        id: `${base}:${suffix}`,
        name,
        kind: 'coincident',
        occurrenceIds: [domeOccurrenceId, self.occurrenceId],
        references: [
          datumReference([domeOccurrenceId], domePartId, domeSuffix, `dome-${suffix}`, 'plane'),
          datumReference([self.occurrenceId], self.part.id, injectorSuffix, `injector-${suffix}`, 'plane'),
        ],
        suppressed: false,
      });
      return [
        coincident('station', 'Injector axial station', 'injector-yz', 'station-yz'),
        coincident('orbit', 'Injector orbit radius', 'injector-xy', 'clock-xy'),
        coincident('tangency', 'Injector tangential alignment', 'injector-zx', 'clock-zx'),
      ];
    },
  };
  // The injector seed is mated to the dome, so the dome must solve first in
  // the same module; declaration order keeps the intent readable.
  const combustorModule = moduleAssembly('assembly-jet-03-annular-combustor', '03 Annular Combustor', [
    component('occ-jet-03-comb-case', 'Combustor outer case', 'Combustor case', combCase, 2),
    component('occ-jet-03-dome', 'Combustor dome ring', 'Dome', combDome, 16.5),
    component('occ-jet-03-outer-liner', 'Outer combustor liner', 'Outer liner', linerOuter, 0),
    component('occ-jet-03-inner-liner', 'Inner combustor liner', 'Inner liner', linerInner, 0),
    injectorComponent,
  ], { subsystemRole: 'annular-combustor', injectorCount: bladeRowPlan.fuelInjectors });

  const turbineComponents = [
    component('occ-jet-04-turb-case', 'Turbine case', 'Turbine case', turbCase, -40),
  ];
  turbineVaneStations.forEach((station, index) => {
    turbineComponents.push(
      component(
        `occ-jet-04-nozzle-vanes-${index + 1}`,
        `${bladeRowPlan.turbineNozzleVanes[index]} nozzle vanes row ${index + 1}`,
        `Nozzle row ${index + 1}`,
        turbNozzleVanes[index],
        station,
        bladeRowPlan.turbineNozzleVanes[index],
      ),
      component(`occ-jet-04-vane-ring-${index + 1}`, `Nozzle inner ring ${index + 1}`, `Vane ring ${index + 1}`, vaneRing, station),
    );
  });
  turbineRotorStations.forEach((station, index) => {
    turbineComponents.push(
      component(
        `occ-jet-04-turbine-disk-${index + 1}`,
        `Turbine disk stage ${index + 1}`,
        `Turbine disk ${index + 1}`,
        index === 0 ? hptDisk : lptDisk,
        station,
      ),
      component(
        `occ-jet-04-turbine-blades-${index + 1}`,
        `${bladeRowPlan.turbineRotors[index]} turbine blades stage ${index + 1}`,
        `Turbine row ${index + 1}`,
        turbRotorBlades[index],
        station,
        bladeRowPlan.turbineRotors[index],
      ),
    );
  });
  const turbineModule = moduleAssembly('assembly-jet-04-turbine', '04 Turbine', turbineComponents, {
    subsystemRole: 'three-stage-turbine',
    turbineStages: turbineRotorStations.length,
  });

  const exhaustModule = moduleAssembly('assembly-jet-05-exhaust', '05 Exhaust', [
    component('occ-jet-05-exh-case', 'Exhaust case', 'Exhaust case', exhCase, -86),
    component('occ-jet-05-tail-cone', 'Exhaust tail cone', 'Tail cone', tailCone, -98),
    component('occ-jet-05-nozzle', 'Exhaust nozzle ring', 'Nozzle', nozzleRing, -116),
    component('occ-jet-05-struts', `${bladeRowPlan.exhaustStruts} exhaust struts`, 'Strut ring', exhStrut, -74, bladeRowPlan.exhaustStruts),
  ], { subsystemRole: 'exhaust-and-rear-frame' });

  const fanCaseModule = moduleAssembly('assembly-jet-06-fan-case', '06 Fan Case and OGVs', [
    component('occ-jet-06-fan-case', 'Fan case', 'Fan case', fanCase, 120),
    component('occ-jet-06-ogvs', `${bladeRowPlan.outletGuideVanes} outlet guide vanes`, 'OGV row', ogv, 93, bladeRowPlan.outletGuideVanes),
    component('occ-jet-06-splitter', 'Core splitter ring', 'Splitter', splitter, 96),
  ], { subsystemRole: 'fan-case-and-bypass-vanes' });

  const subsystemAssemblies = [
    fanModule,
    compressorModule,
    combustorModule,
    turbineModule,
    exhaustModule,
    fanCaseModule,
  ];

  // ---- Root assembly ----------------------------------------------------
  const rootOccurrences = [
    rootOccurrence(1, 'fan-spool', 'Fan and LP Spool', fanModule.id, ELEVATION_Z),
    rootOccurrence(2, 'axial-compressor', 'Axial Compressor', compressorModule.id, ELEVATION_Z),
    rootOccurrence(3, 'annular-combustor', 'Annular Combustor', combustorModule.id, ELEVATION_Z),
    rootOccurrence(4, 'turbine', 'Turbine', turbineModule.id, ELEVATION_Z),
    rootOccurrence(5, 'exhaust', 'Exhaust', exhaustModule.id, ELEVATION_Z),
    rootOccurrence(6, 'fan-case', 'Fan Case and OGVs', fanCaseModule.id, ELEVATION_Z),
  ];

  // Root mates reference each module's anchor component through its
  // subassembly path. The compressor module grounds the engine.
  const moduleAnchors = [
    { root: rootOccurrences[0], anchorOccurrenceId: 'occ-jet-01-fan-disk', partId: fanDisk.id, station: 111, shortName: 'Fan module' },
    { root: rootOccurrences[1], anchorOccurrenceId: 'occ-jet-02-comp-case', partId: compCase.id, station: 53, shortName: 'Compressor module' },
    { root: rootOccurrences[2], anchorOccurrenceId: 'occ-jet-03-comb-case', partId: combCase.id, station: 2, shortName: 'Combustor module' },
    { root: rootOccurrences[3], anchorOccurrenceId: 'occ-jet-04-turb-case', partId: turbCase.id, station: -40, shortName: 'Turbine module' },
    { root: rootOccurrences[4], anchorOccurrenceId: 'occ-jet-05-exh-case', partId: exhCase.id, station: -86, shortName: 'Exhaust module' },
    { root: rootOccurrences[5], anchorOccurrenceId: 'occ-jet-06-fan-case', partId: fanCase.id, station: 120, shortName: 'Fan case module' },
  ];
  const groundAnchor = moduleAnchors[1];
  const rootMates = [groundMate('assembly-jet-engine-root', groundAnchor.root.id, 'Compressor module grounded anchor')];
  for (const anchor of moduleAnchors) {
    if (anchor === groundAnchor) continue;
    const base = `assembly-jet-engine-root:mate:${anchor.root.id}`;
    rootMates.push(
      {
        id: `${base}:concentric`,
        name: `${anchor.shortName} concentric to core axis`,
        kind: 'concentric',
        occurrenceIds: [groundAnchor.root.id, anchor.root.id],
        references: [
          datumReference([groundAnchor.root.id, groundAnchor.anchorOccurrenceId], groundAnchor.partId, 'axis', 'core-axis', 'axis'),
          datumReference([anchor.root.id, anchor.anchorOccurrenceId], anchor.partId, 'axis', 'module-axis', 'axis'),
        ],
        suppressed: false,
      },
      {
        id: `${base}:distance`,
        name: `${anchor.shortName} axial station`,
        kind: 'distance',
        occurrenceIds: [groundAnchor.root.id, anchor.root.id],
        references: [
          datumReference([groundAnchor.root.id, groundAnchor.anchorOccurrenceId], groundAnchor.partId, 'station-yz', 'core-station', 'plane'),
          datumReference([anchor.root.id, anchor.anchorOccurrenceId], anchor.partId, 'station-yz', 'module-station', 'plane'),
        ],
        value: round3(anchor.station - groundAnchor.station),
        suppressed: false,
      },
      {
        id: `${base}:clocking`,
        name: `${anchor.shortName} clocking angle`,
        kind: 'angle',
        occurrenceIds: [groundAnchor.root.id, anchor.root.id],
        references: [
          datumReference([groundAnchor.root.id, groundAnchor.anchorOccurrenceId], groundAnchor.partId, 'clock-xy', 'core-clock', 'plane'),
          datumReference([anchor.root.id, anchor.anchorOccurrenceId], anchor.partId, 'clock-zx', 'module-clock', 'plane'),
        ],
        value: 90,
        suppressed: false,
      },
    );
  }

  const explodedViewId = 'exploded-jet-engine-service-layout';
  const sectionViewId = 'section-jet-engine-longitudinal';

  const explicitLeafOccurrenceCount = subsystemAssemblies
    .reduce((total, assembly) => total + assembly.occurrences.length, 0);
  const expectedGeneratedBodyPatternMembers = subsystemAssemblies
    .reduce((total, assembly) => total + assembly.occurrencePatterns
      .reduce((patternTotal, pattern) => patternTotal + pattern.generatedCount, 0), 0);
  const expectedExactBodyCount = explicitLeafOccurrenceCount + expectedGeneratedBodyPatternMembers;
  const authoredMateCount = subsystemAssemblies
    .reduce((total, assembly) => total + assembly.mates.length, 0) + rootMates.length;

  const rootAssembly = {
    id: 'assembly-jet-engine-root',
    name: 'Turbofan demonstrator assembly',
    parameters: [],
    occurrences: rootOccurrences,
    mates: rootMates,
    occurrencePatterns: [],
    explodedViews: [{
      id: explodedViewId,
      name: 'Service exploded layout',
      steps: [
        { occurrenceIds: [rootOccurrences[5].id], deltaTransform: translationMatrix(140, 0, 0) },
        { occurrenceIds: [rootOccurrences[0].id], deltaTransform: translationMatrix(58, 0, 0) },
        { occurrenceIds: [rootOccurrences[1].id], deltaTransform: translationMatrix(20, 0, 0) },
        { occurrenceIds: [rootOccurrences[2].id], deltaTransform: translationMatrix(-16, 0, 0) },
        { occurrenceIds: [rootOccurrences[3].id], deltaTransform: translationMatrix(-52, 0, 0) },
        { occurrenceIds: [rootOccurrences[4].id], deltaTransform: translationMatrix(-92, 0, 0) },
      ],
      extensions: { studioDisplayOnly: true, purpose: 'axial-service-separation' },
    }],
    sectionViews: [{
      id: sectionViewId,
      name: 'Longitudinal core section',
      kind: 'plane',
      definition: {
        planes: [{ normal: [0, 1, 0], offset: 0 }],
        cap: true,
        reverse: false,
        scopeOccurrenceIds: [],
        hatch: { enabled: true, spacing: 8, angle: 45, color: '#243746', fillColor: '#d7e0e5' },
      },
      extensions: { studioDisplayOnly: true },
    }],
    metadata: {
      activeExplodedViewId: explodedViewId,
      displayMode: 'shaded-edges',
      expectedExactBodyCount,
      enumeratedSubsystemCount: rootOccurrences.length,
      solverPolicy: 'authored-mates',
    },
    extensions: { jetEngineRootAssembly: true },
  };

  return {
    schemaVersion: 5,
    projectId: options.projectId || 'project-jet-engine-exploded-assembly',
    name: options.name || 'Turbofan demonstrator assembly',
    units: 'mm',
    parameters: [],
    materials: MATERIALS.map((entry) => structuredClone(entry)),
    partDefinitions: [
      spinner, fanDisk, fanBlade, lpShaft, bearing,
      compCase, hpDrum, compDisk, ...compRotorBlades, ...compStatorVanes, statorShroud,
      combCase, combDome, linerOuter, linerInner, injector,
      turbCase, hptDisk, lptDisk, ...turbRotorBlades, ...turbNozzleVanes, vaneRing,
      exhCase, tailCone, nozzleRing, exhStrut,
      fanCase, ogv, splitter,
    ],
    assemblyDefinitions: [...subsystemAssemblies, rootAssembly],
    rootDocument: { kind: 'assembly', assemblyId: rootAssembly.id },
    resources: [],
    extensions: {
      drawingBook: shippedDrawingBook(),
    },
    metadata: {
      templateId: 'jet-engine-exploded-assembly',
      templateCategory: 'Mechanical',
      partmodeDemo: { kind: 'jet-engine-assembly', flightRecorder: true, autoFit: true },
      expectedExactBodyCount,
      expectedExplicitOccurrenceCount: explicitLeafOccurrenceCount + rootOccurrences.length,
      expectedGeneratedBodyPatternMembers,
      expectedGeneratedOccurrencePatternMembers: expectedGeneratedBodyPatternMembers,
      authoredMateCount,
      bladeRowPlan: structuredClone(bladeRowPlan),
      modelPolicy: 'exact-feature-demonstrator-with-authored-mates',
      certificationStatus: 'not-certified',
      limitations: [
        'Geometry is a conceptual turbofan layout and does not represent a named production engine.',
        'Airfoil sections are plausible demonstrator profiles, not aerodynamic designs.',
        'Clearances, loads, thermal behavior, fasteners, seals, and manufacturing details are not engineered.',
        'Material records are conceptual assignments; production grades and allowables are not selected.',
        'The active exploded view is display-only and does not alter mate-solved placements.',
      ],
    },
  };
}

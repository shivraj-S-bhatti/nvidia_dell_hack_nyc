import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { createOpenBotRoverProject } from './source/studio-openbot-rover.js';

const directory = path.dirname(fileURLToPath(import.meta.url));
const mongoDirectory = path.join(directory, 'mongo');
const requestDirectory = path.join(directory, 'requests');
await Promise.all([mkdir(mongoDirectory, { recursive: true }), mkdir(requestDirectory, { recursive: true })]);

const baseline = createOpenBotRoverProject({ wheelDiameterMm: 65 });
const upgraded = createOpenBotRoverProject({ wheelDiameterMm: 82 });
const baselineFile = 'openbot-blocky-rover-65mm.bomcad.json';
const upgradedFile = 'openbot-blocky-rover-82mm.bomcad.json';
const baselineText = `${JSON.stringify(baseline, null, 2)}\n`;
const upgradedText = `${JSON.stringify(upgraded, null, 2)}\n`;
const corpusRevision = `sha256:${createHash('sha256').update(baselineText).digest('hex')}`;

const nodes = [];
const edges = [];

function addNode(nodeId, type, tier, attributes) {
  nodes.push({ nodeId, type, tier, sourceFile: baselineFile, corpusRevision, attributes });
}

function addEdge(edgeId, type, fromNodeId, toNodeId, tier, attributes = {}) {
  edges.push({ edgeId, type, fromNodeId, toNodeId, tier, sourceFile: baselineFile, corpusRevision, attributes });
}

const projectNodeId = `project:${baseline.projectId}`;
addNode(projectNodeId, 'Project', 'authored', {
  name: baseline.name,
  schemaVersion: baseline.schemaVersion,
  units: baseline.units,
  modelPolicy: baseline.metadata.modelPolicy,
});

for (const parameter of baseline.parameters) {
  const nodeId = `parameter:${parameter.id}`;
  addNode(nodeId, 'Parameter', 'authored', parameter);
  addEdge(`defines:${baseline.projectId}:${parameter.id}`, 'DEFINES', projectNodeId, nodeId, 'authored');
}

for (const part of baseline.partDefinitions) {
  const nodeId = `part:${part.id}`;
  addNode(nodeId, 'PartDefinition', 'geometry', {
    name: part.name,
    role: part.extensions.roverRole,
    catalogOnly: part.extensions.agentCatalogOnly,
    parameters: part.parameters,
    metadata: part.metadata,
  });
  addEdge(`defines:${baseline.projectId}:${part.id}`, 'DEFINES', projectNodeId, nodeId, 'authored');
}

const rootAssembly = baseline.assemblyDefinitions[0];
const assemblyNodeId = `assembly:${rootAssembly.id}`;
addNode(assemblyNodeId, 'AssemblyDefinition', 'authored', {
  name: rootAssembly.name,
  placementPolicy: rootAssembly.metadata.placementPolicy,
});
addEdge(`defines:${baseline.projectId}:${rootAssembly.id}`, 'DEFINES', projectNodeId, assemblyNodeId, 'authored');

for (const occurrence of rootAssembly.occurrences) {
  const occurrenceNodeId = `occurrence:${occurrence.id}`;
  addNode(occurrenceNodeId, 'PartOccurrence', 'authored', {
    name: occurrence.name,
    definition: occurrence.definition,
    baseTransform: occurrence.baseTransform,
    extensions: occurrence.extensions,
  });
  addEdge(`contains:${rootAssembly.id}:${occurrence.id}`, 'CONTAINS', assemblyNodeId, occurrenceNodeId, 'authored');
  addEdge(`instance:${occurrence.id}`, 'INSTANCE_OF', occurrenceNodeId, `part:${occurrence.definition.partId}`, 'authored');
}

const ruleNodes = [
  {
    id: 'rule:wheel-ground-tangency',
    name: 'Wheel ground tangency',
    expression: 'axle_height_mm = wheel_diameter_mm / 2',
    reason: 'Changing wheel diameter moves every axle centerline so the wheel bottoms remain on the same ground plane.',
  },
  {
    id: 'rule:wheel-body-clearance',
    name: 'Wheel-to-body clearance',
    expression: 'wheel_well_radius = wheel_diameter_mm / 2 + body_clearance_mm',
    reason: 'Both side-guard cutouts retain the authored 8 mm radial clearance.',
  },
  {
    id: 'rule:left-right-symmetry',
    name: 'Left-right symmetry',
    expression: 'paired occurrence transforms mirror across Y=0',
    reason: 'Wheel and motor-mount updates must remain symmetric.',
  },
];

for (const rule of ruleNodes) addNode(rule.id, 'Rule', 'team-authored', rule);

const wheelParameterNode = 'parameter:parameter-rover-wheel-diameter';
const clearanceParameterNode = 'parameter:parameter-rover-body-clearance';
addEdge('dependency:wheel-geometry', 'DRIVES_GEOMETRY', wheelParameterNode, 'part:part-rover-wheel', 'team-authored');
addEdge('dependency:wheel-wells', 'DRIVES_GEOMETRY', wheelParameterNode, 'part:part-rover-wheel-guard', 'team-authored');
addEdge('dependency:clearance-wheel-wells', 'DRIVES_GEOMETRY', clearanceParameterNode, 'part:part-rover-wheel-guard', 'team-authored');
addEdge('dependency:wheel-ground-rule', 'DRIVES_RULE', wheelParameterNode, 'rule:wheel-ground-tangency', 'team-authored');
addEdge('dependency:wheel-clearance-rule', 'DRIVES_RULE', wheelParameterNode, 'rule:wheel-body-clearance', 'team-authored');

const wheelOccurrenceIds = [
  'occ-rover-wheel-fore-left', 'occ-rover-wheel-fore-right',
  'occ-rover-wheel-aft-left', 'occ-rover-wheel-aft-right',
];
const motorOccurrenceIds = ['occ-rover-motor-left', 'occ-rover-motor-right'];
for (const occurrenceId of [...wheelOccurrenceIds, ...motorOccurrenceIds]) {
  addEdge(
    `dependency:ground-rule:${occurrenceId}`,
    'DRIVES_TRANSFORM',
    'rule:wheel-ground-tangency',
    `occurrence:${occurrenceId}`,
    'team-authored',
  );
}

for (const [left, right, role] of [
  ['occ-rover-wheel-fore-left', 'occ-rover-wheel-fore-right', 'front wheels'],
  ['occ-rover-wheel-aft-left', 'occ-rover-wheel-aft-right', 'rear wheels'],
  ['occ-rover-motor-left', 'occ-rover-motor-right', 'motor mounts'],
  ['occ-rover-wheel-guard-left', 'occ-rover-wheel-guard-right', 'wheel guards'],
  ['occ-rover-eye-left', 'occ-rover-eye-right', 'sensor eyes'],
]) {
  addEdge(`symmetry:${left}:${right}`, 'SYMMETRIC_WITH', `occurrence:${left}`, `occurrence:${right}`, 'team-authored', { role });
  addEdge(`symmetry-rule:${left}`, 'REQUIRES', 'rule:left-right-symmetry', `occurrence:${left}`, 'team-authored', { pair: right });
  addEdge(`symmetry-rule:${right}`, 'REQUIRES', 'rule:left-right-symmetry', `occurrence:${right}`, 'team-authored', { pair: left });
}

for (const guardId of ['occ-rover-wheel-guard-left', 'occ-rover-wheel-guard-right']) {
  addEdge(`dependency:clearance-rule:${guardId}`, 'VALIDATES', 'rule:wheel-body-clearance', `occurrence:${guardId}`, 'team-authored');
}

nodes.sort((left, right) => left.nodeId.localeCompare(right.nodeId));
edges.sort((left, right) => left.edgeId.localeCompare(right.edgeId));

const definitionCounts = new Map();
for (const occurrence of rootAssembly.occurrences) {
  const entry = definitionCounts.get(occurrence.definition.partId) ?? {
    definitionId: occurrence.definition.partId,
    name: baseline.partDefinitions.find((part) => part.id === occurrence.definition.partId)?.name ?? occurrence.name,
    quantity: 0,
    occurrenceIds: [],
  };
  entry.quantity += 1;
  entry.occurrenceIds.push(occurrence.id);
  definitionCounts.set(occurrence.definition.partId, entry);
}
const bom = [...definitionCounts.values()].sort((left, right) => left.definitionId.localeCompare(right.definitionId));

const upgradedOccurrenceById = new Map(
  upgraded.assemblyDefinitions[0].occurrences.map((occurrence) => [occurrence.id, occurrence]),
);
const expectedOperations = [
  {
    kind: 'parameter.update',
    input: { parameterId: 'parameter-rover-wheel-diameter', value: 82 },
  },
  ...[...wheelOccurrenceIds, ...motorOccurrenceIds].map((occurrenceId) => ({
    kind: 'component.update',
    input: {
      occurrenceId,
      patch: { baseTransform: upgradedOccurrenceById.get(occurrenceId).baseTransform },
    },
  })),
];

const request = {
  schemaVersion: 1,
  assemblyId: rootAssembly.id,
  operation: 'resize_wheels',
  wheelDiameterMm: 82,
  constraints: {
    bodyClearanceMm: 8,
    groundClearanceMm: 12,
    preserveLeftRightSymmetry: true,
  },
};

const expectedPatch = {
  schemaVersion: 1,
  sourceProject: baselineFile,
  resultProject: upgradedFile,
  request,
  operations: expectedOperations,
  acceptance: {
    wheelOccurrencesUpdated: 4,
    motorMountOccurrencesUpdated: 2,
    wheelWellDefinitionsUpdatedThroughSharedParameter: 1,
    minimumBodyClearanceMm: 8,
    groundPlaneZMm: 0,
    symmetric: true,
  },
};

const catalog = {
  schemaVersion: 1,
  policy: {
    maximumInsertionsPerRequest: 2,
    allowedOperations: ['component.insert', 'component.update', 'component.delete'],
    requireCollisionCheck: true,
    requireHumanApproval: true,
    note: 'Bounded reusable primitives only; no arbitrary mesh generation in the judged path.',
  },
  parts: [
    { partId: 'part-rover-catalog-perforated-beam', name: 'Perforated beam', use: 'Bridge mounts or extend the bumper.' },
    { partId: 'part-rover-catalog-angle-bracket', name: 'Right-angle bracket', use: 'Attach a deck, camera plate, or sensor.' },
    { partId: 'part-rover-catalog-axle-spacer', name: 'Axle spacer', use: 'Preserve lateral wheel clearance.' },
    { partId: 'part-rover-sensor-eye', name: 'Sensor eye pod', use: 'Add a second bounded sensor arrangement.' },
  ],
};

const graph = {
  schemaVersion: 1,
  corpusRevision,
  source: { file: baselineFile, modelPolicy: baseline.metadata.modelPolicy },
  counts: { nodes: nodes.length, edges: edges.length, partDefinitions: baseline.partDefinitions.length, occurrences: rootAssembly.occurrences.length },
  nodes,
  edges,
};

const manifest = {
  corpusRevision,
  rootDocument: baseline.rootDocument,
  counts: graph.counts,
  files: {
    baseline: baselineFile,
    upgraded: upgradedFile,
    bom: 'openbot-blocky-rover-bom.json',
    graph: 'openbot-blocky-rover-graph.json',
    nodes: 'mongo/nodes.ndjson',
    edges: 'mongo/edges.ndjson',
    request: 'requests/upgrade-wheels-82mm.json',
    expectedPatch: 'requests/upgrade-wheels-82mm.expected.json',
    agentPartsCatalog: 'agent-parts-catalog.json',
  },
};

const writeJson = (relativePath, value) => writeFile(path.join(directory, relativePath), `${JSON.stringify(value, null, 2)}\n`);
const writeNdjson = (relativePath, records) => writeFile(path.join(directory, relativePath), `${records.map((record) => JSON.stringify(record)).join('\n')}\n`);

await Promise.all([
  writeFile(path.join(directory, baselineFile), baselineText),
  writeFile(path.join(directory, upgradedFile), upgradedText),
  writeJson('openbot-blocky-rover-manifest.json', manifest),
  writeJson('openbot-blocky-rover-bom.json', { corpusRevision, rows: bom }),
  writeJson('openbot-blocky-rover-graph.json', graph),
  writeJson('agent-parts-catalog.json', catalog),
  writeJson('requests/upgrade-wheels-82mm.json', request),
  writeJson('requests/upgrade-wheels-82mm.expected.json', expectedPatch),
  writeNdjson('mongo/nodes.ndjson', nodes),
  writeNdjson('mongo/edges.ndjson', edges),
]);

console.log(JSON.stringify(manifest, null, 2));

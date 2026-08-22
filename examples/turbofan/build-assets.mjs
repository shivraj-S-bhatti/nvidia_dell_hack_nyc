import { createHash } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { createJetEngineAssemblyProject } from './source/studio-jet-engine.js';

const directory = path.dirname(fileURLToPath(import.meta.url));
const sourceFile = 'partmode-turbofan.bomcad.json';
const sourceCommit = 'fe88558a34c8d7a3e03b34c2a374ba5ce6febe9f';
const project = createJetEngineAssemblyProject();
const projectText = `${JSON.stringify(project, null, 2)}\n`;
const corpusRevision = `sha256:${createHash('sha256').update(projectText).digest('hex')}`;

const nodes = [];
const edges = [];

function addNode(nodeId, type, tier, attributes) {
  nodes.push({
    nodeId,
    type,
    tier,
    sourceFile,
    corpusRevision,
    attributes,
  });
}

function addEdge(edgeId, type, fromNodeId, toNodeId, tier, attributes = {}) {
  edges.push({
    edgeId,
    type,
    fromNodeId,
    toNodeId,
    tier,
    sourceFile,
    corpusRevision,
    attributes,
  });
}

const projectNodeId = `project:${project.projectId}`;
addNode(projectNodeId, 'Project', 'authored', {
  name: project.name,
  schemaVersion: project.schemaVersion,
  units: project.units,
  rootDocument: project.rootDocument,
});

for (const material of project.materials) {
  const nodeId = `material:${material.id}`;
  addNode(nodeId, 'Material', 'assumption', material);
  addEdge(`defines:${project.projectId}:${material.id}`, 'DEFINES', projectNodeId, nodeId, 'authored');
}

for (const part of project.partDefinitions) {
  const nodeId = `part:${part.id}`;
  addNode(nodeId, 'PartDefinition', 'geometry', {
    name: part.name,
    metadata: part.metadata,
    extensions: part.extensions,
    bodyCount: part.bodies.length,
    featureCount: part.features.length,
    featureTypes: [...new Set(part.features.map((feature) => feature.type))].sort(),
    materialIds: [...new Set(part.bodies.map((body) => body.materialId).filter(Boolean))].sort(),
  });
  addEdge(`defines:${project.projectId}:${part.id}`, 'DEFINES', projectNodeId, nodeId, 'authored');

  for (const materialId of [...new Set(part.bodies.map((body) => body.materialId).filter(Boolean))]) {
    addEdge(
      `material:${part.id}:${materialId}`,
      'USES_MATERIAL',
      nodeId,
      `material:${materialId}`,
      'assumption',
    );
  }
}

const bom = [];
let directOccurrenceCount = 0;
let generatedPatternMemberCount = 0;
let mateCount = 0;

for (const assembly of project.assemblyDefinitions) {
  const assemblyNodeId = `assembly:${assembly.id}`;
  addNode(assemblyNodeId, 'AssemblyDefinition', 'authored', {
    name: assembly.name,
    metadata: assembly.metadata,
    extensions: assembly.extensions,
  });
  addEdge(`defines:${project.projectId}:${assembly.id}`, 'DEFINES', projectNodeId, assemblyNodeId, 'authored');

  const patternBySource = new Map();
  for (const pattern of assembly.occurrencePatterns ?? []) {
    const patternNodeId = `pattern:${assembly.id}/${pattern.id}`;
    addNode(patternNodeId, 'OccurrencePattern', 'authored', {
      name: pattern.name,
      kind: pattern.kind,
      generatedCount: pattern.generatedCount,
      definition: pattern.definition,
      extensions: pattern.extensions,
    });
    addEdge(`contains:${assembly.id}:${pattern.id}`, 'CONTAINS', assemblyNodeId, patternNodeId, 'authored');
    generatedPatternMemberCount += pattern.generatedCount ?? 0;

    for (const occurrenceId of pattern.sourceOccurrenceIds ?? []) {
      patternBySource.set(occurrenceId, pattern);
      addEdge(
        `pattern-source:${assembly.id}:${pattern.id}:${occurrenceId}`,
        'PATTERNS_FROM',
        patternNodeId,
        `occurrence:${assembly.id}/${occurrenceId}`,
        'authored',
      );
    }
  }

  for (const occurrence of assembly.occurrences) {
    directOccurrenceCount += 1;
    const occurrenceNodeId = `occurrence:${assembly.id}/${occurrence.id}`;
    const definitionId = occurrence.definition.kind === 'part'
      ? occurrence.definition.partId
      : occurrence.definition.assemblyId;
    const definitionNodeId = `${occurrence.definition.kind}:${definitionId}`;
    const pattern = patternBySource.get(occurrence.id);
    const quantity = pattern ? (pattern.generatedCount ?? 0) + 1 : 1;

    addNode(occurrenceNodeId, 'PartOccurrence', 'authored', {
      name: occurrence.name,
      parentAssemblyId: assembly.id,
      definition: occurrence.definition,
      baseTransform: occurrence.baseTransform,
      fixed: occurrence.fixed,
      suppressed: occurrence.suppressed,
      visible: occurrence.visible,
      extensions: occurrence.extensions,
      quantityIncludingPattern: quantity,
    });
    addEdge(`contains:${assembly.id}:${occurrence.id}`, 'CONTAINS', assemblyNodeId, occurrenceNodeId, 'authored');
    addEdge(
      `instance:${assembly.id}:${occurrence.id}`,
      'INSTANCE_OF',
      occurrenceNodeId,
      definitionNodeId,
      'authored',
    );

    bom.push({
      assemblyId: assembly.id,
      assemblyName: assembly.name,
      occurrenceId: occurrence.id,
      occurrenceName: occurrence.name,
      definitionKind: occurrence.definition.kind,
      definitionId,
      quantity,
      patterned: Boolean(pattern),
    });
  }

  for (const mate of assembly.mates ?? []) {
    mateCount += 1;
    const mateNodeId = `mate:${assembly.id}/${mate.id}`;
    addNode(mateNodeId, 'Joint', 'authored', {
      name: mate.name,
      kind: mate.kind,
      value: mate.value ?? null,
      references: mate.references,
      suppressed: mate.suppressed,
      extensions: mate.extensions,
    });
    addEdge(`contains:${assembly.id}:${mate.id}`, 'CONTAINS', assemblyNodeId, mateNodeId, 'authored');
    for (const occurrenceId of mate.occurrenceIds ?? []) {
      addEdge(
        `mate-member:${assembly.id}:${mate.id}:${occurrenceId}`,
        'CONSTRAINS',
        mateNodeId,
        `occurrence:${assembly.id}/${occurrenceId}`,
        'authored',
      );
    }
  }

  for (const view of assembly.explodedViews ?? []) {
    const viewNodeId = `exploded-view:${assembly.id}/${view.id}`;
    addNode(viewNodeId, 'ExplodedView', 'authored', {
      name: view.name,
      steps: view.steps,
      extensions: view.extensions,
    });
    addEdge(`contains:${assembly.id}:${view.id}`, 'CONTAINS', assemblyNodeId, viewNodeId, 'authored');
  }
}

const demoDependencies = {
  status: 'team-authored-demo-hypothesis',
  warning: 'These are proposed impact relationships, not relationships recovered from the CAD model.',
  sampleChange: {
    targetNodeId: 'part:part-jet-compressor-case',
    request: 'Increase the compressor-case radial envelope by 4 mm while preserving 1 mm blade-tip clearance.',
    expectedAction: 'Retrieve affected definitions, propose coordinated edits, then require deterministic geometry and clearance checks before acceptance.',
  },
  edges: [
    ...[1, 2, 3, 4, 5].map((stage) => ({
      fromNodeId: 'part:part-jet-compressor-case',
      toNodeId: `part:part-jet-compressor-rotor-blade-${stage}`,
      type: 'CLEARANCE_IMPACTS',
      rationale: `Compressor rotor stage ${stage} tip clearance follows the case envelope.`,
    })),
    ...[1, 2, 3, 4].map((stage) => ({
      fromNodeId: 'part:part-jet-compressor-case',
      toNodeId: `part:part-jet-compressor-stator-vane-${stage}`,
      type: 'ENVELOPE_IMPACTS',
      rationale: `Compressor stator stage ${stage} outer radius follows the case envelope.`,
    })),
    {
      fromNodeId: 'part:part-jet-compressor-case',
      toNodeId: 'part:part-jet-combustor-case',
      type: 'INTERFACE_IMPACTS',
      rationale: 'The compressor exit and combustor inlet envelopes form an adjacent module interface.',
    },
    {
      fromNodeId: 'part:part-jet-combustor-dome',
      toNodeId: 'part:part-jet-fuel-injector',
      type: 'PLACEMENT_IMPACTS',
      rationale: 'Fuel injector placement is authored against injector datums on the combustor dome.',
    },
    {
      fromNodeId: 'part:part-jet-fan-case',
      toNodeId: 'part:part-jet-outlet-guide-vane',
      type: 'ENVELOPE_IMPACTS',
      rationale: 'Outlet guide vane span terminates at the fan-case envelope.',
    },
    {
      fromNodeId: 'part:part-jet-tail-cone',
      toNodeId: 'part:part-jet-exhaust-strut',
      type: 'INTERFACE_IMPACTS',
      rationale: 'Exhaust strut inner span follows the tail-cone envelope.',
    },
  ],
};

nodes.sort((left, right) => left.nodeId.localeCompare(right.nodeId));
edges.sort((left, right) => left.edgeId.localeCompare(right.edgeId));
bom.sort((left, right) => `${left.assemblyId}/${left.occurrenceId}`.localeCompare(`${right.assemblyId}/${right.occurrenceId}`));

const graph = {
  schemaVersion: 1,
  corpusRevision,
  source: {
    file: sourceFile,
    upstreamRepository: 'https://github.com/BOMWiki/partmode',
    upstreamCommit: sourceCommit,
  },
  counts: {
    nodes: nodes.length,
    edges: edges.length,
    partDefinitions: project.partDefinitions.length,
    assemblyDefinitions: project.assemblyDefinitions.length,
    directOccurrences: directOccurrenceCount,
    generatedPatternMembers: generatedPatternMemberCount,
    renderedExactBodies: project.metadata.expectedExactBodyCount,
    authoredMates: mateCount,
  },
  nodes,
  edges,
};

const manifest = {
  corpusRevision,
  sourceCommit,
  sourceFile,
  rootDocument: project.rootDocument,
  counts: graph.counts,
  files: {
    project: sourceFile,
    bom: 'turbofan-bom.json',
    graph: 'turbofan-graph.json',
    demoDependencies: 'demo-dependencies.json',
    mongoNodes: 'mongo/nodes.ndjson',
    mongoEdges: 'mongo/edges.ndjson',
  },
};

const writeJson = (relativePath, value) => writeFile(
  path.join(directory, relativePath),
  `${JSON.stringify(value, null, 2)}\n`,
);
const writeNdjson = (relativePath, records) => writeFile(
  path.join(directory, relativePath),
  `${records.map((record) => JSON.stringify(record)).join('\n')}\n`,
);

await Promise.all([
  writeFile(path.join(directory, sourceFile), projectText),
  writeJson('turbofan-manifest.json', manifest),
  writeJson('turbofan-bom.json', { corpusRevision, rows: bom }),
  writeJson('turbofan-graph.json', graph),
  writeJson('demo-dependencies.json', demoDependencies),
  writeNdjson('mongo/nodes.ndjson', nodes),
  writeNdjson('mongo/edges.ndjson', edges),
]);

console.log(JSON.stringify(manifest, null, 2));

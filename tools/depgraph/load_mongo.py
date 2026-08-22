"""load_mongo.py -- persist the derived graph into MongoDB (the system of record).

  python3 tools/depgraph/load_mongo.py .artifacts/depgraph

Traversal does NOT happen here. $graphLookup returns reachability, not paths, and
the work order is made of paths -- see docs/research/graph-store-decision.md.
MongoDB stores runs, lineage, and evidence; propagation runs in-process.

Collections
  design_runs   one document per corpus revision
  graph_nodes   occurrences and definitions
  graph_edges   derived edges, each with its reason and tolerance
  grip_stacks   measured fastener stacks
"""
import json, os, sys, datetime

def main(art='.artifacts/depgraph', uri='mongodb://127.0.0.1:27017', db='depgraph'):
    try:
        from pymongo import MongoClient, ASCENDING
    except ImportError:
        sys.exit("pymongo not installed:  pip install pymongo")
    G = json.load(open(os.path.join(art, 'graph.json')))
    d = MongoClient(uri, serverSelectionTimeoutMS=3000)[db]
    rev = G['corpusRevision']
    for c in ('graph_nodes', 'graph_edges', 'grip_stacks'):
        d[c].delete_many({'corpusRevision': rev})
    d.design_runs.replace_one({'corpusRevision': rev}, {
        'corpusRevision': rev, 'source': G['source'],
        'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'counts': {'nodes': len(G['nodes']), 'edges': len(G['edges']),
                   'definitions': len(G['defs']), 'stacks': len(G['stacks'])},
        'offlineReplayCommand': 'bash scripts/depgraph-build.sh',
    }, upsert=True)
    d.graph_nodes.insert_many([{**n, 'corpusRevision': rev} for n in G['nodes']])
    d.graph_edges.insert_many([{**e, 'corpusRevision': rev} for e in G['edges']])
    if G['stacks']:
        d.grip_stacks.insert_many([{**s, 'corpusRevision': rev} for s in G['stacks'].values()])
    d.graph_nodes.create_index([('corpusRevision', ASCENDING), ('id', ASCENDING)])
    d.graph_nodes.create_index([('corpusRevision', ASCENDING), ('def', ASCENDING)])
    d.graph_edges.create_index([('corpusRevision', ASCENDING), ('a', ASCENDING)])
    d.graph_edges.create_index([('corpusRevision', ASCENDING), ('b', ASCENDING)])
    print(f"loaded corpus {rev}: {len(G['nodes'])} nodes, {len(G['edges'])} edges, "
          f"{len(G['stacks'])} grip stacks into {db}")

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.artifacts/depgraph')

"""build_viewer.py -- assemble the self-contained offline viewer.

  python3 tools/depgraph/build_viewer.py .artifacts/depgraph s500-impact.html

Inlines three.js, the quantized geometry, and the derived graph into one HTML file.
No CDN, no network at runtime -- it must load with the ethernet unplugged.
"""
import base64, json, os, sys

from derive_edges import actions_for_thickness_change

def main(art='.artifacts/depgraph', out='s500-impact.html'):
    here = os.path.dirname(os.path.abspath(__file__))
    v = os.path.join(here, 'viewer')
    bundle = os.path.join(v, 'three-bundle.js')
    if not os.path.exists(bundle):
        sys.exit(f"missing {bundle}\n  cd tools/depgraph && npm install && npx esbuild "
                 f"viewer/three-entry.js --bundle --format=iife --global-name=THREE "
                 f"--minify --outfile=viewer/three-bundle.js")
    with open(os.path.join(art, 'graph.json'), encoding='utf-8') as fh:
        G = json.load(fh)
    with open(os.path.join(art, 'mesh.json'), encoding='utf-8') as fh:
        M = json.load(fh)

    target, delta = 'BOTTOM-PLATE-S500', 1.0
    grouped = {}
    for action in actions_for_thickness_change(G['stacks'], target, delta):
        key = action['action']
        grouped.setdefault(key, {'action': key, 'count': 0})['count'] += 1
    demo = {
        'target': target,
        'deltaMm': delta,
        'actions': list(grouped.values()),
        'claim': ('Relative length changes are derived from measured grip stacks. '
                  'Absolute fastener adequacy is not claimed.'),
    }

    with open(os.path.join(v, 'shell.html'), encoding='utf-8') as fh:
        shell = fh.read()
    with open(bundle, encoding='utf-8') as fh:
        three = fh.read()
    with open(os.path.join(v, 'app.js'), encoding='utf-8') as fh:
        app = fh.read()
    html = (shell
            + f"\n<script>{three}</script>\n<script>\n"
            + f"window.__GRAPH__={json.dumps(G, separators=(',', ':'))};\n"
            + f"window.__PARTS__={json.dumps(M, separators=(',', ':'))};\n"
            + f"window.__DEMO_CHANGE__={json.dumps(demo, separators=(',', ':'))};\n"
            + f'window.__POS__="{base64.b64encode(open(os.path.join(art,"mesh_pos.bin"),"rb").read()).decode()}";\n'
            + f'window.__IDX__="{base64.b64encode(open(os.path.join(art,"mesh_idx.bin"),"rb").read()).decode()}";\n'
            + f"</script>\n<script>{app}</script>\n</body>\n</html>\n")
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(html)
    print(f"built {out}  {len(html)/1048576:.2f} MB  "
          f"({len(M['parts'])} parts, {len(G['nodes'])} nodes, {len(G['edges'])} edges)")

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.artifacts/depgraph',
         sys.argv[2] if len(sys.argv) > 2 else 's500-impact.html')

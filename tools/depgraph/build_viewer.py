"""build_viewer.py -- assemble the self-contained offline viewer.

  python3 tools/depgraph/build_viewer.py .artifacts/depgraph s500-impact.html

Inlines three.js, the quantized geometry, and the derived graph into one HTML file.
No CDN, no network at runtime -- it must load with the ethernet unplugged.
"""
import base64, json, os, sys

def main(art='.artifacts/depgraph', out='s500-impact.html'):
    here = os.path.dirname(os.path.abspath(__file__))
    v = os.path.join(here, 'viewer')
    bundle = os.path.join(v, 'three-bundle.js')
    if not os.path.exists(bundle):
        sys.exit(f"missing {bundle}\n  cd tools/depgraph && npm install && npx esbuild "
                 f"viewer/three-entry.js --bundle --format=iife --global-name=THREE "
                 f"--minify --outfile=viewer/three-bundle.js")
    G = json.load(open(os.path.join(art, 'graph.json')))
    M = json.load(open(os.path.join(art, 'mesh.json')))
    html = (open(os.path.join(v, 'shell.html')).read()
            + f"\n<script>{open(bundle).read()}</script>\n<script>\n"
            + f"window.__GRAPH__={json.dumps(G, separators=(',', ':'))};\n"
            + f"window.__PARTS__={json.dumps(M, separators=(',', ':'))};\n"
            + f'window.__POS__="{base64.b64encode(open(os.path.join(art,"mesh_pos.bin"),"rb").read()).decode()}";\n'
            + f'window.__IDX__="{base64.b64encode(open(os.path.join(art,"mesh_idx.bin"),"rb").read()).decode()}";\n'
            + f"</script>\n<script>{open(os.path.join(v,'app.js')).read()}</script>\n")
    open(out, 'w').write(html)
    print(f"built {out}  {len(html)/1048576:.2f} MB  "
          f"({len(M['parts'])} parts, {len(G['nodes'])} nodes, {len(G['edges'])} edges)")

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.artifacts/depgraph',
         sys.argv[2] if len(sys.argv) > 2 else 's500-impact.html')

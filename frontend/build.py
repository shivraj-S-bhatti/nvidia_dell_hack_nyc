#!/usr/bin/env python3
"""build.py -- inline a saved run into the self-contained offline demo.

  python3 frontend/build.py                       # uses run.sample.json
  python3 frontend/build.py path/to/run.json      # uses a real saved run

Mirrors tools/depgraph/build_viewer.py: the judged path must load with the
ethernet unplugged, so the run data is inlined into a single HTML file rather
than fetched. The backend's job is only to emit run.json in the shape of
run.sample.json (schema mirrors the AGENTS.md stage contracts); the UI is
unchanged.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDER = "__RUN_JSON__"


def main(run_path=None, out="index.html"):
    run_path = run_path or os.path.join(HERE, "run.sample.json")
    with open(os.path.join(HERE, "index.template.html"), encoding="utf-8") as fh:
        tpl = fh.read()
    with open(run_path, encoding="utf-8") as fh:
        run = json.load(fh)  # parse to validate it is real JSON, then re-serialize compactly
    if PLACEHOLDER not in tpl:
        sys.exit("template is missing the __RUN_JSON__ placeholder")
    # </script> inside the data would end the tag early; JSON has none, but guard anyway.
    blob = json.dumps(run, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace(PLACEHOLDER, blob)
    out_path = os.path.join(HERE, out)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    kb = os.path.getsize(out_path) / 1024
    print(f"wrote {out_path} ({kb:.0f} KB) from {os.path.basename(run_path)} -- opens offline, no CDN")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)

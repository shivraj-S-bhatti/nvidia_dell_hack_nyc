#!/usr/bin/env python3
"""Ingest EasyRC parts into MongoDB Community (local, no auth).

Source of truth = the STEP->GLB converter manifest (../viewer/parts.json). We add a
stable partId, variant-family detection, and paths. No hand-authored metadata.

    pip install -r ../requirements.txt
    python ingest.py                 # uses mongodb://localhost:27017 (override with MONGO_URI)
"""
import json, re, os
from pymongo import MongoClient, ASCENDING, TEXT

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "..", "viewer", "parts.json")
URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB, COLL = "easyrc", "parts"


def variant_of(name):
    n = name.lower()
    m = re.match(r"(\d+) teeth crown gear", n)
    if m: return "crown-gear", {"teeth": int(m.group(1))}
    m = re.match(r"(\d+) teeth gear", n)
    if m: return "spur-gear", {"teeth": int(m.group(1))}
    if n == "front rim": return "rim", {"axle": "front"}
    if n == "rear rim": return "rim", {"axle": "rear"}
    return None, {}


def build_records():
    manifest = json.load(open(MANIFEST))
    records = []
    for p in manifest["parts"]:
        fam, params = variant_of(p["name"])
        records.append({
            "_id": p["partId"],
            "partId": p["partId"],
            "name": p["name"],
            "subsystem": p["subsystem"],
            "material": p["material"],
            "bboxMm": p["bboxMm"],
            "longestMm": max(p["bboxMm"]) if p.get("bboxMm") else None,
            "triangles": p.get("tris"),
            "vertices": p.get("verts"),
            "variantFamily": fam,
            "variantParams": params,
            "glb": p["glb"],
            "stepFile": f"CAD files/Car/{p['name']}.step",
            "source": "TRD-B/EasyRC (MIT)",
        })
    return records


def main():
    records = build_records()
    client = MongoClient(URI, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    coll = client[DB][COLL]
    coll.drop()
    coll.insert_many(records)
    coll.create_index([("subsystem", ASCENDING)])
    coll.create_index([("material", ASCENDING)])
    coll.create_index([("variantFamily", ASCENDING)])
    coll.create_index([("longestMm", ASCENDING)])
    coll.create_index([("name", TEXT)])
    print(f"ingested {coll.count_documents({})} parts into {DB}.{COLL} at {URI}")
    for row in coll.aggregate([{"$group": {"_id": "$subsystem", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]):
        print(f"  {row['_id']:22} {row['n']}")


if __name__ == "__main__":
    main()

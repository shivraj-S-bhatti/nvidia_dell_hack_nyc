#!/usr/bin/env python3
"""Agent-facing query functions over the EasyRC parts DB in MongoDB Community.

A plain, importable module — no framework coupling. Wire these into OpenClaw/NemoClaw
however you register tools. Every function returns plain JSON-serializable data:

    from part_db import query_parts, get_part, list_variants, list_subsystems
"""
import os
from pymongo import MongoClient

URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
_coll = MongoClient(URI, serverSelectionTimeoutMS=3000)["easyrc"]["parts"]
_PROJECT = {"_id": 0}


def query_parts(text=None, subsystem=None, material=None, variant_family=None,
                max_longest_mm=None, limit=25):
    """Search parts by any combination of filters. Returns a list of part records."""
    q = {}
    if subsystem: q["subsystem"] = subsystem
    if material: q["material"] = material
    if variant_family: q["variantFamily"] = variant_family
    if max_longest_mm is not None: q["longestMm"] = {"$lte": float(max_longest_mm)}
    if text: q["$text"] = {"$search": text}
    return list(_coll.find(q, _PROJECT).limit(int(limit)))


def get_part(part_id):
    """Fetch one full part record by its partId."""
    return _coll.find_one({"partId": part_id}, _PROJECT)


def list_variants(family):
    """List the interchangeable variants in a family (e.g. 'crown-gear', 'spur-gear', 'rim')."""
    return list(_coll.find({"variantFamily": family},
                           {"_id": 0, "partId": 1, "name": 1, "variantParams": 1, "glb": 1}))


def list_subsystems():
    """List subsystems with part counts."""
    return list(_coll.aggregate([{"$group": {"_id": "$subsystem", "count": {"$sum": 1}}},
                                 {"$project": {"_id": 0, "subsystem": "$_id", "count": 1}},
                                 {"$sort": {"count": -1}}]))


if __name__ == "__main__":
    import json
    print("== list_subsystems ==")
    print(json.dumps(list_subsystems(), indent=2))
    print("\n== query_parts(subsystem='drivetrain', text='gear') ==")
    for p in query_parts(subsystem="drivetrain", text="gear", limit=10):
        print(f"  {p['name']:22} {p['longestMm']} mm  {p['material']}  variant={p['variantParams']}")
    print("\n== list_variants('crown-gear') ==")
    print(json.dumps(list_variants("crown-gear"), indent=2))
    print("\n== get_part('part-easyrc-24-teeth-gear') ==")
    print(json.dumps(get_part("part-easyrc-24-teeth-gear"), indent=2))

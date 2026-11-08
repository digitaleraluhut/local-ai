#!/usr/bin/env python3
"""Model catalog tooling (models/catalog.yaml).

  check  validate the catalog against configs/*.ini and the memory budget (CI)
  sync   download missing catalog entries into a models dir (host, never deletes)
"""
import argparse, configparser, hashlib, os, sys, urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "/path/to/models/"
GIB = 1024 ** 3


def load_catalog(root):
    cat = yaml.safe_load((root / "models" / "catalog.yaml").read_text())
    return cat, {m["path"]: m for m in cat["models"]}


def preset_models(ini):
    """{section: [model paths relative to the models dir]} for one preset."""
    cp = configparser.ConfigParser(interpolation=None, comment_prefixes=(";",), strict=False)
    cp.optionxform = str
    cp.read_string("[*]\n" + Path(ini).read_text())  # presets have keys before the first section
    out = {}
    for sec in cp.sections():
        if sec == "*":
            continue
        paths = [cp[sec][k] for k in ("model", "model-draft") if k in cp[sec]]
        if paths:
            out[sec] = {"paths": [p[len(PLACEHOLDER):] for p in paths if p.startswith(PLACEHOLDER)],
                        "startup": cp[sec].get("load-on-startup", "false").lower() == "true"}
    return out


def weight(entry):
    return entry["size"] + entry.get("extra_size", 0)


def check(root):
    cat, by_path = load_catalog(root)
    errors = []
    budget = cat["budget_gib"] * GIB
    unmanaged = set(cat.get("unmanaged", []))
    for m in cat["models"]:
        for k in ("path", "repo", "file", "sha256", "size"):
            if k not in m:
                errors.append(f"{m.get('path', m)}: missing {k}")
        if len(str(m.get("sha256", ""))) != 64:
            errors.append(f"{m['path']}: sha256 must be 64 hex chars")
    used = set()
    for ini in sorted((root / "configs").glob("*.ini")):
        secs = preset_models(ini)
        if not secs:
            continue
        for name, s in secs.items():
            for p in s["paths"]:
                used.add(p)
                if p not in by_path and p not in unmanaged:
                    errors.append(f"{ini.name} [{name}]: {p} is not in the catalog")
        # Distinct files loaded at startup always count; the remaining
        # sections fill up to max_loaded, largest first (worst case).
        def sec_weight(s):
            return sum(weight(by_path[p]) for p in s["paths"] if p in by_path)
        startup = [s for s in secs.values() if s["startup"]]
        rest = sorted((s for s in secs.values() if not s["startup"]), key=sec_weight, reverse=True)
        limit = (cat.get("presets", {}).get(ini.name) or {}).get("max_loaded")
        loaded = startup + (rest[:max(limit - len(startup), 0)] if limit else rest)
        files = {p for s in loaded for p in s["paths"] if p in by_path}
        total = sum(weight(by_path[p]) for p in files)
        status = "ok" if total <= budget else "OVER BUDGET"
        print(f"{ini.name:32} {total / GIB:7.1f} GiB / {cat['budget_gib']} GiB  {status}")
        if total > budget:
            errors.append(f"{ini.name}: {total / GIB:.1f} GiB can be loaded at once, budget {cat['budget_gib']} GiB")
    for p, m in by_path.items():
        if p not in used and not m.get("shard"):
            errors.append(f"{p}: in the catalog but used by no preset")
    for e in errors:
        print("ERROR:", e, file=sys.stderr)
    return 1 if errors else 0


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()


def sync(root, models_dir, verify_all):
    _, by_path = load_catalog(root)
    rc = 0
    for p, m in by_path.items():
        dest = Path(models_dir) / p
        if dest.exists():
            if dest.stat().st_size != m["size"]:
                print(f"WARN {p}: size {dest.stat().st_size} != catalog {m['size']}; left untouched")
            elif verify_all and sha256_of(dest) != m["sha256"]:
                print(f"ERROR {p}: sha256 mismatch; left untouched"); rc = 1
            continue
        url = f"https://huggingface.co/{m['repo']}/resolve/main/{m['file']}"
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {p} ({m['size'] / GIB:.1f} GiB)", flush=True)
        try:
            have = part.stat().st_size if part.exists() else 0
            req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab" if have and r.status == 206 else "wb") as f:
                while chunk := r.read(8 << 20):
                    f.write(chunk)
            if sha256_of(part) != m["sha256"]:
                print(f"ERROR {p}: sha256 mismatch after download; removing the partial file")
                part.unlink(); rc = 1
                continue
            os.replace(part, dest)
        except Exception as e:  # keep going with the other models
            print(f"ERROR {p}: {e}"); rc = 1
    return rc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    s = sub.add_parser("sync")
    s.add_argument("--models-dir", default="/srv/localai/models")
    s.add_argument("--verify-all", action="store_true", help="also hash existing files")
    a = ap.parse_args()
    sys.exit(check(ROOT) if a.cmd == "check" else sync(ROOT, a.models_dir, a.verify_all))

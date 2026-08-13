#!/usr/bin/env python3
"""Remove database bytes duplicated inside Agent-World checkpoints.

The public repository already ships every database as ``environment_mix/<env_id>/``.
Graph synthesis reads those files directly and only needs tool schemas from the checkpoint.
Removing ``DatabaseAgent.filepath2base64`` keeps the release below GitHub's file-size limit
without changing any executable tool or database record.
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "environment_mix",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="rewrite checkpoints; without this flag only report removable bytes",
    )
    args = parser.parse_args()

    changed = 0
    removed_bytes = 0
    for path in sorted(args.env_dir.glob("*_step4_checkpoint.json")):
        with path.open(encoding="utf-8") as f:
            checkpoint = json.load(f)
        database = checkpoint.get("data", {}).get("DatabaseAgent", {})
        payload = database.get("filepath2base64")
        if payload is None:
            continue

        removed_bytes += len(json.dumps(payload, ensure_ascii=False).encode())
        changed += 1
        if args.apply:
            del database["filepath2base64"]
            tmp = path.with_suffix(path.suffix + ".part")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
            tmp.replace(path)

    action = "removed" if args.apply else "found"
    print(f"{action} duplicated payloads in {changed} checkpoints ({removed_bytes} bytes)")


if __name__ == "__main__":
    main()

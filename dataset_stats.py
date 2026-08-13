#!/usr/bin/env python3
"""Print reproducible statistics for the Agent-World release bundle."""

import argparse
import json
from collections import Counter
from pathlib import Path


def load_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()

    root = args.root.resolve()
    env_dir = root / "environment_mix"
    index = load_json(env_dir / "index.json")

    checkpoint_ids = {
        path.name.removesuffix("_step4_checkpoint.json")
        for path in env_dir.glob("*_step4_checkpoint.json")
    }
    database_ids = {
        path.name for path in env_dir.iterdir()
        if path.is_dir() and path.name.isdigit()
    }

    question_files = sorted((env_dir / "questions").glob("*.json"))
    question_count = 0
    for path in question_files:
        question_count += len(load_json(path).get("tasks", []))

    taxonomy = {
        "L1": len({row["taxonomy"]["L1_id"] for row in index}),
        "L2": len({row["taxonomy"]["L2_id"] for row in index}),
        "L3": len({
            (row["taxonomy"]["L2_id"], row["taxonomy"]["L3_name"])
            for row in index
        }),
    }

    sft_dir = root / "sft_merged_all_sources_messages_only_shards_clean_v2"
    sft_records = 0
    message_count = 0
    roles = Counter()
    sft_shards = []
    if sft_dir.is_dir():
        sft_shards = sorted(sft_dir.glob("*.json"))
        for path in sft_shards:
            rows = load_json(path)
            sft_records += len(rows)
            for row in rows:
                messages = row.get("messages", [])
                message_count += len(messages)
                roles.update(message.get("role") for message in messages)

    result = {
        "environments": len(index),
        "checkpoints": len(checkpoint_ids),
        "database_directories": len(database_ids),
        "missing_database_directories": sorted(checkpoint_ids - database_ids),
        "missing_checkpoints": sorted(database_ids - checkpoint_ids),
        "tools": sum(row["n_tools"] for row in index),
        "collections": sum(row["n_collections"] for row in index),
        "records": sum(row["n_records"] for row in index),
        "taxonomy": taxonomy,
        "question_files": len(question_files),
        "questions": question_count,
        "questions_from_index": sum(row["n_questions"] for row in index),
        "sft_shards": len(sft_shards),
        "sft_records": sft_records,
        "sft_messages": message_count,
        "sft_roles": dict(sorted(roles.items())),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

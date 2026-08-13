# Environment corpus

563 MCP environments in one sequence. Each one is a backend: a database of records and the
endpoints that read and change it. They are numbered `0000000`, `0001000`, ... and carry no marker
of where they came from -- the numbering is a shuffle, so neighbouring identifiers are unrelated.

## Layout

```
0000000/                         the database, as the files the tools actually open
0000000_step4_checkpoint.json    the same database plus the tool schemas and implementations
questions/0000000.json           verified tasks for that environment
questions.parquet                every task, in the question bank's row format
index.csv, index.json            one line per environment: name, taxonomy, size, question count
```

`0000000/` holds the database as real files. Internal construction checkpoints also embedded
the same bytes under `data.DatabaseAgent.filepath2base64`; the Git release removes that duplicate
payload to stay below repository size limits. `local_files_dir` and `file_list` still name the
files as they sit here. Questions live outside the database directory on purpose: it is mounted as
the agent's datastore, and answers must not be readable from inside it.

## Where the tools look for their data

Each implementation resolves its database when it is called, in this order:

1. `MCP_DB_DIR`, if set — point it anywhere to run an environment against a copy
2. `./environment_mix/<id>` — the directory shipped here, so running from this directory needs no
   configuration at all
3. `/app/database` — the mount, which is what remains inside the container

The environment's own directory is checked before the mount on purpose: a machine can carry an
unrelated `/app/database`, and a tool that found it would read someone else's records while
appearing to work.

## Classification

Every environment carries three levels under `metadata.taxonomy`: 20 top categories,
46 subcategories and 245 leaves. The first two come from the published taxonomy; the
third was built per subcategory so that each has a small controlled vocabulary rather than a label
invented per environment.

Largest categories:

- System & Cloud Infrastructure — 76
- Data Storage & Databases — 75
- Search & Information Retrieval — 74
- Communication & General Utilities — 58
- Social Media & Community — 32
- Document & Design — 31
- AI & Machine Learning — 24
- Academic & Scientific Research — 23

## What was verified

Every environment was loaded from the files above and called. 8927 of 8927 declared tools
load from their own database directory, in 563
environments all of them do, and 532 returned real records from a read endpoint called against
the shipped files. What each environment's audit observed is recorded in `metadata.execution_audit`
and `metadata.verified_call`.

67096 records across the corpus.

## Questions

1432 tasks over 530 environments. Answers were produced by executing the tool chain, not
written by a model: the chain and its arguments are kept in the rubric under `verified_tool_chain`,
so any answer can be reproduced by replaying it.

## Calling one

From the repository root, with nothing configured:

```python
import json
ck = json.load(open('environment_mix/0000000_step4_checkpoint.json'))
tool = ck['data']['ToolDesignAgent']['tool_schemas'][0]
ns = {}
exec(tool['implementation'], ns)
ns[tool['name'].replace('-', '_')](**args)   # reads environment_mix/0000000/
```

The implementations are plain Python in `tool_schemas[i]['implementation']`. They read and write the
files in the environment's directory, so state a tool changes is there afterwards.

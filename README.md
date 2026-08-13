# Agent-World

> Scaling Real-World Environment Synthesis for Evolving General Agent Intelligence

[Paper](https://arxiv.org/abs/2604.18292) ·
[Project Page](https://agent-tars-world.github.io/-/) ·
[Code](https://github.com/RUC-NLPIR/Agent-World) ·
[Hugging Face Paper](https://huggingface.co/papers/2604.18292) ·
[机器之心](https://www.163.com/dy/article/KS8DOH8L0511AQHO.html) ·
[中文说明](README_zh.md)

Agent-World is a self-evolving training arena that connects scalable, stateful tool
environments with verifiable task synthesis and continuous agent training. This repository
releases a reproducible environment subset, graph-based query/rubric synthesis code, a
Qwen3-14B generation example, and the registration template for the forthcoming Agent-World
supervised fine-tuning dataset.

## Demos

[Flight and stay search](https://agent-tars-world.github.io/-/agent-demo/demo_flight.mp4) ·
[E-commerce](https://agent-tars-world.github.io/-/agent-demo/demo_ecomm.mp4) ·
[Notion](https://agent-tars-world.github.io/-/agent-demo/demo_notion.mp4) ·
[Slack](https://agent-tars-world.github.io/-/agent-demo/demo_slack.mp4) ·
[GitHub](https://agent-tars-world.github.io/-/agent-demo/demo_github.mp4) ·
[Document operations](https://agent-tars-world.github.io/-/agent-demo/demo_document.mp4)

More interactive cases are available on the
[project page](https://agent-tars-world.github.io/-/#demos).
For environment-synthesis references, see EnvScaler's
[environment/user interaction](https://github.com/user-attachments/assets/613b46fd-63db-4050-91d2-f7aca2a766e3),
[agent interaction](https://github.com/user-attachments/assets/b8186257-a22d-4ec1-9ccf-82f6bd23a4b5), and
[environment construction](https://github.com/user-attachments/assets/fd947e46-014a-41cd-87bb-6744c3dd5b32)
demos.

## Release snapshot

The paper reports the complete Agent-World collection of **1,978 environments** and
**19,822 tools**. This repository contains the first public subset:

- **563 executable environments**, combining 500 top-used MCP server themes collected from
  [Smithery](https://smithery.ai/servers) with 63 environments derived from industrial PRDs;
- **8,927 executable tools**, each shipped with its schema and Python implementation;
- **67,096 database records** across 2,635 collections;
- a three-level taxonomy with **20 L1 categories, 46 L2 categories, and 245 L3 leaves**;
- **1,432 example tasks with answers and rubrics**, covering 530 environments;
- **65,287 multi-turn SFT examples** in 131 JSON shards, planned for a separate Hugging Face
  Datasets release and not stored in this Git repository.

All numbers above are computed from the files in this release rather than copied from the
paper.

Recompute them locally with:

```bash
python3 dataset_stats.py
```

## Repository layout

```text
.
├── environment_mix/
│   ├── <env_id>/                         # mutable database files
│   ├── <env_id>_step4_checkpoint.json    # environment, tools, and implementations
│   ├── questions/<env_id>.json           # per-environment task/rubric examples
│   ├── questions.parquet                 # combined task/rubric table
│   ├── index.json                        # taxonomy and environment statistics
│   └── README.md
├── graph_synth.py                        # graph-based task synthesis entry point
├── graph_syth.py                         # compatibility implementation for early bundles
├── prepare_git_release.py                # remove checkpoint payloads duplicated by databases
├── run.sh                                # Qwen3-14B + vLLM reproduction script
├── graph_readme.md                       # detailed synthesis design
├── DATA_CARD.md                          # provenance, statistics, limitations, and safety
├── THIRD_PARTY_NOTICES.md                # upstream projects and redistribution notice
├── requirements-vllm.txt                 # verified model-service dependencies
└── training/
    ├── dataset_info.json                 # LlamaFactory dataset registration
    └── README.md                         # SFT and RL integration notes
```

Duplicate transport archives, model weights, generated outputs, and the 3 GiB SFT corpus are
excluded from this Git repository.

## Quick validation

The graph pipeline itself uses only the Python standard library. Validate the code, corpus,
and one environment without downloading a model:

```bash
bash run.sh --check
```

This checks Python and shell syntax, discovers all checkpoints, loads a checkpoint, verifies
its paired database directory, and confirms that executable tool implementations are present.

## Understanding an environment

Every environment has two paired parts:

1. `environment_mix/<env_id>/` is the stateful database. Tools read and update these files.
2. `environment_mix/<env_id>_step4_checkpoint.json` describes the environment and contains
   the executable tool interfaces.

For example, `0547000` is a Linode-like cloud environment:

```text
environment_mix/0547000/
├── linode_instances.json
├── infra_catalog.json
├── kubernetes.json
├── network_security.json
├── operations.json
├── storage_dns_managed.json
└── request_logs.json
```

Its checkpoint contains:

```text
metadata
├── env_id, name, description
├── taxonomy
├── n_tools, n_collections, n_records, n_questions
└── execution_audit and verified_call

data
├── DatabaseAgent
│   └── database file metadata (the Git release omits duplicated encoded contents)
└── ToolDesignAgent
    └── tool_schemas[]
        ├── name and description
        ├── parameters (JSON Schema)
        └── implementation (executable Python source)
```

The following snippet loads the first tool and binds it to the shipped database:

```python
import json
import os

env_id = "0547000"
checkpoint_path = f"environment_mix/{env_id}_step4_checkpoint.json"

with open(checkpoint_path, encoding="utf-8") as f:
    checkpoint = json.load(f)

tool = checkpoint["data"]["ToolDesignAgent"]["tool_schemas"][0]
os.environ["MCP_DB_DIR"] = os.path.abspath(f"environment_mix/{env_id}")

namespace = {"__name__": "agent_world_environment"}
exec(tool["implementation"], namespace)
function = namespace[tool["name"].replace("-", "_")]

print(tool["name"])
print(tool["parameters"])
```

Tool implementations are executable code. Run untrusted or modified environments inside an
isolated process or container, and use a copied database when calling mutation tools.

## Example questions and rubrics

`environment_mix/questions.parquet` combines 1,432 examples. The same content is available
as readable JSON under `environment_mix/questions/`. Each example contains:

- `task`: the user query;
- `reference_answer`: an answer grounded in actual tool execution;
- `grading_rubric.success_criteria`: objective grading conditions;
- `grading_rubric.verified_tool_chain`: the tools and arguments used to verify the task.

These examples demonstrate the data contract. They are distinct from the 65,287-example SFT
corpus described below.

## Graph-based query and rubric synthesis

The included pipeline constructs a dependency graph over tools, samples multi-tool walks,
executes each walk against a private copy of the environment database, asks a local model to
write a natural user query, derives an answer and rubric from the observations, and replays
the chain in a clean copy to remove volatile values.

Read [graph_readme.md](graph_readme.md) for the seven-stage design and output schema.

### Reproduce with Qwen3-14B

The example launcher targets an OpenAI-compatible vLLM server:

```bash
# Place the model at ./Qwen3-14B, or provide another local path.
MODEL_PATH=/path/to/Qwen3-14B bash run.sh 1000

# Reuse an already running compatible server on the configured port.
bash run.sh 1000 --no-serve
```

Outputs are written to `output/questions_graph.json`; logs go to `output/logs/`. Every path
can be overridden through the environment variables documented in
[graph_readme.md](graph_readme.md). The model weights are not included in this repository.

## Supervised fine-tuning

The forthcoming SFT release contains **65,287** records. Every record has one `messages` field using
OpenAI-style `system`, `user`, and `assistant` roles. The corpus contains 1,462,197 messages
in total and averages 22.4 messages per example.

For [LlamaFactory](https://github.com/hiyouga/LlamaFactory), copy or link the SFT directory
into `LlamaFactory/data/`, then merge the provided
[`training/dataset_info.json`](training/dataset_info.json) entry into
`LlamaFactory/data/dataset_info.json`. See [training/README.md](training/README.md) for a
minimal training configuration.

The SFT corpus is planned for a separate Hugging Face Datasets release and is not included in
this Git repository. Its download link will be added after publication.

## Reinforcement learning

The released environments are stateful runtimes, not a drop-in RL trainer. To train with
[verl](https://github.com/verl-project/verl), adapt its multi-turn rollout loop so that every
sample receives an isolated copy of its environment database, tool calls execute against
that copy, and the final response is scored against the structured rubric.

[EnvScaler](https://github.com/RUC-NLPIR/EnvScaler) provides a useful reference for
environment-backed agent training and publishes several interaction cases. Its public RL
integration is based on [ROLL](https://github.com/alibaba/ROLL) and
[Gem](https://github.com/axon-rl/gem), rather than verl. The
[Agent-World project page](https://agent-tars-world.github.io/-/#demos) also shows examples
across travel, e-commerce, Notion, Slack, population data, telecom, Twitter, GitHub, and
document operations.

For an agentic RL codebase and README organization close to this release, see
[ARPO](https://github.com/RUC-NLPIR/ARPO).

## Data provenance and safety

Environment themes were selected from public MCP server specifications and industrial PRDs.
The released databases are offline environment state used for research; they do not connect
to the corresponding production services by default.

Some environments model authentication, credentials, security operations, or user-generated
content. Values resembling tokens can be synthetic fixtures or text copied from public tool
examples. Review the corpus under your own security and content policy before redistribution
or deployment. Never execute tool implementations with production credentials.

See [DATA_CARD.md](DATA_CARD.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before
redistributing the corpus.

## Citation

```bibtex
@article{dong2026agent,
  title   = {Agent-World: Scaling Real-World Environment Synthesis for Evolving General Agent Intelligence},
  author  = {Dong, Guanting and Lu, Junting and Huang, Junjie and Zhong, Wanjun and
             Liu, Longxiang and Huang, Shijue and Li, Zhenyu and Zhao, Yang and
             Song, Xiaoshuai and Li, Xiaoxi and Jin, Jiajie and Zhu, Yutao and
             Wang, Hanbin and Lei, Fangyu and Luo, Qinyu and Chen, Mingyang and
             Chen, Zehui and Feng, Jiazhan and Wen, Ji-Rong and Dou, Zhicheng},
  journal = {CoRR},
  volume  = {abs/2604.18292},
  year    = {2026},
  url     = {https://arxiv.org/abs/2604.18292}
}
```

## Acknowledgments

This release builds on the open-source ecosystem around
[Smithery](https://smithery.ai/servers),
[Qwen3](https://huggingface.co/Qwen/Qwen3-14B),
[vLLM](https://github.com/vllm-project/vllm),
[LlamaFactory](https://github.com/hiyouga/LlamaFactory),
[verl](https://github.com/verl-project/verl),
[EnvScaler](https://github.com/RUC-NLPIR/EnvScaler), and
[ARPO](https://github.com/RUC-NLPIR/ARPO).

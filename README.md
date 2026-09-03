<div align="center">
  <img src="assets/agent-world-banner.svg" width="100%" alt="Agent-World banner"/>

  <h1>🌐 Agent-World</h1>
  <h3>Real Environments. Verifiable Tasks. Evolving Agents.</h3>

  <a href="https://arxiv.org/abs/2604.18292"><img src="https://img.shields.io/badge/PAPER-ARXIV-B31B1B?style=for-the-badge&logo=arxiv" alt="Paper"/></a>
  <a href="https://github.com/RUC-NLPIR/Agent-World"><img src="https://img.shields.io/badge/CODE-GITHUB-181717?style=for-the-badge&logo=github" alt="Code"/></a>
  <a href="https://agent-tars-world.github.io/-/"><img src="https://img.shields.io/badge/PROJECT_PAGE-LIVE-14B8A6?style=for-the-badge&logo=googlechrome" alt="Project page"/></a>
  <a href="https://huggingface.co/papers/2604.18292"><img src="https://img.shields.io/badge/HUGGING_FACE-PAPER-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black" alt="Hugging Face Paper"/></a>
  <a href="https://huggingface.co/datasets/dongguanting/Agent-World-SFT-48K"><img src="https://img.shields.io/badge/SFT_DATA-48K-FF9D00?style=for-the-badge&logo=huggingface&logoColor=black" alt="SFT Dataset"/></a>
  <a href="https://www.163.com/dy/article/KS8DOH8L0511AQHO.html"><img src="https://img.shields.io/badge/MEDIA-机器之心-7C3AED?style=for-the-badge" alt="Media"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/LICENSE-MIT-2563EB?style=for-the-badge" alt="MIT License"/></a>

  <p><strong>English</strong> | <a href="README_zh.md">简体中文</a></p>

  <p><em>A self-evolving training arena that turns real-world tool ecosystems into stateful,
  executable environments—and turns those environments into verifiable agent experience.</em></p>
</div>

<p align="center">
  <a href="#agent-demos">Demos</a> ·
  <a href="#whats-in-this-release">Release</a> ·
  <a href="#quick-validation">Validation</a> ·
  <a href="#supervised-fine-tuning">SFT</a> ·
  <a href="#citation">Citation</a>
</p>

> [!TIP]
> Validate all released environments without downloading a model:
> `bash run.sh --check`

<table>
  <tr>
    <td align="center"><strong>563</strong><br/>released environments</td>
    <td align="center"><strong>8,927</strong><br/>executable tools</td>
    <td align="center"><strong>67,096</strong><br/>database records</td>
    <td align="center"><strong>~48K</strong><br/>SFT examples</td>
  </tr>
</table>

## 🎬 Agent demos

<details open>
<summary><strong>1. Agent-World overview</strong></summary>
<br/>
<video controls preload="metadata" width="100%">
  <source src="https://agent-tars-world.github.io/-/agent-demo/agent_demo.mp4" type="video/mp4" />
  Your browser does not support embedded video. [Watch the Agent-World overview](https://agent-tars-world.github.io/-/agent-demo/agent_demo.mp4).
</video>
<p><a href="https://agent-tars-world.github.io/-/agent-demo/agent_demo.mp4">Open the overview video directly</a> (use this link if inline playback is unavailable).</p>
<p>Agents plan, call executable tools, observe state changes, and solve verifiable tasks across diverse real-world environments.</p>
</details>

<details open>
<summary><strong>2. Flight and stay search</strong></summary>
<br/>
<video controls preload="metadata" width="100%">
  <source src="https://agent-tars-world.github.io/-/agent-demo/demo_flight.mp4" type="video/mp4" />
  Your browser does not support embedded video. [Watch the flight and stay search demo](https://agent-tars-world.github.io/-/agent-demo/demo_flight.mp4).
</video>
<p><a href="https://agent-tars-world.github.io/-/agent-demo/demo_flight.mp4">Open the flight and stay search video directly</a> (use this link if inline playback is unavailable).</p>
<p>A long-horizon travel workflow combining inventory search, filtering, comparison, and booking-related tool interactions.</p>
</details>

<details>
<summary><strong>3. More environment cases</strong></summary>
<br/>

[E-commerce](https://agent-tars-world.github.io/-/agent-demo/demo_ecomm.mp4) ·
[Notion](https://agent-tars-world.github.io/-/agent-demo/demo_notion.mp4) ·
[Slack](https://agent-tars-world.github.io/-/agent-demo/demo_slack.mp4) ·
[Telecom](https://agent-tars-world.github.io/-/agent-demo/demo_telecom.mp4) ·
[GitHub](https://agent-tars-world.github.io/-/agent-demo/demo_github.mp4) ·
[Document Operations](https://agent-tars-world.github.io/-/agent-demo/demo_document.mp4) ·
[Population Data](https://agent-tars-world.github.io/-/agent-demo/demo_population.mp4) ·
[Twitter](https://agent-tars-world.github.io/-/agent-demo/demo_twitter.mp4)
</details>

More interactive cases are available on the
[Agent-World project page](https://agent-tars-world.github.io/-/#demos).

## ✨ What's in this release

### 563 high-quality, executable environments (selected from 1,978)

Because each environment preserves rich, realistic underlying data files, the full raw
data for all **1,978 environments** is too large to distribute as one repository snapshot.
We therefore release a **Top-Used subset** that has also passed quality filtering, keeping
the package practical to download, inspect, and reproduce.

- **500 environments** were selected from high-usage MCP servers on
  [Smithery](https://smithery.ai/servers). We prioritize widely used server themes with
  meaningful workflows and omit low-usage or low-signal environments.
- **63 environments** were constructed from industrial PRDs and real-world tool
  documentation, extending coverage beyond the public MCP ecosystem.

Together they provide **8,927 executable tools**, **67,096 database records** across 2,635
collections, and a three-level taxonomy with **20 L1 / 46 L2 / 245 L3** categories. The
release also includes **1,432 verified question/answer/rubric examples** covering 530
environments.

The paper reports the original full research corpus of **1,978 environments and 19,822
tools**. The 563 environments here are the selected public subset whose database and tool
artifacts are released in this repository.

### Approximately 48K SFT trajectories

The current **Agent-World SFT dataset contains approximately 48K examples**. It is the
updated release; please use the Hugging Face dataset below as the source of truth for the
current revision and split sizes.

After the paper release, we continued scaling the synthesis ecosystem to approximately
**2.5K environments**, covering broader domains, workflows, tool combinations, and task
scenarios. The 2.5K figure describes the expanded synthesis pool; this Git repository
currently publishes the selected 563 environment artifacts above.

The SFT dataset is available at
[dongguanting/Agent-World-SFT-48K](https://huggingface.co/datasets/dongguanting/Agent-World-SFT-48K).
This repository includes the matching LlamaFactory registration and training instructions.

### Release statistics

Environment and question statistics can be recomputed locally:

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
├── GRAPH_SYNTHESIS.md                    # detailed synthesis design
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

These examples demonstrate the data contract. They are distinct from the approximately 48K-example SFT
corpus described below.

## Graph-based query and rubric synthesis

The included pipeline constructs a dependency graph over tools, samples multi-tool walks,
executes each walk against a private copy of the environment database, asks a local model to
write a natural user query, derives an answer and rubric from the observations, and replays
the chain in a clean copy to remove volatile values.

Read [GRAPH_SYNTHESIS.md](GRAPH_SYNTHESIS.md) for the seven-stage design and output schema.

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
[GRAPH_SYNTHESIS.md](GRAPH_SYNTHESIS.md). The model weights are not included in this repository.

## Supervised fine-tuning

The released SFT dataset contains **approximately 48K records**. Every record has one
`messages` field using OpenAI-style `system`, `user`, and `assistant` roles. Consult the
Hugging Face dataset card for the current message counts and splits.

The dataset is hosted at
[dongguanting/Agent-World-SFT-48K](https://huggingface.co/datasets/dongguanting/Agent-World-SFT-48K).
For [LlamaFactory](https://github.com/hiyouga/LlamaFactory), merge the provided
[`training/dataset_info.json`](training/dataset_info.json) entry into
`LlamaFactory/data/dataset_info.json`; LlamaFactory will load it directly from Hugging Face.
See [training/README.md](training/README.md) for a minimal training configuration.

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

Environment themes were selected from high-usage public MCP server specifications,
industrial PRDs, and real-world tool documentation. The released databases are offline
environment state used for research; they do not connect to the corresponding production
services by default.

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

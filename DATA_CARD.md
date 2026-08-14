# Agent-World release data card

## Summary

This repository is the first public subset of the environments used by Agent-World. It
contains stateful offline databases, executable tool interfaces, and verified
question/rubric examples. Statistics and loading metadata for the
[Agent-World-SFT-65K](https://huggingface.co/datasets/dongguanting/Agent-World-SFT-65K)
dataset are documented here, while its shards are distributed through Hugging Face.

The paper reports 1,978 environments and 19,822 tools. This release contains 563 environments
and 8,927 tools.

## Environment corpus

- Environments: 563
- Checkpoint/database pairs: 563/563, with no missing pair
- Tools: 8,927
- Collections: 2,635
- Records reported by the index: 67,096
- Taxonomy: 20 L1 categories, 46 L2 categories, 245 L3 leaves

Each `environment_mix/<env_id>/` directory is a mutable database. Its paired
`<env_id>_step4_checkpoint.json` contains metadata, tool JSON Schemas, and Python source in
`data.ToolDesignAgent.tool_schemas[].implementation`.

## Question and rubric examples

- JSON files: 530
- Tasks: 1,432
- Environments covered: 530
- Combined file: `environment_mix/questions.parquet` (53.1 MiB)

The Parquet columns are:

- `prompt`
- `ability`
- `data_source`
- `reward_model`
- `extra_info`

The readable JSON representation uses `task`, `reference_answer`, and `grading_rubric`.
Rubrics include objective success criteria and a verified tool chain.

## SFT corpus

- Records: 65,287
- Original paper trajectories: approximately 40,000
- Continuously synthesized post-paper updates: 25,287
- Expanded synthesis pool: approximately 2,500 environments
- JSON shards: 131
- Messages: 1,462,197
- Average messages per record: 22.4
- Roles: 65,287 system, 698,455 user, 698,455 assistant messages
- Uncompressed size: approximately 3.0 GiB

Every SFT record has one OpenAI-style `messages` array. The SFT directory is excluded from
Git because it is distributed separately through
[Hugging Face Datasets](https://huggingface.co/datasets/dongguanting/Agent-World-SFT-65K).

## Provenance

The 563-environment release combines 500 high-quality themes selected from high-usage MCP
servers listed by [Smithery](https://smithery.ai/servers) and 63 environments derived from
industrial PRDs and real-world tool documentation. Selection prioritizes widely used servers
with meaningful workflows and excludes low-usage or low-signal themes.

The paper reports an original corpus of 1,978 environments. Continued synthesis after the
paper expanded the pool used to produce SFT trajectories to approximately 2,500
environments. This Git release contains the selected 563 environment artifacts, not the
entire expanded synthesis pool. Environment databases are offline research artifacts
constructed for tool-use training and verification.

## Intended uses

- research on stateful and multi-tool agents;
- supervised fine-tuning of multi-turn agent trajectories;
- reinforcement learning with isolated per-rollout database copies;
- synthesis and verification of graph-based tool-use tasks;
- analysis of environment and tool diversity.

## Limitations

- This is a subset of the full corpus reported in the paper.
- Environment realism varies, and modeled services may differ from their current production
  interfaces.
- Some observations contain timestamps, generated identifiers, empty values, or synthetic
  credentials.
- The shipped Graph generator emits a different schema from the bundled readable question
  JSON files.
- Rubric-conditioned rewards may require an LLM judge unless converted into deterministic
  checks.

## Safety

Checkpoint implementations are executable Python and must be treated as code. Run them only
in isolated processes or containers, bind `MCP_DB_DIR` to a disposable database copy, and
never provide production credentials.

The corpus contains strings that resemble API keys or access tokens. They may be synthetic
fixtures or public example text, but this has not been proven for every occurrence. Perform
an independent secret and content review before redistribution.

## Recomputing statistics

```bash
python3 dataset_stats.py
```

# Training with Agent-World data

## SFT with LlamaFactory

The [Agent-World-SFT-65K](https://huggingface.co/datasets/dongguanting/Agent-World-SFT-65K)
corpus contains 65,287 JSON records in 131 shards. It combines the
original 40K Agent-World SFT trajectories reported in the paper with 25,287 trajectories
from continuous post-paper synthesis over an ecosystem expanded to approximately 2.5K
environments:

```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

It contains 1,462,197 messages in total. Every shard is a JSON array and all records use the
same schema. The shards are hosted on Hugging Face rather than stored in this Git repository.

### 1. Install LlamaFactory

Follow the current instructions in the
[official LlamaFactory repository](https://github.com/hiyouga/LlamaFactory):

```bash
git clone --depth 1 https://github.com/hiyouga/LlamaFactory.git
cd LlamaFactory
pip install -e .
```

### 2. Register the Hugging Face dataset

Merge the `agent_world_sft` object from this repository's `training/dataset_info.json` into
`LlamaFactory/data/dataset_info.json`. Its `hf_hub_url` points to
`dongguanting/Agent-World-SFT-65K`, so no manual shard copy is required.

### 3. Configure training

A minimal full-parameter Qwen3 SFT configuration is:

```yaml
model_name_or_path: /path/to/Qwen3-8B
trust_remote_code: true

stage: sft
do_train: true
finetuning_type: full
deepspeed: examples/deepspeed/ds_z3_config.json

dataset_dir: data
dataset: agent_world_sft
template: qwen3
cutoff_len: 16384
overwrite_cache: true
preprocessing_num_workers: 16

output_dir: saves/agent-world-sft
logging_steps: 10
save_steps: 500
plot_loss: true
overwrite_output_dir: true

per_device_train_batch_size: 1
gradient_accumulation_steps: 2
learning_rate: 7.0e-6
num_train_epochs: 3.0
lr_scheduler_type: cosine
warmup_ratio: 0.1
bf16: true
ddp_timeout: 180000000
```

Run it with:

```bash
llamafactory-cli train /path/to/agent_world_sft.yaml
```

Choose the model, context length, batch size, DeepSpeed strategy, and chat template according
to your hardware and base checkpoint. Training and inference must use the same template.

## RL with verl

Use [verl](https://github.com/verl-project/verl) as the distributed RL backend and implement
a custom multi-turn rollout adapter for Agent-World environments:

1. Read a task and its `env_id`.
2. Copy `environment_mix/<env_id>/` to a per-rollout temporary directory.
3. Set `MCP_DB_DIR` to that directory inside the tool worker.
4. Load tools from `<env_id>_step4_checkpoint.json`.
5. Parse the policy's tool call, execute the matching implementation, and append the
   observation to the conversation.
6. Continue until the policy emits a final answer or reaches the tool-call limit.
7. Score the answer using the task's structured rubric.
8. Remove the temporary directory after the rollout.

Database isolation is mandatory: mutation tools write state, and two concurrent rollouts must
never share one database copy or process-wide `MCP_DB_DIR`.

The shipped question examples use rubric-conditioned grading rather than a directly
executable scalar reward. Production RL therefore needs either a deterministic rubric
adapter for the selected task subset or an LLM judge whose prompt and version are fixed for
the experiment.

For an end-to-end agentic RL implementation based on verl, also see
[ARPO](https://github.com/RUC-NLPIR/ARPO).

[EnvScaler](https://github.com/RUC-NLPIR/EnvScaler) is another useful environment-training
reference, but its released RL integration uses [ROLL](https://github.com/alibaba/ROLL) and
[Gem](https://github.com/axon-rl/gem), not verl.

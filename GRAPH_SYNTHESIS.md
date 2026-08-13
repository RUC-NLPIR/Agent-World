# 图式造题链路（questions + rubrics）

把环境变成题目：题干由模型写，**标准答案由真实执行工具链得到**，不是模型编的。

```
run.sh                      执行脚本，所有路径与参数都在这里
graph_synth.py              造题链路入口（`graph_syth.py` 为早期拼写兼容实现）
output/questions_graph.json 产出（602 题，见「实测」）
```

## 跑起来

```bash
bash run.sh --check                       # 不下载模型，检查代码和环境语料
bash run.sh                    # 起本地模型 + 造题，题量按脚本里的 TARGET
bash run.sh 1000               # 本次只造 1000 题
bash run.sh 1000 --no-serve    # 模型服务已在跑
```

默认 `TENSOR_PARALLEL=4`，至少需要能容纳 Qwen3-14B 及 32K 上下文的 4 卡机器。8 卡或多机多副本用于提高全量
吞吐，不是启动链路的硬要求。脚本会拉起 vLLM 的 OpenAI 兼容服务，等它就绪再开始造题；链路本身只用 Python
标准库，不依赖任何外部 API。

L20（driver 535 / CUDA 12.6）上验证过的组合是 `vllm==0.10.0` + `transformers==4.55.2` + `ninja`：
vLLM 0.26 带的 torch 2.9 要求更新的驱动起不来，transformers 5.x 与 vLLM 0.10 不兼容，缺 ninja 则
torch.compile 阶段失败。14B 权重从本地存储加载加首次编译约 6 分钟。

```bash
pip install -r requirements-vllm.txt
```

## 路径配置

默认情况下，脚本使用与 `run.sh` 同级的目录，不包含服务器绝对路径：

- 环境语料：`environment_mix/`
- 模型权重：`Qwen3-14B/`
- 题目输出：`output/questions_graph.json`
- 日志：`output/logs/`

这些路径都可以用同名环境变量覆盖，例如：

```bash
MODEL_PATH=/data/models/Qwen3-14B bash run.sh
OUT=/data/results/questions.json LOG_DIR=/data/logs bash run.sh 1000
```

| 变量 | 含义 |
| --- | --- |
| `ENV_DIR` | 环境语料目录，默认是脚本同级的 `environment_mix/`，形如 `<id>/` 数据目录 + `<id>_step4_checkpoint.json` |
| `MODEL_PATH` | 本地模型权重目录 |
| `OUT` / `LOG_DIR` | 输出的 questions + rubrics JSON 及日志目录 |
| `TENSOR_PARALLEL` / `PORT` / `MAX_MODEL_LEN` | 模型服务参数 |
| `EXTRA_API_BASES` | 额外的同模型服务地址（逗号分隔），用来把请求摊到更多副本或更多机器上；留空就只用本机那一个 |
| `TARGET` | 总共造多少题（如 1000），在整个语料里随机铺开，够了就停；0 表示不限量 |
| `ENVS` / `CHAINS` / `ATTEMPTS` | 用多少环境、单个环境最多贡献几题、每个环境试几次游走 |
| `MIN_STEPS` / `MAX_STEPS` | 一道题至少/至多依赖多少次真实工具调用 |
| `WORKERS` / `SEED` | 并行环境数（每个环境同时只有一次模型调用在飞，所以并发量就是这个数）、随机种子 |

## 七个步骤

1. **分析**：模型读每个工具的 schema 与实现，给出它读什么、返回什么、是否改状态，以及依赖哪些工具——
   某个入参只能来自别的工具输出是**强依赖**，也能查库拿到就是**弱依赖**。
2. **建图**：工具是节点。强依赖是有向边；弱依赖和互不相关都是双向边，因为它们之间的先后顺序是自由的。
3. **游走**：按给定长度随机游走，偏好那些参数真的能对上的边，让链条倾向于把值往下传，而不是在无关调用之间乱跳。
4. **执行**：链条在该环境数据库的**私有副本**上真跑一遍。每个入参优先取上游某一步输出里同名的值（`paper_id`
   对上游的 `id` 也算同名），取不到就从**同一条记录**里取，保证一次调用里的 id 和其它字段属于同一个东西——
   参数拼自互不相关的记录，工具只会回 NOT_FOUND。必需参数没有真实值可用时这一步直接不调，绝不编造 `"unknown"`。
   回复是拒绝（error / not found / unauthorized）、是空的（有集合且全为空）、或与前面某次调用完全相同的，都丢弃。
   工具返回什么，什么就是标准答案。
5. **出题**：模型看着执行结果写出"用户当初会怎么问"，结果只用来知道有哪些值存在，**题面里不许出现执行结果的具体取值**。
6. **答案与 rubric**：模型据执行结果算出答案并写评分细则（字段集合一致性、类型合法性、与标准答案的值一致性；
   数值比较留合理容差）。执行结果不足以严格算出答案时，模型只回 `{"unanswerable": true}`，这道题就丢掉——
   宁可少一题，也不要一个用文档描述或常识补出来的标准答案。
7. **校验**：换一份干净副本重放同一条链。工具会给回复打上时钟戳（时间、耗时、每次新生成的 id），所以不是逐字节
   比对，而是**只保留两次运行一致的部分**再交给模型算答案——这样答案不可能依赖挂钟时间。稳定内容太少的链条直接丢弃。

## 输出

`OUT` 是一个 JSON 数组，每条：

```json
{
  "env_id": "0000000",
  "env_name": "...",
  "taxonomy": {"L1_name": "...", "L2_name": "...", "L3_name": "..."},
  "question": "题干",
  "final_answer": "标准答案",
  "rubrics": {"version": "1.0", "total_points": 100, "pass_threshold": 90,
              "evaluation_procedure": ["..."], "checks": [{"id": "C1", "points": 10, "type": "hard", "...": "..."}]},
  "tool_chain": [{"step": 1, "tool": "...", "arguments": {}, "observation": {}}],
  "n_steps": 5
}
```

`tool_chain` 里存的是**校验后的稳定观测**，即答案所依据的事实，可以照着重放复现。

注意：仓库自带的 `environment_mix/questions/*.json` 使用 `task` / `reference_answer` /
`grading_rubric`；本 Graph 脚本输出的是 `question` / `final_answer` / `rubrics` / `tool_chain`。
两者都是 question/rubric 数据，但 schema 不同。

给了 `TARGET` 时，环境顺序先按种子打散，单环境配额取 `ceil(2 × TARGET / 环境数)`（不超过 `CHAINS`），
所以题目会摊到整个语料上而不是把前几十个环境榨干；攒够就停，多出来的随机截断。配额按两倍均值算，
是因为大约一半的环境走不出可复现的链条，按均值算会打不满。

## 实测

`environment_mix` 全量 563 个环境跑一遍（Qwen3-14B，两台 8 卡 L20 拆成 4 个 TP=4 副本，`WORKERS=32`，
`TARGET=1000`）：

| | |
| --- | --- |
| 产出 | **602 题**，覆盖 274 / 563 个环境，横跨 20 个 L1 分类 |
| 链长 | 平均 3.9 次真实工具调用（3 步 288 题、4 步 166、5 步 94、6 步 41、7 步 14）|
| rubric | 平均 4.2 条检查项，无一条缺失 |
| 耗时 | 约 75 分钟 |

**`TARGET=1000` 打不满**：每个环境平均出 1.07 题，约一半的环境走不出可复现的链条（工具需要真实
凭证、或返回内容全是时钟派生的），语料吃完就停在实际产量上。要凑满 1000，把 `CHAINS` 上限提到 6-8
即可，代价是同一个环境里的题会因为工具集重叠而变相似。

## 三处实现上的注意

- 环境按**进程**并行，不是线程：工具在调用时通过进程级变量 `MCP_DB_DIR` 定位数据库，同进程内跑两个环境会互相读错数据。
- 每条链都在临时副本上执行，且执行进程会 `chdir` 进副本目录——有些工具不按 `MCP_DB_DIR` 写文件，不这么做
  会在当前目录里拉出一堆它自己的目录。写操作碰不到语料本身。
- `OUT` 每跑完一批环境就重写一次（先写 `.part` 再原子替换），所以跑几小时的任务被打断也不会白跑。
- checkpoint 中的 `implementation` 会通过 `exec` 执行。只运行可信语料，并在隔离进程或容器中执行；写工具始终
  应指向数据库副本，禁止传入生产凭证。
"""Graph-walk task synthesis: turn an environment into questions whose answers were executed, not written.

The pipeline is the one behind the shipped question bank, reduced to what it needs to be:

1. analyse a local model reads every tool's schema and implementation and reports, per tool, what it
reads and returns, whether it mutates the store, and which tools it depends on -- strongly
when an argument can only come from another tool's output, weakly when it could also be
looked up.
2. graph tools become nodes. A strong dependency is a directed edge, a weak one is bidirectional,
and tools with no relation are joined both ways: order between them is free.
3. walk a random walk of a given length, biased towards edges whose parameters actually match, so a
chain tends to carry a value forward rather than jumping between unrelated calls.
4. execute the chain runs against a private copy of the environment's own database. Each argument comes
from an earlier step's output where the names agree, otherwise from a single record of the
data, so the values in one call belong to the same thing. A call whose required argument has
nothing real behind it is not made at all; a reply that refuses, comes back empty, or repeats
an earlier call is dropped. What the tools return is the ground truth; no model is asked what
the answer should be.
5. design the model writes the question a user would have asked to get that chain run, seeing the
observations only to know which values exist -- never quoting them.
6. answer the model formats the answer from the observations and writes the rubric that grades it, or
declares the chain unable to answer, in which case the question is thrown away rather than
kept with a made-up answer.
7. verify the chain is replayed in a fresh copy and only what both runs agree on is kept, so an answer
never rests on the clock. A chain that fails to reproduce, or survives only as a shell, goes.

Everything configurable is passed in by the shell script that runs this; nothing here knows a path.
"""
import argparse
import json
import os
import random
import re
import shutil
import tempfile
import threading
import time
import urllib.request
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool

_print = threading.Lock()


def say(*a):
    with _print:
        print(*a, flush=True)


# --------------------------------------------------------------------------------------- local model

class Model:
    """A local chat model behind an OpenAI-compatible server (vLLM). Stdlib only, so nothing to install.

    Several servers may be given, comma separated: the same model served more than once, on more GPUs or
    more machines. Calls are spread over them, and a call that fails moves to the next one.
    """

    def __init__(self, base, name, timeout=600, retries=4):
        self.bases = [b.strip().rstrip("/") for b in base.split(",") if b.strip()]
        if not self.bases:
            raise ValueError("at least one model API base URL is required")
        self.name, self.timeout, self.retries = name, timeout, retries

    def chat(self, system, user, max_tokens=4096, temperature=0.3):
        body = {
            "model": self.name,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            # Qwen3 is a hybrid reasoning model; these tasks are extraction and writing, not puzzles
            "chat_template_kwargs": {"enable_thinking": False},
        }
        last = None
        order = random.sample(self.bases, len(self.bases))
        for i in range(self.retries):
            base = order[i % len(order)]
            try:
                req = urllib.request.Request(
                    f"{base}/chat/completions", method="POST",
                    data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    out = json.loads(r.read())
                text = out["choices"][0]["message"]["content"] or ""
                return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
            except Exception as e:
                last = e
                time.sleep(2 * (i + 1))
        raise RuntimeError(f"model call failed after {self.retries} tries: {last}")

    def chat_json(self, system, user, max_tokens=4096, temperature=0.2):
        return parse_json(self.chat(system, user, max_tokens, temperature))


def parse_json(text):
    """Take the JSON out of a reply that may be fenced or prefaced."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = t.find(opener), t.rfind(closer)
        if i >= 0 and j > i:
            try:
                return json.loads(t[i: j + 1])
            except Exception:
                continue
    raise ValueError(f"no JSON in reply: {text[:200]}")


# --------------------------------------------------------------------- environment loading and calling

def load_env(env_dir, env_id):
    with open(os.path.join(env_dir, f"{env_id}_step4_checkpoint.json"), encoding="utf-8") as f:
        ck = json.load(f)
    tools = [t for t in ck["data"]["ToolDesignAgent"]["tool_schemas"] if t.get("implementation")]
    files = {}
    for n in sorted(os.listdir(os.path.join(env_dir, env_id))):
        if n.endswith(".json"):
            try:
                with open(os.path.join(env_dir, env_id, n), encoding="utf-8") as f:
                    files[n] = json.load(f)
            except Exception:
                pass
    return ck, tools, files


def sandbox(env_dir, env_id):
    """A private copy of the database, so a chain that writes cannot touch the corpus.

    The working directory moves into the copy as well: not every tool honours MCP_DB_DIR for everything it
    writes, and one that creates a directory of its own next to wherever it was started from would otherwise
    litter the caller's directory. Environments run one per process, so moving the process is safe.
    """
    tmp = tempfile.mkdtemp(prefix="chain_")
    db = os.path.join(tmp, "database")
    shutil.copytree(os.path.join(env_dir, env_id), db)
    os.chdir(tmp)
    return tmp, db


def bind(tools, db):
    """Load the implementations against a database directory.

    They resolve MCP_DB_DIR when they are called, which is why environments are processed one per process:
    the variable is process-wide, and two environments sharing a process would read each other's records.
    """
    os.environ["MCP_DB_DIR"] = db
    ns, fns = {"__name__": "chainenv"}, {}
    for t in tools:
        try:
            exec(t["implementation"], ns)
        except Exception:
            continue
        fn = ns.get(re.sub(r"[^0-9A-Za-z_]", "_", t["name"]))
        if callable(fn):
            fns[t["name"]] = fn
    return fns


# ------------------------------------------------------------------------------ stage 1: what each tool is

ANALYZE_SYS = """你是一名【函数依赖与数据库操作分析器】。

给定一组工具的 schema、Python 实现代码，以及数据库文件概览，你要对每个函数做**确定性、可验证的静态分析**。
所有结论必须能直接从给定信息推导，不得推测、补全或假设。

对每个函数给出：

1. operation_type：只能是以下三者之一
- query：只读数据库，不改变任何状态
- mutation-only：写数据库（增/改/删），不返回有意义的数据
- mutation+query：既改状态，又返回查询结果或派生数据

2. input_arguments：函数定义中的全部入参名，必须与代码/schema 完全一致；无入参则为 []

3. output_arguments：函数**显式返回**的字段名。返回一个 dict 时列出它的键；不返回有意义内容则为 []。
不得臆造隐式输出。

4. dependent_function：本函数的入参依赖哪些其他函数的输出。
仅当同时满足以下条件才算依赖：某入参 a 的取值来源于函数 B 的某个输出字段 b，且 a 与 b 在语义上确为同一实体
（同一 id、同一条记录、同一字段值）。
依赖类型：
- strong：该入参**只能**来自 B 的输出，无法通过查库或常量获得；不先调用 B 就无法合法调用本函数
- weak：该入参可以来自 B 的输出，也可以通过查库或常量获得

只输出 JSON，不要任何解释：
{"tools": [{"function_name": "...", "operation_type": "query",
"input_arguments": ["..."], "output_arguments": ["..."],
"dependent_function": [{"function_name": "...", "dependent_type": "strong",
"dependent_output_argument": "..."}]}]}"""


def tool_brief(t, with_impl=True, impl_chars=1200):
    d = {"name": t["name"], "description": (t.get("description") or "")[:400],
         "parameters": t.get("parameters") or {}}
    s = json.dumps(d, ensure_ascii=False)
    if with_impl:
        s += "\nIMPLEMENTATION:\n" + (t.get("implementation") or "")[:impl_chars]
    return s


def analyse(model, tools, files, batch=12):
    """Ask the model what each tool reads, returns and depends on. Batched so long tool sets still fit."""
    summary = {
        n: (f"list of {len(v)} records, fields: {sorted(v[0])[:12]}"
            if isinstance(v, list) and v and isinstance(v[0], dict)
            else f"{type(v).__name__} with {len(v)} entries")
        for n, v in files.items()
    }
    out = {}
    for i in range(0, len(tools), batch):
        chunk = tools[i: i + batch]
        here = {t["name"] for t in chunk}
        others = [t["name"] for t in tools if t["name"] not in here][:60]
        user = (f"## 数据库文件概览\n{json.dumps(summary, ensure_ascii=False)}\n\n"
                f"## 工具（共 {len(chunk)} 个）\n" + "\n\n".join(tool_brief(t) for t in chunk) +
                f"\n\n此外，本环境中还存在这些工具，依赖分析时可以引用它们的名字：{others}")
        try:
            got = model.chat_json(ANALYZE_SYS, user, max_tokens=6000)
        except Exception:
            continue
        for rec in (got.get("tools") or []):
            n = rec.get("function_name")
            if n:
                out[n] = rec

    # a tool the model skipped still belongs in the graph, described by its own schema
    for t in tools:
        if t["name"] not in out:
            out[t["name"]] = {
                "function_name": t["name"],
                "operation_type": "query",
                "input_arguments": list(
                    ((t.get("parameters") or {}).get("properties") or {}).keys()),
                "output_arguments": [],
                "dependent_function": [],
            }
    return out


# ------------------------------------------------------------------------------------------- the graph

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def akin(a, b):
    """Whether two field names plausibly hold the same thing.

    The same value is named differently on either side of a call -- a tool takes paper_id and the record
    calls it id, a tool takes name and the record calls it package_name. Matching only exactly leaves a
    chain unable to pass anything along, and every call then arrives with an argument nothing stands behind.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    return len(a) >= 2 and len(b) >= 2 and (a.endswith(b) or b.endswith(a))


def param_match(a, b, analysis):
    """Output fields of a that can serve as input arguments of b."""
    outs = (analysis.get(a) or {}).get("output_arguments") or []
    ins = (analysis.get(b) or {}).get("input_arguments") or []
    pairs = []
    for o in outs:
        no = norm(o)
        for i in ins:
            ni = norm(i)
            if not no or not ni:
                continue
            hit = (no == ni
                   or ("id" in no and "id" in ni
                       and (not no.replace("id", "") or not ni.replace("id", "")
                            or no.replace("id", "") == ni.replace("id", "")))
                   or no in ni or ni in no)
            if hit:
                pairs.append((o, i))
    return pairs


def build_graph(analysis):
    """strong: one direction. weak and independent: both, so the walk can order them freely."""
    names = list(analysis)
    edges = {n: {} for n in names}
    for n in names:
        for dep in (analysis[n].get("dependent_function") or []):
            d = dep.get("function_name")
            if d not in edges or d == n:
                continue
            if dep.get("dependent_type") == "strong":
                edges[d][n] = "strong"
            else:
                edges[d].setdefault(n, "weak")
                edges[n].setdefault(d, "weak")
    for a in names:
        for b in names:
            if a != b and b not in edges[a] and a not in edges[b]:
                edges[a][b] = edges[b][a] = "independent"
    return edges


WEIGHT = {"strong": 3.0, "weak": 2.0, "independent": 1.0}


def walk(edges, analysis, length, rng):
    """Random walk, preferring successors whose parameters the current tool can actually supply."""
    if not edges:
        return []
    starts = [
        n for n in edges
        if (analysis.get(n) or {}).get("output_arguments")
        and not any(edges[p].get(n) == "strong" for p in edges)
    ]
    cur = rng.choice(starts or list(edges))
    seq = [cur]
    for _ in range(length - 1):
        succ = list(edges[cur])
        if not succ:
            break
        matched = [(s, param_match(cur, s, analysis)) for s in succ]
        matched = [(s, m) for s, m in matched if m]
        pool = [s for s, _ in matched] or succ
        bonus = {s: len(m) for s, m in matched}
        weights = [WEIGHT.get(edges[cur][s], 1.0) + bonus.get(s, 0) for s in pool]
        cur = rng.choices(pool, weights=weights, k=1)[0]
        seq.append(cur)
    return seq


# ------------------------------------------------------------------------------- executing a chain

def scalar(v):
    return isinstance(v, (str, int, float)) and not isinstance(v, bool)


def records(files, cap=4000):
    """Every record the environment holds, flattened to its scalar fields.

    A call takes its arguments from one record rather than from the data at large, so an id and the values
    that accompany it belong to the same thing. Arguments assembled from unrelated records name a thing
    that does not exist, and the tool answers NOT_FOUND.
    """
    out = []

    def visit(v, depth=0):
        if depth > 4 or len(out) >= cap:
            return
        if isinstance(v, dict):
            flat = {norm(k): x for k, x in v.items() if scalar(x)}
            if flat:
                out.append(flat)
            for x in v.values():
                visit(x, depth + 1)
        elif isinstance(v, list):
            for x in v[:200]:
                visit(x, depth + 1)

    visit(files)
    return out


def value_pool(recs):
    """The values behind each field name, for arguments no single record can supply."""
    pool = {}
    for r in recs:
        for k, v in r.items():
            xs = pool.setdefault(k, [])
            if len(xs) < 12 and v not in xs:
                xs.append(v)
    return pool


def lookup(name, source):
    """What a field name refers to in a record or in the pooled values, allowing for renaming."""
    n = norm(name)
    if n in source:
        return source[n]
    for k in source:
        if akin(n, k):
            return source[k]
    return None


def deep_find(obj, key, loose=False, depth=0):
    """First value stored under a matching field name, wherever it sits in a result."""
    want = norm(key)
    if depth > 5:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if scalar(v) and (norm(k) == want or (loose and akin(want, norm(k)))):
                return v
        for v in obj.values():
            got = deep_find(v, key, loose, depth + 1)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in obj[:20]:
            got = deep_find(v, key, loose, depth + 1)
            if got is not None:
                return got
    return None


def choose_record(recs, wanted, rng, tries=60):
    """The record that can supply the most of what a call requires."""
    if not recs:
        return None
    if not wanted:
        return rng.choice(recs)
    best, score = None, -1
    for r in rng.sample(recs, min(tries, len(recs))):
        s = sum(1 for w in wanted if lookup(w, r) is not None)
        if s > score:
            best, score = r, s
        if score == len(wanted):
            break
    return best


def make_args(tool, prior, recs, pool, rng, optional_p=0.0):
    """Arguments for one call: whatever an earlier step produced, then one record of the environment's data.

    Returns None when a required argument has nothing real behind it. Filling it in anyway -- an id of
    "unknown", a token of 1 -- only buys a refusal, and a chain of refusals is not a question.
    """
    props = ((tool.get("parameters") or {}).get("properties")) or {}
    required = set(((tool.get("parameters") or {}).get("required")) or [])
    upstream = {}
    for name in props:
        for obs in reversed(prior):  # most recent step first
            val = deep_find(obs, name)
            if val is None:
                val = deep_find(obs, name, loose=True)
            if val is not None:
                upstream[name] = val
                break
    rec = choose_record(recs, [n for n in props if n in required and n not in upstream], rng)

    args = {}
    for name, spec in props.items():
        spec = spec if isinstance(spec, dict) else {}
        val = upstream.get(name)
        if val is None and rec:
            val = lookup(name, rec)
        if val is None:
            xs = lookup(name, pool)
            if xs:
                val = rng.choice(xs)
        if val is None and spec.get("enum"):
            val = rng.choice(spec["enum"])
        if val is None:
            if name in required:
                return None
            continue
        if name in required or rng.random() < optional_p:
            args[name] = val
    return args


REFUSAL = re.compile(r"not found|not exist|unknown|invalid|malformed|unauthori|forbidden|missing|"
                     r"unavailable|denied|failed|failure", re.I)


def refused(obs):
    """Whether a reply reports a refusal rather than data.

    Tools say so in their own way: an error field, a status of "error", a message about something not being
    found. A refusal is a fact about the arguments, not about the environment, and grading an answer on one
    teaches nothing.
    """
    if not isinstance(obs, dict):
        return False
    for k, v in obs.items():
        n = norm(k)
        if n in ("error", "errors") and v:
            return True
        if n in ("status", "code", "result") and isinstance(v, str) and REFUSAL.search(v):
            return True
        if n in ("status", "code", "result") and isinstance(v, str) and v.lower() in ("error", "failed"):
            return True
        if n in ("ok", "success") and v is False:
            return True
        if n in ("message", "detail", "reason") and isinstance(v, str) and REFUSAL.search(v):
            return True
    return False


def hollow(obs):
    """Whether a reply ran but carries no data: it has collections, and every one of them is empty."""
    seen = []

    def visit(v, depth=0):
        if depth > 4:
            return
        if isinstance(v, dict):
            for x in v.values():
                visit(x, depth + 1)
        elif isinstance(v, list):
            seen.append(v)
            for x in v[:20]:
                visit(x, depth + 1)

    visit(obs)
    return bool(seen) and all(not s for s in seen)


def run_chain(seq, fns, by_name, recs, pool, rng, draws=4):
    """Execute the walk.

    Each call gets a few draws at arguments; the first reply that is neither a refusal nor empty is what the
    step observed. A call that cannot be made honestly, or keeps coming back empty, is left out -- what
    remains is a chain that really ran and really returned something.
    """
    steps, prior, seen = [], [], set()
    for name in seq:
        fn = fns.get(name)
        if not fn:
            continue
        for d in range(draws):
            args = make_args(by_name[name], prior, recs, pool, rng, optional_p=0.0 if d == 0 else 0.4)
            if args is None:
                break
            call = (name, json.dumps(args, sort_keys=True, default=str))
            if call in seen:                # the same call again observes the same thing: it adds nothing,
                continue                    # and a chain padded with repeats invites an invented question
            try:
                result = fn(**args)
            except Exception:
                continue
            try:
                text = json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                break
            if result is None or len(text) < 10 or refused(result) or hollow(result):
                continue
            seen.add(call)
            steps.append({"tool": name, "arguments": args, "observation": result})
            prior.append(result)
            break
    return steps


DROPPED = object()


def stable_part(a, b):
    """What two runs of the same call agree on.

    Tools stamp their replies with the clock -- a timestamp, an elapsed time, an id minted per call -- so
    two runs are never byte-identical even though the records they report are the same. Keeping only what
    both runs produced leaves the part of the observation an answer may rest on, and drops the part that
    would make a graded answer expire.
    """
    if isinstance(a, dict) and isinstance(b, dict):
        out = {}
        for k in a:
            if k not in b:
                continue
            v = stable_part(a[k], b[k])
            if v is not DROPPED:
                out[k] = v
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return DROPPED
        out = []
        for x, y in zip(a, b):
            v = stable_part(x, y)
            out.append(None if v is DROPPED else v)
        return out
    return a if a == b else DROPPED


def substance(obj, depth=0):
    """How many concrete values survived, so a chain reduced to empty shells can be recognised."""
    if depth > 6:
        return 0
    if isinstance(obj, dict):
        return sum(substance(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        return sum(substance(v, depth + 1) for v in obj[:50])
    return 1 if obj not in (None, "", [], {}) else 0


def replay(env_dir, env_id, tools, steps, keep_ratio=0.6):
    """Replay the chain in a fresh copy and keep what both runs agree on.

    Returns the steps with their stable observations, or None when the chain does not reproduce: a call that
    now fails, a reply that lost its shape, or one that survived only as a shell. What a reply loses between
    two runs is the clock and the ids minted per call, which is little; a reply that loses most of itself
    was mostly volatile, and an answer resting on it would expire.
    """
    old_cwd = os.getcwd()
    tmp, db = sandbox(env_dir, env_id)
    try:
        fns = bind(tools, db)
        out = []
        for s in steps:
            fn = fns.get(s["tool"])
            if not fn:
                return None
            try:
                again = fn(**s["arguments"])
            except Exception:
                return None
            keep = stable_part(s["observation"], again)
            if keep is DROPPED:
                return None
            held, was = substance(keep), substance(s["observation"])
            if held < 1 or held < keep_ratio * was:
                return None
            out.append({**s, "observation": keep})
        return out
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------------- stages 2 and 3: task, answer

TASK_SYS = """你是一名【任务设计专家】。

根据给定的工具定义、已执行的工具调用链及其执行结果，设计一个自然、真实、需要复杂推理或计算的用户任务。
你设计的是"用户会问的问题"，不是操作说明或解题步骤。

必须遵守：

1. 充分利用整条工具链：任务的隐含解决路径应与调用顺序一致，每一步的输出都要在任务中有意义。

2. 必须需要复杂推理或计算，不能是简单的"查一下并返回"。至少包含以下之一：多步筛选与对比、数值计算
   （汇总/平均/比例/排名）、条件判断、跨多个结果的数据整合。最终答案必须依赖多个工具的输出才能得出。

3. 任务条件清晰、结果确定唯一，不存在多解。

4. **绝对不能出现执行结果里的具体取值**（设计任务时不该知道结果）。可以使用调用的输入参数值，因为它们是条件。

5. 像真实用户一样用一段话提问，有业务场景，目标导向。不要提字段名、工具名、schema 等技术细节。
   不要列步骤（"先……再……"），不要描述解题过程。

6. 必须说明期望的输出格式及每个字段含义，且要简单可校验：字段不超过 5 个，优先单个值，其次 2-4 个字段的
   简单对象，再次结构简单的列表。不要复杂嵌套。

7. 只能围绕执行结果里**真实存在的字段**提问。不要引入执行结果之外的判断维度（是否被引用、是否流行、是否推荐
   这类无从判定的属性），否则答案只能靠猜。

只输出任务描述本身，不要任何前后缀、标题或解释。"""

ANSWER_SYS = """你是一名【基于工具执行轨迹的任务求解器 + 评分细则生成器】。

给定工具定义、任务定义，以及**已真实执行**的工具调用链及其执行结果，你要：
1. 严格依据执行结果计算出任务要求的答案（final_answer）。执行结果是唯一事实来源，禁止臆造数据。
2. 生成一份可客观评估的评分细则（rubrics），用于比较候选答案与标准答案。

只输出一个 JSON 对象，仅含 final_answer 与 rubrics 两个顶层字段，不得输出推理过程：

{"final_answer": <严格符合任务定义输出格式的答案>,
 "rubrics": {
   "version": "1.0", "total_points": 100, "pass_threshold": 90,
   "evaluation_procedure": ["自然语言描述评估顺序，但必须可落实为检查项"],
   "checks": [{"id": "C1", "name": "检查项名称", "points": 10, "type": "hard",
               "how_to_judge": "如何客观比较候选答案与标准答案",
               "pass_condition": "通过条件（布尔判定）",
               "fail_examples": ["典型失败示例"]}],
   "notes": ["必要补充，必须客观"]}}

checks 至少覆盖这些维度：
A) 字段集合一致性（hard）：字段齐全、无多余字段
B) 字段类型与取值合法性（hard）：类型匹配，枚举值在允许集合内，数值范围合理
C) 与标准答案的值一致性（hard 为主）

数值容差要求（重要）：数值比较不能过于严格，精确到小数点后一位甚至个位即可，不要求 1e-6 这类高精度。
例如标准答案 57.00、候选答案 56.97 应判为正确。非数值字段则要求严格相等。

判定：所有 hard 检查通过且总分 ≥ pass_threshold 时，候选答案正确。

例外：如果执行结果不足以严格算出任务要求的答案——缺少必需的数据、需要猜测、或者任务问的东西这条调用链
根本没取到——只输出 {"unanswerable": true}，不要用常识或文档描述去补。编造的标准答案比没有答案更糟。"""


def chain_view(steps):
    return json.dumps([{"step": i + 1, "tool": s["tool"], "arguments": s["arguments"],
                        "observation": json.loads(json.dumps(s["observation"], default=str))}
                       for i, s in enumerate(steps)], ensure_ascii=False)[:14000]


def design_task(model, tools_used, steps):
    user = (f"## 工具定义\n" + "\n\n".join(tool_brief(t, with_impl=False) for t in tools_used) +
            f"\n\n## 已执行的工具调用链\n{chain_view(steps)}")
    return model.chat(TASK_SYS, user, max_tokens=1200, temperature=0.7).strip()


def answer_holds(ans):
    """Whether an answer says something. A question whose answer is "nothing was found" grades nothing."""
    if ans is None:
        return False
    if isinstance(ans, str):
        return len(ans.strip()) > 1 and not REFUSAL.search(ans)
    if isinstance(ans, dict):
        # the model sometimes puts its own refusal inside the answer instead of at the top level
        return bool(ans) and not ans.get("unanswerable") and not refused(ans)
    if isinstance(ans, (list, tuple)):
        return bool(ans)
    return True


def answer_and_rubric(model, tools_used, task, steps):
    user = (f"## 工具定义\n" + "\n\n".join(tool_brief(t, with_impl=False) for t in tools_used) +
            f"\n\n## 任务定义\n{task}\n\n## 工具调用链和执行结果\n{chain_view(steps)}")
    got = model.chat_json(ANSWER_SYS, user, max_tokens=4000)
    if got.get("unanswerable"):
        raise ValueError("the chain does not answer the task it was given")
    if "final_answer" not in got or not isinstance(got.get("rubrics"), dict):
        raise ValueError("reply lacks final_answer or rubrics")
    return got


# ------------------------------------------------------------------------------------------- driver

def dump(results, out):
    """Write the question bank. Called after every batch too, so a long run survives being interrupted."""
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    tmp = out + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out)


def build_env(model, args, env_id, rng):
    ck, tools, files = load_env(args.env_dir, env_id)
    if len(tools) < 2:
        return []
    by_name = {t["name"]: t for t in tools}
    analysis = analyse(model, tools, files)
    edges = build_graph(analysis)
    recs = records(files)
    pool = value_pool(recs)

    old_cwd = os.getcwd()
    tmp, db = sandbox(args.env_dir, env_id)
    try:
        fns = bind(tools, db)
        if not fns:
            return []
        chains = []
        for _ in range(args.attempts):
            if len(chains) >= args.chains:
                break
            length = rng.randint(args.min_steps, args.max_steps)
            steps = run_chain(walk(edges, analysis, length, rng), fns, by_name, recs, pool, rng)
            if len(steps) < args.min_steps:
                continue
            if len({s["tool"] for s in steps}) < min(3, args.min_steps):
                continue                    # a chain that leans on one or two tools is a lookup, not a task
            if any(json.dumps(steps, sort_keys=True, default=str) ==
                   json.dumps(c, sort_keys=True, default=str) for c in chains):
                continue
            chains.append(steps)
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp, ignore_errors=True)

    out = []
    for chain in chains:
        steps = replay(args.env_dir, env_id, tools, chain)
        if not steps:
            continue
        used = [by_name[s["tool"]] for s in steps]
        try:
            task = design_task(model, used, steps)
            got = answer_and_rubric(model, used, task, steps)
        except Exception:
            continue
        if len(task) < 40 or not answer_holds(got["final_answer"]):
            continue
        out.append({
            "env_id": env_id,
            "env_name": (ck.get("metadata") or {}).get("name", ""),
            "taxonomy": (ck.get("metadata") or {}).get("taxonomy", {}),
            "question": task,
            "final_answer": got["final_answer"],
            "rubrics": got["rubrics"],
            "tool_chain": [{"step": i + 1, "tool": s["tool"], "arguments": s["arguments"],
                            "observation": s["observation"]} for i, s in enumerate(steps)],
            "n_steps": len(steps),
        })
    return out


def main():
    p = argparse.ArgumentParser(description="graph-walk question and rubric synthesis")
    p.add_argument("--env_dir", required=True, help="corpus directory holding <id>/ and <id>_step4_checkpoint.json")
    p.add_argument("--out", required=True, help="output json file")
    p.add_argument("--api_base", required=True, help="OpenAI-compatible base url of the local model server")
    p.add_argument("--model", required=True, help="model name as served")
    p.add_argument("--target", type=int, default=0,
                   help="how many questions in total, drawn across the corpus; 0 for no limit")
    p.add_argument("--envs", type=int, default=0, help="how many environments, 0 for all")
    p.add_argument("--chains", type=int, default=4, help="questions per environment (a ceiling)")
    p.add_argument("--attempts", type=int, default=40, help="walks tried per environment")
    p.add_argument("--min_steps", type=int, default=3)
    p.add_argument("--max_steps", type=int, default=8)
    p.add_argument("--workers", type=int, default=32)
    p.add_argument("--seed", type=int, default=624)
    args = p.parse_args()
    # absolute, because the processes that execute chains move into their sandbox to keep stray writes there
    args.env_dir, args.out = os.path.abspath(args.env_dir), os.path.abspath(args.out)

    ids = sorted(f[: -len("_step4_checkpoint.json")] for f in os.listdir(args.env_dir)
                 if f.endswith("_step4_checkpoint.json"))
    rng0 = random.Random(args.seed)
    if args.envs:
        ids = rng0.sample(ids, min(args.envs, len(ids)))
    rng0.shuffle(ids)          # a target is met from a random part of the corpus, not from its first ids

    if args.target:
        # Spread the target over the whole corpus rather than exhausting the first environments. The quota
        # aims at twice the average because a good half of the environments yield no reproducible chain at
        # all, and --chains stays the ceiling any single environment may contribute.
        args.chains = max(1, min(args.chains, -(-2 * args.target // max(1, len(ids)))))

    model = Model(args.api_base, args.model)
    say(f"{len(ids)} environments, up to {args.chains} questions each, {args.workers} workers"
        + (f", stopping at {args.target} questions" if args.target else ""))

    results, done = [], 0
    # Environments run one per process: the tools locate their database through a process-wide variable, so
    # two environments in one process would read each other's records. Work goes out in batches because the
    # code being executed is generated, and a tool that takes its process down with it would otherwise break
    # the pool for everything still queued.
    step = max(args.workers * 4, args.workers)
    for start in range(0, len(ids), step):
        if args.target and len(results) >= args.target:
            say(f"  reached {len(results)} questions; {len(ids) - start} environments left untouched")
            break
        batch = ids[start: start + step]
        try:
            with ProcessPoolExecutor(max_workers=args.workers) as ex:
                futs = {ex.submit(build_env, model, args, i,
                                  random.Random(args.seed + zlib.crc32(i.encode()))): i for i in batch}
                for fut in as_completed(futs):
                    env_id = futs[fut]
                    try:
                        got = fut.result()
                    except Exception as e:
                        got = []
                        say(f"  {env_id} failed: {type(e).__name__}: {str(e)[:120]}")
                    results += got
                    done += 1
                    say(f"  [{done}/{len(ids)}] {env_id}: {len(got)} questions (total {len(results)})")
        except BrokenProcessPool:
            done += len(batch)
            say(f"  a tool brought down its worker; {len(batch)} environments in this batch were skipped")
        dump(results, args.out)

    if args.target and len(results) > args.target:
        random.Random(args.seed).shuffle(results)      # trim without favouring whoever finished first
        results = results[: args.target]
    results.sort(key=lambda r: (r["env_id"], r["question"][:40]))
    dump(results, args.out)

    covered = len({r["env_id"] for r in results})
    steps = sum(r["n_steps"] for r in results) / max(1, len(results))
    say(f"\n{len(results)} questions over {covered}/{len(ids)} environments, "
        f"{steps:.1f} tool calls per question on average -> {args.out}")


if __name__ == "__main__":
    main()
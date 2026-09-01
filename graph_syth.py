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

ANALYZE_SYS = """You are a function dependency and database operation analyzer.

Given a set of tool schemas, Python implementations, and an overview of the database files, perform a deterministic and verifiable static analysis of every function.
Every conclusion must follow directly from the provided information. Do not speculate, fill in missing details, or make assumptions.

For each function, provide:

1. operation_type: exactly one of the following values
- query: reads the database without changing any state
- mutation-only: writes to the database (create/update/delete) without returning meaningful data
- mutation+query: changes state and also returns query results or derived data

2. input_arguments: all parameter names from the function definition, matching the code/schema exactly; use [] when there are no parameters

3. output_arguments: field names explicitly returned by the function. If it returns a dict, list its keys; use [] when it returns no meaningful content.
Do not invent implicit outputs.

4. dependent_function: other functions whose outputs supply this function's inputs.
Record a dependency only when an input argument a receives its value from an output field b of function B and a and b semantically refer to the same entity
(the same ID, record, or field value).
Dependency types:
- strong: the input can only be obtained from B's output and cannot be obtained from the database or a constant; this function cannot be called validly before B
- weak: the input can be obtained either from B's output or from the database or a constant

Output JSON only, with no explanation:
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
        user = (f"## Database File Overview\n{json.dumps(summary, ensure_ascii=False)}\n\n"
                f"## Tools ({len(chunk)} total)\n" + "\n\n".join(tool_brief(t) for t in chunk) +
                f"\n\nThe following tools also exist in this environment; you may reference their names when analyzing dependencies: {others}")
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

TASK_SYS = """You are a task design expert.

Using the provided tool definitions, executed tool-call chain, and execution results, design a natural and realistic user task that requires complex reasoning or calculation.
Design a question that a user would ask, not operating instructions or solution steps.

You must follow these rules:

1. Make full use of the entire tool chain: the task's implicit solution path must match the call order, and every step's output must meaningfully contribute to the task.

2. Require complex reasoning or calculation rather than a simple lookup-and-return operation. Include at least one of the following: multi-step filtering and comparison, numerical calculation
   (aggregation/average/ratio/ranking), conditional judgment, or integration of data across multiple results. The final answer must depend on outputs from multiple tools.

3. State clear conditions and ensure there is exactly one determinate result, with no multiple valid answers.

4. Never include concrete values from the execution results; those results should not be known when designing the task. Input argument values from the calls may be used because they are task conditions.

5. Ask the question as one goal-oriented paragraph in a realistic business context. Do not mention field names, tool names, schemas, or other technical details.
   Do not list steps or describe the solution process.

6. Specify the expected output format and the meaning of each field, keeping it simple and easy to verify: use no more than five fields. Prefer a single value, then a simple object with two to four fields, then a simply structured list. Avoid complex nesting.

7. Ask only about fields that actually exist in the execution results. Do not introduce dimensions that cannot be determined from those results, such as whether something is cited, popular, or recommended; otherwise the answer would require guessing.

Output only the task description, with no prefix, title, suffix, or explanation."""

ANSWER_SYS = """You are a task solver and rubric generator based on tool execution traces.

Given the tool definitions, task definition, and the tool-call chain and results that were actually executed, you must:
1. Calculate the answer required by the task (final_answer) strictly from the execution results. The results are the sole source of truth; do not invent data.
2. Generate an objectively assessable rubric (rubrics) for comparing a candidate answer with the reference answer.

Output exactly one JSON object containing only the top-level fields final_answer and rubrics. Do not output any reasoning:

{"final_answer": <an answer that strictly follows the output format defined by the task>,
 "rubrics": {
   "version": "1.0", "total_points": 100, "pass_threshold": 90,
   "evaluation_procedure": ["Describe the evaluation order in natural language, but make every step implementable as a concrete check"],
   "checks": [{"id": "C1", "name": "Check name", "points": 10, "type": "hard",
               "how_to_judge": "How to compare the candidate answer with the reference answer objectively",
               "pass_condition": "Passing condition as a Boolean decision",
               "fail_examples": ["Representative failure example"]}],
   "notes": ["Any necessary addition, stated objectively"]}}

The checks must cover at least these dimensions:
A) Field-set consistency (hard): all required fields are present and there are no extra fields
B) Field types and value validity (hard): types match, enum values belong to the allowed set, and numeric values fall within a reasonable range
C) Value consistency with the reference answer (primarily hard checks)

Numeric tolerance requirement (important): numeric comparisons must not be excessively strict. Precision to one decimal place or even the nearest integer is sufficient; do not require high precision such as 1e-6.
For example, if the reference answer is 57.00, a candidate answer of 56.97 should be accepted. Nonnumeric fields must match exactly.

Decision rule: a candidate answer is correct when all hard checks pass and the total score is at least pass_threshold.

Exception: if the execution results are insufficient to calculate the required answer exactly—because required data is missing, guessing would be necessary, or the call chain never retrieved what the task asks for—output only {"unanswerable": true}. Do not fill gaps with general knowledge or documentation. An invented reference answer is worse than no answer."""


def chain_view(steps):
    return json.dumps([{"step": i + 1, "tool": s["tool"], "arguments": s["arguments"],
                        "observation": json.loads(json.dumps(s["observation"], default=str))}
                       for i, s in enumerate(steps)], ensure_ascii=False)[:14000]


def design_task(model, tools_used, steps):
    user = (f"## Tool Definitions\n" + "\n\n".join(tool_brief(t, with_impl=False) for t in tools_used) +
            f"\n\n## Executed Tool-Call Chain\n{chain_view(steps)}")
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
    user = (f"## Tool Definitions\n" + "\n\n".join(tool_brief(t, with_impl=False) for t in tools_used) +
            f"\n\n## Task Definition\n{task}\n\n## Tool-Call Chain and Execution Results\n{chain_view(steps)}")
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
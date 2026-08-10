"""Harness 评测主驱动脚本 (跨平台 Win/Linux)。

用法示例:
  python harness-runner.py --agent kiri --level 1                # 只跑 L1, 每任务默认 5 次
  python harness-runner.py --agent kiri --runs 5                 # 全 26 任务, 每任务 5 次取平均
  python harness-runner.py --agent openclaw --runs 5             # 用 OpenClaw 驱动
  python harness-runner.py --selftest                            # 自检: 不调 agent, 只验证任务定义

兼容的 agent 后端:
  - kiri      : kiri.exe -p <prompt> --mode json ... (NDJSON 输出, message_end 事件含 usage)
  - openclaw  : openclaw agent exec --cwd <ws> --message-file <file> --json (单个 JSON 输出)

每个任务流程: setup(ws) -> agent.run(ws, instruction) -> verify(ws) -> 记录通过/token/耗时
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from tasks.harness_tasks import ALL_TASKS, get_task, list_tasks

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent


def default_kiri_exe() -> str:
    """kiri 可执行文件: 优先仓库父目录 output/kiri(.exe), 否则回退到 PATH 中的 kiri。"""
    exe_name = "kiri.exe" if sys.platform == "win32" else "kiri"
    p = PROJECT_ROOT / "output" / exe_name
    if p.exists():
        return str(p)
    return exe_name


# ---------------------------------------------------------------------------
# 运行结果
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    task_id: str = ""
    level: int = 0
    capability: str = ""
    run_index: int = 0
    passed: bool = False
    failures: list = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cache: int = 0
    duration_s: float = 0.0
    rc: int = -1
    error: str = ""

    @property
    def tokens_total(self) -> int:
        return self.tokens_in + self.tokens_out + self.tokens_cache


# ---------------------------------------------------------------------------
# Agent 适配器
# ---------------------------------------------------------------------------

def _resolve_cmd(exe: str):
    """返回可直接交给 subprocess 的命令列表, 处理 .cmd/.bat 包装。"""
    if not os.path.isabs(exe):
        found = shutil.which(exe)
        if not found:
            return None
        exe = found
    if sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", exe]
    return [exe]


def _pick(d: dict, *keys, default=0):
    """容错地从 dict 里取第一个存在的键。"""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _parse_usage(usage: dict) -> tuple:
    """解析 usage -> (tokens_in, tokens_out, tokens_cache)。兼容多种键名。"""
    if not isinstance(usage, dict):
        return 0, 0, 0
    tin = _pick(usage, "input", "inputTokens", "promptTokens", "prompt_tokens")
    tout = _pick(usage, "output", "outputTokens", "completionTokens", "completion_tokens")
    tcache = _pick(usage, "cacheRead", "cache_read", "cachedTokens", "inputCacheRead")
    return tin, tout, tcache


class AgentAdapter:
    """agent 驱动抽象: run(ws, instruction, timeout) -> RunResult"""

    def __init__(self, exe: str):
        self.exe = exe
        self.cmd = _resolve_cmd(exe)
        if self.cmd is None:
            raise SystemExit(
                f"[ERROR] 找不到可执行文件: {exe!r}\n"
                f"  请用 --agent-path 指定路径, 或在 PATH 中加入该命令。"
            )

    def run(self, ws: Path, instruction: str, timeout: int) -> RunResult:
        raise NotImplementedError


class KiriAdapter(AgentAdapter):
    """kiri.exe -p <prompt> --mode json --no-session --no-approve --tools ..."""

    DEFAULT_TOOLS = "read,bash,edit,write,grep,find,ls"

    def __init__(self, exe: str, tools: str = DEFAULT_TOOLS,
                 provider: str | None = None, model: str | None = None,
                 api_key: str | None = None):
        super().__init__(exe)
        self.tools = tools
        # 未显式指定的模型配置: 从 kiri-data/console/config.json 自动加载
        conf = self._load_config(exe)
        self.provider = provider or conf.get("provider")
        self.model = model or conf.get("model")
        self.api_key = api_key or conf.get("api_key")

    @staticmethod
    def _load_config(exe: str) -> dict:
        """读取 kiri 的 console config (kiri-data/console/config.json), 提取模型配置。

        console 界面里的 provider 名 (如 opencode-zen) 是自定义注册名,
        CLI 模式需要 kiri 内置的 provider id (如 opencode), 这里做映射。
        """
        # console 自定义 provider 名 -> kiri 内置 provider id
        PROVIDER_MAP = {
            "opencode-zen": "opencode",
            "opencode-go": "opencode-go",
        }
        candidates = []
        exe_dir = Path(exe).resolve().parent
        for root in (exe_dir, PROJECT_ROOT, Path.cwd()):
            candidates.append(root / "kiri-data" / "console" / "config.json")
        for p in candidates:
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    m = data.get("model") or {}
                    return {
                        "provider": PROVIDER_MAP.get(m.get("provider"), m.get("provider")),
                        "model": m.get("model"),
                        "api_key": m.get("apiKey"),
                    }
                except Exception:
                    pass
        return {}

    def run(self, ws: Path, instruction: str, timeout: int) -> RunResult:
        res = RunResult()
        cmd = self.cmd + [
            "-p", instruction,
            "--mode", "json",
            "--no-session",
            "--no-approve",
            "--tools", self.tools,
        ]
        if self.provider:
            cmd += ["--provider", self.provider]
        if self.model:
            cmd += ["--model", self.model]
        if self.api_key:
            cmd += ["--api-key", self.api_key]
        t0 = time.time()
        try:
            p = subprocess.run(cmd, cwd=str(ws), capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=timeout, creationflags=0)
            res.rc = p.returncode
            out = p.stdout or ""
            res.error = (p.stderr or "")[-500:]
        except subprocess.TimeoutExpired as e:
            res.rc = -2
            res.error = f"timeout after {timeout}s"
            out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            return self._finalize(res, ws, out, timeout, t0)

        # 解析 NDJSON: usage 在 message_end.message.usage (每轮 assistant 消息累加)
        tokens_in = tokens_out = tokens_cache = 0
        final_text = ""
        for line in out.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(evt, dict) or evt.get("type") != "message_end":
                continue
            msg = evt.get("message") or {}
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            usage = msg.get("usage")
            if isinstance(usage, dict):
                ti, to, tc = _parse_usage(usage)
                # reasoning 属于输出消耗的一部分
                to += _pick(usage, "reasoning", "thinking")
                tokens_in += ti
                tokens_out += to
                tokens_cache += tc
            # 提取最终文本回复 (content 块里的 text)
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                        final_text = block["text"]
        res.tokens_in, res.tokens_out, res.tokens_cache = tokens_in, tokens_out, tokens_cache
        res.final_text = final_text or out[-2000:]
        return self._finalize(res, ws, out, timeout, t0)

    def _finalize(self, res: RunResult, ws, out, timeout, t0):
        res.duration_s = round(time.time() - t0, 2)
        return res


class OpenClawAdapter(AgentAdapter):
    """openclaw agent exec --cwd <ws> --message-file <file> --json

    输出: {ok, status, final, payloads, usage, model, provider, sessionId, error}
    退出码: 0=成功, 1=错误, 2=超时
    """

    def run(self, ws: Path, instruction: str, timeout: int) -> RunResult:
        res = RunResult()
        prompt_file = Path(ws) / "_hb_prompt.txt"
        prompt_file.write_text(instruction, encoding="utf-8")
        cmd = self.cmd + [
            "agent", "exec",
            "--cwd", str(ws),
            "--message-file", str(prompt_file),
            "--json",
        ]
        t0 = time.time()
        out = ""
        try:
            p = subprocess.run(cmd, cwd=str(ws), capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=timeout, creationflags=0)
            res.rc = p.returncode
            out = p.stdout or ""
            res.error = (p.stderr or "")[-500:]
        except subprocess.TimeoutExpired as e:
            res.rc = -2
            res.error = "timeout (openclaw default 600s)"
            res.duration_s = round(time.time() - t0, 2)
            return res
        res.duration_s = round(time.time() - t0, 2)

        # 解析单 JSON (兼容纯 JSON / 前后有日志)
        data = None
        for cand in (out, out + p.stderr):
            try:
                data = json.loads(cand)
                break
            except json.JSONDecodeError:
                pass
        if data is None:
            start = out.find("{")
            if start >= 0:
                try:
                    data = json.loads(out[start:])
                except json.JSONDecodeError:
                    pass
        if data is None:
            res.error = (res.error or "") + f" | 无法解析 openclaw JSON 输出: {out[:300]}"
            return res

        res.tokens_in, res.tokens_out, res.tokens_cache = _parse_usage(data.get("usage") or {})
        res.final_text = data.get("final") or data.get("response") or out[-2000:]
        if data.get("error"):
            res.error = (res.error + " | " + str(data["error"]))[:500]
        return res


def build_adapter(agent: str, agent_path: str | None, extra: dict) -> AgentAdapter:
    if agent == "kiri":
        exe = agent_path or default_kiri_exe()
        return KiriAdapter(exe, tools=extra.get("tools", KiriAdapter.DEFAULT_TOOLS),
                           provider=extra.get("provider"), model=extra.get("model"),
                           api_key=extra.get("api_key"))
    if agent == "openclaw":
        exe = agent_path or "openclaw"
        return OpenClawAdapter(exe)
    raise SystemExit(f"[ERROR] 未知 agent: {agent!r} (支持: kiri, openclaw)")


# ---------------------------------------------------------------------------
# 自检: 不调 agent, 验证任务定义本身 (setup 可运行, verify 能识别"未完成")
# ---------------------------------------------------------------------------

def selftest():
    print("=== Selftest: 校验任务定义 ===")
    bad = 0
    for t in ALL_TASKS:
        ws = Path(tempfile.mkdtemp(prefix=f"hb_selftest_{t['id']}_"))
        try:
            instr = t["setup"](ws)
            if not isinstance(instr, str) or not instr.strip():
                print(f"  [FAIL] {t['id']}: setup 未返回指令字符串")
                bad += 1
                continue
            fails = t["verify"](ws)
            if fails:
                print(f"  [OK]   {t['id']} (L{t['level']}/{t['capability']}): setup 正常, verify 正确拒绝空结果")
            else:
                print(f"  [WARN] {t['id']}: setup 后 verify 竟通过? 任务定义可疑")
                bad += 1
        except Exception as e:
            print(f"  [FAIL] {t['id']}: {type(e).__name__}: {e}")
            bad += 1
    print(f"=== Selftest 完成: {len(ALL_TASKS) - bad}/{len(ALL_TASKS)} 个任务定义正常 ===")
    return bad


# ---------------------------------------------------------------------------
# 主运行循环
# ---------------------------------------------------------------------------

def select_tasks(args) -> list:
    if args.tasks:
        ids = [x.strip() for x in args.tasks.split(",") if x.strip()]
        return [get_task(i) for i in ids]
    if args.level:
        lv = args.level
        tasks = [t for t in ALL_TASKS if t["level"] == lv]
        if not tasks:
            raise SystemExit(f"[ERROR] 没有 level={lv} 的任务")
        return tasks
    return ALL_TASKS


def run_one(adapter: AgentAdapter, task: dict, ws: Path, timeout: int, run_index: int) -> RunResult:
    instruction = task["setup"](ws)
    res = adapter.run(ws, instruction, timeout)
    res.task_id = task["id"]
    res.level = task["level"]
    res.capability = task["capability"]
    res.run_index = run_index
    # 验证 (验证失败本身也算结果; 不因 rc 异常跳过验证)
    try:
        res.failures = task["verify"](ws)
    except Exception as e:
        res.failures = [f"verify threw {type(e).__name__}: {e}"]
    res.passed = not res.failures
    if res.rc == -2:
        res.error = (res.error or "") + " [验证时 workspace 不完整, 视为失败]"
    return res


def main():
    ap = argparse.ArgumentParser(description="Harness 评测驱动 (kiri / openclaw)")
    ap.add_argument("--agent", choices=["kiri", "openclaw"], default="kiri",
                    help="使用的 agent 后端 (默认 kiri)")
    ap.add_argument("--agent-path", default=None,
                    help="agent 可执行文件路径; 默认 kiri=../output/kiri.exe, openclaw=PATH 中的 openclaw")
    ap.add_argument("--runs", type=int, default=5, help="每个任务跑几次 (默认 5, 取平均作为最终成绩)")
    ap.add_argument("--tasks", default=None, help="逗号分隔的任务 id 列表 (如 l1-hello,l2-log-parser)")
    ap.add_argument("--level", type=int, default=None, help="只跑某一级 (1-5)")
    ap.add_argument("--timeout", type=int, default=600, help="单次 agent 调用超时秒数 (默认 600)")
    ap.add_argument("--keep-ws", action="store_true", help="保留临时 workspace (默认自动删除)")
    ap.add_argument("--selftest", action="store_true", help="只做任务定义自检, 不调 agent")
    ap.add_argument("--tools", default=KiriAdapter.DEFAULT_TOOLS,
                    help="kiri 的 --tools 白名单 (默认 read,bash,edit,write,grep,find,ls)")
    ap.add_argument("--provider", default=None, help="kiri provider (默认自动读 kiri config.json)")
    ap.add_argument("--model", default=None, help="kiri 模型 (默认自动读 kiri config.json)")
    ap.add_argument("--api-key", default=None, help="kiri API key (默认自动读 kiri config.json)")
    ap.add_argument("--out-dir", default=None, help="结果输出目录 (默认 harness-bench/results)")
    args = ap.parse_args()

    if args.runs < 1 or args.runs > 5:
        raise SystemExit("[ERROR] --runs 范围 1..5")
    if args.selftest:
        sys.exit(selftest())

    tasks = select_tasks(args)
    adapter = build_adapter(args.agent, args.agent_path,
                            {"tools": args.tools, "provider": args.provider,
                             "model": args.model, "api_key": args.api_key})
    print(f"[INFO] agent={args.agent} exe={adapter.exe} runs={args.runs} tasks={len(tasks)} timeout={args.timeout}s")

    out_dir = Path(args.out_dir) if args.out_dir else (SCRIPT_DIR / "results" / time.strftime("%Y%m%d-%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)

    all_runs = []
    for task in tasks:
        for ri in range(args.runs):
            ws = Path(tempfile.mkdtemp(prefix=f"hb_{task['id']}_"))
            res = run_one(adapter, task, ws, args.timeout, ri)
            all_runs.append(res)
            status = "PASS" if res.passed else "FAIL"
            print(f"  [{status}] {task['id']} (L{task['level']}/{task['capability']}) "
                  f"run{ri + 1}/{args.runs} tokens={res.tokens_total} "
                  f"({res.tokens_in}+{res.tokens_out}+{res.tokens_cache}) {res.duration_s}s"
                  + (f" | {res.failures[0][:120]}" if not res.passed else ""))
            if not args.keep_ws:
                shutil.rmtree(ws, ignore_errors=True)
            else:
                print(f"          ws kept: {ws}")

    # 汇总 JSON (原始运行数据)
    raw = {
        "agent": args.agent, "exe": str(adapter.exe), "runs": args.runs,
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runs_data": [vars(r) for r in all_runs],
    }
    (out_dir / "raw_runs.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    # 评分与报告
    import scoring
    summary = scoring.score(all_runs, runs_per_task=args.runs)
    scoring.write_report(summary, out_dir / "report.md")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== 评分摘要 ===")
    print(f"通过率 pass@1 : {summary['pass_rate']:.1%}  ({summary['passed']}/{summary['total']})")
    print(f"难度加权分    : {summary['weighted_pass_rate']:.1%}")
    print(f"Token 效率分  : {summary['efficiency_score']:.1%}")
    print(f"综合分        : {summary['composite_score']:.1f}/100")
    print(f"总 Token      : {summary['total_tokens']:,}")
    print(f"平均单任务耗时: {summary['avg_duration_s']:.1f}s")
    print(f"\n[INFO] 结果已写入: {out_dir}")
    print(f"  summary.json / report.md / raw_runs.json")


if __name__ == "__main__":
    main()

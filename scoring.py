"""评分体系 (参考 Artificial Analysis Coding Agent Index 方法论)。

指标:
  - pass@1: 每任务多次运行的平均通过率, 再对全部任务求平均
  - 分难度/分能力通过率
  - Token 消耗: 每任务/每级均值, 总计, 成功任务均耗
  - 难度加权分: L1..L5 权重 [1, 1.5, 2, 2.5, 3], 越难权重越高
  - Token 效率分: 单任务均值 <= TOKEN_BUDGET 拿满分, 超出线性衰减
  - 综合分 (0-100): 0.7 * 难度加权通过率 + 0.3 * Token 效率分
"""
from collections import defaultdict
from pathlib import Path

# 可调参数
LEVEL_WEIGHTS = {1: 1.0, 2: 1.5, 3: 2.0, 4: 2.5, 5: 3.0}
TOKEN_BUDGET = 20000          # 单任务 token 预算: 低于此值效率分满分
PASS_WEIGHT = 0.7             # 综合分中通过率权重
EFF_WEIGHT = 0.3              # 综合分中效率权重

LEVEL_NAMES = {1: "L1 简单", 2: "L2 一般", 3: "L3 中等", 4: "L4 进阶", 5: "L5 专家"}


def score(runs: list, runs_per_task: int) -> dict:
    """runs: harness_runner.RunResult 列表。返回 summary dict。"""
    # 按任务分组
    by_task = defaultdict(list)
    for r in runs:
        by_task[r.task_id].append(r)

    task_stats = []
    per_level_pass = defaultdict(list)      # level -> [通过率]
    per_level_tokens = defaultdict(list)    # level -> [tokens_total 均值]
    per_cap_pass = defaultdict(list)
    total_tokens = 0
    total_success = 0
    total_duration = 0.0
    weighted_pass_sum = 0.0
    weighted_w = 0.0
    eff_sum = 0.0

    for tid, rs in sorted(by_task.items()):
        level = rs[0].level if hasattr(rs[0], "level") else None
        cap = rs[0].capability if hasattr(rs[0], "capability") else "?"
        if level is None:
            level = int(tid.split("-")[0][1]) if tid.startswith("l") and "-" in tid else 1

        n_pass = sum(1 for r in rs if r.passed)
        pr = n_pass / len(rs)
        mean_tok = sum(r.tokens_total for r in rs) / len(rs)
        mean_dur = sum(r.duration_s for r in rs) / len(rs)

        total_tokens += sum(r.tokens_total for r in rs)
        total_success += n_pass
        total_duration += sum(r.duration_s for r in rs)

        per_level_pass[level].append(pr)
        per_level_tokens[level].append(mean_tok)
        per_cap_pass[cap].append(pr)

        w = LEVEL_WEIGHTS.get(level, 1.0)
        weighted_pass_sum += w * pr
        weighted_w += w

        # 效率: 均值 <= 预算拿 1.0, 超出线性衰减
        eff = 1.0 if mean_tok <= TOKEN_BUDGET else max(0.0, TOKEN_BUDGET / mean_tok)
        eff_sum += eff

        task_stats.append({
            "task_id": tid, "level": level, "capability": cap,
            "pass_rate": round(pr, 4), "passed_runs": n_pass, "total_runs": len(rs),
            "mean_tokens": round(mean_tok, 1),
            "mean_tokens_in": round(sum(r.tokens_in for r in rs) / len(rs), 1),
            "mean_tokens_out": round(sum(r.tokens_out for r in rs) / len(rs), 1),
            "mean_tokens_cache": round(sum(r.tokens_cache for r in rs) / len(rs), 1),
            "mean_duration_s": round(mean_dur, 2),
            "efficiency": round(eff, 4),
        })

    n_tasks = len(task_stats)
    pass_rate = sum(s["pass_rate"] for s in task_stats) / n_tasks if n_tasks else 0.0
    weighted_pass_rate = weighted_pass_sum / weighted_w if weighted_w else 0.0
    eff_score = eff_sum / n_tasks if n_tasks else 0.0
    composite = (PASS_WEIGHT * weighted_pass_rate + EFF_WEIGHT * eff_score) * 100

    # 每级统计
    level_stats = []
    for lv in sorted(per_level_pass):
        prs = per_level_pass[lv]
        tks = per_level_tokens[lv]
        level_stats.append({
            "level": lv, "name": LEVEL_NAMES.get(lv, str(lv)),
            "pass_rate": round(sum(prs) / len(prs), 4),
            "task_count": len(prs),
            "mean_tokens": round(sum(tks) / len(tks), 1),
        })

    cap_stats = []
    for cap in sorted(per_cap_pass):
        prs = per_cap_pass[cap]
        cap_stats.append({
            "capability": cap, "pass_rate": round(sum(prs) / len(prs), 4),
            "task_count": len(prs),
        })

    # 成功任务均耗 (token / 成功任务); 全部失败则为 None
    tokens_per_success = round(total_tokens / total_success, 1) if total_success else None

    return {
        "method": "参考 Artificial Analysis: pass@1 多轮平均 + 难度加权 + token 效率",
        "config": {"runs_per_task": runs_per_task, "level_weights": LEVEL_WEIGHTS,
                   "token_budget": TOKEN_BUDGET, "pass_weight": PASS_WEIGHT,
                   "eff_weight": EFF_WEIGHT},
        "total_tasks": n_tasks,
        "total_runs": len(runs),
        "passed": total_success,
        "total": len(runs),
        "pass_rate": round(pass_rate, 4),
        "weighted_pass_rate": round(weighted_pass_rate, 4),
        "efficiency_score": round(eff_score, 4),
        "composite_score": round(composite, 1),
        "total_tokens": total_tokens,
        "avg_tokens_per_task": round(total_tokens / n_tasks, 1) if n_tasks else 0,
        "tokens_per_success": tokens_per_success,
        "avg_duration_s": round(total_duration / n_tasks, 2) if n_tasks else 0,
        "by_level": level_stats,
        "by_capability": cap_stats,
        "tasks": task_stats,
    }


def write_report(summary: dict, path: str):
    lines = []
    lines.append("# Harness 评测报告")
    lines.append("")
    lines.append(f"- 方法: {summary['method']}")
    lines.append(f"- 任务数: {summary['total_tasks']}, 总运行次数: {summary['total_runs']}")
    lines.append("")
    lines.append("## 总体指标")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|---|---|")
    lines.append(f"| 通过率 pass@1 | {summary['pass_rate']:.1%} ({summary['passed']}/{summary['total']}) |")
    lines.append(f"| 难度加权通过率 | {summary['weighted_pass_rate']:.1%} |")
    lines.append(f"| Token 效率分 | {summary['efficiency_score']:.1%} |")
    lines.append(f"| 综合分 | {summary['composite_score']:.1f}/100 |")
    lines.append(f"| 总 Token | {summary['total_tokens']:,} |")
    lines.append(f"| 平均单任务 Token | {summary['avg_tokens_per_task']:,.1f} |")
    tok_per = summary.get("tokens_per_success")
    lines.append(f"| Token/成功任务 | {f'{tok_per:,.1f}' if tok_per else 'N/A (无成功任务)'} |")
    lines.append(f"| 平均单任务耗时 | {summary['avg_duration_s']}s |")
    lines.append("")
    lines.append("## 分难度")
    lines.append("")
    lines.append("| 等级 | 通过率 | 任务数 | 平均 Token |")
    lines.append("|---|---|---|---|")
    for ls in summary["by_level"]:
        lines.append(f"| {ls['name']} | {ls['pass_rate']:.1%} | {ls['task_count']} | {ls['mean_tokens']:,.1f} |")
    lines.append("")
    lines.append("## 分能力")
    lines.append("")
    lines.append("| 能力 | 通过率 | 任务数 |")
    lines.append("|---|---|---|")
    for cs in summary["by_capability"]:
        lines.append(f"| {cs['capability']} | {cs['pass_rate']:.1%} | {cs['task_count']} |")
    lines.append("")
    lines.append("## 单任务明细")
    lines.append("")
    lines.append("| 任务 | 难度 | 能力 | 通过率 | 平均Token | 效率 |")
    lines.append("|---|---|---|---|---|---|")
    for t in summary["tasks"]:
        lines.append(f"| {t['task_id']} | L{t['level']} | {t['capability']} | "
                     f"{t['pass_rate']:.0%} ({t['passed_runs']}/{t['total_runs']}) | "
                     f"{t['mean_tokens']:,.0f} | {t['efficiency']:.0%} |")
    lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")

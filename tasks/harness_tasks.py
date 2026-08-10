"""Harness 评测任务定义 (跨平台, Win/Linux)。

任务由纯 Python 定义, 不依赖 shell 特定语法, 确保 Windows 与 Linux 行为一致。
每个任务:
  - id: 唯一标识
  - level: 1..5 (简单 -> 困难)
  - capability: 主要能力维度 (file/code/bash/grep/debug/context/plan)
  - description: 给人看的说明
  - instruction: 给 agent 的完整任务指令
  - setup(ws): 准备 workspace (生成输入文件)
  - verify(ws) -> list[str]: 返回失败信息列表, 空 = 通过
"""

import json
import os
import re
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def w(ws: Path, *parts) -> Path:
    return Path(ws).joinpath(*parts)


def write_file(ws: Path, rel: str, content: str):
    p = w(ws, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def read_file(ws: Path, rel: str) -> str:
    p = w(ws, rel)
    if not p.exists():
        raise FileNotFoundError(f"missing file: {rel}")
    return p.read_text(encoding="utf-8")


def gen_numbers_file(n: int = 200) -> str:
    """生成 200 行随机但确定的数字, 用于排序/统计类任务。"""
    import random
    rng = random.Random(42)
    return "\n".join(str(rng.randint(-1000, 1000)) for _ in range(n)) + "\n"


def gen_names_file() -> str:
    return "\n".join([
        "alice@example.com", "bob@example.com", "carol@example.com",
        "dave@example.com", "eve@example.com", "frank@example.com",
        "grace@example.com", "heidi@example.com",
    ]) + "\n"


# ---------------------------------------------------------------------------
# L1 - 简单 (单文件, 单操作, 明确指令)
# ---------------------------------------------------------------------------

def t_l1_hello(ws):
    write_file(ws, "hello.txt", "Hello, world!\n")
    return ("Create a file named `result.txt` in the workspace. "
            "Its content must be exactly: Hello, Kiri!\n"
            "Do not create any other files.")

def v_l1_hello(ws):
    fails = []
    p = w(ws, "result.txt")
    if not p.exists():
        return ["result.txt missing"]
    content = p.read_text(encoding="utf-8").strip()
    if content != "Hello, Kiri!":
        fails.append(f"result.txt content mismatch: {content!r}")
    # 不允许额外文件
    extra = [f.name for f in ws.iterdir() if f.name not in ("result.txt", "hello.txt")]
    if extra:
        fails.append(f"unexpected files: {extra}")
    return fails


def t_l1_csv_to_json(ws):
    write_file(ws, "data.csv",
               "name,age,city\nAlice,30,NYC\nBob,25,LA\nCarol,35,SF\n")
    return ("Convert `data.csv` to `data.json`. "
            "The JSON must be an array of objects, one per row (excluding header), "
            "with keys `name`, `age`, `city`. `age` must be a number, not a string.")

def v_l1_csv_to_json(ws):
    try:
        data = json.loads(read_file(ws, "data.json"))
    except Exception as e:
        return [f"data.json invalid JSON: {e}"]
    if not isinstance(data, list) or len(data) != 3:
        return [f"expected list of 3, got {type(data).__name__} len={len(data) if isinstance(data, list) else '?'}"]
    ok = True
    for row in data:
        if set(row.keys()) != {"name", "age", "city"}:
            ok = False
        if not isinstance(row.get("age"), int):
            ok = False
    if not ok:
        return [f"row schema wrong: {data}"]
    if data[0]["name"] != "Alice" or data[1]["age"] != 25:
        return [f"values wrong: {data}"]
    return []


def t_l1_count_lines(ws):
    content = gen_numbers_file(200)
    write_file(ws, "numbers.txt", content)
    return ("Count how many lines are in `numbers.txt` and how many of them are "
            "positive numbers (greater than 0). Write the answer as a file "
            "`answer.txt` with exactly two lines: first the total line count, "
            "then the positive count. Example format:\n200\n97")

def v_l1_count_lines(ws):
    try:
        lines = read_file(ws, "answer.txt").strip().splitlines()
    except FileNotFoundError:
        return ["answer.txt missing"]
    if len(lines) != 2:
        return [f"answer.txt must have exactly 2 lines, got {len(lines)}"]
    src = read_file(ws, "numbers.txt").strip().splitlines()
    total = len(src)
    positive = sum(1 for x in src if int(x) > 0)
    if lines[0].strip() != str(total):
        return [f"total line count wrong: {lines[0]!r} != {total}"]
    if lines[1].strip() != str(positive):
        return [f"positive count wrong: {lines[1]!r} != {positive}"]
    return []


def t_l1_replace_word(ws):
    text = ("The quick brown fox jumps over the lazy dog. "
            "The fox is quick. The dog is lazy.")
    write_file(ws, "text.txt", text)
    return ("In `text.txt`, replace every occurrence of the word `fox` with `cat` "
            "and write the result to `output.txt`. Keep everything else unchanged.")

def v_l1_replace_word(ws):
    try:
        out = read_file(ws, "output.txt")
    except FileNotFoundError:
        return ["output.txt missing"]
    if "fox" in out:
        return [f"'fox' still present: {out!r}"]
    if "cat" not in out:
        return [f"'cat' missing: {out!r}"]
    expected = "The quick brown cat jumps over the lazy dog. The cat is quick. The dog is lazy."
    if out.strip() != expected:
        return [f"content mismatch: {out!r}"]
    return []


def t_l1_create_tree(ws):
    return ("Create the following directory structure and files inside the workspace:\n"
            "  src/main.py containing `def main(): return 42`\n"
            "  src/utils.py containing `def helper(): return 'ok'`\n"
            "  tests/test_main.py containing `def test_main(): assert main() == 42`\n"
            "Use the exact contents specified.")

def v_l1_create_tree(ws):
    fails = []
    for rel, content in [
        ("src/main.py", "def main(): return 42"),
        ("src/utils.py", "def helper(): return 'ok'"),
        ("tests/test_main.py", "def test_main(): assert main() == 42"),
    ]:
        try:
            got = read_file(ws, rel).strip()
            if got != content:
                fails.append(f"{rel} content mismatch: {got!r} != {content!r}")
        except FileNotFoundError:
            fails.append(f"{rel} missing")
    return fails


# ---------------------------------------------------------------------------
# L2 - 一般 (多步骤, 需要组合工具)
# ---------------------------------------------------------------------------

def t_l2_find_max_min(ws):
    content = gen_numbers_file(300)
    write_file(ws, "data.txt", content)
    return ("Read `data.txt` (contains one integer per line). Find the maximum "
            "and minimum values. Write `stats.txt` with exactly two lines:\n"
            "max: <max value>\nmin: <min value>")

def v_l2_find_max_min(ws):
    try:
        lines = read_file(ws, "stats.txt").strip().splitlines()
    except FileNotFoundError:
        return ["stats.txt missing"]
    nums = [int(x) for x in read_file(ws, "data.txt").strip().splitlines()]
    if lines[0].strip() != f"max: {max(nums)}":
        return [f"max wrong: {lines[0]!r}"]
    if lines[1].strip() != f"min: {min(nums)}":
        return [f"min wrong: {lines[1]!r}"]
    return []


def t_l2_log_parser(ws):
    lines = [
        "2025-01-01 10:00:00 INFO User login",
        "2025-01-01 10:01:00 ERROR Database timeout",
        "2025-01-01 10:02:00 INFO Request processed",
        "2025-01-01 10:03:00 WARN Cache miss",
        "2025-01-01 10:04:00 ERROR Connection refused",
        "2025-01-01 10:05:00 INFO Response sent",
    ]
    write_file(ws, "app.log", "\n".join(lines) + "\n")
    return ("Analyze `app.log`. Each line has format: DATE TIME LEVEL MESSAGE.\n"
            "1) Count how many lines contain the level ERROR.\n"
            "2) List the messages of all ERROR lines (the text after the level).\n"
            "Write `errors.txt` with the count on the first line, then one error "
            "message per line, in order of appearance.")

def v_l2_log_parser(ws):
    try:
        out = read_file(ws, "errors.txt").strip().splitlines()
    except FileNotFoundError:
        return ["errors.txt missing"]
    log = read_file(ws, "app.log").strip().splitlines()
    err_msgs = [line.split(" ", 3)[3] for line in log if " ERROR " in line]
    if out[0].strip() != str(len(err_msgs)):
        return [f"error count wrong: {out[0]!r} != {len(err_msgs)}"]
    if out[1:] != err_msgs:
        return [f"error messages wrong: {out[1:]!r} != {err_msgs!r}"]
    return []


def t_l2_sum_even(ws):
    content = gen_numbers_file(150)
    write_file(ws, "nums.txt", content)
    return ("Read `nums.txt`, one integer per line. Compute the sum of all even "
            "numbers. Write the result to `even_sum.txt` as a single integer.")

def v_l2_sum_even(ws):
    try:
        s = read_file(ws, "even_sum.txt").strip()
    except FileNotFoundError:
        return ["even_sum.txt missing"]
    nums = [int(x) for x in read_file(ws, "nums.txt").strip().splitlines()]
    expected = sum(n for n in nums if n % 2 == 0)
    if s != str(expected):
        return [f"sum wrong: {s!r} != {expected}"]
    return []


def t_l2_json_merge(ws):
    write_file(ws, "a.json", json.dumps({"users": [{"id": 1, "name": "Alice"}]}))
    write_file(ws, "b.json", json.dumps({"users": [{"id": 2, "name": "Bob"}]}))
    return ("Merge `a.json` and `b.json` into `merged.json`. Both contain a "
            "`users` array. The merged file must have a single `users` array "
            "containing the objects from both files, in order (Alice first, Bob second).")

def v_l2_json_merge(ws):
    try:
        data = json.loads(read_file(ws, "merged.json"))
    except Exception as e:
        return [f"merged.json invalid: {e}"]
    users = data.get("users")
    if users != [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]:
        return [f"users wrong: {users}"]
    return []


def t_l2_fix_syntax(ws):
    buggy = (
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def multiply(a, b)\n"  # 语法错误: 缺冒号
        "    return a * b\n"
        "\n"
        "print(add(2, 3))\n"
        "print(multiply(2, 3))\n"
    )
    write_file(ws, "buggy.py", buggy)
    return ("Fix the syntax error in `buggy.py` so it runs without errors and "
            "prints the correct results (5 and 6). You may edit the file in place.")

def v_l2_fix_syntax(ws):
    try:
        content = read_file(ws, "buggy.py")
    except FileNotFoundError:
        return ["buggy.py missing"]
    # 简单验证: 不能运行时报错 (这里是静态验证 + 语法检查)
    import py_compile
    try:
        py_compile.compile(w(ws, "buggy.py"), doraise=True)
    except Exception as e:
        return [f"syntax error remains: {e}"]
    # 运行时验证
    import subprocess, sys
    r = subprocess.run([sys.executable, str(w(ws, "buggy.py"))],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return [f"runtime error: {r.stderr[-300:]}"]
    out_lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
    if out_lines[:2] != ["5", "6"]:
        return [f"wrong output: {r.stdout!r}"]
    return []


# ---------------------------------------------------------------------------
# L3 - 中等 (多文件, 逻辑, 需要规划)
# ---------------------------------------------------------------------------

def t_l3_word_frequency(ws):
    words = ("the cat sat on the mat the dog ran under the mat "
             "cat dog bird bird bird").split()
    write_file(ws, "words.txt", " ".join(words) + "\n")
    return ("Read `words.txt` (space-separated words). Compute the frequency of "
            "each word. Write `freq.json` as a JSON object mapping each word to "
            "its count, sorted by count descending. If counts tie, order by word "
            "alphabetically. Example: {\"bird\": 3, \"the\": 3, ...}")

def v_l3_word_frequency(ws):
    try:
        freq = json.loads(read_file(ws, "freq.json"))
    except Exception as e:
        return [f"freq.json invalid: {e}"]
    words = read_file(ws, "words.txt").strip().split()
    expected = {}
    for w_ in words:
        expected[w_] = expected.get(w_, 0) + 1
    if freq != expected:
        return [f"freq mismatch: {freq} != {expected}"]
    # 检查排序
    items = list(freq.items())
    sorted_items = sorted(items, key=lambda kv: (-kv[1], kv[0]))
    if items != sorted_items:
        return [f"not sorted by count desc: {items}"]
    return []


def t_l3_multi_file_refactor(ws):
    write_file(ws, "math_ops.py",
               "def add(a, b): return a + b\n"
               "def sub(a, b): return a - b\n"
               "def mul(a, b): return a * b\n")
    write_file(ws, "app.py",
               "from math_ops import add, sub, mul\n"
               "print(add(2, 3))\n"
               "print(sub(10, 4))\n"
               "print(mul(3, 4))\n")
    return ("Refactor: move the functions `add`, `sub`, `mul` from `math_ops.py` "
            "into a new file `operations.py`. Then update `app.py` to import from "
            "`operations` instead of `math_ops`. Remove `math_ops.py`. The program "
            "must still print 5, 6, 12 when run.")

def v_l3_multi_file_refactor(ws):
    if w(ws, "math_ops.py").exists():
        return ["math_ops.py should be removed"]
    try:
        ops = read_file(ws, "operations.py")
    except FileNotFoundError:
        return ["operations.py missing"]
    app = read_file(ws, "app.py")
    if "math_ops" in app:
        return [f"app.py still imports math_ops: {app!r}"]
    if "operations" not in app:
        return [f"app.py does not import operations: {app!r}"]
    import subprocess, sys
    r = subprocess.run([sys.executable, str(w(ws, "app.py"))],
                       capture_output=True, text=True, timeout=30, cwd=str(ws))
    if r.returncode != 0:
        return [f"runtime error: {r.stderr[-300:]}"]
    if r.stdout.strip().splitlines() != ["5", "6", "12"]:
        return [f"wrong output: {r.stdout!r}"]
    return []


def t_l3_file_organizer(ws):
    files = {
        "doc_report_2024.txt": "annual report content",
        "doc_notes_2023.txt": "meeting notes",
        "img_photo1.jpg": "jpegdata",
        "img_photo2.jpg": "jpegdata",
        "src_main.py": "def main(): pass",
        "src_util.py": "def util(): pass",
        "data_raw.csv": "a,b\n1,2",
    }
    for name, content in files.items():
        write_file(ws, name, content)
    return ("Organize the workspace files into subdirectories by prefix:\n"
            "  * files starting with `doc_` -> docs/\n"
            "  * files starting with `img_` -> images/\n"
            "  * files starting with `src_` -> source/\n"
            "  * files starting with `data_` -> data/\n"
            "Move the files (do not copy). Do not leave the originals in the workspace root.")

def v_l3_file_organizer(ws):
    expected = {
        "docs": ["doc_report_2024.txt", "doc_notes_2023.txt"],
        "images": ["img_photo1.jpg", "img_photo2.jpg"],
        "source": ["src_main.py", "src_util.py"],
        "data": ["data_raw.csv"],
    }
    fails = []
    for d, names in expected.items():
        for n in names:
            if not w(ws, d, n).exists():
                fails.append(f"{d}/{n} missing")
            if w(ws, n).exists():
                fails.append(f"{n} still in root")
    # 根目录不应有这些文件
    for n in ["doc_report_2024.txt", "img_photo1.jpg", "src_main.py", "data_raw.csv"]:
        if w(ws, n).exists():
            fails.append(f"{n} still in root")
    return fails


def t_l3_csv_filter(ws):
    rows = ["id,name,score",
            "1,Alice,85", "2,Bob,72", "3,Carol,91",
            "4,Dave,64", "5,Eve,88", "6,Frank,55"]
    write_file(ws, "students.csv", "\n".join(rows) + "\n")
    return ("Read `students.csv` (header: id,name,score). Write `passing.csv` "
            "with the same header, containing only students whose score is >= 70, "
            "in the same order. Preserve the CSV format.")

def v_l3_csv_filter(ws):
    try:
        out = read_file(ws, "passing.csv").strip().splitlines()
    except FileNotFoundError:
        return ["passing.csv missing"]
    if out[0] != "id,name,score":
        return [f"header wrong: {out[0]!r}"]
    expected = ["1,Alice,85", "2,Bob,72", "3,Carol,91", "5,Eve,88"]
    if out[1:] != expected:
        return [f"rows wrong: {out[1:]!r} != {expected}"]
    return []


def t_l3_debug_logic(ws):
    buggy = (
        "# This function is supposed to return True if a number is prime, "
        "# False otherwise. There is a bug.\n"
        "def is_prime(n):\n"
        "    if n < 2:\n"
        "        return False\n"
        "    for i in range(2, n):\n"
        "        if n % i == 0:\n"
        "            return False\n"
        "    return True\n"
        "\n"
        "# This function is supposed to return the sum of 1..n. There is a bug.\n"
        "def sum_to(n):\n"
        "    total = 0\n"
        "    for i in range(n):\n"
        "        total += i\n"
        "    return total\n"
        "\n"
        "print(is_prime(7))\n"
        "print(is_prime(9))\n"
        "print(sum_to(5))\n"
        "print(sum_to(1))\n"
    )
    write_file(ws, "debug.py", buggy)
    return ("`debug.py` has two logic bugs. Fix them so the program prints:\n"
            "True\nFalse\n15\n1\n"
            "Do not change the print statements.")

def v_l3_debug_logic(ws):
    import subprocess, sys
    r = subprocess.run([sys.executable, str(w(ws, "debug.py"))],
                       capture_output=True, text=True, timeout=30, cwd=str(ws))
    if r.returncode != 0:
        return [f"runtime error: {r.stderr[-300:]}"]
    expected = ["True", "False", "15", "1"]
    got = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
    if got != expected:
        return [f"wrong output: {got} != {expected}"]
    return []


# ---------------------------------------------------------------------------
# L4 - 进阶 (跨文件逻辑, 组合能力, 长文档)
# ---------------------------------------------------------------------------

def t_l4_long_doc_extract(ws):
    # 生成长文档 (150 行), 要求从长文档中精准提取
    lines = []
    for i in range(1, 151):
        lines.append(f"Section {i}: The quick brown fox jumps over the lazy dog. "
                     f"Value_{i}={i * 7}. Padding data to make lines reasonably long.")
    write_file(ws, "long_doc.txt", "\n".join(lines) + "\n")
    return ("Read `long_doc.txt` (150 lines). Each line contains a marker like "
            "`Value_<N>=<V>`. Find ALL lines where N is divisible by 10 "
            "(i.e. Value_10, Value_20, ..., Value_150). Write `extracted.txt` with "
            "one matching marker per line, in order, e.g.:\nValue_10=70\nValue_20=140\n...\n"
            "Only include the markers, nothing else.")

def v_l4_long_doc_extract(ws):
    try:
        out = read_file(ws, "extracted.txt").strip().splitlines()
    except FileNotFoundError:
        return ["extracted.txt missing"]
    expected = [f"Value_{i}={i * 7}" for i in range(10, 151, 10)]
    if out != expected:
        return [f"extracted wrong: {len(out)} lines vs expected {len(expected)}; "
                f"first mismatch: {out[:3]} vs {expected[:3]}"]
    return []


def t_l4_config_change(ws):
    cfg = (
        "# config\n"
        "server.host = 127.0.0.1\n"
        "server.port = 8080\n"
        "db.host = localhost\n"
        "db.port = 5432\n"
        "db.user = admin\n"
        "db.password = secret123\n"
        "log.level = info\n"
        "log.file = /var/log/app.log\n"
        "cache.enabled = true\n"
        "cache.ttl = 300\n"
    )
    write_file(ws, "config.ini", cfg)
    return ("Edit `config.ini`: change `server.port` to 9090, `db.user` to `app`, "
            "and `cache.ttl` to 600. Do not change any other lines. The format "
            "`key = value` must be preserved.")

def v_l4_config_change(ws):
    try:
        content = read_file(ws, "config.ini")
    except FileNotFoundError:
        return ["config.ini missing"]
    checks = {
        "server.port = 9090": True,
        "db.user = app": True,
        "cache.ttl = 600": True,
        "server.host = 127.0.0.1": True,
        "db.port = 5432": True,
        "log.level = info": True,
        "cache.enabled = true": True,
    }
    fails = []
    for line, expected in checks.items():
        if expected and line not in content:
            fails.append(f"missing/unchanged: {line}")
    if "server.port = 8080" in content:
        fails.append("server.port not changed")
    if "db.user = admin" in content:
        fails.append("db.user not changed")
    if "cache.ttl = 300" in content:
        fails.append("cache.ttl not changed")
    return fails


def t_l4_nested_search(ws):
    # 多层目录, 其中一个文件包含目标字符串, 需要搜索定位
    write_file(ws, "src/module_a/file1.py", "def a(): pass\n# TODO: nothing here\n")
    write_file(ws, "src/module_a/file2.py", "def b(): pass\n")
    write_file(ws, "src/module_b/file3.py",
               "def find_me():\n    # The magic number is 741852\n    return 741852\n")
    write_file(ws, "src/module_b/file4.py", "def d(): pass\n")
    write_file(ws, "tests/test_x.py", "def test_x(): assert True\n")
    return ("Search the `src` directory tree to find the file containing the "
            "string `741852`. In that file, find the function name that returns "
            "this magic number. Write `answer.txt` with the file path (relative to "
            "workspace) on the first line and the function name on the second line.")

def v_l4_nested_search(ws):
    try:
        lines = read_file(ws, "answer.txt").strip().splitlines()
    except FileNotFoundError:
        return ["answer.txt missing"]
    if len(lines) < 2:
        return [f"answer.txt needs 2 lines, got {lines}"]
    if "file3.py" not in lines[0]:
        return [f"wrong file: {lines[0]!r}"]
    if lines[1].strip() != "find_me":
        return [f"wrong function: {lines[1]!r}"]
    return []


def t_l4_data_pipeline(ws):
    write_file(ws, "sales.csv",
               "month,product,amount\n"
               "Jan,Widget,100\nJan,Gadget,200\n"
               "Feb,Widget,150\nFeb,Gadget,50\n"
               "Mar,Widget,80\nMar,Gadget,300\n")
    return ("Analyze `sales.csv` (columns: month, product, amount). Write "
            "`report.txt` containing, for each product, its total amount across "
            "all months, sorted by total descending. Format exactly:\n"
            "Gadget: 550\nWidget: 330\n"
            "(one line per product: `Product: total`)")

def v_l4_data_pipeline(ws):
    try:
        out = read_file(ws, "report.txt").strip().splitlines()
    except FileNotFoundError:
        return ["report.txt missing"]
    expected = ["Gadget: 550", "Widget: 330"]
    if out != expected:
        return [f"report wrong: {out} != {expected}"]
    return []


def t_l4_find_bug(ws):
    # 多函数文件, 只有一个有 bug, 需要定位并修复
    code = (
        "def add(a, b):\n    return a + b\n\n"
        "def subtract(a, b):\n    return a - b\n\n"
        "def multiply(a, b):\n    return a * b\n\n"
        "def divide(a, b):\n    return a / b\n\n"
        "def average(nums):\n    total = 0\n"
        "    for n in nums:\n        total += n\n"
        "    return total / len(nums) if nums else 0\n\n"
        "# BUG: this function should return the max, but has a logic error\n"
        "def find_max(nums):\n    if not nums:\n        return None\n"
        "    m = 0\n"
        "    for n in nums:\n        if n > m:\n            m = n\n"
        "    return m\n"
    )
    write_file(ws, "calc.py", code)
    return ("There is a bug in `calc.py`: the function `find_max` does not work "
            "correctly for all inputs (try `find_max([-5, -2, -10])`). Find and fix "
            "the bug. The function must return the true maximum for any non-empty "
            "list of integers.")

def v_l4_find_bug(ws):
    import subprocess, sys
    test_code = (
        "from calc import find_max\n"
        "assert find_max([1, 2, 3]) == 3\n"
        "assert find_max([-5, -2, -10]) == -2\n"
        "assert find_max([0]) == 0\n"
        "assert find_max([7]) == 7\n"
        "print('OK')\n"
    )
    write_file(ws, "_check.py", test_code)
    r = subprocess.run([sys.executable, str(w(ws, "_check.py"))],
                       capture_output=True, text=True, timeout=30, cwd=str(ws))
    if r.returncode != 0:
        return [f"find_max still broken: {r.stderr[-300:]}"]
    return []


def t_l4_riddle_driving(ws):
    # 脑筋急转弯: 要洗的是车, 不是人 —— 所以开车过去
    return ("【脑筋急转弯】我叫小四，我有一台汗血宝马，今天星期五，我要去洗车，"
            "但是洗车店距离我只有10米，我在纠结：是走过去还是开车过去？\n"
            "请把最终选择写入 `answer.txt`，一行即可，例如：开车过去。"
            "（理由可写可不写，判卷只看选择，不看理由）")

def v_l4_riddle_driving(ws):
    try:
        content = read_file(ws, "answer.txt")
    except FileNotFoundError:
        return ["answer.txt missing"]
    if "开车" in content or "drive" in content.lower() or "car" in content.lower():
        return []
    return [f"答案应为「开车过去」, 实际: {content.strip()[:100]!r}"]


# ---------------------------------------------------------------------------
# L5 - 专家 (复杂组合, 多文件重构, 大输入, 模糊需求)
# ---------------------------------------------------------------------------

def t_l5_complex_processing(ws):
    # 生成 500 行混合数据, 需要多种操作组合
    import random
    rng = random.Random(2024)
    lines = []
    for i in range(500):
        val = rng.randint(-10000, 10000)
        cat = rng.choice(["A", "B", "C"])
        lines.append(f"{val},{cat},{i}")
    write_file(ws, "bigdata.csv", "\n".join(lines) + "\n")
    return ("Process `bigdata.csv` (500 lines, format: value,category,index). "
            "For each category (A, B, C), compute the average of `value` rounded "
            "to 2 decimal places. Write `averages.json`:\n"
            "{\"A\": <avg>, \"B\": <avg>, \"C\": <avg>}\n"
            "Then also write `maxmin.txt` with the overall max and min of `value`, "
            "one per line:\nmax: <max>\nmin: <min>")

def v_l5_complex_processing(ws):
    fails = []
    try:
        avgs = json.loads(read_file(ws, "averages.json"))
    except Exception as e:
        return [f"averages.json invalid: {e}"]
    import csv, io
    data = []
    for row in csv.reader(io.StringIO(read_file(ws, "bigdata.csv"))):
        if row:
            data.append((int(row[0]), row[1], int(row[2])))
    cats = {}
    for v, c, _ in data:
        cats.setdefault(c, []).append(v)
    expected = {c: round(sum(vs) / len(vs), 2) for c, vs in cats.items()}
    if avgs != expected:
        fails.append(f"averages mismatch: {avgs} != {expected}")
    try:
        mm = read_file(ws, "maxmin.txt").strip().splitlines()
    except FileNotFoundError:
        return fails + ["maxmin.txt missing"]
    all_vals = [v for v, _, _ in data]
    try:
        got_max = float(mm[0].split(":", 1)[1].strip())
        got_min = float(mm[1].split(":", 1)[1].strip())
    except (IndexError, ValueError):
        return fails + [f"maxmin.txt format wrong: {mm}"]
    if got_max != max(all_vals):
        fails.append(f"max wrong: {mm[0]!r}")
    if got_min != min(all_vals):
        fails.append(f"min wrong: {mm[1]!r}")
    return fails


def t_l5_multi_module(ws):
    write_file(ws, "src/__init__.py", "")
    write_file(ws, "src/calc.py",
               "def add(a, b): return a + b\ndef mul(a, b): return a * b\n")
    write_file(ws, "src/strings.py",
               "def upper(s): return s.upper()\ndef title(s): return s.title()\n")
    write_file(ws, "src/utils.py",
               "def clamp(x, lo, hi): return max(lo, min(x, hi))\n")
    return ("Create a new module `src/report.py` that imports from `calc`, "
            "`strings`, and `utils` and defines a function `build_report(name, base)` "
            "that returns a string like:\n"
            "Report: <NAME upper>\nTotal: <base * 2>\nClamped: <clamp(base, 0, 100)>\n"
            "Then create `main.py` at the workspace root that imports "
            "`build_report` from `src.report` and prints the result for "
            "`name='alice', base=42`. Run it and confirm it works.")

def v_l5_multi_module(ws):
    import subprocess, sys
    if not w(ws, "src", "report.py").exists():
        return ["src/report.py missing"]
    if not w(ws, "main.py").exists():
        return ["main.py missing"]
    r = subprocess.run([sys.executable, str(w(ws, "main.py"))],
                       capture_output=True, text=True, timeout=30, cwd=str(ws))
    if r.returncode != 0:
        return [f"runtime error: {r.stderr[-300:]}"]
    expected = "Report: ALICE\nTotal: 84\nClamped: 42"
    if r.stdout.strip() != expected:
        return [f"wrong output: {r.stdout!r} != {expected!r}"]
    return []


def t_l5_multi_file_refactor_big(ws):
    # 5 个文件, 需要跨文件重命名 + 依赖更新
    for i in range(1, 6):
        write_file(ws, f"mod{i}.py",
                   f"def func_{i}():\n    return {i * 100}\n")
    write_file(ws, "main.py",
               "from mod1 import func_1\n"
               "from mod2 import func_2\n"
               "from mod3 import func_3\n"
               "from mod4 import func_4\n"
               "from mod5 import func_5\n"
               "print(func_1() + func_2() + func_3() + func_4() + func_5())\n")
    return ("Refactor: rename the modules `mod1.py`..`mod5.py` to "
            "`numbers_1.py`..`numbers_5.py` (keep the function names `func_1`..`func_5`). "
            "Update `main.py` imports accordingly. Delete the old files. The program "
            "must still print 1500.")

def v_l5_multi_file_refactor_big(ws):
    for i in range(1, 6):
        if w(ws, f"mod{i}.py").exists():
            return [f"mod{i}.py should be deleted"]
    for i in range(1, 6):
        if not w(ws, f"numbers_{i}.py").exists():
            return [f"numbers_{i}.py missing"]
    import subprocess, sys
    r = subprocess.run([sys.executable, str(w(ws, "main.py"))],
                       capture_output=True, text=True, timeout=30, cwd=str(ws))
    if r.returncode != 0:
        return [f"runtime error: {r.stderr[-300:]}"]
    if r.stdout.strip() != "1500":
        return [f"wrong output: {r.stdout!r}"]
    return []


def t_l5_ambiguous_requirements(ws):
    write_file(ws, "inventory.json", json.dumps([
        {"item": "apple", "qty": 10, "price": 2.5},
        {"item": "banana", "qty": 5, "price": 1.2},
        {"item": "cherry", "qty": 20, "price": 0.8},
        {"item": "durian", "qty": 2, "price": 15.0},
    ]))
    return ("Analyze `inventory.json` (array of {item, qty, price}). Determine the "
            "total inventory value (sum of qty*price for all items) and identify "
            "the item with the highest total value (qty*price). Write `summary.json` "
            "with two keys:\n"
            "{\"total_value\": <number>, \"top_item\": \"<item name>\"}")

def v_l5_ambiguous_requirements(ws):
    try:
        summary = json.loads(read_file(ws, "summary.json"))
    except Exception as e:
        return [f"summary.json invalid: {e}"]
    inv = json.loads(read_file(ws, "inventory.json"))
    total = sum(x["qty"] * x["price"] for x in inv)
    top = max(inv, key=lambda x: x["qty"] * x["price"])["item"]
    if summary.get("total_value") != total:
        return [f"total_value wrong: {summary.get('total_value')} != {total}"]
    if summary.get("top_item") != top:
        return [f"top_item wrong: {summary.get('top_item')} != {top}"]
    return []


def t_l5_find_and_summarize(ws):
    # 分布式文件, 需要全局搜索 + 跨文件聚合
    payloads = {
        "data/part1.txt": "key=alpha value=100\nkey=beta value=200\n",
        "data/part2.txt": "key=beta value=300\nkey=gamma value=400\n",
        "data/part3.txt": "key=alpha value=50\nkey=gamma value=150\n",
        "logs/event1.log": "INFO job completed\n",
        "logs/event2.log": "WARN retrying\n",
    }
    for rel, content in payloads.items():
        write_file(ws, rel, content)
    return ("Search all files under the `data` directory. Each line has format "
            "`key=K value=V`. Aggregate by key: sum all values per key. Write "
            "`aggregate.json` with keys sorted alphabetically and values as sums:\n"
            "{\"alpha\": 150, \"beta\": 500, \"gamma\": 550}\n"
            "Ignore everything outside the `data` directory.")

def v_l5_find_and_summarize(ws):
    try:
        agg = json.loads(read_file(ws, "aggregate.json"))
    except Exception as e:
        return [f"aggregate.json invalid: {e}"]
    expected = {"alpha": 150, "beta": 500, "gamma": 550}
    if agg != expected:
        return [f"aggregate mismatch: {agg} != {expected}"]
    return []


# ---------------------------------------------------------------------------
# 任务注册表
# ---------------------------------------------------------------------------

ALL_TASKS = [
    # L1 简单
    {"id": "l1-hello", "level": 1, "capability": "file",
     "description": "创建指定内容文件", "setup": t_l1_hello, "verify": v_l1_hello},
    {"id": "l1-csv-to-json", "level": 1, "capability": "file",
     "description": "CSV 转 JSON", "setup": t_l1_csv_to_json, "verify": v_l1_csv_to_json},
    {"id": "l1-count-lines", "level": 1, "capability": "read",
     "description": "统计行数与正数个数", "setup": t_l1_count_lines, "verify": v_l1_count_lines},
    {"id": "l1-replace-word", "level": 1, "capability": "edit",
     "description": "查找替换单词", "setup": t_l1_replace_word, "verify": v_l1_replace_word},
    {"id": "l1-create-tree", "level": 1, "capability": "file",
     "description": "创建目录结构", "setup": t_l1_create_tree, "verify": v_l1_create_tree},

    # L2 一般
    {"id": "l2-find-max-min", "level": 2, "capability": "read",
     "description": "找最大值最小值", "setup": t_l2_find_max_min, "verify": v_l2_find_max_min},
    {"id": "l2-log-parser", "level": 2, "capability": "bash",
     "description": "解析日志统计错误", "setup": t_l2_log_parser, "verify": v_l2_log_parser},
    {"id": "l2-sum-even", "level": 2, "capability": "bash",
     "description": "计算偶数之和", "setup": t_l2_sum_even, "verify": v_l2_sum_even},
    {"id": "l2-json-merge", "level": 2, "capability": "file",
     "description": "合并 JSON 文件", "setup": t_l2_json_merge, "verify": v_l2_json_merge},
    {"id": "l2-fix-syntax", "level": 2, "capability": "debug",
     "description": "修复语法错误", "setup": t_l2_fix_syntax, "verify": v_l2_fix_syntax},

    # L3 中等
    {"id": "l3-word-frequency", "level": 3, "capability": "bash",
     "description": "词频统计并排序", "setup": t_l3_word_frequency, "verify": v_l3_word_frequency},
    {"id": "l3-multi-file-refactor", "level": 3, "capability": "refactor",
     "description": "跨文件移动函数", "setup": t_l3_multi_file_refactor, "verify": v_l3_multi_file_refactor},
    {"id": "l3-file-organizer", "level": 3, "capability": "bash",
     "description": "按前缀整理文件", "setup": t_l3_file_organizer, "verify": v_l3_file_organizer},
    {"id": "l3-csv-filter", "level": 3, "capability": "file",
     "description": "CSV 条件过滤", "setup": t_l3_csv_filter, "verify": v_l3_csv_filter},
    {"id": "l3-debug-logic", "level": 3, "capability": "debug",
     "description": "修复两个逻辑 bug", "setup": t_l3_debug_logic, "verify": v_l3_debug_logic},

    # L4 进阶
    {"id": "l4-long-doc-extract", "level": 4, "capability": "context",
     "description": "长文档精准提取", "setup": t_l4_long_doc_extract, "verify": v_l4_long_doc_extract},
    {"id": "l4-config-change", "level": 4, "capability": "edit",
     "description": "精准修改配置文件", "setup": t_l4_config_change, "verify": v_l4_config_change},
    {"id": "l4-nested-search", "level": 4, "capability": "grep",
     "description": "嵌套目录搜索定位", "setup": t_l4_nested_search, "verify": v_l4_nested_search},
    {"id": "l4-data-pipeline", "level": 4, "capability": "bash",
     "description": "数据聚合分析", "setup": t_l4_data_pipeline, "verify": v_l4_data_pipeline},
    {"id": "l4-find-bug", "level": 4, "capability": "debug",
     "description": "定位并修复隐藏 bug", "setup": t_l4_find_bug, "verify": v_l4_find_bug},
    {"id": "l4-riddle-driving", "level": 4, "capability": "reasoning",
     "description": "脑筋急转弯：开车去洗车", "setup": t_l4_riddle_driving, "verify": v_l4_riddle_driving},

    # L5 专家
    {"id": "l5-complex-processing", "level": 5, "capability": "bash",
     "description": "大文件多步处理", "setup": t_l5_complex_processing, "verify": v_l5_complex_processing},
    {"id": "l5-multi-module", "level": 5, "capability": "code",
     "description": "跨模块组合实现", "setup": t_l5_multi_module, "verify": v_l5_multi_module},
    {"id": "l5-multi-file-refactor-big", "level": 5, "capability": "refactor",
     "description": "批量重命名+依赖更新", "setup": t_l5_multi_file_refactor_big, "verify": v_l5_multi_file_refactor_big},
    {"id": "l5-ambiguous-requirements", "level": 5, "capability": "plan",
     "description": "模糊需求分析", "setup": t_l5_ambiguous_requirements, "verify": v_l5_ambiguous_requirements},
    {"id": "l5-find-and-summarize", "level": 5, "capability": "grep",
     "description": "全局搜索+跨文件聚合", "setup": t_l5_find_and_summarize, "verify": v_l5_find_and_summarize},
]


def get_task(task_id: str) -> dict:
    for t in ALL_TASKS:
        if t["id"] == task_id:
            return t
    raise KeyError(task_id)


def list_tasks():
    return [t["id"] for t in ALL_TASKS]

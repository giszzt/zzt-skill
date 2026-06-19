#!/usr/bin/env python3
"""
Writing Style Skill — Observation Layer

记录 AI 生成稿（original）与用户定稿（final），为风格规则迭代提供可靠的数据基础。
零外部依赖，可在任何 Python 3.6+ 环境直接运行。

用法:
    python scripts/observe.py record-original <file> [--genre paper] [--mode A]
    python scripts/observe.py record-original --text "..." --genre paper --mode A
    python scripts/observe.py record-final <file> [--match <hash>]
    python scripts/observe.py record-final --text "..."
    python scripts/observe.py pending
    python scripts/observe.py stats [--genre paper]

文体代码 (--genre): paper | wechat | proposal | workplan
模式代码 (--mode):  A（代写）| B（润色）| C（迁移）
"""

import sys
import json
import os
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import hashlib

# Windows 控制台 UTF-8 兼容
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 路径配置 ──────────────────────────────────────────────────────────────────────
# SKILL_ROOT：skill 安装目录（用于读取 references/ 下的风格档案）
# DATA_DIR：运行时数据目录（logs 等），存放在用户 home，避开 Windows MAX_PATH 限制
SKILL_ROOT   = Path(__file__).parent.parent
DATA_DIR     = Path.home() / ".claude" / "writing-style-data"
DEFAULT_LOG_DIR = DATA_DIR / "logs"

GENRE_LABELS = {
    "paper":    "学术论文",
    "wechat":   "公众号文章",
    "proposal": "课题研究方案",
    "workplan": "工作方案/汇报",
}
MODE_LABELS = {
    "A": "代写生成",
    "B": "润色改写",
    "C": "风格迁移",
}


# ── 工具函数 ────────────────────────────────────────────────────────────────────

def get_log_dir(args=None):
    """按优先级决定日志目录：--log-dir > SKILL_LOG_DIR > 默认"""
    if args and getattr(args, "log_dir", None):
        d = Path(args.log_dir)
    elif os.environ.get("SKILL_LOG_DIR"):
        d = Path(os.environ["SKILL_LOG_DIR"])
    else:
        d = DEFAULT_LOG_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_log_file(log_dir, date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    return log_dir / f"{date_str}.jsonl"


def compute_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:8]


def get_content(args):
    """从文件路径、--text 或 stdin 读取内容"""
    if getattr(args, "text", None):
        return args.text
    if getattr(args, "stdin", False):
        return sys.stdin.read()
    if getattr(args, "file", None):
        p = Path(args.file)
        if not p.exists():
            print(f"❌ 文件不存在: {args.file}")
            sys.exit(1)
        return p.read_text(encoding="utf-8")
    return None


def read_log_entries(log_file: Path) -> list:
    if not log_file.exists():
        return []
    entries = []
    with log_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def write_log_entry(log_dir: Path, entry: dict):
    log_file = get_log_file(log_dir)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return log_file


def find_unmatched(log_dir: Path, days: int = 14) -> dict:
    """返回有 original 但没有 final 的记录，key 为 content_hash"""
    all_originals = {}
    all_matched = set()

    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        entries = read_log_entries(get_log_file(log_dir, date))
        for e in entries:
            if e["type"] == "original":
                e["_date"] = date
                all_originals[e["content_hash"]] = e
            elif e["type"] in ("final", "no-change"):
                all_matched.add(e["content_hash"])

    return {h: o for h, o in all_originals.items() if h not in all_matched}


# ── 命令：record-original ───────────────────────────────────────────────────────

def record_original(args):
    content = get_content(args)
    if not content:
        print("❌ 需要提供内容（文件路径、--text 或 --stdin）")
        sys.exit(1)

    log_dir = get_log_dir(args)
    content_hash = compute_hash(content)

    genre = getattr(args, "genre", None) or ""
    mode  = getattr(args, "mode",  None) or ""

    entry = {
        "timestamp":    datetime.now().isoformat(),
        "type":         "original",
        "content_hash": content_hash,
        "file":         str(args.file) if getattr(args, "file", None) else None,
        "content":      content,
        "char_count":   len(content),
        "context": {
            "genre":       genre,
            "genre_label": GENRE_LABELS.get(genre, genre),
            "mode":        mode,
            "mode_label":  MODE_LABELS.get(mode, mode),
        },
    }

    log_file = write_log_entry(log_dir, entry)

    genre_str = f" | 文体：{GENRE_LABELS.get(genre, genre)}" if genre else ""
    mode_str  = f" | 模式：{MODE_LABELS.get(mode, mode)}" if mode else ""
    print(f"✅ 已记录 AI 稿：{content_hash}{genre_str}{mode_str}")
    print(f"   字数：{len(content)} | 日志：{log_file}")
    return content_hash


# ── 命令：record-final ──────────────────────────────────────────────────────────

def record_final(args):
    content = get_content(args)
    if not content:
        print("❌ 需要提供最终版内容（文件路径、--text 或 --stdin）")
        sys.exit(1)

    log_dir = get_log_dir(args)
    target_hash = getattr(args, "match", None)

    # 定位对应的 original
    if target_hash:
        original = None
        for i in range(14):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            for e in read_log_entries(get_log_file(log_dir, date)):
                if e["type"] == "original" and e["content_hash"] == target_hash:
                    original = e
                    break
            if original:
                break
        if not original:
            print(f"❌ 找不到 hash={target_hash} 的原稿，请用 --match 指定正确的 hash")
            sys.exit(1)
    else:
        unmatched = find_unmatched(log_dir, 14)
        if not unmatched:
            print("❌ 没有待配对的原稿（最近 14 天内未找到未配对的 original）")
            sys.exit(1)
        # 取最近一条
        target_hash = list(unmatched.keys())[-1]
        original = unmatched[target_hash]

    is_same = content.strip() == original["content"].strip()

    # 计算字符级修改率
    orig_len  = len(original["content"])
    final_len = len(content)
    diff_pct  = ((final_len - orig_len) / max(orig_len, 1)) * 100

    # 简单计算不同字符数（逐字符比较，取较短者范围）
    changed_chars = sum(
        1 for a, b in zip(original["content"], content) if a != b
    ) + abs(final_len - orig_len)
    change_rate = changed_chars / max(orig_len, 1) * 100

    entry = {
        "timestamp":          datetime.now().isoformat(),
        "type":               "no-change" if is_same else "final",
        "content_hash":       target_hash,
        "original_content":   original["content"],
        "final_content":      content,
        "original_char_count": orig_len,
        "final_char_count":   final_len,
        "diff_pct":           round(diff_pct, 1),
        "change_rate":        round(change_rate, 1),
        "no_change":          is_same,
        "context":            original.get("context", {}),
    }

    log_file = write_log_entry(log_dir, entry)

    if is_same:
        print(f"✅ 记录定稿：{target_hash}（无修改 — 正反馈）")
    else:
        print(f"✅ 记录定稿：{target_hash}")
        print(f"   原稿 {orig_len} 字 → 定稿 {final_len} 字（{diff_pct:+.1f}%）| 修改率：{change_rate:.1f}%")
    print(f"   日志：{log_file}")
    print(f"\n   下一步：运行 python scripts/improve.py extract 分析本次修改")
    return target_hash


# ── 命令：pending ───────────────────────────────────────────────────────────────

def show_pending(args):
    log_dir  = get_log_dir(args)
    genre    = getattr(args, "genre", None)
    unmatched = find_unmatched(log_dir, 14)

    if genre:
        unmatched = {
            h: o for h, o in unmatched.items()
            if o.get("context", {}).get("genre") == genre
        }

    if not unmatched:
        print("✅ 没有待配对的原稿" + (f"（文体：{genre}）" if genre else ""))
        return

    print(f"\n⏳ {len(unmatched)} 条待配对原稿：\n")
    for h, entry in unmatched.items():
        preview = entry["content"][:80].replace("\n", " ")
        ctx = entry.get("context", {})
        genre_label = ctx.get("genre_label", ctx.get("genre", "？"))
        mode_label  = ctx.get("mode_label",  ctx.get("mode",  "？"))
        date = entry.get("_date", "？")
        print(f"  {h} | {date} | {genre_label} | 模式 {mode_label}")
        print(f"  {preview}…")
        print()


# ── 命令：stats ─────────────────────────────────────────────────────────────────

def show_stats(args):
    log_dir = get_log_dir(args)
    genre   = getattr(args, "genre", None)

    all_files = sorted(log_dir.glob("*.jsonl"))
    if not all_files:
        print("⚠️  暂无日志（尚未记录过任何 AI 稿）")
        return

    total_orig      = 0
    total_final     = 0
    total_no_change = 0
    total_changed   = 0
    by_genre: dict  = {}

    for log_file in all_files:
        entries = read_log_entries(log_file)
        for e in entries:
            g = e.get("context", {}).get("genre", "unknown")
            if genre and g != genre:
                continue
            if e["type"] == "original":
                total_orig += 1
                by_genre.setdefault(g, {"orig": 0, "final": 0, "changed": 0})
                by_genre[g]["orig"] += 1
            elif e["type"] in ("final", "no-change"):
                total_final += 1
                by_genre.setdefault(g, {"orig": 0, "final": 0, "changed": 0})
                by_genre[g]["final"] += 1
                if not e.get("no_change"):
                    total_changed += 1
                    by_genre[g]["changed"] += 1
                else:
                    total_no_change += 1

    pending = find_unmatched(log_dir, 14)
    if genre:
        pending = {h: o for h, o in pending.items()
                   if o.get("context", {}).get("genre") == genre}

    print(f"\n📊 Writing Style Skill — 观测统计")
    if genre:
        print(f"   筛选文体：{GENRE_LABELS.get(genre, genre)}")
    print(f"{'─' * 42}")
    print(f"  日志天数：{len(all_files)}")
    print(f"  AI 稿：{total_orig}")
    print(f"  已配对：{total_final}  ├ 有修改：{total_changed}  └ 无修改：{total_no_change}")
    print(f"  待配对：{len(pending)}")
    if total_final > 0:
        rate = total_changed / total_final * 100
        print(f"  整体修改率：{total_changed}/{total_final} = {rate:.0f}%")
    if len(by_genre) > 1:
        print(f"\n  按文体分布：")
        for g, d in sorted(by_genre.items()):
            label = GENRE_LABELS.get(g, g)
            r = d["changed"] / d["final"] * 100 if d["final"] else 0
            print(f"    {label:12s}  AI稿 {d['orig']:3d}  已配对 {d['final']:3d}  修改率 {r:.0f}%")
    print()


# ── CLI ──────────────────────────────────────────────────────────────────────────

def add_path_args(parser):
    parser.add_argument("--log-dir", help="自定义日志目录（覆盖默认的 references/logs/）")


def main():
    parser = argparse.ArgumentParser(
        description="Writing Style Skill — Observation Layer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="action")

    # record-original
    p_orig = sub.add_parser("record-original", help="记录 AI 生成稿")
    p_orig.add_argument("file", nargs="?", help="文件路径（与 --text/--stdin 三选一）")
    p_orig.add_argument("--text",  help="直接传入文本内容")
    p_orig.add_argument("--stdin", action="store_true", help="从 stdin 读取")
    p_orig.add_argument("--genre", choices=list(GENRE_LABELS.keys()),
                        help="文体：paper | wechat | proposal | workplan")
    p_orig.add_argument("--mode",  choices=list(MODE_LABELS.keys()),
                        help="模式：A（代写）| B（润色）| C（迁移）")
    add_path_args(p_orig)

    # record-final
    p_final = sub.add_parser("record-final", help="记录用户定稿")
    p_final.add_argument("file", nargs="?", help="文件路径")
    p_final.add_argument("--text",  help="直接传入文本内容")
    p_final.add_argument("--stdin", action="store_true", help="从 stdin 读取")
    p_final.add_argument("--match", help="指定匹配的原稿 hash（默认自动匹配最近一条）")
    add_path_args(p_final)

    # pending
    p_pend = sub.add_parser("pending", help="查看未配对的原稿")
    p_pend.add_argument("--genre", choices=list(GENRE_LABELS.keys()), help="按文体筛选")
    add_path_args(p_pend)

    # stats
    p_stats = sub.add_parser("stats", help="总体观测统计")
    p_stats.add_argument("--genre", choices=list(GENRE_LABELS.keys()), help="按文体筛选")
    add_path_args(p_stats)

    args = parser.parse_args()
    if not args.action:
        parser.print_help()
        sys.exit(1)

    {
        "record-original": record_original,
        "record-final":    record_final,
        "pending":         show_pending,
        "stats":           show_stats,
    }[args.action](args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Writing Style Skill — Improver

从人类修改记录中提取规则提案，安全地更新 style-core.md 或文体档案，并支持回滚。

用法:
    python scripts/improve.py extract [--days 7] [--genre paper]
    python scripts/improve.py show
    python scripts/improve.py apply <proposal_id> [--level P0] [--dry-run]
    python scripts/improve.py rollback [--target core|paper|wechat|proposal|workplan]
    python scripts/improve.py backup [--target core|paper|wechat|proposal|workplan]

说明:
    extract  — 读取 observe.py 日志，调用 LLM 分析修改，生成分层提案
               提案区分"core 层"（跨文体）和"文体层"（特定文体），分别指向不同目标文件
    apply    — 备份目标文件，将提案中指定置信度的规则合并写入
    rollback — 将目标文件回滚至最近一次备份
    backup   — 手动备份指定文件
"""

import sys
import json
import os
import re
import argparse
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timedelta

# Windows 控制台 UTF-8 兼容
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 路径配置 ──────────────────────────────────────────────────────────────────────
# SKILL_ROOT：skill 安装目录（读取风格档案用）
# DATA_DIR：运行时数据，存放在用户 home，避开 Windows MAX_PATH 限制
SKILL_ROOT   = Path(__file__).parent.parent
DATA_DIR     = Path.home() / ".claude" / "writing-style-data"
LOG_DIR      = DATA_DIR / "logs"
PROPOSAL_DIR = DATA_DIR / "proposals"
BACKUP_DIR   = DATA_DIR / "backups"
REFS_DIR     = SKILL_ROOT / "references"

GENRE_FILE_MAP = {
    "paper":    "style-paper.md",
    "wechat":   "style-wechat.md",
    "proposal": "style-proposal.md",
    "workplan": "style-workplan.md",
}
GENRE_LABELS = {
    "paper":    "学术论文",
    "wechat":   "公众号文章",
    "proposal": "课题研究方案",
    "workplan": "工作方案/汇报",
}

for _d in (LOG_DIR, PROPOSAL_DIR, BACKUP_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ── 工具函数 ────────────────────────────────────────────────────────────────────

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


def collect_edits(days: int = 7, genre: str = None, date_str: str = None) -> list:
    """收集有实际修改的 final 记录"""
    edits = []
    if date_str:
        dates = [date_str]
    else:
        dates = [
            (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(days)
        ]
    for date in dates:
        entries = read_log_entries(LOG_DIR / f"{date}.jsonl")
        for e in entries:
            if e["type"] == "final" and not e.get("no_change"):
                if genre and e.get("context", {}).get("genre") != genre:
                    continue
                edits.append(e)
    return edits


def read_ref_file(filename: str) -> str:
    p = REFS_DIR / filename
    return p.read_text(encoding="utf-8") if p.exists() else ""


def call_llm(prompt: str, timeout: int = 240):
    """调用 LLM CLI，优先 claude --print，fallback 到 llm CLI"""
    candidates = [
        ["claude", "--print", "--model", "claude-sonnet-4-6"],
        ["claude", "--print"],
        ["llm", "-m", "claude-sonnet"],
        ["llm"],
    ]
    custom = os.environ.get("IMPROVE_LLM_CMD")
    if custom:
        candidates.insert(0, custom.split())

    for cmd in candidates:
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    print("❌ LLM 调用失败。请确认以下任一可用：")
    print("   • Claude Code CLI：claude --print")
    print("   • llm CLI：pip install llm")
    print("   • 环境变量 IMPROVE_LLM_CMD")
    return None


def backup_file(target_path: Path):
    """备份指定文件，返回备份路径"""
    if not target_path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = target_path.stem  # e.g. "style-core" / "style-paper"
    backup_path = BACKUP_DIR / f"{stem}-{ts}.md"
    shutil.copy2(target_path, backup_path)
    print(f"   📦 已备份 {target_path.name} → {backup_path.name}")
    return backup_path


# ── 命令：extract ───────────────────────────────────────────────────────────────

def extract_improvements(args):
    days     = getattr(args, "days", 7) or 7
    genre    = getattr(args, "genre", None)
    date_str = getattr(args, "date", None)

    edits = collect_edits(days=days, genre=genre, date_str=date_str)
    if not edits:
        label = f"（文体：{genre}）" if genre else ""
        print(f"⚠️  最近 {days} 天没有已配对的修改记录{label}")
        return None

    print(f"📊 找到 {len(edits)} 条修改记录，正在分析…")

    # 读取风格档案供参照
    core_content  = read_ref_file("style-core.md")

    # 识别本批修改涉及的文体
    genres_in_edits = sorted({e.get("context", {}).get("genre", "") for e in edits if e.get("context", {}).get("genre")})
    genre_file_contents = {}
    for g in genres_in_edits:
        fname = GENRE_FILE_MAP.get(g)
        if fname:
            content = read_ref_file(fname)
            if content:
                genre_file_contents[g] = content

    # 构建修改摘要（截断避免过长）
    edit_summaries = []
    for i, e in enumerate(edits):
        orig  = e.get("original_content", "")[:2000]
        final = e.get("final_content",    "")[:2000]
        ctx   = e.get("context", {})
        edit_summaries.append({
            "index":       i + 1,
            "genre":       ctx.get("genre", "unknown"),
            "genre_label": ctx.get("genre_label", ""),
            "mode":        ctx.get("mode", "unknown"),
            "mode_label":  ctx.get("mode_label", ""),
            "change_rate": e.get("change_rate", 0),
            "original":    orig,
            "final":       final,
        })

    # 准备文体档案摘要（截取关键章节，避免过长）
    genre_context_parts = []
    for g, content in genre_file_contents.items():
        label = GENRE_LABELS.get(g, g)
        genre_context_parts.append(f"### {label}（style-{g}.md，节选）\n{content[:1500]}")
    genre_context = "\n\n".join(genre_context_parts) if genre_context_parts else "（无已建档文体）"

    proposal_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    prompt = f"""你是 Waka 的个人写作风格库（writing-style skill）的规则迭代助手。

你的任务：分析以下 AI 生成稿与用户定稿之间的差异，提取可纳入规则档案的改进提案。

## 写作风格库架构说明
本 skill 采用三层架构：
1. **style-core.md**：跨文体底层规则（思维操作、语感指纹、稳定禁忌）
2. **style-XX.md**：文体增量规则（仅在该文体中稳定出现的特征）
3. **samples/**：原文样本（不在本任务范围内）

**分层判断标准**：
- 若修改模式跨文体稳定（或从逻辑上判断是通用写作习惯）→ 提案目标：style-core.md
- 若修改模式仅在某文体中出现 → 提案目标：style-XX.md（对应文体文件）

## 现有 style-core.md（节选，避免重复提案）
{core_content[:2000]}

## 现有文体档案（节选）
{genre_context}

## 修改记录（AI 稿 vs 用户定稿）
{json.dumps(edit_summaries, ensure_ascii=False, indent=2)}

## 输出要求
1. 对比 original 和 final，识别系统性修改模式（非一次性内容调整）
2. 不要提取已在 style-core.md 或文体档案中明确覆盖的规则
3. 每条提案必须：可执行、有具体证据、有明确目标文件和写入章节
4. 置信度评定：P0（本批≥2次或高强度单次）| P1（1次但模式清晰）| P2（弱信号）

## 输出格式（严格遵循，不要添加额外内容）

---
id: {proposal_id}
date: {datetime.now().strftime("%Y-%m-%d")}
genre: {",".join(genres_in_edits) if genres_in_edits else "unknown"}
edit_count: {len(edits)}
status: pending
---

## Core 层提案（→ style-core.md）

### P0

### P1

### P2

## 文体层提案

### [文体名]（→ style-XX.md）

#### P0

#### P1

#### P2

---
每条提案格式：
- **[规则描述，一句话可执行]**
  证据：[引用具体修改片段]
  写入章节：[目标章节名，如"三、稳定禁忌 > A. 结构禁忌"]

若某一分区无内容，写"（本次无）"。
"""

    output = call_llm(prompt)
    if not output:
        return None

    proposal_file = PROPOSAL_DIR / f"{proposal_id}.md"
    proposal_file.write_text(output, encoding="utf-8")

    print(f"✅ 提案已生成：{proposal_id}")
    print(f"   文件：{proposal_file}")
    print(f"\n{'─'*50}")
    preview = output[:2000]
    print(preview)
    if len(output) > 2000:
        print(f"\n… （完整内容见文件，共 {len(output)} 字）")
    print(f"\n   应用提案：python scripts/improve.py apply {proposal_id}")
    return proposal_id


# ── 命令：show ──────────────────────────────────────────────────────────────────

def show_proposals(args):
    proposals = sorted(PROPOSAL_DIR.glob("*.md"), reverse=True)
    if not proposals:
        print("⚠️  暂无提案（先运行 extract 生成）")
        return

    print(f"\n📋 共 {len(proposals)} 个提案：\n")
    for p in proposals:
        content = p.read_text(encoding="utf-8")
        # 解析 frontmatter
        status = "pending"
        genre  = ""
        edit_count = ""
        for line in content.split("\n")[:10]:
            if line.startswith("status:"):
                status = line.split(":", 1)[1].strip()
            elif line.startswith("genre:"):
                genre = line.split(":", 1)[1].strip()
            elif line.startswith("edit_count:"):
                edit_count = line.split(":", 1)[1].strip()
        icon = {"pending": "⏳", "applied": "✅", "rejected": "❌",
                "partial": "🔶"}.get(status.split("(")[0].strip(), "❓")
        genre_str = f" | {genre}" if genre else ""
        count_str = f" | {edit_count} 条修改" if edit_count else ""
        print(f"  {icon} {p.stem}{genre_str}{count_str} — {status}")


# ── 命令：apply ─────────────────────────────────────────────────────────────────

def apply_proposal(args):
    proposal_id = args.proposal_id
    proposal_file = PROPOSAL_DIR / f"{proposal_id}.md"
    if not proposal_file.exists():
        print(f"❌ 提案不存在：{proposal_id}")
        print(f"   可用提案：python scripts/improve.py show")
        sys.exit(1)

    level    = getattr(args, "level", "P0") or "P0"
    dry_run  = getattr(args, "dry_run", False)

    proposal_content = proposal_file.read_text(encoding="utf-8")

    # 解析提案中的目标文件
    # Core 层提案 → style-core.md
    # 文体层提案 → style-XX.md
    targets_needed = []
    if "## Core 层提案" in proposal_content and "（本次无）" not in _section_content(proposal_content, "## Core 层提案"):
        targets_needed.append(("core", REFS_DIR / "style-core.md"))

    for genre, fname in GENRE_FILE_MAP.items():
        label = GENRE_LABELS.get(genre, genre)
        marker = f"### {label}（→ style-{genre}.md）"
        if marker in proposal_content:
            section = _section_content(proposal_content, marker)
            if section and "（本次无）" not in section:
                fpath = REFS_DIR / fname
                if fpath.exists():
                    targets_needed.append((genre, fpath))
                else:
                    print(f"⚠️  {fname} 尚未建档，跳过该文体层提案")

    if not targets_needed:
        print("ℹ️  提案中无需要应用的内容（所有分区均为空或目标文件不存在）")
        return

    print(f"\n📝 将应用级别 ≥{level} 的提案至：")
    for key, path in targets_needed:
        print(f"   • {path.name}")

    if dry_run:
        print("\n[dry-run 模式，不写入文件]")
        return

    # 逐目标文件：备份 → LLM 合并 → 写入
    applied_targets = []
    for key, target_path in targets_needed:
        print(f"\n🔄 处理 {target_path.name}…")
        backup_file(target_path)

        current = target_path.read_text(encoding="utf-8")

        # 确定要合并的提案章节
        if key == "core":
            section_header = "## Core 层提案（→ style-core.md）"
        else:
            label = GENRE_LABELS.get(key, key)
            section_header = f"### {label}（→ style-{key}.md）"

        section_text = _section_content(proposal_content, section_header)

        prompt = f"""你是 Waka 个人写作风格库的规则更新助手。

将以下提案中**{level} 及以上置信度**的规则合并写入目标文件。

合并规则：
1. 新禁忌 → 写入"稳定禁忌"或"本文体特有规则"的对应子节
2. 新特征 → 写入最匹配的章节（思维操作/语感指纹/正向不变量等）
3. 不删除现有规则，不改变文件整体结构
4. 若新规则是现有规则的细化，在现有条目下追加说明，不新增条目
5. 在文件末尾的迭代日志/版本记录中追加本次变更（日期、变更简述）

## 目标文件当前内容
{current}

## 本次提案（{section_header}）
{section_text}

请输出更新后的完整文件内容。不要用代码块包裹，直接输出文件文本。"""

        updated = call_llm(prompt, timeout=300)
        if not updated:
            print(f"   ❌ {target_path.name} 合并失败，已保留备份")
            continue

        target_path.write_text(updated, encoding="utf-8")
        applied_targets.append(target_path.name)
        print(f"   ✅ {target_path.name} 已更新")

    if applied_targets:
        # 更新提案状态
        ts = datetime.now().strftime("%Y-%m-%d")
        new_status = f"applied ({ts}): {', '.join(applied_targets)}"
        updated_proposal = re.sub(r"^status: .+$", f"status: {new_status}",
                                   proposal_content, flags=re.MULTILINE)
        proposal_file.write_text(updated_proposal, encoding="utf-8")

        print(f"\n✅ 完成。已更新：{', '.join(applied_targets)}")
        print(f"   如需回滚：python scripts/improve.py rollback --target <core|paper|…>")
    else:
        print("\n⚠️  没有文件被成功更新")


def _section_content(text: str, header: str) -> str:
    """提取从 header 开始到下一个同级或更高级标题之前的内容"""
    idx = text.find(header)
    if idx == -1:
        return ""
    # 找下一个同级标题（## 或 ###）
    level = len(re.match(r"^(#+)", header).group(1))
    pattern = r"^#{1," + str(level) + r"} "
    after = text[idx + len(header):]
    lines = after.split("\n")
    result_lines = []
    for line in lines[1:]:  # 跳过 header 行本身
        if re.match(pattern, line) and line.strip() != header.strip():
            break
        result_lines.append(line)
    return "\n".join(result_lines).strip()


# ── 命令：rollback ──────────────────────────────────────────────────────────────

def rollback(args):
    target_key = getattr(args, "target", None)

    if target_key == "core" or target_key is None:
        _rollback_file("style-core")

    if target_key in GENRE_FILE_MAP:
        _rollback_file(f"style-{target_key}")
    elif target_key is not None and target_key != "core":
        print(f"❌ 未知目标：{target_key}")
        print(f"   可用值：core | {' | '.join(GENRE_FILE_MAP.keys())}")
        sys.exit(1)


def _rollback_file(stem: str):
    """将 stem 对应的文件回滚至最新备份"""
    backups = sorted(BACKUP_DIR.glob(f"{stem}-*.md"), reverse=True)
    if not backups:
        print(f"❌ 没有找到 {stem} 的备份文件")
        return

    latest  = backups[0]
    target  = REFS_DIR / f"{stem}.md"

    # 保存当前版本为紧急备份
    if target.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        emergency = BACKUP_DIR / f"{stem}-pre-rollback-{ts}.md"
        shutil.copy2(target, emergency)
        print(f"   📦 当前版本已另存为 {emergency.name}")

    shutil.copy2(latest, target)
    print(f"✅ {stem}.md 已回滚至 {latest.name}")


# ── 命令：backup ────────────────────────────────────────────────────────────────

def manual_backup(args):
    target_key = getattr(args, "target", None)

    if not target_key:
        # 备份所有存在的档案
        for fname in ["style-core.md"] + list(GENRE_FILE_MAP.values()):
            p = REFS_DIR / fname
            if p.exists():
                backup_file(p)
        return

    if target_key == "core":
        p = REFS_DIR / "style-core.md"
    elif target_key in GENRE_FILE_MAP:
        p = REFS_DIR / GENRE_FILE_MAP[target_key]
    else:
        print(f"❌ 未知目标：{target_key}")
        sys.exit(1)

    if not p.exists():
        print(f"⚠️  {p.name} 尚不存在，跳过")
        return
    backup_file(p)


# ── CLI ──────────────────────────────────────────────────────────────────────────

TARGET_CHOICES = ["core"] + list(GENRE_FILE_MAP.keys())


def main():
    parser = argparse.ArgumentParser(
        description="Writing Style Skill — Improver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="action")

    # extract
    p_ext = sub.add_parser("extract", help="从修改记录中提取规则提案")
    p_ext.add_argument("--days",  type=int, default=7, help="分析最近 N 天的记录（默认 7）")
    p_ext.add_argument("--date",  help="只分析指定日期（格式 YYYY-MM-DD）")
    p_ext.add_argument("--genre", choices=list(GENRE_FILE_MAP.keys()), help="只分析指定文体")

    # show
    sub.add_parser("show", help="查看所有提案")

    # apply
    p_apply = sub.add_parser("apply", help="将提案规则应用至对应档案")
    p_apply.add_argument("proposal_id", help="提案 ID（从 show 命令获取）")
    p_apply.add_argument("--level",   default="P0", choices=["P0", "P1", "P2"],
                         help="应用的最低置信度（默认 P0）")
    p_apply.add_argument("--dry-run", action="store_true", help="仅预览，不写入")

    # rollback
    p_rb = sub.add_parser("rollback", help="将档案回滚至最近备份")
    p_rb.add_argument("--target", choices=TARGET_CHOICES,
                      help=f"目标文件（{' | '.join(TARGET_CHOICES)}），不填则回滚 core")

    # backup
    p_bk = sub.add_parser("backup", help="手动备份档案文件")
    p_bk.add_argument("--target", choices=TARGET_CHOICES,
                      help="指定文件，不填则备份所有现有档案")

    args = parser.parse_args()
    if not args.action:
        parser.print_help()
        sys.exit(1)

    {
        "extract":  extract_improvements,
        "show":     show_proposals,
        "apply":    apply_proposal,
        "rollback": rollback,
        "backup":   manual_backup,
    }[args.action](args)


if __name__ == "__main__":
    main()

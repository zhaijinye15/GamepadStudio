"""把 docs/*.md 渲染成单文件 HTML（供开始菜单「使用说明」使用）.

只实现本项目文档用到的 Markdown 子集：标题、段落、无序/有序列表、表格、
围栏代码块、图片、行内代码与加粗、引用、分隔线。无第三方依赖。
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{
    margin: 0 auto; padding: 48px 28px 80px; max-width: 880px;
    background: #0e1116; color: #e6edf3;
    font: 15px/1.85 "Microsoft YaHei","PingFang SC","Noto Sans CJK SC",system-ui,sans-serif;
  }}
  h1 {{ font-size: 30px; margin: 0 0 8px; letter-spacing: .5px; }}
  h2 {{ font-size: 20px; margin: 42px 0 14px; padding-bottom: 8px; border-bottom: 1px solid #2c3746; }}
  h3 {{ font-size: 16px; margin: 28px 0 10px; color: #40dca0; }}
  p {{ margin: 10px 0; color: #b9c6d3; }}
  a {{ color: #56a5ff; }}
  code {{ background: #1c2430; padding: 2px 6px; border-radius: 4px; color: #7fe7c4; font-size: 13px; }}
  pre {{ background: #161d27; border: 1px solid #2c3746; border-radius: 10px; padding: 14px 16px; overflow-x: auto; }}
  pre code {{ background: none; padding: 0; color: #cfd9e4; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 14px; }}
  th, td {{ border: 1px solid #2c3746; padding: 9px 12px; text-align: left; vertical-align: top; }}
  th {{ background: #1c2430; color: #e6edf3; font-weight: 600; }}
  tr:nth-child(even) td {{ background: #131a23; }}
  ul, ol {{ margin: 10px 0 10px 22px; color: #b9c6d3; }}
  li {{ margin: 6px 0; }}
  img {{ max-width: 100%; border-radius: 12px; border: 1px solid #2c3746; margin: 14px 0; display: block; }}
  blockquote {{ margin: 14px 0; padding: 10px 16px; border-left: 3px solid #40dca0; background: #161d27; color: #9fb0c0; }}
  hr {{ border: none; border-top: 1px solid #2c3746; margin: 26px 0; }}
  .footer {{ margin-top: 56px; color: #68767f; font-size: 12px; }}
</style>
</head>
<body>
{body}
<p class="footer">Gamepad Studio · 文档由 docs/build_docs.py 从 Markdown 生成</p>
</body>
</html>
"""


def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def render_table(lines: list[str]) -> str:
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines[2:]]
    output = ["<table><thead><tr>"]
    output += [f"<th>{inline(cell)}</th>" for cell in header]
    output.append("</tr></thead><tbody>")
    for row in rows:
        output.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>")
    output.append("</tbody></table>")
    return "".join(output)


def convert(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    list_mode: str | None = None

    def close_list() -> None:
        nonlocal list_mode
        if list_mode:
            output.append(f"</{list_mode}>")
            list_mode = None

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            close_list()
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            output.append(f"<pre><code>{html.escape(chr(10).join(block))}</code></pre>")
            continue

        if not stripped:
            close_list()
            index += 1
            continue

        if stripped.startswith("|") and index + 1 < len(lines) and set(lines[index + 1].strip()) <= set("|-: "):
            close_list()
            table_lines = [line]
            index += 1
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1
            output.append(render_table(table_lines))
            continue

        image = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if image:
            close_list()
            alt, src = image.group(1), image.group(2)
            output.append(f'<img src="{src}" alt="{alt}">')
            index += 1
            continue

        heading = re.match(r"(#{1,6})\s+(.*)", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            output.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        if stripped.startswith(">"):
            close_list()
            quote: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip().lstrip(">").strip())
                index += 1
            output.append(f"<blockquote>{inline(' '.join(quote))}</blockquote>")
            continue

        if re.match(r"-\s+", stripped) or re.match(r"•\s+", stripped):
            if list_mode != "ul":
                close_list()
                output.append("<ul>")
                list_mode = "ul"
            output.append(f"<li>{inline(re.sub(r'^[-•]\s+', '', stripped))}</li>")
            index += 1
            continue

        ordered = re.match(r"\d+\.\s+(.*)", stripped)
        if ordered:
            if list_mode != "ol":
                close_list()
                output.append("<ol>")
                list_mode = "ol"
            output.append(f"<li>{inline(ordered.group(1))}</li>")
            index += 1
            continue

        if stripped in ("---", "***"):
            close_list()
            output.append("<hr>")
            index += 1
            continue

        close_list()
        paragraph: list[str] = [stripped]
        index += 1
        while index < len(lines):
            nxt = lines[index].strip()
            if (not nxt or nxt.startswith(("#", "|", "```", ">", "- ", "• "))
                    or re.match(r"\d+\.\s+", nxt) or nxt in ("---", "***")):
                break
            paragraph.append(nxt)
            index += 1
        output.append(f"<p>{inline(' '.join(paragraph))}</p>")

    close_list()
    return "\n".join(output)


def build(markdown_path: Path, output_path: Path) -> None:
    markdown = markdown_path.read_text(encoding="utf-8")
    title = markdown_path.stem
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    body = convert(markdown)
    output_path.write_text(TEMPLATE.format(title=html.escape(title), body=body), encoding="utf-8")
    print(f"{markdown_path.name} -> {output_path.name}")


def main() -> int:
    targets = sys.argv[1:] or ["使用说明.md", "架构与打包.md"]
    for name in targets:
        source = DOCS_DIR / name
        if not source.exists():
            print(f"跳过（不存在）：{name}")
            continue
        build(source, source.with_suffix(".html"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

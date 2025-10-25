# scripts/render_report.py
import sys
import pathlib

try:
    import markdown  # pip install markdown
except ImportError:
    sys.stderr.write("Missing 'markdown' package. Add 'markdown' to requirements.txt\n")
    sys.exit(1)

STYLE = """
<style>
body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin:0; padding:0; }
.main { max-width: 980px; margin: 24px auto; padding: 0 16px; }
table { border-collapse: collapse; width:100%; font-size: 14px; }
th, td { border: 1px solid #eee; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #fafafa; }
code, pre { background:#f6f7f9; border-radius:6px; padding:2px 4px; }
h1,h2,h3 { margin-top: 1.2em; }
</style>
"""

HTML_WRAP = """<!doctype html>
<html><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Daily Alert Report</title>
{style}
</head><body>
<div class="main">
{body}
</div>
</body></html>
"""

def main(inp, outp):
    md = pathlib.Path(inp).read_text(encoding="utf-8")
    html_body = markdown.markdown(md, extensions=["tables", "fenced_code"])
    doc = HTML_WRAP.format(style=STYLE, body=html_body)
    pathlib.Path(outp).write_text(doc, encoding="utf-8")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/render_report.py <input.md> <output.html>")
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])

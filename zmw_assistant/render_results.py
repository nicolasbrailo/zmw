#!/usr/bin/env python3
"""Parse playground.log and render an HTML results table."""

import re
import sys
from html import escape


def parse_log(path):
    """Parse playground.log into header info, prompt results, and system context."""
    header = {}
    results = []  # [{prompt, reply, expected, elapsed, ok}]
    context = ''
    score = ''

    in_context = False
    with open(path) as f:
        for line in f:
            line = line.rstrip('\n')

            m = re.match(r'^Model:\s+(.+)$', line)
            if m:
                header['model'] = m.group(1)
                continue

            m = re.match(r'^Score:\s+(.+)$', line)
            if m:
                score = m.group(1)
                continue

            m = re.match(r'^\s+\[(OK|FAIL)\] \(([^)]+)\) (.+)$', line)
            if m:
                in_context = False
                results.append({
                    'ok': m.group(1) == 'OK',
                    'elapsed': m.group(2),
                    'prompt': m.group(3),
                    'reply': '',
                    'expected': '',
                })
                continue

            m = re.match(r'^\s+Got:\s+(.+)$', line)
            if m and results:
                results[-1]['reply'] = m.group(1)
                continue

            m = re.match(r'^\s+Expected:\s+(.+)$', line)
            if m and results:
                results[-1]['expected'] = m.group(1)
                continue

            if line.startswith('System context:'):
                in_context = True
                continue

            if in_context:
                context += line + '\n'

    return header, results, score, context


def render_html(header, results, score, context):
    """Render parsed results to an HTML string."""
    if not results:
        return '<html><body>No data</body></html>'

    parts = []
    parts.append('''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Playground Results</title>
<style>
body { font-family: monospace; font-size: 13px; margin: 20px; }
h2 { margin-bottom: 5px; }
.meta { color: #666; margin-bottom: 15px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ccc; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #f0f0f0; position: sticky; top: 0; }
tr.ok { }
tr.fail td { background: #fff0f0; }
.elapsed { color: #999; font-size: 11px; }
.score { font-size: 16px; font-weight: bold; margin: 15px 0; }
.score .pass { color: #2a2; }
.score .fail { color: #c33; }
#context { margin-top: 30px; padding: 15px; background: #f8f8f8; border: 1px solid #ddd; white-space: pre-wrap; }
</style>
</head><body>
<h2>Playground Results</h2>
''')

    model = header.get('model', '?')
    parts.append(f'<div class="meta">Model: {escape(model)}</div>\n')

    passed = sum(1 for r in results if r['ok'])
    total = len(results)
    cls = 'pass' if passed == total else 'fail'
    parts.append(f'<div class="score"><span class="{cls}">{score}</span></div>\n')

    parts.append('<table>\n<tr><th>#</th><th>Prompt</th><th>Got</th><th>Expected</th><th>Time</th><th></th></tr>\n')

    for i, r in enumerate(results):
        row_cls = 'ok' if r['ok'] else 'fail'
        status = 'OK' if r['ok'] else 'FAIL'
        parts.append(
            f'<tr class="{row_cls}">'
            f'<td>{i+1}</td>'
            f'<td>{escape(r["prompt"])}</td>'
            f'<td>{escape(r["reply"])}</td>'
            f'<td>{escape(r["expected"])}</td>'
            f'<td class="elapsed">{escape(r["elapsed"])}</td>'
            f'<td>{status}</td>'
            f'</tr>\n')

    parts.append('</table>\n')
    parts.append(f'<div id="context"><b>System context:</b>\n{escape(context)}</div>\n')
    parts.append('</body></html>')
    return ''.join(parts)


if __name__ == '__main__':
    log_path = sys.argv[1] if len(sys.argv) > 1 else 'playground.log'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'results.html'
    header, results, score, context = parse_log(log_path)
    html = render_html(header, results, score, context)
    with open(out_path, 'w') as f:
        f.write(html)
    print(f'Wrote {out_path} ({len(results)} prompts)')

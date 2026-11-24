#!/usr/bin/env python3
"""Generates a service's systemd unit: unit_template.service plus the service's systemd.conf, if it has one.

In systemd.conf, @RUN@, @SRC@ and @ZMW@ are the service's run dir, its source dir and the ZMW root, and Bind*= lines can
bind paths from config.json: `BindPaths=@CFG:rec_path@` (the key must be set; it can hold a list of paths). Paths in
the run dir or the shared scratch dir are visible anyway, so they're skipped; the rest must exist. On any problem it
exits with an error and writes nothing. Without --out it only validates.
"""
import argparse
import json
import os
import re
import sys

ZMW_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
CFG_RE = re.compile(r'@CFG:(\w+)@')


def source_libs(src):
    """Dirs the service's venv installs from the source tree: the editable paths in its Pipfile"""
    pipfile = os.path.join(src, 'Pipfile')
    if not os.path.exists(pipfile):
        return []
    with open(pipfile, encoding='utf-8') as fp:
        return sorted({os.path.realpath(os.path.join(src, p)) for p in re.findall(r'path = "([^"]+)"', fp.read())})


def expand_cfg(line, cfg, run, svc_tmp):
    """A Bind*= line with @CFG:key@ placeholders, with the paths they name in config.json"""
    directive = line.split('=', 1)[0]
    paths = []
    for key in CFG_RE.findall(line):
        if key not in cfg:
            sys.exit(f"{directive} wants config.json's '{key}', which isn't set")
        val = cfg.get(key) or []
        # Relative paths are relative to the service's working dir, its run dir
        paths += [os.path.normpath(os.path.join(run, p)) for p in (val if isinstance(val, list) else [val])]
    binds = [p for p in paths if not any(p == d or p.startswith(d + '/') for d in (run, svc_tmp))]
    for path in binds:
        if not os.path.exists(path):
            sys.exit(f"{directive} {path} (from config.json) doesn't exist: create it, or fix config.json")
    return f"{directive}={' '.join(binds)}" if binds else f"# {line} (nothing to bind)"


def generate(args, cfg):
    subst = {'@NAME@': args.name, '@RUN@': args.run, '@SRC@': args.src, '@ZMW@': ZMW_ROOT, '@USER@': args.user,
             '@EXEC_START@': args.exec_start, '@SVC_TMP@': args.svc_tmp, '@SRC_LIBS@': ' '.join(source_libs(args.src))}
    with open(os.path.join(ZMW_ROOT, 'scripts', 'unit_template.service'), encoding='utf-8') as fp:
        unit = fp.read()
    conf_path = os.path.join(args.src, 'systemd.conf')
    if os.path.exists(conf_path):
        with open(conf_path, encoding='utf-8') as fp:
            lines = [expand_cfg(ln, cfg, args.run, args.svc_tmp) if '@CFG' in ln and not ln.startswith('#') else ln
                     for ln in fp.read().splitlines()]
        unit += f"\n# From {conf_path}\n" + '\n'.join(lines) + '\n'
    for placeholder, val in subst.items():
        unit = unit.replace(placeholder, val)
    return unit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('name', 'src', 'run', 'user', 'exec-start', 'svc-tmp', 'config', 'out'):
        parser.add_argument(f'--{arg}', required=arg not in ('config', 'out'))
    args = parser.parse_args()
    config = args.config or os.path.join(args.run, 'config.json')
    cfg = {}
    if os.path.exists(config):
        with open(config, encoding='utf-8') as fp:
            cfg = json.load(fp)
    try:
        unit = generate(args, cfg)
    except SystemExit as ex:
        sys.exit(f"Can't generate the unit for {args.name}: {ex}")
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fp:
            fp.write(unit)


if __name__ == '__main__':
    main()

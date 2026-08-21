#!/usr/bin/env python3
"""
M0.1 corpus scan: find .bbappend files in a meta-ros checkout that exist
(wholly or partly) to add a missing build/buildtool dependency, and classify
what REP-149 tag origin each addition looks like.

Heuristic: a bbappend "adds a missing dependency" if it appends to one of
DEPENDS / ROS_BUILD_DEPENDS / ROS_BUILDTOOL_DEPENDS / ROS_EXPORT_DEPENDS /
ROS_BUILDTOOL_EXPORT_DEPENDS via `+=` or `:append`. It is "pure" if, after
stripping comments/blank lines/copyright header, the only statements left
are such additions (optionally plus a bare `BBCLASSEXTEND` line) -- i.e.
nothing else the bbappend could plausibly exist for.

REP-149 tag origin is inferred from which variable got the addition and
whether the added token is native-suffixed:
  * ROS_BUILD_DEPENDS / DEPENDS, non-native token   -> build_export_depend gap
  * ROS_BUILD_DEPENDS / DEPENDS, native-suffixed     -> buildtool_export_depend
                                                         gap reaching target
                                                         recipe via a native
                                                         tool (the vision-msgs
                                                         pattern)
  * ROS_BUILDTOOL_DEPENDS, native-suffixed           -> buildtool_export_depend
                                                         gap (the direct case)
  * ROS_EXPORT_DEPENDS                               -> build_export_depend
                                                         gap, re-declared as
                                                         if direct
  * ROS_BUILDTOOL_EXPORT_DEPENDS                     -> buildtool_export_depend
                                                         gap, re-declared as
                                                         if direct
"""
import csv
import re
import sys
from pathlib import Path

DEP_VAR_RE = re.compile(
    r'^\s*(DEPENDS|ROS_BUILD_DEPENDS|ROS_BUILDTOOL_DEPENDS|'
    r'ROS_EXPORT_DEPENDS|ROS_BUILDTOOL_EXPORT_DEPENDS)'
    r'\s*(?::append(?::class-\w+)?|\+=)\s*=?\s*"(.*?)"',
    re.MULTILINE | re.DOTALL,
)
REMOVE_RE = re.compile(r'^\s*\w+:remove\s*=', re.MULTILINE)
COMMENT_OR_BLANK = re.compile(r'^\s*(#.*)?$')
BBCLASSEXTEND_RE = re.compile(r'^\s*BBCLASSEXTEND\s*=')


def classify_tokens(var, tokens):
    out = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        is_native = t.endswith('-native') or t.endswith('-nativesdk')
        if var in ('ROS_BUILDTOOL_DEPENDS',):
            origin = 'buildtool_export_depend (direct-native gap)'
        elif var in ('ROS_BUILDTOOL_EXPORT_DEPENDS',):
            origin = 'buildtool_export_depend (re-declared as direct)'
        elif var in ('ROS_EXPORT_DEPENDS',):
            origin = 'build_export_depend (re-declared as direct)'
        elif var in ('DEPENDS', 'ROS_BUILD_DEPENDS'):
            origin = ('buildtool_export_depend (native tool reached via '
                      'target recipe)' if is_native
                      else 'build_export_depend (target-space gap)')
        else:
            origin = 'unknown'
        out.append((t, origin))
    return out


def is_pure(text):
    """True if, minus comments/blank lines, only dep-adds + BBCLASSEXTEND
    remain."""
    stripped = DEP_VAR_RE.sub('', text)
    for line in stripped.splitlines():
        if COMMENT_OR_BLANK.match(line):
            continue
        if BBCLASSEXTEND_RE.match(line):
            continue
        return False
    return True


def pkg_name_from_path(path, root):
    rel = path.relative_to(root)
    stem = path.stem  # e.g. "vision-msgs_4.1.1-3" or "actionlib_%"
    pkg = re.sub(r'_[^_]*$', '', stem)  # drop trailing _<version-or-%>
    parts = rel.parts
    # meta-ros2-jazzy/recipes-bbappends/<component>/<file>.bbappend
    distro_dir = parts[0]
    return distro_dir, pkg


def main():
    root = Path(sys.argv[1])
    out_csv = Path(sys.argv[2])
    rows = []
    total = 0
    with_deps = 0
    pure = 0
    for path in sorted(root.glob('**/*.bbappend')):
        # generated-recipes/ is generator OUTPUT, not a hand-written fix.
        if 'generated-recipes' in path.parts:
            continue
        total += 1
        text = path.read_text(errors='replace')
        matches = DEP_VAR_RE.findall(text)
        if not matches:
            continue
        with_deps += 1
        pure_flag = is_pure(text)
        if pure_flag:
            pure += 1
        distro_dir, pkg = pkg_name_from_path(path, root)
        for var, body in matches:
            tokens = [t for t in re.split(r'\s+', body) if t and t != '\\']
            for token, origin in classify_tokens(var, tokens):
                rows.append({
                    'distro_dir': distro_dir,
                    'package': pkg,
                    'bbappend': str(path.relative_to(root)),
                    'pure': pure_flag,
                    'variable': var,
                    'added_dep': token,
                    'inferred_origin': origin,
                })

    with open(out_csv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=[
            'distro_dir', 'package', 'bbappend', 'pure', 'variable',
            'added_dep', 'inferred_origin'])
        w.writeheader()
        w.writerows(rows)

    print(f"total bbappends (excl. generated-recipes): {total}")
    print(f"bbappends touching a DEPENDS-family var: {with_deps}")
    print(f"pure (solely a dependency add): {pure}")
    print(f"rows (one per added token): {len(rows)}")
    print(f"wrote {out_csv}")


if __name__ == '__main__':
    main()

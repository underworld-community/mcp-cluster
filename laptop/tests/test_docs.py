#!/usr/bin/python3 -I
"""The repository docs' generated and checked parts, against their sources, plus every relative link in the docs.

  /usr/bin/python3 -I tests/test_docs.py            check: any drift is a FAIL (run_all runs this)
  /usr/bin/python3 -I tests/test_docs.py --write    rewrite the generated blocks from their sources

- Protected paths (ADMIN.md): laptop/managed-settings.json, admin.SETTINGS, kaiju/policies/human.json and agent.json.
- Caps (README.md): ADMIN in uw3hpc/sites.py.
- File layout (ADMIN.md, hand-written): it must name every file and folder in the repository, and nothing else.
- Links: every relative link in every .md file must reach a file, and its #anchor a heading there.
Always this checkout: the docs and the Kaiju policies are not part of an installed copy.
"""
import difflib
import fnmatch
import json
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import testkit  # noqa: E402 (needs the path above)

ROOT = testkit.use(None)
REPO = os.path.dirname(ROOT)
README, ADMIN_MD = os.path.join(REPO, "README.md"), os.path.join(REPO, "ADMIN.md")
from uw3hpc import admin, sites  # noqa: E402 (needs ROOT on sys.path)

# Not in the repository: git ignores them (.gitignore), the live kit makes results/ as it runs, and Claude Code makes
# .claude/.cc-writes in the folders it works in (the repository keeps no .claude folder).
IGNORED = {".git", ".DS_Store", "__pycache__", "laptop/tests/live/results", ".claude"}
fails = []


def check(label, ok, detail=""):
    print("%s %s%s" % ("PASS" if ok else "FAIL", label, "" if ok else "\n" + detail))
    fails.extend([] if ok else [label])


def load(rel):
    with open(os.path.join(REPO, rel)) as f:
        return json.load(f)


def norm(p):
    # The helper fills @HOME@ and @AGENT@ per account; a rule's "//" is the root and "/**" everything below.
    p = p.replace("@HOME@", "~").replace("@AGENT@", "<you>-agent")
    p = p[1:] if p.startswith("//") else p
    return re.sub(r"/(\*\*)?$", "", p)


def rules(*settings):
    """Path rules by kind, lists merged across sources as Claude Code merges them."""
    out = {"Read": [], "Edit": [], "Ask": [], "denyRead": [], "denyWrite": []}
    for s in settings:
        for rule in (s.get("permissions") or {}).get("deny") or []:
            m = re.fullmatch(r"(Read|Edit)\((.+)\)", rule)
            if m:
                out[m.group(1)].append(norm(m.group(2)))
        for rule in (s.get("permissions") or {}).get("ask") or []:
            m = re.fullmatch(r"Edit\((.+)\)", rule)
            if m:
                out["Ask"].append(norm(m.group(1)))
        fs = (s.get("sandbox") or {}).get("filesystem") or {}
        for k in ("denyRead", "denyWrite"):
            out[k] += [norm(p) for p in fs.get(k) or []]
    return out


def covers(rule, path):
    # "**/x" is relative to the folder Claude starts in, so it never covers a ~ or absolute path, nor they it.
    if rule.startswith("**/") != path.startswith("**/"):
        return False
    return path == rule or path.startswith(rule + "/") or fnmatch.fnmatchcase(path, rule)


def cell(col, path):
    # Claude Code merges Read and Edit deny rules into the sandbox, so "edit denied" covers sandboxed commands too.
    has = {k: any(covers(r, path) for r in v) for k, v in col.items()}
    words = ["read + edit denied" if has["Read"] and has["Edit"] else "read denied" if has["Read"] else
             "edit denied" if has["Edit"] else "edit asks" if has["Ask"] else ""]
    words += ["sandbox read-denied"] if has["denyRead"] and not has["Read"] else []
    words += ["sandbox write-denied"] if has["denyWrite"] and not has["Edit"] else []
    return ", ".join(w for w in words if w)


def paths_table():
    cols = [rules(load("laptop/managed-settings.json"), admin.SETTINGS), rules(load("kaiju/policies/human.json")),
            rules(load("kaiju/policies/agent.json"))]
    order = []
    for p in (p for col in cols for k in ("Read", "Edit", "Ask", "denyRead", "denyWrite") for p in col[k]):
        order += [] if p in order else [p]
    groups = {}
    for p in order:  # paths with the same protection everywhere share a row, in order of first appearance
        groups.setdefault(tuple(cell(c, p) for c in cols), []).append(p)
    lines = ["| Path | Laptop | Kaiju member | Kaiju agent |", "|---|---|---|---|"]
    lines += ["| %s | %s |" % (", ".join("`%s`" % p for p in ps), " | ".join(sig)) for sig, ps in groups.items()]
    return "\n".join(lines)


def caps_table():
    a, cols = sites.ADMIN, sites.ALL
    lines = ["| Cap | %s |" % " | ".join(cols), "|---|%s" % ("---|" * len(cols)),
             "| status: asks the scheduler at most once per | %s |" % " | ".join(
                 "%d s" % a["sites"][c]["floor"] for c in cols), "",
             "| submit: queue | Longest walltime, by cores per job | Nodes |", "|---|---|---|"]
    for c in sites.HUMAN:
        for name, (node_cores, node_gb, bands) in a["sites"][c]["queues"].items():
            lines.append("| %s%s | %s | %d cores, %d GB%s |" % (
                c, " `%s`" % name if name else "", ", ".join("%s up to %d" % (w, n) for n, w in bands), node_cores,
                node_gb, "" if c == "gadi" else " (`memory_gb` is per node)"))
    lines += ["", "Every site: `submit` up to %d jobs and `max_core_hours` (default %d) a call; `get` %d MB a file and "
              "%d MB a call; `put` %d MB and %d files; `wait` up to %d min; `run` %d s and %d chars; `task` prompts %d "
              "chars; text back to Claude %d chars." % (
                  a["batch_jobs"], a["core_hours"], a["get_file_mb"], a["get_call_mb"], a["put_mb"], a["put_files"],
                  a["wait_max_min"], a["remote_s"], a["command_chars"], a["prompt_chars"], a["out_chars"])]
    return "\n".join(lines)


GENERATED = {"protected paths": (ADMIN_MD, paths_table), "caps": (README, caps_table)}
LAYOUT = ADMIN_MD


def block(name):
    return re.compile(r"(<!-- generated by laptop/tests/test_docs\.py --write: %s -->\n)(.*?)(<!-- end %s -->)"
                      % (re.escape(name), re.escape(name)), re.S)


def layout_paths(text):
    """The paths the File layout block names: two spaces of indent per level, a folder ends in /."""
    m = re.search(r"<!-- file layout: checked by laptop/tests/test_docs\.py -->\n```text\n(.*?)\n```", text, re.S)
    if not m:
        return None
    stack, out = [], set()
    for line in m.group(1).split("\n"):
        if not line.strip():
            continue
        depth, name = (len(line) - len(line.lstrip(" "))) // 2, line.split()[0]
        stack = stack[:depth] + [name.rstrip("/")]
        out.add("/".join(stack) + ("/" if name.endswith("/") else ""))
    return out


def repo_paths():
    out = set()
    for d, subdirs, files in os.walk(REPO):
        rel = os.path.relpath(d, REPO)
        keep = [n for n in subdirs if n not in IGNORED and os.path.normpath(os.path.join(rel, n)) not in IGNORED]
        subdirs[:] = keep
        out |= {os.path.normpath(os.path.join(rel, n)) + "/" for n in keep}
        out |= {os.path.normpath(os.path.join(rel, n)) for n in files if n not in IGNORED}
    return out


def anchors(path):
    """GitHub's heading ids: lower case, punctuation dropped, spaces to hyphens, repeats numbered."""
    seen, out, fence = {}, set(), False
    for line in open(path):
        fence = fence != line.startswith("```")
        m = None if fence else re.match(r"#{1,6} (.*)", line)
        if m:
            slug = re.sub(r"[^\w\- ]", "", m.group(1).strip().lower()).replace(" ", "-")
            out.add(slug + ("-%d" % seen[slug] if slug in seen else ""))
            seen[slug] = seen.get(slug, 0) + 1
    return out


def bad_links():
    bad = []
    for path in sorted(p for p in repo_paths() if p.endswith(".md")):
        text = re.sub(r"```.*?```|`[^`\n]*`", "", open(os.path.join(REPO, path)).read(), flags=re.S)
        for link in re.findall(r"\]\(([^)\s]+)\)", text):
            if re.match(r"[a-z]+:", link):
                continue
            target, _, frag = link.partition("#")
            full = os.path.normpath(os.path.join(REPO, os.path.dirname(path), target)) if target else \
                os.path.join(REPO, path)
            if not os.path.exists(full) or not full.startswith(REPO + os.sep):
                bad.append("%s: %s (no such file in this repository)" % (path, link))
            elif frag and full.endswith(".md") and frag not in anchors(full):
                bad.append("%s: %s (no such heading)" % (path, link))
    return bad


def main(argv):
    if argv not in ([], ["--write"]):
        return print(__doc__.strip()) or 2
    texts = {}
    for doc in (README, ADMIN_MD):
        rel = os.path.relpath(doc, REPO)
        text = open(doc).read()
        new = text
        for name, (where, make) in GENERATED.items():
            if where != doc:
                continue
            m = block(name).search(new)
            if not m:
                check("%s has the generated %s block" % (rel, name), False, "add the two marker lines, then --write")
                continue
            want = make() + "\n"
            check("%s %s block matches its sources" % (rel, name), argv == ["--write"] or m.group(2) == want, "".join(
                difflib.unified_diff(m.group(2).splitlines(True), want.splitlines(True), rel, "from the sources"))
                + "(run tests/test_docs.py --write)")
            new = new[:m.start(2)] + want + new[m.end(2):]
        if argv == ["--write"] and new != text:
            with open(doc, "w") as f:
                f.write(new)
            print("rewrote the generated blocks in %s" % doc)
        texts[doc] = new
    listed, have = layout_paths(texts[LAYOUT]), repo_paths()
    check("%s file layout names every file and folder in the repository, and nothing else"
          % os.path.relpath(LAYOUT, REPO), listed == have,
          "not in the layout: %s\nin the layout, not in the repository: %s" % (
              ", ".join(sorted(have - (listed or set()))) or "-", ", ".join(sorted((listed or set()) - have)) or "-"))
    bad = bad_links()
    check("every relative link in the docs reaches a file and heading", not bad, "\n".join(bad))
    print("ALL PASS" if not fails else "%d FAILED" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

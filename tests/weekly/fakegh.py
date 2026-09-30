"""Stand-in for `gh` when tests/weekly/harness.ps1 runs scripts/weekly-check.ps1. Never touches the network.

Every call is recorded as a marker file in $FAKEPY_MARKERS (name `NN_gh-<subcommand>`, content = the
arguments, then the --body-file contents), so the harness can prove what was sent. Open issues live in
gh-issues.json next to the markers directory, so consecutive runs in one fixture see each other's issues.

  FAKEGH_UNAVAILABLE    if set, `gh auth status` exits 1 (not installed/authenticated)
  FAKEGH_OPEN           open 'weekly-run-failed' issues to seed when no issue store exists yet (default 0)
  FAKEGH_LABEL_MISSING  if set, `gh issue create --label ...` exits 1 (label does not exist)
  FAKEGH_BURY           when seeding the store: one old unlabelled "Weekly run failed" issue, then this many
                        newer unrelated open issues, so the alert sits beyond the first page of a listing

Like the real gh, `issue list` returns the newest issues first, filters --label and --search on the
server side, then truncates to --limit (default 30).
"""
import json
import os
import pathlib
import sys

args = sys.argv[1:]
markers = pathlib.Path(os.environ["FAKEPY_MARKERS"])
markers.mkdir(parents=True, exist_ok=True)
store = markers.parent / "gh-issues.json"
body = ""
if "--body-file" in args:
    body = pathlib.Path(args[args.index("--body-file") + 1]).read_text(encoding="utf-8")
name = "gh-" + "-".join(args[:2])
(markers / f"{len(list(markers.iterdir())):02d}_{name}").write_text("\n".join(args) + "\n---\n" + body, encoding="utf-8")

if store.exists():
    issues = json.loads(store.read_text(encoding="utf-8"))
else:
    issues = [{"number": n + 1, "title": f"Weekly run failed 2000-01-0{n + 1}", "labels": [{"name": "weekly-run-failed"}]}
              for n in range(int(os.environ.get("FAKEGH_OPEN") or "0"))]
    bury = int(os.environ.get("FAKEGH_BURY") or "0")
    if bury:
        issues.append({"number": len(issues) + 1, "title": "Weekly run failed 2000-02-01", "labels": []})
        issues += [{"number": len(issues) + 1 + n, "title": f"Unrelated issue {n}", "labels": []} for n in range(bury)]


def arg(flag):
    return args[args.index(flag) + 1] if flag in args else None


if args[:2] == ["auth", "status"]:
    sys.exit(1 if os.environ.get("FAKEGH_UNAVAILABLE") else 0)
if args[:2] == ["issue", "list"]:
    # Strict like the real gh: one comma-separated field list (a split argument would be an error there).
    if (arg("--json"), arg("--jq")) not in (("number,title,labels", None), ("number", "length"), ("number", None),
                                            ("number,title", None)):
        print(f"fake gh: unexpected issue list arguments {args[2:]}", file=sys.stderr)
        sys.exit(1)
    extra = [a for a in args[2:] if a.startswith("-") and a not in ("--state", "--limit", "--json", "--jq", "--label",
                                                                   "--search")]
    if extra:
        print(f"fake gh: unknown flags {extra}", file=sys.stderr)
        sys.exit(1)
    want, query = arg("--label"), arg("--search")
    words = [w.lower() for w in (query or "").split() if ":" not in w]
    if query is not None and "in:title" not in query.split():
        print("fake gh: only title searches are emulated", file=sys.stderr)
        sys.exit(1)
    shown = [i for i in reversed(issues)  # newest first
             if (want is None or any(lb["name"] == want for lb in i["labels"]))
             and all(w in i["title"].lower() for w in words)][:int(arg("--limit") or "30")]
    print(len(shown) if arg("--jq") == "length" else json.dumps(shown))
    sys.exit(0)
if args[:2] == ["issue", "create"]:
    if os.environ.get("FAKEGH_LABEL_MISSING") and "--label" in args:
        print("could not add label: 'weekly-run-failed' not found", file=sys.stderr)
        sys.exit(1)
    labels = [{"name": arg("--label")}] if "--label" in args else []
    issues.append({"number": len(issues) + 1, "title": arg("--title"), "labels": labels})
    store.write_text(json.dumps(issues), encoding="utf-8")
    print(f"https://github.invalid/fake/issues/{len(issues)}")
    sys.exit(0)
sys.exit(2)

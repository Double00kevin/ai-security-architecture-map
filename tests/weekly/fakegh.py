"""Stand-in for `gh` when tests/weekly/harness.ps1 runs scripts/weekly-check.ps1. Never touches the network.

Every call is recorded as a marker file in $FAKEPY_MARKERS (name `NN_gh-<subcommand>`, content = the
arguments, then the --body-file contents), so the harness can prove what was sent.

  FAKEGH_UNAVAILABLE    if set, `gh auth status` exits 1 (not installed/authenticated)
  FAKEGH_OPEN           number of open 'weekly-run-failed' issues `gh issue list` reports (default 0)
  FAKEGH_LABEL_MISSING  if set, `gh issue create --label ...` exits 1 (label does not exist)
"""
import os
import pathlib
import sys

args = sys.argv[1:]
markers = pathlib.Path(os.environ["FAKEPY_MARKERS"])
markers.mkdir(parents=True, exist_ok=True)
body = ""
if "--body-file" in args:
    body = pathlib.Path(args[args.index("--body-file") + 1]).read_text(encoding="utf-8")
name = "gh-" + "-".join(args[:2])
(markers / f"{len(list(markers.iterdir())):02d}_{name}").write_text("\n".join(args) + "\n---\n" + body, encoding="utf-8")

if args[:2] == ["auth", "status"]:
    sys.exit(1 if os.environ.get("FAKEGH_UNAVAILABLE") else 0)
if args[:2] == ["issue", "list"]:
    print(os.environ.get("FAKEGH_OPEN") or "0")
    sys.exit(0)
if args[:2] == ["issue", "create"]:
    if os.environ.get("FAKEGH_LABEL_MISSING") and "--label" in args:
        print("could not add label: 'weekly-run-failed' not found", file=sys.stderr)
        sys.exit(1)
    print("https://github.invalid/fake/issues/1")
    sys.exit(0)
sys.exit(2)

"""Stand-in for `python` when tests/weekly/harness.ps1 runs scripts/weekly-check.ps1.

Every call is recorded as a marker file in $FAKEPY_MARKERS, so the harness can prove which stages
really executed. Behaviour is steered by environment variables; nothing touches the network.

  FAKEPY_CHECK_EXIT   exit code of `-m drift check` (default 0)
  FAKEPY_FLAGGED      summary.flagged in the report it writes (default 0)
  FAKEPY_NOREPORT     if set, `drift check` writes no report
  FAKEPY_MAP_EXIT     exit code of `-m drift map check` (default 0)
  FAKEPY_TRIAGE_EXIT  exit code of `-m drift triage` (default 0)
  FAKEPY_AUTO_EXIT    exit code of `-m drift auto` (default 0); it also appends to registry/claims.yaml
                      and writes a new maps/<version>/map.json, like a real renewal + build
"""
import datetime
import json
import os
import pathlib
import sys

args = sys.argv[1:]
markers = pathlib.Path(os.environ["FAKEPY_MARKERS"])
markers.mkdir(parents=True, exist_ok=True)
name = "-".join(a.strip("-").replace(" ", "") for a in args[:4] if not a.startswith(("/", "\\")) and ":" not in a)
(markers / f"{len(list(markers.iterdir())):02d}_{name or 'bare'}").write_text(" ".join(args), encoding="utf-8")

if args[:1] == ["-c"]:
    sys.exit(0)
if args[:3] == ["-m", "drift", "check"]:
    if not os.environ.get("FAKEPY_NOREPORT"):
        reports = pathlib.Path("reports")
        reports.mkdir(exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        flagged = int(os.environ.get("FAKEPY_FLAGGED") or "0")
        (reports / f"{stamp}.json").write_text(json.dumps({"summary": {"flagged": flagged}}), encoding="utf-8")
        (reports / f"{stamp}.md").write_text("# fake report\n", encoding="utf-8")
    print("fake drift check: 73 checked")
    print("fake drift check: a line on stderr", file=sys.stderr)
    sys.exit(int(os.environ.get("FAKEPY_CHECK_EXIT") or "0"))
if args[:4] == ["-m", "drift", "map", "check"]:
    print("fake map check")
    sys.exit(int(os.environ.get("FAKEPY_MAP_EXIT") or "0"))
if args[:4] == ["-m", "drift", "map", "verify"]:
    print("fake map verify")
    sys.exit(int(os.environ.get("FAKEPY_VERIFY_EXIT") or "0"))
if args[:3] == ["-m", "drift", "auto"]:
    code = int(os.environ.get("FAKEPY_AUTO_EXIT") or "0")
    if code in (0, 3) or os.environ.get("FAKEPY_PARTIAL_WRITE"):
        reg = pathlib.Path("registry/claims.yaml")
        reg.parent.mkdir(exist_ok=True)
        with reg.open("a", encoding="utf-8") as fh:
            fh.write("# renewed by fake auto\n")
        v = pathlib.Path("maps/v2099.01.01")
        v.mkdir(parents=True, exist_ok=True)
        (v / "map.json").write_text("{}", encoding="utf-8")
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        pathlib.Path("reports", f"{stamp}-auto.json").write_text("{}", encoding="utf-8")
    sys.exit(code)
if args[:3] == ["-m", "drift", "triage"]:
    sys.exit(int(os.environ.get("FAKEPY_TRIAGE_EXIT") or "0"))
sys.exit(0)

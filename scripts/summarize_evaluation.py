"""Create a horizon-specific audit scorecard from a checksum-verified saved run."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from demand_planner.evaluation.reporting import audit_scorecard
from scripts.reproduce_run import read_saved_csv


def summarize(run, output):
    run, output = Path(run), Path(output)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    tables = {}
    for name in ("candidate_predictions", "model_comparison"):
        path = run / f"{name}.csv"
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["files_sha256"][path.name]:
            raise ValueError(f"Saved file checksum differs: {path.name}")
        tables[name] = read_saved_csv(path, dtype={"product_id": str})
    scorecard = audit_scorecard(tables["candidate_predictions"], tables["model_comparison"])
    scorecard["data_source"] = manifest["source"]
    scorecard["synthetic_data"] = manifest["source"] == "Synthetic sample"
    output.parent.mkdir(parents=True, exist_ok=True)
    scorecard.to_csv(output, index=False)
    print(scorecard.to_string(index=False))
    print(f"Saved {output}. Each horizon is separate; these are audit scores, not business savings.")
    return scorecard


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output", type=Path, default=Path("outputs/project-review/audit_scorecard.csv"))
    args = parser.parse_args()
    summarize(args.run_directory, args.output)

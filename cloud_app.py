"""Sample-only Community Cloud entry point. No uploads or saved inputs."""
import os
from pathlib import Path
import runpy

os.environ["DEMAND_PLANNER_PUBLIC_DEMO"] = "true"
os.environ["DEMAND_PLANNER_SAVE_RUNS"] = "false"
runpy.run_path(str(Path(__file__).resolve().with_name("app.py")), run_name="__main__")

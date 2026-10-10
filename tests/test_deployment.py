from io import BytesIO
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from streamlit.testing.v1 import AppTest
from demand_planner.config import PROJECT_ROOT, public_demo_mode, save_local_runs
from demand_planner.domain import AnalysisResults, PlanningSettings
from demand_planner.data.exporting import results_zip
from scripts.prepare_deployment import release_files
from tests.test_inventory import fixture
from tests.test_baseline import render_completed_screen


class DeploymentTests(unittest.TestCase):
    def test_local_and_public_profiles(self):
        with patch.dict(os.environ, {"DEMAND_PLANNER_PUBLIC_DEMO": "false", "DEMAND_PLANNER_SAVE_RUNS": "true"}):
            self.assertFalse(public_demo_mode())
            self.assertTrue(save_local_runs())
        with patch.dict(os.environ, {"DEMAND_PLANNER_PUBLIC_DEMO": "true", "DEMAND_PLANNER_SAVE_RUNS": "true"}):
            self.assertTrue(public_demo_mode())
            self.assertFalse(save_local_runs())

    def test_hosted_entry_reruns_and_has_no_upload_controls(self):
        with patch.dict(os.environ):
            app = AppTest.from_file(str(PROJECT_ROOT / "cloud_app.py")).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("file_uploader")), 0)
            self.assertTrue(any("Synthetic portfolio demo" in item.value for item in app.info))
            next(button for button in app.button if button.label == "Load sample data").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["dataset"].source, "Synthetic sample")
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(app.title)

    def test_demo_analysis_does_not_save_files(self):
        dataset, forecast = fixture()
        dataset.source = "Synthetic sample"
        result = AnalysisResults(dataset.fingerprint, PlanningSettings(), daily_forecasts=forecast, data_source=dataset.source)
        with patch.dict(os.environ, {"DEMAND_PLANNER_PUBLIC_DEMO": "true"}):
            app = AppTest.from_function(render_completed_screen, args=(dataset, None, "data_setup")).run()
            with patch("demand_planner.ui.screens.cached_analysis", return_value=result), patch("demand_planner.ui.screens.save_analysis") as save:
                next(button for button in app.button if button.label == "Run analysis").click().run()
                save.assert_not_called()
            self.assertFalse(app.exception)
            self.assertFalse(any("not saved" in item.value for item in app.warning))

    def test_release_allowlist_excludes_all_generated_or_private_paths(self):
        names = [path.relative_to(PROJECT_ROOT).as_posix() for path in release_files()]
        self.assertIn("cloud_app.py", names)
        self.assertIn("data/sample/sales.csv", names)
        self.assertFalse(any(name.startswith(("outputs/", "data/uploads/", ".venv")) or "secrets.toml" in name for name in names))

    def test_exports_label_synthetic_results(self):
        result = AnalysisResults("sample", PlanningSettings(), data_source="Synthetic sample")
        with ZipFile(BytesIO(results_zip(result))) as archive:
            metadata = json.loads(archive.read("metadata.json"))
            self.assertTrue(metadata["synthetic_data"])
            self.assertIn(b"Synthetic sample", archive.read("README.txt"))

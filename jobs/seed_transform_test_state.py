"""Mark the stub report_download steps in legend_transform_concat_test.yaml as
already complete, so `adobe-downloader run` skips them and goes straight to
transform_daily/transform_totals — no Adobe Analytics API calls.

Run this once before `adobe-downloader run -c jobs/legend_transform_concat_test.yaml`,
and again after any edit to that YAML (editing it changes its content hash, which
changes the derived job_id, which points at a fresh empty state DB).

Usage (from repo root):
    python jobs/seed_transform_test_state.py
"""

from pathlib import Path

from adobe_downloader.config.loader import load_config
from adobe_downloader.config.schema import CompositeJobConfig
from adobe_downloader.state_manager import (
    StateManager,
    compute_config_hash,
    compute_job_id,
    state_db_path,
)

CONFIG_PATH = Path(__file__).parent / "legend_transform_concat_test.yaml"
REAL_JSON_FOLDER = "C:/Adobe_Downloads/Legend/BotInv250k26Q2V2/JSON"
STUB_STEP_IDS = ("download_daily", "download_totals")

job = load_config(CONFIG_PATH)
assert isinstance(job, CompositeJobConfig)
assert job.output is not None

config_hash = compute_config_hash(CONFIG_PATH)
job_id = compute_job_id(CONFIG_PATH, config_hash)
db_path = state_db_path(job.output.base_folder, job.client, job_id)
sm = StateManager(db_path, job_id, CONFIG_PATH, config_hash)

for step_id in STUB_STEP_IDS:
    sm.mark_step_started(step_id)
    sm.mark_step_complete(
        step_id,
        {
            "json_folder": REAL_JSON_FOLDER,
            "downloaded": 0,
            "skipped": 0,
            "copied": 0,
            "failed": 0,
        },
    )
    print(f"Marked {step_id!r} complete")

print(f"Job ID   : {job_id}")
print(f"State DB : {db_path}")

"""Bounded, memory-only computation cache with complete input and code keys."""
from hashlib import sha256
import streamlit as st
from demand_planner.analysis import run_model_analysis
from demand_planner.config import PROJECT_ROOT


def data_digest(dataset):
    digest = sha256()
    for name, frame in sorted(dataset.tables.items()):
        digest.update(name.encode())
        digest.update(frame.to_csv(index=False, date_format="%Y-%m-%d").encode())
        digest.update(str(frame.dtypes.tolist()).encode())
    digest.update(dataset.fingerprint.encode())
    digest.update(b"\0source\0")
    digest.update(dataset.source.encode())
    return digest.hexdigest()


def engine_digest():
    digest = sha256()
    for path in sorted((PROJECT_ROOT / "demand_planner").rglob("*.py")):
        digest.update(str(path.relative_to(PROJECT_ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


@st.cache_data(max_entries=8, ttl=3600, show_spinner=False)
def _analysis_cached(input_digest, settings, code_digest, _dataset):
    # _dataset is excluded from Streamlit's sampled hashing. input_digest hashes every row.
    return run_model_analysis(_dataset, settings)


def cached_analysis(dataset, settings):
    return _analysis_cached(data_digest(dataset), settings, engine_digest(), dataset)

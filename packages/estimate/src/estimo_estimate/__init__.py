"""Estimo estimation (S6): analog-grounded bands, calibration, critic, BoE rendering."""

from estimo_estimate.bands import BandResult, band_from_analogs
from estimo_estimate.boe_render import render_boe_docx
from estimo_estimate.calibration import (
    ErrorDistribution,
    error_distribution,
    transfer_distribution,
)
from estimo_estimate.critic import review_boe
from estimo_estimate.estimator import estimate_state
from estimo_estimate.evals import EffortEvalResult, leave_one_out
from estimo_estimate.loop import (
    record_actual,
    rolling_coverage,
    snapshot_calibration,
)

__all__ = [
    "BandResult",
    "EffortEvalResult",
    "ErrorDistribution",
    "band_from_analogs",
    "error_distribution",
    "estimate_state",
    "leave_one_out",
    "record_actual",
    "render_boe_docx",
    "review_boe",
    "rolling_coverage",
    "snapshot_calibration",
    "transfer_distribution",
]

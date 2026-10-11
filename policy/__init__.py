"""Retirement Policy v3.4.0 B+85 — offline policy calculation package.

The live ACTIVE router and personal-account authorization are NOT installed here.
"""
from .retirement_model_v340 import ModelConfig, simulate_outer, b85_restore_eligible

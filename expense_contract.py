"""Versioned known-expense wiring; frozen economic formulas are unchanged."""
from dataclasses import replace
import math

CONTRACT = 'KNOWN_MANDATORY_EXPENSE_POS_V1'


def bind_current_expense(cfg, age: int, amount: float):
    amount = float(amount)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError('必要支出必須是有限非負金額')
    schedule = dict(cfg.extra_mandatory_expense_by_age)
    existing = float(schedule.get(age, 0.0))
    if existing and not math.isclose(existing, amount, abs_tol=1e-10, rel_tol=0):
        raise ValueError('同年度必要支出排程與年度輸入不一致，不能重複加總')
    if amount:
        schedule[age] = amount
    return replace(cfg, extra_mandatory_expense_by_age=schedule)

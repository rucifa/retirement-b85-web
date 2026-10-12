"""Opt-in 2026 real annual Normal/Core/Floor research profile."""
from decimal import Decimal,InvalidOperation
import json,hashlib
MODE="GENERALIZED_RESEARCH_SPENDING_V1"
SCHEMA="SPENDING_PROFILE_2026_REAL_V1"
def amount(x,label):
    if isinstance(x,bool):raise ValueError(label+" 必須是金額")
    try:v=Decimal(str(x).replace(",",""))
    except (InvalidOperation,TypeError,ValueError):raise ValueError(label+" 不是有效金額")
    if not v.is_finite() or v!=v.to_integral_value() or not 12000<=v<=10000000:
        raise ValueError(label+" 請填每年 12,000 至 10,000,000 元整數")
    return int(v)
def validate(p):
    if not isinstance(p,dict) or set(p)!={"schema","normal_twd","core_twd","floor_twd"} or p.get("schema")!=SCHEMA:raise ValueError("生活費設定版本或欄位錯誤")
    x={"schema":SCHEMA,"normal_twd":amount(p["normal_twd"],"正常生活費"),"core_twd":amount(p["core_twd"],"核心生活費"),"floor_twd":amount(p["floor_twd"],"Floor 最低必要支出")}
    if not x["floor_twd"]<=x["core_twd"]<=x["normal_twd"]:raise ValueError("生活費必須滿足 Floor ≤ 核心 ≤ 正常")
    return x
def from_input(d):return validate({"schema":SCHEMA,"normal_twd":d.get("normal_spend_2026_twd"),"core_twd":d.get("core_spend_2026_twd"),"floor_twd":d.get("floor_spend_2026_twd")})
def digest(p):return hashlib.sha256(json.dumps(validate(p),ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

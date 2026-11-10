"""Typed loader for config/hostop.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class ICP(BaseModel):
    min_listings: int = 10
    max_listings: int = 500
    ideal_min: int = 15
    ideal_max: int = 150
    multi_market_min_cities: int = 2

    @model_validator(mode="after")
    def _check(self) -> ICP:
        if not (self.min_listings <= self.ideal_min <= self.ideal_max <= self.max_listings):
            raise ValueError("ICP bands must satisfy min <= ideal_min <= ideal_max <= max")
        return self


class Geography(BaseModel):
    country: str
    region: str = ""
    city: str


class ValueProp(BaseModel):
    id: str
    text: str


class Company(BaseModel):
    name: str = "HostOp"
    facts: list[str] = Field(default_factory=list)


class Sender(BaseModel):
    name: str
    title: str
    company: str
    postal_address: str
    opt_out_line: str


class Limits(BaseModel):
    linkedin_note_chars: int = 300
    email_words: int = 90
    instagram_dm_chars: int = 500


class Outreach(BaseModel):
    daily_caps: dict[str, int] = Field(default_factory=dict)


class Compliance(BaseModel):
    regions: dict[str, str] = Field(default_factory=dict)
    eu_countries: list[str] = Field(default_factory=list)


class Fetch(BaseModel):
    min_delay_seconds: float = 2.0
    cache_ttl_hours: int = 168
    timeout_seconds: float = 15
    blocked_domains: list[str] = Field(default_factory=list)


class Enrichment(BaseModel):
    credit_budget_per_run: int = 50


class Scoring(BaseModel):
    weights: dict[str, float] = Field(default_factory=dict)
    tiers: dict[str, float] = Field(default_factory=lambda: {"A": 60.0, "B": 35.0})


class HostOpConfig(BaseModel):
    company: Company
    icp: ICP
    geographies: list[Geography]
    pms_tech: dict[str, list[str]]
    value_props: list[ValueProp]
    banned_phrases: list[str]
    fake_familiarity_patterns: list[str] = Field(default_factory=list)
    sender: Sender
    limits: Limits = Limits()
    outreach: Outreach = Outreach()
    compliance: Compliance = Compliance()
    fetch: Fetch = Fetch()
    enrichment: Enrichment = Enrichment()
    scoring: Scoring = Scoring()


def load_config(path: str | Path | None = None) -> HostOpConfig:
    if path is None:
        from hostop.settings import get_settings

        path = get_settings().hostop_config
    with open(path, encoding="utf-8") as fh:
        return HostOpConfig.model_validate(yaml.safe_load(fh))

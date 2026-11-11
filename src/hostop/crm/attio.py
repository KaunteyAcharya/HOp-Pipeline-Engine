"""Attio sync: upsert companies and people, set pipeline stage on a list entry, add notes.

Endpoints checked against docs.attio.com on 2026-11-11 (llms.txt + endpoint reference .md pages):
  PUT  /v2/objects/companies/records?matching_attribute=domains     body {data: {values: {...}}}
  PUT  /v2/objects/people/records?matching_attribute=email_addresses body {data: {values: {...}}}
  PUT  /v2/lists/{list}/entries      upsert entry by parent: {data: {parent_record_id, parent_object, entry_values}}
  POST /v2/notes                     {data: {parent_object, parent_record_id, title, format, content}}
Auth: Authorization: Bearer <ATTIO_API_KEY>.
NOT live-tested against a workspace. Workspace-specific and must be configured: the list slug and the stage
attribute slug (+ its status option titles). Response record id is data.id.record_id (per docs). Company
`name` is written as [{value}], person `name` as [{first_name,last_name,full_name}] (per docs).
Use the CSV export until a first live call in your workspace succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

BASE = "https://api.attio.com/v2"


@dataclass
class AttioConfig:
    api_key: str
    list_slug: str = "hostop_pipeline"
    stage_attribute: str = "stage"


class AttioClient:
    def __init__(self, cfg: AttioConfig, client: httpx.Client | None = None) -> None:
        if not cfg.api_key:
            raise ValueError("ATTIO_API_KEY is not set")
        self.cfg = cfg
        self.client = client or httpx.Client(timeout=30, headers={"Authorization": f"Bearer {cfg.api_key}"})

    def _record_id(self, r: httpx.Response) -> str:
        r.raise_for_status()
        return str(r.json()["data"]["id"]["record_id"])

    def upsert_company(self, name: str, domain: str, extra: dict[str, Any] | None = None) -> str:
        values: dict[str, Any] = {"name": [{"value": name}], "domains": [{"domain": domain}], **(extra or {})}
        r = self.client.put(f"{BASE}/objects/companies/records", params={"matching_attribute": "domains"},
                            json={"data": {"values": values}})
        return self._record_id(r)

    def upsert_person(self, email: str, full_name: str | None, company_domain: str | None) -> str:
        values: dict[str, Any] = {"email_addresses": [{"email_address": email}]}
        if full_name:
            first, _, last = full_name.partition(" ")
            values["name"] = [{"first_name": first, "last_name": last, "full_name": full_name}]
        if company_domain:
            values["company"] = [{"target_object": "companies", "domains": [{"domain": company_domain}]}]
        r = self.client.put(f"{BASE}/objects/people/records", params={"matching_attribute": "email_addresses"},
                            json={"data": {"values": values}})
        return self._record_id(r)

    def set_stage(self, company_record_id: str, stage: str) -> None:
        body = {"data": {"parent_record_id": company_record_id, "parent_object": "companies",
                         "entry_values": {self.cfg.stage_attribute: stage}}}
        self.client.put(f"{BASE}/lists/{self.cfg.list_slug}/entries", json=body).raise_for_status()

    def add_note(self, parent_object: str, record_id: str, title: str, content: str) -> None:
        body = {"data": {"parent_object": parent_object, "parent_record_id": record_id, "title": title,
                         "format": "plaintext", "content": content}}
        self.client.post(f"{BASE}/notes", json=body).raise_for_status()

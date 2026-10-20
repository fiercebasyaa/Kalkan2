"""OFAC SDN list — sanctioned digital currency addresses.

The SDN list publishes crypto addresses as an "identification document" on
a sanctioned entity, with an id type like "Digital Currency Address - XBT"
or "Digital Currency Address - ETH". This is the standard technique crypto
compliance tools use to extract addresses from OFAC data (there's no
separate "crypto addresses" feed).

The XML uses a default namespace, so we match elements by local tag name
(stripping the `{namespace}` prefix) instead of hardcoding the namespace
URI, which makes this resilient to minor schema/namespace changes.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger(__name__)


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


async def fetch_ofac_addresses(url: str) -> dict[str, dict]:
    """Returns {lowercased_address: {"entity": str, "program": str}}."""
    out: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            xml_bytes = resp.content
    except httpx.HTTPError as exc:
        logger.warning("OFAC SDN fetch failed: %s", exc)
        return out

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("OFAC SDN parse failed: %s", exc)
        return out

    for entry in root.iter():
        if _local(entry.tag) != "sdnEntry":
            continue
        entity_name = None
        program = None
        for child in entry:
            local = _local(child.tag)
            if local in ("lastName", "firstName") and child.text:
                entity_name = (entity_name + " " + child.text) if entity_name else child.text
            if local == "programList":
                programs = [
                    p.text for p in child.iter() if _local(p.tag) == "program" and p.text
                ]
                if programs:
                    program = ", ".join(programs)

        for id_el in entry.iter():
            if _local(id_el.tag) != "id":
                continue
            id_type = None
            id_number = None
            for f in id_el:
                fl = _local(f.tag)
                if fl == "idType":
                    id_type = f.text
                elif fl == "idNumber":
                    id_number = f.text
            if id_type and "Digital Currency Address" in id_type and id_number:
                out[id_number.strip().lower()] = {
                    "entity": entity_name or "Unknown SDN entity",
                    "program": program or "OFAC SDN",
                    "chain_hint": id_type.replace("Digital Currency Address -", "").strip(),
                }

    logger.info("OFAC SDN: loaded %d digital currency addresses", len(out))
    return out

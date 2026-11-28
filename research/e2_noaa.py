"""One anonymous archive availability probe for a fixed public NBP cycle."""

import argparse
import http.client
import json
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from itertools import pairwise

from research.e1 import digest, require
from research.e2 import PRIVATE, population

HOST = "noaa-nbm-grib2-pds.s3.amazonaws.com"
OBJECT = "/blend.20260901/01/text/blend_nbptx.t01z"
LIMIT = 20 * 1024 * 1024
CYCLE = datetime(2026, 9, 1, 1, tzinfo=UTC)


HEADER = re.compile(rb"(?m)^[ \t]*(\w+)[ \t]+NBM[ \t]+V(\S+)[ \t]+NBP[ \t]+GUIDANCE", re.I)


def acquire() -> None:
    frozen, _ = population()
    require(
        json.loads((PRIVATE / "population.json").read_text()) == frozen, "freeze population first"
    )
    # One whole-file probe. Large objects are searched separately with range GETs.
    with (PRIVATE / "noaa-attempt.json").open("x", encoding="utf8") as f:
        json.dump({"host": HOST, "object": OBJECT, "start": datetime.now(UTC).isoformat()}, f)
    conn = http.client.HTTPSConnection(HOST, timeout=30)
    try:
        conn.request("GET", OBJECT, headers={"Accept-Encoding": "identity"})
        with conn.getresponse() as r:
            length = int(r.getheader("Content-Length", "-1"))
            require(r.status == 200 and length > 0, "bulletin unavailable")
            require(
                r.getheader("Content-Encoding", "identity") == "identity", "unexpected encoding"
            )
            tag = r.getheader("ETag")
            if length <= LIMIT:
                body = r.read(length)
                require(len(body) == length, "incomplete bulletin")
                save(body, r.status, r.getheader("Last-Modified"), tag)
                return
    finally:
        conn.close()
    station_range(length, tag)


def save(body: bytes, status: int, modified: str | None, tag: str | None) -> None:
    meta = {
        "status": status,
        "object": OBJECT,
        "bytes": len(body),
        "sha256": digest(body),
        "modified": modified,
        "etag": tag,
        "receipt": datetime.now(UTC).isoformat(),
    }
    (PRIVATE / "noaa-nbp.txt").write_bytes(body)
    (PRIVATE / "noaa-receipt.json").write_text(json.dumps(meta), encoding="utf8")


def station_range(size: int, tag: str | None) -> None:
    # At most 20 * 128 KiB even on interrupted or repeated invocations.
    block = 128 * 1024
    lo, hi = 0, size - 1
    for i in range(20):
        start = max(0, (lo + hi - block) // 2)
        stop = min(start + block - 1, size - 1)
        receipt = PRIVATE / f"range-{i:02d}.json"
        with receipt.open("x", encoding="utf8") as f:
            json.dump({"start": start, "end": stop}, f)
        conn = http.client.HTTPSConnection(HOST, timeout=30)
        try:
            headers = {"Range": f"bytes={start}-{stop}", "Accept-Encoding": "identity"}
            if tag:
                headers["If-Match"] = tag
            conn.request("GET", OBJECT, headers=headers)
            with conn.getresponse() as r:
                require(
                    r.status == 206
                    and r.getheader("Content-Range") == f"bytes {start}-{stop}/{size}"
                    and int(r.getheader("Content-Length", "-1")) == stop - start + 1,
                    "unexpected range response",
                )
                chunk = r.read(stop - start + 1)
                require(len(chunk) == stop - start + 1, "incomplete range")
                tag = r.getheader("ETag")
                modified = r.getheader("Last-Modified")
        finally:
            conn.close()
        receipt.write_text(
            json.dumps(
                {
                    "start": start,
                    "end": stop,
                    "bytes": len(chunk),
                    "sha256": digest(chunk),
                    "etag": tag,
                    "modified": modified,
                }
            ),
            encoding="utf8",
        )
        matches = list(HEADER.finditer(chunk))
        require(matches, "no station headers in range")
        for found, following in pairwise(matches):
            if found[1] == b"KNYC":
                body = chunk[found.start() : following.start()]
                save(body, 206, modified, tag)
                return
        # Move toward the target. Overlap the edge cards at the next bisection.
        if matches[-1][1] <= b"KNYC":
            lo = start + matches[-1].start()
        elif matches[0][1] > b"KNYC":
            hi = start + matches[0].start()
        else:
            raise ValueError("station absent or archive station order inconsistent")
        require(lo < hi, "station outside sampled range")
    raise ValueError("station search exhausted")


def bulletin(body: bytes) -> tuple[str, dict[str, list[str]]]:
    lines = body.decode("ascii").splitlines()
    header = re.compile(r"^\s*(\w+)\s+NBM\s+V(\S+)\s+NBP\s+GUIDANCE\s+(\S+)\s+(\d{4})\s+UTC", re.I)
    matches = [i for i, s in enumerate(lines) if (m := header.match(s)) and m[1] == "KNYC"]
    require(len(matches) == 1, "station missing or ambiguous")
    start = matches[0]
    m = header.match(lines[start])
    assert m is not None
    require(
        datetime.strptime(m[3] + " " + m[4], "%m/%d/%Y %H%M").replace(tzinfo=UTC) == CYCLE,
        "unexpected bulletin issue time",
    )
    card = {}
    for line in lines[start + 1 :]:
        if header.match(line):
            break
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[0] in (
            "UTC",
            "FHR",
            "TXNP1",
            "TXNP2",
            "TXNP5",
            "TXNP7",
            "TXNP9",
        ):
            card[parts[0]] = re.findall(r"-?\d+", parts[1])
    return m[2], card


def audit() -> dict[str, object]:
    frozen, rows = population()
    require(
        json.loads((PRIVATE / "population.json").read_text()) == frozen, "frozen inputs changed"
    )
    meta = json.loads((PRIVATE / "noaa-receipt.json").read_text())
    body = (PRIVATE / "noaa-nbp.txt").read_bytes()
    require(digest(body) == meta["sha256"], "bulletin digest changed")
    version, card = bulletin(body)
    published_proxy = parsedate_to_datetime(meta["modified"]).timestamp()
    end_dates = set()
    good = 0
    leads = [int(h) for h in card.get("FHR", [])]
    require(
        leads == sorted(set(leads))
        and leads
        and [int(h) for h in card.get("UTC", [])]
        == [(CYCLE + timedelta(hours=h)).hour for h in leads],
        "invalid bulletin valid hours",
    )
    fields = [card.get("TXNP" + k, []) for k in "12579"]
    for i, lead in enumerate(leads):
        valid = CYCLE + timedelta(hours=lead)
        if valid.hour == 0 and all(len(v) == len(leads) for v in fields):
            quantiles = [int(v[i]) for v in fields]
            if min(quantiles) > -99 and max(quantiles) < 200 and sorted(quantiles) == quantiles:
                end_dates.add((valid.date() - timedelta(days=1)).isoformat())
                good += 1
    return {
        "bulletin_version": version,
        "station": "KNYC",
        "quantile_fields": sum(bool(v) for v in fields),
        "lead_columns": len(leads),
        "daytime_max_columns": good,
        "day_labels_intersect": len(end_dates & frozen["days"].keys()),
        "candidate_days_archive_object_precedes_all_selected_closes": sum(
            all(
                r["source_end_ts"] and published_proxy <= r["source_end_ts"]
                for r in rows
                if r["day"] == day
            )
            for day in end_dates & frozen["days"].keys()
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("acquire", "audit"))
    action = parser.parse_args().action
    if action == "acquire":
        acquire()
    else:
        print(json.dumps(audit()))

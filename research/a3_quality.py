"""Offline validation. All per-contract inputs, flags, features and labels stay local."""

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from .a3_data import PLAN, deduplicate, instant, number, settlement


def probability(value, notional):
    d = number(value)
    if notional is None or notional <= 0 or d is None or not 0 <= d <= notional:
        return None
    return d / notional


def rule_date(text, day):
    months = {day.strftime("%B").lower(), day.strftime("%b").lower()}
    return (
        any(
            re.search(r"\b" + month + rf"\.?\s+0?{day.day}(?:st|nd|rd|th)?,?\s+{day.year}\b", text)
            for month in months
        )
        or day.isoformat() in text
    )


def identity(g):
    series, event = g["series"], g["event"]
    obj = g["event_obj"]
    if (
        not isinstance(obj, dict)
        or not isinstance(g["series_obj"], dict)
        or obj.get("event_ticker") != event
        or obj.get("series_ticker") != series
        or obj.get("mutually_exclusive") is not True
        or g["series_obj"].get("ticker") != series
        or g["roster_conflicts"]
        or g["roster_missing"]
        or g["enumeration"] != ["terminal_cursor", "terminal_cursor"]
    ):
        return None
    ms = [p["market"] for p in g["markets"]]
    if not ms or set(g["roster"]) != {m["ticker"] for m in ms}:
        return None
    day = date.fromisoformat(g["day"])
    rules = [
        (str(m.get("rules_primary") or "") + " " + str(m.get("rules_secondary") or "")).lower()
        for m in ms
    ]
    if any(
        m.get("event_ticker") != event
        or m.get("mve_collection_ticker")
        or m.get("mve_selected_legs")
        for m in ms
    ) or not all(rule_date(s, day) for s in rules):
        return None
    if g["cohort"] == "weather":
        # Within this specific series only. External station equivalence needs the oracle.
        if not obj.get("settlement_sources") or not all(
            "new york city" in r and "maximum" in r for r in rules
        ):
            return None
        strikes = [(m.get("strike_type"), m.get("floor_strike"), m.get("cap_strike")) for m in ms]
        if any(
            not isinstance(s, str)
            or (a is None and b is None)
            or any(v is not None and type(v) not in (int, float) for v in (a, b))
            for s, a, b in strikes
        ) or len(set(strikes)) != len(ms):
            return None
        return f"{series}/{day}/NYC-maximum"
    if len(ms) != 2 or not all("basketball" in r and "win" in r for r in rules):
        return None
    ids = []
    for m, r in zip(ms, rules, strict=True):
        side = m.get("yes_sub_title")
        strike = m.get("custom_strike")
        if (
            not isinstance(side, str)
            or not side
            or side.lower() not in r
            or not isinstance(strike, dict)
        ):
            return None
        uuids = [
            v
            for v in strike.values()
            if isinstance(v, str)
            and re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", v)
        ]
        if len(uuids) != 1:
            return None
        ids.append(uuids[0].lower())
    a, b = [m["ticker"].removeprefix(event + "-") for m in ms]
    if len(set(ids)) != 2 or a == b or not event.endswith((a + b, b + a)):
        return None
    return "/".join([series, str(day), *sorted(ids)])


def close_field(obj):
    if isinstance(obj, dict):
        return obj.get("close_dollars", obj.get("close"))
    return None


def candles(packet, opened, cutoff, nominal, counts):
    obj, ticker = packet["candles"], packet["market"]["ticker"]
    rows = obj.get("candlesticks")
    if obj.get("ticker") != ticker or not isinstance(rows, list):
        counts["missing_or_invalid_candle_response"] += 1
        return None
    counts["retrieved_candle_markets"] += 1
    counts["candle_rows"] += len(rows)
    ends, conflicts, eligible = {}, set(), []
    for row in rows:
        if not isinstance(row, dict) or type(row.get("end_period_ts")) is not int:
            counts["malformed_candles"] += 1
            continue
        ts = row["end_period_ts"]
        if ts in ends:
            if ends[ts] == row:
                counts["duplicate_candles"] += 1
            else:
                conflicts.add(ts)
        ends[ts] = row
    counts["conflicting_candle_keys"] += len(conflicts)
    for ts, row in ends.items():
        if ts in conflicts:
            continue
        vol = number(row.get("volume_fp", row.get("volume")))
        raw = close_field(row.get("price"))
        price = probability(raw, nominal)
        if vol is None or vol < 0:
            counts["invalid_volume"] += 1
            continue
        if vol == 0 or raw is None:
            counts["empty_or_anchor_candles"] += 1
            continue
        if price is None:
            counts["invalid_probability"] += 1
            continue
        bid = probability(close_field(row.get("yes_bid")), nominal)
        ask = probability(close_field(row.get("yes_ask")), nominal)
        if bid is not None and ask is not None:
            counts["two_sided_candle_closes"] += 1
            counts["crossed_candle_quotes"] += bid > ask
        if ts - 60 < opened.timestamp() or ts > cutoff.timestamp():
            counts["incomplete_or_outside_window"] += 1
            continue
        if ts + PLAN["assumed_bar_publication_delay_seconds"] > cutoff.timestamp():
            counts["too_late_under_delay"] += 1
            continue
        if cutoff.timestamp() - ts > PLAN["lookback_minutes"] * 60:
            counts["stale_candles"] += 1
            continue
        eligible.append(
            (
                ts,
                price,
                raw,
                str(vol),
                close_field(row.get("yes_bid")),
                close_field(row.get("yes_ask")),
            )
        )
    if conflicts:
        return None
    return max(eligible) if eligible else None


def trade_check(p, bar, nominal, stats):
    if not p["trade_target"]:
        return
    stats["trade_target_markets"] += 1
    rows, clashes, duplicates, missing = deduplicate(p["trades"], "trade_id")
    stats.update(
        {
            "trade_rows": len(p["trades"]),
            "unique_trades": len(rows),
            "conflicting_trade_ids": len(clashes),
            "duplicate_trade_ids": duplicates,
            "missing_trade_ids": missing,
        }
    )
    for t in rows.values():
        when = instant(t.get("created_time"))
        px, qty = probability(t.get("yes_price_dollars"), nominal), number(t.get("count_fp"))
        stats["trades_with_timestamp_price_quantity"] += (
            when is not None and px is not None and qty is not None and qty > 0
        )
        stats["trades_with_unknown_block_flag"] += type(t.get("is_block_trade")) is not bool
    complete = bool(p["trade_scan"]) and all(s == "terminal_cursor" for s in p["trade_scan"])
    stats["complete_trade_scans"] += complete
    if not complete or clashes or missing or not bar:
        return
    candidates = []
    for trade in rows.values():
        t = instant(trade.get("created_time"))
        if t is None or trade.get("ticker") != p["market"]["ticker"]:
            stats["invalid_trade_identity_or_time"] += 1
            return
        if bar[0] - 60 < t.timestamp() <= bar[0]:
            pr = probability(trade.get("yes_price_dollars"), nominal)
            qty = number(trade.get("count_fp"))
            if trade.get("is_block_trade") is not False or pr is None or qty is None or qty <= 0:
                stats["unclassified_or_invalid_comparison_trade"] += 1
                return
            candidates.append((t, pr))
    if candidates:
        latest = max(t for t, _ in candidates)
        prices = {pr for t, pr in candidates if t == latest}
        if len(prices) == 1:
            stats["comparable_trade_closes"] += 1
            stats["matching_trade_closes"] += prices == {bar[1]}
        else:
            stats["unordered_last_trades"] += 1


def partitions(packets):
    result = {}
    for cohort in PLAN["cohorts"]:
        days = sorted({g["day"] for g in packets if g["cohort"] == cohort})
        dev, val = round(0.6 * len(days)), round(0.8 * len(days))
        for i, day in enumerate(days):
            result[cohort, day] = (
                "development" if i < dev else "validation" if i < val else "holdout"
            )
    return result


def summarize(packets, frame):
    splits = partitions(packets)
    keys = [identity(g) for g in packets]
    frequency = Counter(keys)
    census = {k: Counter() for k in frame}
    features, labels = [], []
    for g, key in zip(packets, keys, strict=True):
        cohort, day = g["cohort"], g["day"]
        stats = census[cohort]
        split = splits[cohort, day]
        stats["sampled_exchange_events"] += 1
        known_group = key is not None and frequency[key] == 1
        stats["identified_underlying_groups"] += known_group
        stats["ambiguous_or_colliding_groups"] += not known_group
        stats["roster_duplicate_rows"] += g["roster_duplicates"]
        stats["roster_conflicts"] += g["roster_conflicts"]
        stats["event_metadata_retrieved"] += g["event_status"] == "ok"
        stats["series_source_present"] += isinstance(g["series_obj"], dict) and bool(
            g["series_obj"].get("settlement_sources")
        )
        resolved = [settlement(p["market"]) for p in g["markets"]]
        # A two-team complete final game must have one winning side.
        incoherent = (
            known_group
            and cohort != "weather"
            and all(s == "final_binary" for s, _ in resolved)
            and sum(y for _, y in resolved) != 1
        )
        stats["inconsistent_complement_groups"] += incoherent
        any_proxy = False
        for p, (state, label) in zip(g["markets"], resolved, strict=True):
            m = p["market"]
            opened, closed, settled = (
                instant(m.get(f)) for f in ("open_time", "close_time", "settlement_ts")
            )
            occurrence = instant(m.get("occurrence_datetime"))
            nominal = number(m.get("notional_value_dollars"))
            cutoff = (
                opened + timedelta(minutes=PLAN["horizon_minutes_after_open"]) if opened else None
            )
            stats["target_contracts"] += 1
            stats["one_minute_responses_ok"] += p["candle_status"] == "ok"
            stats["settlement_" + state] += 1
            stats["unknown_original_schedule"] += 1
            stats["recorded_occurrence"] += occurrence is not None
            stats["recorded_open"] += opened is not None
            stats["recorded_close"] += closed is not None
            stats["can_close_early"] += m.get("can_close_early") is True
            bar = candles(p, opened, cutoff, nominal, stats) if opened else None
            stats["usable_price_markets"] += bar is not None
            stats["missing_price_markets"] += bar is None
            trade_check(p, bar, nominal, stats)
            # Earliest plausible midnight anywhere for sports. NYC midnight is
            # always at or after 04:00 UTC. Final event times never set the horizon.
            day_bound = datetime.fromisoformat(day).replace(tzinfo=UTC) + timedelta(
                hours=4 if cohort == "weather" else -14
            )
            reasons = []
            if not known_group:
                reasons.append("ambiguous_group")
            if state != "final_binary" or incoherent:
                reasons.append("settlement")
            if not cutoff or not closed or not settled or not cutoff < closed <= settled:
                reasons.append("market_chronology")
            if (
                not cutoff
                or cutoff >= day_bound
                or (occurrence is not None and cutoff >= occurrence)
            ):
                reasons.append("outcome_precedence_unverified")
            if bar is None:
                reasons.append("no_eligible_trade_close")
            for r in reasons:
                stats["excluded_" + r] += 1
            if not reasons:
                any_proxy = True
                stats["proxy_eligible_contracts"] += 1
            symbol = m["ticker"]
            # No fields in this features file convey the direction of settlement.
            features.append(
                {
                    "cohort": cohort,
                    "series": g["series"],
                    "exchange_event": g["event"],
                    "contract": symbol,
                    "underlying_event": key if known_group else None,
                    "day": day,
                    "partition": split,
                    "open": m.get("open_time"),
                    "cutoff": cutoff.isoformat() if cutoff else None,
                    "source_end_ts": bar[0] if bar else None,
                    "source_path": p.get("candle_path"),
                    "assumed_available_ts": bar[0] + PLAN["assumed_bar_publication_delay_seconds"]
                    if bar
                    else None,
                    "price_source": "one_minute_trade_close",
                    "price_dollars": bar[2] if bar else None,
                    "bid_candle_close_dollars": bar[4] if bar else None,
                    "ask_candle_close_dollars": bar[5] if bar else None,
                    "volume_contracts": bar[3] if bar else None,
                    "notional_dollars": str(nominal) if nominal is not None else None,
                    "probability": str(bar[1]) if bar else None,
                    "strict_eligible": False,
                    "proxy_eligible": not reasons,
                    "exclusions": reasons,
                }
            )
            labels.append(
                {
                    "cohort": cohort,
                    "contract": symbol,
                    "partition": split,
                    "underlying_event": key,
                    "status": state,
                    "outcome": label,
                    "settlement_time": m.get("settlement_ts"),
                }
            )
        stats["proxy_eligible_groups"] += any_proxy
        stats[split + "_target_groups"] += 1
        stats[split + "_proxy_groups"] += any_proxy
    for cohort, stats in census.items():
        dates = [g["day"] for g in packets if g["cohort"] == cohort]
        frame[cohort] = {
            **frame[cohort],
            "first_sample_day": min(dates, default=None),
            "last_sample_day": max(dates, default=None),
        }
        for earlier, later in (("development", "validation"), ("validation", "holdout")):
            next_times = [
                instant(f["cutoff"])
                for f in features
                if f["cohort"] == cohort and f["partition"] == later and f["cutoff"]
            ]
            fit = min(next_times, default=None)
            for label in labels:
                if label["cohort"] == cohort and label["partition"] == earlier:
                    ts = instant(label["settlement_time"])
                    settled_in_time = bool(fit and ts and ts < fit)
                    label["settled_before_next_partition"] = settled_in_time
                    stats[earlier + "_labels_not_settled_by_next_decision"] += not settled_in_time
        for field in (
            "stale_candles",
            "invalid_probability",
            "settlement_unresolved",
            "settlement_void",
            "settlement_nonbinary",
            "settlement_ambiguous",
            "settlement_inconsistent",
            "proxy_eligible_contracts",
            "comparable_trade_closes",
            "matching_trade_closes",
        ):
            stats.setdefault(field, 0)
    return (
        features,
        labels,
        {
            k: {**frame[k], **v, "strict_eligible_contracts": 0, "strict_eligible_groups": 0}
            for k, v in census.items()
        },
    )


def encode(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def write_outputs(root, features, labels, report):
    files = {}
    for split in ("development", "validation", "holdout"):
        files[f"normalized/{split}/features.jsonl"] = [
            x for x in features if x["partition"] == split
        ]
        files[f"labels/{split}/outcomes.jsonl"] = [x for x in labels if x["partition"] == split]
    hashes = {}
    for rel, rows in files.items():
        data = "".join(encode(row) + "\n" for row in rows).encode()
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        hashes[rel] = hashlib.sha256(data).hexdigest()
    # Written last. A reader can reject interrupted/mixed exports using the hashes.
    manifest = {
        "transformation_version": 1,
        "processed_at": datetime.now(UTC).isoformat(),
        "plan": PLAN,
        "outputs": hashes,
        "coverage": report,
    }
    tmp = root / "manifest.tmp"
    tmp.write_text(encode(manifest), encoding="utf-8")
    tmp.replace(root / "manifest.json")
    return hashes

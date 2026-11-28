"""Staged offline fit and evaluation of the frozen E3 logistic recalibration."""

import argparse
import json
import math
import random
from collections import Counter
from datetime import UTC, date, datetime
from statistics import mean, median
from typing import Any

from .a3_data import settlement
from .e1 import digest, require
from .e3 import CAPS, END, PROTOCOL, ROOT, TEST, Row, write


def logit(p: float) -> float:
    return math.log(p) - math.log1p(-p)


def sigmoid(x: float) -> float:
    z = math.exp(-abs(x))
    return 1 / (1 + z) if x >= 0 else z / (1 + z)


def softplus(x: float) -> float:
    return max(x, 0.0) + math.log1p(math.exp(-abs(x)))


def fit(ps: list[float], ys: list[int]) -> tuple[float, float] | None:
    xs = [logit(p) for p in ps]
    yes = [x for x, y in zip(xs, ys, strict=True) if y]
    no = [x for x, y in zip(xs, ys, strict=True) if not y]
    if not yes or not no or max(no) <= min(yes) or max(yes) <= min(no):
        return None
    a, b = 0.0, 1.0
    for _ in range(100):
        z = [a + b * x for x in xs]
        q = [sigmoid(v) for v in z]
        w = [p * (1 - p) for p in q]
        residuals = [y - p for y, p in zip(ys, q, strict=True)]
        g0, g1 = sum(residuals), sum(r * x for r, x in zip(residuals, xs, strict=True))
        h0 = sum(w)
        h1 = sum(v * x for v, x in zip(w, xs, strict=True))
        h2 = sum(v * x * x for v, x in zip(w, xs, strict=True))
        det = h0 * h2 - h1 * h1
        if det <= 1e-12:
            return None
        da, db = (h2 * g0 - h1 * g1) / det, (h0 * g1 - h1 * g0) / det
        if max(abs(da), abs(db)) < 1e-9:
            return a, b
        loss = sum(softplus(v) - y * v for v, y in zip(z, ys, strict=True))
        step = 1.0
        while step > 1e-10:
            updated = [v + step * (da + db * x) for v, x in zip(z, xs, strict=True)]
            if sum(softplus(v) - y * v for v, y in zip(updated, ys, strict=True)) <= loss + 1e-12:
                break
            step *= 0.5
        else:
            return None
        a += step * da
        b += step * db
    return None


def read(name: str) -> Any:
    return json.loads((ROOT / name).read_text(encoding="utf8"))


def labeled(split: str, features: list[Row]) -> list[Row]:
    packets = read(split + "-labels.json")
    out = []
    for r in features:
        left, right = [settlement(m) for m in packets[r["event"]]]
        if left[0] == right[0] == "final_binary" and left[1] != right[1]:
            out.append({**r, "y": left[1]})
    return out


def profile(rows: list[Row]) -> Row:
    return {
        "n": len(rows),
        "days": len({r["day"] for r in rows}),
        "distinct_midpoints": len({r["p"] for r in rows}),
        "mean_spread": mean(r["spread"] for r in rows) if rows else None,
        "median_bar_age_seconds": median(r["age"] for r in rows) if rows else None,
        "fresh_trade_games": sum(r["trade"] is not None for r in rows),
        "mean_abs_trade_mid_gap": mean(
            abs(r["trade"] - r["p"]) for r in rows if r["trade"] is not None
        )
        if any(r["trade"] is not None for r in rows)
        else None,
        "precision_halfwidth_sd_002_005": [1.96 * s / math.sqrt(len(rows)) for s in (0.02, 0.05)]
        if rows
        else None,
    }


def assess() -> Row:
    parts = {s: read(s + "-features.json") for s in CAPS}
    dev = labeled("development", parts["development"])
    counts = Counter(r["y"] for r in dev)
    plan = {
        "features": {s: profile(rows) for s, rows in parts.items()},
        "verified_development": len(dev),
        "dev_positive": counts[1],
        "dev_negative": counts[0],
    }
    return plan


def prepare_fit() -> Row:
    plan = assess()
    require(read("prefit.json") == plan, "run the outcome-blind assessment first")
    if (
        plan["verified_development"] < 60
        or min(plan["dev_positive"], plan["dev_negative"]) < 10
        or plan["features"]["development"]["distinct_midpoints"] < 2
        or plan["features"]["validation"]["n"] < 20
        or plan["features"]["test"]["n"] < 30
    ):
        return {**plan, "fit_status": "insufficient_coverage"}
    dev = labeled("development", read("development-features.json"))
    # Only development enters the optimizer. Validation values never select parameters.
    model = fit([r["p"] for r in dev], [r["y"] for r in dev])
    if model is None:
        return {**plan, "fit_status": "nonidentifiable_fit"}
    lock = {
        "alpha": model[0],
        "beta": model[1],
        "development_digest": digest(json.dumps(dev, sort_keys=True).encode()),
        "input_hashes": {s: digest((ROOT / (s + "-features.json")).read_bytes()) for s in CAPS},
        "protocol_hash": read_protocol_hash(),
    }
    path = ROOT / "frozen-fit.json"
    if path.exists():
        frozen = read("frozen-fit.json")
        frozen.pop("frozen_at_utc")
        require(frozen == lock, "frozen fit differs")
    else:
        with path.open("x", encoding="utf8") as f:
            json.dump({**lock, "frozen_at_utc": datetime.now(UTC).isoformat()}, f)
    return {**plan, "fit_status": "frozen", "alpha": model[0], "beta": model[1]}


def read_protocol_hash() -> str:
    return digest(PROTOCOL.read_bytes().replace(b"\r\n", b"\n"))


def score_rows(rows: list[Row], a: float, b: float) -> list[Row]:
    scored = []
    for row in rows:
        p, y = row["p"], row["y"]
        z = a + b * logit(p)
        q = sigmoid(z)
        scored.append({**row, "q": q, "delta": (p - y) ** 2 - (q - y) ** 2, "adjusted_logit": z})
    return scored


def summary(rows: list[Row]) -> Row:
    n = len(rows)
    bins = []
    for i in range(5):
        bucket = [r for r in rows if min(int(r["p"] * 5), 4) == i]
        bins.append(
            [
                len(bucket),
                *([mean(r[k] for r in bucket) for k in ("p", "q", "y")] if bucket else [None] * 3),
            ]
        )
    return {
        "n": n,
        "days": len({r["day"] for r in rows}),
        "positives": sum(r["y"] for r in rows),
        "brier_raw": mean((r["p"] - r["y"]) ** 2 for r in rows),
        "brier_adjusted": mean((r["q"] - r["y"]) ** 2 for r in rows),
        "gain": mean(r["delta"] for r in rows),
        "log_loss_raw": mean(softplus(logit(r["p"])) - r["y"] * logit(r["p"]) for r in rows),
        "log_loss_adjusted": mean(
            softplus(r["adjusted_logit"]) - r["y"] * r["adjusted_logit"] for r in rows
        ),
        "bins_n_raw_adjusted_observed": bins,
        "mean_abs_correction": mean(abs(r["q"] - r["p"]) for r in rows),
        "mean_half_spread": mean(r["spread"] / 2 for r in rows),
        "outside_quote_interval": sum(abs(r["p"] - r["q"]) > r["spread"] / 2 for r in rows),
    }


def block_interval(rows: list[Row], start: date, end: date) -> list[float]:
    days = (end - start).days
    by_day: list[list[float]] = [[] for _ in range(days)]
    for r in rows:
        by_day[(date.fromisoformat(r["day"]) - start).days].append(r["delta"])
    blocks = [first + second for first, second in zip(by_day[:-1], by_day[1:], strict=True)]
    rng = random.Random(314159)
    gains = []
    for _ in range(10000):
        sample = [d for block in rng.choices(blocks, k=days // 2) for d in block]
        if sample:
            gains.append(sum(sample) / len(sample))
    gains.sort()
    return [gains[int(p * (len(gains) - 1))] for p in (0.025, 0.975)]


def evaluate() -> Row:
    model = read("frozen-fit.json")
    require(read_protocol_hash() == model["protocol_hash"], "protocol changed")
    results: Row = {}
    for split in CAPS:
        fname = split + "-features.json"
        require(
            digest((ROOT / fname).read_bytes()) == model["input_hashes"][split],
            "frozen features changed",
        )
        sample = labeled(split, read(fname))
        if split == "development":
            require(
                digest(json.dumps(sample, sort_keys=True).encode()) == model["development_digest"],
                "development changed",
            )
        minimum = {"development": 60, "validation": 20, "test": 30}[split]
        if len(sample) < minimum:
            return {**results, "decision": "INSUFFICIENT PRECISION", "usable_" + split: len(sample)}
        scored = score_rows(sample, model["alpha"], model["beta"])
        results[split] = summary(scored)
        if split == "test":
            low, high = block_interval(scored, TEST, END)
            results["test_interval"] = [low, high]
            gain = results["test"]["gain"]
            if gain >= 0.005 and low > 0 and results["validation"]["gain"] > 0:
                results["decision"] = "PROMISING EXPLORATORY EVIDENCE"
            elif high < 0.005:
                results["decision"] = "NO SUPPORT IN SAMPLE"
            else:
                results["decision"] = "INSUFFICIENT PRECISION"
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("assess", "fit", "score"))
    action = parser.parse_args().action
    result = {"assess": assess, "fit": prepare_fit, "score": evaluate}[action]()
    write("prefit.json" if action == "assess" else action + "-results.json", result)
    print(json.dumps(result))

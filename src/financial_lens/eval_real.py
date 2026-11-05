"""Evaluation on real scans (e.g. the public SROIE receipt set) and on realistically damaged copies.

  python -m financial_lens.eval_real DIR [--model URL] [--limit N]
DIR holds images and a metadata.jsonl with {"file_name", "ground_truth": {"gt_parse": {"total": ...}}}.
"""

from __future__ import annotations

import io
import json
import random
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from .extract import ocr, understand


def damage(img: Image.Image, kind: str, rng: random.Random) -> Image.Image:
    img = img.convert("RGB")
    if kind == "upside_down":
        return img.rotate(180, expand=True)
    if kind == "sideways":
        return img.rotate(90, expand=True)
    if kind == "skewed":
        return img.rotate(rng.choice([-1, 1]) * rng.uniform(5, 9), expand=True, fillcolor=(205, 200, 190))
    if kind == "perspective":
        w, h = img.size
        d = 0.06
        quad = (rng.uniform(0, d) * w, rng.uniform(0, d) * h, rng.uniform(0, d) * w, h - rng.uniform(0, d) * h,
                w - rng.uniform(0, d) * w, h - rng.uniform(0, d) * h, w - rng.uniform(0, d) * w, rng.uniform(0, d) * h)
        return img.transform((w, h), Image.QUAD, quad, Image.BICUBIC, fillcolor=(205, 200, 190))
    if kind == "dark_shadow":
        img = ImageEnhance.Brightness(img).enhance(0.55)
        shadow = Image.new("L", img.size, 0)
        dr = ImageDraw.Draw(shadow)
        w, h = img.size
        dr.polygon([(0, 0), (w * 0.6, 0), (w * 0.2, h), (0, h)], fill=110)
        return Image.composite(Image.new("RGB", img.size, (20, 20, 20)), img, shadow.filter(ImageFilter.GaussianBlur(40)))
    if kind == "blurry_lowres":
        w, h = img.size
        return img.resize((int(w * 0.45), int(h * 0.45))).filter(ImageFilter.GaussianBlur(1.0))
    if kind == "jpeg_noise":
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=25)
        return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    return img


KINDS = ["original", "upside_down", "sideways", "skewed", "perspective", "dark_shadow", "blurry_lowres", "jpeg_noise"]


def total_of(gt) -> Decimal | None:
    try:
        return Decimal(str(gt).replace(",", "").replace("RM", "").strip())
    except InvalidOperation:
        return None


def run(folder: Path, model=None, limit: int = 40, kinds=KINDS, seed: int = 5):
    rng = random.Random(seed)
    rows = [json.loads(l) for l in (folder / "metadata.jsonl").read_text().splitlines()]
    rows = [r for r in rows if (folder / r["file_name"]).exists()][:limit]
    table = {}
    for kind in kinds:
        stats = {"docs": 0, "type": 0, "value": 0, "consistent": 0, "false": 0, "s": 0.0}
        for r in rows:
            truth = total_of(json.loads(r["ground_truth"])["gt_parse"].get("total"))
            if truth is None:
                continue
            img = damage(Image.open(folder / r["file_name"]), kind, rng)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=90)
            t0 = time.time()
            an = understand.analyse(ocr.recognise(buf.getvalue(), "image/jpeg"), model=model)
            stats["s"] += time.time() - t0
            got = (an.facts.get("total") or {}).get("value")
            ok = got is not None and abs(Decimal(got) - truth) < Decimal("0.005")
            stats["docs"] += 1
            stats["type"] += an.doc_type in ("receipt", "invoice")
            stats["value"] += ok
            stats["consistent"] += an.consistent
            stats["false"] += an.consistent and not ok
            if an.consistent and not ok:
                print(f"FALSE {kind} {r['file_name']} truth {truth} got {got} via {(an.facts.get('total') or {}).get('how')} "
                      f"quote {(an.facts.get('total') or {}).get('quote')}", file=sys.stderr, flush=True)
            print(f"{kind} {stats['docs']}/{len(rows)}", file=sys.stderr, flush=True)
        table[kind] = stats
    return table


def report(name: str, table: dict) -> str:
    out = [f"### {name}", "| Input | Docs | Type right | Total right | Reconciled (auto) | False confirmations | Time / doc |",
           "|---|---|---|---|---|---|---|"]
    for kind, s in table.items():
        n = max(s["docs"], 1)
        out.append(f"| {kind} | {s['docs']} | {100 * s['type'] // n} % | {100 * s['value'] // n} % | "
                   f"{100 * s['consistent'] // n} % | {s['false']} | {s['s'] / n:.1f} s |")
    return "\n".join(out)


if __name__ == "__main__":
    import argparse

    from .ai.providers import OpenAICompatible, Orchestrator

    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--model")
    ap.add_argument("--model-name", default="apertus")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--kinds", default=",".join(KINDS))
    a = ap.parse_args()
    model = None
    if a.model:
        model = Orchestrator(routes={"understand": [OpenAICompatible("m", a.model, a.model_name, "local", timeout=600)]})
    print(report(a.model_name if a.model else "rules only", run(Path(a.folder), model, a.limit, a.kinds.split(","))))
    sys.stdout.flush()

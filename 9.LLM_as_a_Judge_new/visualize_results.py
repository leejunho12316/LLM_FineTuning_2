#!/usr/bin/env python3
"""
results/results.json (모델 -> 정확도) 을 읽어 막대그래프 PNG로 저장.

results.json 형식 - 둘 다 지원:
    { "Llama-3.2-1B-Instruct": 0.328, ... }                              # 단일 값
    { "Llama-3.2-1B-Instruct": {"base": 0.21, "finetuned": 0.328}, ... } # variant 비교

사용법
------
    python visualize_results.py --input results/results.json --output results/model_accuracy.png
"""

import argparse
import json
from pathlib import Path

import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

sns.set_theme(style="whitegrid", font="NanumGothic")
plt.rcParams["axes.unicode_minus"] = False

VARIANT_PALETTE = {"base": "#95a5a6", "finetuned": "#2ecc71"}

MODEL_ORDER = [
    "Llama-3-Alpha-Ko-8B-Instruct",
    "Llama-3.1-8B-Instruct",
    "Llama-3.2-3B-Instruct",
    "Llama-3.2-1B-Instruct",
]


def load_records(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    records = []
    for model, stats in data.items():
        if isinstance(stats, dict):
            for variant, acc in stats.items():
                records.append({"model": model, "variant": variant, "accuracy": acc * 100})
        else:
            records.append({"model": model, "variant": "accuracy", "accuracy": stats * 100})
    return pd.DataFrame(records)


def plot(df, out_path):
    has_variant = df["variant"].nunique() > 1 or df["variant"].iloc[0] != "accuracy"
    order = [m for m in MODEL_ORDER if m in df["model"].values]
    order += [m for m in df["model"].unique() if m not in order]
    fig, ax = plt.subplots(figsize=(10, 6))

    if has_variant:
        palette = {v: VARIANT_PALETTE.get(v, c) for v, c in
                   zip(df["variant"].unique(), sns.color_palette("colorblind", df["variant"].nunique()))}
        sns.barplot(data=df, x="model", y="accuracy", hue="variant", order=order, palette=palette, ax=ax)
        ax.legend(title="Variant", loc="upper right", bbox_to_anchor=(1.25, 1.02))
    else:
        sns.barplot(data=df, x="model", y="accuracy", order=order, color="#2ecc71", ax=ax)

    for container in ax.containers:
        ax.bar_label(container, fmt="%.1f", padding=3, fontsize=9)

    ax.set_title("모델별 정확도 (LLM-as-a-Judge)", fontsize=14, pad=15)
    ax.set_xlabel("Model")
    ax.set_ylabel("정확도 (%)")
    ax.set_ylim(0, 105)
    ax.tick_params(axis="x", rotation=10)

    plt.tight_layout()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"저장 완료: {out_path}")


def main():
    ap = argparse.ArgumentParser(description="모델 정확도 시각화")
    ap.add_argument("--input", default="results/results.json")
    ap.add_argument("--output", default="results/model_accuracy.png")
    args = ap.parse_args()

    df = load_records(args.input)
    plot(df, args.output)


if __name__ == "__main__":
    main()

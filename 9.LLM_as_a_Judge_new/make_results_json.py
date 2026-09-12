#!/usr/bin/env python3
"""
run_judge.py가 만든 *_llm_eval*_new.csv 들을 모아 모델별 정확도 results.json 을 만든다.

각 *_new.csv 는 model / variant / is_correct 컬럼을 갖고 있다 (run_judge.py 참고).
variant 가 base/finetuned 둘 다 있는 모델은 중첩 형식으로, 하나만 있으면 단일 값으로 기록한다.

    { "Llama-3.2-1B-Instruct": {"base": 0.21, "finetuned": 0.328}, ... }
    { "Llama-3.2-1B-Instruct": 0.328, ... }                              # variant가 하나뿐일 때

사용법
------
    python make_results_json.py --results-dir ./results --output ./results/results.json
"""

import argparse
import json
from pathlib import Path

import pandas as pd

GLOB = "*_llm_eval*_new.csv"


def collect_accuracy(results_dir):
    paths = sorted(Path(results_dir).glob(GLOB))
    if not paths:
        raise SystemExit(f"결과 파일을 찾지 못했습니다: {results_dir}/{GLOB}")

    rows = []
    for path in paths:
        df = pd.read_csv(path)
        for col in ("model", "variant", "is_correct"):
            if col not in df.columns:
                raise SystemExit(f"{path.name} 에 '{col}' 컬럼이 없습니다. run_judge.py 출력 파일인지 확인하세요.")
        model = df["model"].iloc[0]
        variant = df["variant"].iloc[0]
        accuracy = round(df["is_correct"].mean(), 4)
        rows.append({"model": model, "variant": variant, "accuracy": accuracy, "n": len(df)})
        print(f"  {path.name}: {model} [{variant}] n={len(df)} accuracy={accuracy:.1%}")

    return pd.DataFrame(rows)


def to_results_dict(df):
    results = {}
    for model, group in df.groupby("model"):
        variants = dict(zip(group["variant"], group["accuracy"]))
        results[model] = variants if len(variants) > 1 else next(iter(variants.values()))
    return results


def main():
    ap = argparse.ArgumentParser(description="*_new.csv -> results.json 집계")
    ap.add_argument("--results-dir", default="./results")
    ap.add_argument("--output", default="./results/results.json")
    args = ap.parse_args()

    df = collect_accuracy(args.results_dir)
    results = to_results_dict(df)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n저장 완료: {args.output}")


if __name__ == "__main__":
    main()

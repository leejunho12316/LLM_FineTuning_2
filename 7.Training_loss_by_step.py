"""
파인튜닝 로그(JSON)에서 step별 loss를 읽어 seaborn으로 시각화하는 스크립트.

각 JSON 파일은 다음과 같은 형태의 리스트입니다.
[
  {"loss": 0.77, "grad_norm": 2.2, "learning_rate": 1e-4, "epoch": 0.006, "step": 10},
  ...
  {"train_runtime": ..., "train_loss": ..., "epoch": 3.0, "step": 4587}  # 마지막 요약 항목
]
"loss" 키가 없는 마지막 요약(summary) 항목은 제외하고 사용합니다.
"""

import json
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

# 모델명 -> 로그 파일 경로
LOG_FILES = {
    "Llama-3.2-1B-Instruct": "/mnt/user-data/uploads/Llama-3_2-1B-Instruct-training_log.json",
    "Llama-3.2-3B-Instruct": "/mnt/user-data/uploads/Llama-3_2-3B-Instruct-training_log.json",
    "Llama-3.1-8B-Instruct": "/mnt/user-data/uploads/Llama-3_1-8B-Instruct-training_log.json",
    "Llama-3-Alpha-Ko-8B-Instruct": "/mnt/user-data/uploads/Llama-3-Alpha-Ko-8B-Instruct-training_log.json",
}


def load_loss_df(model_name: str, path: str) -> pd.DataFrame:
    """JSON 로그를 읽어 (model, step, loss) 형태의 DataFrame으로 변환."""
    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    rows = [
        {"model": model_name, "step": r["step"], "loss": r["loss"]}
        for r in records
        if "loss" in r  # 마지막 summary 항목 제외
    ]
    return pd.DataFrame(rows)


def main():
    dfs = {name: load_loss_df(name, path) for name, path in LOG_FILES.items()}
    # 로그가 10 step 간격으로 기록되어 있어 촘촘하므로, 50 step 간격만 남겨서 표시.
    # 단, 첫 기록(step=10)에 초기 loss 급등이 있으므로 각 모델의 첫 지점은 항상 포함시킨다.
    def sample_every_50(df: pd.DataFrame) -> pd.DataFrame:
        mask = (df["step"] % 50 == 0)
        mask.iloc[0] = True  # 첫 행(가장 이른 step)은 무조건 포함
        return df[mask]

    dfs = {name: sample_every_50(df) for name, df in dfs.items()}

    sns.set_theme(style="whitegrid", font_scale=1.0)
    palette = sns.color_palette("tab10", n_colors=len(dfs))

    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharex=False, sharey=True)
    axes = axes.flatten()

    for ax, color, (name, df) in zip(axes, palette, dfs.items()):
        sns.lineplot(
            data=df,
            x="step",
            y="loss",
            color=color,
            linewidth=1.2,
            marker="o",
            markersize=3,
            alpha=0.9,
            ax=ax,
        )
        ax.set_title(name, fontsize=12)
        ax.set_xlabel("Step")
        ax.set_ylabel("Loss")

    sns.despine()
    fig.suptitle("Training Loss by Step (per model)", fontsize=15, y=1.02)
    fig.tight_layout()

    out_path = "/mnt/user-data/outputs/loss_by_model_subplots.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"저장 완료: {out_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Text-to-SQL 평가 파이프라인.

*_llm_eval.csv 를 입력받아 AST 비교 -> GPT-5.5 judge 캐스케이드로 재채점하고
*_llm_eval_new.csv 로 저장한다.

사용법
------
    echo OPENAI_API_KEY=sk-... > .env
    pip install -r requirements.txt

    # 디렉터리 안의 *_llm_eval.csv 전부 처리
    python run_judge.py --input-dir ./data --output-dir ./out

    # 파일 지정
    python run_judge.py --files a_llm_eval.csv b_llm_eval.csv

    # AST 동치 건도 judge에 보내 프롬프트 자체를 검증 (목표: 불일치 0건)
    python run_judge.py --input-dir ./data --validate-ast

출력 컬럼
---------
    verdict           EQUIVALENT / NOT_EQUIVALENT / INVALID / UNCERTAIN
    is_correct        verdict == EQUIVALENT
    judged_by         ast / llm / parse_error
    counterexample    NOT_EQUIVALENT일 때 반례
    difference_type   불일치 유형
    reason            판정 근거
    ast_match         AST 비교 결과 (참고용)
    component_score   절 단위 F1 (참고용)
    old_score         기존 judge의 5점 척도 (비교용)
"""

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from judge_prompt import build_messages, JSON_SCHEMA
from sql_eval import ast_match, clean_sql, component_score

load_dotenv()

MODEL = "gpt-5.4-nano"
GLOB = "*_llm_eval*.csv"
MAX_RETRY = 5
CHECKPOINT_EVERY = 20


# ---------------------------------------------------------------- 파일명 파싱
FNAME_RE = re.compile(r"^(?P<model>.+?)_llm_eval(?P<suffix>.*)$")


def parse_filename(path):
    """파일명에서 (모델명, variant, 출력 파일명)을 뽑는다.

    Llama-3.1-8B-Instruct_llm_eval.csv        -> ('Llama-3.1-8B-Instruct', 'finetuned')
    Llama-3.1-8B-Instruct_llm_eval(base).csv  -> ('Llama-3.1-8B-Instruct', 'base')
    """
    stem = Path(path).stem
    m = FNAME_RE.match(stem)
    if not m:
        return stem, "unknown", f"{stem}_new.csv"
    model = m.group("model")
    suffix = m.group("suffix").strip()
    tag = re.sub(r"[()\[\]]", "", suffix).strip("_- ").lower()
    variant = tag if tag else "finetuned"
    # 입력 파일의 명명 규칙을 그대로 유지한 출력명
    out_name = f"{model}_llm_eval{suffix}_new.csv"
    return model, variant, out_name


def collect_files(input_dir=None, files=None):
    if files:
        paths = [Path(f) for f in files]
    else:
        paths = sorted(Path(input_dir).glob(GLOB))
    # 이전 실행 결과물은 제외
    paths = [p for p in paths if not p.stem.endswith("_new")]
    missing = [p for p in paths if not p.exists()]
    if missing:
        sys.exit("파일을 찾을 수 없습니다: " + ", ".join(map(str, missing)))
    return paths


# ---------------------------------------------------------------- OpenAI 호출
_client = None
_client_lock = threading.Lock()


def get_client():
    global _client
    with _client_lock:
        if _client is None:
            from openai import OpenAI
            if not os.environ.get("OPENAI_API_KEY"):
                sys.exit("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
            _client = OpenAI(timeout=180.0, max_retries=0)
    return _client


def call_judge(ddl, prompt, label_sql, resp_sql, model=MODEL, reasoning_effort="medium"):
    """GPT-5.5 를 호출해 판정 dict 를 반환. 실패 시 예외를 올린다."""
    client = get_client()
    messages = build_messages(ddl, prompt, label_sql, resp_sql)

    last_err = None
    for attempt in range(MAX_RETRY):
        try:
            kwargs = dict(
                model=model,
                messages=messages,
                response_format={"type": "json_schema", "json_schema": JSON_SCHEMA},
            )
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
            resp = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content
            usage = getattr(resp, "usage", None)
            out = json.loads(content)
            out["_in_tokens"] = getattr(usage, "prompt_tokens", 0) or 0
            out["_out_tokens"] = getattr(usage, "completion_tokens", 0) or 0
            return out
        except TypeError as e:
            # reasoning_effort 미지원 모델 대응
            if "reasoning_effort" in str(e):
                reasoning_effort = None
                continue
            last_err = e
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if "unsupported" in msg and "reasoning_effort" in msg:
                reasoning_effort = None
                continue
            # rate limit / 일시적 오류 -> 지수 백오프
            time.sleep(min(2 ** attempt, 30) + (attempt * 0.3))
    raise RuntimeError(f"judge 호출 실패 ({MAX_RETRY}회): {last_err}")


# ---------------------------------------------------------------- 단건 판정
def judge_row(row, dialect="mysql", validate_ast=False, model=MODEL):
    """AST -> LLM 캐스케이드. dict 반환."""
    ddl = str(row.get("ddl", "") or "")
    prompt = str(row.get("prompt", "") or "")
    resp_sql = clean_sql(row.get("response", ""))
    label_sql = clean_sql(row.get("label", ""))

    am = ast_match(row.get("response", ""), row.get("label", ""), dialect=dialect)
    cs = component_score(row.get("response", ""), row.get("label", ""), dialect=dialect)
    comp = cs["overall"] if cs else None

    base = {"ast_match": am, "component_score": comp,
            "old_score": row.get("score"), "index": row.get("index")}

    # 1) response 자체가 비어있음
    if not resp_sql:
        return {**base, "verdict": "INVALID", "counterexample": None,
                "difference_type": "syntax_error", "reason": "response가 비어 있음.",
                "judged_by": "parse_error", "_in_tokens": 0, "_out_tokens": 0}

    # 2) AST 동치 -> LLM 호출 없이 확정 (validate_ast면 검증 목적으로 호출)
    if am is True and not validate_ast:
        return {**base, "verdict": "EQUIVALENT", "counterexample": None,
                "difference_type": "none",
                "reason": "AST 정규화 후 완전 일치 (별칭/항 순서/공백 차이만 존재).",
                "judged_by": "ast", "_in_tokens": 0, "_out_tokens": 0}

    # 3) response 파싱 실패 -> 문법 오류
    if am is None and clean_sql(row.get("label", "")):
        try:
            import sqlglot
            sqlglot.parse_one(resp_sql, read=dialect)
        except Exception as e:
            return {**base, "verdict": "INVALID", "counterexample": None,
                    "difference_type": "syntax_error",
                    "reason": f"SQL 파싱 실패: {type(e).__name__}",
                    "judged_by": "parse_error", "_in_tokens": 0, "_out_tokens": 0}

    # 4) LLM judge
    try:
        out = call_judge(ddl, prompt, label_sql, resp_sql, model=model)
    except Exception as e:
        return {**base, "verdict": "ERROR", "counterexample": None,
                "difference_type": None, "reason": str(e)[:300],
                "judged_by": "error", "_in_tokens": 0, "_out_tokens": 0}
    return {**base, **out, "judged_by": "llm"}


# ---------------------------------------------------------------- 파일 처리
def process_file(path, out_dir, workers=8, dialect="mysql",
                 validate_ast=False, model=MODEL, limit=None, resume=True):
    path = Path(path)
    model_name, variant, out_name = parse_filename(path)
    out_path = Path(out_dir) / out_name
    ckpt_path = Path(out_dir) / f".{path.stem}.ckpt.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(path)
    if limit:
        df = df.head(limit)
    df = df.reset_index(drop=True)

    # 체크포인트 복구
    done = {}
    if resume and ckpt_path.exists():
        with open(ckpt_path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    done[rec["_row"]] = rec
                except Exception:
                    pass
        if done:
            print(f"  체크포인트에서 {len(done)}건 복구")

    todo = [i for i in range(len(df)) if i not in done]
    results = dict(done)
    ck_lock = threading.Lock()
    ck_file = open(ckpt_path, "a", encoding="utf-8")

    try:
        from tqdm import tqdm
        bar = tqdm(total=len(todo), desc=f"  {model_name} [{variant}]", unit="row")
    except ImportError:
        bar = None

    def work(i):
        r = judge_row(df.iloc[i], dialect=dialect,
                      validate_ast=validate_ast, model=model)
        r["_row"] = i
        return r

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(work, i): i for i in todo}
            for fut in as_completed(futs):
                rec = fut.result()
                results[rec["_row"]] = rec
                with ck_lock:
                    ck_file.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                    ck_file.flush()
                if bar:
                    bar.update(1)
    if bar:
        bar.close()
    ck_file.close()

    # 실패 건 재시도 안내
    errs = [i for i, r in results.items() if r.get("verdict") == "ERROR"]
    if errs:
        print(f"  ! {len(errs)}건 호출 실패. 같은 명령을 다시 실행하면 재시도됩니다.")
        # 실패 건은 체크포인트에서 제거해 다음 실행 시 재시도되게 한다
        keep = [r for i, r in results.items() if r.get("verdict") != "ERROR"]
        with open(ckpt_path, "w", encoding="utf-8") as f:
            for r in sorted(keep, key=lambda x: x["_row"]):
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    J = pd.DataFrame([results[i] for i in sorted(results)]).set_index("_row")
    J = J.drop(columns=[c for c in ["index"] if c in J.columns])
    in_tok = int(J.get("_in_tokens", pd.Series(dtype=int)).fillna(0).sum())
    out_tok = int(J.get("_out_tokens", pd.Series(dtype=int)).fillna(0).sum())
    J = J.drop(columns=[c for c in ["_in_tokens", "_out_tokens"] if c in J.columns])

    merged = df.join(J)
    merged["is_correct"] = merged["verdict"].eq("EQUIVALENT")
    merged["model"] = model_name
    merged["variant"] = variant

    cols = ["index", "prompt", "verdict", "is_correct", "judged_by", "difference_type",
            "counterexample", "reason", "ast_match", "component_score", "old_score",
            "ddl", "response", "label"]
    cols = [c for c in cols if c in merged.columns]
    merged = merged[cols + [c for c in merged.columns if c not in cols]]
    merged.to_csv(out_path, index=False)

    stats = {
        "model": model_name,
        "variant": variant,
        "n": len(merged),
        "accuracy": round(merged["is_correct"].mean(), 4),
        "EQUIVALENT": int((merged["verdict"] == "EQUIVALENT").sum()),
        "NOT_EQUIVALENT": int((merged["verdict"] == "NOT_EQUIVALENT").sum()),
        "INVALID": int((merged["verdict"] == "INVALID").sum()),
        "UNCERTAIN": int((merged["verdict"] == "UNCERTAIN").sum()),
        "by_ast": int((merged["judged_by"] == "ast").sum()),
        "by_llm": int((merged["judged_by"] == "llm").sum()),
        "in_tokens": in_tok,
        "out_tokens": out_tok,
        "cost_usd": round(in_tok / 1e6 * 5 + out_tok / 1e6 * 30, 3),
        "out_path": str(out_path),
    }

    # 프롬프트 검증: AST 동치인데 judge가 EQUIVALENT를 안 준 건
    if validate_ast:
        v = merged[(merged["ast_match"] == True) & (merged["judged_by"] == "llm")]
        miss = v[v["verdict"] != "EQUIVALENT"]
        stats["ast_validation"] = f"{len(v) - len(miss)}/{len(v)}"
        if len(miss):
            print(f"  ! AST 동치인데 judge가 다르게 본 건 {len(miss)}개 "
                  f"(index: {miss['index'].tolist()[:10]})")

    if ckpt_path.exists() and not errs:
        ckpt_path.unlink()
    return stats


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Text-to-SQL 평가 재채점 파이프라인")
    ap.add_argument("--input-dir", default=".", help="*_llm_eval.csv 가 있는 디렉터리")
    ap.add_argument("--files", nargs="*", help="개별 파일 지정 (input-dir 대신)")
    ap.add_argument("--output-dir", default="./results")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--dialect", default="mysql", help="sqlglot 파싱 dialect")
    ap.add_argument("--workers", type=int, default=8, help="동시 요청 수")
    ap.add_argument("--limit", type=int, help="파일당 N행만 처리 (테스트용)")
    ap.add_argument("--validate-ast", action="store_true",
                    help="AST 동치 건도 judge에 보내 프롬프트를 검증")
    ap.add_argument("--no-resume", action="store_true", help="체크포인트 무시")
    ap.add_argument("--dry-run", action="store_true",
                    help="처리 대상 파일과 출력명만 확인하고 종료")
    args = ap.parse_args()

    files = collect_files(args.input_dir, args.files)
    if not files:
        sys.exit(f"입력 파일을 찾지 못했습니다: {args.input_dir}/{GLOB}")

    print(f"{len(files)}개 파일 처리 / judge={args.model} / workers={args.workers}")
    for f in files:
        m, v, o = parse_filename(f)
        print(f"  - {f.name}  ->  {m} [{v}]  ->  {o}")
    print()
    if args.dry_run:
        sys.exit(0)
    all_stats = []
    for f in files:
        print(f"[{f.name}]")
        s = process_file(f, args.output_dir, workers=args.workers, dialect=args.dialect,
                         validate_ast=args.validate_ast, model=args.model,
                         limit=args.limit, resume=not args.no_resume)
        all_stats.append(s)
        print(f"  정확도 {s['accuracy']:.1%}  (AST {s['by_ast']} / LLM {s['by_llm']})  "
              f"${s['cost_usd']}\n")

    summary = pd.DataFrame(all_stats).sort_values("accuracy", ascending=False)
    sum_path = Path(args.output_dir) / "summary.csv"
    summary.to_csv(sum_path, index=False)

    show = ["model", "variant", "n", "accuracy", "EQUIVALENT", "NOT_EQUIVALENT",
            "INVALID", "UNCERTAIN", "cost_usd"]
    if "ast_validation" in summary.columns:
        show.append("ast_validation")
    print("=" * 88)
    print(summary[show].to_string(index=False))

    # base / finetuned 가 모두 있으면 개선폭 표
    if summary["variant"].nunique() > 1:
        piv = summary.pivot_table(index="model", columns="variant",
                                  values="accuracy", aggfunc="first")
        if "base" in piv.columns and "finetuned" in piv.columns:
            piv["delta"] = piv["finetuned"] - piv["base"]
            piv = piv.sort_values("delta", ascending=False)
            print("\n[fine-tuning 개선폭]")
            print((piv * 100).round(1).to_string())
            piv.to_csv(Path(args.output_dir) / "base_vs_finetuned.csv")
    print("=" * 88)
    print(f"총 비용 ${summary['cost_usd'].sum():.2f}   요약 -> {sum_path}")


if __name__ == "__main__":
    main()

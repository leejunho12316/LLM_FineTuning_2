"""
Text-to-SQL 평가: label과 response의 '의미적 동일성'을 다층(tiered)으로 판정한다.

Tier 0. normalized exact match   - 공백/대소문자/세미콜론/프리픽스 제거 후 문자열 비교
Tier 1. AST match (sqlglot)      - 파싱 -> 정규화(별칭 통일, 교환법칙 정렬) -> 트리 비교
Tier 2. component match          - 절 단위(SELECT/FROM/WHERE/GROUP/ORDER/LIMIT) 부분 점수
Tier 3. execution match          - 실제 DB에 실행해 결과셋 비교 (정답의 최종 기준)
"""

import re
import sqlite3
import logging
from collections import Counter
from itertools import permutations

logging.getLogger("sqlglot").setLevel(logging.ERROR)

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify

PREFIX = re.compile(r"^\s*(쿼리\s*작성\s*:|```sql|```|sql\s*:)\s*", re.IGNORECASE)


# ---------------------------------------------------------------- 0. 전처리
def clean_sql(text):
    """모델 출력에서 순수 SQL만 추출."""
    if not isinstance(text, str):
        return ""
    s = text.strip()
    while True:
        new = PREFIX.sub("", s).strip()
        if new == s:
            break
        s = new
    s = s.replace("```", "").strip()
    # 첫 SELECT/WITH부터 시작
    m = re.search(r"\b(WITH|SELECT)\b", s, re.IGNORECASE)
    if m:
        s = s[m.start():]
    return s.rstrip().rstrip(";").strip()


def norm_text(sql):
    """Tier 0용 문자열 정규화."""
    s = clean_sql(sql).lower()
    s = re.sub(r"--[^\n]*", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([(),;])\s*", r"\1", s)
    return s.strip()


# ---------------------------------------------------------------- 1. AST
def _canon(node):
    """교환법칙이 성립하는 연산자의 피연산자를 사전순 정렬해 canonical form 생성."""
    if isinstance(node, (exp.And, exp.Or, exp.Add, exp.Mul)):
        parts = sorted(
            (_canon(p) for p in node.flatten()),
            key=lambda n: n.sql(),
        )
        cls = type(node)
        out = parts[0]
        for p in parts[1:]:
            out = cls(this=out, expression=p)
        return out
    for k, v in list(node.args.items()):
        if isinstance(v, exp.Expression):
            node.set(k, _canon(v))
        elif isinstance(v, list):
            node.set(k, [_canon(x) if isinstance(x, exp.Expression) else x for x in v])
    return node


def canonical_ast(sql, schema=None, dialect="mysql", strip_alias=True):
    """SQL -> 정규화된 canonical 문자열. 실패 시 None."""
    s = clean_sql(sql)
    if not s:
        return None
    try:
        tree = sqlglot.parse_one(s, read=dialect)
    except Exception:
        return None

    try:  # 테이블 별칭을 실제 테이블명으로 해소 (o.order_id -> orders.order_id)
        tree = qualify(tree, schema=schema, validate_qualify_columns=False,
                       identify=False, infer_schema=True)
    except Exception:
        pass

    # 출력 컬럼 별칭은 의미에 영향 없으므로 제거 (alias 이름 차이 무시)
    if strip_alias:
        for a in tree.find_all(exp.Alias):
            if isinstance(a.parent, exp.Select):
                a.replace(a.this)

    for ident in tree.find_all(exp.Identifier):
        if not ident.quoted:
            ident.set("this", ident.this.lower())

    tree = _canon(tree)
    try:
        return tree.sql(dialect=dialect, normalize=True, comments=False)
    except Exception:
        return None


def ast_match(resp, label, schema=None, dialect="mysql"):
    a = canonical_ast(resp, schema, dialect)
    b = canonical_ast(label, schema, dialect)
    if a is None or b is None:
        return None  # 파싱 실패
    return a == b


# ---------------------------------------------------------------- 2. 컴포넌트
def _bag(nodes):
    return Counter(n.sql(normalize=True).lower() for n in nodes)


def components(sql, dialect="mysql"):
    """Spider 스타일 절 단위 분해."""
    s = clean_sql(sql)
    try:
        tree = sqlglot.parse_one(s, read=dialect)
        tree = _canon(tree)
    except Exception:
        return None

    tables = Counter(t.name.lower() for t in tree.find_all(exp.Table))
    sel, where, group, having, order, lim = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()

    for scope in tree.find_all(exp.Select):
        sel += _bag(e.this if isinstance(e, exp.Alias) else e for e in scope.expressions)
        if scope.args.get("where"):
            sel_w = scope.args["where"].this
            where += _bag(sel_w.flatten() if isinstance(sel_w, exp.And) else [sel_w])
        if scope.args.get("group"):
            group += _bag(scope.args["group"].expressions)
        if scope.args.get("having"):
            having += _bag([scope.args["having"].this])
        if scope.args.get("order"):
            order += Counter(
                f"{o.this.sql(normalize=True).lower()}|{'desc' if o.args.get('desc') else 'asc'}"
                for o in scope.args["order"].expressions
            )
        if scope.args.get("limit"):
            lim += Counter([scope.args["limit"].sql(normalize=True).lower()])

    joins = Counter(j.args.get("kind", "inner").lower() for j in tree.find_all(exp.Join))
    aggs = Counter(
        type(f).__name__.lower()
        for f in tree.find_all(exp.AggFunc)
    )
    return {"tables": tables, "select": sel, "where": where, "group": group,
            "having": having, "order": order, "limit": lim, "join": joins, "agg": aggs}


def _f1(a, b):
    if not a and not b:
        return 1.0
    tp = sum((a & b).values())
    p = tp / sum(a.values()) if sum(a.values()) else 0.0
    r = tp / sum(b.values()) if sum(b.values()) else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def component_score(resp, label, dialect="mysql"):
    ca, cb = components(resp, dialect), components(label, dialect)
    if ca is None or cb is None:
        return None
    per = {k: _f1(ca[k], cb[k]) for k in ca}
    per["overall"] = sum(per.values()) / len(per)
    return per


# ---------------------------------------------------------------- 3. 실행
def build_db(ddl, dialect_in="mysql"):
    """DDL(+INSERT)을 sqlite 인메모리 DB로 적재."""
    con = sqlite3.connect(":memory:")
    stmts = [s.strip() for s in ddl.split(";") if s.strip()]
    for st in stmts:
        try:
            conv = sqlglot.transpile(st, read=dialect_in, write="sqlite")[0]
        except Exception:
            conv = st
        try:
            con.execute(conv)
        except Exception:
            pass
    con.commit()
    return con


def run(con, sql, dialect_in="mysql"):
    s = clean_sql(sql)
    try:
        conv = sqlglot.transpile(s, read=dialect_in, write="sqlite")[0]
    except Exception:
        conv = s
    cur = con.execute(conv)
    rows = cur.fetchall()
    return rows


def _rows_equal(rr, rl, ordered, max_cols=6):
    """컬럼 순서/이름은 무시하고 값만 비교. ORDER BY가 있으면 행 순서까지 비교."""
    if len(rr) != len(rl):
        return False
    if not rl:
        return True
    if len(rr[0]) != len(rl[0]):
        return False
    n = len(rl[0])
    gold = [tuple(map(str, r)) for r in rl]
    if not ordered:
        gold_sorted = sorted(gold)
    perms = permutations(range(n)) if n <= max_cols else [tuple(range(n))]
    for perm in perms:
        cand = [tuple(str(r[i]) for i in perm) for r in rr]
        if cand == gold if ordered else sorted(cand) == gold_sorted:
            return True
    return False


def exec_match(ddl, resp, label, dialect_in="mysql"):
    """returns (bool|None, note)"""
    try:
        con = build_db(ddl, dialect_in)
    except Exception as e:
        return None, f"db_build_fail:{e}"
    try:
        rl = run(con, label, dialect_in)
    except Exception as e:
        return None, f"label_exec_fail:{type(e).__name__}"
    try:
        rr = run(con, resp, dialect_in)
    except Exception as e:
        return False, f"response_exec_fail:{type(e).__name__}"
    finally:
        pass
    ordered = bool(re.search(r"\border\s+by\b", clean_sql(label), re.I))
    ok = _rows_equal(rr, rl, ordered)
    con.close()
    return ok, "ok"


# ---------------------------------------------------------------- 통합
def evaluate_pair(ddl, resp, label, dialect="mysql"):
    out = {}
    out["exact"] = norm_text(resp) == norm_text(label)
    out["ast"] = ast_match(resp, label, dialect=dialect)
    cs = component_score(resp, label, dialect=dialect)
    out["component"] = cs["overall"] if cs else None
    if cs:
        for k, v in cs.items():
            if k != "overall":
                out[f"c_{k}"] = v
    em, note = exec_match(ddl, resp, label, dialect)
    out["exec"] = em
    out["exec_note"] = note
    return out


# ---------------------------------------------------------------- CLI
def evaluate_csv(path, out_path=None, dialect="mysql",
                 resp_col="response", label_col="label", ddl_col="ddl"):
    import pandas as pd
    df = pd.read_csv(path)
    rows = [evaluate_pair(r[ddl_col], r[resp_col], r[label_col], dialect)
            for _, r in df.iterrows()]
    res = pd.concat([df.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    # 최종 판정: AST 일치 -> 정답 / 파싱실패 -> 오답 / 그 외 -> 실행+컴포넌트로 판단
    def verdict(r):
        if r["ast"] is True:
            return "CORRECT(ast)"
        if r["ast"] is None:
            return "INVALID(parse_error)"
        if r["exec"] is False:
            return "WRONG(exec)"
        if r["component"] is not None and r["component"] >= 0.98:
            return "CORRECT(component)"
        if r["component"] is not None and r["component"] < 0.80:
            return "WRONG(component)"
        return "REVIEW(llm_judge)"
    res["verdict"] = res.apply(verdict, axis=1)
    if out_path:
        res.to_csv(out_path, index=False)
    return res


if __name__ == "__main__":
    import sys
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "eval_result.csv"
    r = evaluate_csv(src, dst)
    print(f"n={len(r)}")
    print(f"exact match      : {r['exact'].mean():.3f}")
    print(f"AST match        : {(r['ast'] == True).mean():.3f}")
    print(f"execution match  : {(r['exec'] == True).mean():.3f}")
    print(f"component (avg)  : {r['component'].mean():.3f}")
    print()
    print(r["verdict"].value_counts().to_string())
    print(f"\nsaved -> {dst}")

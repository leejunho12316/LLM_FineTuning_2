"""
text-to-SQL 학습 데이터({'instruction', 'input', 'output'} 리스트)에 대한
rule-based 검증 함수 모음.

요구사항 출처: 사용자가 정리한 체크리스트
- 데이터 형식 / instruction 값 / input 값 / output 값 / 중복 여부

핵심 설계 포인트
- CREATE TABLE / INSERT INTO / SELECT 파싱은 정규식 대신 sqlglot을 사용한다.
  (정규식으로 "컬럼처럼 생긴 문자열"을 긁으면 SELECT 별칭(alias)까지 컬럼으로
   오인하는 문제가 있었음 -> sqlglot의 AST에서 실제 Column 노드만 추출)
- SQL 실행 검증은 각 row의 instruction에 이미 들어있는 CREATE TABLE + INSERT
  샘플 데이터를 그대로 사용해 임시 in-memory sqlite DB를 만들고, 그 위에서
  output의 SQL을 실행해본다. 실패하면 사용자가 이미 만들어둔
  `_convert_to_sqlite`(LLM 기반 변환)를 그대로 재사용해 2차 시도한다.
"""

import re
import sqlite3
import logging
from collections import Counter

import sqlglot
from sqlglot import exp

# sqlglot이 MySQL DATEDIFF(date1, date2)를 SQLite로 변환할 때 기본 단위(DAY)를
# 자체 버그로 "unsupported"라고 경고하는데, 실제 변환 결과는 정확하므로 로그만 끈다.
logging.getLogger("sqlglot").setLevel(logging.ERROR)


# =========================================================
# 0. 파싱 유틸 (sqlglot 기반)
# =========================================================

def _extract_create_statement(instruction: str) -> str | None:
    m = re.search(r"(CREATE TABLE.*?;)", instruction, re.S)
    return m.group(1).strip() if m else None


def _extract_insert_statement(instruction: str) -> str | None:
    m = re.search(r"(INSERT INTO.*?;)", instruction, re.S)
    return m.group(1).strip() if m else None


def _extract_query(output: str) -> str | None:
    if not isinstance(output, str) or "쿼리 작성" not in output:
        return None
    sql = output.split("쿼리 작성:", 1)[-1].strip()
    return sql if sql else None


def _parse_create(create_sql: str) -> dict | None:
    """CREATE TABLE 문을 파싱해 테이블명 / 컬럼별 타입·NULL 허용여부 / PK 목록을 반환"""
    try:
        tree = sqlglot.parse_one(create_sql, read="mysql")
    except Exception:
        return None

    table_node = tree.find(exp.Table)
    table_name = table_node.name if table_node else None

    columns = {}
    for col_def in tree.find_all(exp.ColumnDef):
        name = col_def.name
        dtype_node = col_def.kind
        dtype_name = dtype_node.this.name if dtype_node else None  # VARCHAR / DATETIME / INT ...
        length = None
        if dtype_node and dtype_node.expressions:
            try:
                length = int(dtype_node.expressions[0].this.this)
            except Exception:
                length = None

        constraints = col_def.constraints or []
        nullable = True
        for c in constraints:
            if isinstance(c.kind, exp.NotNullColumnConstraint):
                # allow_null=True 이면 NULL 허용(=NOT NULL이 아님), 없으면 NOT NULL
                nullable = bool(c.kind.args.get("allow_null", False))
        columns[name] = {"type": dtype_name, "length": length, "nullable": nullable}

    pk_columns = []
    for pk in tree.find_all(exp.PrimaryKey):
        pk_columns = [e.name for e in pk.expressions]

    return {"table_name": table_name, "columns": columns, "primary_key": pk_columns}


def _parse_insert(insert_sql: str) -> dict | None:
    """INSERT INTO 문을 파싱해 테이블명 / 컬럼 목록 / 각 행의 (kind, value) 값을 반환"""
    try:
        tree = sqlglot.parse_one(insert_sql, read="mysql")
    except Exception:
        return None

    table_node = tree.find(exp.Table)
    table_name = table_node.name if table_node else None

    schema = tree.find(exp.Schema)
    insert_columns = [c.name for c in schema.expressions] if schema else []

    rows = []
    values_expr = tree.find(exp.Values)
    if values_expr:
        for tup in values_expr.expressions:
            row = []
            for v in tup.expressions:
                if isinstance(v, exp.Null):
                    row.append(("NULL", None))
                elif isinstance(v, exp.Boolean):
                    row.append(("BOOL", v.this))
                elif isinstance(v, exp.Neg) and isinstance(v.this, exp.Literal):
                    # 음수 리터럴(-23.5 등)은 Literal이 아니라 Neg(Literal)로 파싱됨
                    inner = v.this
                    kind = "STRING" if inner.is_string else "NUMBER"
                    row.append((kind, f"-{inner.this}"))
                elif isinstance(v, exp.Literal):
                    row.append(("STRING" if v.is_string else "NUMBER", v.this))
                else:
                    row.append(("OTHER", str(v)))
            rows.append(row)

    return {"table_name": table_name, "columns": insert_columns, "rows": rows}


def _get_sql_columns(sql: str) -> set | None:
    """
    SELECT/SQL문에서 '실제 컬럼 참조'만 추출.
    - SELECT절에서 정의된 alias(예: COUNT(*) AS order_count)는 sqlglot이 ColumnDef가 아닌
      Alias 노드로 잡아주므로 자동으로 제외됨.
    - 다만 ORDER BY/GROUP BY 등에서 '그 alias를 다시 참조'하는 경우나, 서브쿼리가 만들어낸
      파생 컬럼(t.total 같은)은 구조적으로 일반 Column과 구분이 안 되기 때문에,
      쿼리 안에서 정의된 모든 alias 이름을 따로 모아서 결과에서 빼준다.
    """
    try:
        tree = sqlglot.parse_one(sql, read="mysql")
    except Exception:
        return None

    referenced = {c.name for c in tree.find_all(exp.Column) if c.name != "*"}
    defined_aliases = {a.alias for a in tree.find_all(exp.Alias) if a.alias}
    return referenced - defined_aliases


_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$")


def _value_matches_type(kind: str, value, col_type: str) -> bool:
    col_type = (col_type or "").upper()
    if col_type.startswith("VARCHAR") or col_type in ("TEXT", "CHAR", "VARCHAR"):
        return kind == "STRING"
    if col_type in ("DATETIME", "DATE", "TIMESTAMP"):
        return kind == "STRING" and bool(_DATETIME_RE.match(str(value)))
    if col_type in ("INT", "INTEGER", "BIGINT", "SMALLINT"):
        return kind == "NUMBER"
    if col_type in ("FLOAT", "DOUBLE", "DECIMAL", "NUMERIC"):
        return kind == "NUMBER"
    if col_type in ("BOOLEAN", "BOOL"):
        return kind in ("BOOL", "NUMBER")
    # 정의 안 된 타입은 통과(룰이 모르는 타입까지 억지로 틀렸다고 하지 않음)
    return True


# =========================================================
# 1. row(개별 항목) 단위 검증
# =========================================================

def _add(report, index, category, rule, ok, detail=""):
    report.append({
        "index": index,
        "category": category,
        "rule": rule,
        "status": "PASS" if ok else "FAIL",
        "detail": detail,
    })


def _validate_format(item, idx, report) -> bool:
    """데이터 형식 검증. 이후 단계를 더 진행해도 되는지(False면 중단) 여부를 반환"""
    is_dict = isinstance(item, dict)
    _add(report, idx, "데이터 형식", "원소가 dict 타입인지", is_dict)
    if not is_dict:
        return False

    keys_ok = all(k in item for k in ("instruction", "input", "output"))
    _add(report, idx, "데이터 형식", "instruction/input/output 키 존재", keys_ok,
         detail=f"keys={list(item.keys())}" if not keys_ok else "")
    if not keys_ok:
        return False

    instr_not_null = item.get("instruction") is not None
    output_not_null = item.get("output") is not None
    _add(report, idx, "데이터 형식", "instruction 값 not null", instr_not_null)
    _add(report, idx, "데이터 형식", "output 값 not null", output_not_null)

    return instr_not_null and output_not_null


def _validate_instruction(item, idx, report) -> dict:
    """
    instruction 값 검증.
    Returns: {'create_info':.., 'insert_info':.., 'sql_columns_in_ddl': set, 'table_name':..}
    이후 output 검증에서 재사용하기 위해 파싱 결과를 같이 반환한다.
    """
    instr = item["instruction"]
    ctx = {"create_info": None, "insert_info": None}

    is_str = isinstance(instr, str)
    _add(report, idx, "instruction 값", "값이 string 타입인지", is_str)
    if not is_str:
        return ctx

    has_q = "입력 텍스트" in instr
    has_ddl = "DDL statements" in instr
    _add(report, idx, "instruction 값", "'입력 텍스트' 존재", has_q)
    _add(report, idx, "instruction 값", "'DDL statements' 존재", has_ddl)

    if has_q and has_ddl:
        order_ok = instr.find("입력 텍스트") < instr.find("DDL statements")
        _add(report, idx, "instruction 값", "'입력 텍스트'가 'DDL statements'보다 앞에 위치", order_ok)

    create_sql = _extract_create_statement(instr)
    insert_sql = _extract_insert_statement(instr)
    create_info = _parse_create(create_sql) if create_sql else None
    ctx["create_info"] = create_info

    if create_sql and create_info is None:
        _add(report, idx, "instruction 값", "CREATE TABLE 문 파싱 가능 여부", False,
             detail="sqlglot 파싱 실패")

    if insert_sql is None:
        # INSERT문이 없는 경우(VALUES 0개 샘플링)는 정상 케이스이므로 별도 FAIL 처리하지 않음
        return ctx

    insert_info = _parse_insert(insert_sql)
    ctx["insert_info"] = insert_info
    if insert_info is None:
        _add(report, idx, "instruction 값", "INSERT 문 파싱 가능 여부", False,
             detail="sqlglot 파싱 실패")
        return ctx
    if create_info is None:
        # CREATE를 못 읽었으면 이후 대조 불가
        return ctx

    # 1) 테이블명 일치
    table_match = create_info["table_name"] == insert_info["table_name"]
    _add(report, idx, "instruction(INSERT)", "CREATE/INSERT 테이블명 일치", table_match,
         detail=f"CREATE={create_info['table_name']}, INSERT={insert_info['table_name']}")

    # 2) 컬럼명 전체 일치 (집합 비교: 누락/추가 모두 검출)
    ddl_cols = set(create_info["columns"].keys())
    insert_cols = set(insert_info["columns"])
    cols_match = ddl_cols == insert_cols
    _add(report, idx, "instruction(INSERT)", "CREATE/INSERT 컬럼명 전체 일치", cols_match,
         detail=f"DDL에만 있음={ddl_cols - insert_cols}, INSERT에만 있음={insert_cols - ddl_cols}"
                if not cols_match else "")

    # 3) 컬럼 개수 vs 각 행의 값 개수 일치
    n_cols = len(insert_info["columns"])
    mismatched_rows = [i for i, row in enumerate(insert_info["rows"]) if len(row) != n_cols]
    _add(report, idx, "instruction(INSERT)", "컬럼 개수와 값 개수 일치", len(mismatched_rows) == 0,
         detail=f"불일치 행 인덱스={mismatched_rows}" if mismatched_rows else "")

    # 4) VALUES 자료형 일치 + 5) NULL 허용 여부
    type_violations = []
    null_violations = []
    for r_i, row in enumerate(insert_info["rows"]):
        for c_i, (kind, val) in enumerate(row):
            if c_i >= n_cols:
                continue
            col_name = insert_info["columns"][c_i]
            col_meta = create_info["columns"].get(col_name)
            if col_meta is None:
                continue  # 컬럼명 불일치는 위에서 이미 잡음
            if kind == "NULL":
                if not col_meta["nullable"]:
                    null_violations.append((r_i, col_name))
                continue
            if not _value_matches_type(kind, val, col_meta["type"]):
                type_violations.append((r_i, col_name, kind, col_meta["type"]))

    _add(report, idx, "instruction(INSERT)", "VALUES 값이 컬럼 데이터형에 맞는지", len(type_violations) == 0,
         detail=f"{type_violations}" if type_violations else "")
    _add(report, idx, "instruction(INSERT)", "VALUES 값이 NULL 허용 여부에 맞는지", len(null_violations) == 0,
         detail=f"{null_violations}" if null_violations else "")

    # 6) PK 중복 여부
    pk_cols = create_info["primary_key"]
    if pk_cols and all(c in insert_info["columns"] for c in pk_cols):
        pk_idx = [insert_info["columns"].index(c) for c in pk_cols]
        pk_values = []
        for row in insert_info["rows"]:
            try:
                pk_values.append(tuple(row[i][1] for i in pk_idx))
            except IndexError:
                continue
        dup = [v for v, cnt in Counter(pk_values).items() if cnt > 1]
        _add(report, idx, "instruction(INSERT)", "PRIMARY KEY 값 중복 여부", len(dup) == 0,
             detail=f"중복 PK={dup}" if dup else "")

    return ctx


def _validate_input(item, idx, report):
    val = item.get("input")
    _add(report, idx, "input 값", "항상 빈 문자열인지", val == "",
         detail=f"실제 값={val!r}" if val != "" else "")


def _validate_output(item, idx, report, create_info, conn_factory=None, llm_sql=None) -> str | None:
    output = item["output"]

    is_str = isinstance(output, str)
    _add(report, idx, "output 값", "값이 string 타입인지", is_str)
    if not is_str:
        return None

    has_marker = "쿼리 작성" in output
    _add(report, idx, "output 값", "'쿼리 작성' 존재", has_marker)

    sql = _extract_query(output)
    if sql is None:
        return None

    # SQL이 참조하는 컬럼이 DDL에 정의된 컬럼인지 (sqlglot으로 실제 Column 노드만 비교, alias 오탐 방지)
    if create_info is not None:
        sql_cols = _get_sql_columns(sql)
        if sql_cols is None:
            _add(report, idx, "output(SQL)", "SQL 파싱 가능 여부", False, detail="sqlglot 파싱 실패")
        else:
            ddl_cols = set(create_info["columns"].keys())
            unknown = sql_cols - ddl_cols
            _add(report, idx, "output(SQL)", "SQL이 참조하는 컬럼이 DDL에 정의되어 있는지",
                 len(unknown) == 0, detail=f"미정의 컬럼={unknown}" if unknown else "")

    # SQL 실제 실행 여부 (row 자체의 CREATE+INSERT 샘플로 임시 DB를 구성해서 실행)
    if conn_factory is not None:
        status, detail = conn_factory(item["instruction"], sql, llm_sql)
        _add(report, idx, "output(SQL)", "SQL 실제 실행 가능 여부", status == "success", detail=detail)

    return sql


# =========================================================
# 2. SQL 실행 검증 (row별 임시 sqlite DB)
# =========================================================

def _build_row_sqlite_conn(instruction: str):
    """instruction에 들어있는 CREATE TABLE(+INSERT) 샘플로 임시 in-memory DB를 구성"""
    create_sql = _extract_create_statement(instruction)
    insert_sql = _extract_insert_statement(instruction)
    if create_sql is None:
        return None

    conn = sqlite3.connect(":memory:")
    try:
        # SQLite 문법으로 변환 (sqlglot transpile, LLM 호출 없이 1차 시도)
        create_sqlite = sqlglot.transpile(create_sql, read="mysql", write="sqlite")[0]
        conn.executescript(create_sqlite)
        if insert_sql:
            insert_sqlite = sqlglot.transpile(insert_sql, read="mysql", write="sqlite")[0]
            conn.executescript(insert_sqlite)
        return conn
    except Exception:
        conn.close()
        return None


def _try_execute_sql(conn, sql: str):
    sql_clean = sql.rstrip(";")
    sql_type = sql_clean.strip().split()[0].upper() if sql_clean.strip() else ""
    cursor = conn.cursor()
    if sql_type == "SELECT":
        cursor.execute(sql_clean)
        cursor.fetchall()
    else:
        cursor.execute(sql_clean)
        conn.rollback()


def make_sql_execution_checker(_convert_to_sqlite=None):
    """
    execute_sql_on_db에서 쓰던 _convert_to_sqlite(LLM 기반 변환)를 그대로 재사용하기 위한 팩토리.
    Args:
        _convert_to_sqlite: 사용자가 이미 정의해둔 함수(없으면 LLM 변환 단계는 건너뜀)
    Returns:
        validate_dataset()의 conn_factory 인자로 넘길 콜러블
    """
    def _checker(instruction: str, sql: str, llm_sql=None):
        conn = _build_row_sqlite_conn(instruction)
        if conn is None:
            return "error", "instruction에서 CREATE TABLE을 읽거나 변환하지 못함"

        # 1차: sqlglot으로 SQLite 방언 변환 후 실행
        try:
            sql_sqlite = sqlglot.transpile(sql, read="mysql", write="sqlite")[0]
            _try_execute_sql(conn, sql_sqlite)
            conn.close()
            return "success", ""
        except Exception as e1:
            first_error = str(e1)

        # 2차: LLM 기반 변환 재시도 (제공된 _convert_to_sqlite 사용, llm_sql 필요)
        if _convert_to_sqlite is not None and llm_sql is not None:
            try:
                sql_llm = _convert_to_sqlite(sql).rstrip(";")
                _try_execute_sql(conn, sql_llm)
                conn.close()
                return "success", f"(LLM 변환 후 성공) 1차 오류={first_error}"
            except Exception as e2:
                conn.close()
                return "error", f"1차 오류={first_error} / LLM 변환 후 오류={e2}"

        conn.close()
        return "error", first_error

    return _checker


# =========================================================
# 3. 데이터셋 전체(중복) 검증
# =========================================================

def _validate_duplicates(data, report):
    instructions = [item.get("instruction") for item in data if isinstance(item, dict)]
    outputs_sql = [_extract_query(item.get("output", "")) for item in data if isinstance(item, dict)]

    def _dup_indices(values):
        counter = Counter(v for v in values if v is not None)
        dup_values = {v for v, c in counter.items() if c > 1}
        return [i for i, v in enumerate(values) if v in dup_values]

    instr_dup_idx = _dup_indices(instructions)
    _add(report, "GLOBAL", "중복 여부", "instruction 중복", len(instr_dup_idx) == 0,
         detail=f"중복 인덱스={instr_dup_idx}" if instr_dup_idx else "")

    sql_dup_idx = _dup_indices(outputs_sql)
    _add(report, "GLOBAL", "중복 여부", "output SQL 중복", len(sql_dup_idx) == 0,
         detail=f"중복 인덱스={sql_dup_idx}" if sql_dup_idx else "")


# =========================================================
# 4. 메인 함수
# =========================================================

def validate_dataset(data: list, llm_sql=None, _convert_to_sqlite=None, check_execution: bool = True) -> list[dict]:
    """
    text-to-SQL 학습 데이터(JSON list)를 rule-based로 검증한다.

    Args:
        data : [{'instruction':.., 'input':.., 'output':..}, ...]
        llm_sql : execute_sql_on_db에서 쓰던 LangChain LLM (SQL 변환용, 없으면 LLM 변환 단계 생략)
        _convert_to_sqlite : 사용자가 정의해둔 LLM 기반 SQLite 변환 함수 (없으면 sqlglot 변환만 사용)
        check_execution : SQL 실제 실행 검증을 수행할지 여부 (False면 건너뜀, 속도↑)

    Returns:
        list[dict] : 각 row(index)별로 어떤 룰을 통과/위반했는지 정리한 리포트.
                     index='GLOBAL'인 항목은 데이터셋 전체 단위(중복) 체크 결과.
    """
    report = []
    conn_factory = make_sql_execution_checker(_convert_to_sqlite) if check_execution else None

    for idx, item in enumerate(data):
        ok = _validate_format(item, idx, report)
        if not ok:
            continue

        ctx = _validate_instruction(item, idx, report)
        _validate_input(item, idx, report)
        _validate_output(item, idx, report, ctx.get("create_info"),
                          conn_factory=conn_factory, llm_sql=llm_sql)

    _validate_duplicates(data, report)
    return report


def summarize_report(report: list[dict]):
    """
    검사한 모든 항목([검사 항목] 단위)을 빠짐없이 나열해서 보여준다.
    - 해당 항목이 모든 row에서 통과했으면 "전체 통과"
    - 위반이 하나라도 있으면 몇 건인지 + index/상세 내용을 출력

    형식:
        [카테고리 - 룰] 전체 통과
        [카테고리 - 룰] 위반 N건
          - index=.. | 상세내용
    """
    grouped = {}
    for r in report:
        key = (r["category"], r["rule"])
        grouped.setdefault(key, []).append(r)

    for (category, rule), entries in grouped.items():
        fails = [e for e in entries if e["status"] == "FAIL"]
        label = f"[{category} - {rule}]"
        if not fails:
            print(f"{label} 전체 통과")
        else:
            print(f"{label} 위반 {len(fails)}건")
            for f in fails:
                detail = f" | {f['detail']}" if f["detail"] else ""
                print(f"  - index={f['index']}{detail}")


def validate_json_file(path: str, llm_sql=None, _convert_to_sqlite=None,
                        check_execution: bool = True, verbose: bool = True) -> list[dict]:
    """
    JSON 파일 경로 하나만 넣으면 로드 -> 전체 룰 검증 -> (verbose면) 요약 출력까지 한 번에 처리.

    Args:
        path : 검증할 JSON 파일 경로 (예: '/mnt/user-data/uploads/xxx.json')
        llm_sql, _convert_to_sqlite : SQL 실행 2차 시도용 (없으면 sqlglot 변환까지만 시도)
        check_execution : SQL 실행 검증 수행 여부
        verbose : True면 요약을 콘솔에 바로 출력

    Returns:
        list[dict] : validate_dataset()과 동일한 형식의 리포트
    """
    import json

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    report = validate_dataset(
        data,
        llm_sql=llm_sql,
        _convert_to_sqlite=_convert_to_sqlite,
        check_execution=check_execution,
    )

    if verbose:
        print(f"파일: {path}")
        print(f"총 {len(data)}건 로드\n")
        summarize_report(report)

    return report


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용법: python validate_dataset.py <json_path>")
        sys.exit(1)

    validate_json_file(sys.argv[1])

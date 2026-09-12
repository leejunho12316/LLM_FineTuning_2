"""Text-to-SQL 의미 동치성 판정용 프롬프트 v2."""

SYSTEM_PROMPT = """당신은 SQL 의미 동치성(semantic equivalence) 판정기다.

당신의 임무는 두 SQL 쿼리가 **주어진 스키마 위의 모든 가능한 데이터에 대해 항상 동일한 결과 집합을 반환하는지**를 판정하는 것이다.

절대 혼동하지 말 것:
- 당신은 문체 채점기가 아니다. 쿼리 A와 얼마나 비슷하게 생겼는지는 판정 대상이 아니다.
- 쿼리 A는 유일한 정답이 아니라 정답의 한 예시다. 동일한 결과를 내는 다른 작성 방식은 모두 동등하게 정답이다.
- 당신은 품질 평가자가 아니다. 가독성, 성능, 인덱스 활용, 스타일 일관성은 판정에 영향을 주지 않는다.
- 감점거리를 찾아낼 의무가 없다. 차이를 발견하지 못했다면 그것이 정상적인 결론이다.

## 무시해야 할 차이 (이 항목들은 절대 불일치 근거가 될 수 없다)

1. 출력 컬럼 별칭 이름 — `COUNT(*) AS cnt`와 `COUNT(*) AS product_count`는 동일하다. 접미사 유무(`min_weight` vs `min_weight_g`)도 동일하다. 별칭이 아예 없어도 동일하다.
2. 테이블 별칭 이름 — `FROM orders o`와 `FROM orders AS ord`는 동일하다.
3. 교환법칙이 성립하는 연산자의 항 순서 — `a*b*c`와 `a*c*b`, `x AND y`와 `y AND x`, `a+b`와 `b+a`는 동일하다. "수학적으로는 같지만 순서가 다르다"는 불일치 근거가 아니다.
4. 동등한 구문 변형 — 서브쿼리 vs JOIN, `IN` vs `EXISTS` vs `INNER JOIN`, `CASE WHEN` vs `IIF`, `BETWEEN a AND b` vs `>= a AND <= b`, CTE vs 인라인 서브쿼리, `!=` vs `<>`, `JOIN` vs `INNER JOIN`.
5. 공백, 줄바꿈, 들여쓰기, 대소문자, 키워드 표기, 주석, 마지막 세미콜론.
6. 결과에 영향 없는 중복 조건 — PK 컬럼에 대한 `IS NOT NULL`, NOT NULL 제약이 걸린 컬럼에 대한 NULL 체크, 항상 참인 조건.
7. SELECT 절의 컬럼 나열 순서. 단, 반환되는 컬럼의 집합 자체는 같아야 한다.

## 반드시 검사해야 할 차이 (하나라도 다르면 NOT_EQUIVALENT)

1. 반환 행 집합 — 필터 조건이 실질적으로 다른가.
2. 반환 컬럼 집합 — 한쪽에만 있는 컬럼이 있는가.
3. 집계 단위 — GROUP BY 키가 다른가. 집계 함수가 다른가 (`COUNT(*)` vs `COUNT(DISTINCT x)`, `AVG` vs `SUM`).
4. 중복 처리 — `DISTINCT` 유무가 결과 행 수를 바꾸는가.
5. JOIN 종류 — `INNER` vs `LEFT` vs `FULL`로 인해 행이 보존/누락되는가.
6. 정렬 — ORDER BY 기준 컬럼 또는 방향(ASC/DESC)이 다른가. 단, 정렬이 결과의 의미에 영향을 주지 않는 경우(집계 결과 1행 등)는 무시한다. `LIMIT`과 함께 쓰인 정렬 기준의 차이는 항상 중요하다.
7. LIMIT / OFFSET 값.
8. NULL 처리 — NULL이 존재할 때 한쪽만 행을 누락시키는가.
9. 타입/값 변환 — `LOWER()`, `TRIM()`, `CAST()`의 유무가 그룹핑이나 비교 결과를 바꿀 수 있는가. 스키마상 그럴 가능성이 없다고 단정할 수 없다면 차이로 본다.

## 반례 원칙 (가장 중요)

NOT_EQUIVALENT로 판정하려면, 두 쿼리가 서로 다른 결과를 내는 구체적인 데이터 상황을 반드시 제시해야 한다.

반례를 만들 수 없다면 그 차이는 실재하지 않는 것이다. 이 경우 EQUIVALENT로 판정하라. "쿼리 A와 다르게 작성되었다", "쿼리 A의 의도와 일치한다고 보기 어렵다" 같은 진술은 반례가 아니며 판정 근거로 인정되지 않는다.

## 판정 레이블

- EQUIVALENT — 모든 데이터에 대해 동일한 결과를 반환한다.
- NOT_EQUIVALENT — 유효한 반례를 제시할 수 있다.
- INVALID — 쿼리 B가 주어진 스키마에서 실행 불가능하다 (문법 오류, 존재하지 않는 테이블/컬럼 참조).
- UNCERTAIN — 동치 여부가 스키마만으로는 결정되지 않고 실제 데이터 분포에 의존한다. 남용하지 말 것. 반례를 구성하려 충분히 시도한 뒤에만 사용한다.

지정된 JSON 스키마에 맞춰 응답한다."""


USER_TEMPLATE = """[스키마]
{ddl}

[자연어 질의]
{prompt}

[쿼리 A - 정답 예시]
{label_sql}

[쿼리 B - 평가 대상]
{resp_sql}

두 쿼리가 위 스키마의 모든 가능한 데이터에 대해 항상 동일한 결과 집합을 반환하는가?"""


# 기존 judge가 실제로 오판했던 케이스를 few-shot으로 사용한다.
FEWSHOT = [
    (
        USER_TEMPLATE.format(
            ddl="CREATE TABLE products (product_id VARCHAR(32) NOT NULL, product_length_cm INT, "
                "product_height_cm INT, product_width_cm INT, PRIMARY KEY (product_id));",
            prompt="부피가 1,000cm³ 미만인 제품의 product_id 50개.",
            label_sql="SELECT product_id FROM products WHERE product_length_cm IS NOT NULL AND "
                      "product_height_cm IS NOT NULL AND product_width_cm IS NOT NULL AND "
                      "(product_length_cm * product_height_cm * product_width_cm) < 1000 "
                      "ORDER BY product_id LIMIT 50",
            resp_sql="SELECT product_id FROM products WHERE product_length_cm IS NOT NULL AND "
                     "product_width_cm IS NOT NULL AND product_height_cm IS NOT NULL AND "
                     "(product_length_cm * product_width_cm * product_height_cm) < 1000 "
                     "ORDER BY product_id LIMIT 50",
        ),
        {
            "verdict": "EQUIVALENT",
            "counterexample": None,
            "difference_type": "none",
            "reason": "곱셈은 교환법칙이 성립하므로 세 컬럼의 곱 순서 차이는 결과에 영향을 주지 않는다. "
                      "WHERE 조건, 정렬, LIMIT이 모두 동일하다.",
        },
    ),
    (
        USER_TEMPLATE.format(
            ddl="CREATE TABLE order_payments (order_id VARCHAR(32) NOT NULL, payment_sequential INT, "
                "payment_installments INT, payment_value FLOAT);",
            prompt="할부 횟수가 1인 결제의 건수와 총 금액.",
            label_sql="SELECT COUNT(*) AS payment_count, SUM(payment_value) AS total_payment_value "
                      "FROM order_payments WHERE payment_installments = 1",
            resp_sql="SELECT COUNT(*) AS single_installment_count, SUM(payment_value) AS "
                     "single_installment_total FROM order_payments WHERE payment_installments = 1",
        ),
        {
            "verdict": "EQUIVALENT",
            "counterexample": None,
            "difference_type": "none",
            "reason": "출력 컬럼 별칭 이름만 다르고 집계 함수, 대상 컬럼, 필터 조건이 모두 동일하다. "
                      "별칭은 판정 대상이 아니다.",
        },
    ),
    (
        USER_TEMPLATE.format(
            ddl="CREATE TABLE sellers (seller_id VARCHAR(32) NOT NULL, seller_city VARCHAR(40) NOT NULL, "
                "seller_state VARCHAR(2) NOT NULL, PRIMARY KEY (seller_id));",
            prompt="도시명 첫 글자별 판매자 수 상위 10개.",
            label_sql="SELECT LOWER(SUBSTRING(seller_city,1,1)) AS initial, COUNT(*) AS seller_count "
                      "FROM sellers GROUP BY LOWER(SUBSTRING(seller_city,1,1)) "
                      "ORDER BY seller_count DESC, initial ASC LIMIT 10",
            resp_sql="SELECT SUBSTRING(seller_city,1,1) AS city_first_char, COUNT(*) AS seller_count "
                     "FROM sellers GROUP BY SUBSTRING(seller_city,1,1) "
                     "ORDER BY seller_count DESC, city_first_char LIMIT 10",
        ),
        {
            "verdict": "NOT_EQUIVALENT",
            "counterexample": "sellers에 seller_city='Sao Paulo'인 행 3개와 'sao paulo'인 행 2개가 있으면, "
                              "A는 대소문자를 정규화해 하나의 그룹(5건)으로 세지만 B는 'S'(3건)와 's'(2건)를 "
                              "별도 그룹으로 센다. 상위 10개의 구성과 순위가 달라진다.",
            "difference_type": "value_transform",
            "reason": "대소문자 정규화 유무가 GROUP BY 키를 바꾸므로 집계 결과가 달라질 수 있다.",
        },
    ),
    (
        USER_TEMPLATE.format(
            ddl="CREATE TABLE orders (order_id VARCHAR(32) NOT NULL, order_status VARCHAR(20));\n"
                "CREATE TABLE order_items (order_id VARCHAR(32), order_item_id INT, "
                "product_id VARCHAR(32), seller_id VARCHAR(32));",
            prompt="주문 상태별 평균 판매자 수와 평균 상품 수.",
            label_sql="SELECT o.order_status, AVG(t.distinct_sellers), AVG(t.distinct_products) "
                      "FROM orders o JOIN (SELECT order_id, COUNT(DISTINCT seller_id) AS distinct_sellers, "
                      "COUNT(DISTINCT product_id) AS distinct_products FROM order_items GROUP BY order_id) t "
                      "ON t.order_id = o.order_id GROUP BY o.order_status",
            resp_sql="SELECT o.order_status, COUNT(*) AS order_count, AVG(i.seller_count), AVG(i.item_count) "
                     "FROM orders o JOIN (SELECT order_id, COUNT(DISTINCT seller_id) AS seller_count, "
                     "COUNT(*) AS item_count FROM order_items GROUP BY order_id) i "
                     "ON i.order_id = o.order_id GROUP BY o.order_status",
        ),
        {
            "verdict": "NOT_EQUIVALENT",
            "counterexample": "한 주문에 동일한 product_id가 2줄로 들어있으면 A의 distinct_products는 1, "
                              "B의 item_count는 2가 된다. 또한 B는 order_count 컬럼을 추가로 반환한다.",
            "difference_type": "aggregation",
            "reason": "COUNT(DISTINCT product_id)와 COUNT(*)는 중복 품목이 있을 때 값이 다르고, "
                      "반환 컬럼 집합도 일치하지 않는다.",
        },
    ),
]


VERDICTS = ["EQUIVALENT", "NOT_EQUIVALENT", "INVALID", "UNCERTAIN"]
DIFF_TYPES = ["row_set", "column_set", "aggregation", "distinct", "join_type", "ordering",
              "limit", "null_handling", "value_transform", "syntax_error", "none"]

JSON_SCHEMA = {
    "name": "sql_equivalence_verdict",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "counterexample", "difference_type", "reason"],
        "properties": {
            "verdict": {"type": "string", "enum": VERDICTS},
            "counterexample": {
                "type": ["string", "null"],
                "description": "NOT_EQUIVALENT인 경우 두 쿼리가 다른 결과를 내는 구체적 데이터 상황. 그 외에는 null.",
            },
            "difference_type": {"type": "string", "enum": DIFF_TYPES},
            "reason": {"type": "string", "description": "판정 근거 한두 문장."},
        },
    },
}


def build_messages(ddl, prompt, label_sql, resp_sql, use_fewshot=True):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if use_fewshot:
        import json
        for user_msg, answer in FEWSHOT:
            msgs.append({"role": "user", "content": user_msg})
            msgs.append({"role": "assistant",
                         "content": json.dumps(answer, ensure_ascii=False)})
    msgs.append({"role": "user", "content": USER_TEMPLATE.format(
        ddl=ddl, prompt=prompt, label_sql=label_sql, resp_sql=resp_sql)})
    return msgs

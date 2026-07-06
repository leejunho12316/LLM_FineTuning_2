# LLM_FineTuning_2

# text-to-sql 파인튜닝 계획 모음

진행

1. (완료) 특정 기관, 정부의 특정 부처 특정 짓고 그곳의 실제 데이터, 스키마, 진짜 질문 예시 확보 (train/test 분리)
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce : ⭐Olist 브라질 이커머스 데이터셋
    
2. (완료) gretelai로 base 데이터 생성 (코드)
https://huggingface.co/datasets/gretelai/synthetic_text_to_sql : base 데이터셋
v- POC : gpt-4o-mini, 100개로 먼저 POC 진행. (text_to_sql_data.json)
v- 실전 : gpt-5.5, 5000개.

3. (완료) Olist 기반 데이터 생성 - 단일
v- POC : GPT-5 DB 1개 * 9개 (Olist_orders_text_to_sql_data.json)
v- 실전 : GPT-5 DB 8개 * 100개씩 
-> 6/20) 단일 데이터 검증 오류난거 처리

4. (완료) Olist 기반 데이터 생성 - 복합
v - POC : GPT-5 DB 연결고리 1개 * 3개 (Olist_orders_n_order_items_text_to_sql_data.json)
v - 실전 : GPT-5 DB 연결고리 8개 * 30개씩 

5. (완료) Olist 데이터셋 검증
v - POC : 건뛰
v- 실전 : rule-based + LLM-as-a-Judge

6. gretelai와 Olist 데이터 섞어 Fine-Tuning
v- POC : A100 & 모델은 아무거나.
- 실전 : 비싼 GPU

no data                 | 3B, 7B, 10<=B
base data               | 3B, 7B, 10<=B
ㅇ base data + olist data  | 3B, 7B, 10<=B

test dataset으로 테스트 결과 비교


7. (완료) POC 발견 TroubleShooting
(완료)- 이미 만들어져 있는 text-to-sql용 데이터 5000행이 있었음. 근데 다 instruction이 입력 텍스트, DDL statements 순으로 되어 있음. Olist 데이터 생성할 때 바꿔주어야 할 듯.

(완료) - query 정교화
ㅇ 질문 text-to-sql Base 데이터의 query와 내가 생성한 Olist 데이터의 query 형태의 차이점 파악하기.
ㅇ Base데이터에 내 데이터 생성 프롬프트에서 지시한 것처럼 완전 구체적인 값을 사용한 질문이 있는지.
ㅇ 사람이 진짜 이렇게 질문을 할 것 같은지.
-> base data 의질문을 예시로 넣어주며 보완

(완료) - 질문 말투 다양화
1. column 이름 직접언급/간접언급
ex) 각 country_of_origin별 모든 statellites의 최대 거리는 얼마인가요? -> 각 국가별로 지구 표면으로부터 모든 위성의 최대 거리는 얼마인가요?
ex) country가 Africa인 모든 org_name 값과 그들이 진행한 num_projects 수를 나열하세요 -> 아프리카에서 활동하는 모든 식량 정의 단체와 그들이 진행한 프로젝트 수를 나열하세요.
2. 명사구 질문.
ex) 마을 변호사는 몇 명이었는가? -> 마을변호사 인원 수
ex) 각 고객별 첫 구매 일시를 알고 싶습니다. 고객 ID와 첫 구매 타임스탬프를 반환해 주세요. -> 각 고객별 첫 구매 일시에 대한 고객 ID와 첫 구매 타임스탬프.
ex) 2018년 2분기(Q2)에 구매된 주문들의 구매 시각부터 배송사 인계까지 평균 며칠이 걸렸는지 알려주세요 -> 2018년 2분기 구매 시각부터 배송사 인계까지 평균일.
4. 끝 말투 변경 (~요? ~까? ~임? ~나?)
ex)태평양 해양의 연간 평균 해수면 온도는 얼마인가요?
-> 태평양 해양의 연간 평균 해수면 온도는 얼마입니까?
-> 태평양 해양의 연간 평균 해수면 온도는 얼마임?
-> 태평양 해양의 연간 평균 해수면 온도는 얼마이나?

영어로 된 칼럼명을 한글로 말해도 알아듣도록 데이터가 만들어져있는지. (데이터의 query가 칼럼명을 있는 그대로 영어로 말하면 FT 후 한글로 질문하면 성능 저하)
-> 위 규칙을 적용해 LLM으로 말투 다양화

(완료) - DDL문
데이터 생성시에는 필요없지만 최종 데이터 생성 시 DDL문에는 INSERT INTO VALUES 까지 있어야 함.
VALUES 개수는 일반화를 막기 위해 0~5개까지 계속 바뀜. 이걸 수동으로 해주긴 좀 그럼.

CREATE TABLE salesperson (salesperson_id INT, name TEXT, region TEXT); 
INSERT INTO salesperson (salesperson_id, name, region) 
VALUES (1, 'John Doe', 'North'), (2, 'Jane Smith', 'South');
-> INSERT문 만드는 함수 새로 작성해 basedata형식으로 전환하는 함수에 추가.

- 복합 DB 데이터
DDL 문에 -- 하고 각 칼럼별 설명 써있음. 복합 DB 데이터에만 되어있는데 수정해야할 듯.
복합 데이턴데 둘 다 쓰는 JOIN같은 SQL문이 아니라 그냥 단일 DB SQL문인 경우가 있음.

7. 평가
SQL문이 정확히 같은지 여부가 아니라 SQL을 실제 DB에 실행 시 돌아온 값이 같은지 여부로 판단하기. SQL문을 쓰는 방식은 아주 다양하기 때문.
exact match 문자열 비교 X -> execution accracy 실행 기반 평가 O


----------

데이터 생성시 문제

1. 도메인 지식
데이터와 도메인에 대한 어느 정도의 지식이 있어야 가능한 질문이 필요함
-> 칼럼 별 unique 값 중 랜덤 n개 추가.
2. 질문 복잡성
실제 사람이 한 것 같은 질문을 만들도록 하고 싶었음. 하지만 특정 SELECT, GROUP BY, COUNT, JOIN 등 어떠한 SQL문을 쓰라고 직접적으로 명시하면 거기에 LLM이 몰두해 대답이 한정적이게 됨. 나노단위 통제보다 유연하게 만들도록 예시를 추가함 추가함.
-> base Text-to-SQL 데이터 중 랜덤 n개에서 질문만 추출해 추가.

README 추가할 내용
- 왜 일반 Llama Instruction이 아닌 allganize를 base model로 사용했는지도 적기. (한국어 성능 더 좋음)


---

# 개요



# Dataset

<img src="https://camo.githubusercontent.com/e70f2a6a8c8f5bf0f4211dd32a0b5311c7464b65098006e654986f6738bfe034/68747470733a2f2f68756767696e67666163652e636f2f64617461736574732f68756767696e67666163652f646f63756d656e746174696f6e2d696d616765732f7261772f6d61696e2f68756767696e67666163655f6875622e737667">

자체제작 Olist Dataset : https://huggingface.co/datasets/leejunho12316/Olist_text_to_sql_FineTuning_dataset/tree/main

Base Fine-Tuning Dataset : https://raw.githubusercontent.com/leejunho12316/LLaMA-Factory/main/data/text_to_sql_data.json

# FineTuned Models

Llama-3.2-1B-Instruct : https://huggingface.co/leejunho12316/Llama-3.2-1B-Instruct-text-to-sql-FT-olist <br>
Llama-3.2-3B-Instruct : https://huggingface.co/leejunho12316/Llama-3.2-3B-Instruct-text-to-sql-FT-olist <br>
Llama-3.1-8B-Instruct : https://huggingface.co/leejunho12316/Llama-3.1-8B-Instruct-text-to-sql-FT-olist-config-edit <br>
allganize-Llama-3-Alpha-Ko-8B-Instruct : https://huggingface.co/leejunho12316/allganize-Llama-3-Alpha-Ko-8B-Instruct-text-to-sql-FT-olist <br>

# 데이터 생성

## 데이터 생성 프롬프트
도메인 지식
1. 데이터 도메인에 대한 지식을 갖추도록 Olist Kaggle 사이트 내 README 데이터 집어넣어 각 칼럼의 역할과 쓰임에 대한 정보를 제공.
2. 컬럼 별 unique한 값 예시 3개씩 추가해줌으로써 정확히 어떤 데이터가 DB에 추가되어 있는지 더 명확하게 알도록 정보를 제공.
3. base dataset의 질문을 랜덤으로 추출해 예시를 제공함으로써 사람이 직접 할 법한 질문을 생성하도록 유도.

```
프롬프트 예시 하나 추가
```

## JOIN 데이터
DB 두개를 사용하는 query-SQL문을 만들기 위한 나의 사투 적기


## 질문 형태 다양화
일반화를 학습하지 않고 사용자가 다양한 말투로 질문을 할 경우 성능을 높이기 위해 종결어미, 말투 등 다방면으로 변경.

1. 명사구 형태

완전한 문장으로 끝나지 않고 명사구 형태로 끝나는 질문. <br>
예) "마을 변호사는 몇 명이었는가?" -> "마을변호사 인원 수"<br>
예) "각 고객별 첫 구매 일시를 알고 싶습니다. 고객 ID와 첫 구매 타임스탬프를 반환해 주세요."
    -> "각 고객별 첫 구매 일시에 대한 고객 ID와 첫 구매 타임스탬프."<br>
예) "2018년 2분기(Q2)에 구매된 주문들의 구매 시각부터 배송사 인계까지 평균 며칠이 걸렸는지 알려주세요"
    -> "2018년 2분기 구매 시각부터 배송사 인계까지 평균일."<br>

2. 문장 종결 어미 변경

"~요?", "~까?", "~임?", "~나?", "~습니까?", "~나요?", "~가요?", "~니?", "~냐?" 등 다양한 물음에 적응 할 수 있도록 종결어미 다양화.<br>
예) 결제 수단별로 결제 승인까지 평균 몇 시간이 걸리는가요?
    -> 결제 수단별로 결제 승인까지 평균 몇 시간이 걸리나?<br>
예)  RS 주에서 고객 수가 가장 많은 우편번호 접두어 상위 5개와 각 고객 수를 보여주세요
    ->  RS 주에서 고객 수가 가장 많은 우편번호 접두어 상위 5개와 각 고객 수를 보여주시겠습니까?<br>
예) 고객이 단 1명만 있는 도시와 주 목록을 도시명 오름차순으로 보여주세요
    -> 고객이 단 1명만 있는 도시와 주 목록을 도시명 오름차순으로 보여줄 수 있으심?<br>

3. 컬럼명 직접/간접 언급

LLM에게 질문 시 영문 칼럼명을 직접 작성할 수 있지만 한국어로 질문할 수도 있음. 간접 언급시에도 올바르게 작동하도록 질의 변형.<br>
예) "각 country_of_origin별 모든 satellites의 최대 거리는 얼마인가요?"
    -> "각 국가별로 지구 표면으로부터 모든 위성의 최대 거리는 얼마인가요?"<br>
예) "country가 Africa인 모든 org_name 값과 그들이 진행한 num_projects 수를 나열하세요"
    -> "아프리카에서 활동하는 모든 식량 정의 단체와 그들이 진행한 프로젝트 수를 나열하세요."<br>


## DDL 선언문 Values 개수 다영화
DDL 선언문 뒤 INSERT INTO ~ VALUES ~ 문의 개수를 0개에서 5개 사이로 랜덤하게 추가. 입력되는 Value 개수가 적든 많든 올바르게 동작하도록 하기 위함.





# 데이터 검증 결과

## Rule-Based 검증 내용
```
# 데이터 형식
1. 모든 list의 원소가 dictionary type인지
2. instruction, input, output 키 존재여부
3. instruction과 output의 값 null 여부

# instruction 값
1. 값이 string 형인지 확인
2. 값에 '입력 텍스트', 'DDL statements' 존재여부
3. '입력 텍스트'가 항상 'DDL statements'보다 앞에 오는지

-> DDL statements에 INSERT문이 있다면
1. CREATE문에 적힌 테이블명과 INSERT 문에 쓰인 테이블명이 일치하는지
2. CREATE문에 적힌 칼럼명과 INSERT 문에 쓰인 칼럼명이 전체 일치하는지
3. INSERT문에 쓰인 칼럼 개수와 값의 개수가 일치하는지.
4. VALUES 값이 칼럼 데이터형에 맞는 올바른 자료형인지
5. VALUES 값이 칼럼 NULL 허용 여부에 맞는지.
6. 전체 INSERT을 봤을 때 PK의 중복 여부

# input 값
1. 항상 빈 문자열인지 체크

# output 값
1. 값이 string 형인지 확인
2. '쿼리 작성' 존재여부
SQL 확인
1. SQL 실제 실행 되는지 여부
2. SQL이 참조하는 컬럼이 DDL statements에 정의된 칼럼인지 여부

# 중복 여부
1. 전체 데이터에서 instruction이 중복되는 것이 있는지 확인
2. 전체 데이터에서 output의 쿼리문이 중복되는 것이 있는지 확인
```

## 검증 대상
- 단일 DB 사용 SQL 데이터 총 800건

Olist_geolocation_text_to_sql_data.json (100건) <br>
Olist_order_reviews_text_to_sql_data.json (100건) <br>
Olist_customers_text_to_sql_data.json (100건) <br>
Olist_order_items_text_to_sql_data.json (100건) <br>
Olist_order_payments_text_to_sql_data.json (100건) <br>
Olist_orders_text_to_sql_data.json (100건) <br>
Olist_products_text_to_sql_data.json (100건) <br>
Olist_sellers_text_to_sql_data.json (100건) <br>
- 복합 DB 사용 SQL 데이터 총 800건

Olist_customers_and_geolocation_text_to_sql_data.json (100건)<br>
Olist_order_items_and_products_text_to_sql_data.json (100건)<br>
Olist_order_items_and_sellers_text_to_sql_data.json (100건)<br>
Olist_orders_and_customers_text_to_sql_data.json (100건)<br>
Olist_orders_and_order_items_text_to_sql_data.json (100건)<br>
Olist_orders_and_order_payments_text_to_sql_data.json (100건)<br>
Olist_orders_and_order_reviews_text_to_sql_data.json (100건)<br>
Olist_sellers_and_geolocation_text_to_sql_data.json (100건)<br>

## 검증 결과

- 단일 DB 사용 SQL 데이터

Olist_order_reviews_text_to_sql_data.json [output(SQL) - SQL 실제 실행 가능 여부] 위반 2건
  - index=75 | 1차 오류=no such function: SUBSTRING_INDEX / LLM 변환 후 오류=near "ORDER": syntax error
  - index=79 | 1차 오류=no such function: CHAR_LENGTH / LLM 변환 후 오류=near "(": syntax error

Olist_geolocation_text_to_sql_data.json [output(SQL) - SQL 실제 실행 가능 여부] 위반 3건
  - index=57 | 1차 오류=no such function: STDDEV_POP / LLM 변환 후 오류=no such column: avg_table.geolocation_state
  - index=83 | 1차 오류=no such function: STDDEV_SAMP / LLM 변환 후 오류=no such column: avg_lng
  - index=96 | 1차 오류=no such function: STDDEV_SAMP / LLM 변환 후 오류=misuse of aggregate function avg()

총 5건 삭제. 795건 데이터 확보.

- 다중 DB 사용 SQL 데이터

Olist_customers_and_geolocation_text_to_sql_data.json [output(SQL) - SQL이 참조하는 컬럼이 DDL에 정의되어 있는지] 위반 1건
  - index=92 | 미정의 컬럼={'gEolocation_lat'}
Olist_customers_and_geolocation_text_to_sql_data.json [output(SQL) - SQL 실제 실행 가능 여부] 위반 2건
  - index=58 | 1차 오류=no such function: STDDEV_POP / LLM 변환 후 오류=ambiguous column name: geolocation_zip_code_prefix
  - index=88 | 1차 오류=no such function: STDDEV_SAMP / LLM 변환 후 오류=misuse of aggregate: MIN()

총 3건 삭제. 797건 데이터 확보.



# 파인 튜닝 결과

## Trouble Shooting
1. 8B 형식 미준수
8B-Instruct를 1B, 3B FT할때와 같은 Config로 FT 진행.
1B와 3B의 경우에 비해 Response에 '쿼리 작성:'으로 시작하는 걸 충분히 학습하지 못함.
큰 모델이라 사전 학습으로 이미 가지고 있는 지식을 바꾸기에 학습이 충분하지 못했음.

```
=== 평가 요약 ===
전체:                  477개
Response 실행 성공:     205개
Label 실행 성공:        473개
실행 결과 일치 (정답):   56개 (11.7%)
```

해결 방법
- r, lora_alpha, target_modules 늘리기
peft_config = LoraConfig(
    r=32,           # 16 -> 32
    lora_alpha=64,  # 32 -> 64 (보통 alpha = 2 × r)
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],  # MLP도 포함
)
- epochs 늘리기
args = SFTConfig(
    num_train_epochs=5,   #3 -> 5
    ...
)

2. 평가 성능 저조
fine tuning된 모델들이 생성한 SQL문이 실행이 안되는 경우가 너무 많음.
LLM-as-a-Judge로 query와 실행결과 퀄리티를 평가했는데 점수가 너무 낮음. 
FineTuning된 모델의 SQL을 실행할 때 DB 방언때문에 실행이 안되면 sqlite 형식으로 변환하는데, 이 때 사용한 gpt-4o-mini라 오류가 많은 것 같음.
-> gpt-5.4로 테스트셋 다시만들기. (xxx.csv -> xxx_with_exec과정만 다시 하면 됨.)

테스트 데이터셋에 DB 실행결과 저장 시 INSERT, DELETE, UPDATE 같은 SQL문이 적용되어서 완전히 같은 SQL을 실행해도 다른 실행결과가 저장됨. 
-> 예외처리 진행.



# 평가

## 평가1 - response_status

테스트 데이터셋의 query를 입력하고 리턴받은 SQL문을 DB에 실행했을 때 response_status 비율.
```
response_status 종류
1. success/success(converted) : 성공 / DB마다 다른 SQL문의 형식을 sqlite 형식으로 변환해서 성공
2. error : SQL too long (** chars) : 비정상적으로 긴 SQL
3. error: Execution failed on sql <SQL문> : SQL문 실행 오류
```

![test1_response_status_ratio.png](6.%20%ED%8F%89%EA%B0%80%20%EB%8D%B0%EC%9D%B4%ED%84%B0/test1_response_status_ratio.png)


## 평가2 - tabels_match

테스트 데이터셋의 query를 입력하고 리턴받은 SQL문이 사용한 table명 정확도

```
카테고리:
1. exact_match:  완전히 같음
2. subset:       response ⊂ label (부족)
3. superset:     response ⊃ label (초과)
4. overlap:      일부 겹침
5. no_match:     겹치는 테이블 없음
6. empty:        response 또는 label이 비어있음
```

![test2_tables_match_ratio.png](6.%20%ED%8F%89%EA%B0%80%20%EB%8D%B0%EC%9D%B4%ED%84%B0/test2_tables_match_ratio.png)


## 평가3 - LLM-as-a-Judge - response 품질

테스트 데이터셋을 실행한 response와 prompt, DDL문, label을 비교해 생성된 SQL문의 퀄리티를 평가.

LLM-as-a-Judge 프롬프트 전문
```
SYSTEM_PROMPT = """
#역할
당신은 Text-to-SQL FineTuning 평가자입니다.
입력된 정보들을 보고 LLM이 올바르게 Fine Tuning 되었는지 평가해주세요.

prompt는 입력된 프롬프트, ddl_statement는 사용된 DB의 DDL문과 예시 값입니다.
response는 Fine-Tuning된 모델의 응답, label은 모범 정답입니다.

#평가 기준
1. response가 prompt의 요구사항을 충족하는지
2. response가 label과 동일한 의도/결과를 제공하는지
3. ddl statement를 보았을 때 response가 존재하는 컬럼/테이블을 참조하는지
4. response의 SQL 형식/문법이 올바른지
5. response가 prompt에서 요구하는 조건을 충족하는지 (LIMIT, ORDER BY, DISTINCT 등)

#출력 형식
평가 기준 별 만족 여부와 그 이유를 적고 만족한 평가 기준 개수로 총점을 매겨주세요.총점은 무조건 정수 하나로만 대답하세요
예시)
[평가]
1 - 만족. 이유.
2 - 불만족. 이유.
3 - 만족. 이유.
...
[총점]
4
"""

HUMAN_PROMPT = """
prompt : {prompt}
ddl_statement : {ddl_statement}
response : {response}
label : {label}
"""
```

Llama-3.2-1B-Instruct 평가 결과 예시


| ID | 프롬프트 | DDL 스키마 | 생성된 쿼리 | 정답 쿼리 | 상세 평가 | 점수 |
| --- | --- | --- | --- | --- | --- | --- |
| **13** | 주별 고객 수를 많은 순서로 보여줄 수 있나? | `CREATE TABLE customers (customer_id VARCHAR(32) NOT NULL, ...)` | `SELECT customer_state, COUNT(*) AS customer_count FROM customers GROUP BY ...` | `SELECT customer_state, COUNT(*) AS customer_count FROM customers GROUP BY ...` | `[평가] 1 - 만족. 주별 고객 수를 많은 순서로 정렬해 보여주고 있습니다. ... [총점] 5` | 5 |
| **14** | 사진 수가 0장이거나 사진 수 정보가 없는 제품 수는 몇 개인가요? | `CREATE TABLE products (product_id VARCHAR(32) NOT NULL, ...); INSERT INTO ...` | `SELECT COUNT(*) AS cnt FROM products WHERE product_photos_qty IS NULL OR ...` | `SELECT COUNT(*) AS product_count FROM products WHERE product_photos_qty IS NULL OR ...` | `[평가] 1 - 만족. 이유: product_photos_qty가 NULL이거나 0인 제품의 개수를... [총점] 5` | 5 |
| **15** | 위치 데이터에서 주 코드가 'SP'인 지역에 해당하는 우편번호가 최소 3개 이상 사용되는 고객 도시와... | `CREATE TABLE customers (...); INSERT INTO ...; CREATE TABLE geolocation (...); ...` | `SELECT c.customer_city, c.customer_state, COUNT(DISTINCT c.customer_zip_code_prefix) ...` | `WITH sp_zips AS ( SELECT DISTINCT geolocation_zip_code_prefix AS zip ... ) ...` | `[평가] 1 - 불만족. 이유: prompt는 “해당 우편번호 개수와 고객 수”를 각 도시별로... [총점] 2` | 2 |
|...|...|...|...|...|...|...|

점수 표 시각화
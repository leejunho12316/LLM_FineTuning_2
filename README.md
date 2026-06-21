# LLM_FineTuning_2

# text-to-sql 파인튜닝

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
- 실전 : GPT-5 DB 연결고리 8개 * 30개씩 

5. (완료) Olist 데이터셋 검증
v - POC : 건뛰
- 실전 : rule-based + LLM-as-a-Judge

6. (완료)gretelai와 Olist 데이터 섞어 Fine-Tuning
v- POC : A100 & 모델은 아무거나.
- 실전 : 비싼 GPU

7. POC 발견 TroubleShooting
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

DDL statements에 INSERT문이 있다면
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
- 단일 DB SQL 데이터 총 800건

Olist_geolocation_text_to_sql_data.json (100건) <br>
Olist_order_reviews_text_to_sql_data.json (100건) <br>
Olist_customers_text_to_sql_data.json (100건) <br>
Olist_order_items_text_to_sql_data.json (100건) <br>
Olist_order_payments_text_to_sql_data.json (100건) <br>
Olist_orders_text_to_sql_data.json (100건) <br>
Olist_products_text_to_sql_data.json (100건) <br>
Olist_sellers_text_to_sql_data.json (100건) <br>


## 검증 결과

[output(SQL) - SQL 실제 실행 가능 여부] 

Olist_order_reviews_text_to_sql_data.json 위반 2건
  - index=75 | 1차 오류=no such function: SUBSTRING_INDEX / LLM 변환 후 오류=near "ORDER": syntax error
  - index=79 | 1차 오류=no such function: CHAR_LENGTH / LLM 변환 후 오류=near "(": syntax error

Olist_geolocation_text_to_sql_data.json
  - index=57 | 1차 오류=no such function: STDDEV_POP / LLM 변환 후 오류=no such column: avg_table.geolocation_state
  - index=83 | 1차 오류=no such function: STDDEV_SAMP / LLM 변환 후 오류=no such column: avg_lng
  - index=96 | 1차 오류=no such function: STDDEV_SAMP / LLM 변환 후 오류=misuse of aggregate function avg()

총 5건 삭제. 795건 데이터 확보.
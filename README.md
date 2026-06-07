# LLM_FineTuning_2

# text-to-sql 파인튜닝

진행

1. (완료) 특정 기관, 정부의 특정 부처 특정 짓고 그곳의 실제 데이터, 스키마, 진짜 질문 예시 확보 (train/test 분리)
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce : ⭐Olist 브라질 이커머스 데이터셋
    
2. (완료) gretelai로 base 데이터 생성 (코드)
https://huggingface.co/datasets/gretelai/synthetic_text_to_sql : base 데이터셋
v- POC : gpt-4o-mini, 100개로 먼저 POC 진행. (text_to_sql_data.json)
- 실전 : gpt-5.5, 5000개.

3. (완료) Olist 기반 데이터 생성 - 단일
v- POC : GPT-5 DB 1개 * 9개 (Olist_orders_text_to_sql_data.json)
- 실전 : GPT-5 DB 8개 * 30개씩 

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

- query 정교화
질문 text-to-sql Base 데이터의 query와 내가 생성한 Olist 데이터의 query 형태의 차이점 파악하기.
Base데이터에 내 데이터 생성 프롬프트에서 지시한 것처럼 완전 구체적인 값을 사용한 질문이 있는지.
사람이 진짜 이렇게 질문을 할 것 같은지.
영어로 된 칼럼명을 한글로 말해도 알아듣도록 데이터가 만들어져있는지. (데이터의 query가 칼럼명을 있는 그대로 영어로 말하면 FT 후 한글로 질문하면 성능 저하)

- 질문 말투 다양화
명사구 질문. (마을 변호사는 몇 명이었는가? -> 마을변호사 인원 수)
답답적인 질문.
끝 말투 변경 (~요? ~까? ~임? ~나?)

- DDL문
데이터 생성시에는 필요없지만 최종 데이터 생성 시 DDL문에는 INSERT INTO VALUES 까지 있어야 함.
VALUES 개수는 일반화를 막기 위해 0~5개까지 계속 바뀜. 이걸 수동으로 해주긴 좀 그럼.

CREATE TABLE salesperson (salesperson_id INT, name TEXT, region TEXT); 
INSERT INTO salesperson (salesperson_id, name, region) 
VALUES (1, 'John Doe', 'North'), (2, 'Jane Smith', 'South');


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
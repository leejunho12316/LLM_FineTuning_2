# LLM_FineTuning_2

# text-to-sql 파인튜닝

진행

v 1. 특정 기관, 정부의 특정 부처 특정 짓고 그곳의 실제 데이터, 스키마, 진짜 질문 예시 확보 (train/test 분리)
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce : ⭐Olist 브라질 이커머스 데이터셋
    
v2. gretelai로 base 데이터 생성 (코드)
https://huggingface.co/datasets/gretelai/synthetic_text_to_sql : base 데이터셋
v- gpt-4o-mini, 100개로 먼저 POC 진행.
- 이후 괜찮으면 gpt-5.5, 5000개.

3. 타겟 데이터 기반 데이터 생성 -> 데이터셋 검증
4. gretelai와 타겟 스키마 기반 합성 데이터 섞어 Fine-Tuning

평기 : SQL문이 정확히 같은지 여부가 아니라 SQL을 실제 DB에 실행 시 돌아온 값이 같은지 여부로 판단하기. SQL문을 쓰는 방식은 아주 다양하기 때문.
exact match 문자열 비교 -> execution accracy 실행 기반 평가
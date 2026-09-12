## 사용법
1. 사용 환경설정/준비
```
pip install -r requirements.txt
.env에 OPENAI_API_KEY 작성
```

2. 실행
평가 - 결과 정리 - 시각화
```
py run_judge.py --input-dir ./data --output-dir ./results
py make_results_json.py --results-dir ./results --output ./results/results.json
py visualize_results.py --input results/results.json --output results/model_accuracy.png
```

3. 추가 코드
API 안 쓰고 "어떤 파일이 어떤 이름으로 나갈지"만 보여주는 확인용.
```
py run_judge.py --input-dir ./data --dry-run
```

# 평가3. LLM-as-a-Judge TroubleShooting

의미적 동치가 아니라 response의 label과의 표면적 유사도를 채점하고 있음.
별칭을 감점 사유로 언급, 24건이 컬럼명 차이를 언급

예시)

- index 1: judge가 직접 "수학적으로는 동일합니다"라고 써놓고도 length*width*height vs length*height*width 항 순서가 다르다며 1, 2번 항목 모두 불만족 처리
- index 57; SQL이 완전히 같고 별칭만 single_installment_count vs payment_count. 이걸로 2개 항목 감점
- index 208: 별칭에 _g, _cm 접미사가 없다는 이유로 3개 항목 감점
- index 180: 쿼리 작성: 프리픽스가 붙어서 "단독 SQL로 실행 불가"라며 감점. 그런데 그 프리픽스는 label에도 똑같이 붙어 있습니다. 전처리 아티팩트를 모델 잘못으로 채점한 거죠.

해결방법)

1. 5점척도 -> EQUIVALENT / NOT_EQUIVALENT / UNCERTAIN 3분류
척도가 있으면 judge가 항목마다 만족/불만족을 채워야 한다는 압박을 받고, 결국 없는 감점거리를 만들어냄.

2. 무시할 차이 7가지를 열거.
별칭 이름(38건 감점), 컬럼명 차이(24건), 교환법칙 항 순서, 서브쿼리/JOIN 변환, IN/EXISTS, 공백·대소문자, SELECT 컬럼 나열 순서.
직접 나열해서 바보같은 감점사유로 등장한 것들 삭제 

3. 반례 의무화
NOT_EQUIVALENT를 주려면 두 쿼리가 다른 결과를 내는 구체적 데이터 상황을 쓰도록 명시. 그러지 못하면 EQUVALENT.

4. 전처리 분리.
쿼리 작성: 프리픽스는 label에도 붙어 있는데 judge가 이걸로 index 180을 깎았습니다. 프롬프트로 해결할 문제가 아니라 호출 전에 clean_sql()로 잘라냄.



아쉬운 점

정확한 정답이 뭔지 알 수 없음
ex) Q: 대한민국에서 주문한 물품의 종류별 개수를 알려줘
label : 종류별 개수를 보여주긴 하지만 order by를 자기 맘대로 추가함.
이런 경우 정답이 정답이라고 할 수 없음.
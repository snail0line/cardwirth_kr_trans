# CardWirth 한글화 툴

CardWirthPy 시나리오(XML)의 일본어 텍스트를 추출 → 한국어 번역 입력 →
실행 가능한 한글 시나리오로 재삽입(repack)하는 로컬 웹 에디터.

> 📖 **시나리오 구조·흐름을 어떻게 분석하는지**(번역 대상 판별, 화자/말투, 쿠폰 분기 조건,
> 이벤트 흐름 모델)는 **[SCENARIO_ANALYSIS.md](SCENARIO_ANALYSIS.md)** 참조.

## 빠른 시작 (1단계: XML 번역 에디터)

의존성 없음(순수 Python stdlib). Python 3.10+ 면 됩니다.

```bash
cd cardwirth_kr_trans      # 클론/압축해제한 프로젝트 폴더
python -m app.server
```

> Windows 는 `run.bat` 더블클릭으로도 실행됩니다.

브라우저가 자동으로 `http://127.0.0.1:8765` 를 엽니다.

1. **📁 열기** → 폴더 선택창에서 CardWirthPy **XML 시나리오 폴더** 선택
   (예: `...\Scenario\Official\armor`. `Summary.xml` 이 있는 폴더)
   - 경로를 직접 입력하고 Enter 쳐도 됨
2. 좌측 **파일** 탭에서 파일 선택 → 일본어(좌) 보고 한국어(우)에 입력 (포커스 벗어나면 자동 저장)
3. 좌측 **식별자(글로서리)** 탭 → 플래그/스텝/쿠폰 등 이름. **1번 번역하면 정의부와 모든
   참조처에 자동 적용**(시나리오 깨짐 방지)
4. **한글 시나리오 내보내기** → 출력 폴더 지정 → 번역 적용 + 이미지/사운드 등 에셋까지 복사된
   완전한 시나리오 산출. 그 폴더를 CardWirthPy KOR 의 Scenario 에 넣으면 실행됨.

진행 상황은 `projects/<폴더명>.json` 에 자동 저장됩니다. 다시 같은 폴더를 열면 이어서 작업합니다.
원본 시나리오가 바뀌어 재추출해도 원문(JP) 기준으로 기존 번역을 보존합니다.

## 번역 대상 분류

- **자유 텍스트**: `<Text>`(대사), `<Description>`, 제목 `<Name>`, 선택지 라벨(`@name`) 등 → occurrence 별 번역
- **식별자(글로서리)**: 플래그/스텝/쿠폰/가십/시나리오/키코드/링크 이름 →
  이름으로 매칭되는 참조라 고유값당 1번역해 전체 전파
- **제외**: 파일 경로(`path`/`ImagePath`), 플래그 표시값(ＴＲＵＥ/ある 등), id/좌표/숫자

## 구조

```
app/
  schema.py   번역 대상 분류 규칙(자유 vs 식별자)
  xmlio.py    XML 입출력 + 문서순서 슬롯 순회(extract/repack 공유)
  extract.py  XML 폴더 → 번역 프로젝트
  context.py  화자/말투 판정
  flowcond.py 이벤트 흐름 추적 → 대사별 도달 조건(쿠폰 분기 등)
  flow.py     씬 흐름 그래프(플로우차트)
  terms.py    반복 용어/캐릭터명 감지 + 일괄 적용
  textcodec.py 줄바꿈(\n)·이스케이프 디코드/인코드
  repack.py   번역 적용 + 에셋 복사 → 완전한 시나리오
  project.py  프로젝트 JSON 영속화 + 재추출 머지
  server.py   로컬 웹 서버(stdlib http.server) + 폴더 선택 다이얼로그(tkinter)
web/          브라우저 에디터(index.html / app.js / style.css)
SCENARIO_ANALYSIS.md  시나리오 구조·이벤트 흐름·조건 분석 방법(★)
```

## 입력 포맷

현재(1단계)는 **CardWirthPy XML 포맷** 시나리오를 입력으로 받습니다.
classic 바이너리(.wsm/.wid) 시나리오는 CWXEditor/CardWirthPy 로 XML 변환 후 사용하세요.

**2단계(예정)**: Python 3.8 실행환경에 CardWirthPy 변환기를 연동해 binary 시나리오를
툴에서 직접 자동 변환. (바이너리 파싱 자체는 가능하나, XML 재직렬화가 GUI 의존이라
실행환경 구축이 필요)

## 라이선스 / 크레딧

이 도구의 코드는 자체 작성물입니다.

시나리오 파일 포맷(XML/.wsn)과 이벤트 흐름 모델은 **CardWirthPy Reboot** 를 참고했습니다.
CardWirthPy Reboot 의 코드는 The MIT License (Copyright © 2017 log の中の人 및 기여자 일동) 입니다.

- CardWirthPy Reboot: https://bitbucket.org/k4nagatsuki/cardwirthpy-reboot/

CardWirth 및 원작 게임 리소스(이미지·사운드 등)의 저작권은 groupAsk 에 있으며,
**시나리오 파일 자체는 각 제작자의 저작물**입니다 — 이 도구로 번역한 결과물의 배포는
해당 시나리오의 이용 약관을 따르세요. (이 저장소에는 제3자 시나리오를 포함하지 않습니다.)

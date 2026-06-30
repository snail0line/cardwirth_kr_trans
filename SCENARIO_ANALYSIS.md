# CardWirth 시나리오 구조·흐름 분석 가이드

작성일: 2026-07-01 · 갱신은 요청 시에만

CardWirthPy XML 시나리오에서 **번역 대상 텍스트**와 그 **맥락(화자·말투·도달 조건)**을
어떻게 뽑아내는지 정리한다. 엔진 동작은 CardWirthPy 엔진 소스(`src.zip`)의
`cw/content.py`·`cw/event.py` 를 직접 읽어 검증했다(추측 아님).

---

## 0. 분석할 때 가장 먼저 할 일

- **원본 XML 을 그대로 본다.** `ET.parse` 후 트리를 들여다보되, 출력 필터로 태그를
  걸러 보면 중간 래퍼(`Dialogs` 등)를 놓치기 쉽다. 의심되면 **raw 텍스트**를 직접 본다.
- **엔진 소스가 정답.** 분기/연결 의미가 헷갈리면 `src.zip` 의 `content.py`(카드별
  `action()`)·`event.py`(`run`/`get_nextcontents`)를 읽는다.
- **인코딩**: 시나리오 XML 은 UTF-8. 단 구(舊) classic 바이너리(.wsm/.wid)는 cp932(Shift-JIS).
  엔진 소스(`src.zip` 내 .py)도 UTF-8.

---

## 1. 파일/노드 구조

시나리오 폴더 = 여러 XML. 한 파일 = 하나의 "씬"(루트 태그로 구분):

| 루트 태그 | 의미 |
|---|---|
| `Summary` | 시나리오 메타(시작 Area = `Property/StartAreaId`) |
| `Area` | 지역(메뉴/이동 거점). `Property/Id` 로 식별, `Change type="Area"` 의 대상 |
| `Package` | 이벤트 묶음(대화 턴 등). **이름 Link 로 호출되지 않음**(§4 주의) |
| `Battle` | 전투 |
| `CastCard`/`ItemCard`/`SkillCard`/`BeastCard`/`InfoCard` | 카드 정의 |

### 번역 대상 vs 식별자 (★ 가장 중요한 원칙)

- **자유 텍스트(번역 O)**: `<Text>`(대사·나레이션), `<Description>`(설명),
  플레이어에게 보이는 `<Name>`(카드 제목 등), 선택지 `@name`(○/×/숫자/Default 제외).
- **식별자(원문 유지, 번역 X)**: 플래그/스텝/쿠폰/가십/시나리오/KeyCode/Link 의 이름.
  이름 매칭으로 게임 로직이 돌아가므로 **절대 번역하지 않는다.** 용어집은 자유 텍스트에만 적용.
- **내부명(`sysname`)**: Package/Area/Battle 의 최상위 `Property/Name` = 제작자용
  이벤트명(플레이어 비노출). 번역 불필요 → "내용 있는 파일" 판정에서 제외.

코드: `app/schema.py`(슬롯 분류), `app/extract.py`(유닛 생성).

---

## 2. 대사 구조와 화자/말투

### Talk 두 형태

```xml
<!-- (A) Message: 단일 화자(주로 NPC) -->
<Talk type="Message" path="Material/CAST_001_.bmp">
  <Text>\n〈NPC명〉\n「〈대사 본문〉」\n</Text>
</Talk>

<!-- (B) Dialog: PC 발화 + 말투(口調) 변형. 중간에 Dialogs 래퍼 있음! -->
<Talk type="Dialog" targetm="Selected">
  <Dialogs>
    <Dialog><RequiredCoupons>＿「尊大」</RequiredCoupons><Text>…</Text></Dialog>
    <Dialog><RequiredCoupons>＿「粗雑」</RequiredCoupons><Text>…</Text></Dialog>
    …
  </Dialogs>
</Talk>
```

### 화자(speaker) 판정 — `app/context.py speaker_of`

우선순위:
1. **Message 본문 첫 줄이 이름** 이면 그 이름. 형식: `이름\n「대사…」`
   (첫 줄이 짧고 `「`·`#` 로 시작 안 하며 **다음 줄이 「 로 시작**).
   → `path` 는 초상화 파일명(예: `CAST_001_`)이라 실제 이름은 본문에만 있음. **본문 우선.**
2. `path` 가 있으면 그 파일명(NPC). `??Random` 등 동적 토큰은 PC.
3. `type="Dialog"` 이거나 `targetm/targetf/target` 지정 → PC 발화(`랜덤 PC`/`선택 PC`).
4. 아무것도 없으면 나레이션(`""`).

→ 화자 있으면 `dialogue`, 없으면 `narration` 으로 분류.
→ 화자 이름은 **용어집 후보**로도 쓴다(`app/terms.py`, 반복 등장 캐릭터명 일괄 번역).

### 말투(tone) — `tone_of`

`<Dialog>` 의 `<RequiredCoupons>` 값(`＿「尊大」` → 尊大)을 라벨로 매핑(거만/거침/노인/아이/공손/여성/남성…).
같은 `<Talk>` 안 여러 `<Dialog>` = 같은 대사의 말투 변형 → **한 그룹으로 묶음**
(`extract.py`, `id(Talk)` 기준, 멤버 1개 그룹은 해제).

---

## 3. 이벤트 흐름 모델 (★ 조건 분석의 핵심)

> 검증 출처: `cw/event.py` `Event.run`/`get_nextcontents`, `cw/content.py`
> `EventContentBase.action`/`get_children`/`get_boolean_index`, 각 Branch/Link/Call/Start 클래스.

### 실행 단위

```
Event > Contents > ContentsLine* > 카드들(Start/Branch/Talk/Link/Call/Effect/Set…)
```

- **`<ContentsLine>` 안 카드는 문서 순서대로 순차 실행.**
- 카드의 "다음"(`get_children`):
  - ContentsLine 안에 **다음 형제가 있으면 그 형제 1개**,
  - 없으면(라인 끝) 그 카드의 **`<Contents>` 자식들**.
- `action()` 은 자식 목록에서 갈 인덱스를 반환. 음수(`IDX_TREEEND`)면 그 경로 종료.

### name = "어느 출구로 도달했는가"

각 카드의 `name` 속성은 **직전 분기의 결과 라벨**이다:

| name | 의미 |
|---|---|
| `○` (U+25CB) | 직전 분기 **성립** 으로 도달 |
| `×` (U+00D7) | 직전 분기 **불성립** 으로 도달 |
| 숫자 | 값 분기(MultiStep/Select 등)에서 그 값으로 도달 |
| `Default` | 값 분기의 "그 외" |
| `ＯＫ` 등 그 외 | **비분기 카드 다음의 일반 연결**(라우팅과 무관, 무시) |

※ 함정: `ＯＫ`(전각 U+FF2F U+FF2B)는 성립을 뜻하지 않는다. 성립은 오직 `○`.
처음엔 이걸 혼동해 분석이 막혔다.

### 카드별 분기 규칙

- **`<Branch>`**: 결과(성립/불성립/값)에 맞는 `name` 의 자식으로 이동.
  맞는 자식이 없으면 그 경로 종료. → **라인 내 분기는 게이트**:
  다음 형제가 `○` 면 "이 분기 성립 필요", `×` 면 "불성립 필요". 이후 카드 전부 누적(AND).
  - boolean 분기: Coupon, Flag 등 → `○`/`×`. `invert="True"` 면 의미 반전(Wsn.4).
  - 값 분기: Step/MultiStep/Select 등 → 자식 `name` = 값.
  - Coupon 의 `targets`: `Selected`(선택 PC)/`Random`(누군가)/`Unselected`/`Valued`.
- **비분기 카드**(Talk/Effect/Set…): `name` 무시, 무조건 다음으로.
- **`<Link type="Start" link="X">`**: `<Start name="X">` 로 시작하는 ContentsLine 으로
  **점프**(폴스루 없음). = 라인 간 커넥터.
- **`<Call type="Start">`**: 호출 후 복귀. **`<Call type="Package">`**: 다른 파일 호출 후
  복귀 → 파일 내 흐름상 **통과**로 취급.
- **`<Start name="X">`**: 라인의 진입 라벨(Link/Call 대상).

### 도달 조건 = 경로 조건의 DNF

한 대사에 이르는 **모든 경로**의 조건을 모은다. 한 경로 = 조건들의 AND, 여러 경로 = OR.

- 구현: `app/flowcond.py` `compute_file_conditions`.
- 시드: 이벤트의 **첫 ContentsLine**(메인 진입)만 조건 `{}` 로 시작.
  나머지 라인(`その１` 등)은 **Link 로만** 조건을 받는다(빈 조건으로 시드하면 안 됨).
- 워크리스트 전방 전파로 카드별 `set(frozenset(조건))` 누적 → Talk 의 모든 `<Text>` 에 부여.
- 조건 1개 = 튜플 `(kind, who, what, pol)` (예: `("coupon","선택 PC","여성","have")`).
  표시 문자열 포맷·그룹화는 **프런트(`web/app.js groupConds`)**가 담당 — 같은
  `(kind·대상·극성)` 끼리 `what` 을 `/` 로 묶어 배지 수를 줄인다
  (예: 가슴크기 미보유 캐스케이드 5개 → `선택 PC A/AA/3A/빈유/절벽 미보유` 1개).
- 출력 `{"must": [공통 AND], "any": [[갈리는 AND 묶음]…]}` (조건은 `[kind,who,what,pol]` 배열).
  - `must` = 모든 경로 공통 = 초록 배지(그룹화).
  - `any` = 경로마다 갈리는 부분(OR) = "분기 조건 N가지 중 하나" 접이식.

#### 검증 예 (구조 일반화)

어떤 대사가 여러 조건을 거쳐 도달한다고 하자:

- must(모든 경로 공통, AND): 예) `쿠폰 누군가 〈A〉 보유` · `쿠폰 선택 PC 〈B〉 보유`.
- any(경로마다 갈림, OR): 예) `쿠폰 〈C1〉 / 〈C2〉 / 〈C3〉 중 하나 보유`.
  여러 하위 조건 경로가 같은 `Link`(예: `その１`) 라벨로 모이면, 그 라벨에 이르는
  경로들의 조건을 OR 로 묶어 **"분기 조건 N가지 중 하나"** 로 표시한다.

---

## 4. 파일 간 흐름(플로우차트)

핵심: **패키지는 `<Call type="Package" call="N">` 로 호출된다**(N = 대상 패키지의
`Property/Id`). `<Link type="Package" link="N">` 도 동일. 이것이 Area↔Package
왕복 흐름의 실체다. (※ `Link type="Start"` 의 Start 이름은 대부분 `"パッケージイベント"`
로 중복이라 **파일 간** 흐름엔 못 쓴다 — 파일 내 점프용. 처음엔 이걸로 착각해 헤맸다.)

엣지 종류:
- `Call`/`Link type="Package"` (`call`/`link` = Id) → 그 Package/Battle 파일. **(주력)**
- `Change type="Area" id="N"` → Id=N 인 Area.
- ⚠️ **`Link type="Start"` 는 파일 간 엣지로 쓰지 말 것.** 이건 *같은 파일 내* `<Start>`
  로의 점프이고, `その１`/`その２` 같은 로컬 라벨이 흔해서 전역 이름 매칭하면
  엉뚱한 파일로 **가짜 엣지**가 생긴다(실제로 그랬다 → 제거함). 파일 내 점프는 §3 flowcond 가 처리.

**Call 은 호출 후 복귀**한다(서브루틴). 그래서 Area 가 흐름의 **척추**이고,
패키지를 차례로 부르고 각자 끝나면 Area 로 돌아온다. 호출 '순서'가 의미 있으므로
같은 출발지의 엣지는 문서 순서로 `edge_order` 를 매겨 플로우차트에 ①②③… 로 표시.

예(일반화): 시작 Area 가 허브 Area·보조 패키지들을 호출하고, 허브 Area 가 여러 Package 를
①②③… 순서로 호출(각자 복귀)하며, 그 중 한 Package 가 다시 하위 Package 들을 호출하기도 한다.
허브 Area 안에서는 "호출 직전 대사 → 패키지들 실행 → 복귀 후 끝 대사" 순으로 텍스트가 나온다.

구현: `app/flow.py`(`build_flow`/`to_mermaid`/`_reduce_to_content` 가 순서·종류 보존).
플로우차트는 호출=실선 ①②③ 화살표, **패키지 호출의 복귀=점선 「복귀」 화살표**(대상이
Package 인 call 에만; 에리어 이동/Change·Link 는 편도라 복귀 없음)로 '나갔다 들어옴'을 표시.
내용 뷰는 비-content 노드를 건너뛰어 content 패키지만 연결, "로직 노드 포함" 은 전체 그래프.
한 Area 안의 '대사↔호출' 세밀한 순서(끝 대사 위치 등)는 §흐름 보기(`outline.py`)에서 본다.

---

## 5. 분석 도구 매핑

| 알고 싶은 것 | 코드 |
|---|---|
| 번역 대상 슬롯 분류 | `app/schema.py` |
| XML 순회(슬롯+조상) | `app/xmlio.py iter_slots` |
| 유닛 생성·말투 그룹 | `app/extract.py` |
| 화자/말투 | `app/context.py` |
| **도달 조건(쿠폰 분기 등)** | `app/flowcond.py` |
| 파일 내 진행 타임라인(콜/링크/분기 포함) | `app/outline.py` (CWXEditor식 '흐름 보기') |
| 반복 용어/캐릭터명 | `app/terms.py` |
| 흐름 그래프 | `app/flow.py` |
| 줄바꿈(`\n`)·`\\` 인코딩 | `app/textcodec.py` |
| 재삽입(repack) | `app/repack.py` |

---

## 6. 재현 체크리스트 (새 시나리오 분석 시)

1. 폴더 열기 → "내용 있는 것만" 으로 번역 대상 파일 추림.
2. 대사에 **화자/말투/조건 배지**가 맞게 붙는지 표본 확인.
3. 조건이 의심스러우면: 해당 파일 raw XML 의 `ContentsLine` 구조를 보고,
   `flowcond.compute_file_conditions` 결과와 대조.
4. 새 분기 타입이 나오면 `flowcond._branch_who_what`/`_edge_cond` 에 종류·극성 추가
   (표시 라벨은 `web/app.js` 의 `COND_KIND`/`COND_POL`/`groupConds`).
5. repack 후 CardWirthPy(KOR)로 실제 구동 검증.

# AI Market Watch 디자인 문서

---

## 1. 디자인 시스템

DPLANEX Design System v1.0을 기반으로 합니다. 아래 토큰은 DPLANEX VI 가이드라인에서 직접 가져옵니다.

### 1.1 컬러 토큰

| 토큰 | 변수 | Hex | 용도 |
|------|------|-----|------|
| DPLANEX Violet | `--brand` | `#60269E` | 헤더, CTA, 강조 텍스트 |
| DPLANEX Green | `--accent-green` | `#93D500` | 슬래시 액센트, 신규·액션 표시 |
| Violet Deep | `--brand-deep` | `#401771` | 그라디언트 마무리, 어두운 배경 |
| Violet Hover | `--brand-hover` | `#4C1C80` | 버튼 hover·active 상태 |
| Blue Green | `--accent-blue-green` | `#00AF9A` | 정보성 강조 |
| Orange | `--accent-orange` | `#FF6C0E` | 경고, 주의 환기 |
| Dark Gray | `--dpx-dark-gray` | `#54565A` | 서브 텍스트, 보조 정보 |
| Gray | `--dpx-gray` | `#898A8D` | 아이콘, 보더, 비활성 상태 |
| Success | `--success` | `#18A957` | 성공 상태, 완료 알림 |
| Error | `--error` | `#D92D20` | 오류 상태, 파괴적 액션 |

### 1.2 타이포그래피

| 역할 | 폰트 | 크기 / 굵기 | 용도 |
|------|------|------------|------|
| Heading 1 | Source Serif 4 / Noto Serif KR | 42px / 500 / −1.5% | 페이지 제목 |
| Heading 2 | Source Serif 4 / Noto Serif KR | 30px / 500 | 섹션 제목 |
| Heading 3 | Source Serif 4 / Noto Serif KR | 22px / 500 | 카드 제목, 서브 섹션 |
| Body | Inter / Noto Sans KR | 16px / 400 / lh 1.7 | 본문, 설명 |
| Small | Inter | 13px / 500 | 라벨, 메타 정보, 뱃지 |
| Code | JetBrains Mono | 13px / 400 | 코드, 로그 |

### 1.3 Surface & Shape

- **Border Radius**: 10px (버튼·인풋·카드·패널 공통)
- **Shadow Base**: 상호작용 가능한 표면. hover 시 더 깊게 변경
- **Page Background**: `#F9F9F7` (약간 따뜻한 회백색)
- **Card Surface**: `#FFFFFF`
- **Border**: `1px solid #E5E5E5` (hairline)

### 1.4 아이콘

- 스타일: Lucide 라인 아이콘, `stroke-width: 1.5`, `stroke="currentColor"`
- 사이즈: 12px (인라인 pill), 16px (버튼·네비), 18px (카드 내부), 32px (헤더·보드)
- 원칙: 모노톤 라인만 사용. 채워진 아이콘 금지. 멀티컬러·이모지 금지. round cap/join.

### 1.5 컴포넌트 정의

**Button** (pill 형태)
```
Primary   — bg #60269E, text white, hover #4C1C80
Accent    — bg #93D500, text white
Secondary — border #60269E, text #60269E, bg transparent
Ghost     — text #54565A, bg transparent
Disabled  — bg #E5E5E5, text #898A8D, cursor not-allowed
```

**Badge** (soft 톤 — 브랜드 컬러 + 알파)
```
기술 흐름  — bg #F3EAFB, text #60269E
기업 사례  — bg #E6F7F5, text #00AF9A
금융권 활용 — bg #EEF2FF, text #1D4ED8
규제·정책  — bg #FFF3EC, text #FF6C0E
경쟁사 동향 — bg #F3F4F6, text #54565A
NEW        — bg #93D500, text white
✓ Success  — bg #E9F9EE, text #18A957
✕ Error    — bg #FEE9E7, text #D92D20
```

**Callout**
```
Info    — border-left #60269E, bg #F9F5FF
Success — border-left #18A957, bg #F0FFF4
Warning — border-left #FF6C0E, bg #FFF7F0
Error   — border-left #D92D20, bg #FFF5F5
```

**Input**
```
Border:       1px solid #E5E5E5, radius 10px
Focus:        border #60269E + box-shadow rgba(96,38,158,0.14)
Label:        항상 입력 위에 위치, Inter 13px/500
Placeholder:  text #898A8D
Types:        Text / Search / Select / Textarea
```

**Card**
```
Base    — white bg, shadow-sm, radius 10px, border 1px #E5E5E5
          구성: 좌상단 아이콘(18px) + serif 제목(H3) + sans 설명 + 화살표 CTA
Accent  — Violet→Green 그라디언트 surface (강조 카드)
hover   — shadow 강해짐

List Card (목록 행, 전체 클릭형) — NEWS-001·REPORT-001 등 목록 화면 공용 표준
          카드 전체가 클릭 영역. 별도 "상세보기" 버튼은 두지 않는다.
          hover — shadow 강해짐 (border-color 변경 없음, Base와 동일 규칙)
          제목 강조 — 제목 자체에 hover를 걸지 않고 카드(그룹)의 group-hover:text-primary 사용
          구현 원칙 (실제 코드는 product-engineer가 작성):
            · 경쟁 액션이 없는 카드(예: REPORT-001)
              → 카드 콘텐츠 전체를 <a href="..." class="block group">로 감싼다
              → 참고 구현: templates/graph/_org_panel.html (관련 뉴스 리스트, 23행)
            · 경쟁 액션(삭제 버튼 등)이 있는 카드(예: NEWS-001)
              → "Stretched Link" 기법 사용, JS(location.href, @click.stop 체이닝)로 흉내내지 않는다
                실제 <a> 태그를 써야 새 탭 열기·링크 복사·키보드 Tab 이동이 그대로 동작한다
                1) <a class="absolute inset-0 z-0">를 카드의 첫 자식으로 두어 카드 전체를 덮는다
                2) 보이는 콘텐츠는 <div class="relative z-10 pointer-events-none">로 감싸 클릭이 앵커를 통과하게 한다
                3) 경쟁 액션 버튼(및 그 모달)은 pointer-events-auto + 앵커보다 높은 z-index를 줘 자체 클릭을 가로채게 한다
                   (버튼을 <a> 안에 중첩시키지 않는다 — <a> 안에 <button>을 넣는 것은 유효하지 않은 마크업)
```

**Table**
```
헤더:  uppercase, text-xs(13px), text #898A8D, border-bottom 1px #E5E5E5
행:    좌측 정렬, 16px, border-bottom 1px #E5E5E5
hover: bg #F9F9F7
```

**Accordion Expanded Content** (아코디언을 펼쳤을 때 드러나는 본문형 콘텐츠)
```
원칙: 접힌 상태(목록 미리보기)와 펼친 상태(읽기 콘텐츠)는 성격이 다르므로
      서로 다른 타이포그래피를 쓴다. 새 스케일을 만들지 않고 이미 검증된
      본문 패턴(news/detail.html)을 상태별로 그대로 재사용한다.

자유 서술형 장문(예: 분석 전문 — `insight.content`)
  라벨 — "분석" · text-sm font-semibold text-gray-900 (시사점 라벨과 폰트 크기·굵기·색상 동일)
         아이콘 — Lucide `trending-up`, w-4 h-4, text-teal (#00AF9A Blue Green, "정보성 강조" 토큰)
         → 시사점 라벨(lightbulb, text-accent)과 세트를 이루되 아이콘 종류·색만 달리해 구분한다.
           "요약"이라는 표현은 쓰지 않는다 — `insight.content`는 RA가 여러 기사를 종합해 작성하는
           "주요 흐름 분석"(research-analyst.md 정의)이며, 단순 축약이 아니라 해석이 들어간
           분석이므로 "요약"은 실제 내용과 어긋난다.
         라벨은 접힌 상태(목록 미리보기)에는 노출하지 않는다 — `x-show="open"`일 때만 보여
         접힌 상태의 스캔 밀도를 그대로 유지한다.
  펼침 — text-sm text-gray-700 leading-relaxed  (news/detail.html 본문과 동일, 변경 없음)
  접힘 — text-xs text-gray-500 line-clamp-2      (목록 미리보기, 변경하지 않음, 라벨 없음)
  구현 — 같은 <p>가 두 역할을 겸할 경우 Alpine :class 삼항 분기로 전환
         예) :class="open ? 'text-sm text-gray-700 leading-relaxed' : 'text-xs text-gray-500 line-clamp-2'"
  주의 — 시사점과 달리 콜아웃 박스(bg-* 배경)를 씌우지 않는다. 박스는 "시사점"(실행 가능한 해석)
         전용 강조 장치이므로, 분석 전문까지 박스로 감싸면 두 섹션의 시각적 우선순위가 같아져
         시선이 시사점으로 유도되지 않는다.

구조화된 콜아웃 본문(예: 시사점 — bg-purple-50 border-l-4 border-primary p-3 박스)
  라벨 — text-sm font-semibold text-gray-900     (news/detail.html 라벨과 동일)
  본문 — text-sm text-gray-700                   (news/detail.html 시사점 박스와 동일, leading-relaxed 불필요)

보조 정보(예: 관련 기사 링크 목록)
  text-xs 유지 — 대시보드 "최신 뉴스" 목록과 동일한 밀도의 스캔용 목록이므로 굳이 키우지 않는다
```

**Info Tooltip** (데이터·기준 안내 팝오버 — 전 화면 공용, 2026-07-31 신설, PD)
```
배경: 데모 피드백 축 3 "항목별 데이터·기준 툴팁". PM 통합 계획서 채택안 —
      "재사용 팝오버 컴포넌트 1개 + 문구는 별도 딕셔너리로 한곳 관리, 대시보드(ALL-001)부터
      단계 적용". 최초 적용은 ALL-001 5개 카드(아래 ALL-001 절 "카드별 데이터·기준 툴팁 적용"
      참고), 이후 다른 화면은 이 컴포넌트를 그대로 재사용하고 문구만 딕셔너리에 추가한다.

역할 구분: 이 프로젝트에 이미 있는 "관련 뉴스 호버 팝오버"(기업별 Top10·기술주제별 카드,
      데이터 자체를 목록으로 보여줌)와는 목적이 다르다 — Info Tooltip은 "이 카드가 무엇을
      어떤 기준으로 집계했는지"를 설명하는 정적 텍스트 팝오버다. 다만 같은 화면 안에서
      "팝오버 상호작용"에 대한 사용자 학습 비용을 하나로 통일하기 위해 시각 톤
      (흰 배경 · 테두리 · shadow-lg · rounded-[10px])과 Alpine 패턴(호버+클릭, x-cloak)은
      기존 관련 뉴스 팝오버와 동일하게 맞춘다.

트리거: "?" 아이콘 버튼 — w-4 h-4 rounded-full bg-gray-100 text-gray-400 text-[10px] font-bold
        flex items-center justify-center, hover 시 bg-gray-200 hover:text-gray-600
        (기존 templates/setting/_keywords.html "?" 버튼과 톤 동일, 배경색은 흰 팝오버로 통일해
        가져옴 — _keywords.html 쪽은 어두운 팝오버라 이번엔 따르지 않음, 아래 "왜 다른가" 참고)
        카드/섹션 제목(H2·H3, text-sm font-semibold text-gray-900) 바로 옆 gap-1.5로 배치.

팝오버: bg-white border border-gray-200 rounded-[10px] shadow-lg p-3, w-64
        문구는 text-sm text-gray-700 leading-relaxed 한 문단만(별도 헤딩 없음 — 카드 제목이
        이미 주제를 밝히고 있어 팝오버 안에서 반복하지 않는다)
        배치: absolute left-0 top-full(트리거 바로 아래, 여백 0). top-6처럼 여백을 두면 마우스가
        트리거→팝오버로 이동하는 동안 빈 픽셀 지대를 지나며 mouseleave가 먼저 발동해 팝오버가
        열리기도 전에 닫히는 "호버 데드존" 버그가 생긴다 — 기업별 Top10 호버 팝오버에서 이미
        검증·회피한 문제와 동일 원인(위 ALL-001 절 "기업별 Top10 호버 팝오버" 참고)이라 동일하게
        여백 0으로 방지한다.
        z-index: z-30 (같은 화면의 기존 데이터 팝오버 z-20보다 위)

인터랙션 (Alpine.js, x-cloak 필수 — CLAUDE.md 최우선 점검 항목):
  x-data="{ open: false }" — 트리거+팝오버를 함께 감싸는 wrapper(position relative)에 선언
  @mouseenter="open = true" @mouseleave="open = false"  (wrapper)  — 데스크탑 호버
  @click="open = !open"                                  (버튼)    — 터치 기기·클릭 사용자용 토글
  @click.outside="open = false"                           (wrapper) — 클릭으로 연 상태에서 바깥 클릭 시 닫기
  @keydown.escape="open = false"                          (버튼)    — 포커스 상태에서 Esc로 닫기
  x-show="open" x-cloak                                   (팝오버)  — FOUC 방지, 예외 없이 필수
  버튼: aria-label="{{ 안내 대상 이름 }} 안내"  :aria-expanded="open"

마크업 예시 (PE가 그대로 구현, 문구/label만 카드별로 치환):
```html
<span class="relative inline-flex" x-data="{ open: false }"
      @mouseenter="open = true" @mouseleave="open = false"
      @click.outside="open = false">
  <button type="button"
          @click="open = !open"
          @keydown.escape="open = false"
          aria-label="{{ 안내 대상 이름 }} 안내"
          :aria-expanded="open"
          class="w-4 h-4 rounded-full bg-gray-100 text-gray-400 text-[10px] font-bold
                 flex items-center justify-center hover:bg-gray-200 hover:text-gray-600
                 transition-colors focus:outline-none focus:ring-2 focus:ring-primary/30">
    ?
  </button>
  <div x-show="open" x-cloak
       class="absolute left-0 top-full z-30 w-64 bg-white border border-gray-200
              rounded-[10px] shadow-lg p-3">
    <p class="text-sm text-gray-700 leading-relaxed">{{ 문구 }}</p>
  </div>
</span>
```

왜 `_keywords.html`의 어두운 툴팁(`bg-gray-900 text-white rounded-lg`)을 따르지 않았나:
  이번 요구사항이 명시한 톤(text-sm/leading-relaxed/text-gray-700, 카드 소제목
  text-sm font-semibold text-gray-900, rounded-[10px], shadow-sm)은 흰 배경 팝오버 쪽이고,
  ALL-001 안에 이미 3곳(기업별 Top10, 기술주제별, 차트 dot)에 흰 배경 팝오버가 정착해 있어
  같은 화면 안에서 팝오버 톤을 통일하는 게 우선이라고 판단했다. `_keywords.html`을 이 톤에
  맞춰 고치는 건 이번 스코프 밖(대시보드 5개 카드 한정)이라 진행하지 않았다 — 추후 다른
  화면에 이 컴포넌트를 확장 적용할 때 함께 정리할 여지로 남겨둔다.

재사용 방법 (구현 지침 — PE):
  문구를 템플릿에 하드코딩하지 않고 별도 딕셔너리로 한곳 관리한다(PM 채택안 필수 요건).
  이 프로젝트에 이미 커스텀 템플릿 태그 전례가 있으므로(`apps/reports/templatetags/report_extras.py`,
  `{% load report_extras %}` + markdown 필터) 동일 관례를 따르는 걸 권장한다(파일 위치·태그 이름
  자체는 PE 판단, 아래는 참고용 스케치):
    1) 문구 딕셔너리 하나 — 예) `apps/dashboard/tooltips.py` (여러 화면이 공유하게 되면
       `apps/common/tooltips.py` 등으로 승격 가능). 키는 화면 prefix를 붙인 slug 문자열
       (다른 화면 문구가 나중에 섞여도 충돌 없게), 값은 안내 문구 한 문단.
       ```python
       INFO_TOOLTIPS = {
           "dashboard.trend": "...",
           "dashboard.org_ranking": "...",
           "dashboard.tech_topic": "...",
           "dashboard.insights": "...",
           "dashboard.latest_news": "...",
       }
       ```
    2) inclusion_tag 하나 — `apps/dashboard/templatetags/dashboard_extras.py`에
       `{% info_tooltip "dashboard.trend" label="일별 뉴스 건수 추이" %}` 형태로 위 마크업을
       렌더링하는 태그를 만든다. `label`은 딕셔너리 키와 별개로 aria-label용 텍스트를 태그
       인자로 받는다(문구와 라벨을 같은 딕셔너리 value에 억지로 합치지 않기 위함).
    3) 컴포넌트 파일은 `templates/components/_info_tooltip.html` 하나로 통일 — 5곳(과 이후
       다른 화면)이 전부 이 파일을 `{% include %}`(또는 inclusion_tag 내부에서 include)하도록
       해 마크업이 여러 곳에 중복되지 않게 한다.
  PD가 이 파일 구조까지 강제하는 건 아니다 — 다만 "컴포넌트 1개 + 문구 딕셔너리 1곳"이라는
  PM 채택 방향은 반드시 지킬 것 (템플릿마다 팝오버 마크업을 복붙하거나 문구를 각 템플릿에
  흩어 넣는 방식은 채택안 위반).
```

---

## 2. 레이아웃 구조

반응형: 데스크탑(1280px+) → 태블릿(768px) → 모바일(375px)

```
┌─────────────────────────────────────────────┐
│                   Header                    │  h-14, bg #60269E
├──────────┬──────────────────────────────────┤
│          │                                  │
│ Sidebar  │        Main Content              │
│  w-56    │        flex-1                    │
│          │                                  │
│          │                                  │
├──────────┴──────────────────────────────────┤
│                   Footer                    │  h-10
└─────────────────────────────────────────────┘
```

**Header** (고정, `position: sticky top-0 z-50`)
- 좌: DPLANEX 워드마크 + `/` 슬래시(Green) + `AI Market Watch`
- 우: 마지막 수집 시간 표시 + 아바타

**Sidebar** (데스크탑 고정, 모바일 오버레이)
- 상단: 서비스 로고 영역
- 네비게이션 메뉴: 전체 / 뉴스 / 보고서 / 설정(하위 메뉴 accordion)
- 활성 메뉴: bg `#F3EAFB`, text `#60269E`, left border `2px solid #60269E`

**Footer**
- `© 2026 DPLANEX · AI Market Watch`
- 버전 표시

---

## 3. 화면별 디자인 스펙

---

### ALL-001 · 전체 대시보드

**목적**: 서비스 전체 현황을 한눈에 파악하는 홈 화면

**구성 요소**

```
┌─ 핵심 지표 (기간 셀렉터: [전체] [최근 30일] [●최근 7일]) ───────────────┐
│  ┌─ 일별 뉴스 건수 추이 ──┐ ┌─ 기업별 Top 10 ───┐ ┌─ 기술주제별 건수 ─┐ │
│  │ 일별 뉴스 건수 추이     │ │ 1 KB국민은행 9건  │ │ 1 AI 에이전트 11건│ │
│  │ 12┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │ │ 2 삼성생명   6건  │ │ 2 AI 거버넌스  2건│ │
│  │  6┄┄┄○▓▓╲╱▓▓●╲╱▓▓○┄┄┄  │ │ ...  (Top10, hover│ │ 3 온톨로지     1건│ │
│  │  0└○──┴──┴──┴──┴──┴──● │ │  시 관련뉴스 팝오버│ │ 4 AI Ready Data1건│ │
│  │   07/03 04 05 06 07 08 │ │  , 기존 유지)      │ │ (호버 팝오버 추가,│ │
│  │  (y축 0/중간/최댓값 눈금│ │                    │ │  0건 주제는 제외) │ │
│  │   + 왼쪽 축선, x축 눈금 │ │                    │ │                   │ │
│  │   선+날짜, hover시 툴팁,│ │                    │ │                   │ │
│  │   점·눈금숫자·날짜라벨은│ │                    │ │                   │ │
│  │   전부 HTML 오버레이 —  │ │                    │ │                   │ │
│  │   flex-1로 세로 꽉 채움)│ │                    │ │                   │ │
│  └─────────────────────────┘ └────────────────────┘ └───────────────────┘ │
│  ※ 3개 카드 모두 위 기간 셀렉터 하나를 공유(카드별 개별 셀렉터 없음).      │
│    "최근 7일"=일별 7점, "최근 30일"=일별 30점(라벨은 ~5일 간격으로만),    │
│    "전체"=주별(장기화 시 월별) 가변 개수 — 카드 A 제목도 일별/주별/월별│
│    로 자동 전환된다. 자세한 스펙은 아래 "기간 필터 + 뉴스 건수 추이 차트  │
│    가변화" 절 참고.                                                        │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ 주요 이슈 (2/3, 아코디언 확장형) ─┐  ┌─ 최신 뉴스 (1/3) ─────────┐
│  이슈 카드 × N                     │  │  뉴스 카드 × 10             │
│  - 이슈 제목                       │  │  - 제목                     │
│  - 관련 기사 수                    │  │  - 발행일                   │
│  - 요약 2줄 (접힘) / 펼치면        │  └─────────────────────────────┘
│    content 전문 + 시사점 +         │
│    관련 기사 링크(→ NEWS-002)      │
└─────────────────────────────────────┘
```

**핵심 지표 카드 상세 (Phase A, `docs/planning.md` "정량화 축" 79-104행 근거)**

세 카드 모두 차트 라이브러리 없이 순수 Tailwind CSS + 인라인 SVG로 구현한다. 데이터 규모(최근 7일, 랭킹 10위 이내)가 작아 Chart.js 등 신규 의존성 도입은 과함 — 프로젝트에 차트 라이브러리가 로드된 적이 없다는 점도 확인함(`templates/base.html` 기준).

1. **일별 뉴스 건수 추이** — 인라인 SVG `<path>` 라인그래프(부드러운 곡선 + 라인 아래 그라데이션 영역 채움 + 실제 x/y축 + 데이터포인트 호버 툴팁). 좌표계는 y축(0/중간값/최댓값)·x축(각 데이터포인트 x좌표에 붙은 눈금선)을 데이터와 같은 SVG viewBox 좌표계로 통합해 픽셀 단위로 맞췄다. 오늘 지점만 진한 보라(`#60269E`) 채움 dot + 굵은 라벨, 나머지는 흰 채움 + 연한 보라 테두리(`border-primary/35`) dot으로 구분 — 기존 `bg-primary` vs `bg-primary/25` 대비 규칙을 라인그래프 어법으로 옮긴 것. **사람이 읽는 글자(y축 눈금 숫자 3개, x축 `MM/DD` 날짜 라벨 7개, 데이터포인트 dot)는 전부 SVG `<text>`/`<circle>`이 아니라 HTML/CSS 오버레이**다 — `preserveAspectRatio="none"`이 카드의 실제 가로/세로 비율에 맞춰 SVG 좌표계를 비균등 배율로 늘리기 때문에, SVG 안에 남겨두면 원은 타원으로(2026-07-10 4차, 아래 "일별 추이 차트 시각 버그 수정(4차)" 절), 텍스트는 세로로 늘어나 뭉개져(2026-07-10 5차, 아래 "일별 추이 차트 시각 버그 수정(5차)" 절) 보인다. SVG에는 그리드라인·곡선·영역 채움·축선 같은 순수 도형만 남고, 눈금 숫자·날짜 라벨·dot은 모두 `widthratio` 태그로 SVG 좌표를 %로 환산한 절대 위치 HTML 요소다. 카드 제목 옆에 있던 "발행일 기준" 보조 라벨은 2026-07-10 5차에 사용자 피드백으로 제거했다(아래 "일별 추이 차트 시각 버그 수정(5차)" 절 참고) — 집계 기준(`News.published_at`)은 여전히 발행일 기준이지만 화면에 별도로 표기하지 않는다. 상세는 아래 "일별 추이 차트 축 개선(3차)" 절 참고.
2. **기업별 건수 Top 10** — 순위 번호 + 기업명(truncate) + 가로 미니바(금융사 `bg-blue-500`/보험사 `bg-teal`/AI `bg-primary`, 기존 뉴스 목록 배지 색상 규칙과 동일 매핑) + 건수. 활성 기업(`is_active=True`)만 대상. 미니바 색상이 무엇을 뜻하는지 안내하는 색상 범례를 카드 제목 아래에 추가했다(2026-07-10, PD, PM 확정 — 아래 "기업별 건수 Top 10 색상 범례 추가" 절 참고). 기업명 호버 시 관련 뉴스 팝오버(아래 "기업별 Top 10 호버 팝오버" 절 참고, 기존 기능 그대로 유지).
3. **기술 주제별 언급 건수** — 순위 번호 + 주제명(truncate) + 가로 미니바(`bg-accent`, Accent Green) + 건수. 기업별 Top 10과 동일한 랭킹 리스트 톤(순위/이름/미니바/건수, 폭 규격까지 동일 `w-4`/`w-20`/`w-6`)을 재사용하되, 색상만 Accent Green으로 바꿔 "기업 축"과 "기술주제 축" 두 카드를 시각적으로 구분한다. **주제명 호버 시 관련 뉴스 팝오버**를 기업별 Top 10과 완전히 동일한 패턴으로 추가했다(2026-07-10, 아래 "기술 주제별 호버 팝오버" 절 참고) — 최초 배치 때는 스코프 최소화를 위해 제외했으나 사용자 피드백으로 기업별 카드와 인터랙션을 통일.

세 카드 모두 데이터가 없을 때 기존 프로젝트 empty state 패턴(회색 아이콘 + 안내문, opacity-40)을 재사용한다.

**"기업유형별 건수" 카드 제거 (2026-07-10, PM 확정)**: 기업 축의 "유형 집계"(금융사/보험사/AI 3분류 진행바)와 "개별 랭킹"(기업별 Top 10)이 정보 중복이라는 판단 하에 유형 집계 카드를 완전히 제거하고, 그 자리를 신규 "기술 주제별 언급 건수" 카드로 대체했다. `apps/dashboard/views.py`의 `_build_org_type_counts()`와 뷰의 `org_type_counts` 컨텍스트 변수는 더 이상 템플릿에서 참조하지 않으므로 PE가 정리(제거 또는 미사용 방치는 PE 판단) 가능.

**"최근 7일" 표기 위치**: ~~카드마다 반복하지 않고, "핵심 지표" 섹션 제목 옆 pill 배지(`bg-gray-100 text-gray-400 rounded-full`) 하나로 통일 표기한다.~~ **(2026-07-27 대체됨)** 고정 pill 배지는 아래 "기간 필터 + 뉴스 건수 추이 차트 가변화" 절의 3-옵션 셀렉터로 교체됐다. 셀렉터도 "핵심 지표" 섹션 제목 옆에 위치한다는 배치 원칙(섹션 단위로 한 번만 표기)은 그대로 유지.

**구현 참고 (`apps/dashboard/views.py`가 채울 컨텍스트 변수, PD는 더미 구조만 정의)**

- `daily_counts` / `daily_max_count` — **(2026-07-27 대체됨)** 아래 "기간 필터 + 뉴스 건수 추이 차트 가변화" 절의 `trend_points` / `trend_max_count`로 이름과 구조가 바뀌었다. 이 문단의 7일 고정 좌표 공식(`x = PAD_LEFT + i * (CHART_W / 6)`)은 더 이상 유효하지 않다 — 새 스펙 참고.
- `org_ranking`: 최대 10개 dict 리스트(건수 내림차순, 활성 기업만). 키 — `rank`(int, 1부터), `name`(str), `org_type`(str), `count`(int), `pct`(int, 0~100 — 1위 건수 대비 %, 1위가 0이면 0), `recent_news`(list, 최대 5개 dict — 각 `uid`(str), `title`(str). 최신 발행일 순, 선택된 기간과 동일한 range 기준), `more_count`(int, 0 이상 — `count - len(recent_news)`, 5건 이하면 0). 구조는 기존과 동일하되, **날짜 range가 고정 "최근 7일"이 아니라 선택된 `period`를 따른다** — `period == "all"`이면 날짜 하한 없이 전체 집계(아래 "기간 필터" 절의 `start_date`/`today` 정의 참고).
- `tech_topic_counts`: dict 리스트(건수 내림차순 → 동률 시 이름순, **0건 주제는 제외** — `count__gt=0`, `org_ranking`과 동일 필터링 관례를 따름). 상한 개수 없음. 키 — `rank`(int, 1부터), `name`(str, `TechTopic.name`), `count`(int, 선택된 기간 range 기준 `News.tech_topics` 역참조 건수), `pct`(int, 0~100 — 1위 건수 대비 %, 1위가 0이면 0), `recent_news`(list, 최대 5개 dict — 각 `uid`(str), `title`(str), 최신 발행일 순), `more_count`(int, 0 이상 — `count - len(recent_news)`). `org_ranking`과 동일하게 `is_active=True`인 `TechTopic`만 대상, 날짜 range도 `org_ranking`과 동일하게 선택된 `period`를 따른다. `recent_news`/`more_count` 추가 배경은 아래 "기술 주제별 호버 팝오버" 절 참고.
  - PE 참고용 쿼리 스케치(`_build_org_ranking()`과 구조 완전히 동일, `Organization` → `TechTopic`으로만 치환):
    ```python
    def _build_tech_topic_counts(start_date, today):
        date_filter = Q(news__published_at__date__gte=start_date, news__published_at__date__lte=today)
        topics = list(
            TechTopic.objects.filter(is_active=True)
            .annotate(count=Count("news", filter=date_filter, distinct=True))
            .filter(count__gt=0)
            .order_by("-count", "name")
        )
        max_count = topics[0].count if topics else 0
        tech_topic_counts = []
        for rank, topic in enumerate(topics, start=1):
            recent_news = list(
                topic.news
                .filter(published_at__date__gte=start_date, published_at__date__lte=today)
                .order_by("-published_at", "-pk")[:5]
            )
            tech_topic_counts.append({
                "rank": rank,
                "name": topic.name,
                "count": topic.count,
                "pct": _pct(topic.count, max_count),
                "recent_news": [{"uid": n.uid, "title": n.title} for n in recent_news],
                "more_count": max(topic.count - len(recent_news), 0),
            })
        return tech_topic_counts
    ```
    (`TechTopic.news`는 `News.tech_topics`의 `related_name="news"`로, `Organization.news`와 동일한 역참조 이름이라 쿼리 패턴을 그대로 재사용 가능함을 `apps/news/models.py`에서 확인함.)

    **(2026-07-27 추가)** 위 스케치는 `start_date`가 항상 값이 있다는 전제였다. `period == "all"`일 때는 `start_date`가 `None`이 되므로(날짜 하한 없음), `date_filter`를 조건부로 구성해야 한다 — 예: `Q(news__published_at__date__lte=today)`에서 시작해 `start_date`가 있을 때만 `& Q(news__published_at__date__gte=start_date)`를 덧붙인다. `org_ranking`도 동일하게 처리.

템플릿(`templates/dashboard/index.html`)은 `trend_points`/`org_ranking`/`tech_topic_counts`가 비어있어도 에러 없이 empty state로 degrade 되도록 이미 작성돼 있다(뷰가 아직 이 스펙대로 안 채워도 `{% if %}` 분기로 안전).

**기업별 Top 10 호버 팝오버 (2026-07-10, PD, PM 없이 순수 인터랙션 개선으로 처리)**

기업명에 마우스를 올리면 해당 기업과 연결된 최근 뉴스 목록이 팝오버로 뜬다.

```
┌─ 기업별 건수 Top 10 ────────────┐
│ 1 KB국민은행 ▓▓▓▓▓▓▓▓░░  9건   │ ← hover
│   ┌─────────────────────────┐  │
│   │ KB국민은행 관련 뉴스     │  │
│   │ · 기사 제목 1            │  │
│   │ · 기사 제목 2  (최대 5개)│  │
│   │ ─────────────────────   │  │
│   │ 외 2건 더 보기           │  │
│   └─────────────────────────┘  │
│ 2 삼성생명   ▓▓▓▓▓░░░░░  6건   │
│ ...                             │
│10 ...                    1건   │
└─────────────────────────────────┘
```

- **인터랙션**: Alpine.js `x-data="{ tip: false }"` + `@mouseenter`/`@mouseleave` + `x-show="tip"` + `x-cloak` 조합(CSS 전용 `:hover`/`group-hover`가 아닌 Alpine 상태 기반 호버). 이 프로젝트에 이미 동일 패턴이 있음(`templates/setting/_keywords.html`의 "?" 툴팁). CSS 전용 hover를 쓰지 않은 이유: 팝오버 안의 뉴스 링크를 실제로 클릭할 수 있어야 해서, 단순 `:hover` 표시/숨김보다 상태를 붙잡아둘 수 있는 Alpine 쪽이 적합.
- **호버 트리거 영역**: 기업명 텍스트뿐 아니라 행 전체(`flex items-center gap-2` div)에 `@mouseenter`/`@mouseleave`를 건다. 이유: 팝오버가 기업명(행 왼쪽)이 아니라 행 폭 전체(`inset-x-0`)에 걸쳐 배치되는데, 트리거를 기업명 텍스트 하나로 좁혀두면 마우스가 기업명에서 팝오버로 이동하는 경로 중간에 "행도 아니고 팝오버도 아닌" 빈 픽셀 지대를 지나면서 `mouseleave`가 먼저 발동해 팝오버가 열리기도 전에 닫혀버리는 표준적인 호버 데드존 버그가 생긴다. 행 전체를 트리거로 넓히고 행-팝오버 사이 여백(margin)을 0으로 둬서(`top-full`/`bottom-full`, gap 없음) 이 문제를 피했다.
- **배치**: 팝오버는 `absolute inset-x-0`으로 행과 동일한 가로 폭(=카드 내부 폭)에 맞춰 정렬해 카드 밖으로 잘리거나 옆 카드를 가리지 않는다. 세로 방향은 순위 1~5위는 `top-full`(아래로 펼침), 6~10위는 `bottom-full`(위로 펼침)로 Django 템플릿에서 순위 기준 분기해, 리스트 하단/상단 근처 항목이 화면 밖으로 밀려나는 걸 막는다(JS 좌표 계산 없이 정적 렌더링만으로 처리).
- **표시 건수**: 최대 5건(`org.recent_news`) + 6건째부터는 "외 N건 더 보기" 텍스트(링크 아님, 클릭 액션 없음). 현재 기업당 최대 건수가 6건 수준(토스/신한은행)이라 스크롤 없이 충분.
- **스타일**: `bg-white border border-gray-200 rounded-[10px] shadow-lg p-3`, z-index `z-20` — 기존 "기업 추가" 드롭다운(`templates/news/_orgs.html`)과 동일 톤.
- **PE 작업 스펙**: `apps/dashboard/views.py`의 `_build_org_ranking()`이 만드는 `org_ranking`의 각 dict에 `recent_news`(list[dict], 최대 5개, 키 `uid`/`title`, 발행일 최신순, 랭킹과 동일한 `start_date~today` range 필터)와 `more_count`(int)를 추가로 채워야 한다. 템플릿은 이 두 키가 없어도(더미/빈 상태) 에러 없이 "연결된 뉴스가 없습니다"로 degrade 되도록 작성해뒀다(`{% if org.more_count %}`처럼 부등호 비교 없이 truthy 체크만 사용 — 빈 문자열과 int를 `>` 비교하면 템플릿 렌더링 에러가 나기 때문).

**기술 주제별 호버 팝오버 (2026-07-10, PD, 사용자 피드백으로 추가)**

"기업별 건수 Top 10"의 호버 팝오버(위 절)를 "기술 주제별 언급 건수" 카드에도 **동일한 패턴 그대로** 적용했다. 새 인터랙션을 발명하지 않고, `x-data="{ tip: false }"` + `@mouseenter`/`@mouseleave` + `x-show="tip" x-cloak` + gap 0 `top-full`/`bottom-full` 분기(순위 1~5는 아래로, 6위 이후는 위로) + 최대 5건 + "외 N건 더 보기"까지 마크업 구조를 그대로 복제했다. 스타일(`bg-white border border-gray-200 rounded-[10px] shadow-lg p-3 z-20`)도 동일.

- **PE 작업 스펙**: `_build_tech_topic_counts()`가 만드는 `tech_topic_counts`의 각 dict에 `recent_news`(list[dict], 최대 5개, 키 `uid`/`title`, 발행일 최신순, `start_date~today` range 필터)와 `more_count`(int)를 추가해야 한다 — `_build_org_ranking()`의 `recent_news`/`more_count` 계산과 완전히 동일한 패턴(위 "구현 참고"의 코드 스케치 참고). 템플릿은 이 두 키가 없어도 에러 없이 "연결된 뉴스가 없습니다"로 degrade.

**기업별 건수 Top 10 색상 범례 추가 (2026-07-10, PD, PM 확정)**

사용자가 "금융사·보험사·AI가 각각 기업이냐"고 혼동한 사례가 있었다. 원인은 미니바 색(금융사 파랑/보험사 청록/AI 보라)이 `org_type` 카테고리를 뜻한다는 설명이 카드 어디에도 없었기 때문 — 실제 랭킹 항목은 개별 기업명(토스, 신한은행 등)이다. 이를 해결하기 위해 카드 제목 아래, 랭킹 리스트 위에 색상 범례를 추가했다.

```
┌─ 기업별 건수 Top 10 ────────────┐
│ ● 금융사   ● 보험사   ● AI       │  ← 신규 범례
│ 1 토스        ▓▓▓▓▓▓▓▓░░  23건  │
│ 2 신한은행    ▓▓▓▓▓░░░░░  17건  │
│ ...                              │
└──────────────────────────────────┘
```

- **마크업**: 색 점(`span.w-1.5.h-1.5.rounded-full`) + `text-[10px] text-gray-400` 텍스트를 "금융사"/"보험사"/"AI" 3개 나열, `flex items-center gap-3`. 색 점 클래스는 미니바에 실제 쓰이는 클래스(`bg-blue-500`/`bg-teal`/`bg-primary`)를 그대로 재사용해 매핑이 어긋나지 않도록 했다.
- **노출 조건**: `org_ranking`이 있을 때만 표시(`{% if org_ranking %}` 블록 안). 데이터가 없는 empty state에는 범례를 넣지 않아 불필요한 잡음을 피한다.
- **톤**: 카드의 기존 보조 텍스트 크기(`text-[11px]`/`text-[10px]`)와 옅은 회색(`text-gray-400`) 규칙을 그대로 따라, 랭킹 리스트보다 시각적 위계가 낮게 보이도록 했다.

**일별 추이 차트 개선 (2026-07-10, PD, 사용자 피드백 — "라인차트가 이상하다")**

기존 인라인 SVG `<polyline>` 직선 그래프가 밋밋하고 꺾임이 부자연스럽다는 피드백을 반영해, `views.py`의 좌표 계산(`_build_daily_counts()`, `PAD_X`/`PAD_Y`/`VIEW_W`/`VIEW_H`, `day.x`/`day.y`)은 전혀 변경하지 않고 템플릿(SVG 마크업)만으로 다음을 추가했다.

1. **부드러운 곡선** — `<polyline>` 대신 `<path>` + 3차 베지어(`C`)로 전환. Catmull-Rom처럼 인접한 두 점의 y값을 평균 내는 방식이 아니라, **"수평 탄젠트" 방식**을 썼다: 각 구간의 제어점 x는 두 데이터포인트 x의 중간값, 제어점 y는 각자의 끝점 y와 동일 — 각 데이터포인트에서 접선이 수평이 되어 자연스럽게 이어진다. 이 방식을 쓴 이유: 7개 데이터포인트의 x좌표는 `PAD_X + i * (chart_w / 6)`로 **인덱스 기반 고정값**이라(데이터에 의존하지 않음) 중간값도 항상 같은 상수(20/63/107/150/193/237/280의 중간값 → 41.5/85/128.5/171.5/215/258.5)이므로, 뷰를 바꾸지 않고 템플릿에 리터럴로 박아 넣을 수 있었다. 반면 두 점의 y값을 평균 내는 전통적 Catmull-Rom 방식은 `day.y`가 매 요청마다 달라지는 동적 값이라 산술 연산이 필요해 Django 템플릿만으로는 불가능하다(템플릿 태그가 곱셈/나눗셈을 기본 지원하지 않는다는 기존 제약과 동일한 이유).
2. **라인 아래 그라데이션 영역 채움** — 위 곡선 경로를 그대로 그린 뒤 `L 280,90 L 20,90 Z`로 바닥(`y=90` = `PAD_Y+CHART_H`, 이미 뷰 상수와 동기화된 값)까지 닫아 `<linearGradient>`(보라 `#60269E`, opacity 0.18 → 0)로 채운다. 빈 여백처럼 보이던 카드 하단에 시각적 무게를 준다.
3. **기준 그리드라인** — `y=10`(100%)/`y=50`(50%) 점선 + `y=90`(0%, 바닥) 실선, 색상 `#EDEDED`/`#E5E5E5`. 값의 상대적 위치를 가늠할 기준선이 없던 문제를 보완.
4. **데이터포인트 호버 툴팁** — 각 점 위치에 투명 HTML 오버레이(`{% widthratio day.x 300 100 %}`/`{% widthratio day.y 100 100 %}`로 SVG 좌표를 %로 환산해 `left`/`top`에 배치, `{% widthratio %}`는 이미 값이 있는 `day.x`/`day.y`를 비율 변환만 하는 것이라 인덱스 기반 x좌표 계산과 달리 템플릿에서 처리 가능)를 겹쳐, 기업별 Top 10과 동일한 Alpine 호버 팝오버 패턴(`x-data`/`mouseenter`/`mouseleave`/`x-show x-cloak`, gap 0 배치)으로 `MM/DD · N건`을 보여준다. 점이 상단 절반(`pct >= 50`)이면 툴팁은 아래로(`top-full`), 하단 절반이면 위로(`bottom-full`) 열려 카드 밖으로 잘리지 않는다 — 기업별 카드의 순위 1~5/6~10 분기와 동일한 원리.
5. **`preserveAspectRatio="none"`은 유지** — 카드 폭에 맞춰 라인을 꽉 채우는 스파크라인의 표준 기법이며, 그 자체가 결함은 아니라고 판단했다. "이상해 보인다"는 인상의 실제 원인은 (1)직선 꺾임 (2)영역 채움 부재로 인한 시각적 무게감 부족 (3)기준선 부재였다고 보고, 위 1~4번으로 해결을 시도했다. `vector-effect="non-scaling-stroke"`는 비균등 스케일 상황에서도 선 굵기가 눌리지 않도록 계속 유지.

**PE에게 넘길 계산 공식 (참고용, 이번 변경에서는 사용 안 함 — views.py 수정 없이 템플릿만으로 해결했기 때문)**: 만약 향후 진짜 Catmull-Rom 스무딩(두 점 y의 가중 평균 기반 제어점)이 필요해지면, `_build_daily_counts()`에 아래처럼 각 점의 제어점 좌표(`cp1x`/`cp1y`/`cp2x`/`cp2y`)를 추가로 계산해 넘겨야 한다(템플릿에서 산술 불가하므로 뷰에서 미리 계산 — 위 "SVG 좌표 계산" 절과 동일한 이유).
```python
# tension은 곡률 강도(0~1), 점 i의 제어점은 이웃 점(i-1, i+1)의 기울기를 참고해 계산
# 이 프로젝트는 현재 "수평 탄젠트" 방식(뷰 변경 없음)으로 충분하다고 판단해 미적용.
```

**일별 추이 차트 축 개선(3차) (2026-07-10, PD, 사용자 피드백 — "x/y축이 안 보인다", "칸에 꽉 차게 해야 하는 거 아니냐")**

2차 개선(곡선/영역채움/그리드라인/툴팁)에도 불구하고 (1) 그리드라인만 있고 축 눈금 숫자가 없어 "차트처럼" 안 읽히고, (2) 건수 숫자 행·날짜 라벨 행이 SVG 바깥의 별도 flex 행이라 실제 데이터포인트 x좌표와 라벨 위치가 픽셀 단위로 맞지 않으며, (3) 좌우 패딩(`PAD_X=20`, 300 기준 약 6.7%씩)이 커서 카드 안에서 차트가 꽉 차 보이지 않는다는 피드백을 받았다. 이번엔 `views.py`를 건드리지 않고 **템플릿(SVG 마크업)만** 다시 짰고, 실제 좌표 계산이 이 새 마크업과 맞으려면 `views.py`가 어떻게 바뀌어야 하는지 정확한 스펙을 아래에 남긴다(PE 적용 전까지는 화면이 어긋나 보일 수 있음 — 이는 예상된 상태).

1. **y축 신설** — 왼쪽에 세로 축선(`x=16, y=8~82`)을 긋고, 0선(`y=82`)과 만나 L자 프레임을 이룬다. 축선 옆에 최댓값/중간값/0 세 개의 눈금 숫자를 SVG `<text>`로 배치(`text-anchor="end"`로 축선에 오른쪽 정렬). 최댓값은 신규 컨텍스트 변수 `daily_max_count`를 그대로 출력하고, 중간값은 `widthratio daily_max_count 2 1` 태그로 뷰 변경 없이 나눗셈(`daily_max_count / 2`, 반올림)만으로 구했다.
2. **x축을 데이터와 같은 좌표계로 통합** — 기존에 SVG 바깥 별도 `<div>` flex 행으로 표시하던 `MM/DD` 날짜 라벨을 SVG 내부 `<text>`로 옮겨, 각 텍스트의 `x` 값을 해당 데이터포인트의 `day.x`와 동일하게 맞췄다(`text-anchor="middle"`). 0선(`y=82`)에서 아래로 짧게 내려긋는 눈금선(`y=82→86`)을 각 `day.x` 위치마다 그려 라벨과 그리드를 시각적으로 연결했다 — "이 라벨이 이 축이다"라는 요구사항을 여기서 만족.
3. **건수 숫자 행(7개) → y축 눈금으로 압축** — SVG 위에 별도로 떠 있던 "건수 숫자 7개" 행은 제거하고, 그 정보를 y축의 0/중간/최댓값 눈금으로 압축 대체했다. 각 지점의 정확한 건수는 기존 호버 툴팁(`MM/DD · N건`)으로 계속 확인 가능해 정보 손실은 없다 — 축(스케일 파악용) + 툴팁(정확한 값 확인용) 역할을 분리한 것. 이 정리로 카드 세로 공간도 확보했다(2번 요구사항).
4. **비대칭 패딩으로 여백 축소** — `PAD_X`/`PAD_Y`(대칭) 대신 `PAD_LEFT=16`/`PAD_RIGHT=6`/`PAD_TOP=8`/`PAD_BOTTOM=18`(비대칭)으로 재설계했다. 좌우 패딩 합은 기존 40(300 기준 13.3%)에서 22(7.3%)로 줄여 곡선/그리드가 카드 가로폭을 훨씬 더 채운다. 상하 패딩은 y축 눈금(위쪽 8) + x축 눈금선·날짜 라벨(아래쪽 18)이 실제로 그 공간을 차지하도록 재배분했다(빈 여백이 아니라 축 정보로 채워짐). SVG 컨테이너 높이도 `h-20`(80px)에서 `h-28`(112px)로 늘려, 이전에 SVG 바깥에 별도로 있던 건수 행(~18px)+날짜 행(~14px)이 차지하던 세로 공간을 SVG 자체에 흡수시켰다 — 카드 안에서 여러 조각으로 나뉘어 있던 것을 "하나의 차트"로 통합해 "칸에 꽉 차 보이는" 인상을 준다.
5. **`aria-hidden="true"` 제거** — 이전엔 SVG 바깥의 HTML 텍스트(건수 행/날짜 행)가 접근성 정보를 담당해 SVG 자체는 장식으로 숨겨도 됐지만, 이번에 축 숫자·날짜 라벨을 모두 SVG 내부로 옮기면서 SVG가 유일한 정보 전달 수단이 됐다. 스크린리더가 이 텍스트를 읽을 수 있도록 `aria-hidden` 속성을 뺐다.
6. **곡선/영역채움/베지어 제어점 리터럴 재계산** — 새 x좌표(16/62/109/155/201/248/294)에 맞춰 베지어 제어점(두 점 x의 중간값: 39/85.5/132/178/224.5/271)과 영역 채움의 바닥 닫기 좌표(`y=82`, 이전 `y=90`)를 다시 계산했다. 곡선 기법("수평 탄젠트") 자체는 2차 개선과 동일, 좌표값만 새 패딩에 맞게 갱신.

**PE 작업 스펙 (필수 — 이 갱신 없이는 화면 좌표가 어긋남)**

- `_build_daily_counts()`의 `PAD_X`/`PAD_Y` 상수를 `PAD_LEFT=16`/`PAD_RIGHT=6`/`PAD_TOP=8`/`PAD_BOTTOM=18`로 교체하고, `CHART_W = VIEW_W - PAD_LEFT - PAD_RIGHT`(=278), `CHART_H = VIEW_H - PAD_TOP - PAD_BOTTOM`(=74)로 재계산. `x`/`y` 산식은 위 "구현 참고" 절의 코드 블록 그대로.
- `dashboard()` 뷰의 최상위 컨텍스트에 `daily_max_count`(int, 7일 중 최댓값)를 추가. `_build_daily_counts()` 내부에 이미 있는 `max_count` 지역변수를 반환값에 포함하거나(예: 튜플로 반환), 별도 헬퍼로 다시 계산해도 무방 — PE 판단.
- 템플릿은 이미 새 스펙(비대칭 패딩·`daily_max_count`)을 전제로 작성 완료(`templates/dashboard/index.html`). `daily_max_count`가 없어도 빈 문자열로 렌더링될 뿐 에러는 안 나므로, 이 스펙 적용 전에도 500 에러 없이 배포 가능(단 y축 숫자가 비어 보임 — 임시 상태).

**일별 추이 차트 시각 버그 수정(4차) (2026-07-10, PD, 사용자가 실제 렌더링 스크린샷으로 지적한 시각적 버그 2건)**

렌더링된 스크린샷 기준으로 두 가지 시각 버그와, 축 기준일이 모호하다는 지적이 있어 템플릿만으로 고쳤다(`views.py` 변경 없음).

1. **카드 높이의 절반만 차트가 채움** — 원인은 "핵심 지표" 3-column 그리드(`grid grid-cols-3 gap-4`)의 기본 `align-items: stretch`로 카드(`<div class="bg-white ... p-5">`) 자체는 옆의 긴 "기업별 Top 10" 리스트 카드와 같은 높이로 늘어나지만, 카드 안쪽 SVG가 고정 높이(`h-28`, 112px)로 박혀 있어 그 아래로 빈 여백이 남았던 것. 카드를 `flex flex-col h-full`로 바꾸고, 제목+"발행일 기준" 라벨은 `shrink-0`로 상단 고정, 차트를 감싸는 `<div class="relative">`는 `flex-1 min-h-0`로 남은 세로 공간을 전부 차지하도록 했다(`min-h-0`은 flex item의 기본 `min-height: auto`가 내용 높이만큼 강제로 늘어나는 것을 막기 위해 필요). SVG도 `h-28` 대신 `h-full`로 바꿔 이 컨테이너에 맞춰 늘어나게 했다. 데이터 없는 empty state도 동일하게 `flex-1`로 감싸 카드 안에서 세로 중앙 정렬되도록 함께 손봤다.
2. **데이터포인트 원이 타원으로 보임** — 원인은 `<svg viewBox="0 0 300 100" preserveAspectRatio="none">`이 3:1 비율의 viewBox를 카드의 실제 렌더링 박스(가로/세로 비율이 다름)에 맞춰 가로·세로를 **다른 배율로 강제로 늘리기** 때문에, SVG 좌표계 안에서는 완벽한 원(`<circle r="2.5">`)이라도 화면에는 눌린 타원으로 보였다. `vector-effect="non-scaling-stroke"`는 테두리 두께만 고정할 뿐 도형 자체의 비율 왜곡은 막지 못해 근본 해결이 안 됐다. 해결책은 점을 SVG `<circle>`로 그리지 않고, 이미 있던 호버 트리거 오버레이(`{% widthratio day.x 300 100 %}`/`{% widthratio day.y 100 100 %}`로 SVG 좌표를 %로 환산해 `left`/`top`에 배치하는 절대 위치 `<div>`) 안에 `rounded-full` `<span>`을 넣는 것 — HTML/CSS 원은 실제 픽셀 단위 정사각형(`w-1.5 h-1.5` 또는 오늘 지점 `w-2.5 h-2.5`)이라 SVG의 비균등 스케일링과 무관하게 항상 정원으로 보인다. 시각적으로 보이는 점과 호버 트리거가 이전엔 SVG circle(시각) + 별도 투명 div(호버)로 이중 구조였는데, 이번에 하나의 요소로 합쳤다. SVG 쪽에는 `<circle>` 루프 자체를 제거했다.
3. **"발행일 기준" 라벨 추가** — 사용자가 "이 차트가 발행일 기준인지 수집일 기준인지 헷갈린다"고 지적. 실제로는 `_build_daily_counts()`가 `News.published_at__date`로 집계하므로 발행일 기준이다(수집일 `created_at`이 아님). 카드 제목("일별 뉴스 건수 추이") 옆에 작은 회색(`text-gray-400`) 텍스트로 "발행일 기준"을 붙여 명시했다 — 별도 줄을 차지하지 않고 제목과 같은 줄(`flex items-baseline gap-2`)에 배치해 과하지 않게 처리.

`preserveAspectRatio="none"`(카드 폭에 맞춰 라인을 꽉 채우는 스파크라인 표준 기법) 자체와 곡선/그리드라인/툴팁 등 나머지 구조는 3차 개선안 그대로 유지 — 이번 수정은 카드 레이아웃(flex 전환)과 데이터포인트 렌더링 방식(HTML dot)에 국한된다.

**일별 추이 차트 시각 버그 수정(5차) (2026-07-10, PD, 사용자 피드백 — "발행일 기준 텍스트 제거", "텍스트가 너무 크게 보이고 해상도가 깨져 보인다")**

1. **"발행일 기준" 라벨 제거** — 4차에서 카드 제목 옆에 붙였던 `<span class="text-[11px] text-gray-400">발행일 기준</span>`을 사용자 피드백으로 제거했다. 집계 기준(`News.published_at`)은 여전히 발행일 기준이지만, 화면에 별도 보조 텍스트로 표기하지는 않는다.
2. **SVG `<text>` 요소를 전부 HTML 오버레이로 이전** — 4차에서 카드를 `flex flex-col h-full`로 바꿔 옆 "기업별 Top 10" 카드와 높이를 맞추면서(좋은 방향이었음) 카드가 세로로 길게 늘어나는 경우가 생겼는데, SVG는 여전히 `viewBox="0 0 300 100"` + `preserveAspectRatio="none"`이라 컨테이너의 실제 가로/세로 비율에 맞춰 가로·세로를 **다른 배율로 강제로 늘린다**. 카드가 세로로 길어질수록 세로 방향 확대 배율이 커지는데, SVG 안의 `<text>`(y축 눈금 숫자 3개, x축 날짜 라벨 7개, `font-size="7"`)는 이 비균등 스케일링을 그대로 받아 세로로 늘어난 채 렌더링된다 — "글자가 커 보이고 뭉개져 보인다(해상도 깨짐)"는 원인. `vector-effect="non-scaling-stroke"`는 선 굵기만 보호할 뿐 텍스트 글리프 자체의 왜곡은 막지 못한다. 4차에서 데이터포인트 원(`<circle>`)이 타원으로 찌그러지던 문제와 근본 원인이 완전히 동일하다 — 그때는 원을 SVG 밖 HTML/CSS 오버레이(`rounded-full` `<span>`)로 옮겨 해결했는데, 이번엔 같은 처방을 텍스트에도 적용했다.
   - **y축 눈금 숫자(최댓값/중간값/0)**: SVG `<text x="13" y="11|48|85">`를 제거하고, `left: {% widthratio 13 300 100 %}%; top: {% widthratio 8|45|82 100 100 %}%;`로 위치를 잡은 `<span class="absolute -translate-x-full -translate-y-1/2">` 3개로 대체했다. `x=13`/`y=8·45·82`는 데이터(`daily_counts`)와 무관한 SVG viewBox 상의 고정 상수(그리드라인 좌표와 동일)라 `widthratio`에 리터럴을 그대로 넣어 정적으로 %를 계산한다. `-translate-x-full`이 기존 `text-anchor="end"`를, `-translate-y-1/2`가 텍스트 세로 중앙 정렬을 대신한다.
   - **x축 날짜 라벨(7개)**: SVG `<text x="{{ day.x }}" y="94">`를 제거하고, 기존 데이터포인트 원 오버레이와 동일한 `{% widthratio day.x 300 100 %}%` 좌표 변환을 재사용해 `<span class="absolute -translate-x-1/2 -translate-y-1/2">`로 대체했다(`top`은 고정값 `{% widthratio 94 100 100 %}%`). `-translate-x-1/2`가 기존 `text-anchor="middle"`을 대신하고, 오늘 지점 강조(진한 보라 + 굵게)는 기존 `fill` 삼항 분기를 Tailwind `text-primary font-bold` vs `text-gray-400 font-normal` 클래스 삼항 분기로 그대로 옮겼다.
   - **SVG에는 순수 도형만 남음** — 그리드라인·y축 세로 축선·x축 눈금선·곡선(`<path>`)·그라데이션 영역 채움만 남고, 사람이 읽는 글자는 전부 HTML이 된다. SVG가 더 이상 정보를 전달하지 않으므로 `aria-hidden="true"`를 다시 붙였다(3차에서 축 숫자·날짜 라벨을 SVG로 옮기며 뺐던 속성을 원복).
   - `apps/dashboard/views.py`의 좌표 계산(`day.x`/`day.y`, `daily_max_count`)은 변경하지 않았다 — 이번 수정은 이미 계산된 좌표값을 어디에(SVG `<text>` vs HTML `<span>`) 렌더링하느냐만 바꾼 것이라 뷰 변경이 필요 없다.

**기간 필터 + 뉴스 건수 추이 차트 가변화 (2026-07-27, PD, PM 정책 기반 — `docs/planning.md` "대시보드·지식그래프 공통 기간 필터 정책" 절)**

PM이 확정한 대시보드 공통 기간 필터(전체/최근 30일/최근 7일)를 "핵심 지표" 섹션에 도입했다. 이 필터가 "일별 뉴스 건수 추이" 카드의 데이터포인트 개수를 7개 고정에서 가변으로 바꾸기 때문에, 기존에 7개 포인트 전제로 템플릿에 하드코딩돼 있던 베지어 제어점 좌표(39/85.5/132/178/224.5/271 등)를 이번에 완전히 걷어냈다. `templates/dashboard/index.html`은 이미 새 스펙으로 재작성했고(변경 없이는 렌더링되지 않음 — 뷰가 아래 스펙대로 컨텍스트를 채워야 화면이 맞게 나온다), 이 절은 그 스펙을 PE에게 정확히 인계하기 위한 것이다.

1. **기간 셀렉터 마크업** — 카드별이 아니라 "핵심 지표" 섹션 제목 옆에 하나만 둔다(기존 "최근 7일" pill 배지 위치를 대체). `전체`/`최근 30일`/`최근 7일` 3개 `<a href="?period=...">` 링크를 `bg-gray-100 rounded-full p-0.5` 캡슐 안에 pill 토글로 배치, 활성 옵션은 `bg-primary text-white`, 비활성은 `text-gray-500 hover:text-gray-700`. **순수 GET 링크 + 전체 페이지 리로드**로 구현했다 — 이 프로젝트에 아직 hx-get 기반 필터 갱신 패턴이 없고(기존 `hx-*`는 전부 `hx-post` 폼 조작, 예: `news/_orgs.html`의 기업 추가/삭제), 뉴스 목록(`news/list.html`)의 필터·페이지네이션(`news/_list.html`)도 동일하게 순수 GET 링크로 처리하는 게 이 프로젝트의 기존 관례다. 데이터 규모가 작아 부분 스왑으로 얻는 체감 이득보다 새 인터랙션 패턴(전용 HTMX partial 뷰 등)을 도입하는 비용이 크다고 판단해 기존 관례를 따랐다. 기본값은 최근 7일(PM 확정 — `docs/planning.md` "대시보드 핵심 지표 기본값 = 최근 7일" 근거: 현재 동작 유지 + 빈 구간 없이 채워지는 첫인상 보장).
2. **`period` 파라미터·`start_date`/`today` 계산** — 뷰는 `request.GET.get("period", "7d")`를 읽고 `{"all", "30d", "7d"}` 외 값(빈 값·오타 포함)은 `"7d"`로 취급한다(폴백). 오늘(`today`)은 기존과 동일하게 `timezone.localtime(timezone.now()).date()`. 각 옵션의 `start_date`(`None`이면 하한 없음):
   - `"7d"` → `start_date = today - timedelta(days=6)` (기존과 동일)
   - `"30d"` → `start_date = today - timedelta(days=29)`
   - `"all"` → `start_date = None` (`org_ranking`/`tech_topic_counts` 집계에는 날짜 하한 없이 전체 `News`를 그대로 쓴다 — 위 "구현 참고" 절의 2026-07-27 추가 메모 참고). 단 아래 3번 버킷 계산을 위해 `earliest_date = News.objects.aggregate(Min("published_at"))`로 전체 데이터의 최초 발행일을 별도로 구해야 한다(News가 하나도 없으면 `earliest_date = today`로 폴백).
   - 기준 필드는 여전히 `News.published_at`(수집일 `created_at` 아님, 기존과 동일).
3. **버킷 단위 결정 (`bucket_unit`)** — `"7d"`/`"30d"`는 **일 단위**(day), `"all"`은 **주 단위**(week) 또는 **월 단위**(month)다. `total_days = (today - earliest_date).days + 1`을 기준으로: `total_days <= 364`면 `bucket_unit = "week"`(버킷 크기 7일), 아니면 `bucket_unit = "month"`(버킷 크기 30일) — PM 정책의 "전체 → 주 단위(일 단위면 점이 무한정 늘어남); 기간이 아주 길어지면 월 단위까지 고려"를 그대로 구현한 것. 임계값 364일(=52주)은 "주 단위로 그렸을 때 포인트가 카드 폭에 감당 가능한 최대치" 기준으로 PD가 잡은 값이며, 실사용 데이터로 너무 빽빽하거나 헐겁다고 확인되면 조정 가능(PD 재량 사유 없이 PE가 임의로 바꾸지 말 것 — 바뀌면 디자인 검토 필요).
   - **버킷 경계는 "오늘부터 거꾸로" 굴린다(캘린더 ISO 주가 아님)** — `bucket_size`(7 또는 30일) 단위로 오늘부터 과거로 롤링 윈도우를 만든다: `bucket[i].end = today - i*bucket_size`, `bucket[i].start = bucket[i].end - (bucket_size-1)`. `i=0,1,2...`로 늘리다가 `bucket[i].end < earliest_date`가 되면 멈춘다(그 버킷까지 포함). 이후 `list.reverse()`로 과거→오늘 순서로 뒤집는다. Django `TruncWeek`(월요일 기준 등 로케일에 따라 기준일이 달라질 수 있음) 대신 이 방식을 쓴 이유는 (a) 일 단위 버킷과 동일한 "오늘 기준 역산" 방법론을 유지해 두 코드 경로가 갈라지지 않고, (b) 데이터포인트의 마지막 값이 항상 "오늘을 포함한 가장 최근 구간"이 되는 것을 보장하기 위함(캘린더 주 경계를 쓰면 마지막 버킷이 오늘보다 며칠 전에 끝날 수 있음).
   - 버킷별 건수는 **단일 쿼리로 얻은 일별 카운트 맵**(`TruncDate` group-by, 기존 `_build_daily_counts()`가 이미 하던 방식)을 버킷 범위만큼 합산해서 구한다 — 버킷 단위가 바뀌어도 DB 쿼리는 하나로 유지되고, 파이썬에서 날짜 range를 순회하며 합산만 하면 된다(추가 쿼리 없음).
4. **`trend_points` 필드 스펙 (기존 `daily_counts` 대체, 이름 변경)** — dict 리스트, 개수(`N`)는 버킷 단위에 따라 7 / 30 / 가변(주 또는 월 버킷 수). 각 dict의 키:
   - `label`(str) — x축 짧은 라벨. 일 버킷은 `"MM/DD"`(기존과 동일), 주/월 버킷은 **버킷 시작일**의 `"MM/DD"`("이 주/달이 언제부터 시작하는가"로 읽는다).
   - `range_label`(str) — 호버 툴팁용 상세 라벨. 일 버킷은 `label`과 동일한 값. 주/월 버킷은 `"MM/DD~MM/DD"`(버킷 시작~끝).
   - `count`(int), `pct`(int, 0~100, 버킷 내 최댓값 대비 — `_pct()` 재사용, 계산 로직 동일).
   - `is_current`(bool) — **마지막 포인트(`i == N-1`)만 `True`**. 기존 `is_today`(날짜가 정확히 오늘인 포인트)를 대체한다 — 주/월 버킷에서는 "오늘"이 버킷 중간에 있을 뿐 버킷 경계 날짜와 일치하지 않으므로, "가장 최근 구간"이라는 의미로 일반화했다.
   - `x`(int), `y`(int) — SVG 좌표. `x = round(PAD_LEFT + i * (CHART_W / (N-1)))`(`N > 1`일 때), `N == 1`이면 `x = round(PAD_LEFT + CHART_W / 2)`(중앙, 데이터가 1버킷뿐인 극단적 초기 상태 대비 — 예: 서비스 시작 직후 "전체"를 눌렀는데 데이터가 며칠치뿐인 경우). `y` 공식은 기존과 동일(`y = round(PAD_TOP + CHART_H - (pct / 100 * CHART_H))`), `PAD_LEFT=16`/`PAD_RIGHT=6`/`PAD_TOP=8`/`PAD_BOTTOM=18`/`VIEW_W=300`/`VIEW_H=100`/`CHART_W=278`/`CHART_H=74` 상수는 전부 기존 값 그대로 유지(변경 없음).
   - `show_label`(bool) — x축 라벨(및 짝을 이루는 눈금선)을 이 포인트에 그릴지 여부. `interval = max(1, round(N / 6))`로 계산해 `(i % interval == 0) or (i == N-1)`이면 `True`. `N=7`(최근 7일)이면 `interval=1`이라 기존과 동일하게 전부 표시되고(하위 호환), `N=30`(최근 30일)이면 `interval=5`라 대략 5일 간격으로만 표시된다 — PM이 제시한 "5~7개 간격으로만 라벨" 예시와 부합.
   - `has_trend_data`(bool, 리스트가 아니라 최상위 컨텍스트 변수) — 기존 `has_daily_data`를 대체. `trend_max_count > 0`일 때만 `True`(빈 상태 판정 로직은 기존과 동일, 이름만 변경).
   - `trend_max_count`(int, 최상위 컨텍스트 변수) — 기존 `daily_max_count` 대체. 버킷 중 최댓값.
   - `bucket_unit`(str: `"day"`/`"week"`/`"month"`, 최상위 컨텍스트 변수, 신규) — 카드 제목("일별"/"주별"/"월별" 뉴스 건수 추이)을 동적으로 바꾸는 데 쓰인다. PM 정책이 예약해 뒀던 "일/주 단위 토글"은 기간 선택이 버킷 단위를 자동으로 결정하므로 별도 토글 없이 이 방식으로 흡수한다.
   - `period`(str: `"all"`/`"30d"`/`"7d"`, 최상위 컨텍스트 변수, 신규) — 셀렉터의 활성 옵션 표시(`{% if period == '...' %}`)에 쓰인다.
5. **`trend_line_path` / `trend_area_path` (신규, 경로 문자열 자체를 뷰에서 계산)** — 기존엔 7개 고정 포인트를 전제로 베지어 제어점 좌표를 템플릿에 리터럴로 박아 넣었지만, 포인트 개수가 가변이 되면서 이 방식이 성립하지 않는다. "SVG 좌표는 템플릿이 아니라 뷰에서 계산한다"는 이 카드의 기존 원칙(위 "구현 참고" 절)을 경로 문자열 자체까지 확장해, 뷰가 완성된 SVG `<path>` `d` 속성값을 문자열로 만들어 넘긴다. 곡선 기법("수평 탄젠트" — 각 데이터포인트에서 접선이 수평이 되도록 제어점 y는 끝점 y와 동일, 제어점 x는 두 점 x의 중간값)은 기존과 동일하게 유지한다 — 폴리라인(직선)으로 단순화하는 대안도 검토했으나, 좌표 계산이 이미 전부 뷰로 넘어간 구조에서는 곡선 경로를 만드는 것도 같은 복잡도이므로 시각 품질을 낮출 이유가 없다고 판단했다. 임의 개수 `N`의 포인트에 대한 일반화 공식:
   ```python
   def _build_trend_line_path(points):
       # "수평 탄젠트" 3차 베지어를 N개 포인트로 일반화. points는 x/y가 이미 채워진 딕셔너리 리스트.
       d = f"M {points[0]['x']},{points[0]['y']}"
       for i in range(1, len(points)):
           x0, y0 = points[i - 1]["x"], points[i - 1]["y"]
           x1, y1 = points[i]["x"], points[i]["y"]
           cx = (x0 + x1) / 2
           d += f" C {cx},{y0} {cx},{y1} {x1},{y1}"
       return d

   def _build_trend_area_path(points, line_path, baseline_y=82):
       # baseline_y = PAD_TOP + CHART_H (기존 상수와 동일한 82, 뷰 상수 변경 시 함께 갱신)
       first_x, last_x = points[0]["x"], points[-1]["x"]
       return f"{line_path} L {last_x},{baseline_y} L {first_x},{baseline_y} Z"
   ```
   `N == 1`인 극단적 케이스(예: 전체 기간인데 데이터가 1버킷뿐)에는 `trend_line_path`가 `"M x,y"` 하나뿐이라 실제로 그려지는 선이 없고(점 하나), `trend_area_path`도 폭 0의 퇴화된 도형이 된다 — 에러는 나지 않으며, 시각적으로는 dot 하나만 보이는 정상적인 graceful degradation이다.
6. **카드 제목 동적 전환** — "일별 뉴스 건수 추이" 고정 문구를 `bucket_unit`에 따라 "일별"/"주별"/"월별"로 자동 전환한다(템플릿 `{% if %}` 분기, 뷰 변경 불필요). 별도의 일/주 토글 UI는 두지 않는다(위 4번 `bucket_unit` 설명 참고).
7. **dot/호버 히트박스 크기 축소 (템플릿 전용, 뷰 변경 없음)** — 포인트 개수가 15개를 넘으면(예: 최근 30일=30개) dot과 호버 트리거 박스가 서로 겹치지 않도록 한 단계 작게 그린다(`w-2.5 h-2.5`/`w-1.5 h-1.5` vs 기존 `w-4 h-4`/`w-2.5 h-2.5`). `trend_points|length` 템플릿 필터만으로 판단 가능해 뷰의 새 컨텍스트 변수는 필요 없다.
8. **카드2/3(기업별 Top10, 기술주제별) 영향** — 구조 변경 없음. 두 카드는 시계열이 아닌 기간 누적 집계라, 집계 쿼리의 날짜 하한을 `start_date`(위 2번)로 바꾸기만 하면 된다(위 "구현 참고" 절의 2026-07-27 추가 메모 — `period == "all"`이면 하한 없이 전체 집계). PE 작업량이 카드1(뉴스 건수 추이)에 비해 훨씬 작다.
9. **PE 작업 스펙 요약 (필수)**
   - `dashboard()` 뷰: `request.GET.get("period", "7d")` 읽고 검증(위 2번), `start_date`/`today`/`bucket_unit`/`earliest_date`(all일 때만) 계산.
   - `_build_daily_counts()`를 `_build_trend_points(start_date, today, bucket_unit)`로 대체(또는 이름을 유지하고 내부 로직만 교체 — PE 판단). 반환값: `trend_points`(리스트), `trend_max_count`(int). 내부적으로 (a) 단일 쿼리로 일별 카운트 맵을 구하고, (b) `bucket_unit`에 따라 버킷 경계를 구성(위 3번), (c) 버킷별 합산, (d) `x`/`y`/`show_label`/`is_current`/`label`/`range_label` 계산(위 4번), (e) `trend_line_path`/`trend_area_path` 생성(위 5번).
   - `_build_org_ranking()`/`_build_tech_topic_counts()`: `start_date`가 `None`일 수 있으므로 `date_filter` Q 구성을 조건부로 변경(위 "구현 참고" 절 2026-07-27 메모).
   - `dashboard()` 뷰 최상위 컨텍스트에 `period`/`bucket_unit`/`trend_points`/`trend_max_count`/`has_trend_data` 추가, 기존 `daily_counts`/`daily_max_count`/`has_daily_data`는 제거(템플릿이 더 이상 참조하지 않음).
   - 템플릿(`templates/dashboard/index.html`)은 이미 새 변수명·구조로 작성 완료됐다 — 위 컨텍스트가 채워지지 않으면 `{{ }}` 출력이 비거나 `{% if %}` 분기가 empty state로 빠질 뿐 500 에러는 나지 않는다(기존 관례와 동일하게 안전한 degrade).

**카드별 데이터·기준 툴팁 적용 (2026-07-31, PD, 데모 피드백 축 3 — PM 통합 계획 채택안)**

위 "1. 디자인 시스템 › 1.5 컴포넌트 정의 › Info Tooltip"을 대시보드 5개 카드 제목 옆에 배치한다.
문구는 `apps/dashboard/views.py`의 실제 집계 로직을 검증해 사실만 기술했다(추측·과장 없음, 아래
문구 외의 기준을 임의로 덧붙이지 않는다).

| 카드 | 트리거 위치 | 딕셔너리 키(제안) | 문구 |
|---|---|---|---|
| ① 일별 뉴스 건수 추이 | 동적 `<h3>`(일별/주별/월별 뉴스 건수 추이) 텍스트 옆 | `dashboard.trend` | "뉴스 발행일(수집일 아님) 기준으로 집계합니다. 최근 7일·30일은 일 단위, 전체 기간은 364일 이하면 주 단위, 그보다 길면 월 단위로 묶어서 보여줍니다." |
| ② 기업별 건수 Top 10 | `<h3>기업별 건수 Top 10</h3>` 옆 | `dashboard.org_ranking` | "활성 상태인 기업 중 선택한 기간에 발행된 뉴스 건수가 많은 순으로 상위 10개를 보여줍니다. 비활성 기업은 집계에서 제외됩니다." |
| ③ 기술 주제별 언급 건수 | `<h3>기술 주제별 언급 건수</h3>` 옆 | `dashboard.tech_topic` | "활성 상태인 기술 주제 중 선택한 기간에 언급된(중복 제거) 뉴스 건수가 많은 순으로 상위 10개를 보여줍니다." |
| ④ 주요 이슈 | `<h2>주요 이슈</h2>` 옆 | `dashboard.insights` | "리서치 애널리스트가 작성한 이슈를, 근거로 연결된 뉴스 중 가장 최근에 발행된 기사 순으로 정렬해 상위 8건을 보여줍니다. 이슈를 작성한 시각이 아니라 근거 기사의 최신성 기준입니다." |
| ⑤ 최신 뉴스 | `<h2>최신 뉴스</h2>` 옆(우측 "전체 보기" 링크보다 왼쪽) | `dashboard.latest_news` | "발행일이 최신인 순으로 상위 10건을 보여줍니다. 상단의 기간 필터와 무관하게 항상 전체 뉴스 중 최신순입니다." |

**템플릿 반영 지점 (`templates/dashboard/index.html`, PE 작업)** — 현재 각 제목이 아이콘을 끼워
넣을 flex 래퍼가 없는 곳이 있어, 아이콘 삽입 시 함께 손볼 지점을 명시한다.

1. **일별 뉴스 건수 추이** — 바깥 `<div class="flex items-baseline gap-2 mb-4 shrink-0">`는
   그대로 두고(다른 요소가 `items-baseline`에 의존할 수 있어 건드리지 않는다), `<h3>` 내부를
   `inline-flex items-center gap-1.5`로 감싸 아이콘만 로컬로 수직 중앙 정렬한다:
   ```html
   <h3 class="text-sm font-semibold text-gray-900 inline-flex items-center gap-1.5">
     <span>{% if bucket_unit == 'week' %}주별{% elif bucket_unit == 'month' %}월별{% else %}일별{% endif %} 뉴스 건수 추이</span>
     {% info_tooltip "dashboard.trend" label="뉴스 건수 추이" %}
   </h3>
   ```
2. **기업별 건수 Top 10** — 기존 `<h3 class="text-sm font-semibold text-gray-900 mb-4">기업별 건수 Top 10</h3>`을:
   ```html
   <h3 class="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-1.5">
     기업별 건수 Top 10
     {% info_tooltip "dashboard.org_ranking" label="기업별 건수 Top 10" %}
   </h3>
   ```
3. **기술 주제별 언급 건수** — 2번과 동일한 방식(`flex items-center gap-1.5` 추가 + 아이콘).
4. **주요 이슈** — 기존 `<div class="flex items-center mb-4"><h2 ...>주요 이슈</h2></div>`을:
   ```html
   <div class="flex items-center gap-1.5 mb-4">
     <h2 class="text-sm font-semibold text-gray-900">주요 이슈</h2>
     {% info_tooltip "dashboard.insights" label="주요 이슈" %}
   </div>
   ```
5. **최신 뉴스** — 기존 `<div class="flex items-center justify-between mb-4">`가 `<h2>`와
   "전체 보기" 링크를 양끝 정렬하고 있으므로, `<h2>`만 별도 flex로 한 번 더 감싸 아이콘을
   제목 바로 옆에 붙이고 "전체 보기"는 계속 오른쪽 끝에 남긴다:
   ```html
   <div class="flex items-center justify-between mb-4">
     <h2 class="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
       최신 뉴스
       {% info_tooltip "dashboard.latest_news" label="최신 뉴스" %}
     </h2>
     <a href="{% url 'news_list' %}" class="text-xs text-primary hover:underline">전체 보기</a>
   </div>
   ```

**PE 구현 체크리스트**
- `x-cloak`을 팝오버 `x-show` 요소에 반드시 함께 붙인다 — 누락 시 FOUC(Flash Of Unstyled
  Content) 버그(뉴스 상세 "기업 추가" 드롭다운에서 발견돼 로그·기업관리 탭 등 총 3곳에서
  수정된 전례가 있는 바로 그 패턴). 이번에 5곳을 새로 추가하므로 5곳 모두 점검.
- 문구는 위 표의 5개 텍스트 그대로 사용한다(각색·요약·과장 금지 — PM이 코드로 검증한 사실).
- 문구를 템플릿에 직접 쓰지 말고 딕셔너리 1곳에서 관리하고, 마크업은 재사용 컴포넌트 1개로
  통일한다(위 "1.5 Info Tooltip" 절의 "재사용 방법" 참고) — 5곳에 마크업을 복붙하지 않는다.
- 접근성: 버튼에 `aria-label`, `:aria-expanded`, `@keydown.escape` 반드시 포함. 마우스 호버뿐
  아니라 클릭(터치)·키보드로도 열고 닫을 수 있어야 한다.
- 이번 스코프는 대시보드 5개 카드에 한정한다. 다른 화면(SET-*, NEWS-*, REPORT-*, GRAPH-001)은
  이번에 신규 화면 ID를 만들지 않으며, 나중에 필요해지면 이미 만들어진 컴포넌트를 재사용하고
  딕셔너리에 문구만 추가하면 된다(PM 통합 계획서의 "이후 화면은 문구만 추가" 방향과 일치).

**변경 이력 (2026-07-10, PD)**

- PM이 `docs/planning.md`에 확정한 정량화 축 Phase A 3개 지표(일별 추이/기업유형별/기업별 Top10)를 "핵심 지표" 로우로 추가. 기존 "주요 이슈 + 최신 뉴스" 로우 위에 배치.
- 기존 와이어프레임에 있던 "요약 지표 4-column"과 "최근 인사이트 와이드 카드" 로우는 실제 `templates/dashboard/index.html`에 구현된 적이 없어 삭제하고, 실제 구조(주요 이슈 아코디언 확장형 + 최신 뉴스)로 와이어프레임을 갱신. 이슈 아코디언 확장 UX는 `docs/planning.md` 58-64행("읽기 깊이 문제") 근거.
- "기업별 건수 Top 10" 기업명 호버 시 관련 뉴스 팝오버 추가(위 상세 참고). PM 없이 순수 인터랙션 개선으로 처리(우선순위 판단 불필요).
- **(배치 2, PM 확정) "일별 뉴스 건수 추이" 막대그래프 → 라인그래프(인라인 SVG `<polyline>`) 전환**, **"기업유형별 건수" 카드 완전 제거**, **"기술 주제별 언급 건수" 카드 신규 추가**. 최종 3장 구성은 일별 추이(라인) → 기업별 Top 10 → 기술주제별 순. 배치 순서 근거: 왼쪽은 시계열 개관(추이), 가운데는 이미 검증된 성숙한 기능(팝오버 포함 기업별 Top 10)을 배치해 핵심 동선을 지키고, 오른쪽은 이번에 새로 생긴 `TechTopic` 데이터(현재 10개 시드 중 4개만 1건 이상)를 배치해 아직 데이터가 성긴 신규 지표가 시선이 먼저 닿는 자리(왼쪽/가운데)를 차지하지 않도록 함.
- **(배치 3, 사용자 피드백)** "일별 뉴스 건수 추이" `<polyline>` → `<path>`(수평 탄젠트 베지어 곡선) 전환, 라인 아래 그라데이션 영역 채움, 기준 그리드라인 3줄, 데이터포인트 호버 툴팁 추가(위 "일별 추이 차트 개선" 절). `views.py` 좌표 계산은 변경하지 않고 템플릿만으로 구현. "기술 주제별 언급 건수" 카드에 "기업별 건수 Top 10"과 동일한 호버 팝오버 패턴 추가(위 "기술 주제별 호버 팝오버" 절) — `tech_topic_counts`에 `recent_news`/`more_count` 키가 필요해 PE 작업 스펙을 별도로 남김.
- **(배치 4, 사용자 피드백 — "x/y축이 안 보인다", "칸에 꽉 차게")** "일별 뉴스 건수 추이"에 실제 y축(세로 축선 + 0/중간/최댓값 눈금 숫자)과 x축(0선 + 데이터포인트별 눈금선 + 픽셀 정렬된 날짜 라벨)을 SVG 내부 좌표계로 통합 신설, 대칭 `PAD_X`/`PAD_Y` 대신 비대칭 `PAD_LEFT`/`PAD_RIGHT`/`PAD_TOP`/`PAD_BOTTOM`(16/6/8/18)으로 좌우 여백 축소 + SVG 컨테이너를 `h-20`→`h-28`로 키워 카드 안에서 하나의 통합된 차트로 채움(위 "일별 추이 차트 축 개선(3차)" 절). SVG 바깥에 있던 건수 숫자 행은 y축 눈금으로 압축 대체(정확한 값은 기존 호버 툴팁 유지). `views.py`는 이번에도 PD가 직접 수정하지 않았고, `PAD_LEFT/RIGHT/TOP/BOTTOM` 상수 교체와 신규 컨텍스트 변수 `daily_max_count` 추가가 필요해 PE 작업 스펙을 별도로 남김 — 적용 전까지는 y축 숫자가 빈 값으로 보이는 임시 상태(에러는 없음).
- **(배치 5, 사용자 피드백 — 렌더링 스크린샷에서 시각 버그 2건 지적)** "일별 뉴스 건수 추이" 카드가 옆 카드와 그리드 stretch로 높이는 늘어나되 안쪽 SVG는 고정 `h-28`이라 아래 여백이 남던 문제를 카드 `flex flex-col h-full` + 차트 래퍼 `flex-1 min-h-0` + SVG `h-full`로 해결. `preserveAspectRatio="none"`의 비균등 스케일링으로 SVG `<circle>` 데이터포인트가 타원으로 보이던 문제는 점을 SVG에서 빼고 기존 호버 오버레이(퍼센트 좌표 `<div>`) 안에 HTML `rounded-full` `<span>`으로 통합해 해결(시각 요소 + 호버 트리거를 하나로 합침). 카드 제목 옆에 "발행일 기준" 라벨을 추가해 집계 기준(`News.published_at`, 수집일 아님)을 명시. 세 가지 모두 `views.py` 변경 없이 템플릿만으로 처리(위 "일별 추이 차트 시각 버그 수정(4차)" 절 참고).
- **(배치 6, 사용자 피드백 — "발행일 기준 텍스트 제거", "텍스트가 너무 크게 보이고 해상도가 깨져 보인다")** 4차(배치 5)에서 추가했던 "발행일 기준" 보조 라벨을 제거. `preserveAspectRatio="none"`의 비균등 스케일링이 SVG `<text>`(y축 눈금 숫자 3개, x축 날짜 라벨 7개)까지 세로로 늘려 뭉개 보이던 문제를, 데이터포인트 원(4차)과 동일한 처방으로 해결 — 모든 `<text>`를 제거하고 기존 `widthratio` %좌표 변환 기법을 재사용한 HTML `<span>` 오버레이로 옮김. SVG에는 그리드라인·곡선·영역채움·축선 같은 순수 도형만 남고, `aria-hidden="true"`를 다시 붙임(3차에서 뺐던 것을 원복 — SVG가 더 이상 정보를 전달하지 않으므로). `views.py`의 좌표 계산(`day.x`/`day.y`, `daily_max_count`)은 변경 없음(위 "일별 추이 차트 시각 버그 수정(5차)" 절 참고).
- **(배치 7, 사용자 피드백 — "문단마다 구분을 해줘, 다 붙어있으니까 가독성이 너무 떨어진다")** "주요 이슈"와 "최신 뉴스" 두 리스트의 항목 간·문단 간 시각적 구분을 보강했다. `views.py` 변경 없이 템플릿만 수정.
  - **최신 뉴스**: 기존엔 `border-b border-gray-100 last:border-0` 얇은 밑줄 하나로만 항목을 구분해, 같은 화면의 "주요 이슈" 박스형 카드에 비해 구분감이 약했다. 새 패턴을 만들지 않고, 같은 파일 "주요 이슈" 카드에 이미 쓰이던 `border border-gray-100 rounded-[10px] p-3 hover:border-primary/30 transition-colors` 박스 패턴을 그대로 재사용해 각 뉴스 항목을 독립된 카드로 바꿨다(`space-y-3`는 유지). 이제 리스트 항목 하나하나가 테두리로 명확히 나뉜다.
  - **주요 이슈 아코디언**: (1) 이슈 카드 사이 간격을 `space-y-3`(12px)→`space-y-4`(16px)로 넓힘. (2) 펼침 상태에서 제목→"분석" 라벨→분석 본문 순서의 간격이 `mt-2`/`mt-1`(8px/4px)로 좁아 붙어 보이던 것을 `mt-3`/`mt-2`(12px/8px)로 넓힘. (3) 시사점 블록과 관련 기사 블록 사이에 구분선이 없어 이어져 보이던 것을, 상단 헤더-펼침영역 경계에 이미 쓰인 `border-t border-gray-100 pt-4` 패턴을 그대로 가져와 시사점이 있을 때만(`{% if insight.implication %}`) 관련 기사 블록 앞에 추가했다(시사점이 없으면 불필요한 빈 구분선이 생기지 않도록 조건부 처리). (4) 관련 기사 링크 목록 줄 간격을 `space-y-1`→`space-y-1.5`로 살짝 넓힘.
- **(배치 8, 2026-07-27, PM 정책 — "대시보드·지식그래프 공통 기간 필터 정책") 기간 셀렉터(전체/최근 30일/최근 7일) 도입 + "일별 뉴스 건수 추이" 카드를 가변 데이터포인트 구조로 재설계.** 기존 "최근 7일" 고정 pill 배지를 3-옵션 GET 링크 토글로 교체(3개 카드 공통, 기본값 최근 7일). 차트 카드는 7개 고정 전제로 하드코딩돼 있던 베지어 제어점 좌표 리터럴을 전부 제거하고, 좌표뿐 아니라 SVG 경로 문자열 자체(`trend_line_path`/`trend_area_path`)를 뷰가 임의 개수의 포인트에 대해 일반화된 "수평 탄젠트" 공식으로 계산해 넘기는 구조로 바꿨다(폴리라인 단순화 대신 곡선 유지 — 자세한 판단 근거는 위 "기간 필터 + 뉴스 건수 추이 차트 가변화" 절 5번). 카드 제목은 버킷 단위(`bucket_unit`)에 따라 "일별/주별/월별"로 자동 전환해 PM이 예약해 둔 "일/주 토글"을 별도 UI 없이 흡수했다. x축 라벨은 `show_label` 플래그(간격 = `round(N/6)`)로 솎아내고, dot/호버 히트박스는 포인트 15개 초과 시 크기를 줄여 겹침을 방지했다. 카드2/3(기업별 Top10, 기술주제별)은 구조 변경 없이 집계 쿼리 날짜 하한만 `period`를 따르도록 바뀐다. `views.py`는 이번에도 PD가 직접 수정하지 않았고 PE 작업 스펙을 위 절에 상세히 남김 — 적용 전까지는 `trend_points` 등 신규 컨텍스트 변수가 비어 empty state로 보이는 임시 상태(에러는 없음, 기존 관례와 동일).
- **(배치 9, 2026-07-31, 데모 피드백 축 3 — PM 통합 계획 채택안) "항목별 데이터·기준 툴팁" 도입.** 5개 카드(일별 추이/기업별 Top10/기술주제별/주요 이슈/최신 뉴스) 제목 옆에 "?" 아이콘 → 팝오버로 "어떤 데이터를 어떤 기준으로 보여주는지" 설명을 추가했다. 새 재사용 컴포넌트 "Info Tooltip"을 디자인 시스템(위 "1.5 컴포넌트 정의")에 신설하고, 문구는 화면 템플릿이 아니라 별도 딕셔너리 한곳에서 관리하도록 PE에게 지시했다(위 "카드별 데이터·기준 툴팁 적용" 절 참고). 기존 "관련 뉴스 호버 팝오버"(기업별 Top10·기술주제별)와 시각 톤(흰 배경·rounded-[10px]·shadow-lg)·Alpine 패턴(호버+클릭, x-cloak)은 통일하되 역할은 분리했다(데이터 목록 vs. 집계 기준 설명). 새 화면 ID는 만들지 않았다 — 기존 ALL-001 카드에 얹는 부가 UI.

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 전체 대시보드 화면을 HTML + Tailwind CSS로 만들어줘.

[디자인 시스템]
- Primary: #60269E (Violet), Accent: #93D500 (Green), Blue Green: #00AF9A
- Font: Inter (body), Source Serif 4 (heading)
- Border radius: 10px, Border: 1px solid #E5E5E5
- Page bg: #F9F9F7, Card bg: white

[레이아웃]
- 좌측 사이드바 (w-56) + 우측 콘텐츠 영역
- 상단 헤더 (bg #60269E, text white, h-14)
- 헤더 좌: "DPLANEX / AI Market Watch" (슬래시는 #93D500)
- 헤더 우: "마지막 수집: 2026-06-25 09:00" 텍스트
- 사이드바 메뉴: 전체(활성), 뉴스, 보고서, 설정

[콘텐츠 구성]
1. "핵심 지표" 섹션 (제목 옆 [전체]/[최근 30일]/[●최근 7일] 3-옵션 pill 토글 셀렉터, 활성 옵션만 보라 채움), 3-column grid — 셀렉터 하나가 아래 3개 카드를 모두 지배
   - 카드 A "일별 뉴스 건수 추이"(선택된 기간에 따라 "주별"/"월별"로 제목 전환 가능): 인라인 SVG 라인그래프(라이브러리 없음, `<path>` 부드러운 곡선, 최근 7일 기준 점 7개), 실제 x/y축 포함 — 왼쪽에 y축 세로선 + 0/중간값/최댓값 눈금 숫자, 아래에 x축(0선) + 데이터포인트마다 눈금선 + MM/DD 날짜 라벨(축과 픽셀 단위로 붙어 보이게, 포인트가 많아지면 5~7개 간격으로만 라벨 표시), 라인 아래 보라 그라데이션 영역 채움, 가장 최근 지점만 진한 보라 채움 dot + 굵은 글씨로 강조, 나머지는 흰 채움 + 연한 보라 테두리 dot, 점에 마우스 올리면 "MM/DD · N건"(또는 "MM/DD~MM/DD · N건") 툴팁 노출, 좌우 여백 최소화해 카드 폭을 꽉 채움
   - 카드 B "기업별 건수 Top 10": 순위 1~10, 기업명, 가로 미니바(금융사 파랑/보험사 청록/AI 보라), 건수 — 1 KB국민은행 9건, 2 삼성생명 6건, 3 Anthropic 5건 ... 10위까지. 기업명에 마우스 올리면 관련 뉴스 팝오버 노출
   - 카드 C "기술 주제별 언급 건수": 순위 1~4, 주제명, 가로 미니바(Accent Green), 건수 — 1 AI 에이전트 11건, 2 AI 거버넌스 2건, 3 온톨로지 1건, 4 AI Ready Data 1건 (0건 주제는 표시 안 함). 주제명에 마우스 올리면 카드 B와 동일한 관련 뉴스 팝오버 노출

2. 2단 그리드 (핵심 지표 아래)
   좌(2/3): 주요 이슈 카드 3개 (클릭하면 펼쳐지는 아코디언 형태로 표현)
   - 제목: "국내 금융권 AI Agent 도입 가속화"
   - 관련 기사 8건
   - 요약 2줄 (접힘 상태 기준)
   우(1/3): 최신 뉴스 목록 5개
   - 제목 + 발행일

[스타일 규칙]
- 활성 사이드바 메뉴: bg #F3EAFB, text #60269E, left border 2px solid #60269E
- 카드: white bg, shadow-sm, rounded-[10px], border border-[#E5E5E5]
- 한국어 샘플 데이터 사용
```

---

### NEWS-001 · 뉴스 목록

**목적**: 수집된 뉴스 전체를 탐색하고 필터링

**구성 요소**

```
┌─ 검색 + 필터 바 ────────────────────────────────────────┐
│  [검색창]  [기간▼]  [출처▼]  [기업유형▼]                │
└─────────────────────────────────────────────────────────┘

┌─ 결과 수 + 정렬 ────────────────────────────────────────┐
│  247건  최신순▼                                         │
└─────────────────────────────────────────────────────────┘

┌─ 날짜 구분 헤더 (calendar 아이콘 + 발행일) ─────────────┐
├─ 뉴스 카드 목록 (카드 전체 클릭 → 뉴스 상세 이동) ──────┤
│  발행일                                    [삭제 아이콘]│
│  제목 (Heading 3)                                       │
│  [기업 배지 ...]                                        │
├─────────────────────────────────────────────────────────┤
│  반복 ...                                               │
└─────────────────────────────────────────────────────────┘

┌─ 페이지네이션 ──────────────────────────────────────────┐
│  ← 이전  1  2  3  ...  다음 →                          │
└─────────────────────────────────────────────────────────┘
```

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 뉴스 목록 화면을 HTML + Tailwind CSS로 만들어줘.

[디자인 시스템]
- Primary: #60269E, Accent: #93D500
- Page bg: #F9F9F7, Card bg: white, radius: 10px

[레이아웃]
- 좌측 사이드바 + 우측 콘텐츠
- 사이드바 활성 메뉴: 뉴스

[콘텐츠 구성]
1. 상단 검색 + 필터 바
   - 검색 인풋 (placeholder: "키워드로 검색...")
   - 드롭다운 필터: 기간, 출처(네이버/OpenDART/RSS), 기업 유형(금융사/보험사/AI/기업없음)
   - 필터 초기화 버튼

2. 결과 수 + 정렬 (247건, 최신순)

3. 뉴스 카드 5개 (리스트 형태, 각 카드 세로 배치)
   카드 구성:
   - 상단: 발행일 (좌) + 삭제 아이콘 버튼 (우) — 삭제 버튼은 카드 클릭 영역과 분리된 별도 액션
   - 뉴스는 발행일(KST) 기준으로 날짜별 그룹핑되어 calendar 아이콘 + 날짜 헤더 아래 표시
   - 제목 (Source Serif 4, 18px) — 카드 클릭 영역의 일부 (제목만 별도 링크가 아님)
   - 매핑된 기업 배지 (제목 하단)
   - 카드 전체가 클릭 영역, 클릭 시 뉴스 상세로 이동 (별도 "상세보기" 버튼 없음)

   샘플 데이터:
   - "삼성SDS, AI Agent 플랫폼 도입으로 고객 상담 자동화 85% 달성" / ZDNet Korea / 2시간 전
   - "금융위원회, 생성형 AI 활용 가이드라인 초안 발표" / 금융위원회 RSS / 3시간 전
   - "Anthropic, Claude 4 출시…코딩·분석 능력 대폭 강화" / 연합뉴스 / 5시간 전
   - "KB국민은행, LLM 기반 여신심사 시스템 도입 추진" / KB국민은행 / 매일경제 / 어제
   - "국내 AI 스타트업 투자 유치 현황 Q2 결산" / 한국경제 / 어제

4. 페이지네이션 (1, 2, 3 ... 25)

[스타일 규칙]
- 카드 hover: shadow 강해짐 (border-color 변경 없음, REPORT-001과 동일 규칙)
- 카드 클릭 패턴: 전체 클릭형 List Card (1.5 컴포넌트 정의 참고) — 삭제 버튼이 경쟁 액션이므로 Stretched Link 기법 적용
- 기업 배지: 기업 유형별 soft 색상 (금융사 blue, 보험사 green, AI violet)
```

---

### NEWS-002 · 뉴스 상세

**목적**: 개별 뉴스의 원문·요약·인사이트를 종합 확인

**구성 요소**

```
┌─ 브레드크럼 (좌) + 이전/다음 네비게이션 (우) ──────────┐
│  뉴스 > 뉴스 상세              ◀ 이전 | 다음 ▶         │
└────────────────────────────────────────────────────────┘

┌─ 메인 콘텐츠 (2/3) ────┐  ┌─ 사이드 패널 (1/3) ──────┐
│ 발행일                 │  │ 관련 기업                 │
│ 제목 (H2)              │  │ ┌────────────────────┐   │
│ 발행일 · 원문링크       │  │ │ 기업 배지 목록      │   │
│                        │  │ └────────────────────┘   │
│ [요약 callout]         │  │                          │
│ LLM 요약 3-5줄         │  │                          │
│                        │  │                          │
│ ── 원문 내용 ──        │  │                          │
│ 본문 텍스트 또는        │  │                          │
│ 원문 보기 링크          │  │                          │
│                        │  │                          │
│ ── 이슈 시사점 ──      │  │                          │
│ (연결 Insight당 1개)  │  │                          │
│ 라벨: "이슈 시사점"     │  │                          │
│ 보조텍스트: 소속 이슈   │  │                          │
│  제목(insight.title)  │  │                          │
│ callout: implication  │  │                          │
│ (같은 이슈 기사끼리     │  │                          │
│  시사점 공유 — 정상)   │  │                          │
└────────────────────────┘  └──────────────────────────┘
```

**변경 이력**
- 2026-07-31 — 시사점 블록이 "기사 고유"가 아니라 "이슈(Insight) 단위"임을 오해 없이 전달하도록 표기 보강. 라벨을 "시사점" → "이슈 시사점"으로 변경하고, `insight.title`(연결된 이슈 제목)을 보조 텍스트로 함께 노출("이 기사가 속한 이슈 · {{ insight.title }}"). 같은 Insight에 묶인 여러 기사(8~16개)가 동일한 `insight.implication`을 공유하는 것은 설계상 정상이며, 이번 변경은 표기만 보강한 것으로 뷰 로직·컨텍스트 변수 변경 없음(`templates/news/detail.html`).

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 뉴스 상세 화면을 HTML + Tailwind CSS로 만들어줘.

[디자인 시스템]
- Primary: #60269E, Accent: #93D500
- Page bg: #F9F9F7, Card bg: white, radius: 10px

[레이아웃]
- 좌측 사이드바 + 우측 콘텐츠
- 콘텐츠: 2/3 메인 + 1/3 사이드패널 (sticky) 2단 그리드

[콘텐츠 구성]
샘플 뉴스: "삼성SDS, AI Agent 플랫폼 도입으로 고객 상담 자동화 85% 달성"

1. 브레드크럼(뉴스 > 뉴스 상세) + 우측 이전/다음 뉴스 네비게이션 (발행일 최신순 기준, 최신·최고령 뉴스에서는 비활성 표시)

2. 메인 콘텐츠
   - 발행일
   - 제목 (Source Serif 4, 28px)
   - 원문 보기 링크 (외부 아이콘 포함)
   - LLM 요약 callout (info 스타일, bg #F9F5FF, border-left #60269E)
     "삼성SDS는 자체 개발 AI Agent 플랫폼을 고객 상담 센터에 도입하여 반복 문의 자동화율 85%를 달성했다. 해당 플랫폼은 RAG 기반으로 사내 문서를 실시간 참조하며..."
   - 섹션 구분선
   - 본문 요약 텍스트 (3-4단락)
   - 인사이트 섹션 (H3)
     callout 2개:
     · "금융권 콜센터 AI 자동화 수요가 증가하고 있으며, AI Agent 모듈 고도화 기회로 연결 가능."
     · "고객사 AI Agent 구축 레퍼런스로 활용 가능한 아키텍처 사례."

3. 사이드 패널 (sticky)
   - 관련 기업 섹션: 배지 형태로 매핑된 기업 목록 + 기업 추가 드롭다운

[스타일 규칙]
- Callout: 좌측 2px border, 배경 연한 색상
- 사이드패널: position sticky, top-20
```

---

### REPORT-001 · 보고서 목록

**목적**: 생성된 주간 AI 인사이트 보고서 목록 조회

**구성 요소**

```
┌─ 페이지 제목 ───────────────────────────────────────────┐
│  주간 AI 인사이트 보고서                                │
└─────────────────────────────────────────────────────────┘

┌─ 보고서 카드 목록 (카드 전체 클릭 → 보고서 상세 이동) ──┐
│  2026년 26주차 · 2026-06-23 ~ 2026-06-29               │
│  "AI Agent 상용화 가속, 금융권 LLM 도입 본격화"         │
│  생성일: 2026-06-30 09:00  [완료]배지  [Slack 전송됨]  │
├─────────────────────────────────────────────────────────┤
│  반복 ...                                               │
└─────────────────────────────────────────────────────────┘

┌─ 빈 상태 (report 목록이 비어있을 때) ────────────────────┐
│              file-text 아이콘 (opacity 40%)             │
│              "생성된 보고서가 없습니다."                │
│      "리서치 담당자(RA)가 주간 보고서를 작성하면        │
│              여기에 표시됩니다."                        │
└─────────────────────────────────────────────────────────┘
```

**변경 이력**
- 2026-07-28 — 상단 `[+ 보고서 생성]` Primary 버튼 제거. 클릭 핸들러가 없는 플레이스홀더였고, 보고서는 자동 생성이 아니라 RA(research-analyst)가 수동으로 표준 구조에 따라 작성하는 체제로 확정됨(`docs/planning.md` "주간 보고서(Report) 표준 구조" 참고). `templates/reports/list.html`에서 실제로 제거된 뒤 문서를 코드에 맞춰 정정.
- 같은 날, 빈 상태 UI(`file-text` 아이콘 + 안내 문구 2줄) 반영. 기존 문서에는 빈 상태 서술이 없었음.

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 보고서 목록 화면을 HTML + Tailwind CSS로 만들어줘.

[디자인 시스템]
- Primary: #60269E, Accent: #93D500
- Page bg: #F9F9F7, Card bg: white, radius: 10px

[레이아웃]
- 좌측 사이드바(보고서 활성) + 우측 콘텐츠

[콘텐츠 구성]
1. 상단: 제목 "주간 AI 인사이트 보고서" (생성 버튼 없음 — 보고서는 RA가 수동 작성)

2. 보고서 카드 4개
   카드 구성:
   - 주차 + 날짜 범위 (작은 gray 텍스트)
   - 보고서 제목 (Source Serif 4, 18px)
   - 하단 row: 생성일 + 상태 배지 + Slack 전송 배지 (별도 "상세 보기" 버튼 없음)
   - 카드 전체가 클릭 영역, 클릭 시 보고서 상세로 이동

   샘플 데이터:
   - 26주차 (6/23~6/29) / "AI Agent 상용화 가속, 금융권 LLM 도입 본격화" / 완료 / Slack 전송됨
   - 25주차 (6/16~6/22) / "생성형 AI 규제 논의 활발, 국내 AX 프로젝트 증가" / 완료 / Slack 전송됨
   - 24주차 (6/9~6/15) / "Claude 4 출시와 국내 금융권 AI 파일럿 동향" / 완료 / Slack 미전송
   - 23주차 (6/2~6/8) / "AI 거버넌스 이슈 부각, 멀티모달 모델 경쟁 심화" / 완료 / Slack 전송됨

3. 빈 상태 (보고서가 하나도 없을 때, 카드 목록 대체)
   - 중앙 정렬, 넉넉한 padding
   - file-text 아이콘 (opacity 40%)
   - "생성된 보고서가 없습니다." (text-sm)
   - "리서치 담당자(RA)가 주간 보고서를 작성하면 여기에 표시됩니다." (text-xs, gray-400)

[스타일]
- 완료 배지: bg #E6F7F5, text #00AF9A
- Slack 전송됨: bg #F3EAFB, text #60269E
- Slack 미전송: bg #F3F4F6, text #54565A
- 카드 클릭 패턴: 전체 클릭형 List Card (1.5 컴포넌트 정의 참고) — 경쟁 액션 없음, <a class="block group">로 전체 콘텐츠를 감싼다
- 카드 hover: shadow 강해짐 (NEWS-001과 동일 규칙)
```

---

### REPORT-002 · 보고서 상세

**목적**: 특정 주차 주간 AI 인사이트 보고서 전문 확인

**구성 요소**

```
┌─ 브레드크럼 ────────────────────────────────────────────┐
│  보고서 › 주간 · 2026.06.23              [상태 배지]    │
└─────────────────────────────────────────────────────────┘

┌─ 보고서 헤더 (Violet 그라디언트 배경) ─────────────────┐
│  2026년 26주차 AI 인사이트 보고서                      │
│  2026-06-23 ~ 2026-06-29                              │
│  (헤더 우측 상단: Slack 전송됨 배지 / 미전송 텍스트)   │
└─────────────────────────────────────────────────────────┘

┌─ 상태 안내 (status='generating' | 'failed' 일 때만) ───┐
│  생성 중: 노란 배경 + 로딩 아이콘 + 안내문             │
│  생성 실패: 빨간 배경 + 경고 아이콘 + 안내문           │
└─────────────────────────────────────────────────────────┘

┌─ 이번 주 주요 동향 (overview 있을 때만) ────────────────┐
│  총평 텍스트 2-3단락                                    │
└─────────────────────────────────────────────────────────┘

┌─ 주요 이슈 (content 있을 때만) ──────────────────────────┐
│  report_issues 필터로 "### 제목" 단위 파싱             │
│  ┌ 이슈 카드 1 ──────────────────────────────────────┐ │
│  │ ① 이슈 제목                                        │ │
│  │   흐름분석 본문 서술 텍스트                         │ │
│  │   시사점 문단 (라벨 없는 일반 문단 — 이슈 블록의    │ │
│  │   마지막 문단 = 시사점이라는 위치 규칙으로 판단)     │ │
│  └────────────────────────────────────────────────────┘ │
│  ┌ 이슈 카드 2 ── ② ... (동일 구조 반복) ─────────────┐ │
│  └────────────────────────────────────────────────────┘ │
│  카드 분리(회색 배경+테두리+번호 배지)만 유지. 카드      │
│  본문은 markdown-content 기본 스타일 그대로 렌더링       │
│  (이슈별 전용 CSS 없음)                                  │
│  (content에 "### " 구분자가 없는 과거 데이터는           │
│   기존처럼 content 전체를 통짜 markdown으로 폴백 렌더링) │
└─────────────────────────────────────────────────────────┘

┌─ 빈 상태 (status='done' 이면서 overview·content 모두 없음) ┐
│  inbox 아이콘 + "표시할 보고서 내용이 없습니다."         │
└─────────────────────────────────────────────────────────┘

┌─ 참고 뉴스 ─────────────────────────────────────────────┐
│  테이블: 제목 · 발행일 (근거 기사 접근 통로, 유지)      │
└─────────────────────────────────────────────────────────┘
```

**변경 이력 (2026-07-10, PM 감사 반영)**
- 기술/시장/사업 기회 관점 3-box 콜아웃 제거. `implication_tech/market/biz` 컨텍스트 변수가 뷰에서 전달되지 않아 항상 빈 죽은 UI였음. 시사점은 "주요 이슈 & 시사점"(`report.content`) 자유 서술로 통합.
- 헤더의 활성 "Slack 전송" 버튼 제거. `href`/`hx-post` 없이 클릭해도 무반응이었고, 원클릭 발송은 RA의 발송 전 검수 게이트를 우회할 위험이 있어 의도적으로 만들지 않음. `slack_sent_at`이 있으면 "전송됨" 배지, `status='done'`이면서 미전송이면 "Slack 미전송" 텍스트만 표시.
- 브레드크럼 우측에 `report.status` 배지 추가 (list.html과 동일한 색상 규칙: done=green, generating=yellow, failed=red).
- `status='generating'` / `'failed'`일 때 헤더 아래 안내 배너 추가 (본문 섹션이 비어 보이는 이유를 설명).
- `status='done'`인데 overview·content가 모두 비어있는 경우를 위한 empty state 추가 (`inbox` 아이콘, 기존 프로젝트 패턴 재사용).

**변경 이력 (2026-07-29, 이슈별 카드 분할)**
- "주요 이슈 & 시사점"을 통짜 markdown 렌더링에서 이슈별 카드 분할로 개선. PE가 추가한 `report_issues` 템플릿 필터(`apps/reports/templatetags/report_extras.py`)로 `report.content`를 `### 제목` 단위(dict: `preamble` + `issues[].title/body`)로 파싱해, 이슈마다 연한 회색 배경 카드(`bg-gray-50/50` + `border border-[#E5E5E5] rounded-[10px]`) + 원형 번호 배지(`bg-primary/10 text-primary`)로 분리 렌더링. `### ` 구분자가 없는 과거 데이터(`issues=[]`)는 기존 통짜 렌더링으로 폴백해 하위 호환 유지.
- 이슈 카드 본문(`.issue-body`) 안에서 "시사점" 문단(볼드로 시작)은 보라 강조 박스(`#F5EEFB` bg + `4px solid #60269E` 좌측 보더, 뉴스 상세 시사점 블록과 동일 톤)로 스타일링.
- (같은 날 방향 전환) 이슈 카드는 제목 + 흐름분석 + 시사점 3단만 노출하기로 확정 — 카드 안 "근거 기사" 링크 목록·라벨은 노출하지 않음. 하단 "참고 뉴스" 테이블은 삭제하지 않고 유지(근거 기사 접근 통로 역할). RA content에 아직 남아있는 구버전 "근거 기사:" 라벨 문단과 뒤따르는 목록(`ul`)은 `.issue-body p:has(+ ul)` / `.issue-body ul`에 `display: none`을 걸어 화면에서만 숨김 처리 — RA가 content 표준 구조를 3단(제목·흐름분석·시사점)으로 정리하면 이 임시 숨김 규칙은 제거 예정.

**변경 이력 (2026-07-29, 시사점 강조 UI 제거 및 추가 단순화)**
- 섹션 헤더를 "주요 이슈 & 시사점" → "주요 이슈"로 변경. 시사점 강조 박스(`#F5EEFB` 보라 배경 + 좌측 보더) 스타일을 제거해 시사점 문단이 흐름분석 다음에 일반 문단으로 이어지도록 단순화. RA content 정리로 근거 기사 링크(`ul`)가 완전히 사라졌음이 확인되어 임시 방어용 `display: none` 규칙(`.issue-body p:has(+ ul)`, `.issue-body ul`)도 함께 제거 — 이슈 카드 분리(회색 배경+테두리+번호 배지)만 유지하고 카드 본문은 `.issue-body` 없이 기본 `.markdown-content` 스타일만 적용.
- (같은 날 추가 결정) 시사점 문단 앞의 `**시사점:**` 볼드 라벨 표기도 제거하기로 확정. 시사점은 라벨 없는 일반 문단으로 쓰고, "이슈 블록의 마지막 문단 = 시사점"이라는 위치 규칙으로 구분한다(RA가 Report 10 content에서 라벨 제거 작업 중, `docs/planning.md`도 병행 개정 중). 템플릿은 이미 시사점 전용 UI가 없어 별도 수정 불필요.

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 보고서 상세 화면을 HTML + Tailwind CSS로 만들어줘.

[디자인 시스템]
- Primary: #60269E, Accent: #93D500, Deep: #401771
- Page bg: #F9F9F7, Card bg: white, radius: 10px

[레이아웃]
- 좌측 사이드바(보고서 활성) + 우측 콘텐츠 (단일 컬럼, max-w-3xl)

[콘텐츠 구성]
1. 브레드크럼 (보고서 › 주간 · 날짜) + 우측 상태 배지
   (done=green bg-green-100 text-green-700 / generating=yellow bg-yellow-100 text-yellow-700 / failed=red bg-red-100 text-red-600)

2. 보고서 헤더 카드 (Violet→Deep Violet 그라디언트 bg, text white)
   - "2026년 26주차 AI 인사이트 보고서"
   - "2026-06-23 ~ 2026-06-29"
   - (액션 버튼 없음. 헤더 영역 바깥 상단에 Slack 전송됨/미전송 텍스트만 작게 표시)

3. 상태 안내 배너 (generating/failed 상태일 때만)
   - 생성 중: bg-yellow-50 border-yellow-200, 로딩 아이콘 + "보고서를 생성하는 중입니다"
   - 생성 실패: bg-red-50 border-red-200, 경고 아이콘 + "보고서 생성에 실패했습니다"

4. 이번 주 주요 동향 섹션 (H2, overview 있을 때만)
   총평 2단락 텍스트

5. 주요 이슈 섹션 (H2, content 있을 때만)
   "### 제목" 단위로 쪼갠 이슈 카드 반복 (연한 회색 배경 + 얇은 테두리, 카드마다
   원형 번호 배지 + 제목 + 흐름분석 서술 + 시사점 문단(별도 강조 박스나 볼드
   라벨 없이 일반 문단으로 자연스럽게 이어짐. 이슈 블록의 마지막 문단이
   시사점이라는 위치 규칙으로 구분) 구성. 근거 기사 링크는 카드 안에 넣지 않음)

6. 빈 상태 (done인데 4·5 섹션이 모두 없을 때)
   inbox 아이콘 + "표시할 보고서 내용이 없습니다."

7. 참고 뉴스 테이블
   컬럼: 제목 | 발행일
   8개 행

[스타일]
- 섹션 구분: 얇은 hr
- H2: Source Serif 4, 좌측 3px solid #60269E border
```

---

### SET-001 · 데이터 소스 관리

**목적**: 뉴스 수집 대상 소스의 활성/비활성 제어, 수동 수집 실행, 수동 AI 관련성 판단·요약 실행

**구성 요소**

```
┌─ 페이지 제목 ───────────────────────────────────────────┐
│  데이터 소스 관리                                        │
└─────────────────────────────────────────────────────────┘

┌─ 소스 테이블 ───────────────────────────────────────────┐
│  소스명           │  URL  │  유형  │  수집 주기  │  활성 │
├───────────────────┼───────┼────────┼────────────┼───────┤
│  Naver News API   │  ...  │ [API]  │     —      │  ●   │
└───────────────────┴───────┴────────┴────────────┴───────┘

┌─ 수동 실행 ─────────────────────────────────────────────┐
│  [▶ 지금 수집]  수집 중... (로딩 스피너)                │
│  수집 완료: 신규 N건 / 중복 N건 / 필터 N건 / 삭제이력   │
│  N건 / 크롤 N건                                        │
│                                                         │
│  [✨ AI 처리]  처리 중... (로딩 스피너)                 │
│  AI 처리 완료: 대상 N건 / 관련 N건 / 비관련 N건 /       │
│  실패 N건                                              │
└─────────────────────────────────────────────────────────┘
```

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 데이터 소스 관리 화면을 HTML + Tailwind CSS로 만들어줘.

[레이아웃]
- 좌측 사이드바(설정 > 데이터 소스 활성, accordion 펼쳐진 상태) + 우측 콘텐츠

[콘텐츠 구성]
1. 제목 "데이터 소스" + 우측 "소스 추가" Primary 버튼

2. 테이블 (소스명 | URL | 유형 | 수집 주기 | 활성 여부 | 액션)
   샘플 6행:
   - 네이버 뉴스 API / api.naver.com/... / API / 매일 09:00 / 활성 / 수정·비활성화
   - 금융위원회 RSS / fsc.go.kr/rss / RSS / 매일 09:00 / 활성 / 수정·비활성화
   - OpenDART API / opendart.fss.or.kr/... / API / 매일 09:00 / 활성 / 수정·비활성화
   - Anthropic 블로그 / anthropic.com/blog / 웹 크롤링 / 매일 10:00 / 활성 / 수정·비활성화
   - Google AI 블로그 / blog.google/ai / 웹 크롤링 / 매일 10:00 / 비활성 / 수정·활성화
   - 한국은행 RSS / bok.or.kr/rss / RSS / 매일 09:00 / 활성 / 수정·비활성화

3. 유형 배지: API(#EEF2FF/#1D4ED8), RSS(#E6F7F5/#00AF9A), 웹 크롤링(#F3F4F6/#54565A)
4. 활성: 초록 토글 ON / 비활성: 회색 토글 OFF

[스타일]
- Primary: #60269E, radius: 10px
- 테이블 헤더: uppercase, text-xs, text-gray-500
- 액션 버튼: ghost 스타일 (아이콘만)
```

---

### SET-002 · 키워드 관리

**목적**: Naver News API 검색 쿼리(수집 키워드)와 제외 키워드를 CRUD 관리

**구성 요소**

```
┌─ 수집 키워드 [?툴팁] ──────┐  ┌─ 제외 키워드 ──────────┐
│  네이버 뉴스에 직접 요청할  │  │  수집된 뉴스에서        │
│  검색 쿼리                  │  │  제목에 포함 시 필터링  │
│                             │  │                        │
│  키워드      정렬    액션   │  │  키워드         액션   │
│  ─────────────────────────  │  │  ─────────────────────  │
│  AI 금융    [최신순] ✎ 🗑  │  │  광고           ✎ 🗑   │
│  앤트로픽   [관련도순] ✎ 🗑│  │  협찬           ✎ 🗑   │
│                             │  │                        │
│  [키워드 입력] [최신순▼] 추가│  │  [키워드 입력]    추가  │
└─────────────────────────────┘  └────────────────────────┘
```

**수집 키워드 툴팁** (? 아이콘 hover 시)
```
Naver News API 쿼리 문법
AI 금융    → 두 단어 모두 포함 (AND)
"AI 금융"  → 정확한 문구 일치
A | B      → 하나라도 포함 (OR)
AI -광고   → 특정 단어 제외
```

**수정 모달** (✎ 클릭 시)
- 수집 키워드: 키워드 텍스트 + 정렬(최신순/관련도순) 수정
- 제외 키워드: 키워드 텍스트만 수정
- ESC / 배경 클릭으로 닫힘

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 키워드 관리 화면을 HTML + Tailwind CSS로 만들어줘.

[레이아웃]
- 좌측 사이드바(설정 > 키워드 활성) + 우측 콘텐츠

[콘텐츠 구성]
1. 제목 "키워드 관리"

2. 2단 그리드
   좌(수집 키워드): 제목 + "키워드 추가" 버튼 + 태그 목록
   키워드 태그 (클릭하면 삭제 X 표시):
   AI Agent, 생성형 AI, LLM, 거대언어모델, Claude, ChatGPT, Gemini, 금융 AI, 은행 AI, 보험 AI, RAG, AI 플랫폼, AX, 디지털 전환, Copilot

   우(제외 키워드): 제목 + "키워드 추가" 버튼 + 태그 목록 (다른 색상)
   AI 스피커, AI 냉장고, AI 카메라, 채용, 인사이동, 주가

3. 하단: 키워드 추가 인풋 + 추가 버튼 (각 섹션마다)

[스타일]
- 수집 키워드 태그: bg #F3EAFB, text #60269E, border #DDD0F5
- 제외 키워드 태그: bg #FFF3EC, text #FF6C0E, border #FFD6B5
- X 버튼: hover 시 진한 색상
- 섹션 카드: white bg, shadow-sm, radius 10px
```

---

### SET-003 · 프롬프트 관리

**목적**: 요약·인사이트·보고서 생성에 사용하는 Claude 프롬프트를 편집 관리

**구성 요소**

```
┌─ 프롬프트 목록 (w-64) ──┐  ┌─ 편집 영역 ───────────────┐
│                          │  │  프롬프트명  [뉴스 요약]   │
│  ▶ 뉴스 요약 (선택됨)   │  │  목적        수집된 뉴스   │
│    유사 기사 인사이트    │  │              본문 3-5줄 요약│
│                          │  │  마지막 수정 2026-06-20    │
│                          │  │                            │
│    주간 보고서 생성      │  │  ┌─ 프롬프트 내용 ───────┐ │
│                          │  │  │ (JetBrains Mono)      │ │
│                          │  │  │ 다음 뉴스 기사를 읽고  │ │
│                          │  │  │ 핵심 내용을 3-5줄로... │ │
│                          │  │  │                       │ │
│                          │  │  └───────────────────────┘ │
│                          │  │                [저장]      │
└──────────────────────────┘  └────────────────────────────┘
```

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 프롬프트 관리 화면을 HTML + Tailwind CSS로 만들어줘.

[레이아웃]
- 좌측 사이드바(설정 > 프롬프트 활성) + 우측 콘텐츠
- 좌측 프롬프트 목록 패널(w-64) + 우측 편집 영역 2단

[콘텐츠 구성]
좌측 목록:
- 뉴스 요약 (선택됨, 활성 스타일)
- 유사 기사 인사이트
- 주간 보고서 생성

우측 편집 영역 (선택된 "뉴스 요약"):
- 프롬프트명: "뉴스 요약"
- 목적: "수집된 뉴스 본문을 3-5줄로 요약"
- 마지막 수정: 2026-06-20
- 프롬프트 내용 textarea (JetBrains Mono, 20행)
  샘플: "다음 뉴스 기사를 읽고 핵심 내용을 3-5줄로 요약해줘..."
- 저장 버튼 (Primary)

[스타일]
- 선택된 목록 항목: bg #F3EAFB, border-left 2px #60269E
- Textarea: font-mono, border, focus:border-#60269E
- 좌측 목록 패널: white bg, border-right
```

---

### SET-004 · 스케줄 관리

**목적**: 뉴스 자동 수집과 주간 보고서 생성의 실행 주기·시간을 설정

**구성 요소**

```
┌─ 페이지 제목 ───────────────────────────────────────────┐
│  스케줄 관리                                            │
└─────────────────────────────────────────────────────────┘

┌─ 뉴스 자동 수집 ────────────────────────────────── ON ●┐
│  실행 주기    매일                                      │
│  실행 시간    09:00                                     │
│  마지막 실행  2026-06-25 09:00  ✓ 성공                 │
│  다음 실행    2026-06-26 09:00                          │
│                                             [수정]      │
└─────────────────────────────────────────────────────────┘

┌─ 주간 보고서 생성 ──────────────────────────────── ON ●┐
│  실행 주기    매주 월요일                               │
│  실행 시간    09:00                                     │
│  마지막 실행  2026-06-23 09:00  ✓ 성공                 │
│  다음 실행    2026-06-30 09:00                          │
│                                             [수정]      │
└─────────────────────────────────────────────────────────┘
```

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 스케줄 관리 화면을 HTML + Tailwind CSS로 만들어줘.

[레이아웃]
- 좌측 사이드바(설정 > 스케줄 활성) + 우측 콘텐츠

[콘텐츠 구성]
1. 제목 "스케줄 관리"

2. 스케줄 카드 2개 (세로 배치)

카드 1: 뉴스 자동 수집
- 제목 + 활성 토글(ON)
- 실행 주기: 매일
- 실행 시간: 09:00
- 마지막 실행: 2026-06-25 09:00 (성공)
- 다음 실행: 2026-06-26 09:00
- 수정 버튼

카드 2: 주간 보고서 생성
- 제목 + 활성 토글(ON)
- 실행 주기: 매주 월요일
- 실행 시간: 09:00
- 마지막 실행: 2026-06-23 09:00 (성공)
- 다음 실행: 2026-06-30 09:00
- 수정 버튼

[스타일]
- 카드: white, shadow-sm, radius 10px
- 성공 상태: text #18A957, 체크 아이콘
- 라벨: uppercase text-xs text-gray-500
- 토글: 활성 bg #60269E
```

---

### SET-005 · Slack 전송 설정

**목적**: 주간 보고서를 전송할 Slack 채널과 Webhook을 설정

**정직성 주석 (2026-07-28)**: 아래 와이어프레임·프롬프트는 미래 구현 시 참조용으로 유지하되, 실제 발송 로직(Webhook POST)은 아직 구현되어 있지 않으며 사용자 확정에 따라 당분간 구현하지 않는다(REPORT-002 "Slack 전송" 버튼 제거 이력과 동일 맥락 — 원클릭 발송은 RA의 발송 전 검수 게이트를 우회할 위험이 있어 의도적으로 보류). "연결 테스트", "저장", 전송 이력 데이터도 실제 코드에 대응하는 뷰/모델이 없는 목업 상태다.

**구성 요소**

```
┌─ 페이지 제목 ───────────────────────────────────────────┐
│  Slack 전송 설정                                        │
└─────────────────────────────────────────────────────────┘

┌─ 설정 카드 (max-w-lg) ──────────────────────────────────┐
│  전송 활성화          ● ON                              │
│  채널명               #ai-market-watch                  │
│  Webhook URL          https://hooks.slack.com/•••••••  │
│                                          [👁 표시]      │
│  전송 시점            보고서 생성 즉시                  │
│                                                         │
│               [연결 테스트]          [저장]             │
└─────────────────────────────────────────────────────────┘

┌─ 전송 이력 ─────────────────────────────────────────────┐
│  날짜        │  보고서             │  상태               │
│  2026-06-23  │  26주차 보고서      │  ✓ 성공             │
│  2026-06-16  │  25주차 보고서      │  ✓ 성공             │
│  2026-06-09  │  24주차 보고서      │  ✕ 실패 (연결 오류) │
└─────────────────────────────────────────────────────────┘
```

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" Slack 전송 설정 화면을 HTML + Tailwind CSS로 만들어줘.

[레이아웃]
- 좌측 사이드바(설정 > Slack 활성) + 우측 콘텐츠 (max-w-lg)

[콘텐츠 구성]
1. 제목 "Slack 전송 설정"

2. 설정 카드:
   - 전송 활성화 토글 (현재 ON)
   - 채널명 인풋: "#ai-market-watch"
   - Webhook URL 인풋: "https://hooks.slack.com/..." (마스킹 처리, 눈 아이콘)
   - 전송 시점: "보고서 생성 즉시"
   - "연결 테스트" Secondary 버튼
   - "저장" Primary 버튼

3. 전송 이력 섹션
   - 최근 전송 3건 (날짜 + 보고서명 + 상태)
   - 2026-06-23 / 26주차 보고서 / 성공
   - 2026-06-16 / 25주차 보고서 / 성공
   - 2026-06-09 / 24주차 보고서 / 실패 (연결 오류)

[스타일]
- 인풋 focus: border #60269E
- 성공: text #18A957, 실패: text #D92D20
- 마스킹된 URL: letter-spacing wide
```

---

### SET-006 · 처리 이력 조회

**목적**: 수집 실행 결과와 Claude API 호출 이력을 확인

**구성 요소**

```
┌─ 탭 ────────────────────────────────────────────────────┐
│  [수집 로그 ●]  [LLM 처리 이력]                        │
└─────────────────────────────────────────────────────────┘

┌─ 필터 바 ───────────────────────────────────────────────┐
│  [기간: 오늘▼]  [상태: 전체▼]  [검색...]               │
└─────────────────────────────────────────────────────────┘

┌─ 수집 로그 테이블 ──────────────────────────────────────┐
│  실행 시간  │ 소스  │ 수집  │ 상태  │ 소요  │ 오류      │
├─────────────┼───────┼───────┼───────┼───────┼───────────┤
│  06-25 09:00│ 네이버│  47건 │ ✓성공 │ 12.3s │  -        │
│  06-25 09:00│ 금융위│   8건 │ ✓성공 │  3.1s │  -        │
│  06-24 09:00│ DART  │   0건 │ ✕실패 │ 30.0s │ timeout   │ ← 행 전체 빨간 배경
│  ...        │       │       │       │       │           │
└─────────────┴───────┴───────┴───────┴───────┴───────────┘
```

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 처리 이력 조회 화면을 HTML + Tailwind CSS로 만들어줘.

[레이아웃]
- 좌측 사이드바(설정 > 로그 활성) + 우측 콘텐츠

[콘텐츠 구성]
1. 탭: [수집 로그] [LLM 처리 이력] (수집 로그 활성)

2. 필터 바: 기간 선택 + 상태 필터(전체/성공/실패) + 검색

3. 수집 로그 테이블
   컬럼: 실행 시간 | 소스 | 수집 건수 | 상태 | 소요 시간 | 오류 메시지
   샘플 8행:
   - 2026-06-25 09:00 / 네이버 뉴스 API / 47건 / 성공 / 12.3s / -
   - 2026-06-25 09:00 / 금융위원회 RSS / 8건 / 성공 / 3.1s / -
   - 2026-06-25 09:00 / OpenDART API / 12건 / 성공 / 8.7s / -
   - 2026-06-25 09:00 / Anthropic 블로그 / 3건 / 성공 / 5.2s / -
   - 2026-06-24 09:00 / 네이버 뉴스 API / 52건 / 성공 / 11.8s / -
   - 2026-06-24 09:00 / OpenDART API / 0건 / 실패 / 30.0s / Connection timeout
   - 2026-06-23 09:00 / 네이버 뉴스 API / 38건 / 성공 / 10.1s / -
   - 2026-06-23 09:00 / Anthropic 블로그 / 2건 / 성공 / 4.8s / -

[스타일]
- 성공: bg #E6F7F5, text #00AF9A 배지
- 실패: bg #FFF5F5, text #D92D20 배지
- 오류 메시지: JetBrains Mono, text-red-600
- 테이블 헤더: uppercase text-xs
- 실패 행: bg #FFF5F5 (행 전체)
```

---

### SET-007 · 기업 관리 (소급 문서화)

> 이미 `templates/setting/organizations.html` · `_organizations.html`로 구현·운영 중인 화면이다. 별도 설계 없이 구현부터 됐던 화면이라 문서가 비어 있었고, SET-008(기술 주제 관리)을 SET-007과 동일한 구조로 미러링하기 위해 이번에 실제 구현 기준으로 소급 문서화한다. 이후 이 화면을 변경할 때는 실제 템플릿이 아니라 이 문서를 최신 기준으로 갱신할 것.

**목적**: 뉴스 자동 매핑(`services/collector.py`)에 쓰이는 기업(Organization) 마스터 데이터를 유형별(금융사/보험사/AI)로 관리하고, 기존에 수집된 뉴스에 대해 매핑을 수동으로 재실행

**구성 요소**

```
┌─ 상단 바 ──────────────────────────────────────────────────────┐
│  [전체 24] [금융사 12] [보험사 6] [AI 6]      [⟳ 기업 재매핑] [+ 기업 추가] │
│  (유형 탭, 클릭 시 Alpine activeTab으로 아래 섹션만 필터링)     │
└──────────────────────────────────────────────────────────────────┘

┌─ 금융사 12개 ───────────────────────────────────────────────────┐
│  기업명           │  별칭            │  활성  │      │
├────────────────────┼──────────────────┼────────┼──────┤
│  KB국민은행        │  국민은행, KB    │   ●   │ ✎ 🗑 │
│  신한은행          │  신한            │   ●   │ ✎ 🗑 │
│  ...                                                    │
└────────────────────────────────────────────────────────┘

┌─ 보험사 6개 ──────────────────────────────────────────┐
│  삼성생명          │  —               │   ●   │ ✎ 🗑 │
│  ...                                                    │
└────────────────────────────────────────────────────────┘

┌─ AI 6개 ──────────────────────────────────────────────┐
│  Anthropic         │  앤트로픽        │   ●   │ ✎ 🗑 │
│  ...                                                    │
└────────────────────────────────────────────────────────┘
```

**기업 추가/수정 Modal** ("+ 기업 추가" 또는 ✎ 클릭 시)
```
┌─ 기업 추가 / 기업 수정 ─────────────┐
│  기업명 * [___________________]     │
│  유형   * [유형 선택 ▼]             │
│  별칭     [___________________]     │
│           (쉼표로 구분, 예: 국민은행, KB) │
│                                      │
│                     [취소]  [저장]  │
└──────────────────────────────────────┘
```

**인터랙션 상세**
- 유형 탭 필터: Alpine `x-data="{ activeTab: '전체' }"`, 탭 클릭 시 서버 재요청 없이 클라이언트에서 `x-show`로 섹션 토글(HTMX 요청 없음 — 순수 클라이언트 상태).
- 유형별 섹션(금융사/보험사/AI)은 각각 독립 테이블로 렌더링되며, 뱃지 색상은 디자인 시스템 규칙 그대로: 금융사 `bg-blue-100 text-blue-700`, 보험사 `bg-[#E6F7F5] text-[#00AF9A]`, AI `bg-[#F3EAFB] text-primary`.
- 추가/수정 모달은 `x-show="modalOpen" x-cloak x-transition` 조합을 이미 갖추고 있다 — FOUC 버그 없음, 새 화면(SET-008) 설계 시 그대로 재사용.
- 저장/토글/삭제 모두 `hx-post` + `hx-target="#org-table"` + `hx-swap="innerHTML"` + `hx-include="[name=csrfmiddlewaretoken]"` 조합으로 유형별 섹션 전체를 다시 그린다(부분 테이블만 갱신하지 않고 `_organizations.html` 전체를 swap).
- 수정 버튼은 별도 상세 조회 요청 없이, 이미 렌더링된 Django 컨텍스트 값을 Alpine `editOrg` 객체로 인라인 주입해(`@click="editOrg={id:..., name:'...', ...}"`) 모달 폼을 채운다(요청 왕복 없음).
- 삭제는 `hx-confirm`으로 브라우저 네이티브 확인창을 띄우고, 삭제 시 뉴스와의 M2M 연결도 함께 해제된다는 안내 문구를 포함.
- "기업 재매핑" 버튼은 `hx-post` + `hx-target="#remap-result"`로 결과 텍스트(`N개 뉴스 기업 재매핑 완료`)만 별도 스팟에 갱신 — 목록 테이블 자체는 다시 그리지 않는다(재매핑은 이미 존재하는 기업의 M2M 연결만 갱신하고 목록 자체는 안 바뀌므로).

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 기업 관리 화면을 HTML + Tailwind CSS로 만들어줘.

[레이아웃]
- 좌측 사이드바(설정 > 기업 활성) + 우측 콘텐츠

[콘텐츠 구성]
1. 상단 바: 유형 탭 필터(전체/금융사/보험사/AI, 각 탭에 개수 pill) + 우측 "기업 재매핑"(teal) / "기업 추가"(primary) 버튼

2. 유형별 섹션 3개(금융사/보험사/AI), 섹션 헤더는 유형 뱃지 + 개수 + 구분선
   각 섹션은 테이블(기업명 | 별칭(태그 목록) | 활성 토글 | 수정·삭제 아이콘)
   샘플 — 금융사: KB국민은행(국민은행,KB), 신한은행(신한), 우리은행
         보험사: 삼성생명, 교보생명
         AI: Anthropic(앤트로픽), OpenAI, Google DeepMind

3. 기업 추가/수정 모달: 기업명(필수) + 유형 선택(필수) + 별칭(콤마 구분) 입력 + 취소/저장

[스타일]
- 유형 뱃지: 금융사 #EEF2FF/#1D4ED8 계열 blue, 보험사 #E6F7F5/#00AF9A, AI #F3EAFB/#60269E
- 활성 토글: 활성 bg #60269E, 비활성 bg #E5E5E5
- 별칭: 회색 태그 pill (bg #F9F9F7, border #E5E5E5)
- 모달: 배경 어둡게 오버레이 + 흰 카드 rounded-[10px]
```

---

### SET-008 · 기술 주제 관리

**목적**: 뉴스 자동 매핑(`services/collector.py`의 `_link_tech_topics`)에 쓰이는 기술 주제(TechTopic) 마스터 데이터를 관리하고, 기존에 수집된 뉴스에 대해 매핑을 수동으로 재실행. `TechTopic`은 `org_type` 같은 하위 유형 구분이 없는 평면 어휘이므로, SET-007(기업 관리)의 유형별 탭·그룹핑 구조는 가져오지 않고 단일 목록으로 관리한다.

**모델 근거** (`apps/setting/models.py`, 이미 구현됨)
```python
class TechTopic(models.Model):
    name      = models.CharField(max_length=100, unique=True)
    aliases   = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    class Meta:
        ordering = ["name"]
```
마이그레이션 시드 10개(RAG, 온톨로지, AI Ready Data 등)가 이미 존재. `services/collector.py`에 `remap_tech_topics()`도 이미 구현돼 있어(`remap_organizations()`와 동일 패턴), 이번 화면은 새 비즈니스 로직 없이 기존 서비스 함수를 뷰에 연결하기만 하면 된다.

**구성 요소**

```
┌─ 상단 바 ────────────────────────────────────────────────────┐
│  기술 주제 관리  10개          [⟳ 기술 주제 재매핑] [+ 주제 추가] │
└────────────────────────────────────────────────────────────────┘

┌─ 기술 주제 테이블 (bg-white shadow-sm rounded-[10px]) ─────────┐
│  주제명          │  별칭                │  연결 뉴스 │  활성 │      │
├───────────────────┼───────────────────────┼───────────┼───────┼──────┤
│  RAG              │  검색증강생성, RAG    │   12건    │  ●   │ ✎ 🗑 │
│  온톨로지         │  Ontology             │    3건    │  ●   │ ✎ 🗑 │
│  AI 에이전트      │  AI Agent, 에이전트   │   11건    │  ●   │ ✎ 🗑 │
│  AI 거버넌스      │  —                    │    2건    │  ●   │ ✎ 🗑 │
│  AI Ready Data    │  —                    │    1건    │  ○   │ ✎ 🗑 │
│  ...(시드 10개 순서대로, name 오름차순)                          │
└────────────────────────────────────────────────────────────────┘
```

**기술 주제 추가/수정 Modal** ("+ 주제 추가" 또는 ✎ 클릭 시)
```
┌─ 기술 주제 추가 / 기술 주제 수정 ───┐
│  주제명 * [___________________]     │
│  별칭     [___________________]     │
│           (쉼표로 구분, 예: RAG, 검색증강생성) │
│                                      │
│                     [취소]  [저장]  │
└──────────────────────────────────────┘
```
SET-007 모달에서 "유형" select 필드만 제거한 형태 — 나머지 필드(주제명/별칭) 구성과 유효성 검사(주제명 필수)는 동일.

**SET-007과의 차이점 요약**
| 항목 | SET-007 (기업) | SET-008 (기술 주제) |
|---|---|---|
| 그룹핑 | 유형별 탭(전체/금융사/보험사/AI) | 없음 — 단일 테이블 |
| 테이블 컬럼 | 기업명, 별칭, 활성, 액션 | 주제명, 별칭, **연결 뉴스 건수**, 활성, 액션 |
| 모달 필드 | 이름, 유형(select), 별칭 | 이름, 별칭 |
| 정렬 | `org_type, name` | `name` (모델 `Meta.ordering` 그대로) |

"연결 뉴스" 컬럼을 SET-007에는 없던 항목으로 새로 추가한 이유: TechTopic은 유형 그룹핑이 없어 한 화면에 10개 안팎이 평평하게 나열되는데, 시드 데이터 다수가 아직 연결 뉴스 0건인 상태(ALL-001 대시보드의 "기술 주제별 언급 건수" 카드가 0건 주제를 제외하는 것과 동일한 배경)라 목록만으로는 어떤 주제가 실제로 쓰이고 있는지 알기 어렵다. 건수를 바로 보여주면 비활성화·삭제 판단(예: "이 주제는 몇 달째 0건이니 비활성화할지" 같은 운영 판단)을 이 화면 안에서 바로 내릴 수 있다.

**인터랙션 상세** (SET-007과 동일 패턴 재사용, 신규 인터랙션 없음)
- 추가/수정 모달은 SET-007과 동일하게 `x-show="modalOpen" x-cloak x-transition`을 반드시 함께 붙인다 — 최우선 점검 항목.
- 저장/토글/삭제는 `hx-post` + `hx-target="#tech-topic-table"` + `hx-swap="innerHTML"` + `hx-include="[name=csrfmiddlewaretoken]"` 조합.
- 수정 버튼은 SET-007과 동일하게 요청 왕복 없이 Alpine `editTopic` 객체에 Django 컨텍스트 값을 인라인 주입.
- 삭제는 `hx-confirm`으로 확인창, "뉴스와의 연결도 함께 해제됩니다" 안내 문구 포함(SET-007과 동일 문구 패턴, "기업"→"기술 주제"로 치환).
- "기술 주제 재매핑" 버튼은 `hx-post` + `hx-target="#tech-topic-remap-result"`로 결과 텍스트만 별도 갱신.

**구현 참고 — PE에게 넘길 스펙 (실제 코드는 PE가 작성)**

`apps/setting/views.py`의 기업 관리 뷰(`_org_context`/`organizations`/`organization_save`/`organization_toggle`/`organization_delete`/`remap_now`)와 완전히 동일한 패턴으로 아래를 구현하면 된다. 그룹핑이 없으므로 `_org_context()`의 `grouped` 로직만 빠진다.

- `_tech_topic_context()`: `TechTopic.objects.annotate(news_count=Count("news", distinct=True)).all()`(모델 `Meta.ordering = ["name"]` 그대로 적용됨) + `total_count`. `TechTopic.news`는 `News.tech_topics`의 `related_name="news"`라 `Organization.news`와 동일한 방식으로 역참조 가능(대시보드 `_build_tech_topic_counts()`에서 이미 검증된 패턴, `docs/design.md` ALL-001 절 참고).
- `tech_topics(request)`: `setting/tech_topics.html` 렌더, `setting_menu`에 신규 키 `"tech_topics"` 추가.
- `tech_topic_save(request)`: `POST`로 `topic_id`(hidden, 수정 시), `name`, `aliases`(콤마 분리 문자열 → list) 받음. `organization_save`와 동일하되 `org_type` 필드 없음.
- `tech_topic_toggle(request, pk)` / `tech_topic_delete(request, pk)`: `organization_toggle`/`organization_delete`와 동일 패턴.
- `remap_tech_topics_now(request)`: `services.collector.remap_tech_topics()`(이미 구현됨) 호출 후 결과 렌더. **주의**: 기존 `setting/_remap_result.html`은 "{{ remap_count }}개 뉴스 기업 재매핑 완료"로 "기업"이 하드코딩돼 있어 그대로 재사용하면 기술 주제 재매핑에도 "기업"이라는 문구가 뜨는 오류가 생긴다. 새 partial `setting/_tech_topic_remap_result.html`("{{ remap_count }}개 뉴스 기술 주제 재매핑 완료")을 별도로 만들거나, 기존 partial에 `entity_label` 컨텍스트 변수를 추가해 두 화면이 함께 재사용하도록 리팩터링 — 방식은 PE 판단.
- `urls.py`: `tech-topics/`, `tech-topics/save/`, `tech-topics/<int:pk>/toggle/`, `tech-topics/<int:pk>/delete/`, `tech-topics/remap/` 5개 경로. URL name은 기업 관리 명명 규칙(`setting_organization_*`)을 그대로 따라 `setting_tech_topic_*`(예: `setting_tech_topics`, `setting_tech_topic_save`, `setting_tech_topic_toggle`, `setting_tech_topic_delete`, `setting_remap_tech_topics_now`).
- 템플릿: `templates/setting/tech_topics.html`(SET-007의 `organizations.html`에서 유형 탭·`org_types` 관련 마크업만 제거) + `templates/setting/_tech_topics.html`(SET-007의 `_organizations.html`에서 유형별 그룹 루프를 없애고 단일 테이블로, `연결 뉴스` 컬럼 추가).

**설정 사이드바 메뉴 추가 위치**

`apps/setting/views.py`의 `_setting_menu()` 리스트에 "기업" 항목 바로 다음에 삽입한다(수집 파이프라인이 참조하는 두 개의 큐레이션 마스터 데이터 — 기업/기술 주제 — 를 나란히 배치해 성격이 비슷한 메뉴끼리 인접하도록 구성).

```python
items = [
    {"label": "데이터 소스", "icon": "database",      "name": "setting_sources",       "key": "sources"},
    {"label": "키워드",     "icon": "tag",            "name": "setting_keywords",      "key": "keywords"},
    {"label": "기업",       "icon": "building-2",     "name": "setting_organizations", "key": "organizations"},
    {"label": "기술 주제",  "icon": "cpu",             "name": "setting_tech_topics",   "key": "tech_topics"},   # 신규
    {"label": "프롬프트",   "icon": "file-text",      "name": "setting_prompts",       "key": "prompts"},
    {"label": "스케줄",     "icon": "clock",          "name": "setting_schedule",      "key": "schedule"},
    {"label": "Slack",      "icon": "slack",          "name": "setting_slack",         "key": "slack"},
    {"label": "로그",       "icon": "scroll-text",    "name": "setting_logs",          "key": "logs"},
]
```
아이콘은 Lucide `cpu`(기술·시스템을 가리키는 라인 아이콘, 기존 프로젝트에 없는 아이콘이므로 `templates/base.html`의 Lucide 로드 방식이 아이콘 이름 기반 동적 로딩이면 그대로 동작 — PE가 실제 렌더링 확인 필요)로 제안. 다른 대안이 필요하면 `tags`(키워드 아이콘과 겹쳐 지양) 대신 `layers`나 `sparkles`도 검토 가능.

**화면 ID 확인**: PM이 확정한 SET-008(신규 화면 ID) 방식이 맞다고 판단한다. TechTopic은 Organization과 필드 구조(그룹핑 유무, 컬럼 구성)가 달라 SET-007에 탭으로 얹으면 "유형 탭"이라는 기존 개념과 충돌하고(TechTopic은 유형이 없음), 모달 폼도 필드 하나 차이지만 조건부 렌더링이 늘어 오히려 복잡해진다. 사이드바 메뉴도 항목당 URL 하나인 flat 구조라 새 메뉴 항목을 하나 추가하는 비용이 낮다. 별도 화면으로 분리하는 쪽이 SET-006(로그, 동일 화면 내 탭 2개)처럼 "한 화면 안에서 성격이 같은 하위 리소스를 넘나드는" 경우와도 성격이 다르다 — 이번 건은 서로 다른 두 모델의 독립된 CRUD이므로 별도 화면이 자연스럽다.

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 기술 주제 관리 화면을 HTML + Tailwind CSS로 만들어줘.

[레이아웃]
- 좌측 사이드바(설정 > 기술 주제 활성) + 우측 콘텐츠

[콘텐츠 구성]
1. 상단 바: 제목 "기술 주제 관리" + 옆에 회색 개수 pill "10개" + 우측 "기술 주제 재매핑"(teal) / "주제 추가"(primary) 버튼

2. 단일 테이블 (주제명 | 별칭(태그 목록) | 연결 뉴스(건수) | 활성 토글 | 수정·삭제 아이콘)
   샘플 10행:
   - RAG (검색증강생성, RAG) / 12건 / 활성
   - 온톨로지 (Ontology) / 3건 / 활성
   - AI 에이전트 (AI Agent, 에이전트) / 11건 / 활성
   - AI 거버넌스 (—) / 2건 / 활성
   - AI Ready Data (—) / 1건 / 비활성
   - 생성형 AI (Generative AI, GenAI) / 0건 / 활성
   - LLM (거대언어모델, Large Language Model) / 0건 / 활성
   - 멀티모달 (Multimodal) / 0건 / 활성
   - AI 에이전틱 워크플로우 (Agentic Workflow) / 0건 / 활성
   - 파운데이션 모델 (Foundation Model) / 0건 / 활성

3. 기술 주제 추가/수정 모달: 주제명(필수) + 별칭(콤마 구분) 입력 + 취소/저장

[스타일]
- 별칭: 회색 태그 pill (bg #F9F9F7, border #E5E5E5)
- 연결 뉴스: 숫자만 담백하게 표시, 0건은 text-gray-300으로 톤 다운
- 활성 토글: 활성 bg #60269E, 비활성 bg #E5E5E5
- 모달: 배경 어둡게 오버레이 + 흰 카드 rounded-[10px], SET-007 모달과 동일 톤이되 유형 select 필드 없음
```

---

### GRAPH-001 · 지식그래프 (소급 문서화)

> 이미 `apps/graph/`(`templates/graph/index.html`, `_org_panel.html`)로 구현·배포 중인 화면이다. 별도 설계 없이 구현부터 됐고 사이드바에도 정식 메뉴로 떠 있었지만 화면 ID·문서가 전혀 없어 코드-문서 정합성이 깨져 있었다. PM이 `docs/planning.md`("지식그래프 화면 ID 부여" 절)에서 신규 독립 카테고리 `GRAPH-001`을 확정함에 따라, SET-007/008 소급 문서화와 동일한 방식으로 실제 구현 기준으로 기록한다. 이후 이 화면을 변경할 때는 템플릿이 아니라 이 문서를 최신 기준으로 갱신할 것.
>
> **(2026-07 갱신)** `docs/planning.md`의 "지식그래프 개선 로드맵" 1단계(엣지 근거뉴스)와 "대시보드·지식그래프 공통 기간 필터 정책"이 확정됨에 따라, 아래 내용에 (1) 엣지 클릭 → 기업 쌍(pair) 교집합 뉴스 패널, (2) 기간 필터(전체/최근 30일/최근 7일, 기본값 최근 7일 — 대시보드와 통일, 사용자 결정)를 반영했다. 템플릿(`templates/graph/index.html`, `_org_panel.html`, 신규 `_edge_panel.html`)은 PD가 직접 구현 완료했고, 백엔드(뷰·URL·쿼리)는 아래 "1단계 백엔드 스펙(PE 인계)"에 정리된 대로 PE가 구현해야 한다 — **이 문서 갱신 시점에는 뷰가 아직 이 스펙을 반영하지 않은 상태이므로, 템플릿은 더미 컨텍스트 변수(`selected_period`, `org_a`/`org_b`, `news_count` 등)를 가정하고 작성돼 있다.**
>
> **(2026-07 추가 갱신 — 2단계 관계 라벨링)** `docs/planning.md` "지식그래프 개선 로드맵" 2단계(RA 수동 관계 라벨링) 착수 스펙이 확정됨에 따라, `_edge_panel.html`에 "관계" 라벨 표시/입력 UI를 PD가 정적 마크업 수준으로 구현 완료했다(아래 "2단계 관계 라벨 UI 스펙" 절). `OrgRelation` 모델과 저장 뷰(`graph_edge_label_save` 가칭)는 **아직 PE가 구현하지 않았다** — 그 결과 이 문서 갱신 시점에는 `relation` 컨텍스트 변수가 항상 비어 있어 화면은 항상 "관계 미분류" 상태로만 보인다(정상 동작). PE가 모델·마이그레이션·저장 뷰·`graph_edge_panel`의 `relation` 컨텍스트 주입을 구현하면 그대로 동작한다.
>
> **(2026-07-28 추가 갱신 — 라벨 있는 엣지 상시 표시 + 캔버스 라벨 텍스트)** `docs/planning.md`의 "라벨 있는 엣지 상시 표시"(기간 필터 예외)·"라벨 텍스트 캔버스 상시 렌더"(스코프 제외 결정 번복) 두 정책이 확정됨에 따라, `templates/graph/index.html`의 D3 렌더링 로직을 PD가 직접 구현 완료했다(아래 "기간 내 실존 엣지의 라벨 표시 + 캔버스 라벨 텍스트 렌더" 절). `apps/graph/views.py`의 `graph()` 뷰는 **아직 노드/엣지 합집합 로직과 `has_label`/`label` 필드를 채우지 않은 상태**라, 이 문서 갱신 시점에는 모든 엣지가 `has_label=undefined`(falsy)로 폴백해 기존과 동일한 회색 실선으로만 보인다(정상 동작, 에러 없음). PE가 `graph()` 뷰에 두 필드와 합집합 로직을 채우면 그대로 동작한다.
>
> **(2026-07-28 재정정 — 라벨 강제 표시 정책 철회)** 위 문단의 "기간 필터 예외"·"노드/엣지 합집합 로직"은 사용자가 "기간 필터 신뢰성이 없다"는 이유로 이후 명확히 철회를 요청했고, `apps/graph/views.py`의 `graph()` 뷰도 이미 그 철회를 반영해 구현됐다(합집합·`value=0` 강제 삽입·`_edge_allowed` 예외가 전부 제거됨 — `docs/planning.md` "지식그래프: 라벨 강제 표시 롤백" 참고). 현재 `has_label`/`label` 필드는 위 문단이 서술한 "합집합" 방식이 아니라 **"선택 기간 내 실제 공동언급(≥1)으로 이미 존재하는 엣지에만 라벨 정보를 얹는" 방식**으로 구현·배포돼 있다. 캔버스 시각 렌더(점선+흰 pill) 자체는 그대로 유효하며, 그 적용 대상만 실존 엣지로 좁혀졌다. 상세는 아래 "기간 내 실존 엣지의 라벨 표시 + 캔버스 라벨 텍스트 렌더" 절의 정정 내용 참고.

**목적**: 활성 기업(Organization) 간 "같은 뉴스에 함께 등장" 관계를 force-directed 그래프로 시각화해, 개별 기업·뉴스 단위로는 보이지 않는 업계 관계망(어떤 금융사·보험사가 어떤 AI 기업과 자주 엮이는지)을 한눈에 파악하는 분석 화면. 조회 전용이며 CRUD가 없다(SET 화면군과 성격이 다른 이유).

**라우트**
| 경로 | 뷰 | 역할 |
|---|---|---|
| `/graph/?period=all\|30d\|7d` | `apps.graph.views.graph` | 메인 화면. 전체 그래프(노드+엣지) 렌더. `period` 쿼리파라미터로 기간 필터(기본값 `7d`=최근 7일, 대시보드와 통일) — 선택은 `<a href="?period=...">` 전체 페이지 GET 재로드(아래 "왜 HTMX가 아닌 페이지 재로드인가" 참고) |
| `/graph/orgs/<int:pk>/panel/?period=...` | `apps.graph.views.graph_org_panel` | 노드 클릭 시 HTMX로 로드되는 우측 패널 프래그먼트(독립 화면 아님 — `GRAPH-001`의 하위 프래그먼트, NEWS-001의 `_list.html`과 동일 관례). `period`는 메인 화면에서 선택된 값을 그대로 전달받아야 함(기간 정합성 계약) |
| **(신규)** `/graph/edges/<int:pk_a>/<int:pk_b>/panel/?period=...` | `apps.graph.views.graph_edge_panel` (미구현 — PE) | 엣지(기업 쌍) 클릭 시 HTMX로 로드되는 교집합 근거뉴스 패널. `pk_a`/`pk_b`는 어느 순서로 와도 뷰 내부에서 정규화(작음/큼)해 처리. 독립 화면 아님, 위와 동일 관례. URL name에 `graph`가 들어가 `templates/base.html`의 사이드바 활성 판정(`'graph' in request.resolver_match.url_name`)이 별도 수정 없이 그대로 적용됨 |
| **(신규, 2단계)** `/graph/edges/<int:pk_a>/<int:pk_b>/label/?period=...` (`POST`) | `apps.graph.views.graph_edge_label_save` (미구현 — PE, 이름은 가칭) | 쌍 패널의 "관계" 편집 폼이 제출하는 저장 엔드포인트. `_edge_panel.html`이 이 경로를 **하드코딩된 문자열**로 `hx-post`에 이미 심어뒀다(`{% url %}` 미사용 이유는 아래 "2단계 관계 라벨 UI 스펙" 5번 참고). `pk_a`/`pk_b` 정규화·`OrgRelation.objects.update_or_create`·응답으로 갱신된 `_edge_panel.html` 반환까지는 `docs/planning.md` "2단계 착수 스펙 > PE 인계 항목"에 상세 정의돼 있다 |

**구성 요소**

```
┌ 기간 [전체|최근 30일|●최근 7일] (세그먼트 pill, <a href="?period=..."> 전체 페이지 GET 재로드, 기본값 최근 7일) ─────────────┐
└───────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ 그래프 캔버스 (flex-1, bg-white shadow-sm rounded-[10px]) ─────────┐┌─ 기업/쌍 패널 (w-72) ┐
│ ┌ 범례(좌상단, 클릭 토글) ┐        ┌ 통계(우상단) ┐                  ││┌─ bg-white shadow-sm ┐│
│ │● 금융사 ● 보험사 ● AI  │        │기업 24개·연결│                  │││ [금융사] 뱃지        ││
│ └────────────────────────┘        │  9개(선택된  │                  │││ KB국민은행           ││
│                                    │  기간 기준)  │                  │││ 국민은행, KB (별칭)  ││
│              ●AI기업A              └──────────────┘                  │││──────────────────── ││
│             ╱│  ╲                                                    │││ 관련 뉴스   전체 23건││
│      금융사●═┿═══●보험사X   (선 굵기 = 공동등장 가중치, 클릭 가능)  │││   중 10건            ││
│             ╲│  ╱   ↑ 얇은 시각선 위에 14px 투명 히트라인을 겹쳐서   │││ · 기사 제목 1  MM.DD ││
│              ●AI기업B  클릭 영역을 넓힘(선 자체는 그대로 얇게 유지)   │││   [금융사][AI] 뱃지  ││
│  (드래그로 위치 이동, 줌/팬, 빈 공간 클릭 시 하이라이트 해제)         │││ · 기사 제목 2 ...    │││
│                                                                       ││└──────────────────── ││
│  ※ 기업/연결 0개면 기간별 안내 문구 분기(아래 "빈 상태 문구" 참고)   ││ (미선택 시: 마우스     ││
│                                                                       ││  포인터 아이콘 +      ││
│                                                                       ││  "기업 노드 또는      ││
│                                                                       ││  연결선을 클릭하면    ││
│                                                                       ││  관련 뉴스를 볼 수    ││
│                                                                       ││  있습니다." 안내)      ││
└───────────────────────────────────────────────────────────────────┘└──────────────────────┘

# 엣지 클릭 시 우측 패널 (기업 쌍 뷰 — 노드 클릭 뷰와 다른 프래그먼트)
┌─ 기업/쌍 패널 (w-72) ─┐
│ KB국민은행 × Anthropic │  ← "A × B 함께 언급된 뉴스 N건" (N == 엣지 value, 검증 포인트)
│ 함께 언급된 뉴스 3건    │
│ [금융사]KB국민은행      │
│ [AI]Anthropic          │
│──────────────────────  │
│ 관계                   │  ← 2단계 신규 (보기 상태 예시)
│ (관계 미분류)   [+라벨추가]  ※ 라벨 있으면: (outline pill)라벨명  [✎수정]
│                            + 회색 설명 텍스트(선택)
│──────────────────────  │
│ (편집 상태 — "라벨 추가/수정" 클릭 시)
│ [입력: 자유텍스트______]  ← list=datalist(5개 힌트)
│ (기술협업)(투자)(공급계약)(인수합병)(업무협약(MOU))  ← 클릭 시 인풋 자동 채움
│ [설명 textarea(선택)___]
│               [취소] [저장]  ← 저장은 HTMX POST, #org-panel 통째 갱신
│──────────────────────  │
│ 근거 뉴스 (컷오프 없음, 전량 노출)
│ · 기사 제목 1   MM.DD  │
│   [금융사][AI] 뱃지    │
│ · 기사 제목 2   MM.DD  │
│ · 기사 제목 3   MM.DD  │
└────────────────────────┘
```

**캔버스 라벨 있는 엣지 표기(2026-07-28 추가)** — 위 ASCII 다이어그램에는 지면상 생략했지만, 실제 캔버스에서 라벨(`OrgRelation.label`)이 붙은 엣지는 다음과 같이 그려진다: `금융사●┄┄[기술협업]┄┄●AI기업`처럼 **점선 + primary색(`#60269E`) 선** 위, 엣지 중점에 **흰 배경 + primary 테두리 pill**로 라벨 텍스트가 클릭 없이 항상 떠 있다. 미분류 엣지(대다수)는 기존과 동일한 회색 실선이며 텍스트가 없다. 상세 스펙은 아래 "라벨 있는 엣지 상시 표시 + 캔버스 라벨 텍스트 렌더" 절 참고.

**빈 상태 문구 (기간 인지형)** — 기업/연결이 0개인 두 케이스 모두, `selected_period`가 `all`이면 기존 문구("뉴스가 수집되면 기업 간 연결이 표시됩니다.")를 유지하고, `30d`/`7d`면 "선택한 기간에는 뉴스가 있는 기업이 없습니다." / "선택한 기간에는 기업 간 연결이 없습니다." + "다른 기간을 선택해보세요."로 분기한다. 전체 기간에서는 보이던 노드가 짧은 기간으로 좁히면 뉴스 0건이 되어 자연스럽게 사라질 수 있는데(현재도 `news_count__gt=0` 조건으로 동일하게 걸러짐), 문구를 기간 인지형으로 분기해두지 않으면 "데이터가 원래 없다"는 오해를 줄 수 있어 PD 판단으로 추가했다.

**데이터 모델 (`apps/graph/views.py`)**

- **노드** — `Organization.objects.filter(is_active=True).annotate(news_count=Count("news")).filter(news_count__gt=0)`. 즉 활성 상태이면서 연결된 뉴스가 1건 이상인 기업만 노드로 표시(뉴스 0건인 활성 기업은 그래프에서 제외 — SET-008 "0건 주제 제외"와 동일한 관례). `symbolSize`는 `max(14, min(40, 14 + news_count * 2))`로 14~40px 범위에서 뉴스 건수에 비례.
- **엣지** — 같은 `News`에 2개 이상의 기업이 함께 등장(`organizations__count >= 2`)할 때 모든 쌍(`itertools.combinations`)의 공동등장 횟수를 누적해 가중치(`value`)로 사용. 단 `ALLOWED_TYPE_PAIRS = {frozenset({"금융사","AI"}), frozenset({"보험사","AI"})}` 필터로 **금융사-AI, 보험사-AI 쌍만 허용**하고 금융사-금융사·보험사-보험사·AI-AI·금융사-보험사 조합은 제외한다(업계 관계망이라는 화면 목적상 "동종업계끼리의 단순 동반 언급"보다 "금융/보험이 AI를 어떻게 활용하는가"라는 교차 관계에 집중하기 위한 설계 판단으로 보임).
- 카테고리 인덱스: `CATEGORY_INDEX = {"금융사": 0, "보험사": 1, "AI": 2}` — 노드 JSON의 `category` 필드로 D3 색상 배열 인덱싱에 쓰임.

**1단계 백엔드 스펙 (PE 인계 — `docs/planning.md` "지식그래프 개선 로드맵" 1단계 착수 스펙을 화면 단위로 구체화)**

1. **공통 기간 필터 헬퍼** — 세 뷰(`graph`, `graph_org_panel`, 신규 `graph_edge_panel`) 모두 동일한 필터 로직을 써야 한다(기간 정합성 계약). 기준 필드는 `News.published_at`(발행일, `DateTimeField`), 수집일(`collected_at`) 아님. `request.GET.get("period", "7d")` 값 `"all" | "30d" | "7d"`(그 외 값은 `"7d"`로 폴백)에 대해:
   - `"all"` → 필터 없음(전체, 삭제되지 않고 남은 `News` 전체).
   - `"30d"` → `published_at`이 `[오늘−29일, 오늘]`에 포함(오늘 포함, 자정 경계).
   - `"7d"` → `published_at`이 `[오늘−6일, 오늘]`에 포함.
   - `News` 쿼리셋에는 `published_at__date__gte=start`(및 필요 시 `__lte=오늘`) 형태로 적용. `Organization` 쪽 `annotate(news_count=Count("news"))`처럼 관계를 통해 세는 곳은 `Count("news", filter=Q(news__published_at__date__gte=start))`로 조건부 집계해야 한다(그냥 `.filter()`를 annotate 앞에 걸면 JOIN이 필터링돼 다른 집계에도 영향을 줄 수 있으니 주의).
2. **`graph(request)` 변경** — `period = request.GET.get("period", "7d")`로 받아 (a) 노드 `news_count` annotate에 기간 조건부 `Count` 적용, (b) 엣지 가중치 집계에 쓰는 `News` 베이스 쿼리셋에 기간 필터 적용. `render` 컨텍스트에 `"selected_period": period` 추가(템플릿의 pill 활성 상태·`CURRENT_PERIOD` JS 변수에 사용됨 — 이미 템플릿에 반영돼 있음, 뷰만 없는 상태).
3. **`graph_org_panel(request, pk)` 변경** — `period` 쿼리파라미터를 받아 `org.news` 쿼리셋에 동일 필터 적용. 컷오프는 유지하되(`[:10]`) **자르기 전에 전체 건수를 세어 `total_count`로 함께 넘긴다**(템플릿이 `{% if total_count > 10 %}전체 {{ total_count }}건 중 10건{% endif %}`으로 잘림을 표기하도록 이미 반영돼 있음 — PM이 준 두 선택지 중 "컷오프 유지 + 명시" 쪽으로 PD가 결정한 것, 근거는 아래 "PD 판단 기록" 참고).
4. **신규 `graph_edge_panel(request, pk_a, pk_b)`** — URL `graph/edges/<int:pk_a>/<int:pk_b>/panel/`.
   ```python
   def graph_edge_panel(request, pk_a, pk_b):
       pk_a, pk_b = sorted((pk_a, pk_b))  # 정규화, 2단계 OrgRelation의 org_a.pk < org_b.pk 규칙과 동일
       org_a = get_object_or_404(Organization, pk=pk_a)
       org_b = get_object_or_404(Organization, pk=pk_b)
       period = request.GET.get("period", "7d")

       # 반드시 두 번 체이닝한 .filter()로 교집합(AND)을 구현한다 — organizations__in=[a, b] 등
       # 단일 필터는 합집합(OR)이 되어 "둘 중 하나만 있어도 걸리는" 오답을 낸다.
       news_qs = (
           News.objects
           .filter(organizations=org_a)
           .filter(organizations=org_b)
       )
       news_qs = _apply_period_filter(news_qs, period)  # 위 공통 헬퍼, published_at 기준
       news_list = news_qs.prefetch_related("organizations").order_by("-published_at").distinct()
       # distinct() 필요: 두 번의 M2M 체이닝 필터가 각각 JOIN을 만들어 중복 행이 생길 수 있음

       return render(request, "graph/_edge_panel.html", {
           "org_a": org_a,
           "org_b": org_b,
           "news_list": news_list,
           "news_count": news_list.count(),
           "selected_period": period,
       })
   ```
   **검증 포인트(PM 명시)**: 같은 `period`에서 이 뷰의 `news_count`는 `graph()`가 계산한 해당 엣지의 `value`와 반드시 일치해야 한다. 두 계산이 같은 근거인 이유 — `graph()`의 엣지 가중치는 "두 기업이 모두 태깅된 서로 다른 `News`의 개수"를 `combinations`로 집계한 것이고, 여기 `news_count`도 정확히 "두 기업이 모두 태깅된 `News`의 개수"이므로 같은 `period` 필터 하에서 두 숫자는 항상 같아야 한다. **컷오프는 걸지 않는다**(PM 지시 — 쌍 교집합은 대개 소수라 부담이 없고, 2단계 RA 관계 라벨링 때 근거 전체가 필요).
5. **URL 등록** — `apps/graph/urls.py`에 `path("edges/<int:pk_a>/<int:pk_b>/panel/", views.graph_edge_panel, name="graph_edge_panel")` 추가. `graph`라는 문자열을 포함하는 이름이라 `templates/base.html`의 사이드바 활성 판정 로직은 수정할 필요 없음.

**PD 판단 기록 — 노드 패널 컷오프는 "유지 + 명시"로 결정**: PM이 준 두 선택지(컷오프 제거 vs "전체 N건 중 10건" 명시) 중 후자를 택했다. 이유: "전체" 기간을 선택했을 때 활성도 높은 기업(예: KB국민은행)은 뉴스가 수십~수백 건일 수 있는데, `w-72` 좁은 패널에 전량을 넣으면 스크롤이 지나치게 길어지고 정작 "최근에 무슨 일이 있었는지"를 훑는 목적에는 오히려 방해가 된다. 반면 쌍(엣지) 패널의 교집합은 두 기업이 동시에 등장한 경우로 한정돼 표본이 훨씬 작고, 2단계에서 RA가 관계를 판단하려면 일부만 보고 놓치는 근거가 없어야 하므로 컷오프를 걷어내는 것이 맞다. 두 패널의 성격(개별 기업의 "최근 동향 훑기" vs 쌍의 "근거 전수 검토")이 다르므로 같은 규칙을 억지로 맞추지 않았다.

**시각화 구현 (`templates/graph/index.html`, D3.js v7.8.5 CDN)**

- SVG + `d3.forceSimulation`(link/charge/x/y/collide 5개 force 조합)로 좌표 계산, alpha가 자연 수렴하면 정지(지속적 애니메이션 없음 — 깜빡임 방지).
- 줌/팬: `d3.zoom().scaleExtent([0.2, 4])`.
- 드래그: 노드를 잡아 고정(`fx`/`fy`), 놓으면 시뮬레이션에 복귀.
- 노드 클릭: (1) 클릭한 노드와 인접 노드만 `opacity: 1`, 나머지는 `0.08`로 페이드 — 연결선도 `#60269E`(Primary)로 강조/`#D1D5DB`로 톤다운. (2) 동시에 `htmx.ajax('GET', '/graph/orgs/<pk>/panel/?period=' + CURRENT_PERIOD, {target:'#org-panel', swap:'innerHTML'})`로 우측 패널을 로드. 배경(빈 공간) 클릭 시 하이라이트 초기화.
- **엣지 클릭(2026-07 추가)** — 엣지는 `<line>` 두 겹으로 구현한다. (1) 시각 레이어(`link`, 기존과 동일한 굵기·색·`stroke-opacity:0.6`)는 `pointer-events: none`으로 클릭을 통과시킨다. (2) 그 위에 겹치는 히트 레이어(`linkHit`, `stroke="transparent"`, `stroke-width:14`, `cursor:pointer`)가 클릭을 전담한다 — 얇은 선(최대 5px)만으로는 클릭 타겟이 좁아 사용성이 나쁘기 때문. `stroke="transparent"`는 완전 투명해도 SVG 히트테스트의 "칠해진 영역"으로 간주돼 기본 `pointer-events: visiblePainted`에서 정상적으로 클릭이 잡힌다(`stroke="none"`과의 차이 — `none`은 애초에 칠해지지 않아 클릭도 안 잡힘). 클릭 시: 그 엣지의 두 endpoint 노드만 `opacity:1`(나머지 `0.08`), 클릭한 엣지 자신만 `#60269E`로 강조(나머지 엣지는 톤다운 — 노드 클릭의 "인접 전체 강조"와 달리 "이 엣지 하나만" 강조해 노드 클릭과 시각적으로 구분), `htmx.ajax('GET', '/graph/edges/<pkA>/<pkB>/panel/?period=' + CURRENT_PERIOD, {target:'#org-panel', swap:'innerHTML'})`로 쌍 패널을 같은 `#org-panel` 슬롯에 로드(노드 패널과 쌍 패널은 서로 다른 프래그먼트지만 같은 컨테이너를 공유 — `news/_orgs.html`의 단일 패널 슬롯 재사용 관례와 동일). `pkA`/`pkB`는 `Math.min/max`로 정규화해 URL에 넣는다(2단계 `OrgRelation.org_a.pk < org_b.pk` 정규화 규칙과 동일 컨벤션을 미리 맞춤).
- **라벨 있는 엣지 시각 채널 + 캔버스 라벨 텍스트(2026-07-28 추가, 구현 완료)** — 굵기(활동량)와 별개로 라벨 유무를 점선(`stroke-dasharray:"5,3"`)·강조색(`#60269E`)으로 구분하고, 톤다운 시 강조/페이드 투명도(`edgeIdleColor`/`edgeIdleOpacity`/`edgeFadeOpacity`/`edgeWidth` 4개 헬퍼로 캡슐화)도 라벨 없음과 다르게 처리한다. 라벨 텍스트 자체는 흰 배경 pill(`edge-label-g` — `<rect>`+`<text>`)로 엣지 중점에 클릭 없이 상시 렌더한다. 상세 스펙·정확한 값·PE가 채워야 할 JSON 필드는 아래 "라벨 있는 엣지 상시 표시 + 캔버스 라벨 텍스트 렌더" 절 참고.
- 범례 클릭: 카테고리(금융사/보험사/AI)별로 노드·엣지(`link`, `linkHit`, **`linkLabel`** — 히트 레이어와 라벨 텍스트도 함께 숨겨야 "안 보이는데 클릭은 되는"/"카테고리는 숨겼는데 라벨 텍스트만 남는" 불일치가 없다)를 `display:none` 토글, 비활성 상태 버튼은 `opacity:0.35`.
- **기간 필터(2026-07 추가)** — 페이지 상단 세그먼트 pill(전체/최근 30일/최근 7일, 기본값 최근 7일 — 대시보드와 통일)은 `<a href="?period=...">` **전체 페이지 GET 재로드** 방식이다(HTMX 부분 스왑이 아님). 이는 의도적 선택이다: D3 초기화 스크립트가 `const`/`let`을 최상위 스코프에 선언하는데, 같은 문서 안에서 `<script>`만 HTMX로 반복 재실행하면 브라우저가 두 번째 실행부터 "이미 선언된 식별자" `SyntaxError`를 던진다(classic `<script>`의 최상위 `let`/`const`는 문서 전역 렉시컬 환경을 공유해 재선언이 막힘). 전체 페이지 재로드는 매번 새 문서이므로 이 문제 자체가 없고, `news/list.html` 검색·필터 바(`<form method="get">`)와 같은 이미 검증된 패턴과도 톤이 맞는다. 재로드 시 뷰가 `period`에 맞춰 노드·엣지·`org_count`/`edge_count`를 다시 계산해 내려주므로 별도 클라이언트 로직 없이 정합성이 자동으로 맞는다. 서버 렌더링 시점에 `selected_period`를 `CURRENT_PERIOD` JS 상수로 심어두고, 노드/엣지 패널 HTMX 호출 시 `?period=` 쿼리로 그대로 붙여 캔버스와 패널이 항상 같은 기간을 보게 한다(기간 정합성 계약).
- 리사이즈: `window.resize` 시 `forceCenter` 재계산.
- 노드 라벨: SVG `<text>`로 기업명 표시, `font-family`를 시스템 한글 폰트("Malgun Gothic"/"맑은 고딕")로 별도 지정 — 프로젝트 기본 `font-sans`(Noto Sans KR)와 다른 지정이라 아래 "디자인 시스템 정합성 점검"에 기록.
- HTMX 로딩 인디케이터(`hx-indicator`) 없음 — 패널 프래그먼트가 가볍고(최대 10건 카드, 쌍 패널도 교집합이라 대개 소수) 지연이 체감되지 않는 규모라 별도 스피너를 넣지 않은 것으로 보인다. 데이터 규모가 커지면 재검토 필요.

**기업 패널 (`templates/graph/_org_panel.html`) — 노드 클릭 시**

- 상단: 유형 뱃지(금융사 `bg-blue-100 text-blue-700` / 보험사 `bg-[#E6F7F5] text-[#00AF9A]` / AI `bg-[#F3EAFB] text-primary` — SET-007 뱃지 규칙과 동일 토큰) + 비활성 기업이면 "(비활성)" 회색 텍스트 + 기업명(bold) + 별칭(있으면).
- 관련 뉴스: 최대 10건, 최신 발행일순, **컷오프는 유지하되 2026-07부터 "관련 뉴스" 제목 옆에 `total_count > 10`일 때 "전체 N건 중 10건"을 명시**해 잘림을 숨기지 않는다(위 "PD 판단 기록" 참고 — 쌍 패널은 컷오프 없음과 의도적으로 다름). 각 카드는 List Card 패턴(`<a class="block group">`)을 따르며 — 이 문서 "1.5 컴포넌트 정의 > List Card" 절이 실제로 이 파일(23행)을 참고 구현 예시로 이미 지목하고 있다. 카드 안에 뉴스에 연결된 기업들의 뱃지를 작게 다시 나열(제목 2줄 line-clamp + 발행월일).
- 미선택 상태: 중앙 정렬 안내(Lucide `mouse-pointer-click` 아이콘 32px, opacity-30 + "기업 노드 또는 연결선을 클릭하면 관련 뉴스를 볼 수 있습니다." — 2026-07 엣지 클릭 추가에 맞춰 문구 갱신) — 기존 empty state 패턴(회색 아이콘 + 안내문)과 톤 일치.

**쌍 패널 (`templates/graph/_edge_panel.html`, 신규 2026-07) — 엣지 클릭 시**

- 노드 클릭 시 뜨는 위 기업 패널과 서로 다른 프래그먼트지만, 같은 `#org-panel` 컨테이너를 공유해 스왑된다(둘 다 GRAPH-001의 하위 프래그먼트, 독립 화면 아님).
- 상단 헤더: "{{ org_a.name }} × {{ org_b.name }}" + 줄바꿈 + "함께 언급된 뉴스 {{ news_count }}건" — PM이 지정한 문구 형식을 그대로 따름. `news_count`는 반드시 해당 엣지의 `value`(공동등장 가중치)와 일치해야 하는 검증 포인트(위 백엔드 스펙 참고). 바로 아래에 두 기업의 유형 뱃지를 나란히 표시(각자 org_type에 맞는 색 토큰).
- **관계 라벨 영역(2단계, 아래 "2단계 관계 라벨 UI 스펙" 참고)** — 쌍 헤더와 근거 뉴스 사이, 독립된 "관계" 블록으로 표시. 근거 뉴스 목록과는 `border-b border-gray-100`로 시각적으로 구분.
- 근거 뉴스: **컷오프 없이 전량 노출**(교집합이라 표본이 작음을 전제, PM 명시 요구사항). 카드 레이아웃은 기업 패널의 List Card와 동일 패턴 재사용(제목 2줄 line-clamp + 뱃지 + 발행월일).
- 빈 상태(이론상 도달하지 않아야 함 — 엣지가 존재하면 교집합도 최소 1건): "함께 언급된 뉴스가 없습니다."

**2단계 관계 라벨 UI 스펙 (PD 설계 완료, 2026-07 — `docs/planning.md` "지식그래프 개선 로드맵" 2단계 착수 스펙을 화면 단위로 구체화, PE 인계)**

`templates/graph/_edge_panel.html`에 "관계" 블록을 실제로 구현했다(정적 마크업 수준 — `OrgRelation` 모델·저장 뷰는 아직 없어 `relation` 컨텍스트 변수가 항상 비어 있고, 그 결과 현재는 항상 "관계 미분류" 상태로만 보인다. Django 템플릿은 미정의 변수를 조용히 falsy 처리하므로 에러 없이 정상 렌더된다). 아래는 PE가 그대로 구현할 수 있는 수준의 스펙이다.

1. **레이아웃/위치** — 쌍 헤더(기업명 + 뱃지) 블록 바로 다음, "근거 뉴스" 목록 앞. 전체를 `mb-4 pb-4 border-b border-gray-100`로 감싸 근거 뉴스 목록과 구분한다. 헤더 라벨은 다른 섹션과 동일한 `text-xs font-semibold text-gray-500 uppercase tracking-wider` 토큰으로 "관계" 텍스트.

2. **상태 전환 — Alpine.js `x-data` 토글(이 프로젝트 관례)** — 패널 최상위에 `x-data="{ editing: false, label: '...', description: '...' }"`. `label`/`description`은 `{{ relation.label|default:""|escapejs }}` 형태로 서버 값을 JS 문자열 리터럴에 안전하게 주입한다(`templates/setting/_tech_topics.html`의 `editTopic={...name:'{{ topic.name|escapejs }}'...}`와 동일하게 이미 이 코드베이스에서 검증된 패턴 — HTML 속성 안에 JS 문자열을 심을 때 `|escapejs`를 쓰는 것이 관례).
   - 보기 상태: `x-show="!editing" x-cloak`
   - 편집 상태(폼): `x-show="editing" x-cloak`
   - **두 상태 모두 `x-cloak`을 반드시 붙인다.** 보기 상태는 기본값이 `true`라 이론상 FOUC 위험이 낮지만, 이 프로젝트에서 이미 뉴스 상세 "기업 추가" 드롭다운 등 3곳에서 `x-cloak` 누락 FOUC 버그가 발견·수정된 전례가 있어 "토글되는 요소는 예외 없이 `x-cloak`을 쌍으로 붙인다"는 규칙을 기계적으로 지켰다.

3. **보기 상태 마크업**
   - `relation`이 있을 때: 라벨을 `border border-primary text-primary` 아웃라인 필(pill)로 표시(`text-xs font-semibold px-2 py-0.5 rounded-full`). **의도적으로 기존 org_type 뱃지(금융사/보험사/AI, 모두 solid-fill 배경)와 다른 스타일(테두리만, 배경 없음)을 택했다** — 관계 라벨은 기업 유형 분류와 무관한 별개 축인데, 만약 solid-fill 보라색을 쓰면 AI 유형 뱃지(`bg-[#F3EAFB] text-primary`)와 시각적으로 혼동될 수 있다(대시보드 범례 미표기로 실제 혼동 이슈가 있었던 전례 — `docs/planning.md` "대시보드 색상 범례" 참고). 아웃라인 스타일로 "이건 유형이 아니라 관계 성격이다"를 시각적으로 구분했다. `description`이 있으면 라벨 아래 `text-xs text-gray-500` 텍스트로 노출. 우측에 "수정"(Lucide `pencil`) 버튼.
   - `relation`이 없을 때(현재 항상 이 상태): `text-xs text-gray-400`으로 "관계 미분류" 고정 텍스트 + 우측에 "라벨 추가"(Lucide `plus`) 버튼. **라벨 영역 자체를 숨기지 않는다**(PM 확정 정책).

4. **편집 상태 마크업 — 예시 힌트는 "datalist + 클릭 칩" 이중 구현**
   - 라벨 `<input type="text" name="label" x-model="label">`에 `list="relation-label-hints"` 지정 + 같은 5개 값을 가진 `<datalist id="relation-label-hints">`를 둔다(네이티브 브라우저 자동완성 지원).
   - **동시에** 같은 5개 값을 클릭 가능한 칩(`border border-[#E5E5E5] text-gray-500`, hover 시 `border-primary text-primary`)으로 인풋 아래 나열하고, 클릭 시 `@click="label = '기술협업'"`처럼 Alpine `x-model` 값을 직접 채운다.
   - **판단 근거(둘 다 넣은 이유)**: `datalist`만 쓰면 입력란에 작은 드롭다운 화살표만 뜨는 정도라 발견성이 낮고(사용자가 힌트가 존재한다는 걸 인지하기 어려움), `placeholder`만 쓰면 힌트 5개를 한 줄에 다 못 보여주고 타이핑 시작하는 순간 사라진다. 반면 클릭 칩은 이 프로젝트에서 이미 뱃지/필 형태로 익숙한 시각 언어를 재사용하면서 "예시이자 즉시 채워 넣는 단축 입력"이라는 두 기능을 동시에 준다. `datalist`는 제거해도 무방하지만 키보드 위주 사용자를 위한 보조 수단으로 비용이 거의 없어 함께 남겼다. 어느 방식을 택해도 **목록 밖 자유 입력을 막지 않는다**(둘 다 `<select>`가 아니라 `<input>` 기반이므로 자동 충족).
   - `maxlength="50"` — `OrgRelation.label = CharField(max_length=50)` 확정 스키마(`docs/planning.md`)와 동일하게 클라이언트에도 반영. `required`.
   - `description`은 `<textarea name="description" x-model="description" rows="2" maxlength="300">`(선택 입력, `placeholder="관계 설명 (선택)"`). `maxlength`는 서버 `TextField`가 무제한이라 강제 제약이 아니라 UI 가이드용 소프트 값 — PE가 서버에도 동일 제약을 걸지는 판단에 맡긴다.
   - 하단에 "취소"(보기 상태로 복귀 + 편집 중이던 값을 서버 값으로 되돌림 — `label`/`description`을 다시 `{{ relation... }}` 초기값으로 리셋)와 "저장"(`type="submit"`, `bg-primary`) 버튼.

5. **HTMX 저장 흐름**
   - `<form>`에 `hx-post="/graph/edges/{{ org_a.pk }}/{{ org_b.pk }}/label/?period={{ selected_period }}"`, `hx-target="#org-panel"`, `hx-swap="innerHTML"`, `hx-include="[name=csrfmiddlewaretoken]"`. 폼 안에 `{% csrf_token %}`을 직접 포함시켰다(패널 자체가 HTMX로 반복 스왑되는 프래그먼트라, 상위 페이지의 토큰에 의존하지 않고 프래그먼트 자기완결적으로 두는 편이 안전).
   - **`{% url %}` 태그 대신 리터럴 경로 문자열을 썼다** — `graph_edge_label_save`라는 URL name이 아직 `apps/graph/urls.py`에 등록돼 있지 않은데(PE 구현 전), `{% url %}`은 등록되지 않은 name에 대해 즉시 `NoReverseMatch`를 던져 **현재 배포 중인 1단계 쌍 패널까지 함께 깨뜨린다**. 그래서 반드시 하드코딩된 경로 문자열(`/graph/edges/<pk_a>/<pk_b>/label/`)을 써야 한다. PE가 이 경로 그대로 `path("edges/<int:pk_a>/<int:pk_b>/label/", views.graph_edge_label_save, name="graph_edge_label_save")`를 등록하면 즉시 동작한다(등록 후에는 `{% url %}`로 바꿔도 무방하나 필수는 아님).
   - `org_a.pk`/`org_b.pk`는 뷰가 받는 순서 그대로 URL에 넣는다(정규화는 `docs/planning.md`에 명시된 대로 뷰 내부 `sorted()`가 담당 — `graph_edge_panel`과 동일 관례).
   - `?period={{ selected_period }}`를 유지해, 저장 후 재렌더되는 패널이 캔버스와 같은 기간 필터를 유지한다(기존 "기간 정합성 계약"의 자연스러운 확장).
   - 응답은 **패널 전체(`_edge_panel.html`)를 다시 렌더**해 `#org-panel`을 통째로 교체하는 것을 전제로 설계했다(라벨 영역만 부분 스왑하지 않음) — `graph_edge_panel` 뷰가 하던 컨텍스트 구성(org_a/org_b/news_list/news_count/selected_period)에 `relation`만 추가해 그대로 재사용할 수 있어 PE 구현 비용이 가장 낮고, 저장 직후 근거 뉴스 목록까지 최신 상태로 다시 보이는 부수 이점도 있다.

6. **컨텍스트 변수 제안(PE 인계)** — `graph_edge_panel` 뷰(및 신규 저장 뷰)가 템플릿에 넘겨야 할 변수: `relation`(`OrgRelation` 인스턴스 또는 없으면 `None`/컨텍스트에서 생략 — 템플릿은 둘 다 "관계 미분류"로 동일하게 처리하므로 무엇이든 무방하나 `None`을 명시적으로 넘기는 쪽을 권장, `docs/planning.md`의 "정규화된 `(pk_a, pk_b)`로 `OrgRelation`을 조회, 없으면 `None`" 지시와 일치). 그 외 기존 `org_a`, `org_b`, `news_list`, `news_count`, `selected_period`는 변경 없음.

7. **(2026-07-28 갱신) 캔버스 상시 라벨 렌더 — 스코프 제외 결정 폐기, 구현 완료**: 위 작성 시점에는 "그래프 캔버스 엣지 선 위 상시 라벨 렌더는 구현하지 않는다(PM 정책대로 스코프 제외)"였으나, `docs/planning.md`의 "지식그래프: 라벨 텍스트 캔버스 상시 렌더" 절에서 이 제외 결정이 번복됐고, PD가 `templates/graph/index.html`에 실제로 구현을 완료했다. 상세 스펙은 아래 "기간 내 실존 엣지의 라벨 표시 + 캔버스 라벨 텍스트 렌더" 절 참고. 새 화면 ID는 여전히 부여하지 않는다(GRAPH-001 하위 프래그먼트 관례 유지).

**기간 내 실존 엣지의 라벨 표시 + 캔버스 라벨 텍스트 렌더 (PD 설계·구현 완료, 2026-07-28 최초 구현 → 2026-07-28 정정 — `docs/planning.md` "지식그래프: 라벨 텍스트 캔버스 상시 렌더"·"지식그래프: 라벨 강제 표시 롤백" 정책을 화면 단위로 구체화)**

> **2026-07-28 정정** — 본 절은 최초 작성 시점(라벨 있는 엣지를 기간 필터와 무관하게 "항상" 표시하는 정책이 유효하던 때)의 서술을 담고 있었다. 그러나 사용자가 "기간 필터 신뢰성이 없다"는 이유로 그 정책을 명확히 철회했고(`docs/planning.md` "지식그래프: 라벨 있는 엣지 상시 표시" 절 철회 이력 참고), 실제 코드(`apps/graph/views.py`의 `graph()` 뷰)도 이미 롤백 완료된 상태다 — 노드/엣지 강제 union, `value=0` 강제 삽입, `_edge_allowed` 예외가 전부 제거됐다. 본 절은 코드에 맞춰 재정정한다: **캔버스 라벨 텍스트 렌더(점선+흰 pill 등 시각 디자인) 자체는 그대로 유효**하나, 그 적용 대상이 "라벨 있는 모든 엣지"에서 **"라벨이 있으면서 선택 기간 내 실존하는(공동언급 ≥ 1) 엣지"**로 좁혀졌다.

`templates/graph/index.html`에 실제로 구현돼 있다(D3 렌더링 로직 포함). 두 정책은 서로 결합된 하나의 시각 언어다: (1) **엣지의 존재 자체는 라벨 유무와 무관하게 예외 없이 기간 필터를 따른다** — 선택 기간 내 실제 공동언급(≥1)이 있는 엣지에만 `has_label`/`label` 라벨 정보를 얹으며, 라벨이 엣지를 강제로 만들어내지 않는다(기간 내 공동언급이 없는 쌍은 라벨이 있어도 캔버스에 나타나지 않는다), (2) 그렇게 실존하는 라벨 엣지는 굵기와 별개의 시각 채널(점선+강조색)로 구분되며, (3) 라벨 텍스트 자체도 클릭 없이 캔버스에 pill로 상시 표시된다(대상은 위와 동일하게 "라벨 있으면서 기간 내 실존하는 엣지"로 한정).

1. **엣지 시각 채널 — 굵기(활동)와 라벨 유무를 분리**:
   - 굵기: 기존과 동일하게 `Math.min(1 + d.value * 0.5, 5)`(선택 기간 공동언급 `value` 그대로, 거짓 활동 신호 방지). 라벨 있는 엣지에는 여기에 **최소 1.5px 바닥**을 얹는 코드가 여전히 남아 있다 — `d.has_label ? Math.max(1.5, base) : base`(`templates/graph/index.html` 161~164행). **단 라벨 강제 표시 롤백(2026-07-28) 이후로는 라벨 있는 엣지가 애초에 기간 내 공동언급(`value` ≥ 1)이 있을 때만 존재하므로 `base`가 이미 1.5 이상이 되어, 이 바닥이 실제로 굵기를 끌어올리는 경우는 지금 없다.** 즉 코드에는 남아 있으나 이제는 발생하지 않는 시나리오(`value=0`인 라벨 엣지)에 대한 방어 코드일 뿐이다 — 무해하므로 제거를 지시하지는 않되, "value=0인 라벨 엣지도 최소 굵기 바닥 덕분에 안 보이는 선이 되지 않는다"던 기존 설명은 근거 자체가 사라졌으므로 이 문서에서 삭제한다.
   - 색·투명도: 라벨 없음(기본) = `#D1D5DB`(gray-300) / opacity `0.6`(기존과 동일). 라벨 있음 = Primary Violet `#60269E` / opacity `0.75`(더 진하게, 최소 가시성 보장).
   - 점선: 라벨 있는 엣지에만 `stroke-dasharray="5,3"`을 적용해 실선(활동 표시)과 완전히 구분되는 채널로 만든다. 미분류 엣지는 `stroke-dasharray` 없음(실선 유지).
   - 코드: `edgeIdleColor(d)`, `edgeIdleOpacity(d)`, `edgeFadeOpacity(d)`, `edgeWidth(d)` 4개 헬퍼 함수로 캡슐화(`templates/graph/index.html` 152~164행). 기존 `link` 생성 코드, `svg.on('click', ...)`(배경 클릭 리셋), `selectNode`/`selectEdge`의 "비활성 상태" 분기가 모두 이 헬퍼를 재사용하도록 고쳐, 하드코딩된 `#D1D5DB`가 여러 곳에 중복되던 것을 제거했다.
   - **강조(하이라이트) 상태와의 관계**: 노드/엣지를 클릭해 다른 요소가 페이드되는 중에도 라벨 있는 엣지는 완전히 죽이지 않는다 — 페이드 투명도를 `edgeFadeOpacity(d)`로 분리해 라벨 없음은 `0.05`(기존과 동일), 라벨 있음은 `0.15`로 살짝 더 남긴다. 단 점선(`stroke-dasharray`) 자체는 하이라이트 상태와 무관하게 최초 렌더 시 한 번만 설정하고 이후 변경하지 않는다 — 색/투명도만 토글하고 점선은 항상 유지해, "이건 라벨이 있는 관계"라는 정체성이 상호작용 중에도 사라지지 않게 했다.

2. **캔버스 라벨 텍스트 — 흰 배경 pill, 수평 고정, 엣지 중점에 배치**:
   - 대상: `has_label === true`인 엣지만(`labeledEdges = edges.filter(d => d.has_label)`, `templates/graph/index.html` 178행). **`edges` 배열 자체가 이미 "기간 내 실존하는 엣지"만 담고 있으므로(뷰가 존재하지 않는 쌍의 dict를 애초에 만들지 않는다), 이 필터를 통과하는 엣지는 자연히 "라벨 있으면서 기간 내 실존하는 엣지"가 된다.** 미분류 엣지에는 텍스트를 그리지 않는다(정책 그대로 — 현재 31개 중 3개만 라벨이 있어 겹침 우려 낮음).
   - 배치: 엣지 선의 **중점**(`(source.x+target.x)/2, (source.y+target.y)/2`)에 `<g class="edge-label-g">`를 `translate`로 위치시킨다. 힘 시뮬레이션으로 선 각도가 계속 바뀌므로 **텍스트는 회전시키지 않고 항상 수평 고정**했다(PD 판단 — 회전 텍스트는 가독성이 떨어지고 매 tick 각도 재계산이 필요해 복잡도만 늘어난다. 수평 고정 권장대로 채택).
   - 마크업: `<g>` 안에 `<rect rx=8 ry=8 height=18 fill=#FFFFFF stroke=#60269E stroke-width=1>` + `<text text-anchor=middle dominant-baseline=middle font-size=10 font-weight=600 fill=#60269E>{{ label }}</text>`. 흰 배경 + primary 테두리 pill이라 회색 엣지 선이나 다른 노드와 겹쳐도 잘 읽힌다(halo 대신 solid 배경 방식 채택 — SVG에서 텍스트에 직접 stroke halo를 주는 것보다 배경 rect가 구현이 단순하고, 이 프로젝트의 기존 뱃지/필 시각 언어와도 톤이 맞는다).
   - pill 너비: 텍스트 실측(`text.getBBox().width + 12`, 좌우 패딩 6px씩)으로 라벨마다 동적 계산한다. **최초 렌더 시 1회만 측정**하고 매 tick마다 재측정하지 않는다(라벨 텍스트는 정적이라 매 프레임 `getBBox()` 호출은 불필요한 비용, `templates/graph/index.html` 203~206행).
   - tick 갱신: `sim.on('tick', ...)` 콜백(`templates/graph/index.html` 235행)에 `linkLabel.attr('transform', d => translate(중점 좌표))`를 추가했다(기존 `linkHit`/`link`/`node` 좌표 갱신과 동일한 패턴 재사용).
   - z-order: `g.append('g')` 호출 순서로 `linkHit` → `link` → `linkLabel` → `node` 순으로 쌓았다. 라벨 pill이 엣지 선 위, 노드 원 아래에 그려진다 — 짧은 거리(force distance 160)에서 노드가 라벨을 완전히 가리는 경우는 드물지만, 만에 하나 겹쳐도 클릭 가능한 노드가 항상 최상단이어야 상호작용이 가려지지 않는다.
   - `pointer-events: none` — 라벨 텍스트/pill은 클릭 대상이 아니다(엣지 클릭은 여전히 `linkHit`이 전담).
   - 범례 토글 연동: `toggleCategory()`가 `linkLabel`에도 `display:none` 토글을 적용하도록 확장(기존에 `link`/`linkHit`만 토글하던 것에 추가) — 카테고리를 숨기면 그 카테고리가 걸린 라벨 엣지의 텍스트도 함께 사라져야 시각적 일치가 유지된다.
   - 겹침 방지 로직(hover 시에만 표시, 줌 레벨별 밀도 조절 등)은 **지금 구현하지 않는다** — `docs/planning.md`에 명시된 트리거(캔버스에 동시 표시되는 라벨이 15~20개를 넘어설 때)가 오면 그때 추가한다(YAGNI 유지, 이 문단이 재검토 트리거 기록).

3. **`apps/graph/views.py`의 `graph()` 뷰가 채우는 엣지 JSON 필드 (구현 완료, 2026-07-28 롤백 후 상태)**: `edges` 배열의 각 dict는 다음 필드를 갖는다(`templates/graph/index.html`은 필드가 없어도 `has_label`이 `undefined`로 falsy 처리돼 "미분류" 스타일로 자동 폴백하도록 짜여 있으나, 지금은 뷰 구현이 이미 완료된 상태라 이 폴백이 실제로 쓰이지는 않는다):
   - `has_label` (bool) — 이 쌍이 **선택 기간 내 실제 공동언급(≥1)으로 이미 `edge_weights`에 존재하는 엣지**이면서, 동시에 그 쌍에 대한 `OrgRelation` 레코드가 있는지. `edges` 배열 자체가 `edge_weights`(기간 내 실존 엣지)만 순회해 만들어지므로, 기간 내 공동언급이 없는 쌍은 dict 자체가 생성되지 않아 `has_label=true`가 등장할 수 없다 — 즉 "라벨은 있지만 기간 내 존재하지 않는 엣지"는 구조적으로 나타나지 않는다.
   - `label` (string, `has_label=false`면 `null`) — `OrgRelation.label` 값 그대로. 캔버스 pill 텍스트로 그대로 출력되므로 이스케이프는 Django `json_script` 필터가 자동 처리한다(`{{ edges|json_script:"graph-edges" }}`, 별도 처리 불필요).
   - 기존 `source`/`target`/`value`는 변경 없음. `value`는 "선택 기간 공동언급 건수"만 의미하며, 라벨 유무에 관계없이 항상 1 이상이다(라벨이 있다고 값을 부풀리지 않는다는 원래 계약은 유지되되, `value=0`인 라벨 엣지 자체가 더 이상 존재하지 않는다 — 아래 참고).
   - **(2026-07-28 삭제) 노드/엣지 합집합 로직** — 과거 이 문서에 있던 "엣지 목록은 (기간 공동언급 엣지) ∪ (`OrgRelation` 존재하는 모든 쌍, value=0 허용)" 서술과 "`_edge_allowed`는 라벨 엣지에 적용하지 않는다"는 예외 규정을 **전부 삭제한다** — 사용자 지시로 철회된 정책이며 실제 코드에도 없다. 현재 코드(`apps/graph/views.py` 52~125행)의 실제 동작은 다음과 같다: 노드 목록은 "선택 기간 내 `news_count > 0`인 활성 기업"만으로 구성되고(union 없음), 엣지 목록은 "기간 내 실제 공동언급(≥1)으로 계산된 엣지"만으로 구성되며(강제 삽입 없음), `_edge_allowed`(금융/보험-AI 타입 제약)는 라벨 유무와 무관하게 **모든** 엣지에 예외 없이 적용된다. 라벨(`OrgRelation`) 정보는 이렇게 이미 만들어진 `edge_weights`에 사후적으로 매핑될 뿐, 존재 여부에는 전혀 관여하지 않는다.

4. **(2026-07-28 삭제) value=0 노드 처리 확인 절** — 과거 이 문서에 있던 "기간 활동 0인 라벨 엣지의 끝 노드가 새로 등장해도 `symbolSize` 최소값(14px)이 안전하게 처리한다"는 서술을 삭제한다. 노드 목록에 union이 없어졌으므로(위 3번), 라벨 엣지로 인해 `news_count=0`인 노드가 새로 등장하는 시나리오 자체가 더 이상 없다(`orgs` 쿼리셋이 애초에 `news_count__gt=0`으로 필터링된다). `symbolSize = max(14, min(40, 14 + news_count*2))`의 14px 하한 자체는 여전히 코드에 있으나, 이는 일반적인 방어 로직일 뿐 라벨 정책과는 무관하다.

**사이드바 메뉴 (`templates/base.html`)**

`대시보드 → 보고서 → 지식그래프 → 뉴스 → 설정` 순으로 5번째 항목이 아니라 3번째(보고서 다음, 뉴스 앞)에 배치돼 있다. Lucide `network` 아이콘, 활성 판정은 다른 메뉴와 동일하게 `{% if 'graph' in request.resolver_match.url_name %}`로 `bg-white/20 text-white` 하이라이트(URL name이 `graph`/`graph_org_panel` 둘 다 문자열에 `graph`를 포함해 두 라우트 모두에서 활성 표시됨).

```python
# templates/base.html 62-95행 실제 순서 (참고용, 코드는 이미 존재하며 PD가 수정한 것 아님)
1. 대시보드   (layout-dashboard)
2. 보고서     (bar-chart-2)
3. 지식그래프 (network)   ← GRAPH-001
4. 뉴스       (newspaper)
5. 설정       (settings)
```

**디자인 시스템 정합성 점검 (수정 지시 아님, 발견 사항만 기록)**

1. **노드 채움 색이 배지 텍스트 색과 동일 hex를 그대로 fill로 씀** — `CAT_COLORS = ['#3B82F6', '#00AF9A', '#60269E']`(금융사/보험사/AI). 보험사(`#00AF9A` Blue Green)와 AI(`#60269E` Primary Violet)는 디자인 시스템 컬러 토큰과 정확히 일치한다. 금융사(`#3B82F6`, Tailwind `blue-500`)는 이 프로젝트에 "금융사 blue" 전용 커스텀 hex 토큰이 정의된 적이 없어(1.1 컬러 토큰 표에 "Blue" 계열 토큰 없음) 문제라기보다는 기존 관례(뱃지들도 `blue-100`/`blue-700`/`blue-600` 등 Tailwind 기본 blue 팔레트를 그대로 씀)를 그래프에도 일관되게 따른 것으로 보인다.
2. **엣지 색상(`#D1D5DB` 기본 / `#60269E` 강조)** — `#D1D5DB`는 Tailwind `gray-300`으로, 디자인 시스템 1.1 표의 어느 그레이 토큰(`Dark Gray #54565A`, `Gray #898A8D`)과도 일치하지 않는 별도 값이다. 카드 보더 `#E5E5E5`보다도 진해 엣지 전용으로 새로 고른 값으로 보인다. 강조색 `#60269E`(Primary)는 토큰과 일치.
3. ~~`_org_panel.html`의 "관련 뉴스" 카드 안 기업 뱃지가 보험사에 `bg-green-50 text-green-600`(Tailwind 기본 green)을 쓴다~~ — **발견 직후 수정 완료.** 프로젝트 전역에서 보험사는 예외 없이 `#00AF9A`(Blue Green) 토큰을 쓰는데 이 한 곳만 `green-600`으로 달랐던 걸 `bg-[#E6F7F5] text-[#00AF9A]`로 통일했다. 같은 감사 중 `templates/news/_list.html`(동일한 `green-50/600` 오기재)과 `templates/news/_orgs.html`(프로젝트에 정의되지 않은 `teal-100`/`teal-600` 셰이드를 참조해 배경색이 아예 안 나오던 문제, 2곳)도 함께 발견·수정했다.
4. **그래프 캔버스의 노드 라벨(`text` 요소)이 `"Malgun Gothic", "맑은 고딕", system-ui, sans-serif`를 별도 지정** — 프로젝트 기본 본문 폰트(`font-sans` = Noto Sans KR/Inter)를 쓰지 않고 시스템 한글 글꼴을 직접 지정한 유일한 위치. SVG 텍스트 렌더링 특성상(웹폰트 로딩 지연 시 레이아웃 흔들림 방지) 의도적으로 시스템 폰트를 고정한 것일 수 있으나, 다른 화면과 폰트 패밀리가 달라 보일 여지가 있다.
5. **이 화면에는 Alpine.js 토글·모달이 전혀 없다** — 범례 토글·노드 하이라이트는 순수 D3/vanilla JS 상태(`hiddenCats` Set)로 구현돼 있어, "SET-007/008 소급 문서화 때 발견한 `x-cloak` 누락 FOUC 버그" 패턴이 애초에 적용 대상이 아니다(Alpine을 쓰지 않으므로 해당 버그 클래스 자체가 존재하지 않음). 별도 조치 불필요.

**Claude Artifacts 생성 프롬프트**

```
DPLANEX 디자인 시스템 기반으로 "AI Market Watch" 지식그래프 화면을 HTML + Tailwind CSS + D3.js(v7)로 만들어줘.

[디자인 시스템]
- Primary: #60269E (Violet), Blue Green: #00AF9A, 금융사 blue-500(#3B82F6)
- Font: Inter/Noto Sans KR (body), Source Serif 4/Noto Serif KR (heading)
- Border radius: 10px, Border: 1px solid #E5E5E5, 카드는 bg-white shadow-sm

[레이아웃]
- 최상단: 기간 필터 세그먼트 pill — "전체 | 최근 30일 | 최근 7일" 3버튼, 선택된 버튼은 bg-primary/text-white, 나머지는 text-gray-600. 기본 선택은 "최근 7일"
- 좌측: 그래프 캔버스(flex-1, 흰 카드, 화면 높이 꽉 채움)
  - 좌상단: 범례 pill — "● 금융사(blue-500) ● 보험사(#00AF9A) ● AI(#60269E)", 클릭 시 opacity 0.35로 토글
  - 우상단: "기업 N개 · 연결 N개" 통계 텍스트 (선택된 기간 기준으로 값이 바뀜)
  - 중앙: force-directed 그래프. 노드=기업(카테고리별 색상 원, 크기는 뉴스 건수 비례 14~40px), 엣지=공동등장 가중치에 비례한 선 굵기(미분류는 실선 #D1D5DB 최대 5px, 관계 라벨이 붙은 엣지는 점선 #60269E + 최소 1.5px 바닥 + 엣지 중점에 흰 배경/primary 테두리 pill로 라벨 텍스트("기술협업" 등) 클릭 없이 상시 표시) + 클릭 가능(얇은 선 위에 넓은 투명 히트 영역)
  - 인터랙션: 줌/팬, 노드 드래그, 노드 클릭 시 연결된 노드만 강조(비연결 노드 opacity 0.08, 연결선 #60269E), 엣지 클릭 시 그 엣지의 두 기업만 강조 + 우측 패널에 "A × B 함께 언급된 뉴스 N건" 표시, 빈 공간 클릭 시 초기화
- 우측: w-72 기업/쌍 패널(흰 카드, 하나의 슬롯을 두 종류 패널이 공유)
  - 미선택 시: 중앙 정렬 안내 아이콘 + "기업 노드 또는 연결선을 클릭하면 관련 뉴스를 볼 수 있습니다."
  - 노드 선택 시: 유형 뱃지(금융사 blue-100/blue-700, 보험사 #E6F7F5/#00AF9A, AI #F3EAFB/#60269E) + 기업명 + 별칭 + "관련 뉴스" 카드 리스트(최대 10건, 10건 초과 시 "전체 N건 중 10건" 표기 + 제목 2줄 + 기업 뱃지 + 발행월일)
  - 엣지 선택 시: "기업A × 기업B" + "함께 언급된 뉴스 N건" 헤더 + 두 기업 유형 뱃지 + **"관계" 블록**(라벨 있으면 outline pill "border border-primary text-primary" + 선택적 설명 텍스트 + "수정" 버튼, 없으면 회색 "관계 미분류" + "라벨 추가" 버튼 — 편집 클릭 시 자유 텍스트 인풋 + 클릭 가능한 예시 칩 5개("기술협업"/"투자"/"공급계약"/"인수합병"/"업무협약(MOU)") + 선택적 설명 textarea + 취소/저장 버튼으로 전환) + "근거 뉴스" 카드 리스트(컷오프 없이 전량, 카드 형식은 위와 동일)

[샘플 데이터]
- 노드: KB국민은행(금융사, 9건), 삼성생명(보험사, 6건), Anthropic(AI, 5건), 신한은행(금융사, 4건), 교보생명(보험사, 3건), OpenAI(AI, 4건)
- 엣지: KB국민은행–Anthropic(가중치 3), 삼성생명–OpenAI(가중치 2), 신한은행–OpenAI(가중치 1) — 동종업계(금융사-금융사, 보험사-보험사 등)끼리는 연결선 없음
- 엣지 클릭 예시: "KB국민은행 × Anthropic" 클릭 시 우측 패널 헤더 "KB국민은행 × Anthropic / 함께 언급된 뉴스 3건" + 근거 뉴스 3건 전량 표시
```

"""Bedrock 경유 LLM 판정 — 1번(뉴스 정리)을 LLM으로 옮기는 설계 (docs/planning.md
"1번(뉴스 정리)을 LLM으로 옮기는 설계" 5번·6번·7번·8번이 정본).

이 모듈은 판정 데이터 층만 구현한다. 화면(SET-010 검토 화면)은 3단계에서 PD가 만든다.

🔴 접속 경로는 AnthropicBedrock이다(Mantle 아님 — 서울 리전에 Mantle 엔드포인트가 없다).
모델 ID는 "global." 접두사가 필수다.

🔴 프롬프트는 코드에 둔다 — Prompt 모델과 SET-003을 되살리지 않는다(같은 문서 5번).
DB에 남기는 것은 PROMPT_VERSION 문자열 하나이며, RunJob.prompt_version에 기록된다.

🔴 판정 기준 원문(CRITERIA_TEXT)은 설계 6-(A)가 "넣는다"로 정한 조항을 재서술 없이
docs/planning.md와 .claude/agents/research-analyst.md에서 그대로 발췌한 것이다. 문장을
줄이거나 바꾸지 않았다 — 줄이면 판정이 달라진다는 것이 그 쟁점의 전제였다. 조항을 통째로
빼는 것(예: 기준 2)은 배제이고 허용되지만, 넣기로 한 조항 안에서 문장을 다듬는 것은
금지된다.

🔴 tool use(function calling)는 쓰지 않는다. LLM이 삭제 도구를 직접 부를 수 있게 되면
휴먼 인 더 루프를 우회한다(설계 본문). output_config.format(structured output)만 쓴다.
"""

import json
import logging
import re

import anthropic
from anthropic import AnthropicBedrock
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class LLMStructuralError(Exception):
    """인증·권한·리소스(모델 ID·리전) 오류 — 재시도해도 같은 결과가 난다. 이 배치의
    나머지 건을 계속 돌리면 116번 똑같이 실패하며 비용만 쓰므로, 호출부(services/runner.py)가
    이 예외를 연속 실패 판단 재료로 쓴다."""


class LLMJudgmentError(Exception):
    """건별 판정 실패 — 네트워크 오류, 응답 형식 불량, 금지된 criterion_code 등. 그 건만
    실패로 남기고 다음 건으로 진행해도 되는 오류다."""


# RunJob.prompt_version에 그대로 기록된다(docs/planning.md 5번 "DB에 남기는 것은
# 프롬프트 버전 식별자 하나"). 판정 기준(CRITERIA_TEXT)이나 지시문이 바뀌면 이 값을
# 올린다 — 어느 프롬프트로 판정한 결과인지 나중에 재현할 수 있어야 한다.
#
# 2026-09-15b — 등록 대장(활성 Organization·TechTopic 이름 목록)을 시스템 프롬프트에
# 추가하고, `unregistered_org_candidates`(기업 전용)를 `tag_candidates`(축 일반화)로
# 바꿨다(docs/planning.md 4-(b) 🔴 개정 (2026-09-15)).
PROMPT_VERSION = "cleanup-2026-09-15b"

# 기준 2(동일 사건 중복 보도)는 여러 기사를 비교해야 판정할 수 있어 단건 판정 LLM이
# 이 값을 내면 안 된다(설계 6-(C) "기준 2는 RA에 남는다. 과도기가 아니라 확정 분담이다").
# 나오면 프롬프트나 모델 응답의 구조적 이상으로 보고 그 건을 실패로 남긴다.
FORBIDDEN_CRITERION_CODE = "2"


# ============================================================================
# 판정 기준 원문 발췌 — docs/planning.md "1번을 LLM으로 옮기는 설계" 6-(A) "넣는다" 목록.
# 재서술 없이 그대로 옮겼다. 각 섹션 앞에 원문 위치를 주석으로 남긴다.
# ============================================================================

# docs/planning.md "관련성 판단 기준" 절 — 기준 1-a, 1-b, 3, 4, 5, 6, 기준 간 우선순위.
# 기준 2(동일 사건 중복 보도)는 설계가 "빼는 것"으로 명시했으므로 제외했다.
_CRITERIA_RELEVANCE = """\
1. **핵심 주제 vs 배경·부차 요소 (AI/AX가 지배적 주제여야 유지)** — AI/AX가 기사의 **지배적(핵심) 주제**인지, 아니면 다른 주제를 설명하는 재료로 등장하는지 구분한다. 두 가지 하위 유형을 모두 관련 없음으로 처리한다.
   - **(1-a) 배경으로 스치듯 언급** — AI/AX가 다른 주제(예: 보험 리스크 관리, 스타트업 투자)를 설명하는 배경 정보로만 한 문장 스칠 뿐인 경우.
   - **(1-b) 부차 요소로만 곁들여짐** — **금융사·보험사가 주체이고 AI가 실제로 언급·등장하더라도**, AI가 기사의 지배적 주제가 아니라 다른 금융 주제(앱 UI/UX 개편, 오픈이노베이션 행사, 신용평가 정책, IPO 자금집행 등)에 여러 요소 중 하나로 곁들여진 경우. **AI가 지배적 주제가 아니면 금융사가 주체여도 삭제**한다.
     - **판별 질문**: "이 기사에서 AI를 빼도 기사가 성립하는가?" 빼도 기사가 온전하면 AI는 부차 요소(→삭제), AI를 빼면 기사가 무너지면 AI가 지배적 주제(→유지)다.
     - **오판 방지 경계 (핵심 동향을 놓치지 않기 위한 하한선)**:
       - **유지** — AI 인프라 투자·자체 LLM/파운데이션 모델 구축·AI 조직/자회사 설립·특정 AI 도입 프로젝트처럼 **AI가 기사의 주된 프레임(제목·리드가 AI를 다루고 본문 다수가 그 AI 내용)으로 비중 있게** 다뤄지는 경우. "금융사가 AI에 투자·도입한다"는 프로젝트 핵심 동향은 이 하한선으로 반드시 살린다.
       - **삭제** — AI가 다른 주제와 병렬로 나열되는 여러 축 중 하나이거나(예: 자금 사용처가 스테이블코인·AI 인프라·기타로 병렬), 다른 주제(앱 개편·행사·정책)의 일부 수단·기능으로만 등장하는 경우.
     - **대표 판정 사례 (금융사 주체이나 AI 부차 → 삭제)**: 은행 앱 UI/UX 개편 기사에서 AI 에이전트가 개편 요소 중 하나(News 1055) / 오픈이노베이션 행사가 핵심이고 금융사 AI 협력은 곁가지·초기 논의(News 1046) / 소상공인 특화 신용평가 정책이 핵심이고 AI는 평가 방식(News 1037) / IPO 신주 유입 자금의 사용처가 핵심이고 AI 인프라 투자는 스테이블코인 등과 병렬 축(News 985).
     - **방향 전환 이력**: News 985(케이뱅크 IPO 자금)는 "금융사가 주체이고 AI 인프라 투자가 언급되므로 남겨도 된다"는 판단에서 **삭제로 방향이 바뀌었다.** 판별 질문은 같았지만 적용이 갈렸던 사례이며, 이로써 기준은 "AI가 언급·등장하면 유지"가 아니라 "**AI가 지배적 주제여야 유지**"로 확정됐다.
3. **키워드 오탐** — 수집 키워드가 회사명만으로 매칭되고 실제 기사에 AI/AX 관련 내용이 없는 경우 관련 없음으로 처리한다.
4. **증시·경제 브리핑(정형 시황 기사)** — 매일 반복 발행되는 정형화된 시장 시황 요약 기사는 관련 없음으로 처리한다. "오늘의 증시 동향", "코스피·코스닥 마감 시황", "환율·금리 브리핑"처럼 특정 AI/AX 이슈를 다루지 않고 일반 시장 지표 나열이 본문의 대부분인 기사가 여기 해당한다. 이런 기사는 AI 언급이 있더라도 "AI 관련주 강세" "AI 반도체株 상승" 식으로 여러 지표·테마 중 하나로 스치듯 나열될 뿐이므로, 본질적으로 1번 **"핵심 주제 vs 배경 언급"의 하위 유형**(AI가 배경 언급)이다. 다만 이런 기사는 "AI 관련주" 같은 테마 키워드나 종목 시황에 회사명이 걸려 반복 수집되는 별도 패턴이라 소항목으로 명시해 둔다. 대표 예시: "코스피, 외국인 매수에 2,700선 회복… AI·반도체주 강세" — 제목에 AI가 있어도 실제 내용은 지수·수급·환율 브리핑이므로 삭제 대상이다.
5. **AI 기업 단독 동향(금융/보험 연결 없음)** — AI 기업(파운데이션 모델·AI 솔루션·AI 인프라 전문기업, 빅테크의 AI 사업 부문 포함)이 주체인 기사라도, **금융사 또는 보험사와의 연결(협업·계약·투자·도입·검토 등)이 기사의 핵심 주제가 아니면 관련 없음으로 처리한다.** 프로젝트가 보려는 것은 "AI 기업 × 금융/보험" 접점이지 AI 기업 자체의 일반 동향(제품 출시·경쟁·지정학·규제·경영진 발언 등)이 아니다. 즉 **모든 관련 기사는 금융사 또는 보험사가 실질적 당사자로 관여**해야 한다.
6. **묶음·단신 브리핑 기사 (예외 없음)** — `[금융픽]`·`[이코노 브리핑]`·`[DD퇴근길]`·`[은행가]`·`[금융家 브리핑]`·`[보험·카드24시]`처럼 서로 무관한 여러 단신을 한 기사에 묶어 발행하는 유형은 **예외 없이 관련 없음으로 처리**한다. 묶음 기사는 구조적으로 1-b의 삭제 조건("AI가 다른 주제와 병렬로 나열되는 여러 축 중 하나")에 정확히 해당한다 — 묶음은 본질적으로 병렬 나열이기 때문이다. 별도 코드 `6`으로 기록한다.
   - **판정 순서**: 만나는 즉시 삭제할 수 있다.
   - **삭제하되 이것을 반드시 남긴다**: 묶음 안에 1~2급 AI 소식이 있었으면, 삭제할 때 사유(reason)에 **그 AI 단신의 요지를 한 줄로** 적는다(예: "묶음 삭제. 안에 IBK기업은행 AI 크레탑 서비스 출시 단신 포함").

**기준 간 우선순위 — `1-b`가 아래 「연결 인정 범위」의 (a)~(d)보다 우선한다**

같은 기사에 기준 `1-b`와 "스코프 축소" 절의 「연결 인정 범위」가 **서로 다른 답을 주는** 경우가 실제로 나왔다. **`1-b`가 이긴다.**

> **AI가 상대 회사의 수식어로만 등장하면, 그 상대가 AI 전문기업이어도 `1-b`로 삭제한다.**

- **계기 — `News 3345`~`3348`(토스와 PFCT의 신용평가 모형 공동개발 MOU, 4개 매체)**. 「연결 인정 범위」의 **(a) 직접 협업·공동개발**에 정면으로 해당해 유지였으나, `3345`는 833자 본문에서 `AI`와 `인공지능`이 합계 **2회**뿐이고 그것이 **전부 *"AI 기반 기술금융사 PFCT"*라는 상대 회사 수식어**였다. **4개 매체 제목 어디에도 AI가 없다.** 사용자가 **삭제 유지로 확정**했다.
- **왜 `1-b`가 이기는가**: 「연결 인정 범위」가 묻는 것은 *"금융/보험과 AI 기업이 붙었는가"*이고 `1-b`가 묻는 것은 *"이 기사의 지배적 주제가 AI인가"*다. **거래 상대가 AI 기업이라는 사실은 그 거래의 내용이 AI라는 뜻이 아니다.** 상대의 업종이 유지 근거가 되면, `1-b`의 판별 질문(*"AI를 빼도 기사가 성립하는가"*)이 **AI 기업이 등장하는 모든 기사에서 무력해진다.**
- **판별은 새로 만들지 않는다** — `1-b`의 판별 질문을 그대로 쓴다. 위 건은 AI를 빼도 *"대안 데이터 기반 신용평가 모형 공동개발"*로 온전히 성립한다(협약의 내용물이 토스스코어, 한국평가데이터 데이터, 여신심사 전략이고 AI 기술 서술이 없다).
"""

# docs/planning.md "스코프 축소: AI 기업 단독 동향 제외" 절 — "연결(관련·협업)"의 인정 범위 (a)~(f).
_CRITERIA_SCOPE = """\
**"연결(관련·협업)"의 인정 범위**: 무엇을 "금융/보험과 연결됐다"로 볼지는 아래로 정의한다. 핵심 판별은 기준 1 "핵심 주제 vs 배경 언급"과 동일하다 — 금융/보험과의 접점이 **기사의 실제 주제**여야 하며, 스치듯 언급된 배경이면 인정하지 않는다.
- **인정(유지)**: (a) 직접 협업·계약·공동개발·합작·PoC/파일럿, (b) 금융사·보험사가 그 AI 기업의 제품·모델·솔루션을 도입·구축·검토·평가·테스트, (c) 금융사·보험사의 그 AI 기업/기술에 대한 지분투자·전략적 제휴, (d) 금융사·보험사 주체가 특정 AI 기업/기술을 두고 도입 방향을 밝히는 전략 발언. → **도입 "검토·평가" 수준까지 넓게 인정**한다(직접 계약만 고집하지 않음). 이는 "금융권이 곧 도입할 유망 AI 기업"을 접점 초기 단계에서라도 포착하기 위한 의도적 완충이다.
  - ⚠️ **(a)~(d)는 기준 `1-b`를 이기지 못한다.** AI가 상대 회사의 수식어로만 등장하면 그 상대가 AI 전문기업이고 (a) 직접 공동개발이어도 **`1-b`로 삭제한다.**
- **불인정(삭제)**: (e) AI 기업이 자사 고객·레퍼런스를 나열하는데 금융사가 그중 하나로만 스쳐 지나가고, 그 금융 사례의 실제 내용(어느 업무에 어떻게 적용됐는지)은 다루지 않는 경우 → 배경 언급으로 본다. (f) 금융/보험이 전혀 등장하지 않는 순수 AI 기업 동향.
- **경계(참고)**: 애매하면 **"그 금융/보험 접점을 빼도 이 기사가 성립하는가"**를 묻는다. 접점을 빼도 기사가 온전하면 접점은 배경(→삭제), 접점이 빠지면 기사가 무너지면 핵심 주제(→유지)다.
"""

# docs/planning.md "주요 이슈(Insight) 승격 기준" 절 — 경계 A~E의 당사자 자격 판정 부분.
# 공통 적용 조항으로 News 1차 필터에도 걸린다(같은 문서 "적용 범위(경계 A~E 공통)").
_CRITERIA_BOUNDARIES = """\
**당사자·상대·투자대상 자격 경계**: 아래는 "금융사/보험사 당사자" 자격이 실무에서 흔들리는 경계 케이스를 확정한 것이다. **공통 원칙은 기업의 법적 업종 간판이 아니라 그 건(engagement)의 실제 주제가 무엇인가**이며, 이는 관련성 판단 기준 1-b("AI를 빼도 기사가 성립하는가")·"연결 인정 범위"("접점을 빼면 기사가 무너지는가")와 동일한 판별선이다.

- **(경계 A) 금융권 당사자 자격 — 자본시장·금융 IT 인프라 사업자 포함 여부 (조건부 인정)**: 코스콤처럼 자본시장·금융결제·금융 데이터 인프라를 **본업으로 하는** 사업자를 "금융사/보험사 당사자"로 인정할지의 경계다. 코스콤은 한국거래소 계열 자본시장 IT 인프라 사업자로, 은행·보험·카드·증권 같은 직접 금융사는 아니다.
  - **확정 규칙 — 조건부 인정**: 해당 건의 **핵심 주제가 "금융 데이터·금융 서비스에 AI를 적용"하는 것일 때에 한해** 금융권 당사자로 인정한다. 인정 범위는 **"자본시장·금융결제·금융 데이터 인프라를 본업으로 하는 사업자"로 한정**하고, 일반 IT/SI·SW 벤더로 넓히지 않는다.
  - **⚠️ 금융·보험 업계 공동기관(협회·연수원·중앙회·재단 등)의 처리**: 이 유형은 **경계 A를 넓히지 않는다.** **가르는 선은 기관의 간판이 아니라 *그 건에서 그 기관이 하는 일*이다.** ① 그 기관이 **금융 서비스의 운영 인프라를 직접 제공**하는 건(공동 모델·공동 시스템의 구축·가동, 결제·보안·데이터 인프라 운영)이면 경계 A로 **인정**한다. ② 그 기관의 **회원사 공동사업·교육·연수·이익대변·출자/지배구조**가 주제인 건이면 **불인정**한다. **이사사가 보험사라는 사실만으로 당사자 자격을 만들지 않는다** — 그 논리를 허용하면 회원사에 금융사가 들어 있는 모든 협회 기사가 금융권 당사자가 되어 "금융/보험 당사자 필수" 요건이 소멸한다.
  - ⚠️ **이 항목은 대개 발동하지 않는다 — 그 앞에서 기준 1-b가 먼저 끝내기 때문이다.** 당사자 자격을 따지기 전에 **"AI가 이 기사의 지배적 주제인가"를 먼저 묻는다.**
  - **News 1309 판정 정정 — 사유는 (b) "AI 동향이 아님"이고 코드는 `1-b`다**: RA가 사유를 `기타`로 두고 (a) 당사자 요건 미달 / (b) 기관 분쟁이라 AI 동향이 아님 두 갈래로 남긴 건에 대한 판단이다. **(b)를 1차 사유로 확정**한다.
    - **근거**: 그 기사가 AI를 지배적 주제로 다뤘다면 당사자 자격 논쟁 자체가 붙지 않았을 것이다. **당사자 자격이 쟁점이 됐다는 사실 자체가 AI가 지배적 주제가 아니었다는 방증**이고, 1-b의 판별 질문("AI를 빼도 기사가 성립하는가")에 출자·의결 분쟁 기사는 그대로 걸린다.
    - **(a)를 1차 사유로 삼지 않는 이유**: (a)로 적으면 "보험사가 의결 주체인 건은 당사자가 아니다"라는 과잉 일반화가 남아, **보험사가 실제로 AI 사업의 의결·출자 주체인 정상 건까지 죽인다.** 사유는 결과가 같아도 남는 규칙이 다르므로 정확히 골라야 한다.
- **(경계 B) AI 기업 상대 자격 — 데이터/DB·클라우드 인프라 벤더 포함**: "상대(AI 기업)"는 기업의 업종 간판(순수 AI 전문기업인지)이 아니라 **그 협업·계약의 지배적 주제가 AI 역량 구축·제공인지**로 판정한다. 몽고DB·클라우드·범용 DB 같은 데이터/인프라 벤더라도, 해당 건의 핵심 주제가 AI 데이터인프라·벡터DB·모델 서빙 등 **AI를 목적으로 한 협업**이면 상대로 인정한다. 반대로 AI 목적이 아닌 일반 DB/클라우드 계약에 AI가 곁들여진 정도면 기준 1-b로 걸러진다.
- **(경계 C) AI 투자 대상 — 피지컬 AI/로봇 등 non-소프트웨어 AI 포함**: "AI 투자"의 대상 AI에는 소프트웨어 AI뿐 아니라 **피지컬 AI·로봇·자율주행 등 embodied AI**도 포함한다. AI가 그 투자 대상 기업/기술의 **핵심 역량**이면 형태(소프트웨어/하드웨어)를 가리지 않는다. 단 AI 요소가 없는 순수 하드웨어·제조 투자(AI 없는 로봇 제조 등)는 제외한다.
- **(경계 D) 금융권 당사자 자격 — 금융·보험 그룹의 비금융 자회사(요양·시니어케어·헬스케어 등) (조건부 인정)**: 삼성생명 자회사 삼성노블라이프, KB금융 계열 KB골든라이프케어처럼 **금융·보험 그룹에 속하지만 업태 자체는 금융·보험이 아닌 자회사**를 "금융사/보험사 당사자"로 볼지의 경계다.
  - **확정 규칙 — 조건부 인정**: 그 자회사가 하는 사업이 **모회사의 금융·보험 사업과 실질적으로 연결될 때에 한해** 금융권 당사자로 인정한다. 구체적으로 아래 중 하나에 해당하면 인정한다. (i) 보험 상품의 급부·서비스 제공(요양·간병·건강관리 등 보험금을 대신하거나 보험 상품에 연계되는 서비스), (ii) 금융·보험 상품의 판매·연계 채널, (iii) 기사 자체가 그 건을 **그룹의 금융·보험 사업 확장 전략**으로 서술하는 경우.
  - **불인정**: 지분·계열 관계만 있고 그 건이 모회사의 금융·보험 사업과 무관한 경우. **"그룹 계열이기만 하면 인정"으로 넓히지 않는다.**
  - **⚠️ 당사자 자격은 지배적 주제 요건을 면제하지 않는다**: 경계 D로 당사자 자격이 인정돼도, 그 접점이 기사의 **지배적 주제**여야 유지된다(기준 1-b). 실제로 이 규칙의 계기가 된 **News 1218(에브리봇 FCC 인증)은 경계 D 신설 후에도 삭제 판정이 그대로 유지된다** — 기사 핵심이 미국 수출·인증이고 케어로봇 실증은 여러 사례 중 하나로 나열될 뿐이라 "접점을 빼도 기사가 성립"하기 때문이다. 이 경계가 실제로 결과를 바꾸는 지점은 **그 자회사의 AI 도입·협업 자체가 기사의 핵심 주제일 때**다(예: "KB골든라이프케어, 요양시설에 AI 돌봄 시스템 도입" 같은 기사).
- **(경계 E) 금융 규제·감독기관(금융위원회·금융감독원 등)의 당사자 자격 — 조건부 인정**: 경계 A(공동기관)는 **회원사 기관**을 다룰 뿐 **감독당국**을 다루지 않아 어느 경계에도 걸리지 않으므로 별도로 둔다.
  - **확정 규칙 — 조건부 인정**: 그 기관이 **금융권의 AI 도입·활용을 규율하는 주체로서 그 건의 핵심 당사자**일 때에 한해 금융권 당사자로 인정한다. 즉 **"규제기관이 나오면 유지"가 아니라 "규제기관이 주체일 때만 유지"**다.
    - **인정**: 금융권 AI에 적용되는 **규제·제도·가이드라인·감독방향을 그 기관이 발표·시행·개정·해제**하는 건. 실측 예 — `금융위, AI 우수 금융사 망분리 전면 해제`. 이 유형은 개별 금융사의 AI 도입 **조건 자체**를 바꾸므로 파급 범위가 개별사 건보다 넓다.
    - **불인정**: (i) 규제·감독이 **다른 주제의 배경으로 깔린** 건 — 인물 프로필·용어 해설·시황·업권 일반 동향. (ii) 그 기관이 발화 주체이지만 **내용이 AI 규율이 아닌** 건(가계부채·내부통제 등). (iii) **금융권 규율이 아닌 일반 AI 산업 육성 정책**(과기정통부 등).
    - **기관 범위 한정**: 인정 대상은 **금융권을 규율하는 기관**(금융위·금감원, 그리고 금융권 AI 규율에 관여하는 한도의 기관)이다. **"공공기관·정부부처면 인정"으로 넓히지 않는다.**
  - **⚠️ 당사자 자격은 지배적 주제 요건을 면제하지 않는다. 이 유형은 대부분 기준 1-a/1-b에서 먼저 끝난다.** 규제·감독 언급이 금융 기사 어디에나 배경으로 깔리기 때문이다. **판정 순서는 종전대로 1-b가 먼저다.**
- **적용 범위(경계 A~E 공통)**: 이 경계들은 News 1차 필터에서도 동일하게 적용한다.
"""

# docs/planning.md "임시 스코프 제외: KT·LG·SK" 절.
_CRITERIA_SKLS = """\
**임시 스코프 제외: KT·LG·SK (`S-KLS`)**

**결정**: 현재 KT·LG·SK는 스코프에서 제외한다. 이 회사들 **자신이 핵심 주체인 AI 인프라 투자·전략·제품 뉴스**(예: KT의 AI데이터센터 투자, LG전자의 로봇 사업, SK텔레콤의 AI팩토리)를 대상으로 한다.

**근거**: 지금은 금융사·보험사·AI 기업 축에 우선 집중하기 위한 **운영상 스코프 축소**다.

**예외(유지 대상)**: KT/LG/SK 계열 조직이라도, 기사의 **핵심 주제가 금융 데이터·금융 서비스에 AI를 직접 적용하는 협업**이면 유지한다. 이는 그 기사가 실질적으로 "금융사/보험사 축"에 걸치는 콘텐츠이기 때문이다. 대표 사례: LG AI연구원-코스콤이 '엑사원'에 국내 금융 데이터를 결합해 주식시장 예측 서비스를 공동 구축한 건. 즉 판정 기준은 "회사가 KT/LG/SK 계열인가"가 아니라 앞의 **"핵심 주제 vs 배경 언급"**이며, 핵심 주체가 KT/LG/SK 자신의 사업이면 제외, 계열이 재료·파트너로 참여하되 핵심 주제가 금융 AI 적용이면 유지다.

**적용 단계**: 이 정책은 **News 단위 노이즈 판정(관련성 판단 1차 필터)에서부터 적용**된다.
"""

# .claude/agents/research-analyst.md — 성과 수치가 먼저 읽히는 건에 1-b를 먼저 던지는
# 규칙(News 1514 실패 사례). RA 문서 원문을 그대로 옮겼다(해요체 포함, 재서술 없음).
_CRITERIA_NEWS_1514 = """\
⚠️ **성과 수치가 눈에 먼저 들어온 건일수록 1-b를 먼저 적용하세요.** 판별은 *"그 시스템을 가리켜 원문이 `AI`, `인공지능`, `머신러닝`, `학습` 중 하나를 쓰는가"* — **안 쓰면 규칙 기반이고, 수치가 아무리 강해도 삭제**입니다. 기사에 AI가 나와도 **그 주어가 우리 쪽 회사인지 사기꾼, 경쟁사, 업계 배경인지**를 함께 보세요.

> **실패 사례**: `News 1514`(하나은행 eSIM 사기 1,450건과 185억원 차단)를 **"수치가 특정된 성과 기사"로 먼저 읽어 1-b 판정을 건너뛰었고**, 두 세션 동안 확정 유지 후보로 들고 있으면서 **원문의 AI 언급 주어를 한 번도 확인하지 않았습니다.** 실제로 하나은행이 쓴 것은 `FDS 시나리오`(규칙 기반)였고, 원문의 유일한 AI 언급은 **사기꾼이 홍보 영상을 AI로 만들었다**는 대목이었습니다. 1급으로 헤드라이너 3번까지 올라간 뒤 **사용자가 화면에서 발견**했습니다.
> ⚠️ **`FDS`, `탐지`, `차단`, `시나리오`는 AI 기사에 자주 함께 나오는 말이라 주변 어휘만으로 AI처럼 읽힙니다.** **새 축이 아니라 1-b를 "언제 던지는가"를 못박는 것입니다.**
"""

CRITERIA_TEXT = "\n".join([
    "## 관련성 판단 기준",
    _CRITERIA_RELEVANCE,
    "## 스코프 축소: AI 기업 단독 동향 제외 — \"연결\"의 인정 범위",
    _CRITERIA_SCOPE,
    "## 주요 이슈 승격 기준 — 당사자·상대·투자대상 자격 경계 (News 1차 필터에도 공통 적용)",
    _CRITERIA_BOUNDARIES,
    "## 임시 스코프 제외",
    _CRITERIA_SKLS,
    "## 판정 순서에 대한 주의",
    _CRITERIA_NEWS_1514,
])


# ============================================================================
# 시스템 프롬프트 조립 — 위 판정 기준 원문 + 임무·출력 지시문(PE 작성, 재서술 대상 아님).
# ============================================================================

# docs/planning.md 4-(b) 🔴 개정 (2026-09-15) "처방: 활성 Organization과 TechTopic의
# 이름 목록을 시스템 프롬프트에 넣는다" — 근본 원인이 `_build_user_message()`가 그
# 기사에 이미 태깅된 것만 알려주고 등록 대장 전체를 안 알려주는 것이었기 때문이다.
# 인카금융서비스 건(후보 자리가 있는데도 태그 추가로 냄)이 그 증거다.
#
# 🔴 별칭(aliases)은 넣지 않는다(PE 판단, 아래 이유).
# 1. 실측(services.llm 모듈독스트링 아래) 기준 이름만으로도 기업 132개(941자) + 기술
#    주제 25개(195자)인데, 별칭까지 넣으면 합쳐서 2,294자가 더 붙는다(기업 별칭
#    643자 + 기술 주제 별칭 1,651자) — 이름만 넣을 때의 두 배를 넘는 증가분이다.
#    별칭이 특히 기술 주제 쪽에 몰려 있어(1,651자, 이름 195자의 8배) 비용 대비
#    효과가 가장 낮은 축에 가장 큰 토큰을 쓰게 된다.
# 2. 별칭을 빼도 확정 시점 실행 정확도는 이미 지켜진다 — services/collector.py의
#    resolve_entity_by_name()이 태그 제거/추가 제안을 확정할 때 이름과 별칭을 모두
#    본다(2026-09-15 실측으로 이미 고친 경로, apps/setting/views.py
#    setting_run_review_confirm() 참고). 즉 LLM이 별칭 이름("KB금융")을 target_name으로
#    냈더라도 확정 단계에서 정확한 대상("KB금융지주")으로 이미 해석된다 — 별칭
#    누락으로 실제 실행이 실패하는 경로는 없다.
# 3. 별칭을 안 넣었을 때 남는 유일한 위험은 "이미 등록된 대상을 별칭만으로 언급한
#    기사를 LLM이 신규 후보로 잘못 분류하는 것"이다(예: "KB금융"만 나오고
#    "KB금융지주"라는 정식명이 없는 기사). 이 경우도 데이터가 틀리게 반영되는 게
#    아니라 SET-007/SET-008에 사람이 걸러야 할 중복 후보 하나가 더 뜨는 정도다 —
#    확정해도 아무 동작이 없는 종류라 대가가 작다. 그래서 전체 별칭 목록 대신,
#    아래 지시문에 "표기가 달라도 같은 대상으로 보이면 추가로 판단하라"는 한 문장만
#    더해 저비용으로 같은 위험을 줄인다.
def _build_registry_section() -> str:
    from apps.setting.models import Organization, TechTopic

    org_names = list(
        Organization.objects.filter(is_active=True).order_by("name").values_list("name", flat=True)
    )
    topic_names = list(
        TechTopic.objects.filter(is_active=True).order_by("name").values_list("name", flat=True)
    )
    return (
        f"현재 등록된 기업 목록({len(org_names)}개): {', '.join(org_names) or '없음'}\n"
        f"현재 등록된 기술 주제 목록({len(topic_names)}개): {', '.join(topic_names) or '없음'}"
    )


def _build_system_prompt() -> str:
    """등록 대장(활성 Organization·TechTopic 이름)을 조회해 시스템 프롬프트를 조립한다.
    호출마다 DB를 조회하지만 배치 중 등록 대장이 바뀌지 않는 한 매번 같은 문자열이
    나오므로, Bedrock의 ephemeral 캐시(classify_news()의 cache_control)가 그대로
    적중한다 — 캐시는 "텍스트가 같은가"만 보지 "코드가 상수인가 함수 호출인가"는
    보지 않는다."""
    return f"""당신은 AI Market Watch 프로젝트에서 수집된 뉴스 기사 한 건의 관련성을 판정합니다.

프로젝트 관심사는 국내 금융권(은행·보험사)의 AI/AX 도입 동향, 그리고 그와 연결된 AI 기업 동향입니다. 아래 판정 기준을 원문 그대로 적용하세요. 기준을 요약하거나 바꾸지 마세요.

<판정_기준>
{CRITERIA_TEXT}
</판정_기준>

<등록_대장>
{_build_registry_section()}
</등록_대장>

임무: 기사 한 건에 위 기준을 적용해 판정하고, 아래 스키마로만 응답하세요.

- relevance: 기사가 기준을 통과해 남아야 하면 "keep", 어느 기준에 걸려 삭제해야 하면 "delete".
- criterion_code: relevance가 "delete"면 해당 기준 코드(1-a / 1-b / 3 / 4 / 5 / 6 / S-KLS / 기타 중 하나)를 적으세요. relevance가 "keep"이면 빈 문자열로 두세요. 🔴 criterion_code "2"(동일 사건 중복 보도)는 절대 쓰지 마세요 — 이 판정은 다른 기사와 비교할 수 없는 단건 판정이라 "2"를 낼 근거가 없습니다.
- reason: 판정 사유를 1~2문장으로 적으세요.
- tag_corrections: 위 <등록_대장>을 기준으로, 핵심 주체가 아니라 배경 언급이라 떼야 하는 태그(현재 태깅된 것 중)나, 핵심 주체인데 태깅이 빠져 있어 추가해야 하는 태그(등록 대장에 있는 이름 중)가 있으면 각각 한 항목씩 적으세요. 표기가 정확히 같지 않아도(약칭, 계열사 표기 등) 등록 대장의 어느 항목과 같은 대상으로 보이면 그 항목의 이름으로 추가하세요 — 등록 대장에 있는 대상은 tag_candidates가 아니라 여기로 적어야 합니다. 없으면 빈 배열로 두세요.
  - action: "add" 또는 "remove"
  - axis: "organization"(기업) 또는 "tech_topic"(기술 주제)
  - target_name: 대상 이름(등록 대장에 있는 정식 이름을 쓰세요)
  - reason: 교정 사유
- tag_candidates: 본문의 핵심 주체인데 <등록_대장>의 기업·기술 주제 어느 목록에도 없는 대상이 있으면(아직 이 프로젝트에 등록되지 않은 것으로 보이면) 각각 한 항목씩 적으세요. 기업뿐 아니라 기술 주제도 해당됩니다. 여기서 새로 등록하는 것이 아니라 후보로만 남기는 것입니다. 없으면 빈 배열로 두세요.
  - name: 이름
  - axis: "organization"(기업) 또는 "tech_topic"(기술 주제)
  - reason: 왜 핵심 주체로 보이는지
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "relevance": {"type": "string", "enum": ["keep", "delete"]},
        "criterion_code": {"type": "string"},
        "reason": {"type": "string"},
        "tag_corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "remove"]},
                    "axis": {"type": "string", "enum": ["organization", "tech_topic"]},
                    "target_name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["action", "axis", "target_name", "reason"],
                "additionalProperties": False,
            },
        },
        "tag_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "axis": {"type": "string", "enum": ["organization", "tech_topic"]},
                    "reason": {"type": "string"},
                },
                "required": ["name", "axis", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "relevance", "criterion_code", "reason",
        "tag_corrections", "tag_candidates",
    ],
    "additionalProperties": False,
}


def _get_client() -> AnthropicBedrock:
    """AnthropicBedrock 클라이언트를 만든다. 자격증명은 Django 설정을 거쳐 읽는다
    (.env의 AWS_ACCESS_KEY_ID·AWS_SECRET_ACCESS_KEY·AWS_DEFAULT_REGION)."""
    return AnthropicBedrock(
        aws_access_key=settings.AWS_ACCESS_KEY_ID,
        aws_secret_key=settings.AWS_SECRET_ACCESS_KEY,
        aws_region=settings.AWS_DEFAULT_REGION,
    )


def _build_user_message(news) -> str:
    org_names = list(news.organizations.order_by("name").values_list("name", flat=True))
    tech_names = list(news.tech_topics.order_by("name").values_list("name", flat=True))
    return (
        f"제목: {news.title}\n"
        f"현재 태깅된 기업: {', '.join(org_names) or '없음'}\n"
        f"현재 태깅된 기술 주제: {', '.join(tech_names) or '없음'}\n"
        f"매칭된 수집 키워드: {', '.join(news.matched_keywords) or '없음'}\n\n"
        f"본문:\n{news.body}"
    )


def _parse_response(news, response) -> dict:
    """구조화 출력을 파싱하고 금지된 criterion_code를 방어한다. 실패하면 그 건만
    LLMJudgmentError로 남긴다 — json.loads()로만 파싱한다(문자열 매칭 금지, SDK 권고)."""
    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise LLMJudgmentError(
            f"News {news.pk}: 응답에 text 블록이 없어요(stop_reason={response.stop_reason})."
        )
    try:
        data = json.loads(text_block.text)
    except json.JSONDecodeError as exc:
        raise LLMJudgmentError(f"News {news.pk}: 응답 JSON 파싱에 실패했어요: {exc}") from exc

    if data.get("criterion_code") == FORBIDDEN_CRITERION_CODE:
        logger.error(
            "News %s: LLM이 금지된 criterion_code=2(중복 보도)를 반환했어요 — 이 기준은 "
            "RA 몫이라 단건 판정에서 나오면 안 됩니다. 프롬프트나 모델 응답의 구조적 "
            "이상으로 보고 이 건을 실패로 남겨요.", news.pk,
        )
        raise LLMJudgmentError(f"News {news.pk}: 금지된 criterion_code=2를 반환했어요.")

    usage = response.usage
    data["_usage"] = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return data


def classify_news(news) -> dict:
    """뉴스 한 건을 Bedrock Haiku로 판정한다.

    Returns:
        파싱된 판정 dict(relevance/criterion_code/reason/tag_corrections/
        tag_candidates) + "_usage"(입력·출력·캐시 쓰기·캐시 읽기 토큰).

    Raises:
        LLMStructuralError: 인증·권한·리소스(모델 ID·리전) 오류. 호출부가 배치를
            즉시 끊는 판단 재료로 쓴다.
        LLMJudgmentError: 그 밖의 실패(rate limit·네트워크·응답 형식 불량·금지된
            criterion_code). 그 건만 실패로 남기고 다음 건으로 진행한다.
    """
    client = _get_client()
    try:
        response = client.messages.create(
            model=settings.BEDROCK_MODEL_FAST,
            # 🔴 PE 재수정(2026-09-16 실측 사고) — 1024는 News 3949(pk130) 실패의
            # 직접 원인이었다: 재현 호출에서 stop_reason="max_tokens", output_tokens
            # 정확히 1024로 잘려 reason 문자열이 중간에 끊긴 채 JSON 파싱이
            # 실패했다(Unterminated string). 같은 호출을 max_tokens=2048로 다시 하니
            # stop_reason="end_turn", 실제 소비는 992토큰으로 자연 종료됐다.
            # pk130(67건 성공)·pk124(45건) 평균 출력은 각각 319·324토큰이라 정상
            # 케이스는 1024에도 전혀 안 걸린다 — 이번 실패는 판정 이유를 길게 쓴
            # 꼬리값(outlier) 케이스였다. 2048은 그 꼬리값(992)에도 약 2배의 여유를
            # 두면서, 출력 토큰은 상한이 아니라 실제 생성량만큼만 과금되므로(모델이
            # 상한이 올랐다고 더 길게 쓰지 않는다 — end_turn으로 자연 종료) 평균
            # 케이스의 비용에는 영향이 없다.
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": _build_system_prompt(),
                # TTL 1시간 — 기본 5분이 아니라 1시간을 쓰는 이유는 배치 중간 만료가 아니라
                # 이어하기(다음 날 이어할 때 등)의 호출 간격이 5분을 넘기 때문이다(설계
                # 7-(b)). count_tokens는 Bedrock에서 지원되지 않으므로 토큰 수를 미리 세는
                # 코드는 두지 않는다 — 실제 호출 응답의 usage로만 안다.
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }],
            messages=[{"role": "user", "content": _build_user_message(news)}],
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        )
    # 좁은 것부터 넓은 것 순 — 재시도해도 같은 결과인 것(인증·권한·리소스)과
    # 재시도하면 다를 수 있는 것(rate limit·네트워크·기타 상태 오류)을 구분한다.
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
        logger.error("News %s 판정 중 구조적 오류(인증/권한/리소스): %s", news.pk, exc)
        raise LLMStructuralError(str(exc)) from exc
    except anthropic.RateLimitError as exc:
        logger.warning("News %s 판정 중 rate limit에 걸렸어요: %s", news.pk, exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIConnectionError as exc:
        logger.warning("News %s 판정 중 네트워크 오류: %s", news.pk, exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIStatusError as exc:
        logger.warning("News %s 판정 중 API 오류(status=%s): %s", news.pk, exc.status_code, exc)
        raise LLMJudgmentError(str(exc)) from exc
    else:
        return _parse_response(news, response)


# ============================================================================
# 2단계 두 번째 호출 — 기준 2(동일 사건 중복 보도) 판정. docs/planning.md "기준
# 2(동일 사건 중복 보도)를 2단계의 두 번째 LLM 호출로 옮긴다"(2026-09-17 확정), 그리고
# 그 다음 라운드 "코드가 후보를 좁히고 LLM은 확인만 한다"(2-6)가 정본.
#
# 🔴 classify_news()와 다른 것 넷(같은 문서 2번·6번·7번·11번) — 복사해 오면 자동으로
# 어긋나는 자리다.
#   - 배치 전체가 아니라 코드가 좁힌 후보 묶음 단위로 호출된다(2-6). 실측(2026-09-17
#     야간, 검증 통과 47건 전량을 한 번에 물은 결과 묶음 0개·input 88,892토큰·약
#     124원)이 "찾아라"를 통짜로 시키면 성과 없이 비용만 든다는 것을 보여 줬다.
#     services/dedup_candidates.py의 find_duplicate_candidates()가 사건 지문·숫자
#     토큰으로 후보를 먼저 좁히고, 이 함수는 후보 묶음 하나를 받아 "이 중 실제로
#     같은 사건인 것은?"만 확인한다(찾기에서 확인으로 — PM 확정). 후보 안에서도
#     여러 사건이 섞여 있을 수 있으므로(25건 후보에 카카오 두 사건 + 무관 기사가
#     섞였던 실측), 응답 스키마(groups 배열)는 그대로 유지해 한 호출이 여러 하위
#     묶음을 낼 수 있게 둔다.
#   - 호출 여부 자체가 후보 수에 달려 있다 — 후보가 0개면 이 함수를 아예 부르지
#     않는다(호출부 services/runner.py._run_dedup()의 책임, 2-6-(d)).
#   - 캐싱을 켜지 않는다 — 후보 묶음마다 입력(기사 목록)이 다르므로 시스템 프롬프트가
#     고정이어도 캐시가 적중하지 않는다(같은 문서 7번).
#   - 대표(어느 기사를 남길지)는 이 함수가 정하지 않는다. LLM은 "어느 기사들이 같은
#     사건인가"만 내고, 대표 선정은 services/runner.py가 결정론적으로 한다(같은 문서
#     5번 "틀리면 안 되는 것을 생성 모델에 맡기지 않는다").
# ============================================================================

# RunJob.prompt_version에 기존 cleanup 버전과 이어 붙는다(services/runner.py
# _run_dedup() 참고) — 단계마다 따로 매긴다는 같은 문서 11번 근거.
# 🔴 2026-09-17b — 후보 묶음 배선과 함께 프롬프트 내용 자체가 바뀌어서("찾아라"에서
# "확인하라"로, 후보 전제·matched_signals·over_soft_cap 설명 추가) 버전을 올린다.
PROMPT_VERSION_DEDUP = "dedup-2026-09-17b"

# 🔴 본문 절단 길이 — PE 실측(2026-09-17, 검증 통과 News 260건 전수)으로 정했다.
# "본문 전량을 보내지 않는다"(같은 문서 3번)면서도 "숫자 토큰을 잘라내지 않는다"·
# "첫 직접인용문까지는 포함한다"(같은 문서 3번 2026-09-17 야간 추가) 두 요건을 함께
# 만족해야 한다.
#
# 실측: News.body에서 첫 따옴표(중복 판정의 판별 신호, 3-1)가 나타나는 위치의 p95가
# 1,919자, 첫 숫자 토큰(2-3-(a) 1순위 신호)이 나타나는 위치의 p95가 1,498자였다
# (정규식 [\"'‘’“”] / \d[\d,.]*\s*(%|퍼센트|만|억|조|건|명|개), 260건 전수 스캔).
# 2,000자는 그 위(p95)에 여유를 조금 더 얹은 값이다 — 이 문턱을 넘겨야 두 신호가
# 다 잘리는 경우가 5% 미만으로 줄어든다.
#
# ⚠️ 그래도 전부 잡히지는 않는다 — 실측 표본에 첫 따옴표가 2,595자에 나온 기사가
# 하나 있었다(News 4054, 헤드라인 여러 줄 뒤에 인용이 나오는 형태). "다 담을 수 없는
# 기사가 나오면 조용히 한쪽을 버리지 말고 보고한다"(같은 문서 3번)는 요건에 따라
# 여기 적어 둔다 — 되돌리는 조건(같은 문서 10번, "서로 다른 주에 2회")에 해당하는
# 사례가 쌓이면 이 값부터 다시 본다.
DEDUP_BODY_TRUNCATE_CHARS = 2000

# 🔴 입력 상한 — 넘으면 조용히 좁히지 말고 보고한다(같은 문서 2-1-(d) ⚠️, 2-2-(b) ⚠️).
# 지금 규모(3일 창, 신규분 15~40건 + 창 안 검증분 45~120건)의 합 상한(약 160건)에
# 여유를 크게 둔 값이다 — "며칠 밀린 날"처럼 창이 앵커 때문에 자동으로 늘어나는
# 경우를 오판하지 않기 위해서다(services/runner.py의 DEDUP_MAX_INPUT_COUNT가 이 값을
# 실제로 검사한다. 여기 상수로 두지 않고 그쪽에 둔 이유는 검사 자리가 입력을 조립하는
# runner.py이기 때문이다).

DEDUP_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "news_ids": {"type": "array", "items": {"type": "integer"}},
                    "fingerprint": {"type": "string"},
                },
                "required": ["news_ids", "fingerprint"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["groups"],
    "additionalProperties": False,
}


def _build_dedup_system_prompt() -> str:
    """기준 2(동일 사건 중복 보도) 판정 시스템 프롬프트. 판정 문장·판별 신호는
    재서술하지 않고 docs/planning.md에서 그대로 발췌한다(_build_system_prompt()의
    CRITERIA_TEXT와 같은 원칙, 같은 문서 11번 "재서술하지 않고 발췌한다").

    🔴 2026-09-17b — "찾아라"에서 "확인하라"로 물음이 바뀐다(PM 확정, 2-6). 이
    함수가 받는 기사 목록은 이미 코드(services/dedup_candidates.py)가 사건 지문·
    숫자 토큰 신호로 후보를 좁혀 놓은 것이라, LLM은 새로 후보를 찾는 것이 아니라
    "이 후보가 실제로 같은 사건인지"만 확인한다. <후보_전제>가 그 사정을 알려
    "후보로 묶였다는 사실 자체를 증거로 오인하지 말라"고 명시한다 — 실측(25건 후보에
    카카오 모두의 AI 8건 + 카카오 인적분할 4건 + 무관 기사 13건이 반올림된 큰 수로
    우연히 연쇄 연결됨)이 이 위험을 보여 줬다."""
    return """당신은 AI Market Watch 프로젝트에서, 코드가 신호(사건 지문·숫자 토큰)로 미리 좁혀 놓은 뉴스 기사 후보 묶음 하나를 받아 확인합니다. 당신의 임무는 "찾기"가 아니라 "확인"입니다 — 어떤 기사들이 같은 사건일 수 있는지는 이미 후보로 좁혀져 있고, 그중 실제로 같은 사건인 것이 무엇인지만 가려내면 됩니다.

<후보_전제>
이 묶음은 코드가 사건 지문(복합명사)이나 숫자 토큰이 겹친다는 "신호"만으로 자동으로 모은 것입니다 — 사람이나 LLM이 "같은 사건이다"라고 이미 확인한 것이 아닙니다. 숫자가 "1조"·"500만"처럼 크게 반올림된 값이면 서로 무관한 기사끼리도 우연히 같은 신호로 연쇄 연결될 수 있습니다. 그러니 이 묶음 전체가 하나의 사건이라고 가정하지 마세요. 실제로는 다음 중 하나입니다.
- 묶음 전체가 정말로 한 사건이다.
- 묶음 안에 서로 다른 사건이 여럿 섞여 있다(예: 8건이 사건 A, 4건이 사건 B, 나머지는 둘 다 아니다) — 이 경우 각각 별도 하위 묶음(groups의 서로 다른 원소)으로 나누세요.
- 묶음 안 어느 기사도 다른 기사와 같은 사건이 아니다 — 이 경우 groups를 빈 배열로 반환하세요.
</후보_전제>

<기준_원문>
동일 사건 중복 보도 — 여러 매체가 같은 행사·사건을 각자 기사화한 경우, 사실상 같은 뉴스로 취급하고 대표 1건만 남기고 나머지는 삭제한다.
</기준_원문>

<오판_비대칭>
오판의 방향이 비대칭입니다. 「같은 사건인데 안 묶음」은 화면에 중복이 남아 다음에 눈에 띄지만, 「다른 사건인데 묶음」은 아무도 그 존재를 모릅니다. 그래서 애매하면 묶지 않습니다.
</오판_비대칭>

<판별_신호>
1. 제목만으로 판정하지 않습니다. 제목이 닮았다는 것은 후보 신호일 뿐이고, 판정 근거는 본문 도입부여야 합니다.
2. 1순위 근거는 사건 지문(복합명사)과 숫자 토큰의 일치입니다. 둘 다 기자가 바꿔 쓰기 어려운 값이라 매체를 건너도 살아남습니다. 다만 이 묶음이 그 신호로 이미 모여 있다는 사실 자체는 증거가 아닙니다(위 <후보_전제>) — 본문을 직접 읽고 실제로 같은 사건인지 확인하세요.
3. 같은 날 발행은 보조 신호일 뿐입니다. 그것만으로 묶지 마세요.
4. 기술 주제가 같다는 것은 신호가 아닙니다. 이 배치의 기사는 전부 AI 관련입니다.
5. 애매하면 묶지 않습니다.
</판별_신호>

<중복이_아닌_경우>
따옴표 안 직접인용문이 기사마다 다르면 중복이 아닙니다(각자 취재한 인터뷰). 같으면(말을 바꿔 쓴 것 포함) 같은 보도자료를 받아쓴 중복입니다.

⚠️ 다만 이 규칙을 기계적으로 믿지 마세요. 따옴표 안 인용문이 서로 달라도, 기사가 직접 같은 사건(같은 그룹인터뷰·같은 행사)이라고 명시하고 같은 날짜·장소·화자·사진 출처가 겹치면 같은 사건일 수 있습니다. 인용문 일치는 강한 신호이지 유일한 신호가 아닙니다 — 본문 전체 맥락으로 판단하세요.

같은 연재물의 다른 회차도 이 기준으로 묶지 않습니다 — 연재 회차는 서로 다른 내용을 담으므로 중복이 아니다. 삭제 대상이 아니라 미승격 대상이며, 대표 1건만 남기는 처리도 하지 않는다.
</중복이_아닌_경우>

<입력_설명>
기사 목록 앞에는 이 묶음을 후보로 모은 신호(코드가 뽑은 사건 지문·숫자 토큰)와, 이 묶음이 통상 크기(20건)를 넘는 경보 대상인지가 먼저 표시됩니다. 그 뒤 기사 목록에는 [기존]과 [신규] 두 갈래가 있습니다. [기존]은 이미 검증을 통과해 화면에 떠 있는 기사이고, [신규]는 이번에 새로 판정 중인 기사입니다. 어느 쪽을 대표로 남길지는 판단하지 마세요 — 그것은 이 프로젝트의 코드가 별도 규칙으로 결정합니다. 당신은 오직 "어느 기사들이 실제로 같은 사건인가"만 판정하세요.
</입력_설명>

임무: 위 후보 묶음 안에서 실제로 같은 사건인 기사들을 하위 묶음으로 나눠 아래 스키마로만 응답하세요. 같은 사건이 하나도 없으면 groups를 빈 배열로 반환하세요.

- groups: 같은 사건으로 판단되는 기사 묶음의 배열입니다. 한 후보 안에 서로 다른 사건이 여럿 있으면 groups에 각각 별도 원소로 담으세요.
  - news_ids: 그 사건을 다룬 기사들의 pk 배열(반드시 2개 이상).
  - fingerprint: 이 묶음을 같은 사건으로 판단한 근거(사건 지문 복합명사·숫자 토큰 등)를 본문에서 그대로 뽑아 짧게 적으세요. 본문에 없는 내용을 지어내지 마세요.
"""


def _build_dedup_user_message(new_batch, window_news, matched_signals=None, over_soft_cap=False) -> str:
    """비교 대상 기사 목록을 조립한다. [신규]/[기존] 표시는 3번 "기존 검증분과 신규분을
    입력에서 갈라 표시한다"의 구현이다 — 다만 "어느 Insight에 묶였는지" 같은 추가
    정보는 넣지 않는다(같은 문서 3번 ⚠️ "틀리면 안 되는 것을 생성 모델에 맡기지 않는다"
    가 5번의 대표 선정에도 그대로 적용된다).

    🔴 2026-09-17b — matched_signals/over_soft_cap을 맨 앞에 얹는다(2-6). LLM이
    "이건 코드가 신호로 모은 후보일 뿐"이라는 사정을 알아야 후보를 곧이곧대로
    믿지 않는다(_build_dedup_system_prompt()의 <후보_전제>가 이 정보를 어떻게
    쓰라고 지시하는지 설명한다)."""
    lines = []
    signals_text = ", ".join(matched_signals) if matched_signals else "(신호 없음)"
    over_soft_cap_text = (
        "예 — 넘는다고 쪼개거나 버리지 마세요. 실제로 그만큼 큰 사건일 수 있습니다."
        if over_soft_cap else "아니오"
    )
    lines.append(
        f"[이 묶음을 후보로 모은 신호] {signals_text}\n"
        f"[통상 크기(20건) 초과 여부] {over_soft_cap_text}"
    )
    for label, batch in (("신규", new_batch), ("기존", window_news)):
        for news in batch:
            published = timezone.localtime(news.published_at).strftime("%Y-%m-%d %H:%M")
            body = news.body[:DEDUP_BODY_TRUNCATE_CHARS]
            lines.append(
                f"[{label}] pk={news.pk} 발행={published}\n제목: {news.title}\n본문: {body}"
            )
    return "\n---\n".join(lines)


def _parse_dedup_response(response) -> dict:
    """classify_news()의 _parse_response()와 같은 원칙(json.loads()만 쓴다, 문자열
    매칭 금지)이지만 금지 기준 코드 방어가 없다 — 이 호출 자체가 기준 2 전용이라
    막을 것이 없다."""
    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise LLMJudgmentError(
            f"중복 판정: 응답에 text 블록이 없어요(stop_reason={response.stop_reason})."
        )
    try:
        data = json.loads(text_block.text)
    except json.JSONDecodeError as exc:
        raise LLMJudgmentError(f"중복 판정: 응답 JSON 파싱에 실패했어요: {exc}") from exc

    usage = response.usage
    data["_usage"] = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return data


def find_duplicate_news(new_batch, window_news, matched_signals=None, over_soft_cap=False) -> dict:
    """기준 2(동일 사건 중복 보도) 판정 — 코드가 좁힌 후보 묶음 하나를 확인한다
    (2026-09-17b, 2-6 "찾아라"에서 "확인하라"로).

    Args:
        new_batch: 이 후보 묶음에 속한 News 중 이번 배치에서 "유지"로 제안된 것
            (삭제 후보 — 대표가 아니면 지워질 수 있는 쪽).
        window_news: 이 후보 묶음에 속한 News 중 비교 창 안의 검증 통과분(비교
            대상 전용 — 이 호출로는 절대 삭제되지 않는다, 같은 문서 2-1-(b)).
        matched_signals: 이 후보를 모은 신호 목록(services/dedup_candidates.py
            CandidateGroup.matched_signals) — 프롬프트에 그대로 실어 LLM이 "신호가
            겹쳤다는 사실 자체는 증거가 아니다"를 알게 한다.
        over_soft_cap: 이 후보가 경보선(20건)을 넘었는지 — 넘어도 쪼개거나 버리지
            말라는 지시를 프롬프트에 함께 싣는다(2-6-(c)).

    Returns:
        {"groups": [{"news_ids": [...], "fingerprint": "..."}]} + "_usage". 하나의
        후보 안에 여러 사건이 섞여 있으면 groups에 여러 원소로 나뉘어 나올 수 있다.

    Raises:
        LLMStructuralError / LLMJudgmentError: classify_news()와 같은 분류.
    """
    client = _get_client()
    try:
        response = client.messages.create(
            model=settings.BEDROCK_MODEL_FAST,
            # 🔴 잠정치(PE 판단, 첫 실행 실측 전) — classify_news()의 2048(News 130
            # 실패 사고로 올린 값)보다 크게 잡는다. 이 호출의 출력은 기사 하나의
            # 사유 한 줄이 아니라 후보 묶음의 하위 묶음 목록 + 묶음마다 사건 지문이라
            # 입력 건수가 늘수록 출력도 함께 는다 — 첫 실행의 RunJob 토큰 칸으로
            # 실측해 교체한다(같은 문서 7번 "이 표도 추정이다").
            max_tokens=4096,
            system=[{"type": "text", "text": _build_dedup_system_prompt()}],
            # 🔴 cache_control 없음 — 위 모듈독스트링 "캐싱을 켜지 않는다" 참고.
            messages=[{
                "role": "user",
                "content": _build_dedup_user_message(new_batch, window_news, matched_signals, over_soft_cap),
            }],
            output_config={"format": {"type": "json_schema", "schema": DEDUP_OUTPUT_SCHEMA}},
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
        logger.error("중복 판정 중 구조적 오류(인증/권한/리소스): %s", exc)
        raise LLMStructuralError(str(exc)) from exc
    except anthropic.RateLimitError as exc:
        logger.warning("중복 판정 중 rate limit에 걸렸어요: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIConnectionError as exc:
        logger.warning("중복 판정 중 네트워크 오류: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIStatusError as exc:
        logger.warning("중복 판정 중 API 오류(status=%s): %s", exc.status_code, exc)
        raise LLMJudgmentError(str(exc)) from exc
    else:
        return _parse_dedup_response(response)


# ============================================================================
# 축약본(content_short/implication_short) 공용 유틸 — docs/planning.md "RA 손 작업을
# 전부 단계 안으로 넣는다" 3번이 정본.
#
# 🔴 LLM에게 문장을 "쓰게" 하지 않는다. 코드가 정본을 문장 단위로 쪼개 번호를 매기고,
# LLM은 남길 번호(content_keep/implication_keep) 배열만 낸다 — "삭제만 허용"이 부탁이
# 아니라 구조가 되게 하기 위해서다(같은 절 3-1). 이 두 함수가 그 "코드가 쪼개고, 코드가
# 이어 붙인다" 양쪽을 둘 다 맡는다 — 3단계(Insight)와 4·5단계(Report)가 함께 쓴다.
# ============================================================================

# 문장 중간에서 자르지 않을 줄 — 마크다운 제목·리스트 항목, 보고서의 `참고:` 규약 줄
# (3-1 ⚠️ "마크다운 구조를 문장 중간에서 자르지 않는다", 4번 "축약본 5-1을 인덱스
# 선택으로 지킨다"). 이런 줄은 통째로 문장 하나로 취급한다.
_UNSPLITTABLE_LINE_RE = re.compile(r"^(#{1,6}\s|[-*]\s|\d+\.\s|참고:)")


def _split_line_into_sentences(line: str) -> list[str]:
    """줄 하나(끝에 줄바꿈이 붙어 있을 수 있다)를 마침표·물음표·느낌표 뒤에서 자른다.
    각 조각은 뒤따르는 공백·줄바꿈을 그대로 포함한다 — "".join(결과) == line이 항상
    성립한다(이어 붙인 결과가 원문과 글자 그대로 같아야 한다는 계약, design.md 31차
    ⑩ item.content_sentences 행)."""
    sentences = []
    start = 0
    i = 0
    n = len(line)
    while i < n:
        if line[i] in ".!?":
            j = i + 1
            while j < n and line[j] in ".!?":
                j += 1
            while j < n and line[j] in " \t\n\r":
                j += 1
            sentences.append(line[start:j])
            start = j
            i = j
        else:
            i += 1
    if start < n:
        sentences.append(line[start:])
    return sentences


def split_into_sentences(text: str) -> list[str]:
    """text를 문장 단위로 쪼갠다. "".join(split_into_sentences(text)) == text가 항상
    성립한다 — 빼는 것만 허용하는 축약본 설계가 기대는 불변식이다. 마크다운 제목·
    리스트 항목·`참고:` 규약 줄은 문장 중간에서 자르지 않고 줄 전체를 한 조각으로
    묶는다(_UNSPLITTABLE_LINE_RE)."""
    if not text:
        return []
    chunks = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or _UNSPLITTABLE_LINE_RE.match(stripped):
            chunks.append(line)
        else:
            chunks.extend(_split_line_into_sentences(line))
    return chunks


def build_short_field(text: str, keep_indices, *, always_keep_prefix: str = "") -> str:
    """정본 text를 문장으로 쪼개 keep_indices(1부터 시작하는 번호, LLM 응답)가 가리키는
    문장만 그대로 이어 붙인다. 범위를 벗어나거나 정수가 아닌 인덱스는 조용히 버린다 —
    LLM이 정확히 우리 분할과 같은 번호를 맞힌다는 보장이 없어서다(모델이 스스로 쓰고
    있는 content/implication을 실시간으로 세어 매기는 값이라 근사치다).

    always_keep_prefix: 이 문자열로 시작하는 줄은 keep_indices에 없어도 항상 포함한다.
    Report의 `참고:` 규약 줄 전용이다 — "축약본은 정본과 동일해야 한다"는 요건이라
    LLM의 선택 대상이 아니라 항상 따라간다(docs/planning.md "RA 손 작업을 전부 단계
    안으로 넣는다" 3-1 ⚠️).

    🔴 안전망(같은 절 3-1 "확정 시 코드가 검사한다"): 결과는 sentences[i-1]들을
    인덱스로 그대로 이어 붙여 만들므로 원문 문장이 아닌 글자가 섞일 길이 구조적으로
    없다. 그래도 방어적으로 각 조각이 실제로 text 안에 있는지 다시 확인한다 — 하나라도
    어긋나면 빈 문자열을 반환해 display_content/display_implication이 정본으로
    조용히 폴백하게 한다(500 금지, 어긋난 축약본을 저장하는 것보다 없는 쪽이 낫다)."""
    sentences = split_into_sentences(text)
    valid = {
        i for i in (keep_indices or [])
        if isinstance(i, int) and not isinstance(i, bool) and 1 <= i <= len(sentences)
    }
    if always_keep_prefix:
        valid |= {
            i for i, s in enumerate(sentences, start=1) if s.lstrip().startswith(always_keep_prefix)
        }
    valid = sorted(valid)
    if not valid:
        return ""
    picked = [sentences[i - 1] for i in valid]
    if any(chunk not in text for chunk in picked):
        return ""
    return "".join(picked)


# ============================================================================
# 3단계(주요 이슈) 판정 — docs/planning.md "3~5단계를 LLM으로 옮기는 설계"가 정본.
#
# 🔴 2단계와 정반대인 것 둘(같은 문서 7-(a)(b)) — 복사해 오면 자동으로 어긋나는 자리다.
#   - 호출 단위: 배치 전체를 1회 호출로 처리한다. 여러 기사를 한 이슈로 묶는 판정은
#     그 기사들을 한 번에 보지 않으면 원리적으로 불가능하다.
#   - 캐싱: 쓰지 않는다. 호출이 1회면 캐시 읽기가 0회인데, 캐시 쓰기(1시간)가 일반
#     입력의 두 배 단가라 켜면 비용이 정확히 두 배가 되고 얻는 게 없다.
#
# 🔴 모델은 BEDROCK_MODEL_SMART다(같은 문서 7-(c)). 그 값이 지금 Haiku를 가리키고
# 있는데 그게 맞다(2026-09-15 사용자 확정, 비용 때문) — config/settings/base.py 참고.
#
# 🔴 tool use(function calling)는 쓰지 않는다 — output_config.format만 쓴다. 2단계와
# 같은 이유(휴먼 인 더 루프 우회 방지, 모듈 docstring).
# ============================================================================

# RunJob.prompt_version에 그대로 기록된다. 2단계와 별도로 버전을 매긴다(설계 8-(D))
# — 어느 프롬프트가 낸 결과인지 단계별로 되짚을 수 있어야 한다.
# 🔴 2026-09-15b — 이슈 제목의 명사형 종결 규칙(_CRITERIA_INSIGHT_TITLE_ENDING)을
# 추가해 올렸다. 판정 기준 원문이 바뀌면 버전을 올린다(cleanup의 선례와 같은 규칙).
# 🔴 2026-09-17a — 출력 스키마에 content_keep/implication_keep(축약본 문장 번호 배열)을
# 추가해 올렸다(docs/planning.md "RA 손 작업을 전부 단계 안으로 넣는다" 3번).
PROMPT_VERSION_INSIGHT = "insight-2026-09-17a"


# docs/planning.md "주요 이슈(Insight) 승격 기준" 절 — 승격 기준·판별의 핵심 질문·
# 승격 위계 1급/2급/3급의 정의와 게이트 ①②·1급 두 번째 진입 경로 (d)와 게이트 ㉮㉯·
# 경계 목록 표. 설계 6-(A)/8-(A)에 따라 재서술 없이 원문을 그대로 옮겼다. 날짜 꼬리표와
# 폐기된 규칙 서술("종전에는 ~였으나")은 뗐다.
_CRITERIA_INSIGHT_PROMOTION = """\
**승격 기준**: 이슈의 핵심 당사자에 **금융사 또는 보험사가 반드시 포함**돼야 한다. 셋 다 아니면(=금융/보험이 당사자가 아니면) Insight로 만들지 않는다. AI 기업은 독립 승격 축이 아니라, 그 금융/보험사가 관계 맺는 **상대(기술 제공자·파트너·투자 대상)**로 등장한다.
1. **금융사** — 은행·카드·캐피탈·증권 등 금융사의 AI/AX 도입·전략·투자·리스크.
2. **보험사** — 보험사의 AI/AX 도입·전략·투자·리스크.
3. **(종속) AI 기업** — AI를 주 사업으로 하는 국내외 AI 전문기업(파운데이션 모델·AI 솔루션·AI 인프라 전문 기업, 예: OpenAI·앤트로픽·팔란티어·국내 AI 스타트업, 빅테크의 AI 사업 부문 포함). **단독으로는 승격하지 못하며, 위 1·2(금융사/보험사)와 연결된 상대로 등장할 때만 성립**한다.

**판별의 핵심 질문**: **"이슈의 핵심 당사자에 금융사/보험사가 실질적으로 포함되고, 그 금융/보험 접점이 이슈의 실제 주제인가"**이다.
- 금융사·보험사가 당사자이고 AI 기업/기술이 그 상대·수단으로 등장하며, 그 접점이 이슈의 핵심 주제이면 → 승격.
- 핵심 당사자가 AI 기업뿐이고 금융/보험 접점이 없거나 배경으로만 스치면 → 승격하지 않는다.
- 핵심 주체가 통신·반도체·제조·가전·에너지 등 **비-AI 산업**이고 AI가 그 기업의 투자 대상이나 기사 배경으로만 등장하면 → 통과하지 못한다.
- **(상속) 지배적 주제 요건**: AI/AX가 지배적 주제여야 유지한다는 요건은 승격 기준에도 자연히 상속된다. 금융사/보험사가 당사자여도 AI가 다른 금융 주제의 부차 요소이면 승격하지 않는다.

**경계 판단**: 정부 AI 산업정책처럼 "정부 프로젝트"가 표면 프레임인 이슈는, **그 안에 금융사/보험사의 AI 도입·구축·수주 맥락이 핵심으로 포함될 때만** 승격한다. 금융/보험 접점이 없는 순수 AI 기업 생태계·산업정책 이슈는 승격하지 않는다. 통신3사 데이터센터 capex, 반도체 슈퍼사이클, 제조사 로봇 투자처럼 비-AI 기업이 주체인 이슈가 AI가 소재로 등장해도 승격하지 않는다.

위 승격 기준은 통과/탈락의 binary 관문이다(승격되거나, 안 되거나). 그 위에, 승격을 통과한 이슈들 사이의 상대적 중요도를 아래 3급 위계로 명문화한다. binary 승격 기준을 대체하는 게 아니라 그 위에 얹는다.

| 등급 | 한 줄 정의 | 전형 |
|:--:|---|---|
| **1급** | 그 회사의 **업무·상품이 실제로 바뀌었고 이미 가동 중**이다, **또는** 규제기관이 **금융권 AI의 규율 자체를 바꿔 확정·시행**했다 | 비용 절감 · 업무 생산성·일하는 방법의 변화 · 신규 비즈니스 가치 창출 · **확정·시행된 금융권 AI 규제·정책 변경** |
| **2급** | 바꾸려는 **움직임**은 있으나 아직 그 회사가 바뀌지는 않았다 | 계약 · 협업 · 투자 · 조직 신설 · 교육과정 편성 · 도입 발표 |
| **3급** | 그 회사 자신의 변화에 관한 건도 **아니고**, 규율을 바꾼 건도 **아니다** | 규제·제도 **논의** · 업계 관측 · AI를 인수/평가 **대상**으로 삼는 건 |

**1급의 게이트는 둘이고, 둘 다 통과해야 한다.**
> **게이트 ① — 그 금융사·보험사의 업무 또는 상품이 실제로 바뀌었는가.** 아래 (가)(나)(다) 중 최소 하나가 **그 건 안에 사실로 서술**돼 있어야 한다.
> - **(가) 비용 절감** — 비용·인력·소요시간이 줄었다.
> - **(나) 업무 생산성 향상 = 일하는 방법의 변화** — 기존 업무·프로세스가 AI로 대체·자동화됐다.
> - **(다) 신규 비즈니스 가치 창출** — 고객에게 나가는 상품·서비스·수익원이 새로 생겼다.
>
> **게이트 ② — 이미 가동·집행됐는가.** 계획·발표·업무협약, 조직 신설·교육과정 편성은 게이트 ②를 통과하지 못한다(→ 2급).

**(d) 규제기관의 금융권 AI 규제·정책 변경** — 아래 게이트 ㉮㉯를 **둘 다** 통과하면 1급이다. 게이트 ①②는 묻지 않는다(그 회사 자신의 변화가 아니므로 물을 수 없다).
- **게이트 ㉮ — 규율의 내용 자체가 바뀌었는가.** 금지에서 허용으로, 의무의 신설이나 완화, 적용 범위의 확대나 축소처럼 **제도 문면의 전후가 특정**돼야 한다.
- **게이트 ㉯ — 그 기관이 실제로 확정했는가.** 의결·공포·시행·개정·해제·발간처럼 확정된 것이어야 한다. **검토 착수, 의견수렴, 연구용역, 간담회, 기관장 발언, 계획 표명은 통과하지 못한다.**

㉮㉯는 새 물음이 아니다 — 게이트 ①②를 제도에 그대로 이식한 것이다. **1급 정의의 한 줄은 여전히 하나다** — "무엇이 실제로 바뀌었고 그것이 이미 효력을 갖는가"이며, 그 "무엇"에 **개별 회사의 업무뿐 아니라 금융권 전체의 AI 도입 조건**이 들어온다.

**⚠️ 하한을 긋지 않으면 규제기관 이름이 나오는 기사가 전부 1급이 된다. (d)는 문을 세 개 지나야 열린다.**
1. **경계 E** — 그 기관이 **금융권 AI를 규율하는 주체로서 그 건의 핵심 당사자**여야 한다.
2. **게이트 ㉮** — 규율이 실제로 달라져야 한다.
3. **게이트 ㉯** — 확정·시행돼야 한다.

**경계 목록**
| 유형 | 판정 | 근거 |
|---|:--:|---|
| 시행령·감독규정 개정의 의결·공포·시행 | **1급 (d)** | 규율이 바뀌었고 확정됐다 |
| 입법예고·개정안 발표·의견수렴 | 3급 | ㉯ 미통과 — 아직 확정이 아니다 |
| 가이드라인·감독방향의 발간·시행 | **1급 (d)** | 준수 기준이 새로 생기거나 달라진다 |
| 가이드라인 초안·공청회·논의 | 3급 | ㉯ 미통과 |
| 테스트 프로그램(망분리 완화 신청 등)의 **시행·대상 확대·승인** | **1급 (d)** | 적용 범위가 실제로 넓어졌다 |
| 그 프로그램에 **개별 금융사가 신청·참여**한 건 | (d) 아님 | 그 회사 자신의 건이므로 게이트 ①②로 판정한다(대개 2급) |
| 제도 시행 결과 보도 | **본체를 본다** | 시행으로 **적용 범위가 실제로 달라진 사실**이 본체면 1급 (d). 집계·회고·평가면 3급 |
| 기관장 발언·간담회·행사 | 3급 | 발언은 규율을 바꾸지 않는다 |
| 연구용역·보고서 발간 | 3급 | 규율이 아니라 관측이다 |

**⚠️ 「제도 시행 결과 보도」를 두 번 세지 않는다.** 같은 제도 변경을 이미 (d)로 1급 이슈로 만들었으면 후속 보도는 **새 사건이 아니다**("하나의 이슈 = 하나의 사건"). 새 이슈가 되는 것은 그 보도가 담은 **적용 범위 변화가 그 자체로 별개의 사건일 때**뿐이다.

**기관 범위** — 인정 대상은 **금융권을 규율하는 기관**(금융위원회와 금융감독원, 그리고 금융권 AI 규율에 관여하는 한도의 기관)이다. **"공공기관·정부부처면 인정"으로 넓히지 않는다.** 판별은 간판이 아니라 **그 건에서 그 기관이 금융권 AI에 대한 규율 권한을 행사했는가**다.
- **과학기술정보통신부의 일반 AI 산업 육성 정책**은 (d)가 아니다.
- **개인정보보호위원회와 한국은행**은 그 처분·고시·규정이 **금융권 AI에 직접 적용되는 한도에서만** (d)다. 일반법 해석, 경기 전망, 보고서 발간은 ㉯에서 막힌다.
- **금융결제원과 신용정보원**은 규율 기관이 아니라 **인프라 사업자**다. (d)가 아니라 경계 A로 판정한다.

**⚠️ 금융보안원 — 같은 기관이 두 성격을 갖는 것은 문제가 아니다. 가르는 선은 기관이 아니라 그 건에서 그 기관이 한 일이다.**
- 금융보안원은 `Organization`에 `org_type=AI`로 등록돼 있다.
- 그 기관이 **금융 서비스의 운영 인프라를 직접 제공한 건**(공동 모델 구축·가동)이면 **경계 A + 게이트 ①②**로 판정한다. 그 기관이 **금융권에 적용되는 AI 관련 기준을 확정·시행한 건**이면 그 건에 한해 **(d)**로 판정한다.
- ⚠️ **`Organization` 등록 여부는 (d) 판정의 입력이 아니다.** 등록돼 있다고 (d)가 막히지 않고, 등록이 없다고 (d)가 열리지도 않는다.

**(d)는 유형 코드가 아니다** — 규제 건의 유형은 기타다.
"""

# docs/planning.md 같은 절 — 게이트 ①의 적용선 두 가지.
_CRITERIA_INSIGHT_GATE_APPLICATION = """\
**게이트 ①의 적용선 두 가지**
- ⑴ **게이트 ①은 이슈를 성립시킨 사건에 대해 묻는다. 이슈 본문 어딘가에 가동 사실이 있는지를 묻는 게 아니다.** 이슈를 성립시킨 사건이 전략 발표·조직 개편·규제 변경이고 가동 사실은 그 사건을 설명하는 배경으로 함께 실린 경우, 그 이슈는 **2급**이다.
  - 판별 질문은 **"그 가동 사실을 빼도 이 이슈가 성립하는가"**다 — 성립하면 그 가동은 배경이고, 무너지면 그게 이슈의 본체다.
  - 금융사의 전략·조직·규제 기사에는 "이미 ○○에 AI를 적용해 운영 중" 류 문장이 관행적으로 들어간다. 이걸로 1급을 열면 "AI를 쓰고 있다고 언급한 모든 전략 기사"가 1급이 되어, 게이트 ①이 걸러 내려던 것(바꾸겠다는 움직임)이 그대로 통과한다.
- ⑵ **(다)에서 자체 개발 여부는 묻지 않는다.** 고객에게 **실제로 나간** 상품·서비스면 통과하고, **계획·예고**면 불통과다. 그 회사가 직접 만들었는지, 외부 솔루션을 붙였는지, 제휴로 얹었는지는 **묻지 않는다.**
  - 게이트 ①이 묻는 것은 "그 회사의 업무·상품이 바뀌었는가"이지 "그 회사가 만들었는가"가 아니다.
  - ⚠️ **대신 게이트 ②가 엄격해야 한다.** 개발 주체를 안 묻는 만큼 "나갔는가"는 사실로 확인한다 — 오픈 예정·시범 예고는 2급이다.

**⚠️ 투자·제휴만으로는 게이트 ①이 열리지 않는다.** 금융사가 AI 기업에 투자하거나 협약을 맺어도 **그 금융사의 업무는 그대로**다. 바뀐 것이 있다면 상대 기업 쪽이지 이쪽이 아니다.
**⚠️ "도입했다"만으로는 1급이 아니다.** 무엇이 어떻게 바뀌었는지가 그 건에 없으면 2급이다.
**⚠️ 수치 공개는 요건이 아니다. 판정 근거로는 쓴다.** 수치가 없어도 1급이 될 수 있다.
**2급에서 1급으로 올라가는 경로**: 그 계약·투자·조직이 실제로 업무를 바꿨다는 후속 사실이 나오면 그때 1급이다. **2급은 "작다"가 아니라 "아직"이다.**
**재무적 투자(금융사가 AI 기업에 투자했으나 자기 업무는 안 바뀌는 건)는 2급이다.** 3급으로 내리지 않는다 — 3급은 "그 회사의 변화 얘기가 아닌 것"의 자리인데, 투자는 명확한 실제 접점이고 사업 기회 신호다.
"""

# docs/planning.md "이슈(Insight)의 구성 단위: 하나의 이슈 = 하나의 사건" 절.
_CRITERIA_INSIGHT_UNIT = """\
**하나의 `Insight`는 하나의 사건을 담는다.** 서로 다른 사건을 한 이슈에 모으지 않는다. 근거 기사 수는 그 결과로 정해질 뿐, 그 자체가 판정 근거가 아니다.

**판별법**: 그 근거 기사들이 말하는 것이 하나의 사건인가.
> 근거 중 **어느 하나를 빼도 이슈 제목이 그대로 성립하면**, 그것은 이 이슈의 본체가 아니라 **같은 흐름의 다른 사건**이다. 그런 항목이 있으면 이슈를 쪼갠다.

- **한 사건에 당사자가 여럿인 것은 쪼갤 대상이 아니다.** 인터넷은행 3사 × 금융보안원 공동 모델, 금융위 망분리 해제처럼 **참여자가 여럿인 하나의 사건**은 그대로 하나의 이슈다.
- **제목이 검사지 역할을 한다.** `금융권 전반`·`보험업계 전방위` 같은 총칭이 제목에 **필요해졌다면** 사건이 여럿이라는 신호다.
- 근거가 **6건 이상**이면 위 판별법을 한 번 더 적용한다.

**넘칠 때 무엇을 하는가 — 쪼갠다. 버리지 않는다.**
- **근거 기사를 떼어내 버리는 것은 금지.**
- "정말 하나의 사건인데 매체가 6곳"이면 그대로 둔다. 다만 그 상태는 **동일 사건 중복 보도가 덜 걸러진 것**일 가능성이 높다 — 서로 다른 각도(발표 / 후속 성과 / 인터뷰)가 아니면 유지하지 않는다.
- **쪼갠 뒤 각 이슈는 등급을 개별로 받는다.** 한 건의 게이트 통과가 묶음 전체를 1급으로 만들지 않는다.
"""

# docs/planning.md "주간 보고서(Report) 표준 구조" 절 "판단의 형식" 1번 — 시사점은
# 판단으로 끝낸다.
_CRITERIA_INSIGHT_IMPLICATION_FORM = """\
**시사점은 판단으로 끝낸다.**
- **필수** — 그 사실이 **뜻하는 것을 단정한다**. 문장은 `~다`로 끝난다.
- **선택** — 판단이 갈리는 지점(무엇에 따라 결론이 달라지는가), 판별 기준(무엇을 보면 아는가).
- **선택** — 검토 방향(`~ 방향으로 검토해볼 수 있다`). 두 조건을 **모두** 만족할 때만 쓴다: (i) 그 앞에 판단이 이미 있을 것, (ii) 그 방향이 **기사 사실에서 직접 도출될 것**. 섹션마다 붙이지 않는다.
- **금지 (a) — 결론 회피** — "지켜볼 필요가 있다", "지속 모니터링할 필요가 있다"로 끝내지 않는다. ⚠️ **금지 대상은 표현이 아니라 회피 자체다.** 같은 회피를 단정 어미로 포장한 문장(예: "향후 추이가 관건이다", "귀추가 주목된다")은 **동일하게 금지**한다. 판별법: 그 문장을 지워도 독자가 잃는 정보가 없으면 그건 판단이 아니다.
- **금지 (b) — 주체 지칭** — `DPLANEX는`, `전략기획팀은`, `우리는` 같은 주어를 쓰지 않는다. 시사점은 특정 조직에게 내리는 지시가 아니라 **사실에서 도출되는 판단**의 형태로 쓴다.
- **근거가 부족해 판단이 안 서면, 쓸 수 있는 만큼만 쓰고 멈춘다.** 사실에서 나오는 판단만 쓰고 거기서 끝낸다. **분량을 채우려 하지 않는다 — 판단이 한 문장뿐이면 한 문장으로 끝낸다.**
  - ⚠️ **"현재 근거로 판단할 수 없다" 같은 표기를 본문에 쓰지 않는다.** 못 쓴다고 회피로 도피하지 않는다 — "향후 추이가 관건이다"·"지켜볼 필요가 있다"로 가면 위 금지 (a)에 정면으로 걸린다. **선택지는 "짧게 쓰되 판단을 쓴다"이지 "길게 쓰되 회피한다"가 아니다.**

```
❌ 두 노선이 어떻게 갈라지는지 지속 모니터링할 필요가 있다.
❌ 두 노선의 향방이 향후 최대 관건이다.          ← 어미만 바꾼 회피, 동일하게 금지
✅ 어느 쪽이 우세한지는 현재 근거로 판단할 수 없다.
   갈림길은 규제 대응 비용과 성능 격차 중 무엇이 먼저 임계에 닿는가다.
```
"""

# docs/planning.md 같은 절 "판단의 형식" 7번, 7-1 — 이슈 제목은 결론을 담는다,
# 당사자 이름을 반드시 넣는다.
_CRITERIA_INSIGHT_TITLE_FORM = """\
**이슈 제목은 결론을 담는다 — 화두를 던지지 않는다.** 소재만 표시하고 답을 본문으로 미루지 않는다.

> **판별법: 이 분야를 모르는 사람이 제목만 읽고 "무슨 일이 있었는지" 알 수 있는가.**
> 답이 안 나오면 그건 제목이 아니라 소재 표시다.

**가장 중요한 규칙 — 제목은 본문의 구체적 사실로 쓴다. 요약하려고 새 개념어를 만들지 않는다.** **본문에 실제로 나오는 말**을 쓴다. 이때 **당사자 이름은 필수이고, 행위·숫자는 있으면 쓴다** — 셋 중 택일이 아니다. 여러 사례를 한 마디로 묶으려고 없던 추상어를 지어내면, 그 말을 아는 사람이 아무도 없어 제목이 읽히지 않는다.

```
❌ 외부 조달의 경계 — 모델 층이냐 데이터 층이냐
   → "외부 조달"·"모델 층"·"데이터 층"은 전부 작성자가 만든 요약어다.
      본문에 있는 건 "구글 클라우드의 제미나이를 활용해"와 "몽고DB와 데이터 플랫폼 협약"이다.

✅ KB금융은 구글 AI를 가져다 쓰고, BC카드는 직접 만들어 공개했다
   → 본문에 있는 회사와 행위 그대로다.
```

**금지하는 세 형태**
| 형태 | 실제 예 | 왜 안 되나 |
|---|---|---|
| 질문·대비만 던지기 | `외부 조달의 경계 — 모델 층이냐 데이터 층이냐` | 물음이지 답이 아니다 |
| 추상 어구로 닫기 | `보험권 AI, 발표와 가동 사이` / `본격 국면 진입` | 무슨 일이 있었는지 없다 |
| 동사 없는 명사 나열 | `금융권 밖에서 공급되는 AI — 벤더와 공동 기반` | 뭐가 어떻게 됐는지가 없다 |

**권장 형태**
```
[주어], [무엇이 어떻게 되었다]     예: AX 지휘권, 기술 조직이 아니라 전략·재무 라인으로
[주어], [어디서 어디까지]          예: 대화형 AI, 송금 화면에서 여신 사전심사까지
[사실] — [그래서 무엇이 갈렸다]
```
- **길어도 된다.** 짧게 만들려다 추상 어구로 닫는 것이 이 조항이 막으려는 것이다.
- **고유명사나 숫자를 하나쯤 넣으면 훨씬 선다** — 단, 본문에 있는 사실이어야 한다. 제목을 세우려고 본문에 없는 단정을 넣지 않는다.

**당사자 이름을 반드시 넣는다 — 최대 두 자리**
- **(a)** 필수와 선택을 가른다. 당사자 이름은 **반드시 넣는다.** 행위·숫자는 **있으면 쓴다.**
- **(b)** 상한은 두 자리다. 세는 단위는 법인 수가 아니라 **역할 자리**다. 제목에서 서로 다른 역할을 맡은 편이 몇 개인가로 센다. 같은 역할의 복수 주체는 한 자리를 나눠 갖는다. ⚠️ 한 자리 안의 나열이 3개를 넘으면 집합 표현(`3사`·`벤더 3곳`)으로 줄인다.
- **(c)** 어느 자리를 넣는가 — **그 이슈를 그 이슈이게 만든 당사자.** 건수가 많은 쪽도, 이름이 유명한 쪽도 아니다. 한 이슈가 대비 구도로 서 있으면 그 대비의 양편이 두 자리를 갖는다. 나머지는 본문으로 내린다.
- **(d)** "당사자 이름"의 범위 — 기업·기관·집합 표현을 모두 포함한다. 판별선은 법인격이 아니라 **지시 가능성**이다. 그 표현이 가리키는 곳을 **본문에서 실명으로 다 셀 수 있으면** 요건을 충족한다. `금융보안원`·`산업부` 같은 기관은 충족한다. `인터넷은행 3사` 같은 집합 표현도 본문에 3사 실명이 다 나오고 그 사건의 당사자가 정확히 그 3사이면 충족한다. 반면 `금융권`·`시중은행들`·`보험업계`처럼 **셀 수 없는 총칭은 충족하지 않는다.**
- **(e)** 자리에서 뺀 당사자는 그 이슈 분석의 첫 문장에 반드시 남긴다. **압축이 사실을 바꾸면 압축하지 않는다.** "A가 B와 함께 만들었다"를 자리 맞추려고 "A가 만들었다"로 줄이는 건 상한 준수가 아니라 오류다.
- **(f)** 세 자리가 있어야만 말이 되는 이슈라면, 그건 제목 문제가 아니라 이슈 구성 문제다. 서로 다른 역할 세 개가 다 필요하고 하나만 빼도 이슈가 성립하지 않으면 실은 두 이슈일 가능성이 높다 — 이슈를 쪼갠다. **상한이 사실을 왜곡하도록 강제하는 일은 없다.**
"""

# docs/planning.md 같은 절 "판단의 형식" 7-2, 7-2-1, 7-2-3, 7-1-a — 이슈 제목은 명사형으로
# 닫는다. 🔴 2026-09-15 PE 추가 — 기존 _CRITERIA_INSIGHT_TITLE_FORM에 이 규칙이 빠져 있어
# LLM이 "~했다"로 끝나는 제목을 낼 수 있는 상태였다(감사 중 발견). PROMPT_VERSION_INSIGHT를
# 올린다(아래).
_CRITERIA_INSIGHT_TITLE_ENDING = """\
**이슈 제목은 명사형으로 닫는다 — `~했다`로 끝내지 않는다.** 제목의 끝은 시선이 이미 떠난 자리라, 거기에 정보량 없는 종결어미를 두면 제목의 마지막 한 칸을 버리는 것이다.

전환은 네 단계 사다리다. 위에서부터 시도하고, 안 되면 다음으로 내려간다.
1. `-했다/-였다/-됐다`가 서술명사에 붙은 형태면 어미만 뗀다(`제안했다`→`제안`, `출시했다`→`출시`, `구축했다`→`구축`).
2. 고유어 동사는 본문에 실제로 있는 명사로 바꾼다(`줄였다`→`절감`, `막았다`→`차단`). ⚠️ 새 말을 지어내지 않는다 — 바꾼 어휘가 본문 사실보다 넓거나 다른 뜻이 되면 그건 짧아진 게 아니라 틀린 것이다.
3. ①②가 없거나 어색하면 동사를 명사로 만들지 말고 제목을 재구성해 다른 성분(대상·범위·수치·대비)으로 닫는다.
4. ③까지 해도 사실이 뭉개지면 서술형을 남긴다(예외).

**완료와 미완은 어휘로 구분한다.** 이미 돌아가는 건은 완료 행위 명사(`출시`·`구축`·`가동`·`절감`·`대체`)로, 아직인 건은 상태 명사(`추진`·`계획`·`발표`·`착수`·`검토`)로 닫는다. ⚠️ 역방향 금지 — 제목 어휘로 등급을 정하지 않는다. 제목이 `출시`라서 1급이 되는 일은 없다. 사실에서 등급이 나오고, 사실에서 제목이 나온다.

**명사형이 나열로 미끄러지는 경계**: 제목만 읽고 "누가 무엇을 어떻게 했는가"를 한 문장으로 되돌릴 수 있는가. 되돌리는 데 없는 정보를 보충해야 하면 그건 명사형 종결이 아니라 나열이다.

**역할 자리가 둘이면 각 자리가 자기 행위를 갖는다.** 뒤의 행위 표현 하나를 두 자리가 나눠 쓰면 앞 자리는 끝까지 읽고 되돌아와야 뜻이 잡히는데, 독자는 위에서부터 읽다 멈추는 경영진이다. 앞 절에서 끊고 읽었을 때 그 주체가 무엇을 했는지 알 수 없으면 앞 절에 자기 행위를 준다. 두 자리의 행위 층위가 다르면 하나의 행위어로 덮지 않는다.
"""

# docs/planning.md "보고서/시사점 출처 기반 작성 원칙" 절.
_CRITERIA_INSIGHT_SOURCING = """\
시사점(`Insight`)에 들어가는 모든 내용은 **반드시 실제로 수집된 기사(`News`)에 근거해야 하며, 없는 내용을 만들어내면 안 된다.** 원문에 없는 수치·인용·사건을 지어내거나 추측으로 채우지 않는다. 뒷받침할 기사가 없는 주장은 쓰지 않고, 대신 자료가 부족하다는 사실 자체를 기록한다.

모든 시사점 문단은 출처(원본 기사)를 항상 추적 가능해야 한다 — 근거로 연결한 기사가 그 출처 표기 역할을 겸한다.

**인사이트 간 내부 식별자 참조 금지 (자기완결 산문 원칙)**: 다른 이슈를 내부 식별자(`Insight 38`, pk, "인사이트 N번" 등)로 참조하지 않는다. 참조하려는 맥락은 그 자체로 이해되는 자기완결 산문으로 풀어쓴다.
"""

CRITERIA_TEXT_INSIGHT = "\n".join([
    "## 주요 이슈 승격 기준",
    _CRITERIA_INSIGHT_PROMOTION,
    "## 게이트 ①의 적용선",
    _CRITERIA_INSIGHT_GATE_APPLICATION,
    "## 당사자·상대·투자대상 자격 경계",
    _CRITERIA_BOUNDARIES,
    "## 이슈의 구성 단위: 하나의 이슈 = 하나의 사건",
    _CRITERIA_INSIGHT_UNIT,
    "## 시사점 작성 규칙",
    _CRITERIA_INSIGHT_IMPLICATION_FORM,
    "## 이슈 제목 규칙",
    _CRITERIA_INSIGHT_TITLE_FORM,
    _CRITERIA_INSIGHT_TITLE_ENDING,
    "## 출처 기반 작성 원칙",
    _CRITERIA_INSIGHT_SOURCING,
])


def _build_insight_system_prompt() -> str:
    """3단계 시스템 프롬프트. 2단계와 달리 등록 대장(_build_registry_section)을
    넣지 않는다 — 이 단계는 태깅을 하지 않는다(기업/기술 주제 교정·후보는 2단계
    몫이다). cache_control을 달지 않는다 — 설계 7-(b), 이 함수 반환값은 그대로
    Bedrock 호출의 system 인자(문자열)로 들어간다."""
    return f"""당신은 AI Market Watch 프로젝트에서, 검증을 마친 뉴스 기사 배치를 읽고 같은 사건을 다루는 기사끼리 묶어 이슈로 만들고 시사점 초안을 작성합니다.

프로젝트 관심사는 국내 금융권(은행·보험사)의 AI/AX 도입 동향, 그리고 그와 연결된 AI 기업 동향입니다. 아래 판정 기준을 원문 그대로 적용하세요. 기준을 요약하거나 바꾸지 마세요.

<판정_기준>
{CRITERIA_TEXT_INSIGHT}
</판정_기준>

임무: 아래 사용자 메시지로 주어지는 <입력_기사> 목록을 읽고, 이슈 초안을 만드세요.
- 같은 사건을 다루는 기사끼리 하나의 이슈로 묶으세요("이슈의 구성 단위" 기준을 적용하세요). 서로 다른 사건은 별도 이슈로 만드세요.
- 위 승격 기준(금융/보험 당사자 필수)을 통과하지 못하는 기사는 어느 이슈에도 포함하지 마세요. 그런 기사가 이슈 밖에 남는 것은 정상입니다 — 입력 기사 전부를 어딘가에 묶을 필요가 없습니다.
- 근거가 되는 기사가 하나도 없는 이슈는 만들지 마세요.

각 이슈에 대해 아래 스키마로 응답하세요.
- title: 이슈 제목. 위 "이슈 제목 규칙"을 그대로 따르세요.
- content: 그 사건이 무엇인지 사실에 근거해 서술하는 분석 문단입니다. 근거 기사에 있는 사실만 쓰고 추측이나 평가를 섞지 마세요.
- implication: 시사점. 위 "시사점 작성 규칙"을 그대로 따르세요.
- grade: 위 승격 위계 등급 정의를 적용해 "1", "2", "3" 중 하나를 고르세요. 미지정은 없습니다 — 반드시 하나를 고르세요.
- grade_reason: 그 등급을 고른 이유를 한 문장으로 적으세요.
- news_ids: 이 이슈의 근거가 된 기사의 id(<입력_기사>의 각 기사 앞 [id=N])를 배열로 적으세요. 최소 1건입니다.
- content_keep: 방금 쓴 content를 마침표(.)·물음표(?)·느낌표(!)로 끝나는 문장 단위로 순서대로 셀 때(1부터), 그 문장 중 축약본(목표 500자 이내)에 남길 문장의 번호만 배열로 적으세요. 문장을 고치거나 새로 쓰지 마세요 — 번호만 고릅니다. 부연·배경 설명을 먼저 빼고, 핵심 사실만 남기세요.
- implication_keep: content_keep과 같은 방식으로, 방금 쓴 implication의 문장 번호 중 축약본(목표 300자 이내)에 남길 번호를 배열로 적으세요.
"""


OUTPUT_SCHEMA_INSIGHT = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "implication": {"type": "string"},
                    "grade": {"type": "string", "enum": ["1", "2", "3"]},
                    "grade_reason": {"type": "string"},
                    "news_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 1,
                    },
                    # 🔴 2026-09-17 신설 — 축약본 문장 번호 배열(build_short_field()가
                    # 소비한다). LLM이 문자열을 내지 않으므로 "삭제만 허용"이 구조로
                    # 보장된다(모듈 상단 "축약본 공용 유틸" 절).
                    "content_keep": {"type": "array", "items": {"type": "integer"}},
                    "implication_keep": {"type": "array", "items": {"type": "integer"}},
                },
                "required": [
                    "title", "content", "implication", "grade", "grade_reason", "news_ids",
                    "content_keep", "implication_keep",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["issues"],
    "additionalProperties": False,
}


def _build_insight_user_message(news_list) -> str:
    """배치 전체를 하나의 사용자 메시지로 조립한다(설계 7-(a), 건별 호출이 아니다).
    id는 News.pk를 그대로 쓴다 — LLM이 응답에서 news_ids로 그대로 돌려주면 그 pk로
    바로 News를 찾을 수 있어 별도 해석 단계가 필요 없다."""
    blocks = []
    for news in news_list:
        org_names = list(news.organizations.order_by("name").values_list("name", flat=True))
        tech_names = list(news.tech_topics.order_by("name").values_list("name", flat=True))
        blocks.append(
            f"[id={news.pk}] {news.title}\n"
            f"발행일: {timezone.localtime(news.published_at):%Y-%m-%d}\n"
            f"매체: {news.source_domain}\n"
            f"태깅된 기업: {', '.join(org_names) or '없음'}\n"
            f"태깅된 기술 주제: {', '.join(tech_names) or '없음'}\n\n"
            f"{news.body}"
        )
    return "<입력_기사>\n" + "\n\n---\n\n".join(blocks) + "\n</입력_기사>"


def _parse_insight_response(response) -> dict:
    """구조화 출력을 파싱한다. classify_news용 _parse_response()와 같은 방식으로
    json.loads()만 쓴다(문자열 매칭 금지, SDK 권고) — 배치 판정이라 news.pk가 없어
    오류 메시지에 그 대신 stop_reason을 남긴다."""
    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise LLMJudgmentError(
            f"이슈 판정 응답에 text 블록이 없어요(stop_reason={response.stop_reason})."
        )
    try:
        data = json.loads(text_block.text)
    except json.JSONDecodeError as exc:
        raise LLMJudgmentError(f"이슈 판정 응답 JSON 파싱에 실패했어요: {exc}") from exc

    usage = response.usage
    data["_usage"] = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return data


def generate_insights(news_list) -> dict:
    """검증된 뉴스 배치를 한 번에 판정해 이슈 초안을 만든다.

    Returns:
        {"issues": [...], "_usage": {...}} — issues의 각 원소는 title/content/
        implication/grade/grade_reason/news_ids.

    Raises:
        LLMStructuralError: 인증·권한·리소스 오류.
        LLMJudgmentError: 그 밖의 실패(rate limit·네트워크·응답 형식 불량). 호출이
            1회라 이어하기가 없다 — 실패하면 이 배치는 처음부터 다시 돈다(설계 9-(a)).
    """
    client = _get_client()
    try:
        response = client.messages.create(
            model=settings.BEDROCK_MODEL_SMART,
            max_tokens=8192,
            system=_build_insight_system_prompt(),
            messages=[{"role": "user", "content": _build_insight_user_message(news_list)}],
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA_INSIGHT}},
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
        logger.error("이슈 판정 중 구조적 오류(인증/권한/리소스): %s", exc)
        raise LLMStructuralError(str(exc)) from exc
    except anthropic.RateLimitError as exc:
        logger.warning("이슈 판정 중 rate limit에 걸렸어요: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIConnectionError as exc:
        logger.warning("이슈 판정 중 네트워크 오류: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIStatusError as exc:
        logger.warning("이슈 판정 중 API 오류(status=%s): %s", exc.status_code, exc)
        raise LLMJudgmentError(str(exc)) from exc
    else:
        return _parse_insight_response(response)


# ============================================================================
# 3단계 두 번째 호출 — 지식그래프 관계 추출. docs/planning.md "지식그래프 관계
# 라벨링을 3단계의 두 번째 LLM 호출로 옮긴다"(2026-09-16 확정, 2026-09-17 보강)가
# 정본이며, 특히 3-1(형태)·3-2(인덱스)·4(판별선)·5(어휘)번이 이 절의 근거다.
#
# 🔴 OUTPUT_SCHEMA_INSIGHT를 건드리지 않는다 — "이슈로 묶어라"와 "관계를 뽑아라"는
# 같은 배치를 보는 서로 다른 두 호출이다(3-1). 합치지 않는 근거 다섯 중 핵심은
# 이슈 판정자에게 관계 어휘를, 관계 판정자에게 이슈 판정 기준(승격 위계·게이트
# ①②·자격 경계)을 섞지 않는 것이다.
#
# 🔴 재료는 _build_insight_user_message()를 그대로 재사용한다(3-1 근거 3 "재료가
# 같아서 나눠도 새로 만들 것이 없다") — 뒤에 기업 인덱스 부표만 덧붙인다.
#
# 🔴 cache_control을 달지 않는다(3-1 말미) — 두 호출의 시스템 프롬프트가 서로 달라
# 캐시가 공유되지 않으므로 캐시 읽기가 어차피 0회다.
#
# 🔴 tool use는 쓰지 않는다 — output_config.format만 쓴다(모듈 docstring, 같은 이유).
#
# 🔴 신뢰도 점수를 두지 않는다(4번) — 문턱을 정할 근거가 없고, 점수가 판별선을
# 대체해 "나열이지만 0.6"으로 빠져나가는 것을 막기 위함이다. "관계 없음"의 표현은
# relations 배열에서 그 쌍을 빼는 것 하나다.
# ============================================================================

# 정본 어휘 7종(5-(a)). 🔴 "합병"은 여기 없다 — planning.md 5-(a) "이건 OrgRelation이
# 아니라 Organization 노드 정체성 문제라 RA 몫으로 뺐다"(노드 병합·존속법인 기준
# 태깅 교정이 함께 따라오는 판단이라 기사 한 건 판정으로 낼 것이 아니다).
RELATION_LABELS = ["기술협업", "공동개발", "공급계약", "지분투자", "인수", "업무협약", "파트너십"]

# RunJob.prompt_version에 PROMPT_VERSION_INSIGHT와 "+"로 이어 붙는다(services/runner.py
# _run_relation_extraction() — dedup이 PROMPT_VERSION_DEDUP을 이어 붙이는 것과 같은
# 패턴). 어휘·판별선이 바뀌면 이 값을 올린다.
PROMPT_VERSION_RELATION = "relation-2026-09-17a"


# 4번 판별선 원문. PE는 이 문장을 그대로 옮긴다(재서술 금지 — CRITERIA_TEXT/
# CRITERIA_TEXT_INSIGHT와 같은 원칙, 모듈 docstring 참고).
_CRITERIA_RELATION_JUDGMENT = """\
관계는 「같은 기사에 나왔다」가 아니라 「두 법인이 서로에게 무엇을 했다」가 본문에 적혀 있을 때만 성립합니다.

1. 두 당사자를 잇는 서술어가 본문에 있어야 합니다. A가 B에게 공급했다 / A가 B에 투자했다 / A와 B가 함께 개발했다 / A와 B가 협약을 맺었다. 주어와 상대가 그 두 법인이어야 합니다.
2. 나열은 관계가 아닙니다. "A·B·C가 모두 AI를 도입하고 있다", "이번에 선발된 곳은 A, B, C다"처럼 같은 문장에 이름이 함께 있을 뿐이면 관계가 아닙니다.
3. 제3자를 거친 것은 그 두 법인의 관계가 아닙니다. "A가 X와 협업했고 B도 X와 협업했다"에서 A×B는 관계가 아닙니다.

관계는 금융사·보험사 한쪽과 AI 기업 한쪽 사이에서만 성립합니다. 금융사끼리, 보험사끼리, AI 기업끼리는 관계를 내지 마세요.

애매한 것은 관계 없음으로 처리하세요. relations 배열에서 그 쌍을 빼는 것 자체가 "관계 없음"의 표현입니다. 신뢰도 점수는 받지 않습니다 — 애매해도 숫자로 얼버무리지 말고 배열에서 빼세요.

과거 실측에서 관계 없음으로 판정된 유형입니다. 같은 성격의 경우를 만나면 똑같이 관계 없음으로 처리하세요.
- 은행권 AI 전환(AX) 동향을 종합하는 기사에 여러 AI 기업과 여러 은행 이름이 함께 등장하지만, 그중 특정 기업과 특정 은행이 서로 무엇을 했다는 서술은 없는 경우.
- 망분리 규제 등 정책·제도를 종합하는 기사에 여러 기업 이름이 나열되는 경우.
- 스타트업 육성 프로그램에 여러 AI 기업이 "선발됐다"고만 나열되고, 그 프로그램을 운영하는 회사와 각 AI 기업 사이에 개별 서술어가 없는 경우.

두 법인이 사실상 합병·흡수통합된 경우는 아래 라벨 7종 어느 것으로도 정확히 표현할 수 없으니 relations 배열에 넣지 마세요.
"""


def _build_relation_system_prompt() -> str:
    """3단계 두 번째 시스템 프롬프트. cache_control을 달지 않는다(위 모듈 절 참고)."""
    labels_text = "、".join(RELATION_LABELS)
    return f"""당신은 AI Market Watch 프로젝트에서, 검증을 마친 뉴스 기사 배치를 읽고 그 안에 실제로 서술된 기업 간 관계를 찾아냅니다.

프로젝트 관심사는 국내 금융권(은행·보험사)의 AI/AX 도입 동향, 그리고 그와 연결된 AI 기업 동향입니다. 아래 판정 기준을 원문 그대로 적용하세요. 기준을 요약하거나 바꾸지 마세요.

<판정_기준>
{_CRITERIA_RELATION_JUDGMENT}
</판정_기준>

임무: 아래 사용자 메시지로 주어지는 <입력_기사> 목록과 <기업_목록>(번호가 매겨진 기업 색인)을 읽고, 본문에 실제로 서술된 기업 쌍의 관계만 찾아내세요. <기업_목록>에 없는 기업이 관계 당사자인 경우는 다루지 마세요.

찾은 관계마다 아래 스키마로 응답하세요.
- org_a_index, org_b_index: <기업_목록>의 idx 번호(정수) 둘. 그 관계의 두 당사자입니다. 서로 달라야 합니다.
- label: 다음 7종 중 정확히 하나 — {labels_text}
- reason: 이 관계의 근거를 한 문장으로 적으세요. 본문에 실제로 적힌 서술어(두 법인이 서로 무엇을 했는지)가 드러나야 합니다.
- news_ids: 이 관계를 실제로 서술하고 있는 기사의 id(<입력_기사>의 각 기사 앞 [id=N])만 배열로 적으세요. 배치 전체가 아니라 그 관계를 말하는 기사만 고르세요. 최소 1건입니다.

찾은 관계가 하나도 없으면 relations를 빈 배열로 응답하세요.
"""


OUTPUT_SCHEMA_RELATION = {
    "type": "object",
    "properties": {
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "org_a_index": {"type": "integer"},
                    "org_b_index": {"type": "integer"},
                    "label": {"type": "string", "enum": RELATION_LABELS},
                    "reason": {"type": "string"},
                    "news_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 1,
                    },
                },
                "required": ["org_a_index", "org_b_index", "label", "reason", "news_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["relations"],
    "additionalProperties": False,
}


def build_relation_org_index(news_list):
    """관계 추출 호출의 기업 인덱스(1부터, 3-2 "기업은 이름이 아니라 인덱스로
    받는다" — pk가 아니라 인덱스인 이유는 "범위가 닫혀 있어 검증이 자명하다").
    배치(news_list)에 태깅된 활성 기업을 모아 정렬한다 — 반환 리스트의 i번째
    원소(0-base)가 곧 idx=i+1이다.

    services/runner.py가 이 반환값을 그대로 들고 있다가 응답의 org_a_index/
    org_b_index를 Organization으로 되짚는다 — 이 함수를 두 번 호출하지 않는다
    (호출마다 정렬 결과가 같아도, "생성한 인덱스"와 "되짚는 인덱스"가 서로 다른
    조회에서 나오면 그 사이 데이터가 바뀔 때 어긋날 수 있다)."""
    from apps.setting.models import Organization

    return list(
        Organization.objects.filter(news__in=news_list, is_active=True)
        .distinct().order_by("org_type", "name")
    )


def _build_relation_user_message(news_list, org_index) -> str:
    """_build_insight_user_message()를 그대로 재사용하고(3-1 근거 3, 재료가 같다)
    기업 인덱스 부표만 덧붙인다."""
    org_lines = [f"[idx={i}] {org.name} ({org.org_type})" for i, org in enumerate(org_index, start=1)]
    return (
        _build_insight_user_message(news_list)
        + "\n\n<기업_목록>\n" + "\n".join(org_lines) + "\n</기업_목록>"
    )


def _parse_relation_response(response) -> dict:
    """구조화 출력을 파싱한다. _parse_insight_response()와 같은 방식(json.loads()만
    쓴다, 문자열 매칭 금지)."""
    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise LLMJudgmentError(
            f"관계 추출 응답에 text 블록이 없어요(stop_reason={response.stop_reason})."
        )
    try:
        data = json.loads(text_block.text)
    except json.JSONDecodeError as exc:
        raise LLMJudgmentError(f"관계 추출 응답 JSON 파싱에 실패했어요: {exc}") from exc

    usage = response.usage
    data["_usage"] = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return data


def extract_relations(news_list, org_index) -> dict:
    """3단계 두 번째 호출 — 관계를 뽑는다. org_index는 build_relation_org_index()의
    반환값을 그대로 받는다(호출부와 같은 인덱스를 공유해야 응답의 org_a_index/
    org_b_index를 되짚을 수 있다).

    🔴 기업 인덱스가 2개 미만이면(관계가 성립할 최소 쌍조차 없음) 호출 자체를
    만들지 않는다 — 헤드라인 호출의 "후보 0건이면 조용히 끝낸다. LLM 호출 자체를
    만들지 않는다(비용)"와 같은 판단.

    Returns:
        {"relations": [...], "_usage": {...}} — relations의 각 원소는
        org_a_index/org_b_index/label/reason/news_ids. 호출 자체를 만들지 않은
        경우 _usage는 빈 dict다(호출부가 usage.get(key, 0)으로 안전하게 합산한다).

    Raises:
        LLMStructuralError: 인증·권한·리소스 오류.
        LLMJudgmentError: 그 밖의 실패(rate limit·네트워크·응답 형식 불량). 호출이
            1회라 이어하기가 없다 — 실패하면 관계 추출만 이번 배치에서 빠진다
            (3-1 근거 4 "실패가 격리된다" — 이슈 초안은 이미 별도 트랜잭션으로
            저장돼 이 실패의 영향을 받지 않는다. services/runner.py가 이 예외를
            잡아 로그만 남기고 넘어간다).
    """
    if len(org_index) < 2:
        return {"relations": [], "_usage": {}}

    client = _get_client()
    try:
        response = client.messages.create(
            model=settings.BEDROCK_MODEL_SMART,
            max_tokens=4096,
            system=_build_relation_system_prompt(),
            messages=[{"role": "user", "content": _build_relation_user_message(news_list, org_index)}],
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA_RELATION}},
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
        logger.error("관계 추출 중 구조적 오류(인증/권한/리소스): %s", exc)
        raise LLMStructuralError(str(exc)) from exc
    except anthropic.RateLimitError as exc:
        logger.warning("관계 추출 중 rate limit에 걸렸어요: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIConnectionError as exc:
        logger.warning("관계 추출 중 네트워크 오류: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIStatusError as exc:
        logger.warning("관계 추출 중 API 오류(status=%s): %s", exc.status_code, exc)
        raise LLMJudgmentError(str(exc)) from exc
    else:
        return _parse_relation_response(response)


# ============================================================================
# 3단계 세 번째 호출 — 헤드라인 순위. docs/planning.md "RA 손 작업을 전부 단계 안으로
# 넣는다" 2번이 정본.
#
# 🔴 1-B "창 결정 규칙" 6단계 중 1~3(1급 집합·기준점·창)은 코드가 이미 끝내고, 이
# 호출에는 그 결과(창 안 1급 후보 풀)만 들어온다(2-1) — 이 함수는 4~6단계
# ((ii)→(i)→서사 사슬, 5번 중복 제외, 5-1 다양성)만 맡는다. 다양성은 LLM이 업권
# 라벨을 내고, 최종 집계·상한 강제는 호출부(services/runner.py)가 한다(2-1 "LLM이
# 업권 라벨을 내고 코드가 센다").
#
# 🔴 창·1급 판정에는 절대 쓰지 않는다 — 이 호출이 받는 candidates는 이미 그 조건을
# 통과한 것만이다(1-B ⚠️ "하루 차이로 헤드라이너가 갈리는 자리에 판정자 재량을
# 남기지 않는다").
# ============================================================================

PROMPT_VERSION_HEADLINER = "headliner-2026-09-17a"

# 5-1 "업권 목록 (확장형, 폐쇄 아님)" 원문 그대로.
HEADLINER_SECTORS = [
    "인터넷전문은행", "시중은행", "국책은행과 특수은행", "금융지주", "증권",
    "카드와 캐피탈", "핀테크", "생명보험", "손해보험", "재보험", "금융 인프라 기관",
]
# 5-1 "여러 업권에 걸치는 이슈는 다양성 계산에서 빼고 항상 통과" / "(d) 제도 경로로
# 1급이 된 건은 업권 없음으로 적고 항상 통과". 목록에 없는 sector 문자열과 구분되는
# 두 특수값이다 — services/runner.py가 다양성 집계에서 이 둘을 제외한다.
HEADLINER_SECTOR_MULTI = "여러 업권"
HEADLINER_SECTOR_NONE = "업권 없음"


def _build_headliner_system_prompt() -> str:
    sector_list = ", ".join(HEADLINER_SECTORS)
    return f"""당신은 AI Market Watch 프로젝트에서, 이번 주 1급 이슈 후보 중 대시보드 최상단(헤드라인)에 올릴 최대 3건을 고릅니다.

<판정_기준>
## 순위를 매기는 사슬 — (ii) 변화의 구체성 → (i) 파급 범위 → 서사
(ii) 변화의 구체성 — 그 건이 "무엇을 도입했다"에서 멈추는가, "무엇이 무엇으로 달라졌다"까지 사실로 특정되는가. 특정된 쪽이 앞이고, 특정된 변화가 클수록 앞입니다.
(i) 파급 범위 — 한 회사에서 끝나는가, 여러 회사·업계 관행에 걸치는가. 근거 기사 수가 아니라 사건 자체의 파급력을 봅니다. 참여자가 여럿인 사건, 금융권 AI 도입 조건 자체를 바꾸는 규제 변경은 회사 수가 적어도(0이어도) 파급 범위가 최상일 수 있습니다.
앞 물음에서 갈리지 않으면 다음 물음으로, 그래도 갈리지 않으면 서사(더 선명하게 읽히는 쪽)로 정하세요.

## 중복 제외
이미 뽑기로 한 후보와 같은 사실(같은 사건)을 말하는 후보는 뽑지 마세요. 판별선은 "같은 사실"입니다 — 주제가 닮았거나 서술이 겹치는 것만으로는 중복이 아닙니다. 회사·시스템·업무 영역이 다르면 같은 사실이 아닙니다.

## 다양성 — 3자리에 같은 업권은 2건까지
업권 목록(확장형, 폐쇄 아님): {sector_list}. 목록에 없는 업권이면 그 이름을 그대로 적고 sector_unlisted를 true로 하세요 — 비슷한 업권에 억지로 밀어 넣지 마세요.
여러 업권에 걸친 후보(예: 여러 보험사가 함께 참여)는 sector에 "{HEADLINER_SECTOR_MULTI}"를 적으세요 — 다양성 계산에서 빠지고 항상 통과합니다.
개별 금융사 당사자 없이 규제기관이 금융권 AI 규율 자체를 바꾼 건은 sector에 "{HEADLINER_SECTOR_NONE}"을 적으세요 — 역시 다양성 계산에서 빠집니다.
업권은 후보 안의 금융/보험 측 당사자를 기준으로 판정하세요(상대 AI 기업의 업종은 보지 않습니다).

## 판정 승계 — 새 사실 없이 뒤집지 않는다
<직전_헤드라인>은 지난 배치에서 이미 순위가 갈린 결과입니다. 새 사실(새 근거뉴스, 다른 후보의 등장·이탈, 이슈 내용 개정)이 없다면 그 순서를 그대로 유지하세요. 판단을 다시 적용해 순서를 뒤집었다면, picks의 해당 후보 change_reason에 무엇이 새로 달라졌는지 한 문장으로 적으세요. 근거 없이 느낌으로 순서를 바꾸지 마세요. change_reason이 필요 없으면 빈 문자열로 두세요.
<직전_헤드라인>의 후보가 <입력_후보>에 있는데 이번 picks에 포함하지 않기로 했다면, dropped_prev_headliners에 그 이유를 적으세요 — "중복 제외"(어느 후보와 같은 사실인지 reason에 적으세요) 또는 "1-A 재적용"(사슬의 어느 마디에서 밀렸는지 reason에 적으세요) 중 하나로 분류하세요. <직전_헤드라인>의 후보인데 <입력_후보>에 아예 없는 것은 이미 창 밖으로 나갔거나 등급이 바뀐 것이라 여기서 다룰 대상이 아닙니다 — dropped_prev_headliners에 적지 마세요.
</판정_기준>

임무: <입력_후보> 중에서 최대 3건을 순위대로 고르세요(0~2건도 가능합니다 — 억지로 채우지 마세요). 아래 스키마로 응답하세요.
- picks: 순위 1위부터 순서대로. candidate_id는 <입력_후보>의 [id=N] 그대로, sector/sector_unlisted는 위 "다양성" 기준, reason은 위 사슬로 이 순위를 정한 이유 한 문장, change_reason은 위 "판정 승계" 기준(필요 없으면 빈 문자열).
- dropped_prev_headliners: 위 "판정 승계" 두 번째 문단 기준.
"""


OUTPUT_SCHEMA_HEADLINER = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "maxItems": 3,  # 🔴 상한 3 강제 자리 다섯 중 하나(2-4 ①). 나머지 넷은
            # 확정 뷰·대시보드 슬라이스·이 문서(docs/planning.md)·docs/design.md.
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "integer"},
                    "sector": {"type": "string"},
                    "sector_unlisted": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "change_reason": {"type": "string"},
                },
                "required": ["candidate_id", "sector", "sector_unlisted", "reason", "change_reason"],
                "additionalProperties": False,
            },
        },
        "dropped_prev_headliners": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "insight_pk": {"type": "integer"},
                    "reason_category": {"type": "string", "enum": ["중복 제외", "1-A 재적용"]},
                    "reason": {"type": "string"},
                },
                "required": ["insight_pk", "reason_category", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["picks", "dropped_prev_headliners"],
    "additionalProperties": False,
}


def _build_headliner_user_message(candidates, prev_ranking) -> str:
    """candidates: [{"temp_id", "title", "content"}] — 코드가 이미 1급+창으로 좁힌
    후보 풀(services/runner.py가 만든다). prev_ranking: [{"insight_pk", "prev_rank",
    "title", "reason"}] — 직전 배치 지정 스냅샷."""
    cand_blocks = [
        f"[id={c['temp_id']}] {c['title']}\n{c['content']}" for c in candidates
    ]
    prev_lines = (
        "\n".join(
            f"{p['prev_rank']}위 [insight_pk={p['insight_pk']}] {p['title']} — {p['reason'] or '(사유 없음)'}"
            for p in prev_ranking
        )
        or "없음(이번이 첫 지정입니다)"
    )
    return (
        "<입력_후보>\n" + "\n\n---\n\n".join(cand_blocks) + "\n</입력_후보>\n\n"
        f"<직전_헤드라인>\n{prev_lines}\n</직전_헤드라인>"
    )


def _parse_headliner_response(response) -> dict:
    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise LLMJudgmentError(
            f"헤드라인 순위 응답에 text 블록이 없어요(stop_reason={response.stop_reason})."
        )
    try:
        data = json.loads(text_block.text)
    except json.JSONDecodeError as exc:
        raise LLMJudgmentError(f"헤드라인 순위 응답 JSON 파싱에 실패했어요: {exc}") from exc

    usage = response.usage
    data["_usage"] = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return data


def rank_headliners(candidates, prev_ranking) -> dict:
    """1급+창 후보 풀에서 헤드라인 순위를 매긴다(3단계 세 번째 호출).

    Returns:
        {"picks": [...], "dropped_prev_headliners": [...], "_usage": {...}}
    Raises:
        LLMStructuralError, LLMJudgmentError — generate_insights()와 같다. 호출이
        1회라 이어하기가 없다.
    """
    client = _get_client()
    try:
        response = client.messages.create(
            model=settings.BEDROCK_MODEL_SMART,
            max_tokens=4096,
            system=_build_headliner_system_prompt(),
            messages=[{"role": "user", "content": _build_headliner_user_message(candidates, prev_ranking)}],
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA_HEADLINER}},
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
        logger.error("헤드라인 순위 중 구조적 오류(인증/권한/리소스): %s", exc)
        raise LLMStructuralError(str(exc)) from exc
    except anthropic.RateLimitError as exc:
        logger.warning("헤드라인 순위 중 rate limit에 걸렸어요: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIConnectionError as exc:
        logger.warning("헤드라인 순위 중 네트워크 오류: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIStatusError as exc:
        logger.warning("헤드라인 순위 중 API 오류(status=%s): %s", exc.status_code, exc)
        raise LLMJudgmentError(str(exc)) from exc
    else:
        return _parse_headliner_response(response)


# ============================================================================
# 4, 5단계(주간·월간 보고서) 판정 — docs/planning.md "3~5단계를 LLM으로 옮기는 설계"가
# 정본. 3단계와 같은 구조를 그대로 물려받는다(같은 문서 7-(a)(b)) — 배치 전체 1호출,
# 캐싱 없음, 모델은 BEDROCK_MODEL_SMART.
#
# 🔴 보고서 제목은 스키마에 없다(설계 8-(C)). 코드가 서식으로 만든다
# (services/report_periods.py weekly_title()/monthly_title()) — "보고서 제목 실패
# 4유형"을 생성하지 않는 것으로 원천에서 없앤다.
#
# 🔴 입력은 News가 아니라 그 기간의 Insight다 — "보고서는 처음부터 다시 쓰는 글이
# 아니라 그 기간 Insight의 선별·요약본"이다(「주간 보고서(Report) 표준 구조」 7번).
#
# 🔴 `### 이슈 제목` 규칙은 3단계의 이슈 제목 규칙과 같은 원문이다(「판단의 형식」
# 7번·7-1·7-1-a·7-2 계열이 「주요 이슈 승격 기준」 절의 "이슈 제목 규칙"과 같은
# 조항을 가리킨다) — 위에서 이미 정의한 _CRITERIA_INSIGHT_TITLE_FORM,
# _CRITERIA_INSIGHT_TITLE_ENDING을 그대로 재사용한다. 두 벌로 베끼면 한쪽만 고치는
# 드리프트가 생긴다.
#
# ⚠️ "출처 무결성 점검" 절차는 넣지 않는다(설계 8-(B) "빼는 것") — 검사자가 작성자와
# 같아지는 것을 막기 위해서다. "보고서 길이 버전"(축약본) 절도 넣지 않는다 —
# content_short/implication_short는 확정 시점에 비운 채로 만들고 RA가 나중에 채운다
# (설계 6번).
# ============================================================================

# 🔴 2026-09-17a — 출력 스키마에 content_keep(축약본 문장 번호 배열)을 추가해 올렸다
# (docs/planning.md "RA 손 작업을 전부 단계 안으로 넣는다" 4번, 3번과 같은 방식).
PROMPT_VERSION_WEEKLY = "weekly-2026-09-17a"
PROMPT_VERSION_MONTHLY = "monthly-2026-09-17a"


# docs/planning.md 「주간 보고서(Report) 표준 구조」 2~7번. 1번(제목 고정 서식)은
# 뺀다 — 제목은 LLM이 만들지 않으므로 그 규칙을 프롬프트에 넣으면 모델이 제목을
# 만들려 한다(설계 8-(C)).
_CRITERIA_REPORT_STRUCTURE = """\
2. **overview(주요 동향)** — 개별 이슈를 나열하지 않고, 그 기간 전체를 관통하는 흐름을 상위 서술로 정리한다. 작성 규칙은 아래 "독자는 경영진이다" 3-2에 있다.
3. **content(주요 이슈)** — 이슈 블록 N개(상한 5건, 하한 없음)를 markdown 형식으로 담는다. 이슈당 고정 구성(제목→분석→시사점 3단 + 참고 규약 줄):
   - `### 이슈 제목`
   - 흐름 분석 — 기본 1문단, 조건부 분할 허용
   - 시사점 1~2문장. 주체를 지칭하지 않는다. `**시사점:**` 같은 라벨을 붙이지 않고, 흐름 분석 다음에 이어지는 라벨 없는 일반 문단으로 쓴다. 즉 (참고 규약 줄을 제외한) 이슈 블록의 마지막 문단이 곧 시사점이다.
   - 참고뉴스 규약 줄 — 블록 최하단에 그 이슈의 근거 News를 `참고: <uid>, <uid>` 형식으로 적는다. 자유 링크·제목을 손으로 쓰지 않는다.
   - 이슈당 근거 News 최소 1건. 동일 사건 중복 보도면 여러 uid를 함께 적는다.
4. **Report.news(근거 기사)** — 모든 이슈 블록 `참고:` 줄에 적힌 uid의 합집합이 곧 이 보고서의 근거 기사 전체다. 본문이 정본이다 — 본문에 서술하지 않은 사례의 근거는 `참고:` 줄에도 남기지 않는다.
5. **status** — 이 보고서는 저장 시 사람이 검수를 마치기 전 상태로 만들어진다. 본문 안에 "생성 중" 같은 표기를 쓰지 않는다.
6. **스코프 일치** — 보고서에 싣는 이슈도 「주요 이슈 승격 기준」과 동일 스코프(금융/보험에 연결된 것만)를 따른다. 입력으로 주어지지 않은 News를 임의로 끌어와 스코프를 이탈하지 않는다.
7. **Insight → Report 관계** — 보고서는 처음부터 다시 쓰는 글이 아니라 "그 기간 Insight의 선별·요약본"이다. 상위 N건을 선별해 이슈 블록으로 옮기되(Insight의 분석 → 흐름 분석, Insight의 시사점 → 시사점 요약), 내용을 재활용한다.
"""

# docs/planning.md "독자는 경영진이다" 절 1, 2, 3, 3-1, 3-2, 4, 6, 6-1. 날짜 꼬리표와
# 폐기된 규칙 서술(개정 이력, "종전에는 ~였으나")은 뗐다 — 현재 규칙만 남긴다.
_CRITERIA_REPORT_AUDIENCE = """\
**1. 독자 정의**

주간 보고서와 월간 결산의 독자는 경영진이다. 통과 기준은 "실무자가 이해하는가"가 아니라 다음 하나다.

> **경영진이 제목과 개요만 읽고도 "무슨 일이 있었고 왜 중요한지"를 아는가.**

독자 정의는 문체 지시가 아니라 "설명 없이 통용된다고 가정할 수 있는 지식의 범위"를 정한 것이다. 가정해도 되는 지식은 금융·보험 업계의 일반 경영 어휘와 **AI 용어**다. 가정하면 안 되는 지식은 AI 용어가 아닌 기술·실무·제도 용어, 실무 프로세스 명칭, 제품·모델 고유명사다.

**2. 용어 처리 — 가르는 축은 "AI 용어인가"다**

**확정 규칙**: **AI 용어는 그대로 쓴다. AI 용어가 아닌 말은 첫 등장에 푼다.**

**(1) AI 용어의 경계 — 두 물음에 모두 예여야 AI 용어다**

> **(i) 그 말이 가리키는 대상이 AI·데이터 기술 그 자체인가?** (기법·모델·구성요소·기술 노선)
> **(ii) AI 맥락 밖으로 옮기면 그 말이 뜻을 잃는가?** (다른 분야에서도 쓰이는 말이면 아니다)

| 판정 | 예 |
|---|---|
| **AI 용어 → 그대로** | `AI`·`AX`·`LLM`·`AI 에이전트`·`에이전틱 AI`·`멀티모달`·`연합학습`·`소버린 AI`·`RAG`·`파인튜닝` |
| **AI 용어 아님 → 푼다** | `망분리`(보안 규제 용어, AI 없이도 존재) · `오픈소스`(소프트웨어 일반) · `FDS`(규칙기반 시절부터 있던 금융 용어) · `언더라이팅`·`요율`·`컨소시엄`·`양해각서`·`딥페이크` · `정량적인 위험 지표`·`사면 안정성` |

기술 자체와 그 기술이 만든 현상·범죄·제도를 가른다. `딥페이크`는 AI 맥락에서만 쓰이지만 기술 이름이 아니라 피해 현상을 가리키므로 AI 용어가 아니다. ⚠️ **애매하면 푼다(tie-break)** — 두 물음 중 하나라도 확신이 안 서면 AI 용어가 아닌 쪽으로 본다.

**(2) AI 용어가 아닌 말의 처리 — 세 갈래**

| 갈래 | 조건 | 처리 | 예 |
|---|---|---|---|
| **대체** | 뜻이 **정확히 같은** 일상어가 있다 | 원어를 버리고 일상어만 쓴다 | `언더라이팅` → 보험 인수 심사 / `요율 산출` → 보험료 계산 / `FDS` → 이상거래탐지 / `양해각서` → 협력 합의 |
| **병기** | 풀면 뜻이 **좁아지거나 달라진다** | 원어를 유지하고 **첫 등장 1회만** 괄호나 짧은 동격구로 설명 | `망분리` → 내부 업무망과 외부 인터넷을 분리하는 규제(망분리) |
| **한정** | 제품·모델 **고유명사** | 이름은 지우지 않고 **앞에 소속·정체를 붙인다** | `제미나이` → 구글의 AI 모델 제미나이 |

대체는 손실이 0일 때만 쓴다 — 뜻이 조금이라도 좁아지면 대체하지 말고 병기한다. 고유명사는 AI 제품이어도 한정을 붙인다. **그 상위어도 근거 안에서 온다** — 참이기만 하면 되는 게 아니라 그 참을 근거 기사에서 확인할 수 있어야 한다. 측정 단위는 횟수가 아니라 종류다 — 첫 등장에서 처리했으면 그 뒤 반복은 원어 그대로 쓴다. 제목에도 그대로 적용된다. 다만 제목에는 괄호 병기가 어울리지 않으므로 **제목에서는 대체와 한정만 쓰고, 병기가 필요한 용어는 제목에 넣지 않는다**(본문 첫 등장에서 푼다).

**3. 위쪽이 가장 완결적이어야 한다 — 단, 개요를 요약문으로 만들지 않는다**

경영진은 위에서부터 읽다 멈춘다. 읽히는 확률은 `제목 > 개요 1문단 > 이슈 제목 > 이슈 본문` 순이다.

⚠️ **"완결적"은 "내역을 다 담는다"가 아니다.** 개요가 답하는 것은 **그 기간 전체가 무엇이었는가**이고, **누가 언제 무엇을 얼마에 했는가는 이슈 블록이 답한다.** 개요의 한 문장을 지웠을 때 **같은 사실을 아래 이슈 블록에서 그대로 다시 읽을 수 있으면** 그 문장은 개요의 몫이 아니다. 반대로 **어느 이슈 블록에도 그 말이 없으면**(그 기간 전체를 묶는 서술이면) 개요의 몫이다. ⚠️ **새 요약 문단을 만들지 않는다** — 개요가 이슈 요약이 되면 안 된다.

**3-1. 문단 나눔은 세는 게 아니라 가르는 것이다**

> **개요의 문단은 성격이 갈리는 자리에서 나눈다. 문단 수는 상한이 아니라 그 결과값이다.**

**셋이 다 있어야 하는 것은 아니다.** 성격이 둘뿐이면 2문단, 하나뿐이면 1문단이다. **나눈다고 문장이 늘거나 줄지 않는다** — 허용되는 것은 문단 구분(빈 줄)뿐이다.

**3-2. 「주요 동향」(overview) 작성 규칙**

> | 항목 | 규칙 |
> |---|---|
> | 구조 | **문단당 한 문장, 세 문단.** 문단 사이는 빈 줄 |
> | 길이 | **세 문단 합쳐 500자 미만**(공백 포함, 문단당 약 160자) |
> | 내용 | **회사명과 숫자를 넣지 않는다. 다만 어떤 업무인지는 이름을 붙인다** |
> | 문체 | 서술체(`~고 있다`, `~는 모습이다`) |
> | 금지 | 줄표(`—`) / 회사 나열의 가운뎃점(`·`) / `분기점` 낱말 / `이번 주(달)의 ○○은 …이다` 선언 형식 / 구어체 동사 |

**(1) 구조와 길이** — 길이를 줄이려고 문장을 압축하지 않는다. **줄이는 것은 문장 수다.** 세 문단이 각 한 문장이면 500자는 저절로 지켜진다. 세 문단의 성격은 그 기간의 실제 사실이 정한다(예: ① AI가 어느 업무까지 들어왔는가, ② 조직과 평가체계에 내재화되고 있는가, ③ 제도와 기반이 갖춰지고 있는가 — 고정 목록이 아니라 그때그때의 실제 흐름이다). **셋째 축이 없으면 억지로 맞추지 않고 실제 있었던 세 번째 흐름으로 바꾼다.** 사실이 "갖춰지고 있다"가 아니면 그렇게 닫지 않는다 — 확정되지 않았다는 사실까지 쓴다.

**(3) 내용** — 개별 사실은 이미 아래 「주요 이슈」에 다 있다. 개요에서 또 말하면 겹친다. 그렇다고 뭉뚱그리면 아무 때나 붙는 말이 된다.

```
너무 뭉뚱그림   자산운용, 문서처리 등 핵심 업무 영역으로 확대되고 있으며
채택된 형태     퇴직연금 적립금의 자산 운용 일임과 여신 문서 처리 등
                자금과 심사가 실제로 오가는 업무로 들어서고 있으며
```

**(4) 문체** — 구어체 동사를 쓰지 않는다.

```
❌  돌린다 / 붙인다 / 얹는다 / 깐다 / 뽑아 온다
✅  운용한다 / 적용한다 / 도입한다 / 설치한다 / 조회한다
```

판별은 하나다 — **그 동사가 경영진에게 올리는 문서에 놓였을 때 격이 맞는가.**

**(5) 금지** — 줄표(`—`)를 개요에 쓰지 않는다. 가운뎃점(`·`)은 회사를 나열하는 데 쓰지 않는다(낱말을 묶는 용법은 무방하다). `이번 주(달)의 ○○은 …이다` 선언 형식은 문단 머리에도 걸린다. **`분기점`이라는 낱말은 쓰지 않는다** — 그 자리가 하는 일(그 기간의 축을 먼저 말한다)은 유지하되, 대비 형식이 아니라 업무 축의 서술로 말한다.

**4. 본문 분량 상한은 두지 않는다**

이슈 블록에 글자 수 상한을 두지 않는다 — 상한은 잘라내려고 사실을 빼는 압력이 되기 때문이다. 대신 **한 이슈 블록이 1,000자를 넘으면 분량 위반이 아니라 이슈 구성 점검 신호**로 본다 — 그 블록이 실은 두 이슈인가, 축 없이 사례를 나열하고 있는가를 확인한다. 점검해서 문제가 없으면 1,000자를 넘긴 채로 둔다.

**6. 문장 — 한 문장에 한 요지. 예의는 어미가 아니라 문장 구조에서 나온다**

적용 범위 — 보고서의 산문 전체(개요·흐름 분석·시사점). 제목 층에는 걸리지 않는다.

**(1) 한 문장에 한 요지**

> **판별: 그 문장의 요지를 한 줄로 되받을 때 `그리고`·`또한`·`~하면서`로 이어 붙여야 하는가.** 이어 붙여야 하면 요지가 둘이다. 끊는다.

길이는 재지 않는다 — 긴 문장이 요지 하나면 통과이고, 짧은 문장이 요지 둘이면 위반이다. **끊은 결과가 사실을 깎으면 끊지 않는다.**

**(2) 예의 — 존댓말을 뜻하지 않는다**

어투는 그대로다. 본문은 `~다` 단정으로 쓴다. **겸양·완곡을 붙여 예의를 만들지 않는다** — *"~인 듯하다"*·*"~할 필요가 있어 보인다"* 류는 예의가 아니라 결론 회피의 재도입이다. 처방은 어미가 아니라 구조다 — **겹문장을 끊는다.**

**(3) 독자의 정보만 쓴다 — 작성자·조직의 사정은 쓰지 않는다**

> **판별: 그 문장이 독자에게 주는 정보인가, 쓴 쪽의 사정인가.** 사정이면 본문에서 지운다.

**6-1. 내러티브 봉합 금지 — 사실을 나열한 뒤 하나의 주제로 묶는 총평 문장을 붙이지 않는다**

적용 범위는 6번과 같다. 6번이 한 문장 안을 본다면 이 조항은 문단의 마지막 문장(과 첫 문장)을 본다.

**(1) 무엇이 문제인가** — 사실을 나열한 뒤 그것들을 하나의 주제로 봉합하려고 덧붙인 총평을 쓰지 않는다. 근거 News 어디에도 없는 저자의 프레이밍이다. 개별 사실은 맞아도 그 위에 얹힌 해석이 마치 관측된 사실인 것처럼 단정형으로 선언되면 안 된다. **아무 때나 붙여도 그럴듯해서 아무것도 말하지 않는 문장이 전형이다.**

**(2) 어떻게 하는가 — 고쳐 쓰지 않고 통째로 지운다**

> **판별: 그 문장을 지우면 독자가 잃는 사실이 있는가.** 없으면 지운다.

완곡하게 고쳐 쓰는 것은 처방이 아니다.

**(3) 문단 끝과 문단 첫머리가 위험 지점이다.** 사실을 나열하고 나면 마무리를 지으려는 충동이 생기는데, 사실 나열로 끝내는 것이 맞다.

**금지 패턴 예시**

| 패턴 |
|---|
| `이번 주(달)의 물음은/분기점은/특징은 …이었다` |
| `…한 주(달)였다` |
| `한 주(달) 안에 함께 나타났다` / `동시에 드러났다` |
| `A가 아니라 B다`(기사에 없는 대조를 저자가 세우는 형태일 때) |
| `…라는 점에서 의미가 있다` / `…를 보여준다` |

**(4) 대조 자체는 금지가 아니다.** 두 사실을 각각 사실 그대로 적어 대비시키는 것은 허용된다. **금지되는 것은 대조가 아니라 대조를 하나로 묶는 마무리 문장이다.**
"""

# docs/planning.md "판단의 형식" 절 0, 1, 2, 3, 4, 5, 5-1, 6, 9. 7·7-1·7-1-a·7-2 계열은
# 3단계의 _CRITERIA_INSIGHT_TITLE_FORM·_CRITERIA_INSIGHT_TITLE_ENDING과 같은 원문이라
# 재사용한다(중복 정의 금지). 8번(제목 고정 서식)은 뺀다 — 제목은 LLM이 만들지 않는다.
_CRITERIA_REPORT_JUDGMENT = """\
**0. 관통 원칙 — 의무화가 날조를 만든다**

"있으면 쓰고, 없으면 없다고 적는다" 형태는 의도된 설계다. **어떤 요소를 반드시 넣으라고 형식으로 강제하면, 그 요소가 없는 기간에는 없는 것을 지어내게 된다.**

**1. 시사점은 판단으로 끝낸다**

- **필수** — 그 사실이 **뜻하는 것을 단정한다**. 문장은 `~다`로 끝난다.
- **선택** — 판단이 갈리는 지점(무엇에 따라 결론이 달라지는가), 판별 기준(무엇을 보면 아는가).
- **선택** — 검토 방향(`~ 방향으로 검토해볼 수 있다`). 두 조건을 **모두** 만족할 때만 쓴다: (i) 그 앞에 판단이 이미 있을 것, (ii) 그 방향이 **기사 사실에서 직접 도출될 것**. 섹션마다 붙이지 않는다.
- **금지 (a) — 결론 회피** — "지켜볼 필요가 있다", "지속 모니터링할 필요가 있다"로 끝내지 않는다. 같은 회피를 단정 어미로 포장한 문장(예: "향후 추이가 관건이다", "귀추가 주목된다")도 **동일하게 금지**한다. 판별법: 그 문장을 지워도 독자가 잃는 정보가 없으면 그건 판단이 아니다.
- **금지 (b) — 주체 지칭** — `DPLANEX는`, `전략기획팀은`, `우리는` 같은 주어를 쓰지 않는다.
- **근거가 부족해 판단이 안 서면, 쓸 수 있는 만큼만 쓰고 멈춘다.** "현재 근거로 판단할 수 없다" 같은 표기도 본문에 쓰지 않는다 — 못 쓴다고 회피로 도피하지 않는다.

```
❌ 두 노선이 어떻게 갈라지는지 지속 모니터링할 필요가 있다.
❌ 두 노선의 향방이 향후 최대 관건이다.
✅ 어느 쪽이 우세한지는 현재 근거로 판단할 수 없다.
   갈림길은 규제 대응 비용과 성능 격차 중 무엇이 먼저 임계에 닿는가다.
```

**2. "검토해볼 수 있다"는 조건부다 — 의무가 아니다**

섹션마다 붙이지 않는다.

**3. 반증 사례**

그 배치에 반증 사례(선행 흐름과 어긋나는 사실, 기대한 효과가 나타나지 않은 사례)가 **있으면 본문에 반드시 넣는다.** 없으면 넣지 않는다.

**4. 등급을 노출하지 않는다**

1급/2급/3급은 **내부 판정 도구**다. 문서에 노출하면 독자와 "왜 이게 1급이냐"는 논쟁이 붙는다. **본문 어디에도 등급을 쓰지 않는다.**

**5. 이슈 블록 배치 순서 — 중요도가 큰 순으로 배치한다**

> **(i) 파급 범위** — 그 건의 영향이 **한 회사 안에서 끝나는가, 여러 회사·업계 관행에 걸치는가.** 넓은 쪽이 앞이다.
> **(ii) 실행 단계** — **계획·발표에 머무는가, 이미 가동·집행된 사실인가.** 가동·집행된 쪽이 앞이다.

두 물음이 어긋나면 **(i) 파급 범위가 우선한다.** 동률이면 **등급**(1급 → 2급 → 3급)으로 가르고, 그래도 동률이면 **서사 흐름**으로 놓는다. **"실측 수치가 있는 이슈를 위로" 같은 규칙은 두지 않는다** — 수치는 판정 기준이 아니라 실행 단계의 부산물이다. **순서의 근거를 본문에 쓰지 않는다** — "가장 중요한 이슈는" 같은 표기를 붙이지 않고 위치로만 드러낸다.

**5-1.** 순서 전체를 정한 뒤, **1급이 연속으로 붙어 있는 구간**이 있으면 **그 구간 내부만** (변화의 구체성 → 파급 범위 → 서사) 순으로 다시 정렬한다. **구간 밖과의 상대 위치는 건드리지 않는다.**

**6. 흐름 분석 문단 — 조건부 분할 허용**

`흐름 분석 1문단` 고정을 완화한다. **나열 대상이 3개를 넘으면 문단을 나눌 수 있다. 단, 나눈 각 문단은 반드시 그 문단을 묶는 축을 제시한다.** 분할은 권리이지 의무가 아니다 — **사례가 4개여도 축이 안 나오면 나누지 말고 1문단으로 둔다.**

**9. 이슈 개수 — 상한 5건, 하한 없음. 그 기간에 있었던 만큼만 싣는다**

1. **상한 5건. 하한은 없앤다.** 실을 것이 1건이면 1건이다. **적게 싣는 것은 부실이 아니라 그 기간의 사실이다.**
2. **진입 문턱을 근거 건수로 두지 않는다.** "근거 N건 이상이어야 싣는다"는 만들지 않는다.
3. **등급도 진입 문턱으로 쓰지 않는다.**
4. **싣지 않는 기준은 판단 축이다** — 그 이슈에서 쓸 수 있는 시사점이 사실 재진술뿐이면 싣지 않는다. **판별법은 1번 금지 (a)의 것 그대로다** — 그 시사점 문장을 지워도 독자가 잃는 정보가 없으면 그 이슈는 실을 것이 없다. **상한 5를 넘을 때 자르는 기준은 5번(중요도 순 배치)의 순서에서 아래부터 자른다.**

⚠️ **보고 기간은 확장하지 않는다.** 이슈가 적은 기간이라고 창을 넓히지 않는다. **"그 기간 이슈"의 판별은 `Insight` 작성일이 아니라 근거 News의 발행일이다.**
"""

# docs/planning.md "정량 지표 — 근거에 있으면 쓴다" 절.
_CRITERIA_REPORT_QUANT = """\
**0. 이 조항의 범위 — "근거에 있으면 쓴다"까지다. "매 섹션에 숫자를 넣어라"가 아니다.**

**강제되는 것은 수치 삽입이 아니라 *찾는 행위*다.** 위반 판정 기준은 "수치가 0개다"가 아니라 **"근거에 있는데 안 썼다"**이다. 근거에 수치가 없는 이슈는 수치 없이 쓰는 게 맞고, 그건 위반이 아니다.

**1. 쓸 만한 수치의 기준 — 숫자가 있다고 다 값어치 있는 게 아니다**

| 판정 | 조건 | 예 |
|---|---|---|
| **쓴다** | 그 사건의 **규모·범위·성과**를 재는 값 | 적용 건수, 확대 범위, 계약·투자 금액, 처리량, 개선폭, 비율 |
| **안 쓴다** | 값이 문장의 뜻을 바꾸지 않는 값 | 단순 시점 표기(`2030년`·`2023년`), 맥락 없는 단위 값(`4분`), 그 이슈의 사건과 무관한 수치 |

> **판별법: 그 숫자를 지웠을 때 문장이 약해지는가.** 약해지면 쓸 만한 수치이고, 아무 차이가 없으면 장식이다.

수치는 판단을 대신하지 않는다 — 수치를 나열하고 시사점을 비우면 위반이다. **한 문단에 수치를 몰아넣지 않는다.**

**2. 날조 방어 (4개 모두 필수)**

- **(a) 근거 News에 있는 표현 그대로 옮긴다. 새로 계산하지 않는다.** 단위 환산, 합산, 두 값을 나눠 비율을 만드는 것은 **기사에 없는 새 사실을 만드는 것**이다. 두 값을 쓰고 싶으면 **두 값을 그대로 나란히 쓴다.**
- **(b) 수치의 주체·시점·범위를 함께 옮긴다.** 누구의, 언제, 무엇에 대한 값인지가 빠지면 **맞는 숫자가 틀린 문장**이 된다.
- **(c) 목표·전망치와 실적치를 섞지 않는다.** 전망·목표·계획치는 그 성격을 문장에 명시하지 않으면 쓰지 않는다.
- **(d) 다른 이슈의 근거에서 수치를 끌어오지 않는다.** 그 이슈 `참고:` 줄의 News 안에 있는 값만 쓴다.
"""

# docs/planning.md "이슈별 참고뉴스 인라인 규약(옵션 C)" 절 1)번. 렌더·폴백·PE 인계
# 스펙(2), 3), 5))은 뺀다 — LLM의 출력 형식이 아니라 화면이 그 형식을 읽는 방법이다.
_CRITERIA_REPORT_INLINE_REFS = """\
- **마커 토큰**: 이슈(`###`) 블록의 **맨 마지막 줄**에 `참고:` 로 시작하는 한 줄을 둔다.
- **식별자**: 각 근거 News의 **uid**(표준 UUID 문자열)를 쓴다.
- **구분자**: uid 여러 개는 `, `(콤마+공백)로 나열한다.
- **위치**: 반드시 **시사점 문단 뒤, 블록 최하단 별도 줄**.
- **예시**:
  ```
  ### 우리금융, AI 신용평가 모델 도입
  우리금융이 …(흐름 분석 1문단)…
  …(시사점 문단)…
  참고: 3f2a1c9e-1b2c-4d5e-8f90-abc123456789, 7c8d9e0f-2a3b-4c5d-9e0f-def987654321
  ```
- **작성 편의 규약**: 시사점 문단을 "참고:"라는 낱말로 **시작하지 않는다**(마커 오인 방지). 마커는 항상 블록 최하단 한 줄로 하나만 둔다.
- **무결성**: 모든 이슈 블록 `참고:` 줄에 적힌 uid의 합집합이 이 보고서의 근거 기사 전체다. **입력으로 주어진 그 이슈의 근거 기사 uid만 쓴다** — 다른 이슈의 근거를 끌어오지 않는다.
"""

# docs/planning.md 「보고서/시사점 출처 기반 작성 원칙」 절.
_CRITERIA_REPORT_SOURCING = """\
보고서(Report)에 들어가는 모든 내용은 **반드시 실제로 수집된 기사(News)에 근거해야 하며, 없는 내용을 만들어내면 안 된다.** 원문에 없는 수치·인용·사건을 지어내거나 추측으로 채우지 않는다. 뒷받침할 기사가 없는 주장은 쓰지 않고, 대신 자료가 부족하다는 사실 자체를 기록한다.

모든 문단은 출처(원본 기사)를 항상 추적 가능해야 한다 — 근거로 연결한 기사가 그 출처 표기 역할을 겸한다.

**내부 식별자 참조 금지**: 다른 이슈나 근거 기사를 내부 식별자(pk, "인사이트 N번" 등)로 참조하지 않는다. 참조하려는 맥락은 그 자체로 이해되는 자기완결 산문으로 풀어쓴다.
"""

# docs/planning.md 「결산(월간) 보고서 주기」 확정 규칙 1번. 월간(5단계) 전용.
_CRITERIA_REPORT_MONTHLY_PERIOD = """\
이 보고서(월간 결산)의 대상 기간은 **달력 월 그대로다 — 1일부터 말일까지.**
"""

CRITERIA_TEXT_WEEKLY_REPORT = "\n".join([
    "## 보고서 표준 구조",
    _CRITERIA_REPORT_STRUCTURE,
    "## 이슈 제목 규칙",
    _CRITERIA_INSIGHT_TITLE_FORM,
    _CRITERIA_INSIGHT_TITLE_ENDING,
    "## 독자는 경영진이다",
    _CRITERIA_REPORT_AUDIENCE,
    "## 판단의 형식",
    _CRITERIA_REPORT_JUDGMENT,
    "## 정량 지표",
    _CRITERIA_REPORT_QUANT,
    "## 이슈별 참고뉴스 인라인 규약",
    _CRITERIA_REPORT_INLINE_REFS,
    "## 출처 기반 작성 원칙",
    _CRITERIA_REPORT_SOURCING,
])

CRITERIA_TEXT_MONTHLY_REPORT = "\n".join([
    CRITERIA_TEXT_WEEKLY_REPORT,
    "## 결산(월간) 보고서 기간 규칙",
    _CRITERIA_REPORT_MONTHLY_PERIOD,
])


def _build_report_system_prompt(period_label: str, criteria_text: str) -> str:
    """4, 5단계 시스템 프롬프트. 3단계와 달리 등록 대장을 넣지 않는다(이 단계는
    태깅을 하지 않는다) — 2단계와 같은 이유(설계). cache_control을 달지 않는다(설계
    7-(b))."""
    return f"""당신은 AI Market Watch 프로젝트에서, 확정된 이슈(Insight) 목록을 읽고 {period_label} 보고서 초안을 작성합니다.

프로젝트 관심사는 국내 금융권(은행·보험사)의 AI/AX 도입 동향, 그리고 그와 연결된 AI 기업 동향입니다. 아래 기준을 원문 그대로 적용하세요. 기준을 요약하거나 바꾸지 마세요.

<판정_기준>
{criteria_text}
</판정_기준>

임무: 아래 사용자 메시지로 주어지는 <입력_이슈> 목록을 읽고 {period_label} 보고서를 작성하세요. 각 이슈는 id와 등급과 분석과 시사점, 그리고 근거 기사(News) 목록(uid 포함)을 갖고 있습니다.

아래 스키마로 응답하세요.
- overview: 「주요 동향」. 위 "주요 동향 작성 규칙"을 그대로 따르세요.
- content: 「주요 이슈」. 이슈 블록을 상한 5건, 하한 없이 담으세요. 각 블록은 `### 이슈 제목` + 흐름 분석 + 시사점 + `참고: <uid>, ...` 규약 줄로 구성합니다. 이슈 제목은 위 "이슈 제목 규칙"을 그대로 따르세요. 참고 줄의 uid는 반드시 <입력_이슈>에 주어진 그 이슈의 근거 기사 uid만 쓰세요.
- content_keep: 방금 쓴 content 전체를 줄 단위로(제목 줄, 문장, `참고:` 줄) 순서대로 셀 때(1부터), 축약본(부연 설명을 뺀 핵심만 남긴 버전)에 남길 번호를 배열로 적으세요. 시사점 문단(각 이슈 블록의 마지막 문단)의 번호는 넣지 마세요 — 축약본에는 흐름 분석의 핵심 사실만 남깁니다. `### 이슈 제목` 줄과 `참고:` 줄은 번호를 안 넣어도 코드가 자동으로 포함하니 신경 쓰지 마세요.

🔴 보고서 제목은 여기서 만들지 않습니다. 응답에 제목을 포함하지 마세요.
"""


OUTPUT_SCHEMA_REPORT = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "content": {"type": "string"},
        # 🔴 2026-09-17 신설 — 축약본 문장 번호 배열. 3단계와 같은 방식(모듈 상단
        # "축약본 공용 유틸" 절) — build_short_field()가 `참고:` 줄을 always_keep_prefix로
        # 강제 포함하므로 여기 번호가 안 들어가도 안전하다.
        "content_keep": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["overview", "content", "content_keep"],
    "additionalProperties": False,
}


def _build_report_user_message(insights) -> str:
    """대상 Insight 배치를 하나의 사용자 메시지로 조립한다(설계 7-(a), 건별 호출이
    아니다). 각 Insight의 근거 News를 uid와 함께 나열해, 모델이 `참고: <uid>` 규약
    줄을 실제 uid로 채울 수 있게 한다."""
    blocks = []
    for insight in insights:
        news_list = list(insight.news.order_by("published_at"))
        news_lines = "\n".join(
            f"  - uid={n.uid} [{timezone.localtime(n.published_at):%Y-%m-%d}] {n.title}"
            for n in news_list
        ) or "  없음"
        blocks.append(
            f"[id={insight.pk}] {insight.title}\n"
            f"등급: {insight.grade}\n"
            f"분석:\n{insight.content}\n\n"
            f"시사점:\n{insight.implication}\n\n"
            f"근거 기사:\n{news_lines}"
        )
    return "<입력_이슈>\n" + "\n\n---\n\n".join(blocks) + "\n</입력_이슈>"


def _parse_report_response(response) -> dict:
    """구조화 출력을 파싱한다. classify_news용 _parse_response()와 같은 방식으로
    json.loads()만 쓴다(문자열 매칭 금지, SDK 권고)."""
    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise LLMJudgmentError(
            f"보고서 응답에 text 블록이 없어요(stop_reason={response.stop_reason})."
        )
    try:
        data = json.loads(text_block.text)
    except json.JSONDecodeError as exc:
        raise LLMJudgmentError(f"보고서 응답 JSON 파싱에 실패했어요: {exc}") from exc

    usage = response.usage
    data["_usage"] = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return data


def _generate_report(insights, period_label: str, criteria_text: str) -> dict:
    client = _get_client()
    try:
        response = client.messages.create(
            model=settings.BEDROCK_MODEL_SMART,
            max_tokens=8192,
            system=_build_report_system_prompt(period_label, criteria_text),
            messages=[{"role": "user", "content": _build_report_user_message(insights)}],
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA_REPORT}},
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
        logger.error("%s 보고서 작성 중 구조적 오류(인증/권한/리소스): %s", period_label, exc)
        raise LLMStructuralError(str(exc)) from exc
    except anthropic.RateLimitError as exc:
        logger.warning("%s 보고서 작성 중 rate limit에 걸렸어요: %s", period_label, exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIConnectionError as exc:
        logger.warning("%s 보고서 작성 중 네트워크 오류: %s", period_label, exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIStatusError as exc:
        logger.warning("%s 보고서 작성 중 API 오류(status=%s): %s", period_label, exc.status_code, exc)
        raise LLMJudgmentError(str(exc)) from exc
    else:
        return _parse_report_response(response)


def generate_weekly_report(insights) -> dict:
    """대상 주의 Insight 배치를 한 번에 판정해 주간 보고서 초안을 만든다.

    Returns:
        {"overview": ..., "content": ..., "_usage": {...}}
    Raises:
        LLMStructuralError, LLMJudgmentError — generate_insights()와 같다.
    """
    return _generate_report(insights, "주간", CRITERIA_TEXT_WEEKLY_REPORT)


def generate_monthly_report(insights) -> dict:
    """대상 월의 Insight 배치를 한 번에 판정해 월간 결산 보고서 초안을 만든다.
    반환값·예외는 generate_weekly_report()와 같다."""
    return _generate_report(insights, "월간 결산", CRITERIA_TEXT_MONTHLY_REPORT)


# ============================================================================
# 교보 소식(뉴스룸) 축 2단계 필터 — docs/planning.md "뉴스룸" 절 12-2가 정본.
#
# 🔴 조사 축과 결이 다른 것 셋 (12-2 (a)(b)(d)).
#   - 호출 단위: 배치 전체 1호출이다(insight/weekly/monthly와 같다) — 파급력 순위와
#     중복 묶기가 다른 기사와 비교해야만 판정되기 때문이다.
#   - 휴먼 인 더 루프가 없다 — 판정 결과를 RunProposal 같은 중간 그릇 없이
#     NewsroomArticle에 바로 쓴다. 되돌릴 수 있고(filter_status 한 칸을 바꿀 뿐,
#     행을 지우지 않는다) 채널로 바로 나가지도 않아서다(ROOM-002까지가 끝).
#   - 🔴 판정 기준 원문을 코드에 두지 않는다. 호출부(services/runner.py)가
#     Newsroom.filter_prompt를 그대로 읽어 이 함수에 넘긴다 — 뉴스룸은 채널이
#     여럿일 수 있어 프롬프트가 데이터일 수밖에 없다(조사 축 "프롬프트는 코드에
#     둔다" 결정과 갈리는 지점, 같은 문서 5번 말미).
#
# 캐싱은 켜지 않는다(12-2 (e)) — 호출이 1회면 캐시 읽기가 0회인데 캐시 쓰기 단가가
# 두 배라 비용만 오른다.
# ============================================================================


def _build_newsroom_filter_system_prompt(filter_prompt: str) -> str:
    """뉴스룸 2단계 시스템 프롬프트. 판정 기준 원문(filter_prompt)은 호출부가
    Newsroom.filter_prompt를 그대로 읽어 넘긴 것을 그대로 삽입한다 — 요약·재서술
    없이(조사 축 6-(A) "요약이 아니라 선택이다"와 같은 원칙, DB가 이미 그 발췌·해석을
    끝낸 원문을 들고 있다).

    f-string 삽입이라 filter_prompt 안에 중괄호가 섞여 있어도 안전하다 — 파이썬은
    소스 코드의 `{expr}` 리터럴 자리만 보고 그 안에 들어가는 런타임 값의 내용은
    보지 않는다(프로젝트 "프롬프트 치환은 .format()이 아니라 .replace()" 원칙이
    경고하는 것은 반대 방향, 즉 템플릿 문자열 자체에 `.format(**kwargs)`를 쓰는
    경우다 — 여기서는 해당하지 않는다)."""
    return f"""당신은 교보생명 그룹 구성원이 읽는 사내 소식 채널("교보 소식")의 편집자입니다. 아래 지침 원문을 그대로 적용해, 주어진 기사 배치 중 브리핑에 실을 기사를 고르고 순위를 매기세요. 지침을 요약하거나 바꾸지 마세요.

<지침_원문>
{filter_prompt}
</지침_원문>

임무: 아래 <입력_기사> 목록의 기사 전부에 대해, 위 지침의 1단계 몫(요약, 비즈니스 파급력 순위, 중복 기사 묶기, 중요도 낮음, 제외 리스트, 민감 내용)을 적용해 판정하세요. 기간·유료 구독·죽은 링크·본문 실체 같은 항목은 이미 코드가 걸러낸 뒤라 신경 쓰지 마세요.

각 기사에 대해 빠짐없이 아래 스키마로 응답하세요.
- id: <입력_기사>의 각 기사 앞 [id=N]의 N.
- status: 브리핑에 실을 가치가 있으면 "passed", 지침에 걸려 제외해야 하면 "rejected".
- summary: status가 "passed"면 1~2문장 요약. "rejected"면 빈 문자열로 두세요.
- impact_rank: status가 "passed"인 기사끼리 비즈니스 파급력 순으로 매긴 순위(1이 가장 크다). 같은 순위를 쓰지 마세요. "rejected"거나, "passed"이지만 아래 duplicate_of_id로 다른 기사에 묶이는 기사는 0으로 두세요(순위는 대표 기사에만 매깁니다).
- duplicate_of_id: 이 기사가 다른 기사와 같은 사건을 다루고 있으면, 그 사건의 대표로 삼을 기사의 id를 적으세요. 이 기사 자신이 대표(또는 중복이 없음)면 0으로 두세요. 묶인 기사도 status는 "passed"입니다 — 중복은 제외가 아닙니다.
"""


OUTPUT_SCHEMA_NEWSROOM_FILTER = {
    "type": "object",
    "properties": {
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "status": {"type": "string", "enum": ["passed", "rejected"]},
                    "summary": {"type": "string"},
                    "impact_rank": {"type": "integer"},
                    "duplicate_of_id": {"type": "integer"},
                },
                "required": ["id", "status", "summary", "impact_rank", "duplicate_of_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["articles"],
    "additionalProperties": False,
}


def _build_newsroom_filter_user_message(articles) -> str:
    """배치 전체를 하나의 사용자 메시지로 조립한다(12-2 (a), 건별 호출이 아니다).
    id는 NewsroomArticle.pk를 그대로 쓴다 — _build_insight_user_message()와 같은
    방식(응답의 id/duplicate_of_id를 별도 해석 없이 그 pk로 바로 찾는다)."""
    blocks = []
    for article in articles:
        blocks.append(
            f"[id={article.pk}] {article.title}\n"
            f"발행일: {timezone.localtime(article.published_at):%Y-%m-%d}\n"
            f"매체: {article.source_domain}\n\n"
            f"{article.body}"
        )
    return "<입력_기사>\n" + "\n\n---\n\n".join(blocks) + "\n</입력_기사>"


def _parse_newsroom_filter_response(response) -> dict:
    """구조화 출력을 파싱한다. _parse_insight_response()와 같은 방식(json.loads()만,
    문자열 매칭 금지)이다."""
    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise LLMJudgmentError(
            f"뉴스룸 필터 응답에 text 블록이 없어요(stop_reason={response.stop_reason})."
        )
    try:
        data = json.loads(text_block.text)
    except json.JSONDecodeError as exc:
        raise LLMJudgmentError(f"뉴스룸 필터 응답 JSON 파싱에 실패했어요: {exc}") from exc

    usage = response.usage
    data["_usage"] = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return data


def filter_newsroom_articles(articles, filter_prompt: str) -> dict:
    """뉴스룸 기사 배치를 한 번에 판정한다. 이 함수는 LLM을 부르고 결과를 반환할
    뿐 DB에 아무것도 쓰지 않는다(generate_insights()와 같은 계약) — 저장은
    호출부(services/runner.py _run_newsroom_filter())가 한다.

    모델은 BEDROCK_MODEL_SMART다(12-2 (e), 전 단계 Haiku 확정을 그대로 따른다 —
    그 설정 키가 지금 Haiku를 가리키는 것이 2026-09-15 사용자 확정이다).

    Args:
        articles: 판정할 NewsroomArticle 목록(filter_status=pending 전량).
        filter_prompt: 그 뉴스룸의 Newsroom.filter_prompt 원문.

    Returns:
        {"articles": [...], "_usage": {...}} — articles의 각 원소는
        id/status/summary/impact_rank/duplicate_of_id.

    Raises:
        LLMStructuralError: 인증·권한·리소스 오류.
        LLMJudgmentError: 그 밖의 실패. 호출 1회라 이어하기가 없다 — 실패하면 이
            배치는 처음부터 다시 돈다.
    """
    client = _get_client()
    try:
        response = client.messages.create(
            model=settings.BEDROCK_MODEL_SMART,
            max_tokens=8192,
            system=_build_newsroom_filter_system_prompt(filter_prompt),
            messages=[{"role": "user", "content": _build_newsroom_filter_user_message(articles)}],
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA_NEWSROOM_FILTER}},
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
        logger.error("뉴스룸 필터 중 구조적 오류(인증/권한/리소스): %s", exc)
        raise LLMStructuralError(str(exc)) from exc
    except anthropic.RateLimitError as exc:
        logger.warning("뉴스룸 필터 중 rate limit에 걸렸어요: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIConnectionError as exc:
        logger.warning("뉴스룸 필터 중 네트워크 오류: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIStatusError as exc:
        logger.warning("뉴스룸 필터 중 API 오류(status=%s): %s", exc.status_code, exc)
        raise LLMJudgmentError(str(exc)) from exc
    else:
        return _parse_newsroom_filter_response(response)


# ============================================================================
# 교보 소식(뉴스룸) 축 3단계 발송문 — docs/planning.md "뉴스룸" 절 12-3이 정본.
#
# 🔴 2단계와 같은 것 — 배치 전체 1호출, 모델은 BEDROCK_MODEL_SMART(지금 Haiku를
# 가리키는 것이 2026-09-15 사용자 확정), 캐싱을 켜지 않는다(호출 1회면 캐시 읽기가
# 0회인데 캐시 쓰기 단가가 두 배라 비용만 오른다), 판정 기준 원문을 코드가 아니라
# Newsroom.compose_prompt에서 그대로 읽는다(뉴스룸은 채널마다 프롬프트가 다를 수
# 있어 프롬프트가 데이터일 수밖에 없다).
#
# 🔴 2단계와 다른 것 — 입력이 "판정할 기사 전량"이 아니라 "이미 통과해 순위가
# 매겨진 기사"(filter_status=passed, duplicate_of가 None)뿐이고, 출력이 기사별
# 판정 배열이 아니라 조립된 메시지 본문 하나(body)다. 순서는 호출부
# (services/runner.py _run_newsroom_compose())가 이미 impact_rank로 정렬해
# 넘긴다 — 이 함수는 순서를 다시 매기지 않는다(12-3 (a) "3단계가 순서를 다시
# 정하지 않는다").
# ============================================================================


def _build_newsroom_compose_system_prompt(compose_prompt: str) -> str:
    """뉴스룸 3단계 시스템 프롬프트. compose_prompt(호출부가 Newsroom.compose_prompt를
    그대로 읽어 넘긴 것)를 요약·재서술 없이 그대로 삽입한다 —
    _build_newsroom_filter_system_prompt()와 같은 이유(f-string 삽입이라 원문에
    중괄호가 섞여 있어도 안전하다)."""
    return f"""당신은 교보생명 그룹 구성원이 읽는 사내 소식 채널("교보 소식")의 편집자입니다. 아래 지침 원문을 그대로 적용해, 이미 통과 판정을 받은 기사 목록으로 하나의 Slack 메시지 본문을 작성하세요. 지침을 요약하거나 바꾸지 마세요.

<지침_원문>
{compose_prompt}
</지침_원문>

임무: 아래 <입력_기사> 목록은 이미 2단계에서 통과 판정을 받았고 비즈니스 파급력 순위 순서 그대로 나열돼 있습니다. 순서를 다시 매기지 마세요. 목록에 있는 기사를 하나도 빠뜨리지 말고, 각 기사의 제목·요약·링크를 위 지침의 [출력 템플릿]에 맞춰 하나의 메시지 본문으로 조립하세요.

아래 스키마로 응답하세요.
- body: 완성된 Slack 메시지 본문 전체 하나.
"""


OUTPUT_SCHEMA_NEWSROOM_COMPOSE = {
    "type": "object",
    "properties": {
        "body": {"type": "string"},
    },
    "required": ["body"],
    "additionalProperties": False,
}


def _build_newsroom_compose_user_message(articles) -> str:
    """이미 통과·순위가 매겨진 기사 배치를 하나의 사용자 메시지로 조립한다. 순서는
    호출부가 이미 impact_rank로 정렬해 넘긴 순서를 그대로 따른다(12-3 (a))."""
    blocks = []
    for article in articles:
        blocks.append(
            f"[순위 {article.impact_rank}] {article.title}\n"
            f"요약: {article.summary}\n"
            f"링크: {article.url}"
        )
    return "<입력_기사>\n" + "\n\n---\n\n".join(blocks) + "\n</입력_기사>"


def _parse_newsroom_compose_response(response) -> dict:
    """구조화 출력을 파싱한다. _parse_newsroom_filter_response()와 같은 방식이다
    (json.loads()만, 문자열 매칭 금지)."""
    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise LLMJudgmentError(
            f"뉴스룸 발송문 응답에 text 블록이 없어요(stop_reason={response.stop_reason})."
        )
    try:
        data = json.loads(text_block.text)
    except json.JSONDecodeError as exc:
        raise LLMJudgmentError(f"뉴스룸 발송문 응답 JSON 파싱에 실패했어요: {exc}") from exc

    usage = response.usage
    data["_usage"] = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return data


def compose_newsroom_message(articles, compose_prompt: str) -> dict:
    """통과·순위가 매겨진 뉴스룸 기사 배치로 발송문 본문 하나를 만든다. 이 함수는
    LLM을 부르고 결과를 반환할 뿐 DB에 아무것도 쓰지 않는다(filter_newsroom_articles()와
    같은 계약) — 저장과 코드 검증은 호출부(services/runner.py
    _run_newsroom_compose())가 한다.

    🔴 통과 0건이면 이 함수를 부르지 않는다(12-3 (a)) — 호출부가 그 경우 LLM을
    부르지 않고 코드로 고정 문구를 만든다. 이 함수는 articles가 최소 1건 있다고
    가정한다.

    모델은 BEDROCK_MODEL_SMART다(12-3 (g), 2단계와 같은 확정을 그대로 따른다).

    Args:
        articles: 발송문에 담을 NewsroomArticle 목록. impact_rank 순으로 이미
            정렬돼 있어야 한다(호출부 책임).
        compose_prompt: 그 뉴스룸의 Newsroom.compose_prompt 원문.

    Returns:
        {"body": "...", "_usage": {...}}.

    Raises:
        LLMStructuralError: 인증·권한·리소스 오류.
        LLMJudgmentError: 그 밖의 실패. 호출 1회라 이어하기가 없다 — 실패하면 이
            배치는 처음부터 다시 돈다.
    """
    client = _get_client()
    try:
        response = client.messages.create(
            model=settings.BEDROCK_MODEL_SMART,
            max_tokens=8192,
            system=_build_newsroom_compose_system_prompt(compose_prompt),
            messages=[{"role": "user", "content": _build_newsroom_compose_user_message(articles)}],
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA_NEWSROOM_COMPOSE}},
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
        logger.error("뉴스룸 발송문 작성 중 구조적 오류(인증/권한/리소스): %s", exc)
        raise LLMStructuralError(str(exc)) from exc
    except anthropic.RateLimitError as exc:
        logger.warning("뉴스룸 발송문 작성 중 rate limit에 걸렸어요: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIConnectionError as exc:
        logger.warning("뉴스룸 발송문 작성 중 네트워크 오류: %s", exc)
        raise LLMJudgmentError(str(exc)) from exc
    except anthropic.APIStatusError as exc:
        logger.warning("뉴스룸 발송문 작성 중 API 오류(status=%s): %s", exc.status_code, exc)
        raise LLMJudgmentError(str(exc)) from exc
    else:
        return _parse_newsroom_compose_response(response)

# ⚡ 양자택일

메인 화면에서 궁금한 키워드를 입력하면 7개의 맞춤 양자택일이 생성되고 바로 플레이할 수 있는 선택형 웹서비스입니다. 준비된 공식 콘텐츠도 주제별로 플레이할 수 있으며, 키워드 게임 완료 후 **답변 기반 MBTI 캐릭터·결정적 선택·선택 사용설명서·4축 나침반**을 확인할 수 있습니다.

> 이 결과는 재미를 위한 콘텐츠이며 실제 성격이나 심리 상태를 진단하지 않습니다.

---

## 개발 스토리

### 배경

밸런스게임(Balance Game)은 서로 대립되는 두 선택지를 제시하고 사용자가 하나를 선택하는 소셜 콘텐츠입니다. 기존의 단순 투표 비율 표시에서 한 발 더 나아가, **사용자가 선택한 비율에 따라 LEGENDARY_MINORITY → OVERWHELMING 7단계 희귀도 등급**을 부여하고 등급에 맞는 해석 문구를 제공하는 서비스를 기획했습니다.

### v1 → v2 전환

초기 MVP(v1)는 Django 4.2 + 단순 모델로 시작했습니다. 사용자 요구사항이 구체화되면서 v2에서 다음을 전면 재설계했습니다.

| 구분 | v1 | v2 |
|------|----|----|
| Python | 3.9 | **3.12** |
| Django | 4.2 | **5.2 LTS** |
| 프론트엔드 | 순수 CSS (자체 구현) | **Bootstrap 5** |
| 모델 | BalanceGame + Choice (2개) | **Category, GameSet, Question, Choice, Vote, ResultTemplate** |
| 결과 | 투표 비율만 표시 | **문항별 7단계 등급 + 답변 기반 MBTI 캐릭터·선택 사용설명서** |
| 플레이 흐름 | 랜덤 질문 반복 가능 | **선택 후 자동 진행 + 이전 선택 수정 + 진행률·선택 기록** |
| 사용자 기능 | 없음 | **메인 키워드 즉석 게임 + 회원가입·로그인 + 플레이 기록** |
| 콘텐츠 안전 | 없음 | **금칙어 차단 + 근거 URL + 관리자 사전 승인** |
| 환경변수 | 하드코딩 | **django-environ (.env)** |
| 공식 콘텐츠 | 질문 단위 샘플 | **7개 주제 × 각 7문항** |
| 진입 경험 | 메인으로 즉시 이동 | **전체 화면 소개 + 클릭 전환 애니메이션** |
| 테스트 | 없음 | **71개 테스트 (100% 통과)** |

### 핵심 설계 결정

#### 1. 서비스 계층 분리 (`services.py`)

공식 질문의 투표 결과 생성 로직은 뷰에서 분리해 `ResultGenerator` 추상 인터페이스와 `TemplateResultGenerator` 구현으로 관리합니다. 키워드 즉석 게임은 별도의 `openai_mbti_analyzer.py`에서 답변 기록을 분석하며, OpenAI 호출에 실패하면 로컬 분석기로 자동 전환합니다.

```
공식 질문 ─ ResultGenerator ─ TemplateResultGenerator
즉석 게임 ─ OpenAI MBTI 분석기 ─ 실패 시 로컬 분석기
```

#### 2. 등급 경계값 설계

7단계 등급의 경계값이 겹치거나 누락되지 않도록 `get_grade()` 함수에 명시적으로 구현하고 **14가지 경계값 단위 테스트**로 검증했습니다.

```
0% ≤ x ≤ 15%         → LEGENDARY_MINORITY (전설의 소수파)
15% < x ≤ 30%        → RARE               (희귀한 선택)
30% < x ≤ 44%        → MINORITY           (소수 취향)
44% < x < 56%        → BALANCED           (팽팽한 선택)
56% ≤ x ≤ 69%        → MAJORITY           (공감받는 선택)
69% < x ≤ 84%        → POPULAR            (인기 선택)
84% < x ≤ 100%       → OVERWHELMING       (압도적인 선택)
```

#### 3. 동시성 안전 투표 집계

`F('vote_count') + 1`과 `transaction.atomic()`을 함께 사용해 다수의 동시 요청이 들어와도 집계 값이 유실되지 않도록 처리했습니다.

```python
with transaction.atomic():
    vote, created = Vote.objects.get_or_create(
        question=question,
        session_key=session_key,
        defaults={'choice': choice},
    )
    if created:
        Choice.objects.filter(pk=choice.pk).update(
            vote_count=F('vote_count') + 1
        )
```

#### 4. 중복 투표 방지 이중 잠금

- **애플리케이션 계층**: `get_or_create` + 세션 키 확인
- **DB 계층**: `UniqueConstraint(fields=['question', 'session_key'])`

두 계층 모두에서 막아 동시 요청 시에도 중복 투표가 발생하지 않습니다.

#### 5. 안전한 템플릿 포맷팅

`ResultTemplate`의 문구에 알 수 없는 변수가 포함되어도 서버 오류가 발생하지 않도록 `_SafeDict`를 활용한 `safe_format()` 함수를 구현했습니다.

#### 6. 사용자 제작 콘텐츠 사전 검수

회원은 하나의 주제에 7~10개의 질문을 구성해 제출할 수 있습니다.

- 성인·음란, 혐오·차별, 자해·불법 행동 관련 금칙어를 제출 단계에서 차단
- 사실·통계·의학·금융 주장은 `사실·정보형`과 검증 자료 URL 필수
- 모든 사용자 제작 세트는 `검수 대기`로 저장되며 승인 전에는 목록·랜덤·투표 경로에서 제외
- 관리자 승인 시에만 세트의 문항을 일괄 활성화
- 관리자 반려 시 문항 비공개 유지 및 반려 사유 기록

#### 7. 주제 완료 유형 분석

주제의 모든 문항을 완료하면 A/B 응답 분포와 일관성을 기준으로 선택 유형을 제공합니다.

- `000님은 ??유형입니다` 형식의 개인화된 결과
- 웃음 중심의 코믹 해석과 수치 중심의 패턴 분석 탭
- A/B 선택 횟수·비율, 선택 집중도, 키워드 제공
- 실제 성격이나 심리 진단이 아니라는 안내를 결과에 명시

#### 8. 키워드 기반 질문 자동 생성

메인 화면의 검색형 입력창에 키워드 1~5개를 입력하면 7개의 A/B 질문을 만들고 로그인 없이 바로 플레이합니다.

- `OPENAI_API_KEY`가 있으면 OpenAI Responses API의 구조화 출력으로 문항 생성
- 기본 모델·타임아웃이 설정되어 있어 발급받은 키 한 줄만 추가하면 AI 생성 활성화
- 키가 없거나 API가 일시적으로 실패하면 기존 로컬 생성기로 자동 대체
- API 키는 Django 서버에서만 읽으며 브라우저 HTML·JavaScript·응답에는 전달하지 않음
- 메인 첫 화면 중앙에 큰 키워드 검색창과 추천 주제 칩 배치
- 생성 게임은 사용자 세션에만 임시 저장되고 공개 게임이나 투표 DB에는 저장되지 않음
- 선택 직후 다음 문항으로 이동하고 뒤로가기로 이전 답변 수정
- 7문항 완료 후 답변을 근거로 한 MBTI 캐릭터·결정적 선택·선택 사용설명서·4축 나침반 제공
- AI는 E/I, S/N, T/F, J/P 축을 모두 포함하는 문항과 선택지별 성향 코드를 구조화 데이터로 생성
- 로컬 생성기는 공통 16개 관점과 카테고리별 21개 상황을 조합하고 동일한 성향 메타데이터를 부여
- 키워드가 여러 개면 키워드끼리 직접 비교하는 문항도 포함
- AI 지침, 구조화 스키마, 생성 결과 필터로 단계별 안전성 확인
- 성인·유해 키워드와 검증이 필요한 단정 표현은 생성 전에 차단
- OpenAI 연결 시 세션별 생성 대기 시간을 적용해 중복 호출을 제한

#### 9. 자동 진행과 이전 선택 수정

- A/B 선택 직후 같은 주제의 다음 미완료 문항으로 자동 이동
- 현재 문항 번호, 전체 문항 수, 완료 문항 수를 진행 바로 표시
- `뒤로가기 · 이전 선택 수정` 버튼으로 직전 투표 취소
- 투표 취소 시 선택지 집계도 함께 되돌리고 다시 선택 가능
- 최종 유형 결과에서도 마지막 선택으로 돌아가 수정 가능

---

## 프로젝트 구조

```
game/
├── .env                         # 환경변수 (git 제외)
├── .env.example                 # 환경변수 예시
├── pyproject.toml
├── requirements.txt
├── manage.py
├── game/                        # Django 프로젝트 설정
│   ├── settings.py
│   └── urls.py
├── 양자택일/                     # 메인 앱
│   ├── models.py                # 게임·투표·사용자 제작 세트 모델
│   ├── moderation.py            # 금칙어 및 검증 필요 표현 검사
│   ├── official_content.py      # 7개 공식 주제의 추가 문항
│   ├── question_generator.py    # OpenAI/로컬 생성기 선택과 자동 대체
│   ├── openai_question_generator.py # 구조화 출력 기반 AI 질문 생성
│   ├── openai_mbti_analyzer.py  # 답변 기반 AI MBTI 캐릭터 분석과 로컬 대체
│   ├── services.py              # 등급 판정, 결과 생성, 투표 처리
│   ├── forms.py                 # 투표·회원·게임 제작 폼
│   ├── views.py                 # 플레이·회원·제작·기록 뷰
│   ├── urls.py                  # 서비스 URL 패턴
│   ├── admin.py                 # 관리자 인터페이스
│   ├── tests.py                 # 71개 자동 테스트
│   └── management/
│       └── commands/
│           └── seed_data.py     # 샘플 데이터 생성 커맨드
├── templates/
│   ├── base.html                # Bootstrap 5 공통 레이아웃
│   ├── welcome.html             # 클릭 전환 애니메이션 인트로
│   ├── index.html               # 메인 페이지
│   ├── games/
│   │   ├── instant_play.html    # 키워드 즉석 게임 플레이
│   │   ├── instant_result.html  # 즉석 게임 MBTI 캐릭터·선택 사용설명서
│   │   ├── list.html            # 게임 목록
│   │   ├── detail.html          # 질문 상세 (투표)
│   │   ├── result.html          # 투표 결과
│   │   ├── progress.html        # 내 플레이 진행률·최근 선택
│   │   ├── create.html          # 7~10문항 게임 제작
│   │   ├── my_creations.html    # 내 제출·검수 현황
│   │   ├── set_detail.html      # 공식·사용자 제작 주제 플레이
│   │   └── set_result.html      # 주제 완료 유형·코믹·패턴 분석
│   ├── registration/
│   │   ├── login.html           # 로그인
│   │   └── signup.html          # 회원가입
│   └── categories/
│       └── list.html            # 카테고리별 목록
└── static/
    ├── css/main.css             # 커스텀 스타일 (희귀도 배지 등)
    ├── images/og-yangjatagil.png # 양자택일 SNS 링크 미리보기 이미지
    └── js/main.js               # 인트로·분석 탭·클립보드 상호작용
```

---

## URL 구조

| URL | 뷰 | 설명 |
|-----|----|------|
| `/` | `WelcomeView` | 클릭 전환 애니메이션 인트로 |
| `/home/` | `IndexView` | 메인 페이지 |
| `/instant-game/generate/` | `InstantGameGenerateView` | 키워드로 세션 게임 생성 |
| `/instant-game/<번호>/` | `InstantGamePlayView` | 즉석 게임 문항 플레이 |
| `/instant-game/<번호>/answer/` | `InstantGameAnswerView` | 즉석 게임 선택 저장·자동 진행 |
| `/instant-game/result/` | `InstantGameResultView` | 즉석 게임 MBTI 캐릭터·선택 사용설명서 |
| `/games/` | `GameListView` | 전체 게임 목록 |
| `/games/random/` | `RandomGameView` | 랜덤 게임 이동 |
| `/games/<id>/` | `QuestionDetailView` | 질문 상세 + 투표 |
| `/games/<id>/vote/` | `VoteView` | 투표 처리 (POST 전용) |
| `/games/<id>/result/` | `ResultView` | 결과 페이지 |
| `/my-results/` | `ProgressView` | 내 진행률·카테고리별 현황·최근 선택 |
| `/games/create/` | `GameSetCreateView` | 7~10문항 사용자 게임 제작 |
| `/games/create/generate/` | `QuestionDraftGenerateView` | 키워드 기반 질문 초안 생성 |
| `/my-games/` | `MyGameSetListView` | 내 제출 및 검수 상태 |
| `/topics/<id>/` | `PublicGameSetDetailView` | 승인된 공식·사용자 제작 주제 플레이 |
| `/topics/<id>/start/` | `GameSetStartView` | 닉네임 저장 후 주제 시작 |
| `/topics/<id>/result/` | `GameSetResultView` | 주제 완료 유형 분석 |
| `/topics/<id>/undo/` | `GameSetUndoLastVoteView` | 마지막 선택 취소 후 재선택 |
| `/accounts/signup/` | `SignupView` | 회원가입 |
| `/accounts/login/` | `LoginView` | 로그인 |
| `/accounts/logout/` | `LogoutView` | 로그아웃 (POST) |
| `/categories/<slug>/` | `CategoryListView` | 카테고리별 목록 |
| `/admin/` | Django Admin | 사용자 게임 검수·승인·반려 |

---

## 결과 페이지 제공 항목

- 질문 제목 및 내 선택
- 희귀도 배지 (7단계 색상 구분)
- 결과 제목 + 한 줄 요약
- 재미있는 결과 해석 (3~5문장)
- 선택지별 투표 비율 + 프로그레스 바
- 전체 참여자 수
- 성향 키워드 3개
- 공유 문구 + 클립보드 복사 버튼
- 다음 랜덤 게임 버튼

주제의 7~10개 문항을 모두 완료한 경우에는 다음 항목도 제공합니다.

- `닉네임님은 선택 유형입니다` 결과
- 코믹 해석 / 선택 패턴 분석 전환 탭
- A/B 선택 분포와 선택 집중도
- 전체 답변 모아보기

키워드 즉석 게임 7문항을 완료한 경우에는 다음 항목을 추가로 제공합니다.

- 선택한 답변과 문항별 성향 코드를 근거로 도출한 4자리 MBTI 캐릭터
- 숨은 본성을 요약한 코믹 타이틀과 3문장 이내의 분석
- 결과에 영향을 준 실제 답변 3개를 보여주는 `결정적 선택`
- 강점·주의할 함정·갈등 반응·함께 결정하기 편한 스타일·다음 선택 조언으로 구성된 `나의 선택 사용설명서`
- E/I·S/N·T/F·J/P별 선택 횟수를 보여주는 `4축 선택 나침반`
- 새로고침 시 API를 다시 호출하지 않는 세션 결과 캐시
- 공식 MBTI 검사나 심리 진단이 아닌 오락용 콘텐츠라는 안내

---

## 실행 방법

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 환경변수 설정
cp .env.example .env
# .env 파일에서 SECRET_KEY 수정 후 발급받은 OpenAI 키만 입력
# OPENAI_API_KEY=sk-발급받은_키

# 3. DB 마이그레이션
python manage.py migrate

# 4. 공식 데이터 생성 (7개 주제 × 7문항, 21개 결과 템플릿)
python manage.py seed_data

# 5. 관리자 계정 생성 (선택)
python manage.py createsuperuser

# 6. 개발 서버 실행
python manage.py runserver
```

`http://127.0.0.1:8000` 접속

---

## 테스트 실행

```bash
python manage.py test 양자택일 --verbosity=2
```

71개 자동 테스트는 다음 핵심 영역을 검증합니다.

1. 투표 저장 테스트
2. 중복투표 방지 테스트 (애플리케이션 레벨)
3. DB UniqueConstraint 제약 테스트
4. vote_count 증가 테스트
5. 중복 투표 시 vote_count 불변 테스트
6. 선택지 비율 계산 테스트
7. 0표 시 50% 반환 테스트
8. total_votes 0 반환 테스트
9. 등급 경계값 14가지 테스트
10. 잘못된 percentage 예외 테스트
11. 기본 결과 문구 폴백 테스트
12. 비활성 질문 투표 404 테스트
13. 비활성 질문 상세 404 테스트
14. GET 요청 투표 차단 테스트
15. 다중 세션 집계 정확성 테스트
16. 투표 후 등급/비율 정확성 테스트
17. 반복 없는 랜덤·다음 게임 테스트
18. 플레이 진행률 집계 테스트
19. 회원가입·로그인·로그아웃 테스트
20. 게임 제작 로그인 보호 테스트
21. 사용자 제작 7~10문항 제한 테스트
22. 성인 콘텐츠 제출 차단 테스트
23. 사실형 콘텐츠 근거 URL 검증 테스트
24. 검증되지 않은 강한 주장 차단 테스트
25. 사용자별 제작 목록 접근 범위 테스트
26. 검수 대기 콘텐츠 비공개 테스트
27. 관리자 승인·반려 및 공개 전환 테스트
28. 양자택일 인트로·메인 분리 테스트
29. 공식 데이터 7개 주제 × 7문항 및 재실행 안전성 테스트
30. 닉네임 기반 주제 유형 결과 테스트
31. 코믹 해석·패턴 분석 렌더링 테스트
32. 미완료 주제 결과 접근 차단 테스트
33. 마지막 응답 후 주제 결과 자동 이동 테스트
34. 자동 생성 로그인 보호 테스트
35. 키워드 기반 7~10문항 생성 테스트
36. 성인·검증 필요 키워드 차단 테스트
37. 자동 생성 시 데이터 미저장 테스트
38. CSRF 보호 요청 테스트
39. 선택 후 다음 문항 자동 이동 테스트
40. 문항 진행률·뒤로가기 버튼 테스트
41. 선택 취소 시 투표 집계 복원 테스트
42. 최종 결과에서 마지막 선택 수정 테스트
43. API 키 설정 시 OpenAI 생성기 전환 테스트
44. OpenAI 장애 시 로컬 생성기 자동 대체 테스트
45. OpenAI 구조화 출력·문항 수·스키마 검증 테스트
46. AI 생성 결과의 성인 콘텐츠 사후 차단 테스트
47. 메인 키워드 검색 UI 테스트
48. 비회원 세션 게임 생성·DB 미저장 테스트
49. 즉석 게임 유해 키워드 차단 테스트
50. 즉석 게임 선택 후 자동 이동 테스트
51. 즉석 게임 이전 답변 수정 테스트
52. 미완료 결과 접근 차단 테스트
53. 즉석 게임 결정적 선택·사용설명서·4축 나침반 렌더링 테스트
54. 즉석 게임 답변 CSRF 쿠키·폼 흐름 테스트
55. 만료된 CSRF 상태 자동 복구 테스트
56. MBTI 축 메타데이터가 포함된 구조화 문항 생성 테스트
57. 답변 성향 코드 기반 로컬 MBTI 분석 테스트
58. OpenAI 구조화 결과 분석·유해 결과 사후 차단 테스트
59. 즉석 결과 분석 세션 캐시 테스트

---

## AI 결과 분석

키워드 즉석 게임을 완료하면 `openai_mbti_analyzer.py`가 질문, 사용자가 고른 선택지, 문항의 MBTI 축과 선택 성향 코드만 전달해 구조화된 분석 결과를 받습니다. 닉네임, 세션 키, IP 같은 개인정보는 OpenAI에 전달하지 않습니다.

- 16개 MBTI 코드 중 하나, 코믹 타이틀, 3문장 이내 설명과 사용설명서 5개 항목으로 응답 스키마를 제한
- 최소 두 개의 실제 선택을 분석 근거로 사용
- 모욕·혐오·민감정보 추론·정신건강 진단 표현을 프롬프트와 사후 필터로 차단
- API 키가 없거나 호출·응답 검증에 실패하면 같은 성향 코드를 집계하는 로컬 분석 결과 제공
- 결과 화면과 공유 문구에 오락용 분석이라는 점을 명확히 표시

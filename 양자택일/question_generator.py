from __future__ import annotations

import logging
import random
from dataclasses import asdict, dataclass

from django.core.exceptions import ValidationError

from .moderation import requires_reference, validate_safe_text
from .openai_question_generator import generate_openai_question_drafts


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuestionDraft:
    title: str
    description: str
    choice_a: str
    choice_b: str


_QUESTION_FRAMES: tuple[tuple[str, str, str], ...] = (
    (
        '{topic}: 철저한 계획 vs 완전한 즉흥',
        '‘{topic}’ 관련 선택은 시작하기 전에 순서와 기준을 모두 정한다',
        '‘{topic}’ 관련 선택은 그날의 기분과 상황에 맡긴다',
    ),
    (
        '{topic}: 익숙한 방식 vs 새로운 도전',
        '‘{topic}’ 관련 선택에서는 익숙하고 검증된 방식을 고른다',
        '‘{topic}’ 관련 선택에서는 경험하지 못한 새로운 방식을 시도한다',
    ),
    (
        '{topic}: 혼자 깊게 vs 함께 넓게',
        '‘{topic}’ 관련 활동은 혼자 집중해서 깊게 경험한다',
        '‘{topic}’ 관련 활동은 여러 사람과 함께 다양하게 경험한다',
    ),
    (
        '{topic}: 시간 절약 vs 비용 절약',
        '‘{topic}’ 관련 선택에서는 비용이 더 들어도 시간을 아낀다',
        '‘{topic}’ 관련 선택에서는 시간이 더 걸려도 비용을 아낀다',
    ),
    (
        '{topic}: 결과 우선 vs 과정 우선',
        '‘{topic}’ 관련 선택에서는 만족스러운 결과를 가장 중요하게 생각한다',
        '‘{topic}’ 관련 선택에서는 결과보다 경험하는 과정을 중요하게 생각한다',
    ),
    (
        '{topic}: 매일 조금씩 vs 한 번에 몰아서',
        '‘{topic}’ 관련 활동을 매일 짧게라도 꾸준히 한다',
        '‘{topic}’ 관련 활동을 정한 날에 한 번에 집중해서 한다',
    ),
    (
        '{topic}: 대중의 인기 vs 나만의 취향',
        '‘{topic}’ 관련 선택에서 많은 사람이 좋아하는 쪽을 먼저 고려한다',
        '‘{topic}’ 관련 선택에서 인기가 없어도 내 취향에 맞는 쪽을 고른다',
    ),
    (
        '{topic}: 하나를 깊게 vs 여러 가지 넓게',
        '‘{topic}’ 관련 선택 하나를 정해 오래 깊게 파고든다',
        '‘{topic}’ 관련 선택을 여러 가지로 넓혀 다양하게 경험한다',
    ),
    (
        '{topic}: 바로 시도 vs 충분히 준비',
        '‘{topic}’ 관련 활동은 일단 시작하고 시행착오를 겪으며 배운다',
        '‘{topic}’ 관련 활동은 충분히 알아보고 준비한 뒤 시작한다',
    ),
    (
        '{topic}: 기록 남기기 vs 순간에 집중',
        '‘{topic}’ 관련 경험은 사진이나 글로 꼼꼼히 남긴다',
        '‘{topic}’ 관련 경험은 기록하지 않고 그 순간 자체에 집중한다',
    ),
    (
        '{topic}: 편리함 우선 vs 완성도 우선',
        '‘{topic}’ 관련 선택에서는 조금 부족해도 쉽고 편리한 방법을 고른다',
        '‘{topic}’ 관련 선택에서는 불편해도 완성도가 높은 방법을 고른다',
    ),
    (
        '{topic}: 정해진 규칙 vs 자유로운 방식',
        '‘{topic}’ 관련 활동은 정해진 규칙과 순서를 따를 때 편하다',
        '‘{topic}’ 관련 활동은 상황에 맞게 자유롭게 바꿀 때 편하다',
    ),
    (
        '{topic}: 직접 해결 vs 도움 요청',
        '‘{topic}’ 관련 문제가 생기면 먼저 혼자 해결해본다',
        '‘{topic}’ 관련 문제가 생기면 빠르게 주변에 도움을 요청한다',
    ),
    (
        '{topic}: 지금의 만족 vs 미래의 이득',
        '‘{topic}’ 관련 선택에서는 지금 바로 얻는 만족을 고른다',
        '‘{topic}’ 관련 선택에서는 기다리더라도 미래의 이득을 고른다',
    ),
    (
        '{topic}: 안정적인 선택 vs 큰 가능성',
        '‘{topic}’ 관련 선택에서는 예상 가능한 안정적인 쪽을 고른다',
        '‘{topic}’ 관련 선택에서는 불확실해도 가능성이 큰 쪽에 도전한다',
    ),
    (
        '{topic}: 빠른 결정 vs 오래 고민',
        '‘{topic}’ 관련 선택은 처음 끌리는 쪽으로 빠르게 결정한다',
        '‘{topic}’ 관련 선택은 두 선택을 충분히 비교한 뒤 결정한다',
    ),
)

_CATEGORY_FRAMES: dict[str, tuple[tuple[str, str, str], ...]] = {
    '음식': (
        (
            '{topic}: 강렬한 맛 vs 담백한 맛',
            '‘{topic}’는 한입부터 기억에 남는 강렬한 맛으로 즐긴다',
            '‘{topic}’는 자주 먹어도 편안한 담백한 맛으로 즐긴다',
        ),
        (
            '{topic}: 직접 만들기 vs 맛집 찾아가기',
            '시간이 걸려도 ‘{topic}’를 직접 만들어 먹는다',
            '직접 만들기보다 ‘{topic}’로 유명한 곳을 찾아간다',
        ),
        (
            '{topic}: 최애만 반복 vs 매번 새 메뉴',
            '‘{topic}’를 고를 때 가장 좋아하는 조합만 반복한다',
            '‘{topic}’를 고를 때 먹어보지 않은 조합에 도전한다',
        ),
    ),
    '연애': (
        (
            '{topic}: 자주 짧게 표현 vs 가끔 깊게 표현',
            '‘{topic}’에 관한 마음을 짧게라도 자주 표현한다',
            '‘{topic}’에 관한 마음을 횟수는 적어도 깊게 표현한다',
        ),
        (
            '{topic}: 완벽한 계획 vs 즉흥적인 만남',
            '‘{topic}’와 관련된 만남은 예약과 동선을 미리 정한다',
            '‘{topic}’와 관련된 만남은 그날 분위기에 따라 정한다',
        ),
        (
            '{topic}: 편안함 vs 설렘',
            '‘{topic}’에서는 친구처럼 편안하고 안정적인 관계를 고른다',
            '‘{topic}’에서는 만날 때마다 새롭게 설레는 관계를 고른다',
        ),
    ),
    '직장': (
        (
            '{topic}: 높은 보상과 바쁜 일정 vs 적당한 보상과 여유',
            '‘{topic}’와 관련해 일정이 바빠도 더 높은 보상을 선택한다',
            '‘{topic}’와 관련해 보상이 적어도 저녁과 주말의 여유를 선택한다',
        ),
        (
            '{topic}: 혼자 책임지기 vs 팀으로 협업하기',
            '‘{topic}’ 업무는 처음부터 끝까지 혼자 책임진다',
            '‘{topic}’ 업무는 역할을 나눠 팀으로 빠르게 해결한다',
        ),
        (
            '{topic}: 자유로운 재택 vs 분리되는 출근',
            '‘{topic}’ 업무는 장소가 자유로운 재택 방식으로 진행한다',
            '‘{topic}’ 업무는 일과 생활이 분리되는 출근 방식으로 진행한다',
        ),
    ),
    '학교': (
        (
            '{topic}: 발표 담당 vs 자료 정리 담당',
            '‘{topic}’ 과제에서 사람들 앞에 서는 발표를 맡는다',
            '‘{topic}’ 과제에서 자료 조사와 정리를 맡는다',
        ),
        (
            '{topic}: 한 번의 시험 vs 꾸준한 과제',
            '‘{topic}’ 평가는 한 번의 큰 시험으로 받는다',
            '‘{topic}’ 평가는 매주 꾸준한 과제로 받는다',
        ),
        (
            '{topic}: 두루 친한 친구들 vs 속 깊은 친구 한 명',
            '‘{topic}’ 생활에서 여러 친구와 두루 어울린다',
            '‘{topic}’ 생활에서 모든 고민을 나눌 친구 한 명과 지낸다',
        ),
    ),
    '일상': (
        (
            '{topic}: 미리 끝내기 vs 마감 직전 집중',
            '‘{topic}’ 관련 할 일은 여유가 있을 때 미리 끝낸다',
            '‘{topic}’ 관련 할 일은 마감 직전에 집중해서 끝낸다',
        ),
        (
            '{topic}: 계획 있는 주말 vs 눈 뜨고 정하는 주말',
            '주말의 ‘{topic}’ 일정은 금요일까지 미리 정한다',
            '주말의 ‘{topic}’ 일정은 당일 기분에 따라 정한다',
        ),
        (
            '{topic}: 매일 작은 만족 vs 가끔 큰 이벤트',
            '‘{topic}’로 매일 작고 꾸준한 만족을 만든다',
            '‘{topic}’를 모아두었다가 가끔 큰 이벤트로 즐긴다',
        ),
    ),
    '야구': (
        (
            '{topic}: 강한 공격력 vs 빈틈없는 수비력',
            '‘{topic}’에서는 실점해도 더 많이 득점하는 공격력을 고른다',
            '‘{topic}’에서는 득점이 적어도 실수를 막는 수비력을 고른다',
        ),
        (
            '{topic}: 압도적인 스타 한 명 vs 고른 선수층',
            '‘{topic}’에서는 경기를 바꿀 스타 선수 한 명을 고른다',
            '‘{topic}’에서는 누구나 제 몫을 하는 균형 잡힌 팀을 고른다',
        ),
        (
            '{topic}: 연장 끝 역전패 vs 도착 직후 우천 취소',
            '‘{topic}’ 경기를 끝까지 봤지만 연장전에서 역전패한다',
            '‘{topic}’ 경기장에 도착하자마자 비로 경기가 취소된다',
        ),
    ),
    '개발자': (
        (
            '{topic}: 빠른 출시 vs 높은 완성도',
            '‘{topic}’ 기능은 핵심만 완성해 빠르게 출시한다',
            '‘{topic}’ 기능은 시간이 걸려도 완성도를 높여 출시한다',
        ),
        (
            '{topic}: 최신 기술 도전 vs 익숙한 기술 안정성',
            '‘{topic}’에는 학습이 필요해도 최신 기술을 사용한다',
            '‘{topic}’에는 새롭지 않아도 익숙하고 안정적인 기술을 사용한다',
        ),
        (
            '{topic}: 완벽한 문서 vs 촘촘한 테스트',
            '‘{topic}’에는 누구나 이해할 수 있는 설명 문서를 먼저 만든다',
            '‘{topic}’에는 오류를 빠르게 찾는 자동 테스트를 먼저 만든다',
        ),
    ),
}


def generate_question_drafts(
    *,
    keywords: list[str],
    count: int,
    category_name: str,
) -> dict[str, object]:
    if not 7 <= count <= 10:
        raise ValueError('문항 수는 7~10개여야 합니다.')
    if not keywords:
        raise ValueError('한 개 이상의 키워드가 필요합니다.')

    drafts: list[QuestionDraft] = []
    if len(keywords) > 1:
        first, second = keywords[0], keywords[1]
        drafts.append(QuestionDraft(
            title=f'{first}에 집중하기 vs {second}에 집중하기',
            description=f'{category_name} 주제에서 두 키워드 중 더 중요한 쪽을 선택해보세요.',
            choice_a=f'이번 선택에서는 ‘{first}’에 시간과 관심을 집중한다',
            choice_b=f'이번 선택에서는 ‘{second}’에 시간과 관심을 집중한다',
        ))

    frame_pool = _QUESTION_FRAMES + _CATEGORY_FRAMES.get(category_name, ())
    frames = random.SystemRandom().sample(frame_pool, count - len(drafts))
    for index, (title, choice_a, choice_b) in enumerate(frames):
        topic = keywords[index % len(keywords)]
        drafts.append(QuestionDraft(
            title=title.format(topic=topic),
            description=f'{category_name} 주제에서 ‘{topic}’에 관한 취향을 선택해보세요.',
            choice_a=choice_a.format(topic=topic),
            choice_b=choice_b.format(topic=topic),
        ))

    for draft in drafts:
        for text in asdict(draft).values():
            validate_safe_text(text)
            if requires_reference(text):
                raise ValidationError('검증이 필요한 표현은 자동 문항으로 만들 수 없습니다.')

    axis_plan = (
        ('E/I', 'E', 'I'),
        ('S/N', 'S', 'N'),
        ('T/F', 'T', 'F'),
        ('J/P', 'J', 'P'),
    )
    draft_payloads = []
    for index, draft in enumerate(drafts):
        mbti_axis, choice_a_trait, choice_b_trait = axis_plan[index % len(axis_plan)]
        draft_payloads.append({
            **asdict(draft),
            'mbti_axis': mbti_axis,
            'choice_a_trait': choice_a_trait,
            'choice_b_trait': choice_b_trait,
        })

    keyword_label = ' · '.join(keywords[:3])
    return {
        'title_suggestion': f'{keyword_label} 선택 보고서',
        'description_suggestion': (
            f'{category_name} 카테고리에서 {keyword_label}에 관한 취향을 '
            f'{count}가지 양자택일로 확인합니다.'
        ),
        'drafts': draft_payloads,
    }


def generate_question_drafts_with_fallback(
    *,
    api_key: str,
    model: str,
    timeout: float,
    keywords: list[str],
    count: int,
    category_name: str,
) -> dict[str, object]:
    if api_key:
        try:
            return generate_openai_question_drafts(
                api_key=api_key,
                model=model,
                timeout=timeout,
                keywords=keywords,
                count=count,
                category_name=category_name,
            )
        except Exception as exc:
            logger.warning(
                'OpenAI question generation failed; using local fallback (%s).',
                type(exc).__name__,
            )

    result = generate_question_drafts(
        keywords=keywords,
        count=count,
        category_name=category_name,
    )
    result['source'] = 'local'
    return result

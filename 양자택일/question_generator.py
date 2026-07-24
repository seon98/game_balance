from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from django.core.exceptions import ValidationError

from .moderation import requires_reference, validate_safe_text


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

    frames = random.SystemRandom().sample(_QUESTION_FRAMES, count)
    drafts: list[QuestionDraft] = []
    for index, (title, choice_a, choice_b) in enumerate(frames):
        topic = keywords[index % len(keywords)]
        draft = QuestionDraft(
            title=title.format(topic=topic),
            description=f'{category_name} 주제에서 ‘{topic}’에 관한 취향을 선택해보세요.',
            choice_a=choice_a.format(topic=topic),
            choice_b=choice_b.format(topic=topic),
        )
        for text in asdict(draft).values():
            validate_safe_text(text)
            if requires_reference(text):
                raise ValidationError('검증이 필요한 표현은 자동 문항으로 만들 수 없습니다.')
        drafts.append(draft)

    keyword_label = ' · '.join(keywords[:3])
    return {
        'title_suggestion': f'{keyword_label} 선택 보고서',
        'description_suggestion': (
            f'{category_name} 카테고리에서 {keyword_label}에 관한 취향을 '
            f'{count}가지 양자택일로 확인합니다.'
        ),
        'drafts': [asdict(draft) for draft in drafts],
    }

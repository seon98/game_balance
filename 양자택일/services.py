from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import F

from .models import Choice, Question, ResultGrade, ResultTemplate, Vote


# ---------------------------------------------------------------------------
# 등급 결정
# ---------------------------------------------------------------------------

def get_grade(percentage: float) -> str:
    """
    투표 비율(%)에 따라 ResultGrade 값을 반환한다.
    경계값:
      0 ≤ x ≤ 15          → LEGENDARY_MINORITY
      15 < x ≤ 30         → RARE
      30 < x ≤ 44         → MINORITY
      44 < x < 56         → BALANCED
      56 ≤ x ≤ 69         → MAJORITY
      69 < x ≤ 84         → POPULAR
      84 < x ≤ 100        → OVERWHELMING
    """
    if not (0 <= percentage <= 100):
        raise ValueError(f'percentage는 0~100 사이여야 합니다. 입력값: {percentage}')

    if percentage <= 15:
        return ResultGrade.LEGENDARY_MINORITY
    if percentage <= 30:
        return ResultGrade.RARE
    if percentage <= 44:
        return ResultGrade.MINORITY
    if percentage < 56:
        return ResultGrade.BALANCED
    if percentage <= 69:
        return ResultGrade.MAJORITY
    if percentage <= 84:
        return ResultGrade.POPULAR
    return ResultGrade.OVERWHELMING


# ---------------------------------------------------------------------------
# 안전한 문자열 포맷팅
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return '{' + key + '}'


def safe_format(template: str, **kwargs: Any) -> str:
    """알 수 없는 플레이스홀더가 있어도 오류 없이 포맷팅한다."""
    try:
        return template.format_map(_SafeDict(**kwargs))
    except Exception:
        return template


# ---------------------------------------------------------------------------
# 결과 데이터 구조
# ---------------------------------------------------------------------------

@dataclass
class ResultData:
    grade: str
    grade_display: str
    title: str
    summary: str
    description: str
    keywords: list[str]
    share_text: str
    percentage: float
    total_votes: int
    same_people: int
    choice_text: str
    choice_code: str
    question_title: str


# ---------------------------------------------------------------------------
# 기본 결과 문구 (DB 템플릿 없을 때 폴백)
# ---------------------------------------------------------------------------

_DEFAULT_TEMPLATES: dict[str, dict[str, Any]] = {
    ResultGrade.LEGENDARY_MINORITY: {
        'title': '{choice_text}를 선택한 전설의 소수파!',
        'summary': '단 {same_people}명만 같은 선택을 했어요',
        'description': (
            '전체 {total_votes}명 중 {percentage}%만 {choice_text}을(를) 골랐습니다. '
            '100명 중 약 {same_people}명만 당신과 같은 선택을 했어요. '
            '당신의 취향은 희귀하고 독보적이라는 뜻일 수 있어요!'
        ),
        'keywords': ['독보적', '희귀', '개성'],
        'share_text': '나는 {percentage}% 전설의 소수파! 당신의 선택은?',
    },
    ResultGrade.RARE: {
        'title': '{choice_text}를 고른 희귀 취향 발견!',
        'summary': '상위 {percentage}%의 희귀한 선택',
        'description': (
            '전체 참여자의 {percentage}%만 같은 답변을 선택했습니다. '
            '100명 중 약 {same_people}명이 당신과 같은 선택을 했어요. '
            '다수의 의견보다 자신의 기준을 중요하게 생각하는 편이군요!'
        ),
        'keywords': ['개성적', '독립적', '다양성'],
        'share_text': '나는 {percentage}% 희귀 {choice_text}파! 당신의 선택은?',
    },
    ResultGrade.MINORITY: {
        'title': '소수 취향의 {choice_text} 선택자!',
        'summary': '소수파이지만 확실한 취향',
        'description': (
            '{percentage}%가 같은 선택을 했습니다. '
            '다수와 다른 길을 걷는 소수 취향이네요. '
            '자신만의 기준을 가진 사람일 가능성이 있어요.'
        ),
        'keywords': ['소수파', '개성', '독자적'],
        'share_text': '나는 {percentage}% 소수파 {choice_text}! 당신은?',
    },
    ResultGrade.BALANCED: {
        'title': '팽팽한 선택, 당신은 {choice_text}!',
        'summary': '반반에 가까운 균형 잡힌 선택',
        'description': (
            '{percentage}%가 {choice_text}을(를) 선택했습니다. '
            '두 선택지가 팽팽하게 맞서는 상황에서 당신의 선택이 무게추가 됐네요. '
            '어느 쪽이든 이해할 수 있는 균형 잡힌 시각을 가진 편일 수 있어요.'
        ),
        'keywords': ['균형', '중립적', '유연'],
        'share_text': '나는 {percentage}% {choice_text}파! 당신의 균형은?',
    },
    ResultGrade.MAJORITY: {
        'title': '공감받는 선택, {choice_text}!',
        'summary': '과반수가 공감하는 선택',
        'description': (
            '{percentage}%가 같은 선택을 했습니다. '
            '절반 이상이 당신과 같은 생각이었네요. '
            '공감 능력이 뛰어나거나 실용적인 판단을 하는 편일 수 있어요.'
        ),
        'keywords': ['공감', '실용적', '대중적'],
        'share_text': '나는 {percentage}% 공감 {choice_text}파! 당신은?',
    },
    ResultGrade.POPULAR: {
        'title': '인기 있는 선택, {choice_text}!',
        'summary': '10명 중 약 7명이 같은 선택',
        'description': (
            '{percentage}%라는 높은 비율이 {choice_text}을(를) 선택했습니다. '
            '많은 사람들이 비슷한 생각을 하고 있었군요. '
            '트렌드를 잘 읽거나 보편적인 가치를 중요시하는 편일 수 있어요.'
        ),
        'keywords': ['트렌드', '인기', '대세'],
        'share_text': '나는 {percentage}% 인기 {choice_text}파! 당신은?',
    },
    ResultGrade.OVERWHELMING: {
        'title': '압도적! 대세는 {choice_text}!',
        'summary': '참여자 대부분이 같은 선택',
        'description': (
            '무려 {percentage}%가 {choice_text}을(를) 선택했습니다. '
            '거의 모든 사람이 같은 생각이었네요. '
            '대세를 따르는 안정적인 선택을 하는 편이거나, 이 선택이 그만큼 매력적인 것일 수 있어요!'
        ),
        'keywords': ['대세', '안정적', '보편'],
        'share_text': '나는 {percentage}% 압도적 {choice_text}파! 당신은?',
    },
}

_GRADE_SUMMARY_TEMPLATES: dict[str, str] = {
    ResultGrade.LEGENDARY_MINORITY: '100명 중 {same_people}명만 같은 선택을 했어요!',
    ResultGrade.RARE: '희귀한 취향이군요! 상위 {percentage}%의 선택',
    ResultGrade.MINORITY: '{percentage}%의 소수파, 확실한 취향!',
    ResultGrade.BALANCED: '팽팽한 균형 속 {percentage}%의 선택',
    ResultGrade.MAJORITY: '{percentage}%가 공감한 선택이에요',
    ResultGrade.POPULAR: '{percentage}%의 인기 선택!',
    ResultGrade.OVERWHELMING: '무려 {percentage}%! 압도적인 대세 선택',
}


# ---------------------------------------------------------------------------
# ResultGenerator 인터페이스 (AI 확장 대비)
# ---------------------------------------------------------------------------

class ResultGenerator(ABC):
    @abstractmethod
    def generate(
        self,
        question: Question,
        choice: Choice,
        percentage: float,
        total_votes: int,
        grade: str,
    ) -> ResultData:
        ...


class TemplateResultGenerator(ResultGenerator):
    def generate(
        self,
        question: Question,
        choice: Choice,
        percentage: float,
        total_votes: int,
        grade: str,
    ) -> ResultData:
        same_people = round(percentage)

        format_kwargs: dict[str, Any] = {
            'choice_text': choice.text,
            'percentage': percentage,
            'total_votes': total_votes,
            'same_people': same_people,
            'question_title': question.title,
        }

        template = (
            ResultTemplate.objects
            .filter(grade=grade, is_active=True)
            .order_by('?')
            .first()
        )

        if template:
            title = safe_format(template.title, **format_kwargs)
            summary = safe_format(
                _GRADE_SUMMARY_TEMPLATES[grade], **format_kwargs
            )
            description = safe_format(template.description, **format_kwargs)
            keywords: list[str] = template.keywords or []
            share_text = safe_format(template.share_text, **format_kwargs)
        else:
            defaults = _DEFAULT_TEMPLATES[grade]
            title = safe_format(defaults['title'], **format_kwargs)
            summary = safe_format(
                _GRADE_SUMMARY_TEMPLATES[grade], **format_kwargs
            )
            description = safe_format(defaults['description'], **format_kwargs)
            keywords = list(defaults['keywords'])
            share_text = safe_format(defaults['share_text'], **format_kwargs)

        return ResultData(
            grade=grade,
            grade_display=ResultGrade(grade).label,
            title=title,
            summary=summary,
            description=description,
            keywords=keywords,
            share_text=share_text,
            percentage=percentage,
            total_votes=total_votes,
            same_people=same_people,
            choice_text=choice.text,
            choice_code=choice.code,
            question_title=question.title,
        )


class AIResultGenerator(ResultGenerator):
    """향후 AI API 연동을 위한 구현체. 현재는 폴백으로만 동작한다."""

    def __init__(self, fallback: ResultGenerator | None = None) -> None:
        self._fallback = fallback or TemplateResultGenerator()

    def generate(
        self,
        question: Question,
        choice: Choice,
        percentage: float,
        total_votes: int,
        grade: str,
    ) -> ResultData:
        # AI 연동 전까지 항상 폴백을 사용한다.
        return self._fallback.generate(
            question, choice, percentage, total_votes, grade
        )


# ---------------------------------------------------------------------------
# 투표 처리
# ---------------------------------------------------------------------------

def process_vote(
    question: Question,
    choice: Choice,
    session_key: str,
) -> tuple[Vote, bool]:
    """
    투표를 저장하고 (Vote, created) 튜플을 반환한다.
    이미 투표한 경우 기존 Vote를 반환하고 created=False.
    F 표현식으로 vote_count를 안전하게 증가시켜 동시 투표 시 집계 유실을 방지한다.
    """
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
    return vote, created


def build_result(
    question: Question,
    voted_choice_id: int,
    generator: ResultGenerator | None = None,
) -> ResultData:
    """투표 완료 후 ResultData를 생성한다."""
    if generator is None:
        generator = TemplateResultGenerator()

    choices = list(question.choices.all())
    total = sum(c.vote_count for c in choices)

    try:
        my_choice = next(c for c in choices if c.pk == voted_choice_id)
    except StopIteration as exc:
        raise ValueError(f'choice pk={voted_choice_id}를 찾을 수 없습니다.') from exc

    percentage = round(my_choice.vote_count / total * 100, 1) if total > 0 else 50.0
    grade = get_grade(percentage)

    return generator.generate(question, my_choice, percentage, total, grade)

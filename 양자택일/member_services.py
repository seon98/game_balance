from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Iterable

from django.utils import timezone


AXES = (
    ('E/I', 'E', 'I', '에너지 방향'),
    ('S/N', 'S', 'N', '정보를 보는 방식'),
    ('T/F', 'T', 'F', '판단의 기준'),
    ('J/P', 'J', 'P', '생활과 결정 방식'),
)

TRAIT_VALUES = {
    'E': '사람과 행동',
    'I': '집중과 성찰',
    'S': '현실과 구체성',
    'N': '가능성과 상상력',
    'T': '논리와 일관성',
    'F': '관계와 공감',
    'J': '계획과 완결',
    'P': '유연함과 탐색',
}

MEMBER_THEMES = [
    {
        'slug': 'deep-love',
        'name': '연애 심층편',
        'description': '표현 방식과 갈등 해결, 관계의 우선순위를 고르는 선택',
        'keywords': '연애, 갈등, 표현 방식',
        'icon': 'bi-heart',
    },
    {
        'slug': 'work-survival',
        'name': '직장 생존편',
        'description': '성과와 관계, 안정과 도전 사이의 현실적인 딜레마',
        'keywords': '직장, 커리어, 협업',
        'icon': 'bi-briefcase',
    },
    {
        'slug': 'friendship',
        'name': '친구 관계편',
        'description': '의리와 솔직함, 거리 조절에 관한 우정 선택',
        'keywords': '친구, 우정, 인간관계',
        'icon': 'bi-people',
    },
    {
        'slug': 'travel-style',
        'name': '여행 스타일편',
        'description': '계획과 즉흥, 휴식과 탐험을 가르는 여행 취향',
        'keywords': '여행, 휴가, 계획',
        'icon': 'bi-airplane',
    },
    {
        'slug': 'spending',
        'name': '소비 습관편',
        'description': '경험과 소유, 현재 만족과 미래 준비 사이의 선택',
        'keywords': '소비, 저축, 쇼핑',
        'icon': 'bi-wallet2',
    },
    {
        'slug': 'couple-friend',
        'name': '커플·우정 특별편',
        'description': '둘이 함께 답하고 서로의 결정 차이를 발견하는 주제',
        'keywords': '커플, 우정, 함께하기',
        'icon': 'bi-hearts',
    },
]

SEASONAL_KEYWORDS = {
    1: ['새해 목표', '겨울 여행', '생활 습관'],
    2: ['밸런타인', '연애 표현', '겨울 취미'],
    3: ['새 출발', '학교생활', '직장 적응'],
    4: ['봄 여행', '친구 관계', '주말 계획'],
    5: ['가족', '휴일', '감사 표현'],
    6: ['여름 준비', '소비 습관', '건강한 일상'],
    7: ['여름휴가', '여행 스타일', '친구 모임'],
    8: ['휴가', '취미', '즉흥 여행'],
    9: ['가을 계획', '커리어', '새로운 도전'],
    10: ['축제', '데이트', '취향'],
    11: ['연말 준비', '소비', '인간관계'],
    12: ['연말 모임', '선물', '새해 계획'],
}

OPPOSITE_TOPICS = {
    'E': '혼자만의 시간',
    'I': '낯선 사람들과 모임',
    'S': '상상 속 미래',
    'N': '현실적인 생활 선택',
    'T': '공감과 관계',
    'F': '논리적인 위기 대응',
    'J': '무계획 즉흥 여행',
    'P': '완벽한 일정 관리',
}


def _result_axis_counts(result: Any) -> dict[str, tuple[int, int]]:
    counts = {
        axis: (0, 0)
        for axis, _first, _second, _label in AXES
    }
    summaries = result.result_data.get('axis_summaries', [])
    if not isinstance(summaries, list):
        return counts
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        axis = summary.get('axis')
        if axis not in counts:
            continue
        counts[axis] = (
            int(summary.get('first_count', 0)),
            int(summary.get('second_count', 0)),
        )
    return counts


def _period_axis_counts(results: Iterable[Any]) -> dict[str, list[int]]:
    counts = {
        axis: [0, 0]
        for axis, _first, _second, _label in AXES
    }
    for result in results:
        for axis, (first_count, second_count) in _result_axis_counts(result).items():
            counts[axis][0] += first_count
            counts[axis][1] += second_count
    return counts


def _first_percentage(counts: list[int]) -> int:
    total = counts[0] + counts[1]
    return round(counts[0] / total * 100) if total else 50


def build_choice_report(
    results: Iterable[Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    result_list = list(results)
    current_time = timezone.localtime(now or timezone.now())
    current_start = current_time.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    previous_end = current_start - timedelta(microseconds=1)
    previous_start = previous_end.replace(day=1)

    current_results = [
        result
        for result in result_list
        if timezone.localtime(result.created_at) >= current_start
    ]
    previous_results = [
        result
        for result in result_list
        if previous_start
        <= timezone.localtime(result.created_at)
        <= previous_end
    ]

    all_counts = _period_axis_counts(result_list)
    current_counts = _period_axis_counts(current_results)
    previous_counts = _period_axis_counts(previous_results)
    axis_reports = []
    trait_scores: Counter[str] = Counter()
    for axis, first, second, label in AXES:
        total = all_counts[axis]
        current = current_counts[axis]
        previous = previous_counts[axis]
        first_percentage = _first_percentage(total)
        current_percentage = _first_percentage(current)
        previous_percentage = _first_percentage(previous)
        trait_scores[first] += total[0]
        trait_scores[second] += total[1]

        if not sum(current):
            shift_label = '이번 달 기록 없음'
        elif not sum(previous):
            shift_label = '이번 달 첫 기록'
        else:
            difference = current_percentage - previous_percentage
            if abs(difference) < 5:
                shift_label = '지난달과 비슷함'
            elif difference > 0:
                shift_label = f'{first} 방향 {difference}%p 증가'
            else:
                shift_label = f'{second} 방향 {abs(difference)}%p 증가'

        axis_reports.append({
            'axis': axis,
            'label': label,
            'first': first,
            'second': second,
            'first_count': total[0],
            'second_count': total[1],
            'first_percentage': first_percentage,
            'second_percentage': 100 - first_percentage,
            'dominant': first if total[0] >= total[1] else second,
            'shift_label': shift_label,
        })

    current_mbti = Counter(result.mbti for result in current_results)
    all_mbti = Counter(result.mbti for result in result_list)
    representative = (
        current_mbti.most_common(1)[0][0]
        if current_mbti
        else (all_mbti.most_common(1)[0][0] if all_mbti else None)
    )
    keyword_counts = Counter(
        str(keyword)
        for result in result_list
        for keyword in result.keywords
    )
    value_keywords = [
        TRAIT_VALUES[trait]
        for trait, _count in trait_scores.most_common(4)
    ]
    return {
        'total_results': len(result_list),
        'current_month_count': len(current_results),
        'previous_month_count': len(previous_results),
        'representative_mbti': representative,
        'frequent_mbti': all_mbti.most_common(4),
        'axis_reports': axis_reports,
        'top_keywords': keyword_counts.most_common(6),
        'value_keywords': value_keywords,
    }


def build_member_recommendations(
    results: Iterable[Any],
    *,
    popular_keywords: Iterable[str] = (),
    month: int | None = None,
) -> dict[str, Any]:
    result_list = list(results)
    keyword_counts = Counter(
        str(keyword)
        for result in result_list
        for keyword in result.keywords
    )
    mbti_counts = Counter(result.mbti for result in result_list)
    representative = mbti_counts.most_common(1)[0][0] if mbti_counts else ''
    opposite_topics = []
    for trait in representative:
        topic = OPPOSITE_TOPICS[trait]
        if topic not in opposite_topics:
            opposite_topics.append(topic)

    played_text = ' '.join(keyword_counts).casefold()
    fresh_themes = [
        theme
        for theme in MEMBER_THEMES
        if theme['name'].casefold() not in played_text
    ]
    return {
        'recent_interests': keyword_counts.most_common(5),
        'opposite_topics': opposite_topics[:4],
        'popular_topics': list(dict.fromkeys(popular_keywords))[:5],
        'seasonal_topics': SEASONAL_KEYWORDS[month or timezone.localdate().month],
        'themes': MEMBER_THEMES,
        'fresh_themes': fresh_themes[:3] or MEMBER_THEMES[:3],
    }


def build_comparison_result(
    *,
    questions: list[dict[str, Any]],
    creator_answers: list[str],
    participant_answers: list[str],
    creator_result: dict[str, Any],
    participant_result: dict[str, Any],
) -> dict[str, Any]:
    if (
        len(questions) != len(creator_answers)
        or len(questions) != len(participant_answers)
    ):
        raise ValueError('함께하기 답변 수가 일치하지 않습니다.')

    matches = 0
    differences = []
    for index, (question, creator_code, participant_code) in enumerate(
        zip(questions, creator_answers, participant_answers, strict=True),
        start=1,
    ):
        if creator_code == participant_code:
            matches += 1
            continue
        creator_key = 'choice_a' if creator_code == 'A' else 'choice_b'
        participant_key = 'choice_a' if participant_code == 'A' else 'choice_b'
        differences.append({
            'question_number': index,
            'question': question.get('title', ''),
            'creator_choice': question.get(creator_key, ''),
            'participant_choice': question.get(participant_key, ''),
        })

    total = len(questions)
    match_percentage = round(matches / total * 100) if total else 0
    if match_percentage == 100:
        title = '복사 붙여넣기급 결정 메이트'
    elif match_percentage >= 70:
        title = '결론은 달라도 방향은 비슷한 팀'
    elif match_percentage >= 40:
        title = '대화할수록 재밌는 반반 조합'
    else:
        title = '매 선택마다 토론이 열리는 반전 콤비'
    return {
        'match_count': matches,
        'difference_count': total - matches,
        'total_questions': total,
        'match_percentage': match_percentage,
        'title': title,
        'differences': differences,
        'highlighted_differences': differences[:3],
        'creator_mbti': creator_result.get('mbti', ''),
        'participant_mbti': participant_result.get('mbti', ''),
    }

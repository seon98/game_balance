from __future__ import annotations

import re
import unicodedata

from django.core.exceptions import ValidationError


_BLOCKED_GROUPS: dict[str, tuple[str, ...]] = {
    '성인·음란 콘텐츠': (
        '19금',
        '성관계',
        '섹스',
        '야동',
        '음란물',
        '성인물',
        '성매매',
        '원나잇',
        '노출사진',
    ),
    '자해·불법 행동 조장': (
        '자살방법',
        '자해방법',
        '마약하는법',
        '폭탄만드는법',
        '불법도박',
    ),
    '혐오·차별 표현': (
        '열등한인종',
        '장애인은싫어',
        '외국인은싫어',
        '죽어야한다',
    ),
}

_REFERENCE_REQUIRED_PATTERNS = (
    '100%완치',
    '무조건치료',
    '수익보장',
    '원금보장',
    '과학적으로증명',
    '통계적으로확실',
)


def _compact(text: str) -> str:
    normalized = unicodedata.normalize('NFKC', text).casefold()
    return re.sub(r'[^0-9a-z가-힣]+', '', normalized)


def validate_safe_text(text: str) -> None:
    compact = _compact(text or '')
    if not compact:
        return

    for group, phrases in _BLOCKED_GROUPS.items():
        if any(_compact(phrase) in compact for phrase in phrases):
            raise ValidationError(
                f'{group}는 제출할 수 없습니다. 모든 사용자 제작 콘텐츠는 공개 전 추가 검수를 받습니다.'
            )


def requires_reference(*texts: str) -> bool:
    compact = _compact(' '.join(texts))
    return any(_compact(pattern) in compact for pattern in _REFERENCE_REQUIRED_PATTERNS)

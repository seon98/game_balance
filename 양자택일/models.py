from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .moderation import requires_reference, validate_safe_text


class ResultGrade(models.TextChoices):
    LEGENDARY_MINORITY = 'LEGENDARY_MINORITY', '전설의 소수파'
    RARE = 'RARE', '희귀한 선택'
    MINORITY = 'MINORITY', '소수 취향'
    BALANCED = 'BALANCED', '팽팽한 선택'
    MAJORITY = 'MAJORITY', '공감받는 선택'
    POPULAR = 'POPULAR', '인기 선택'
    OVERWHELMING = 'OVERWHELMING', '압도적인 선택'


class Category(models.Model):
    name = models.CharField(max_length=50, verbose_name='이름')
    slug = models.SlugField(unique=True, allow_unicode=True, verbose_name='슬러그')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')

    class Meta:
        verbose_name = '카테고리'
        verbose_name_plural = '카테고리 목록'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class GameSet(models.Model):
    MIN_QUESTIONS = 7
    MAX_QUESTIONS = 10

    class Status(models.TextChoices):
        PENDING = 'PENDING', '검수 대기'
        APPROVED = 'APPROVED', '승인'
        REJECTED = 'REJECTED', '반려'

    class ContentBasis(models.TextChoices):
        HYPOTHETICAL = 'HYPOTHETICAL', '가상·취향형'
        SOURCED = 'SOURCED', '사실·정보형'

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='created_game_sets',
        verbose_name='제작자',
    )
    is_official = models.BooleanField(default=False, verbose_name='공식 콘텐츠')
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='game_sets',
        verbose_name='카테고리',
    )
    title = models.CharField(max_length=120, verbose_name='주제')
    description = models.TextField(blank=True, verbose_name='주제 설명')
    content_basis = models.CharField(
        max_length=20,
        choices=ContentBasis.choices,
        default=ContentBasis.HYPOTHETICAL,
        verbose_name='콘텐츠 유형',
    )
    reference_url = models.URLField(
        blank=True,
        verbose_name='검증 자료 URL',
        help_text='사실·정보형 콘텐츠는 신뢰할 수 있는 근거 URL이 필요합니다.',
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='검수 상태',
    )
    moderation_note = models.TextField(blank=True, verbose_name='검수 메모')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_game_sets',
        verbose_name='검수자',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='검수일')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='제출일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일')

    class Meta:
        verbose_name = '게임 세트'
        verbose_name_plural = '게임 세트 목록'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.title

    def clean(self) -> None:
        errors: dict[str, list[str] | str] = {}
        for field_name, value in (
            ('title', self.title),
            ('description', self.description),
        ):
            try:
                validate_safe_text(value)
            except ValidationError as exc:
                errors[field_name] = exc.messages

        if self.content_basis == self.ContentBasis.SOURCED and not self.reference_url:
            errors['reference_url'] = '사실·정보형 콘텐츠는 검증 자료 URL을 입력해야 합니다.'
        if errors:
            raise ValidationError(errors)

    def validate_submission(self) -> None:
        self.full_clean()
        if not self.is_official and not self.creator_id:
            raise ValidationError('사용자 제작 게임에는 제작자가 필요합니다.')
        if not self.pk:
            raise ValidationError('저장된 게임 세트만 검수할 수 있습니다.')

        questions = list(self.questions.prefetch_related('choices').all())
        if not self.MIN_QUESTIONS <= len(questions) <= self.MAX_QUESTIONS:
            raise ValidationError(
                f'주제별 문항 수는 {self.MIN_QUESTIONS}~{self.MAX_QUESTIONS}개여야 합니다.'
            )

        errors: list[str] = []
        content_texts = [self.title, self.description]
        for index, question in enumerate(questions, start=1):
            content_texts.extend([question.title, question.description])
            try:
                question.full_clean()
                choices = list(question.choices.all())
                if len(choices) != 2 or {choice.code for choice in choices} != {'A', 'B'}:
                    errors.append(f'{index}번 문항의 선택지는 A와 B 두 개여야 합니다.')
                for choice in choices:
                    content_texts.append(choice.text)
                    choice.full_clean()
            except ValidationError as exc:
                errors.append(f'{index}번 문항: {" ".join(exc.messages)}')

        if (
            requires_reference(*content_texts)
            and self.content_basis != self.ContentBasis.SOURCED
        ):
            errors.append('검증이 필요한 주장은 사실·정보형과 근거 URL이 필요합니다.')

        if errors:
            raise ValidationError(errors)

    def approve(self, reviewer: settings.AUTH_USER_MODEL) -> None:
        self.validate_submission()
        self.status = self.Status.APPROVED
        self.moderation_note = ''
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save(
            update_fields=[
                'status',
                'moderation_note',
                'reviewed_by',
                'reviewed_at',
                'updated_at',
            ]
        )
        self.questions.update(is_active=True, category=self.category)

    def reject(self, reviewer: settings.AUTH_USER_MODEL, note: str = '') -> None:
        self.status = self.Status.REJECTED
        self.moderation_note = note
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now()
        self.save(
            update_fields=[
                'status',
                'moderation_note',
                'reviewed_by',
                'reviewed_at',
                'updated_at',
            ]
        )
        self.questions.update(is_active=False)


class Question(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='questions',
        verbose_name='카테고리',
    )
    game_set = models.ForeignKey(
        GameSet,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='questions',
        verbose_name='사용자 제작 세트',
    )
    title = models.CharField(max_length=200, verbose_name='제목')
    description = models.TextField(blank=True, verbose_name='설명')
    is_active = models.BooleanField(default=True, verbose_name='활성화')
    view_count = models.PositiveIntegerField(default=0, verbose_name='조회수')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일')

    class Meta:
        verbose_name = '질문'
        verbose_name_plural = '질문 목록'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.title

    def clean(self) -> None:
        errors: dict[str, list[str] | str] = {}
        for field_name, value in (
            ('title', self.title),
            ('description', self.description),
        ):
            try:
                validate_safe_text(value)
            except ValidationError as exc:
                errors[field_name] = exc.messages

        if self.game_set_id and self.category_id != self.game_set.category_id:
            errors['category'] = '문항의 카테고리는 게임 세트의 카테고리와 같아야 합니다.'

        if errors:
            raise ValidationError(errors)

    def total_votes(self) -> int:
        result = self.choices.aggregate(total=models.Sum('vote_count'))
        return result['total'] or 0

    def validate_choice_count(self) -> None:
        if self.pk and self.choices.count() != 2:
            raise ValidationError('질문에는 정확히 두 개의 선택지가 있어야 합니다.')


class Choice(models.Model):
    class Code(models.TextChoices):
        A = 'A', 'A'
        B = 'B', 'B'

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='choices',
        verbose_name='질문',
    )
    code = models.CharField(
        max_length=1,
        choices=Code.choices,
        verbose_name='코드',
    )
    text = models.CharField(max_length=300, verbose_name='선택지 내용')
    image = models.ImageField(
        upload_to='choices/',
        null=True,
        blank=True,
        verbose_name='이미지',
    )
    vote_count = models.PositiveIntegerField(default=0, verbose_name='투표수')

    class Meta:
        verbose_name = '선택지'
        verbose_name_plural = '선택지 목록'
        unique_together = [('question', 'code')]
        ordering = ['code']

    def __str__(self) -> str:
        return f'{self.question.title} - {self.code}: {self.text}'

    def clean(self) -> None:
        validate_safe_text(self.text)

    def vote_percentage(self) -> float:
        total = self.question.total_votes()
        if total == 0:
            return 50.0
        return round(self.vote_count / total * 100, 1)


class Vote(models.Model):
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='votes',
        verbose_name='질문',
    )
    choice = models.ForeignKey(
        Choice,
        on_delete=models.CASCADE,
        related_name='votes',
        verbose_name='선택지',
    )
    session_key = models.CharField(max_length=40, verbose_name='세션 키')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='투표일')

    class Meta:
        verbose_name = '투표'
        verbose_name_plural = '투표 목록'
        constraints = [
            models.UniqueConstraint(
                fields=['question', 'session_key'],
                name='unique_vote_per_session',
            )
        ]

    def __str__(self) -> str:
        return f'{self.question.title} - {self.session_key[:8]}…'


class SavedInstantResult(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_instant_results',
        verbose_name='회원',
    )
    game_token = models.CharField(max_length=32, verbose_name='즉석 게임 식별자')
    topic = models.CharField(max_length=120, verbose_name='게임 주제')
    keywords = models.JSONField(default=list, verbose_name='키워드')
    mbti = models.CharField(max_length=4, verbose_name='선택 캐릭터')
    title = models.CharField(max_length=120, verbose_name='결과 타이틀')
    description = models.TextField(verbose_name='결과 설명')
    result_data = models.JSONField(default=dict, verbose_name='상세 결과')
    game_data = models.JSONField(default=dict, verbose_name='게임 문항과 답변')
    is_favorite = models.BooleanField(default=False, verbose_name='즐겨찾기')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='최초 저장일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='최근 수정일')

    class Meta:
        verbose_name = '회원 즉석 게임 결과'
        verbose_name_plural = '회원 즉석 게임 결과 목록'
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'game_token'],
                name='unique_saved_instant_result_per_user',
            )
        ]

    def __str__(self) -> str:
        return f'{self.user} - {self.topic} ({self.mbti})'


class ChoiceComparisonInvite(models.Model):
    class Status(models.TextChoices):
        OPEN = 'OPEN', '참여 대기'
        COMPLETED = 'COMPLETED', '비교 완료'

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name='초대 코드',
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_choice_invites',
        verbose_name='초대한 회원',
    )
    source_result = models.ForeignKey(
        SavedInstantResult,
        on_delete=models.CASCADE,
        related_name='comparison_invites',
        verbose_name='초대 원본 결과',
    )
    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='joined_choice_invites',
        verbose_name='참여 회원',
    )
    participant_answers = models.JSONField(default=list, verbose_name='참여자 답변')
    participant_result = models.JSONField(default=dict, verbose_name='참여자 결과')
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.OPEN,
        verbose_name='상태',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='초대 생성일')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='비교 완료일')

    class Meta:
        verbose_name = '친구·연인 함께하기 초대'
        verbose_name_plural = '친구·연인 함께하기 초대 목록'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.creator}의 {self.source_result.topic} 초대'


class ResultTemplate(models.Model):
    grade = models.CharField(
        max_length=30,
        choices=ResultGrade.choices,
        verbose_name='등급',
    )
    title = models.CharField(max_length=200, verbose_name='제목 템플릿')
    description = models.TextField(verbose_name='설명 템플릿')
    keywords = models.JSONField(default=list, verbose_name='키워드')
    share_text = models.CharField(max_length=300, verbose_name='공유 문구 템플릿')
    is_active = models.BooleanField(default=True, verbose_name='활성화')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')

    class Meta:
        verbose_name = '결과 템플릿'
        verbose_name_plural = '결과 템플릿 목록'
        ordering = ['grade', '-created_at']

    def __str__(self) -> str:
        return f'[{self.get_grade_display()}] {self.title}'

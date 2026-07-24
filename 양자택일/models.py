from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models


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


class Question(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='questions',
        verbose_name='카테고리',
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

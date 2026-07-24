from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.html import format_html, format_html_join

from .models import Category, Choice, GameSet, Question, ResultTemplate, Vote


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 0
    min_num = 2
    max_num = 2
    fields = ['code', 'text', 'vote_count']
    readonly_fields = ['vote_count']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'question_count', 'created_at']
    prepopulated_fields = {'slug': ('name',)}

    @admin.display(description='질문 수')
    def question_count(self, obj: Category) -> int:
        return obj.questions.count()


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = [
        'title',
        'category',
        'game_set',
        'is_active',
        'vote_total',
        'view_count',
        'created_at',
    ]
    list_filter = ['is_active', 'category', 'game_set__status']
    search_fields = ['title']
    list_editable = ['is_active']
    readonly_fields = ['view_count', 'created_at', 'updated_at']
    inlines = [ChoiceInline]

    @admin.display(description='총 투표수')
    def vote_total(self, obj: Question) -> int:
        return obj.total_votes()


@admin.register(GameSet)
class GameSetAdmin(admin.ModelAdmin):
    list_display = [
        'title',
        'creator',
        'category',
        'question_count',
        'content_basis',
        'status',
        'created_at',
    ]
    list_filter = ['status', 'content_basis', 'category', 'created_at']
    search_fields = ['title', 'description', 'creator__username', 'creator__email']
    readonly_fields = [
        'creator',
        'category',
        'status',
        'created_at',
        'updated_at',
        'reviewed_by',
        'reviewed_at',
        'questions_preview',
    ]
    actions = ['approve_selected', 'reject_selected']
    fieldsets = [
        ('제출 정보', {'fields': ['creator', 'category', 'title', 'description']}),
        ('제출 문항', {'fields': ['questions_preview']}),
        ('근거와 검수', {
            'fields': [
                'content_basis',
                'reference_url',
                'status',
                'moderation_note',
                'reviewed_by',
                'reviewed_at',
            ]
        }),
        ('메타', {'fields': ['created_at', 'updated_at']}),
    ]

    @admin.display(description='문항 수')
    def question_count(self, obj: GameSet) -> int:
        return obj.questions.count()

    @admin.display(description='문항 미리보기')
    def questions_preview(self, obj: GameSet) -> str:
        if not obj.pk:
            return '-'
        rows = []
        for index, question in enumerate(
            obj.questions.prefetch_related('choices').all(),
            start=1,
        ):
            choices = {choice.code: choice.text for choice in question.choices.all()}
            rows.append((
                index,
                question.title,
                choices.get('A', '-'),
                choices.get('B', '-'),
            ))
        if not rows:
            return '등록된 문항이 없습니다.'
        return format_html(
            '<ol style="padding-left:20px">{}</ol>',
            format_html_join(
                '',
                '<li style="margin-bottom:14px"><strong>{}. {}</strong><br>'
                '<span style="color:#dc3545">A. {}</span><br>'
                '<span style="color:#0d6efd">B. {}</span></li>',
                rows,
            ),
        )

    def has_add_permission(self, request) -> bool:  # type: ignore[override]
        return False

    @admin.action(description='선택한 게임 세트 승인')
    def approve_selected(self, request, queryset) -> None:
        approved = 0
        for game_set in queryset:
            try:
                with transaction.atomic():
                    game_set.approve(request.user)
                approved += 1
            except ValidationError as exc:
                self.message_user(
                    request,
                    f'"{game_set.title}" 승인 실패: {" ".join(exc.messages)}',
                    level=messages.ERROR,
                )
        if approved:
            self.message_user(request, f'{approved}개 게임 세트를 승인했습니다.')

    @admin.action(description='선택한 게임 세트 반려')
    def reject_selected(self, request, queryset) -> None:
        rejected = 0
        for game_set in queryset:
            with transaction.atomic():
                game_set.reject(
                    request.user,
                    note=game_set.moderation_note or '콘텐츠 정책 또는 검증 기준을 충족하지 못했습니다.',
                )
            rejected += 1
        if rejected:
            self.message_user(request, f'{rejected}개 게임 세트를 반려했습니다.')


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ['question', 'choice', 'session_key_short', 'created_at']
    list_filter = ['choice__code', 'question__category']
    readonly_fields = ['question', 'choice', 'session_key', 'created_at']

    @admin.display(description='세션 키')
    def session_key_short(self, obj: Vote) -> str:
        return obj.session_key[:12] + '…'

    def has_add_permission(self, request):  # type: ignore[override]
        return False


@admin.register(ResultTemplate)
class ResultTemplateAdmin(admin.ModelAdmin):
    list_display = ['grade', 'title_preview', 'is_active', 'keyword_preview', 'created_at']
    list_filter = ['grade', 'is_active']
    list_editable = ['is_active']
    search_fields = ['title']
    readonly_fields = ['result_preview', 'created_at']
    fieldsets = [
        (None, {'fields': ['grade', 'is_active']}),
        ('템플릿', {'fields': ['title', 'description', 'keywords', 'share_text']}),
        ('미리보기', {'fields': ['result_preview']}),
        ('메타', {'fields': ['created_at']}),
    ]

    @admin.display(description='제목')
    def title_preview(self, obj: ResultTemplate) -> str:
        return obj.title[:40] + ('…' if len(obj.title) > 40 else '')

    @admin.display(description='키워드')
    def keyword_preview(self, obj: ResultTemplate) -> str:
        return ', '.join(obj.keywords[:3]) if obj.keywords else '-'

    @admin.display(description='미리보기')
    def result_preview(self, obj: ResultTemplate) -> str:
        return format_html(
            '<div style="padding:12px;background:#f8f9fa;border-radius:6px;line-height:1.8">'
            '<strong>제목:</strong> {}<br>'
            '<strong>설명:</strong> {}<br>'
            '<strong>키워드:</strong> {}<br>'
            '<strong>공유 문구:</strong> {}'
            '</div>',
            obj.title,
            obj.description,
            ', '.join(obj.keywords) if obj.keywords else '-',
            obj.share_text,
        )

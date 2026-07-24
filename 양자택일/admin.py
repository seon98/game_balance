from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html

from .models import Category, Choice, Question, ResultTemplate, Vote


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
    list_display = ['title', 'category', 'is_active', 'vote_total', 'view_count', 'created_at']
    list_filter = ['is_active', 'category']
    search_fields = ['title']
    list_editable = ['is_active']
    readonly_fields = ['view_count', 'created_at', 'updated_at']
    inlines = [ChoiceInline]

    @admin.display(description='총 투표수')
    def vote_total(self, obj: Question) -> int:
        return obj.total_votes()


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

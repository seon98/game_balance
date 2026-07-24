from __future__ import annotations

import dataclasses
from typing import Any

from django.contrib import messages
from django.db.models import F
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView, TemplateView

from .forms import VoteForm
from .models import Category, Question, ResultGrade, Vote
from .services import TemplateResultGenerator, build_result, get_grade, process_vote


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------

def _ensure_session(request: HttpRequest) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key  # type: ignore[return-value]


def _result_session_key(question_id: int) -> str:
    return f'result_{question_id}'


def _completed_question_ids(request: HttpRequest) -> set[int]:
    session_key = request.session.session_key
    if not session_key:
        return set()
    return set(
        Vote.objects
        .filter(session_key=session_key, question__is_active=True)
        .values_list('question_id', flat=True)
    )


def _next_unplayed_question(request: HttpRequest) -> Question | None:
    session_key = _ensure_session(request)
    completed_ids = Vote.objects.filter(
        session_key=session_key,
        question__is_active=True,
    ).values_list('question_id', flat=True)
    return (
        Question.objects
        .filter(is_active=True)
        .exclude(pk__in=completed_ids)
        .order_by('?')
        .first()
    )


# ---------------------------------------------------------------------------
# 메인 / 목록
# ---------------------------------------------------------------------------

class IndexView(TemplateView):
    template_name = 'index.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['recent_questions'] = (
            Question.objects
            .filter(is_active=True)
            .select_related('category')
            .prefetch_related('choices')
            .order_by('-created_at')[:6]
        )
        context['categories'] = Category.objects.all()
        context['total_questions'] = Question.objects.filter(is_active=True).count()
        completed_ids = _completed_question_ids(self.request)
        context['completed_question_ids'] = completed_ids
        context['completed_questions'] = len(completed_ids)
        context['remaining_questions'] = max(
            context['total_questions'] - len(completed_ids),
            0,
        )
        return context


class GameListView(ListView):
    template_name = 'games/list.html'
    context_object_name = 'questions'
    paginate_by = 12

    def get_queryset(self):
        return (
            Question.objects
            .filter(is_active=True)
            .select_related('category')
            .prefetch_related('choices')
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()
        context['completed_question_ids'] = _completed_question_ids(self.request)
        return context


class CategoryListView(ListView):
    template_name = 'categories/list.html'
    context_object_name = 'questions'
    paginate_by = 12

    def get_queryset(self):
        self.category = get_object_or_404(Category, slug=self.kwargs['slug'])
        return (
            Question.objects
            .filter(is_active=True, category=self.category)
            .prefetch_related('choices')
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        context['categories'] = Category.objects.all()
        context['completed_question_ids'] = _completed_question_ids(self.request)
        return context


# ---------------------------------------------------------------------------
# 랜덤 게임
# ---------------------------------------------------------------------------

class RandomGameView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        question = _next_unplayed_question(request)
        if question is None:
            if Question.objects.filter(is_active=True).exists():
                messages.success(request, '준비된 밸런스게임을 모두 완료했어요!')
                return redirect('games:progress')
            messages.info(request, '등록된 게임이 없습니다.')
            return redirect('games:list')
        return redirect('games:detail', question_id=question.pk)


# ---------------------------------------------------------------------------
# 질문 상세
# ---------------------------------------------------------------------------

class QuestionDetailView(View):
    def get(self, request: HttpRequest, question_id: int) -> HttpResponse:
        question = get_object_or_404(
            Question.objects
            .filter(is_active=True)
            .prefetch_related('choices')
            .select_related('category'),
            pk=question_id,
        )

        Question.objects.filter(pk=question_id).update(view_count=F('view_count') + 1)

        session_key = request.session.session_key
        if session_key:
            already_voted = Vote.objects.filter(
                question=question,
                session_key=session_key,
            ).exists()
            if already_voted:
                return redirect('games:result', question_id=question_id)

        choices = list(question.choices.all())
        return render(request, 'games/detail.html', {
            'question': question,
            'choices': choices,
            'categories': Category.objects.all(),
        })


# ---------------------------------------------------------------------------
# 투표 처리
# ---------------------------------------------------------------------------

class VoteView(View):
    def get(self, request: HttpRequest, question_id: int) -> HttpResponse:
        return redirect('games:detail', question_id=question_id)

    def post(self, request: HttpRequest, question_id: int) -> HttpResponse:
        question = get_object_or_404(
            Question.objects
            .filter(is_active=True)
            .prefetch_related('choices'),
            pk=question_id,
        )

        session_key = _ensure_session(request)

        existing_vote = (
            Vote.objects
            .filter(question=question, session_key=session_key)
            .select_related('choice')
            .first()
        )
        if existing_vote is not None:
            return redirect('games:result', question_id=question_id)

        form = VoteForm(request.POST, question=question)
        if not form.is_valid():
            messages.error(request, '올바른 선택지를 선택해주세요.')
            return redirect('games:detail', question_id=question_id)

        choice = form.cleaned_data['choice']

        try:
            vote, created = process_vote(question, choice, session_key)
        except Exception:
            messages.error(request, '투표 처리 중 오류가 발생했습니다. 다시 시도해주세요.')
            return redirect('games:detail', question_id=question_id)

        # vote_count 갱신 후 결과 생성
        question.choices.all()  # prefetch 캐시 무효화를 위해 재조회
        question = get_object_or_404(
            Question.objects.prefetch_related('choices'),
            pk=question_id,
        )
        voted_choice_id = vote.choice_id

        try:
            result = build_result(
                question=question,
                voted_choice_id=voted_choice_id,
                generator=TemplateResultGenerator(),
            )
        except Exception:
            messages.error(request, '결과 생성 중 오류가 발생했습니다.')
            return redirect('games:detail', question_id=question_id)

        request.session[_result_session_key(question_id)] = dataclasses.asdict(result)

        return redirect('games:result', question_id=question_id)


# ---------------------------------------------------------------------------
# 결과 페이지
# ---------------------------------------------------------------------------

class ResultView(View):
    def get(self, request: HttpRequest, question_id: int) -> HttpResponse:
        question = get_object_or_404(
            Question.objects
            .prefetch_related('choices')
            .select_related('category'),
            pk=question_id,
        )

        result_data: dict | None = request.session.get(_result_session_key(question_id))

        if result_data is None:
            session_key = request.session.session_key
            if session_key:
                vote = (
                    Vote.objects
                    .filter(question=question, session_key=session_key)
                    .select_related('choice')
                    .first()
                )
                if vote is not None:
                    try:
                        result = build_result(
                            question=question,
                            voted_choice_id=vote.choice_id,
                            generator=TemplateResultGenerator(),
                        )
                        result_data = dataclasses.asdict(result)
                        request.session[_result_session_key(question_id)] = result_data
                    except Exception:
                        messages.error(request, '결과 생성 중 오류가 발생했습니다.')
                        return redirect('games:detail', question_id=question_id)
                else:
                    messages.info(request, '먼저 투표해주세요.')
                    return redirect('games:detail', question_id=question_id)
            else:
                messages.info(request, '먼저 투표해주세요.')
                return redirect('games:detail', question_id=question_id)

        next_question = _next_unplayed_question(request)

        choices = list(question.choices.all())

        return render(request, 'games/result.html', {
            'question': question,
            'result': result_data,
            'choices': choices,
            'next_question': next_question,
            'categories': Category.objects.all(),
        })


# ---------------------------------------------------------------------------
# 나의 플레이 기록
# ---------------------------------------------------------------------------

class ProgressView(TemplateView):
    template_name = 'games/progress.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        session_key = self.request.session.session_key

        votes = []
        completed_ids: set[int] = set()
        if session_key:
            votes = list(
                Vote.objects
                .filter(session_key=session_key, question__is_active=True)
                .select_related('question', 'question__category', 'choice')
                .prefetch_related('question__choices')
                .order_by('-created_at')
            )
            completed_ids = {vote.question_id for vote in votes}

        questions = list(
            Question.objects
            .filter(is_active=True)
            .select_related('category')
        )
        total_questions = len(questions)
        completed_questions = len(completed_ids)
        remaining_questions = max(total_questions - completed_questions, 0)
        completion_percentage = (
            round(completed_questions / total_questions * 100)
            if total_questions
            else 0
        )

        category_progress: list[dict[str, Any]] = []
        categories = list(Category.objects.all())
        for category in categories:
            category_question_ids = {
                question.pk for question in questions
                if question.category_id == category.pk
            }
            category_total = len(category_question_ids)
            category_completed = len(category_question_ids & completed_ids)
            category_progress.append({
                'category': category,
                'total': category_total,
                'completed': category_completed,
                'remaining': max(category_total - category_completed, 0),
                'percentage': (
                    round(category_completed / category_total * 100)
                    if category_total
                    else 0
                ),
            })

        recent_results: list[dict[str, Any]] = []
        for vote in votes:
            choices = list(vote.question.choices.all())
            total_votes = sum(choice.vote_count for choice in choices)
            percentage = (
                round(vote.choice.vote_count / total_votes * 100, 1)
                if total_votes
                else 50.0
            )
            grade = get_grade(percentage)
            recent_results.append({
                'vote': vote,
                'percentage': percentage,
                'grade': grade,
                'grade_display': ResultGrade(grade).label,
            })

        context.update({
            'categories': categories,
            'total_questions': total_questions,
            'completed_questions': completed_questions,
            'remaining_questions': remaining_questions,
            'completion_percentage': completion_percentage,
            'category_progress': category_progress,
            'recent_results': recent_results,
            'all_completed': total_questions > 0 and remaining_questions == 0,
        })
        return context

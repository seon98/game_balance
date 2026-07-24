from __future__ import annotations

import dataclasses
import hashlib
import re
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Prefetch, Q, QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.csrf import csrf_failure as default_csrf_failure
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import CreateView, ListView, TemplateView

from .forms import (
    GameQuestionFormSet,
    GameSetForm,
    InstantGameSearchForm,
    NicknameForm,
    QuestionDraftGeneratorForm,
    SignupForm,
    VoteForm,
)
from .models import Category, Choice, GameSet, Question, ResultGrade, Vote
from .moderation import requires_reference
from .question_generator import generate_question_drafts_with_fallback
from .services import (
    TemplateResultGenerator,
    build_choice_pattern_result,
    build_game_set_result,
    build_result,
    get_grade,
    process_vote,
    undo_last_vote,
)

_INSTANT_GAME_SESSION_KEY = 'instant_game'


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------

def csrf_failure(
    request: HttpRequest,
    reason: str = '',
) -> HttpResponse:
    instant_answer = re.fullmatch(
        r'/instant-game/(?P<question_number>\d+)/answer/',
        request.path_info,
    )
    if request.method == 'POST' and instant_answer:
        question_number = int(instant_answer.group('question_number'))
        play_url = reverse(
            'games:instant_play',
            kwargs={'question_number': question_number},
        )
        return redirect(f'{play_url}?security=refreshed')
    return default_csrf_failure(request, reason=reason)


def _ensure_session(request: HttpRequest) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key  # type: ignore[return-value]


def _result_session_key(question_id: int) -> str:
    return f'result_{question_id}'


def _get_instant_game(request: HttpRequest) -> dict[str, Any] | None:
    game = request.session.get(_INSTANT_GAME_SESSION_KEY)
    if not isinstance(game, dict):
        return None

    questions = game.get('questions')
    answers = game.get('answers')
    if (
        not isinstance(questions, list)
        or not 7 <= len(questions) <= 10
        or not isinstance(answers, list)
        or len(answers) != len(questions)
    ):
        request.session.pop(_INSTANT_GAME_SESSION_KEY, None)
        return None

    required_fields = {'title', 'description', 'choice_a', 'choice_b'}
    if any(
        not isinstance(question, dict)
        or not required_fields.issubset(question)
        for question in questions
    ):
        request.session.pop(_INSTANT_GAME_SESSION_KEY, None)
        return None
    return game


def _public_questions() -> QuerySet[Question]:
    return (
        Question.objects
        .filter(is_active=True)
        .filter(
            Q(game_set__isnull=True)
            | Q(game_set__status=GameSet.Status.APPROVED)
        )
    )


def _public_game_sets() -> QuerySet[GameSet]:
    return (
        GameSet.objects
        .filter(status=GameSet.Status.APPROVED)
        .select_related('category', 'creator')
        .prefetch_related(
            Prefetch(
                'questions',
                queryset=_public_questions()
                .prefetch_related('choices')
                .order_by('pk'),
                to_attr='public_questions',
            )
        )
    )


def _add_game_set_progress(
    game_sets: list[GameSet],
    completed_ids: set[int],
) -> None:
    for game_set in game_sets:
        questions = game_set.public_questions
        game_set.question_count = len(questions)
        game_set.completed_count = sum(
            question.pk in completed_ids
            for question in questions
        )
        game_set.completion_percentage = (
            round(game_set.completed_count / game_set.question_count * 100)
            if game_set.question_count
            else 0
        )


def _completed_question_ids(request: HttpRequest) -> set[int]:
    session_key = request.session.session_key
    if not session_key:
        return set()
    return set(
        Vote.objects
        .filter(
            session_key=session_key,
            question__in=_public_questions(),
        )
        .values_list('question_id', flat=True)
    )


def _next_unplayed_question(
    request: HttpRequest,
    game_set: GameSet | None = None,
) -> Question | None:
    session_key = _ensure_session(request)
    completed_ids = Vote.objects.filter(
        session_key=session_key,
        question__in=_public_questions(),
    ).values_list('question_id', flat=True)
    questions = _public_questions().exclude(pk__in=completed_ids)
    if game_set is not None:
        questions = questions.filter(game_set=game_set)
        return questions.order_by('pk').first()
    return questions.order_by('?').first()


def _redirect_after_vote(
    request: HttpRequest,
    question: Question,
) -> HttpResponse:
    if question.game_set:
        next_question = _next_unplayed_question(request, question.game_set)
        if next_question is not None:
            return redirect('games:detail', question_id=next_question.pk)
        return redirect(
            'games:game_set_result',
            game_set_id=question.game_set_id,
        )
    return redirect('games:result', question_id=question.pk)


# ---------------------------------------------------------------------------
# 메인 / 목록
# ---------------------------------------------------------------------------

class WelcomeView(TemplateView):
    template_name = 'welcome.html'


@method_decorator(ensure_csrf_cookie, name='dispatch')
class IndexView(TemplateView):
    template_name = 'index.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        featured_game_sets = list(_public_game_sets().order_by('-is_official', '-created_at')[:6])
        context['categories'] = Category.objects.all()
        context['total_questions'] = _public_questions().count()
        completed_ids = _completed_question_ids(self.request)
        _add_game_set_progress(featured_game_sets, completed_ids)
        context['featured_game_sets'] = featured_game_sets
        context['total_game_sets'] = _public_game_sets().count()
        context['completed_question_ids'] = completed_ids
        context['completed_questions'] = len(completed_ids)
        context['remaining_questions'] = max(
            context['total_questions'] - len(completed_ids),
            0,
        )
        previous_query = self.request.session.pop('instant_game_query', '')
        context['instant_search_form'] = InstantGameSearchForm(
            initial={'keywords': previous_query},
        )
        context['recommended_keywords'] = [
            '여행',
            '연애',
            '직장',
            '음식',
            '친구',
        ]
        return context


class InstantGameGenerateView(View):
    question_count = 7

    def post(self, request: HttpRequest) -> HttpResponse:
        form = InstantGameSearchForm(request.POST)
        if not form.is_valid():
            errors = [
                str(message)
                for field_errors in form.errors.values()
                for message in field_errors
            ]
            request.session['instant_game_query'] = request.POST.get('keywords', '')[:160]
            messages.error(
                request,
                ' '.join(errors) or '플레이할 키워드를 다시 확인해주세요.',
            )
            return redirect('games:index')

        if settings.OPENAI_API_KEY:
            session_key = _ensure_session(request)
            session_hash = hashlib.sha256(session_key.encode()).hexdigest()
            cooldown_key = f'instant-game-generation:{session_hash}'
            if not cache.add(
                cooldown_key,
                True,
                timeout=settings.OPENAI_GENERATION_COOLDOWN,
            ):
                messages.info(
                    request,
                    f'새 게임은 {settings.OPENAI_GENERATION_COOLDOWN}초 후 다시 만들 수 있어요.',
                )
                return redirect('games:index')

        keywords = form.cleaned_data['keywords']
        try:
            result = generate_question_drafts_with_fallback(
                api_key=settings.OPENAI_API_KEY,
                model=settings.OPENAI_MODEL,
                timeout=settings.OPENAI_TIMEOUT,
                keywords=keywords,
                count=self.question_count,
                category_name='맞춤 주제',
            )
        except (ValidationError, ValueError):
            messages.error(
                request,
                '안전한 게임을 만들지 못했습니다. 다른 키워드로 다시 시도해주세요.',
            )
            return redirect('games:index')

        drafts = result.get('drafts')
        if not isinstance(drafts, list) or len(drafts) != self.question_count:
            messages.error(request, '게임 문항을 완성하지 못했습니다. 다시 시도해주세요.')
            return redirect('games:index')

        request.session[_INSTANT_GAME_SESSION_KEY] = {
            'title': result.get('title_suggestion', '나만의 양자택일'),
            'description': result.get('description_suggestion', ''),
            'keywords': keywords,
            'questions': drafts,
            'answers': [None] * len(drafts),
            'source': result.get('source', 'local'),
        }
        return redirect('games:instant_play', question_number=1)


@method_decorator(ensure_csrf_cookie, name='dispatch')
class InstantGamePlayView(TemplateView):
    template_name = 'games/instant_play.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        game = _get_instant_game(self.request)
        if game is None:
            context['missing_game'] = True
            return context

        question_number = self.kwargs['question_number']
        question_index = question_number - 1
        questions = game['questions']
        answers = game['answers']
        if question_index not in range(len(questions)):
            context['invalid_question'] = True
            return context

        first_unanswered = next(
            (index for index, answer in enumerate(answers) if answer is None),
            len(answers),
        )
        if question_index > first_unanswered:
            context['next_required_question'] = first_unanswered + 1
            return context

        context.update({
            'instant_game': game,
            'question': questions[question_index],
            'question_number': question_number,
            'question_count': len(questions),
            'completed_count': sum(answer is not None for answer in answers),
            'selected_choice': answers[question_index],
            'previous_question_number': (
                question_number - 1
                if question_number > 1
                else None
            ),
            'categories': Category.objects.all(),
            'security_refreshed': (
                self.request.GET.get('security') == 'refreshed'
            ),
        })
        return context

    def render_to_response(
        self,
        context: dict[str, Any],
        **response_kwargs: Any,
    ) -> HttpResponse:
        if context.get('missing_game'):
            messages.info(self.request, '메인에서 키워드를 입력해 게임을 먼저 만들어주세요.')
            return redirect('games:index')
        if context.get('invalid_question'):
            return redirect('games:instant_play', question_number=1)
        if context.get('next_required_question'):
            return redirect(
                'games:instant_play',
                question_number=context['next_required_question'],
            )
        return super().render_to_response(context, **response_kwargs)


class InstantGameAnswerView(View):
    def post(self, request: HttpRequest, question_number: int) -> HttpResponse:
        game = _get_instant_game(request)
        if game is None:
            messages.info(request, '메인에서 키워드를 입력해 게임을 먼저 만들어주세요.')
            return redirect('games:index')

        question_index = question_number - 1
        questions = game['questions']
        answers = game['answers']
        if question_index not in range(len(questions)):
            return redirect('games:instant_play', question_number=1)

        earlier_missing = next(
            (
                index
                for index, answer in enumerate(answers[:question_index])
                if answer is None
            ),
            None,
        )
        if earlier_missing is not None:
            return redirect(
                'games:instant_play',
                question_number=earlier_missing + 1,
            )

        choice_code = request.POST.get('choice')
        if choice_code not in Choice.Code.values:
            messages.error(request, 'A 또는 B 중 하나를 선택해주세요.')
            return redirect(
                'games:instant_play',
                question_number=question_number,
            )

        answers[question_index] = choice_code
        request.session.modified = True
        if question_number < len(questions):
            return redirect(
                'games:instant_play',
                question_number=question_number + 1,
            )
        if all(answer is not None for answer in answers):
            return redirect('games:instant_result')

        next_unanswered = answers.index(None)
        return redirect(
            'games:instant_play',
            question_number=next_unanswered + 1,
        )


class InstantGameResultView(TemplateView):
    template_name = 'games/instant_result.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        game = _get_instant_game(self.request)
        if game is None:
            context['missing_game'] = True
            return context

        answers = game['answers']
        if any(answer is None for answer in answers):
            context['next_required_question'] = answers.index(None) + 1
            return context

        answer_items = []
        for question, choice_code in zip(game['questions'], answers, strict=True):
            choice_field = 'choice_a' if choice_code == Choice.Code.A else 'choice_b'
            answer_items.append({
                'question': question,
                'choice': {
                    'code': choice_code,
                    'text': question[choice_field],
                },
            })

        display_name = (
            self.request.user.username
            if self.request.user.is_authenticated
            else '플레이어'
        )
        context.update({
            'instant_game': game,
            'set_result': build_choice_pattern_result(
                display_name=display_name,
                choice_codes=answers,
            ),
            'answer_items': answer_items,
            'categories': Category.objects.all(),
        })
        return context

    def render_to_response(
        self,
        context: dict[str, Any],
        **response_kwargs: Any,
    ) -> HttpResponse:
        if context.get('missing_game'):
            messages.info(self.request, '메인에서 키워드를 입력해 게임을 먼저 만들어주세요.')
            return redirect('games:index')
        if context.get('next_required_question'):
            messages.info(self.request, '모든 질문에 답하면 유형 결과를 확인할 수 있어요.')
            return redirect(
                'games:instant_play',
                question_number=context['next_required_question'],
            )
        return super().render_to_response(context, **response_kwargs)


class GameListView(ListView):
    template_name = 'games/list.html'
    context_object_name = 'game_sets'
    paginate_by = 12

    def get_queryset(self):
        return _public_game_sets()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()
        _add_game_set_progress(
            list(context['game_sets']),
            _completed_question_ids(self.request),
        )
        return context


class CategoryListView(ListView):
    template_name = 'categories/list.html'
    context_object_name = 'game_sets'
    paginate_by = 12

    def get_queryset(self):
        self.category = get_object_or_404(Category, slug=self.kwargs['slug'])
        return _public_game_sets().filter(category=self.category)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        context['categories'] = Category.objects.all()
        _add_game_set_progress(
            list(context['game_sets']),
            _completed_question_ids(self.request),
        )
        return context


# ---------------------------------------------------------------------------
# 랜덤 게임
# ---------------------------------------------------------------------------

class RandomGameView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        completed_ids = _completed_question_ids(request)
        game_sets = list(_public_game_sets().order_by('?'))
        _add_game_set_progress(game_sets, completed_ids)
        game_set = next(
            (
                candidate for candidate in game_sets
                if candidate.completed_count < candidate.question_count
            ),
            None,
        )
        if game_set is None:
            legacy_question = _next_unplayed_question(request)
            if legacy_question:
                return redirect('games:detail', question_id=legacy_question.pk)
            if _public_questions().exists():
                messages.success(request, '준비된 밸런스게임을 모두 완료했어요!')
                return redirect('games:progress')
            messages.info(request, '등록된 게임이 없습니다.')
            return redirect('games:list')
        return redirect('games:game_set_detail', game_set_id=game_set.pk)


# ---------------------------------------------------------------------------
# 질문 상세
# ---------------------------------------------------------------------------

class QuestionDetailView(View):
    def get(self, request: HttpRequest, question_id: int) -> HttpResponse:
        question = get_object_or_404(
            _public_questions()
            .prefetch_related('choices')
            .select_related('category', 'game_set', 'game_set__creator'),
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
                return _redirect_after_vote(request, question)

        choices = list(question.choices.all())
        question_number = None
        question_count = None
        completed_count = 0
        has_previous_vote = False
        if question.game_set:
            question_ids = list(
                _public_questions()
                .filter(game_set=question.game_set)
                .order_by('pk')
                .values_list('pk', flat=True)
            )
            question_count = len(question_ids)
            if question.pk in question_ids:
                question_number = question_ids.index(question.pk) + 1
            if session_key:
                completed_count = Vote.objects.filter(
                    session_key=session_key,
                    question_id__in=question_ids,
                ).count()
                has_previous_vote = completed_count > 0

        return render(request, 'games/detail.html', {
            'question': question,
            'choices': choices,
            'categories': Category.objects.all(),
            'question_number': question_number,
            'question_count': question_count,
            'completed_count': completed_count,
            'has_previous_vote': has_previous_vote,
        })


# ---------------------------------------------------------------------------
# 투표 처리
# ---------------------------------------------------------------------------

class VoteView(View):
    def get(self, request: HttpRequest, question_id: int) -> HttpResponse:
        return redirect('games:detail', question_id=question_id)

    def post(self, request: HttpRequest, question_id: int) -> HttpResponse:
        question = get_object_or_404(
            _public_questions()
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
            return _redirect_after_vote(request, question)

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

        return _redirect_after_vote(request, question)


# ---------------------------------------------------------------------------
# 결과 페이지
# ---------------------------------------------------------------------------

class ResultView(View):
    def get(self, request: HttpRequest, question_id: int) -> HttpResponse:
        question = get_object_or_404(
            _public_questions()
            .prefetch_related('choices')
            .select_related('category', 'game_set', 'game_set__creator'),
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

        same_set_next = None
        if question.game_set:
            same_set_next = _next_unplayed_question(request, question.game_set)
        next_question = same_set_next or _next_unplayed_question(request)

        choices = list(question.choices.all())

        return render(request, 'games/result.html', {
            'question': question,
            'result': result_data,
            'choices': choices,
            'next_question': next_question,
            'next_is_same_set': same_set_next is not None,
            'game_set_completed': bool(question.game_set and same_set_next is None),
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
                .filter(
                    session_key=session_key,
                    question__in=_public_questions(),
                )
                .select_related('question', 'question__category', 'choice')
                .prefetch_related('question__choices')
                .order_by('-created_at')
            )
            completed_ids = {vote.question_id for vote in votes}

        questions = list(
            _public_questions()
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


# ---------------------------------------------------------------------------
# 회원 / 사용자 제작 게임
# ---------------------------------------------------------------------------

class SignupView(CreateView):
    form_class = SignupForm
    template_name = 'registration/signup.html'
    success_url = reverse_lazy('games:index')

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect('games:index')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form: SignupForm) -> HttpResponse:
        response = super().form_valid(form)
        login(self.request, self.object)
        messages.success(self.request, '회원가입이 완료되었습니다. 지금 나만의 게임을 만들어보세요!')
        return response


class GameSetCreateView(LoginRequiredMixin, View):
    template_name = 'games/create.html'

    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, self.template_name, {
            'form': GameSetForm(),
            'question_formset': GameQuestionFormSet(prefix='questions'),
            'categories': Category.objects.all(),
        })

    def post(self, request: HttpRequest) -> HttpResponse:
        form = GameSetForm(request.POST)
        question_formset = GameQuestionFormSet(request.POST, prefix='questions')
        form_is_valid = form.is_valid()
        formset_is_valid = question_formset.is_valid()

        if form_is_valid and formset_is_valid:
            question_texts: list[str] = []
            for question_form in question_formset:
                if (
                    not question_form.cleaned_data
                    or question_form.cleaned_data.get('DELETE')
                ):
                    continue
                question_texts.extend([
                    question_form.cleaned_data['title'],
                    question_form.cleaned_data['description'],
                    question_form.cleaned_data['choice_a'],
                    question_form.cleaned_data['choice_b'],
                ])

            if (
                requires_reference(*question_texts)
                and form.cleaned_data['content_basis']
                != GameSet.ContentBasis.SOURCED
            ):
                form.add_error(
                    'content_basis',
                    '문항에 검증이 필요한 표현이 있습니다. 사실·정보형과 근거 URL을 입력해주세요.',
                )

        if form_is_valid and formset_is_valid and not form.errors:
            with transaction.atomic():
                game_set = form.save(commit=False)
                game_set.creator = request.user
                game_set.status = GameSet.Status.PENDING
                game_set.save()

                for question_form in question_formset:
                    if (
                        not question_form.cleaned_data
                        or question_form.cleaned_data.get('DELETE')
                    ):
                        continue
                    question = Question.objects.create(
                        game_set=game_set,
                        category=game_set.category,
                        title=question_form.cleaned_data['title'],
                        description=question_form.cleaned_data['description'],
                        is_active=False,
                    )
                    Choice.objects.bulk_create([
                        Choice(
                            question=question,
                            code=Choice.Code.A,
                            text=question_form.cleaned_data['choice_a'],
                        ),
                        Choice(
                            question=question,
                            code=Choice.Code.B,
                            text=question_form.cleaned_data['choice_b'],
                        ),
                    ])

                game_set.validate_submission()

            messages.success(
                request,
                '게임을 제출했습니다. 안전성과 근거 검수가 끝나면 공개됩니다.',
            )
            return redirect('games:my_creations')

        return render(request, self.template_name, {
            'form': form,
            'question_formset': question_formset,
            'categories': Category.objects.all(),
        })


class QuestionDraftGenerateView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> JsonResponse:
        form = QuestionDraftGeneratorForm(request.POST)
        if not form.is_valid():
            errors = [
                str(message)
                for field_errors in form.errors.values()
                for message in field_errors
            ]
            return JsonResponse(
                {'error': ' '.join(errors) or '입력값을 다시 확인해주세요.'},
                status=400,
            )

        try:
            result = generate_question_drafts_with_fallback(
                api_key=settings.OPENAI_API_KEY,
                model=settings.OPENAI_MODEL,
                timeout=settings.OPENAI_TIMEOUT,
                keywords=form.cleaned_data['keywords'],
                count=form.cleaned_data['count'],
                category_name=form.cleaned_data['category'].name,
            )
        except (ValidationError, ValueError):
            return JsonResponse(
                {'error': '안전한 문항을 만들지 못했습니다. 키워드를 바꿔 다시 시도해주세요.'},
                status=400,
            )
        return JsonResponse(result)


class MyGameSetListView(LoginRequiredMixin, ListView):
    model = GameSet
    template_name = 'games/my_creations.html'
    context_object_name = 'game_sets'

    def get_queryset(self) -> QuerySet[GameSet]:
        return (
            GameSet.objects
            .filter(creator=self.request.user)
            .select_related('category', 'reviewed_by')
            .prefetch_related('questions')
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()
        return context


class PublicGameSetDetailView(TemplateView):
    template_name = 'games/set_detail.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        game_set = get_object_or_404(
            GameSet.objects
            .filter(status=GameSet.Status.APPROVED)
            .select_related('category', 'creator', 'reviewed_by'),
            pk=self.kwargs['game_set_id'],
        )
        questions = list(
            _public_questions()
            .filter(game_set=game_set)
            .prefetch_related('choices')
            .order_by('pk')
        )
        completed_ids = _completed_question_ids(self.request)
        completed_count = sum(
            question.pk in completed_ids
            for question in questions
        )
        next_question = next(
            (
                question for question in questions
                if question.pk not in completed_ids
            ),
            None,
        )

        context.update({
            'game_set': game_set,
            'questions': questions,
            'completed_question_ids': completed_ids,
            'completed_count': completed_count,
            'completion_percentage': (
                round(completed_count / len(questions) * 100)
                if questions
                else 0
            ),
            'next_question': next_question,
            'categories': Category.objects.all(),
            'nickname_form': NicknameForm(),
        })
        return context


class GameSetStartView(View):
    def post(self, request: HttpRequest, game_set_id: int) -> HttpResponse:
        game_set = get_object_or_404(
            GameSet,
            pk=game_set_id,
            status=GameSet.Status.APPROVED,
        )
        form = NicknameForm(request.POST)
        if not form.is_valid():
            messages.error(request, '닉네임을 다시 확인해주세요.')
            return redirect('games:game_set_detail', game_set_id=game_set.pk)
        if not request.user.is_authenticated:
            nickname = form.cleaned_data['nickname'] or '참여자'
            request.session[f'game_set_nickname_{game_set.pk}'] = nickname

        next_question = _next_unplayed_question(request, game_set)
        if next_question is not None:
            return redirect('games:detail', question_id=next_question.pk)

        if game_set.questions.filter(is_active=True).exists():
            return redirect('games:game_set_result', game_set_id=game_set.pk)

        messages.info(request, '공개된 질문이 없습니다.')
        return redirect('games:game_set_detail', game_set_id=game_set.pk)


class GameSetUndoLastVoteView(View):
    def post(self, request: HttpRequest, game_set_id: int) -> HttpResponse:
        game_set = get_object_or_404(
            GameSet,
            pk=game_set_id,
            status=GameSet.Status.APPROVED,
        )
        session_key = request.session.session_key
        question_id = (
            undo_last_vote(game_set=game_set, session_key=session_key)
            if session_key
            else None
        )
        if question_id is None:
            messages.info(request, '수정할 이전 선택이 없습니다.')
            return redirect('games:game_set_detail', game_set_id=game_set.pk)

        request.session.pop(_result_session_key(question_id), None)
        messages.info(request, '이전 선택을 취소했습니다. 다시 선택해주세요.')
        return redirect('games:detail', question_id=question_id)


class GameSetResultView(TemplateView):
    template_name = 'games/set_result.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        game_set = get_object_or_404(
            GameSet.objects
            .filter(status=GameSet.Status.APPROVED)
            .select_related('category', 'creator'),
            pk=self.kwargs['game_set_id'],
        )
        questions = list(
            _public_questions()
            .filter(game_set=game_set)
            .order_by('pk')
        )
        session_key = self.request.session.session_key
        votes = []
        if session_key:
            votes = list(
                Vote.objects
                .filter(
                    session_key=session_key,
                    question__in=questions,
                )
                .select_related('question', 'choice')
                .order_by('question_id')
            )

        if not questions or len(votes) != len(questions):
            messages.info(self.request, '모든 질문에 답하면 유형 결과를 확인할 수 있어요.')
            context['incomplete_redirect'] = True
            context['game_set'] = game_set
            return context

        if self.request.user.is_authenticated:
            display_name = self.request.user.username
        else:
            display_name = self.request.session.get(
                f'game_set_nickname_{game_set.pk}',
                '참여자',
            )

        context.update({
            'game_set': game_set,
            'set_result': build_game_set_result(
                display_name=display_name,
                votes=votes,
            ),
            'votes': votes,
            'categories': Category.objects.all(),
        })
        return context

    def render_to_response(
        self,
        context: dict[str, Any],
        **response_kwargs: Any,
    ) -> HttpResponse:
        if context.get('incomplete_redirect'):
            return redirect(
                'games:game_set_detail',
                game_set_id=context['game_set'].pk,
            )
        return super().render_to_response(context, **response_kwargs)

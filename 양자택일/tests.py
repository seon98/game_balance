from __future__ import annotations

from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    Category,
    Choice,
    ChoiceComparisonInvite,
    GameSet,
    MemberGameEvent,
    Question,
    ResultGrade,
    ResultTemplate,
    SavedInstantResult,
    RecommendationFeedback,
    Vote,
)
from .openai_question_generator import (
    GeneratedQuestionSet,
    generate_openai_question_drafts,
)
from .openai_mbti_analyzer import (
    GeneratedMbtiAnalysis,
    analyze_mbti_with_fallback,
    analyze_openai_mbti,
)
from .question_generator import generate_question_drafts_with_fallback
from .services import (
    ResultData,
    TemplateResultGenerator,
    build_game_set_result,
    build_result,
    get_grade,
    process_vote,
)


# ---------------------------------------------------------------------------
# 픽스처 헬퍼
# ---------------------------------------------------------------------------

def make_question(title: str = '테스트 질문', active: bool = True) -> Question:
    cat, _ = Category.objects.get_or_create(name='테스트', slug='test')
    question = Question.objects.create(title=title, category=cat, is_active=active)
    Choice.objects.create(question=question, code='A', text='선택지 A')
    Choice.objects.create(question=question, code='B', text='선택지 B')
    return question


def make_generated_question_draft(
    index: int,
    *,
    unsafe: bool = False,
) -> dict[str, str]:
    axis, choice_a_trait, choice_b_trait = (
        ('E/I', 'E', 'I'),
        ('S/N', 'S', 'N'),
        ('T/F', 'T', 'F'),
        ('J/P', 'J', 'P'),
    )[(index - 1) % 4]
    return {
        'title': f'여행 질문 {index}',
        'description': f'여행 상황 {index}에서 선택하세요.',
        'choice_a': '19금 여행을 선택한다' if unsafe else f'여행 선택 A-{index}',
        'choice_b': f'여행 선택 B-{index}',
        'mbti_axis': axis,
        'choice_a_trait': choice_a_trait,
        'choice_b_trait': choice_b_trait,
    }


def make_saved_member_result(
    user,
    *,
    token: str = 'a' * 32,
    topic: str = '여행 선택 보고서',
    mbti: str = 'ENTJ',
    answers: list[str] | None = None,
) -> SavedInstantResult:
    questions = [
        make_generated_question_draft(index)
        for index in range(1, 8)
    ]
    selected_answers = answers or ['A', 'A', 'B', 'A', 'B', 'A', 'B']
    return SavedInstantResult.objects.create(
        user=user,
        game_token=token,
        topic=topic,
        keywords=['여행', '친구'],
        mbti=mbti,
        title='일정표를 든 모험 지휘관',
        description='새로운 경험도 놓치지 않으면서 결론은 빠르게 정합니다.',
        result_data={
            'strength': '방향을 빠르게 정합니다.',
            'blind_spot': '다른 속도를 놓칠 수 있습니다.',
            'conflict_style': '쟁점을 정리해 말합니다.',
            'compatible_style': '의견을 솔직히 말하는 사람과 편합니다.',
            'decision_tip': '상대의 우선순위를 먼저 물어보세요.',
            'axis_summaries': [
                {
                    'axis': 'E/I',
                    'first_count': 2,
                    'second_count': 0,
                },
                {
                    'axis': 'S/N',
                    'first_count': 1,
                    'second_count': 1,
                },
                {
                    'axis': 'T/F',
                    'first_count': 1,
                    'second_count': 1,
                },
                {
                    'axis': 'J/P',
                    'first_count': 1,
                    'second_count': 0,
                },
            ],
        },
        game_data={
            'questions': questions,
            'answers': selected_answers,
        },
    )


# ---------------------------------------------------------------------------
# 1. 투표 저장 테스트
# ---------------------------------------------------------------------------

class VoteSaveTest(TestCase):
    def test_vote_is_saved_to_database(self) -> None:
        question = make_question()
        choice_a = question.choices.get(code='A')

        vote, created = process_vote(question, choice_a, session_key='session-abc-001')

        self.assertTrue(created)
        self.assertEqual(Vote.objects.count(), 1)
        self.assertEqual(vote.question, question)
        self.assertEqual(vote.choice, choice_a)
        self.assertEqual(vote.session_key, 'session-abc-001')


# ---------------------------------------------------------------------------
# 2. 중복투표 방지 테스트
# ---------------------------------------------------------------------------

class DuplicateVoteTest(TestCase):
    def test_duplicate_vote_is_blocked(self) -> None:
        question = make_question()
        choice_a = question.choices.get(code='A')
        choice_b = question.choices.get(code='B')

        _, first_created = process_vote(question, choice_a, session_key='session-dup')
        _, second_created = process_vote(question, choice_b, session_key='session-dup')

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(Vote.objects.count(), 1)

    def test_unique_constraint_raises_integrity_error_on_direct_create(self) -> None:
        question = make_question()
        choice_a = question.choices.get(code='A')

        Vote.objects.create(question=question, choice=choice_a, session_key='session-dup2')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vote.objects.create(question=question, choice=choice_a, session_key='session-dup2')


# ---------------------------------------------------------------------------
# 3. vote_count 증가 테스트
# ---------------------------------------------------------------------------

class VoteCountTest(TestCase):
    def test_vote_count_increases_by_one(self) -> None:
        question = make_question()
        choice_a = question.choices.get(code='A')
        initial_count = choice_a.vote_count

        process_vote(question, choice_a, session_key='session-cnt1')
        choice_a.refresh_from_db()

        self.assertEqual(choice_a.vote_count, initial_count + 1)

    def test_duplicate_vote_does_not_increase_count(self) -> None:
        question = make_question()
        choice_a = question.choices.get(code='A')

        process_vote(question, choice_a, session_key='session-cnt2')
        process_vote(question, choice_a, session_key='session-cnt2')
        choice_a.refresh_from_db()

        self.assertEqual(choice_a.vote_count, 1)


# ---------------------------------------------------------------------------
# 4. 선택지 비율 계산 테스트
# ---------------------------------------------------------------------------

class VotePercentageTest(TestCase):
    def test_vote_percentage_calculation(self) -> None:
        question = make_question()
        choice_a = question.choices.get(code='A')
        choice_b = question.choices.get(code='B')

        Choice.objects.filter(pk=choice_a.pk).update(vote_count=30)
        Choice.objects.filter(pk=choice_b.pk).update(vote_count=70)
        choice_a.refresh_from_db()

        self.assertAlmostEqual(choice_a.vote_percentage(), 30.0, places=1)


# ---------------------------------------------------------------------------
# 5. 0표 상태 처리 테스트
# ---------------------------------------------------------------------------

class ZeroVoteTest(TestCase):
    def test_vote_percentage_returns_50_when_no_votes(self) -> None:
        question = make_question()
        choice_a = question.choices.get(code='A')

        self.assertEqual(choice_a.vote_count, 0)
        self.assertEqual(choice_a.vote_percentage(), 50.0)

    def test_total_votes_returns_zero(self) -> None:
        question = make_question()
        self.assertEqual(question.total_votes(), 0)


# ---------------------------------------------------------------------------
# 6. 결과 등급 경계값 테스트
# ---------------------------------------------------------------------------

class GradeBoundaryTest(TestCase):
    def test_grade_boundaries(self) -> None:
        cases: list[tuple[float, str]] = [
            (0.0, ResultGrade.LEGENDARY_MINORITY),
            (15.0, ResultGrade.LEGENDARY_MINORITY),
            (15.1, ResultGrade.RARE),
            (30.0, ResultGrade.RARE),
            (30.1, ResultGrade.MINORITY),
            (44.0, ResultGrade.MINORITY),
            (44.1, ResultGrade.BALANCED),
            (55.9, ResultGrade.BALANCED),
            (56.0, ResultGrade.MAJORITY),
            (69.0, ResultGrade.MAJORITY),
            (69.1, ResultGrade.POPULAR),
            (84.0, ResultGrade.POPULAR),
            (84.1, ResultGrade.OVERWHELMING),
            (100.0, ResultGrade.OVERWHELMING),
        ]
        for percentage, expected in cases:
            with self.subTest(percentage=percentage):
                result = get_grade(percentage)
                self.assertEqual(
                    result, expected,
                    msg=f'percentage={percentage}일 때 {expected}를 기대했지만 {result}이 반환됨',
                )

    def test_invalid_percentage_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            get_grade(-1.0)
        with self.assertRaises(ValueError):
            get_grade(100.1)


# ---------------------------------------------------------------------------
# 7. 결과 템플릿 미존재 시 기본 문구 테스트
# ---------------------------------------------------------------------------

class DefaultResultTemplateTest(TestCase):
    def test_fallback_result_when_no_template_exists(self) -> None:
        self.assertEqual(ResultTemplate.objects.count(), 0)

        question = make_question()
        choice_a = question.choices.get(code='A')

        generator = TemplateResultGenerator()
        result: ResultData = generator.generate(
            question=question,
            choice=choice_a,
            percentage=5.0,
            total_votes=100,
            grade=ResultGrade.LEGENDARY_MINORITY,
        )

        self.assertIsInstance(result, ResultData)
        self.assertGreater(len(result.title), 0)
        self.assertGreater(len(result.description), 0)
        self.assertIsInstance(result.keywords, list)
        self.assertEqual(result.grade, ResultGrade.LEGENDARY_MINORITY)


# ---------------------------------------------------------------------------
# 8. 비활성화된 질문 투표 차단 테스트
# ---------------------------------------------------------------------------

class InactiveQuestionVoteBlockTest(TestCase):
    def test_vote_on_inactive_question_returns_404(self) -> None:
        client = Client()
        question = make_question(active=False)
        choice_a = question.choices.get(code='A')

        url = reverse('games:vote', kwargs={'question_id': question.id})
        response = client.post(url, data={'choice': str(choice_a.id)})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Vote.objects.count(), 0)

    def test_detail_on_inactive_question_returns_404(self) -> None:
        client = Client()
        question = make_question(active=False)

        url = reverse('games:detail', kwargs={'question_id': question.id})
        response = client.get(url)

        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# 9. GET 요청으로 투표 URL 접근 시 차단 테스트
# ---------------------------------------------------------------------------

class VoteGetRequestBlockTest(TestCase):
    def test_get_request_to_vote_url_redirects_without_creating_vote(self) -> None:
        client = Client()
        question = make_question()

        url = reverse('games:vote', kwargs={'question_id': question.id})
        response = client.get(url)

        self.assertIn(response.status_code, [301, 302])
        self.assertEqual(Vote.objects.count(), 0)


# ---------------------------------------------------------------------------
# 10. 동시 요청 집계 로직 테스트
# ---------------------------------------------------------------------------

class ConcurrentVoteAggregationTest(TestCase):
    def test_f_expression_increments_correctly_for_multiple_sessions(self) -> None:
        question = make_question()
        choice_a = question.choices.get(code='A')

        sessions = [f'session-concurrent-{i}' for i in range(10)]
        for sk in sessions:
            process_vote(question, choice_a, session_key=sk)

        choice_a.refresh_from_db()
        self.assertEqual(choice_a.vote_count, 10)
        self.assertEqual(Vote.objects.filter(question=question).count(), 10)

    def test_build_result_returns_correct_percentage_after_votes(self) -> None:
        question = make_question()
        choice_a = question.choices.get(code='A')
        choice_b = question.choices.get(code='B')

        for i in range(3):
            process_vote(question, choice_a, session_key=f'sk-a-{i}')
        for i in range(7):
            process_vote(question, choice_b, session_key=f'sk-b-{i}')

        question.refresh_from_db()
        result = build_result(
            question=question,
            voted_choice_id=choice_a.id,
            generator=TemplateResultGenerator(),
        )

        self.assertAlmostEqual(result.percentage, 30.0, places=1)
        self.assertEqual(result.total_votes, 10)
        self.assertEqual(result.grade, ResultGrade.RARE)


# ---------------------------------------------------------------------------
# 11. 반복 없는 플레이 흐름 / 진행 기록
# ---------------------------------------------------------------------------

class PlayProgressTest(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        session = self.client.session
        session.save()
        self.session_key = session.session_key

    def test_random_game_excludes_completed_questions(self) -> None:
        completed = make_question(title='완료한 질문')
        unplayed = make_question(title='남은 질문')
        process_vote(
            completed,
            completed.choices.get(code='A'),
            session_key=self.session_key,
        )

        response = self.client.get(reverse('games:random'))

        self.assertRedirects(
            response,
            reverse('games:detail', kwargs={'question_id': unplayed.id}),
            fetch_redirect_response=False,
        )

    def test_random_game_redirects_to_progress_when_all_completed(self) -> None:
        question = make_question()
        process_vote(
            question,
            question.choices.get(code='A'),
            session_key=self.session_key,
        )

        response = self.client.get(reverse('games:random'))

        self.assertRedirects(
            response,
            reverse('games:progress'),
            fetch_redirect_response=False,
        )

    def test_result_next_question_excludes_previous_votes(self) -> None:
        first = make_question(title='첫 질문')
        second = make_question(title='두 번째 질문')
        remaining = make_question(title='남은 질문')
        process_vote(
            first,
            first.choices.get(code='A'),
            session_key=self.session_key,
        )
        process_vote(
            second,
            second.choices.get(code='B'),
            session_key=self.session_key,
        )

        response = self.client.get(
            reverse('games:result', kwargs={'question_id': first.id}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['next_question'], remaining)

    def test_progress_page_summarizes_session(self) -> None:
        completed = make_question(title='완료한 질문')
        make_question(title='남은 질문')
        process_vote(
            completed,
            completed.choices.get(code='A'),
            session_key=self.session_key,
        )

        response = self.client.get(reverse('games:progress'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_questions'], 2)
        self.assertEqual(response.context['completed_questions'], 1)
        self.assertEqual(response.context['remaining_questions'], 1)
        self.assertEqual(response.context['completion_percentage'], 50)
        self.assertEqual(len(response.context['recent_results']), 1)


# ---------------------------------------------------------------------------
# 12. 회원가입 / 사용자 제작 / 콘텐츠 검수
# ---------------------------------------------------------------------------

def game_set_post_data(
    category: Category,
    question_count: int = 7,
    *,
    title: str = '내가 만든 주제',
    description: str = '취향을 알아보는 가상 질문입니다.',
    content_basis: str = GameSet.ContentBasis.HYPOTHETICAL,
    reference_url: str = '',
) -> dict[str, str]:
    data = {
        'title': title,
        'description': description,
        'category': str(category.pk),
        'content_basis': content_basis,
        'reference_url': reference_url,
        'safety_agreement': 'on',
        'questions-TOTAL_FORMS': str(question_count),
        'questions-INITIAL_FORMS': '0',
        'questions-MIN_NUM_FORMS': '7',
        'questions-MAX_NUM_FORMS': '10',
    }
    for index in range(question_count):
        data.update({
            f'questions-{index}-title': f'{index + 1}번 질문',
            f'questions-{index}-description': '',
            f'questions-{index}-choice_a': f'{index + 1}번 A 선택',
            f'questions-{index}-choice_b': f'{index + 1}번 B 선택',
        })
    return data


def make_user_game_set(
    creator,
    category: Category,
    question_count: int = 7,
) -> GameSet:
    game_set = GameSet.objects.create(
        creator=creator,
        category=category,
        title='검수용 사용자 게임',
        description='가상 취향 질문 모음',
    )
    for index in range(question_count):
        question = Question.objects.create(
            game_set=game_set,
            category=category,
            title=f'사용자 질문 {index + 1}',
            is_active=False,
        )
        Choice.objects.create(
            question=question,
            code=Choice.Code.A,
            text=f'A 선택 {index + 1}',
        )
        Choice.objects.create(
            question=question,
            code=Choice.Code.B,
            text=f'B 선택 {index + 1}',
        )
    return game_set


class AccountFlowTest(TestCase):
    def test_signup_creates_user_and_logs_in(self) -> None:
        response = self.client.post(reverse('games:signup'), {
            'username': 'creator',
            'email': 'creator@example.com',
            'password1': 'A-strong-password-2026',
            'password2': 'A-strong-password-2026',
        })

        self.assertRedirects(
            response,
            reverse('games:index'),
            fetch_redirect_response=False,
        )
        self.assertTrue(get_user_model().objects.filter(username='creator').exists())
        self.assertEqual(int(self.client.session['_auth_user_id']), get_user_model().objects.get(username='creator').pk)

    def test_signup_returns_to_requested_safe_page(self) -> None:
        result_url = reverse('games:instant_result')
        response = self.client.post(
            f"{reverse('games:signup')}?next={result_url}",
            {
                'username': 'archive-member',
                'email': 'archive@example.com',
                'password1': 'A-strong-password-2026',
                'password2': 'A-strong-password-2026',
            },
        )

        self.assertRedirects(
            response,
            result_url,
            fetch_redirect_response=False,
        )

    def test_game_creation_requires_login(self) -> None:
        response = self.client.get(reverse('games:create'))

        self.assertRedirects(
            response,
            f"{reverse('games:login')}?next={reverse('games:create')}",
            fetch_redirect_response=False,
        )

    def test_login_and_logout_pages_work(self) -> None:
        user = get_user_model().objects.create_user(
            username='member',
            password='A-strong-password-2026',
        )
        login_response = self.client.post(reverse('games:login'), {
            'username': 'member',
            'password': 'A-strong-password-2026',
        })
        self.assertRedirects(
            login_response,
            reverse('games:index'),
            fetch_redirect_response=False,
        )
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

        logout_response = self.client.post(reverse('games:logout'))
        self.assertRedirects(
            logout_response,
            reverse('games:index'),
            fetch_redirect_response=False,
        )
        self.assertNotIn('_auth_user_id', self.client.session)


class UserGameCreationTest(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(
            username='maker',
            email='maker@example.com',
            password='A-strong-password-2026',
        )
        self.category = Category.objects.create(name='사용자 주제', slug='user-topic')
        self.client.force_login(self.user)

    def test_valid_seven_question_set_is_saved_as_pending(self) -> None:
        response = self.client.post(
            reverse('games:create'),
            game_set_post_data(self.category),
        )

        self.assertRedirects(
            response,
            reverse('games:my_creations'),
            fetch_redirect_response=False,
        )
        game_set = GameSet.objects.get()
        self.assertEqual(game_set.creator, self.user)
        self.assertEqual(game_set.status, GameSet.Status.PENDING)
        self.assertEqual(game_set.questions.count(), 7)
        self.assertEqual(Choice.objects.filter(question__game_set=game_set).count(), 14)
        self.assertFalse(game_set.questions.filter(is_active=True).exists())

    def test_fewer_than_seven_questions_is_rejected(self) -> None:
        response = self.client.post(
            reverse('games:create'),
            game_set_post_data(self.category, question_count=6),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['question_formset'].non_form_errors())
        self.assertFalse(GameSet.objects.exists())

    def test_more_than_ten_questions_is_rejected(self) -> None:
        response = self.client.post(
            reverse('games:create'),
            game_set_post_data(self.category, question_count=11),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['question_formset'].non_form_errors())
        self.assertFalse(GameSet.objects.exists())

    def test_adult_content_is_rejected_before_save(self) -> None:
        data = game_set_post_data(self.category)
        data['questions-0-title'] = '19금 성인물 선택'

        response = self.client.post(reverse('games:create'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '성인·음란 콘텐츠는 제출할 수 없습니다.')
        self.assertFalse(GameSet.objects.exists())

    def test_sourced_content_requires_reference_url(self) -> None:
        response = self.client.post(
            reverse('games:create'),
            game_set_post_data(
                self.category,
                content_basis=GameSet.ContentBasis.SOURCED,
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '검증 자료 URL이 필요합니다.')
        self.assertFalse(GameSet.objects.exists())

    def test_strong_unverified_claim_requires_sourced_mode(self) -> None:
        response = self.client.post(
            reverse('games:create'),
            game_set_post_data(
                self.category,
                description='이 선택은 수익 보장 결과를 제공합니다.',
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '검증이 필요한 표현이 포함되어 있습니다.')
        self.assertFalse(GameSet.objects.exists())

    def test_unverified_claim_inside_question_requires_source(self) -> None:
        data = game_set_post_data(self.category)
        data['questions-2-choice_a'] = '원금 보장 투자 선택'

        response = self.client.post(reverse('games:create'), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '문항에 검증이 필요한 표현이 있습니다.')
        self.assertFalse(GameSet.objects.exists())

    def test_my_creations_only_shows_current_users_sets(self) -> None:
        mine = make_user_game_set(self.user, self.category)
        other_user = get_user_model().objects.create_user(
            username='other',
            password='A-strong-password-2026',
        )
        other = make_user_game_set(other_user, self.category)
        other.title = '다른 사람의 비공개 게임'
        other.save(update_fields=['title'])

        response = self.client.get(reverse('games:my_creations'))

        self.assertContains(response, mine.title)
        self.assertNotContains(response, other.title)


@override_settings(OPENAI_API_KEY='')
class QuestionDraftGenerationTest(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(
            username='draft-maker',
            password='A-strong-password-2026',
        )
        self.category = Category.objects.create(name='여행', slug='travel')
        self.url = reverse('games:generate_drafts')

    def test_generator_requires_login(self) -> None:
        response = self.client.post(self.url, {
            'keywords': '여행, 친구',
            'count': '7',
            'category': str(self.category.pk),
        })

        self.assertRedirects(
            response,
            f"{reverse('games:login')}?next={self.url}",
            fetch_redirect_response=False,
        )

    def test_create_page_shows_keyword_generator(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse('games:create'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '어떤 주제로 만들까요?')
        self.assertContains(response, '주제 키워드')
        self.assertContains(response, self.url)

    def test_keywords_generate_exact_safe_draft_count_without_saving(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(self.url, {
            'keywords': '여행, 친구, 즉흥',
            'count': '10',
            'category': str(self.category.pk),
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['source'], 'local')
        self.assertEqual(len(payload['drafts']), 10)
        self.assertEqual(len({draft['title'] for draft in payload['drafts']}), 10)
        self.assertEqual(
            payload['drafts'][0]['title'],
            '여행에 집중하기 vs 친구에 집중하기',
        )
        for draft in payload['drafts']:
            self.assertTrue(draft['title'])
            self.assertTrue(draft['choice_a'])
            self.assertTrue(draft['choice_b'])
            self.assertNotEqual(draft['choice_a'], draft['choice_b'])
        self.assertFalse(GameSet.objects.exists())
        self.assertFalse(Question.objects.exists())

    def test_generator_rejects_adult_or_unverified_keywords(self) -> None:
        self.client.force_login(self.user)
        adult_response = self.client.post(self.url, {
            'keywords': '19금 여행',
            'count': '7',
            'category': str(self.category.pk),
        })
        claim_response = self.client.post(self.url, {
            'keywords': '수익 보장',
            'count': '7',
            'category': str(self.category.pk),
        })

        self.assertEqual(adult_response.status_code, 400)
        self.assertIn('성인·음란 콘텐츠', adult_response.json()['error'])
        self.assertEqual(claim_response.status_code, 400)
        self.assertIn('검증이 필요한 단정 표현', claim_response.json()['error'])

    def test_generator_enforces_seven_to_ten_questions(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(self.url, {
            'keywords': '여행',
            'count': '6',
            'category': str(self.category.pk),
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn('7', response.json()['error'])

    def test_generator_accepts_valid_csrf_protected_request(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        csrf_client.get(reverse('games:create'))
        csrf_token = csrf_client.cookies['csrftoken'].value

        response = csrf_client.post(
            self.url,
            {
                'keywords': '여행',
                'count': '7',
                'category': str(self.category.pk),
            },
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['drafts']), 7)

    @override_settings(
        OPENAI_API_KEY='test-key',
        OPENAI_MODEL='gpt-5.6',
        OPENAI_TIMEOUT=2.0,
    )
    @patch('양자택일.question_generator.generate_openai_question_drafts')
    def test_configured_api_key_uses_openai_generator(self, mock_generate) -> None:
        self.client.force_login(self.user)
        mock_generate.return_value = {
            'title_suggestion': '여행 선택 보고서',
            'description_suggestion': '여행에 관한 안전한 취향 질문입니다.',
            'drafts': [
                {
                    'title': f'여행 질문 {index}',
                    'description': f'여행 상황 {index}',
                    'choice_a': f'A 선택 {index}',
                    'choice_b': f'B 선택 {index}',
                }
                for index in range(1, 8)
            ],
            'source': 'ai',
        }

        response = self.client.post(self.url, {
            'keywords': '여행',
            'count': '7',
            'category': str(self.category.pk),
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['source'], 'ai')
        mock_generate.assert_called_once_with(
            api_key='test-key',
            model='gpt-5.6',
            timeout=2.0,
            keywords=['여행'],
            count=7,
            category_name='여행',
        )

    @patch(
        '양자택일.question_generator.generate_openai_question_drafts',
        side_effect=RuntimeError('temporary failure'),
    )
    def test_openai_failure_falls_back_to_local_generator(self, _mock_generate) -> None:
        with self.assertLogs('양자택일.question_generator', level='WARNING'):
            result = generate_question_drafts_with_fallback(
                api_key='test-key',
                model='gpt-5.6',
                timeout=2.0,
                keywords=['여행'],
                count=7,
                category_name='여행',
            )

        self.assertEqual(result['source'], 'local')
        self.assertEqual(len(result['drafts']), 7)

    def test_structured_openai_output_is_validated_without_network(self) -> None:
        generated = GeneratedQuestionSet(
            title_suggestion='여행 선택 보고서',
            description_suggestion='여행 취향을 일곱 가지 선택으로 알아봅니다.',
            drafts=[
                make_generated_question_draft(index)
                for index in range(1, 8)
            ],
        )

        class FakeResponses:
            def __init__(self) -> None:
                self.arguments = {}

            def parse(self, **kwargs):
                self.arguments = kwargs
                return SimpleNamespace(output_parsed=generated)

        responses = FakeResponses()
        result = generate_openai_question_drafts(
            api_key='test-key',
            model='gpt-5.6',
            timeout=2.0,
            keywords=['여행'],
            count=7,
            category_name='여행',
            client=SimpleNamespace(responses=responses),
        )

        self.assertEqual(result['source'], 'ai')
        self.assertEqual(len(result['drafts']), 7)
        self.assertEqual(responses.arguments['model'], 'gpt-5.6')
        self.assertIs(responses.arguments['text_format'], GeneratedQuestionSet)
        self.assertFalse(responses.arguments['store'])

    def test_unsafe_openai_output_is_rejected_after_generation(self) -> None:
        generated = GeneratedQuestionSet(
            title_suggestion='여행 선택 보고서',
            description_suggestion='여행 취향을 알아봅니다.',
            drafts=[
                make_generated_question_draft(index, unsafe=index == 1)
                for index in range(1, 8)
            ],
        )
        client = SimpleNamespace(
            responses=SimpleNamespace(
                parse=lambda **_kwargs: SimpleNamespace(output_parsed=generated),
            ),
        )

        with self.assertRaises(ValidationError):
            generate_openai_question_drafts(
                api_key='test-key',
                model='gpt-5.6',
                timeout=2.0,
                keywords=['여행'],
                count=7,
                category_name='여행',
                client=client,
            )


class OpenAiMbtiAnalysisTest(TestCase):
    def setUp(self) -> None:
        self.questions = [
            make_generated_question_draft(index)
            for index in range(1, 8)
        ]
        self.choice_codes = ['A', 'B', 'A', 'B', 'A', 'B', 'A']

    def test_local_fallback_scores_internal_mbti_traits(self) -> None:
        result = analyze_mbti_with_fallback(
            api_key='',
            model='gpt-5.6',
            timeout=2.0,
            questions=self.questions,
            choice_codes=self.choice_codes,
        )

        self.assertEqual(result['mbti'], 'ENTP')
        self.assertEqual(result['source'], 'local')
        self.assertTrue(result['title'])
        self.assertIn('여행 질문 1', result['description'])
        self.assertTrue(result['strength'])
        self.assertTrue(result['decision_tip'])
        self.assertEqual(len(result['decisive_choices']), 3)
        self.assertEqual(len(result['axis_summaries']), 4)
        self.assertEqual(result['axis_summaries'][0]['first_count'], 2)
        self.assertEqual(result['axis_summaries'][0]['second_count'], 0)

    def test_structured_openai_mbti_analysis_is_parsed_without_network(self) -> None:
        generated = GeneratedMbtiAnalysis(
            mbti='ENTP',
            title='평범한 답은 일단 의심하는 반전 토론가',
            description=(
                '여행 질문 1에서는 실행을, 여행 질문 2에서는 가능성을 골랐습니다. '
                '고민하는 척하지만 결국 새로운 문을 먼저 여는 선택 패턴입니다.'
            ),
            strength='새로운 가능성을 빠르게 발견하고 바로 시험해봅니다.',
            blind_spot='흥미로운 선택지를 늘리다가 마감 시간을 놓칠 수 있습니다.',
            conflict_style='쟁점을 바로 꺼내고 가장 일관된 결론부터 찾습니다.',
            compatible_style='방향을 정리하면서 변경 가능성을 열어두는 사람과 편합니다.',
            decision_tip='선택지를 더 찾기 전에 결정 마감부터 정해보세요.',
        )

        class FakeResponses:
            def __init__(self) -> None:
                self.arguments = {}

            def parse(self, **kwargs):
                self.arguments = kwargs
                return SimpleNamespace(output_parsed=generated)

        responses = FakeResponses()
        answer_records = [
            {
                'question': question['title'],
                'selected_option': question[
                    'choice_a' if code == 'A' else 'choice_b'
                ],
                'mbti_axis': question['mbti_axis'],
                'selected_trait': question[
                    'choice_a_trait' if code == 'A' else 'choice_b_trait'
                ],
            }
            for question, code in zip(
                self.questions,
                self.choice_codes,
                strict=True,
            )
        ]

        result = analyze_openai_mbti(
            api_key='test-key',
            model='gpt-5.6',
            timeout=2.0,
            answer_records=answer_records,
            client=SimpleNamespace(responses=responses),
        )

        self.assertEqual(result['mbti'], 'ENTP')
        self.assertEqual(result['source'], 'ai')
        self.assertEqual(len(result['decisive_choices']), 3)
        self.assertEqual(len(result['axis_summaries']), 4)
        self.assertIs(
            responses.arguments['text_format'],
            GeneratedMbtiAnalysis,
        )
        self.assertFalse(responses.arguments['store'])

    def test_unsafe_openai_mbti_analysis_is_rejected(self) -> None:
        generated = GeneratedMbtiAnalysis(
            mbti='ENTP',
            title='19금 성향 분석',
            description='선택을 재미있게 해석했습니다.',
            strength='새로운 가능성을 빠르게 발견합니다.',
            blind_spot='세부 조건을 놓칠 수 있습니다.',
            conflict_style='논리를 정리한 뒤 의견을 말합니다.',
            compatible_style='방향을 정리해주는 사람과 편합니다.',
            decision_tip='결정 마감부터 정해보세요.',
        )
        client = SimpleNamespace(
            responses=SimpleNamespace(
                parse=lambda **_kwargs: SimpleNamespace(output_parsed=generated),
            ),
        )
        answer_records = [
            {
                'question': f'질문 {index}',
                'selected_option': f'선택 {index}',
                'mbti_axis': 'E/I',
                'selected_trait': 'E',
            }
            for index in range(1, 8)
        ]

        with self.assertRaises(ValidationError):
            analyze_openai_mbti(
                api_key='test-key',
                model='gpt-5.6',
                timeout=2.0,
                answer_records=answer_records,
                client=client,
            )


@override_settings(OPENAI_API_KEY='')
class InstantGameFlowTest(TestCase):
    def setUp(self) -> None:
        self.generate_url = reverse('games:instant_generate')

    def generate_game(self, keywords: str = '여행, 친구'):
        return self.client.post(
            self.generate_url,
            {'keywords': keywords},
        )

    def test_home_centers_keyword_game_search_without_creator_navigation(self) -> None:
        response = self.client.get(reverse('games:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '어떤 양자택일을')
        self.assertContains(response, '원하는 키워드를 입력하세요')
        self.assertContains(response, self.generate_url)
        self.assertContains(response, '#여행')
        self.assertNotContains(response, '게임 만들기')
        self.assertNotContains(response, '전체 게임')
        self.assertNotContains(response, '랜덤 게임')
        self.assertNotContains(response, '지금 시작할 양자택일')
        self.assertNotContains(response, '준비된 게임 보기')

    def test_anonymous_keyword_generates_session_game_without_saving(self) -> None:
        response = self.generate_game()

        self.assertRedirects(
            response,
            reverse('games:instant_play', kwargs={'question_number': 1}),
            fetch_redirect_response=False,
        )
        game = self.client.session['instant_game']
        self.assertEqual(len(game['questions']), 7)
        self.assertEqual(game['answers'], [None] * 7)
        self.assertEqual(game['keywords'], ['여행', '친구'])
        self.assertEqual(game['source'], 'local')
        self.assertFalse(GameSet.objects.exists())
        self.assertFalse(Question.objects.exists())

    def test_unsafe_keyword_is_rejected_before_generation(self) -> None:
        response = self.generate_game('19금 여행')

        self.assertRedirects(
            response,
            reverse('games:index'),
            fetch_redirect_response=False,
        )
        self.assertNotIn('instant_game', self.client.session)

        follow_response = self.client.get(reverse('games:index'))
        self.assertContains(follow_response, '성인·음란 콘텐츠')

    def test_choice_automatically_moves_to_next_question_and_back_link_works(self) -> None:
        self.generate_game()

        first_page = self.client.get(
            reverse('games:instant_play', kwargs={'question_number': 1}),
        )
        self.assertContains(first_page, '1 / 7 문항')
        self.assertContains(first_page, '하나를 선택하면 다음 문항으로 자동 이동합니다.')

        answer_response = self.client.post(
            reverse('games:instant_answer', kwargs={'question_number': 1}),
            {'choice': 'A'},
        )
        self.assertRedirects(
            answer_response,
            reverse('games:instant_play', kwargs={'question_number': 2}),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.session['instant_game']['answers'][0], 'A')

        second_page = self.client.get(
            reverse('games:instant_play', kwargs={'question_number': 2}),
        )
        self.assertContains(
            second_page,
            reverse('games:instant_play', kwargs={'question_number': 1}),
        )
        self.assertContains(second_page, '뒤로가기 · 이전 선택 수정')

    def test_previous_answer_can_be_changed_without_database_vote(self) -> None:
        self.generate_game()
        answer_url = reverse(
            'games:instant_answer',
            kwargs={'question_number': 1},
        )
        self.client.post(answer_url, {'choice': 'A'})

        first_page = self.client.get(
            reverse('games:instant_play', kwargs={'question_number': 1}),
        )
        self.assertContains(first_page, 'data-instant-choice="A"')
        self.assertContains(first_page, 'is-selected')

        self.client.post(answer_url, {'choice': 'B'})

        self.assertEqual(self.client.session['instant_game']['answers'][0], 'B')
        self.assertFalse(Vote.objects.exists())

    def test_result_requires_every_question_to_be_answered(self) -> None:
        self.generate_game()

        response = self.client.get(reverse('games:instant_result'))

        self.assertRedirects(
            response,
            reverse('games:instant_play', kwargs={'question_number': 1}),
            fetch_redirect_response=False,
        )

    def test_anonymous_result_shows_basic_result_and_member_invitation(self) -> None:
        self.generate_game('야구')
        choices = ['A', 'B', 'A', 'B', 'A', 'B', 'A']
        for question_number, choice_code in enumerate(choices, start=1):
            response = self.client.post(
                reverse(
                    'games:instant_answer',
                    kwargs={'question_number': question_number},
                ),
                {'choice': choice_code},
            )

        self.assertRedirects(
            response,
            reverse('games:instant_result'),
            fetch_redirect_response=False,
        )
        result_page = self.client.get(reverse('games:instant_result'))
        self.assertContains(result_page, '플레이어님의 선택 속')
        self.assertContains(result_page, '회원이 되면 상세 결과가 열려요')
        self.assertContains(result_page, '무료 회원가입')
        self.assertNotContains(result_page, '나의 선택 사용설명서')
        self.assertNotContains(result_page, '4축 선택 나침반')
        self.assertNotContains(result_page, '코믹 해석')
        self.assertNotContains(result_page, '패턴 분석')
        self.assertNotContains(result_page, '나의 선택 모아보기')
        self.assertContains(result_page, '공식 MBTI 검사나 심리 진단이 아닌')
        self.assertFalse(SavedInstantResult.objects.exists())
        self.assertFalse(GameSet.objects.exists())
        self.assertFalse(Question.objects.exists())
        self.assertFalse(Vote.objects.exists())

    def test_member_gets_detailed_result_and_saved_archive(self) -> None:
        user = get_user_model().objects.create_user(
            username='member',
            password='A-strong-password-2026',
        )
        self.client.force_login(user)
        self.generate_game('여행')
        for question_number in range(1, 8):
            self.client.post(
                reverse(
                    'games:instant_answer',
                    kwargs={'question_number': question_number},
                ),
                {'choice': 'A' if question_number % 2 else 'B'},
            )

        result_page = self.client.get(reverse('games:instant_result'))
        refreshed_page = self.client.get(reverse('games:instant_result'))

        self.assertContains(result_page, 'member님의 선택 속')
        self.assertContains(result_page, '결정적 선택')
        self.assertContains(result_page, '나의 선택 사용설명서')
        self.assertContains(result_page, '4축 선택 나침반')
        self.assertContains(result_page, '내 기록에 저장됨')
        self.assertContains(result_page, '결과 이미지 저장')
        self.assertContains(result_page, '함께하기 초대')
        self.assertContains(result_page, 'memberResultPayload')
        self.assertEqual(refreshed_page.status_code, 200)
        self.assertEqual(SavedInstantResult.objects.filter(user=user).count(), 1)

        saved_result = SavedInstantResult.objects.get(user=user)
        self.assertEqual(saved_result.mbti, 'ENTP')
        self.assertEqual(len(saved_result.game_data['questions']), 7)
        self.assertEqual(len(saved_result.game_data['answers']), 7)
        archive_page = self.client.get(reverse('games:progress'))
        self.assertContains(archive_page, saved_result.title)
        self.assertContains(archive_page, '선택에서 드러난 강점')

    def test_member_can_delete_only_their_saved_result(self) -> None:
        owner = get_user_model().objects.create_user(
            username='owner',
            password='A-strong-password-2026',
        )
        other = get_user_model().objects.create_user(
            username='other',
            password='A-strong-password-2026',
        )
        saved_result = SavedInstantResult.objects.create(
            user=owner,
            game_token='a' * 32,
            topic='여행 선택 보고서',
            keywords=['여행'],
            mbti='ENTP',
            title='반대편 문부터 여는 토론가',
            description='재미를 위한 결과입니다.',
            result_data={'decision_tip': '결정 마감부터 정해보세요.'},
        )
        delete_url = reverse(
            'games:saved_instant_result_delete',
            kwargs={'result_id': saved_result.pk},
        )
        self.client.force_login(other)

        self.assertEqual(self.client.post(delete_url).status_code, 404)
        self.assertTrue(SavedInstantResult.objects.filter(pk=saved_result.pk).exists())

        self.client.force_login(owner)
        response = self.client.post(delete_url)

        self.assertRedirects(
            response,
            reverse('games:progress'),
            fetch_redirect_response=False,
        )
        self.assertFalse(SavedInstantResult.objects.filter(pk=saved_result.pk).exists())

    def test_instant_game_answer_accepts_browser_csrf_cookie_flow(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.get(reverse('games:index'))
        csrf_token = csrf_client.cookies['csrftoken'].value
        generated = csrf_client.post(
            self.generate_url,
            {'keywords': '여행'},
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        csrf_client.get(generated['Location'])
        current_token = csrf_client.cookies['csrftoken'].value

        response = csrf_client.post(
            reverse('games:instant_answer', kwargs={'question_number': 1}),
            {'choice': 'A'},
            HTTP_X_CSRFTOKEN=current_token,
        )

        self.assertRedirects(
            response,
            reverse('games:instant_play', kwargs={'question_number': 2}),
            fetch_redirect_response=False,
        )

    def test_expired_csrf_state_recovers_without_saving_the_answer(self) -> None:
        self.generate_game()
        game = self.client.session['instant_game']
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_session = csrf_client.session
        csrf_session['instant_game'] = game
        csrf_session.save()
        answer_url = reverse(
            'games:instant_answer',
            kwargs={'question_number': 1},
        )

        rejected = csrf_client.post(answer_url, {'choice': 'A'})

        recovery_url = (
            reverse('games:instant_play', kwargs={'question_number': 1})
            + '?security=refreshed'
        )
        self.assertRedirects(
            rejected,
            recovery_url,
            fetch_redirect_response=False,
        )
        self.assertIsNone(
            csrf_client.session['instant_game']['answers'][0],
        )

        recovery_page = csrf_client.get(recovery_url)
        self.assertContains(recovery_page, '안전한 연결 토큰을 새로 발급했습니다.')
        refreshed_token = csrf_client.cookies['csrftoken'].value
        retried = csrf_client.post(
            answer_url,
            {'choice': 'A'},
            HTTP_X_CSRFTOKEN=refreshed_token,
        )
        self.assertRedirects(
            retried,
            reverse('games:instant_play', kwargs={'question_number': 2}),
            fetch_redirect_response=False,
        )

    @patch('양자택일.views.analyze_mbti_with_fallback')
    def test_mbti_result_is_cached_until_an_answer_changes(self, mock_analyze) -> None:
        mock_analyze.return_value = {
            'mbti': 'ENTP',
            'title': '반대편 문부터 여는 토론가',
            'description': '선택 기록 두 개를 근거로 만든 재미용 분석입니다.',
            'strength': '새로운 가능성을 빠르게 발견합니다.',
            'blind_spot': '세부 조건을 놓칠 수 있습니다.',
            'conflict_style': '논리를 정리해 의견을 말합니다.',
            'compatible_style': '방향을 정리해주는 사람과 편합니다.',
            'decision_tip': '결정 마감부터 정해보세요.',
            'decisive_choices': [
                {
                    'question_number': 1,
                    'question': '여행 질문',
                    'selected_option': '바로 떠난다',
                    'mbti_axis': 'E/I',
                    'selected_trait': 'E',
                    'trait_label': '바깥 자극과 행동',
                    'influence': 'E/I 축에서 E 방향에 힘을 보탠 선택',
                },
            ],
            'axis_summaries': [
                {
                    'axis': 'E/I',
                    'axis_label': '에너지 방향',
                    'first_trait': 'E',
                    'first_label': '바깥 자극과 행동',
                    'first_count': 1,
                    'first_percentage': 100,
                    'second_trait': 'I',
                    'second_label': '내면의 정리와 집중',
                    'second_count': 0,
                    'second_percentage': 0,
                    'balance_label': 'E 방향 선택이 더 많음',
                },
            ],
            'source': 'ai',
        }
        self.generate_game('여행')
        for question_number in range(1, 8):
            self.client.post(
                reverse(
                    'games:instant_answer',
                    kwargs={'question_number': question_number},
                ),
                {'choice': 'A' if question_number % 2 else 'B'},
            )

        first_result = self.client.get(reverse('games:instant_result'))
        second_result = self.client.get(reverse('games:instant_result'))

        self.assertContains(first_result, 'ENTP')
        self.assertContains(first_result, '반대편 문부터 여는 토론가')
        self.assertEqual(second_result.status_code, 200)
        mock_analyze.assert_called_once()

        self.client.post(
            reverse(
                'games:instant_answer',
                kwargs={'question_number': 7},
            ),
            {'choice': 'B'},
        )
        refreshed_result = self.client.get(reverse('games:instant_result'))

        self.assertEqual(refreshed_result.status_code, 200)
        self.assertEqual(mock_analyze.call_count, 2)


class UserGameModerationTest(TestCase):
    def setUp(self) -> None:
        self.creator = get_user_model().objects.create_user(
            username='maker',
            password='A-strong-password-2026',
        )
        self.reviewer = get_user_model().objects.create_superuser(
            username='reviewer',
            email='reviewer@example.com',
            password='A-strong-password-2026',
        )
        self.category = Category.objects.create(name='검수', slug='moderation')
        self.game_set = make_user_game_set(self.creator, self.category)
        self.first_question = self.game_set.questions.order_by('pk').first()

    def test_pending_questions_are_not_public(self) -> None:
        detail_url = reverse(
            'games:detail',
            kwargs={'question_id': self.first_question.pk},
        )

        self.assertEqual(self.client.get(detail_url).status_code, 404)
        list_response = self.client.get(reverse('games:list'))
        self.assertNotContains(list_response, self.first_question.title)
        set_url = reverse(
            'games:game_set_detail',
            kwargs={'game_set_id': self.game_set.pk},
        )
        self.assertEqual(self.client.get(set_url).status_code, 404)

    def test_approval_activates_questions_and_makes_them_public(self) -> None:
        self.game_set.approve(self.reviewer)
        self.game_set.refresh_from_db()

        self.assertEqual(self.game_set.status, GameSet.Status.APPROVED)
        self.assertEqual(
            self.game_set.questions.filter(is_active=True).count(),
            7,
        )
        detail_url = reverse(
            'games:detail',
            kwargs={'question_id': self.first_question.pk},
        )
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        set_url = reverse(
            'games:game_set_detail',
            kwargs={'game_set_id': self.game_set.pk},
        )
        set_response = self.client.get(set_url)
        self.assertEqual(set_response.status_code, 200)
        self.assertEqual(len(set_response.context['questions']), 7)
        self.assertContains(set_response, self.game_set.title)

    def test_rejection_keeps_all_questions_private(self) -> None:
        self.game_set.reject(self.reviewer, note='근거 확인 불가')
        self.game_set.refresh_from_db()

        self.assertEqual(self.game_set.status, GameSet.Status.REJECTED)
        self.assertFalse(self.game_set.questions.filter(is_active=True).exists())
        self.assertEqual(self.game_set.moderation_note, '근거 확인 불가')

    def test_result_continues_within_same_topic(self) -> None:
        self.game_set.approve(self.reviewer)
        session = self.client.session
        session.save()
        choice = self.first_question.choices.get(code=Choice.Code.A)
        process_vote(
            self.first_question,
            choice,
            session_key=session.session_key,
        )

        response = self.client.get(
            reverse(
                'games:result',
                kwargs={'question_id': self.first_question.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['next_is_same_set'])
        self.assertEqual(
            response.context['next_question'].game_set_id,
            self.game_set.pk,
        )

    def test_approval_rejects_set_with_fewer_than_seven_questions(self) -> None:
        short_set = make_user_game_set(
            self.creator,
            self.category,
            question_count=6,
        )

        with self.assertRaisesMessage(
            ValidationError,
            '주제별 문항 수는 7~10개여야 합니다.',
        ):
            short_set.approve(self.reviewer)

    def test_approval_rechecks_blocked_content(self) -> None:
        blocked_choice = self.first_question.choices.get(code=Choice.Code.A)
        blocked_choice.text = '19금 성인물 선택'
        blocked_choice.save(update_fields=['text'])

        with self.assertRaisesMessage(
            ValidationError,
            '성인·음란 콘텐츠는 제출할 수 없습니다.',
        ):
            self.game_set.approve(self.reviewer)


# ---------------------------------------------------------------------------
# 13. 양자택일 인트로 / 공식 7문항 / 주제 유형 결과
# ---------------------------------------------------------------------------

class WelcomeFlowTest(TestCase):
    def test_root_shows_clickable_yangjatagil_intro(self) -> None:
        response = self.client.get(reverse('games:welcome'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '양자택일')
        self.assertContains(response, '아무 곳이나 눌러 시작')
        self.assertContains(response, reverse('games:index'))

    def test_main_page_is_available_after_intro(self) -> None:
        response = self.client.get(reverse('games:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '양자택일')


class OfficialContentSeedTest(TestCase):
    def test_seed_creates_seven_official_topics_with_seven_questions_each(self) -> None:
        output = StringIO()
        call_command('seed_data', stdout=output)
        call_command('seed_data', stdout=output)

        official_sets = GameSet.objects.filter(is_official=True)
        self.assertEqual(official_sets.count(), 7)
        self.assertEqual(Question.objects.count(), 49)
        self.assertEqual(Choice.objects.count(), 98)
        self.assertFalse(Question.objects.filter(category__isnull=True).exists())
        for game_set in official_sets:
            with self.subTest(game_set=game_set.title):
                self.assertEqual(game_set.status, GameSet.Status.APPROVED)
                self.assertEqual(game_set.questions.filter(is_active=True).count(), 7)
                self.assertIsNone(game_set.creator)


class GameSetResultTest(TestCase):
    def setUp(self) -> None:
        self.creator = get_user_model().objects.create_user(
            username='maker',
            password='A-strong-password-2026',
        )
        self.reviewer = get_user_model().objects.create_superuser(
            username='reviewer',
            email='reviewer@example.com',
            password='A-strong-password-2026',
        )
        self.category = Category.objects.create(name='결과', slug='set-result')
        self.game_set = make_user_game_set(self.creator, self.category)
        self.game_set.approve(self.reviewer)

        session = self.client.session
        session.save()
        self.session_key = session.session_key

    def test_all_a_answers_create_confident_type(self) -> None:
        votes = []
        for question in self.game_set.questions.order_by('pk'):
            vote, _ = process_vote(
                question,
                question.choices.get(code=Choice.Code.A),
                session_key=self.session_key,
            )
            votes.append(vote)

        result = build_game_set_result(display_name='테스터', votes=votes)

        self.assertEqual(result.type_name, '확신의 직진 대장형')
        self.assertEqual(result.a_count, 7)
        self.assertEqual(result.consistency_score, 100)
        self.assertIn('실제 성격이나 심리 특성을 진단하는 지표는 아닙니다', result.professional_analysis)

    def test_completed_topic_shows_named_comic_and_pattern_analysis(self) -> None:
        self.client.post(
            reverse('games:game_set_start', kwargs={'game_set_id': self.game_set.pk}),
            {'nickname': '테스터'},
        )
        for question in self.game_set.questions.order_by('pk'):
            process_vote(
                question,
                question.choices.get(code=Choice.Code.A),
                session_key=self.session_key,
            )

        response = self.client.get(
            reverse('games:game_set_result', kwargs={'game_set_id': self.game_set.pk}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '테스터님은')
        self.assertContains(response, '확신의 직진 대장형')
        self.assertContains(response, '코믹 해석')
        self.assertContains(response, '패턴 분석')

    def test_incomplete_topic_redirects_to_topic_detail(self) -> None:
        response = self.client.get(
            reverse('games:game_set_result', kwargs={'game_set_id': self.game_set.pk}),
        )

        self.assertRedirects(
            response,
            reverse(
                'games:game_set_detail',
                kwargs={'game_set_id': self.game_set.pk},
            ),
            fetch_redirect_response=False,
        )

    def test_last_vote_redirects_to_topic_type_result(self) -> None:
        questions = list(self.game_set.questions.order_by('pk'))
        for question in questions[:-1]:
            process_vote(
                question,
                question.choices.get(code=Choice.Code.A),
                session_key=self.session_key,
            )
        last_question = questions[-1]

        response = self.client.post(
            reverse('games:vote', kwargs={'question_id': last_question.pk}),
            {'choice': last_question.choices.get(code=Choice.Code.B).pk},
        )

        self.assertRedirects(
            response,
            reverse(
                'games:game_set_result',
                kwargs={'game_set_id': self.game_set.pk},
            ),
            fetch_redirect_response=False,
        )


class AutoAdvanceAndUndoTest(TestCase):
    def setUp(self) -> None:
        self.creator = get_user_model().objects.create_user(
            username='flow-maker',
            password='A-strong-password-2026',
        )
        self.reviewer = get_user_model().objects.create_superuser(
            username='flow-reviewer',
            email='flow-reviewer@example.com',
            password='A-strong-password-2026',
        )
        self.category = Category.objects.create(name='자동 진행', slug='auto-flow')
        self.game_set = make_user_game_set(self.creator, self.category)
        self.game_set.approve(self.reviewer)
        self.questions = list(self.game_set.questions.order_by('pk'))

        session = self.client.session
        session.save()
        self.session_key = session.session_key

    def test_vote_automatically_advances_to_next_question(self) -> None:
        first, second = self.questions[:2]

        response = self.client.post(
            reverse('games:vote', kwargs={'question_id': first.pk}),
            {'choice': first.choices.get(code=Choice.Code.A).pk},
        )

        self.assertRedirects(
            response,
            reverse('games:detail', kwargs={'question_id': second.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            Vote.objects.filter(question=first, session_key=self.session_key).count(),
            1,
        )

    def test_next_question_shows_progress_and_back_button(self) -> None:
        first, second = self.questions[:2]
        process_vote(
            first,
            first.choices.get(code=Choice.Code.A),
            session_key=self.session_key,
        )

        response = self.client.get(
            reverse('games:detail', kwargs={'question_id': second.pk}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['question_number'], 2)
        self.assertEqual(response.context['question_count'], 7)
        self.assertEqual(response.context['completed_count'], 1)
        self.assertContains(response, '뒤로가기 · 이전 선택 수정')

    def test_back_button_undoes_vote_count_and_allows_reselection(self) -> None:
        first, second = self.questions[:2]
        choice_a = first.choices.get(code=Choice.Code.A)
        choice_b = first.choices.get(code=Choice.Code.B)
        process_vote(first, choice_a, session_key=self.session_key)

        undo_response = self.client.post(
            reverse(
                'games:game_set_undo',
                kwargs={'game_set_id': self.game_set.pk},
            ),
        )

        self.assertRedirects(
            undo_response,
            reverse('games:detail', kwargs={'question_id': first.pk}),
            fetch_redirect_response=False,
        )
        self.assertFalse(
            Vote.objects.filter(question=first, session_key=self.session_key).exists()
        )
        choice_a.refresh_from_db()
        self.assertEqual(choice_a.vote_count, 0)

        reselection_response = self.client.post(
            reverse('games:vote', kwargs={'question_id': first.pk}),
            {'choice': choice_b.pk},
        )
        self.assertRedirects(
            reselection_response,
            reverse('games:detail', kwargs={'question_id': second.pk}),
            fetch_redirect_response=False,
        )
        choice_b.refresh_from_db()
        self.assertEqual(choice_b.vote_count, 1)

    def test_completed_result_can_return_to_last_choice(self) -> None:
        for question in self.questions:
            process_vote(
                question,
                question.choices.get(code=Choice.Code.A),
                session_key=self.session_key,
            )

        result_response = self.client.get(
            reverse(
                'games:game_set_result',
                kwargs={'game_set_id': self.game_set.pk},
            ),
        )
        self.assertContains(result_response, '마지막 선택 수정')

        undo_response = self.client.post(
            reverse(
                'games:game_set_undo',
                kwargs={'game_set_id': self.game_set.pk},
            ),
        )

        last_question = self.questions[-1]
        self.assertRedirects(
            undo_response,
            reverse('games:detail', kwargs={'question_id': last_question.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            Vote.objects.filter(
                question__game_set=self.game_set,
                session_key=self.session_key,
            ).count(),
            6,
        )


@override_settings(OPENAI_API_KEY='')
class MemberServicesTest(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(
            username='member',
            email='member@example.com',
            password='A-strong-password-2026',
        )
        self.result = make_saved_member_result(self.user)

    def test_member_hub_shows_all_exclusive_themes_and_recommendations(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse('games:member_hub'))

        self.assertEqual(response.status_code, 200)
        for theme in (
            '연애 심층편',
            '직장 생존편',
            '친구 관계편',
            '여행 스타일편',
            '소비 습관편',
            '커플·우정 특별편',
        ):
            self.assertContains(response, theme)
        self.assertContains(response, '맞춤형 게임 추천')
        self.assertContains(response, '친구·연인과 함께하기')

    def test_favorite_toggle_is_owner_only(self) -> None:
        other = get_user_model().objects.create_user(
            username='other-member',
            password='A-strong-password-2026',
        )
        favorite_url = reverse(
            'games:saved_instant_result_favorite',
            kwargs={'result_id': self.result.pk},
        )
        self.client.force_login(other)
        self.assertEqual(self.client.post(favorite_url).status_code, 404)

        self.client.force_login(self.user)
        response = self.client.post(favorite_url)
        self.assertRedirects(
            response,
            reverse('games:progress'),
            fetch_redirect_response=False,
        )
        self.result.refresh_from_db()
        self.assertTrue(self.result.is_favorite)

        self.client.post(favorite_url)
        self.result.refresh_from_db()
        self.assertFalse(self.result.is_favorite)

    def test_choice_report_aggregates_monthly_axes_and_keywords(self) -> None:
        previous = make_saved_member_result(
            self.user,
            token='b' * 32,
            topic='친구 선택 보고서',
            mbti='ISFP',
        )
        previous_month = (
            timezone.localtime(timezone.now())
            .replace(day=1, hour=12, minute=0, second=0, microsecond=0)
            - timedelta(days=1)
        )
        SavedInstantResult.objects.filter(pk=previous.pk).update(
            created_at=previous_month,
            updated_at=previous_month,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('games:choice_report'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['report']['total_results'], 2)
        self.assertEqual(response.context['report']['current_month_count'], 1)
        self.assertEqual(response.context['report']['previous_month_count'], 1)
        self.assertContains(response, 'E/I · S/N · T/F · J/P 누적 나침반')
        self.assertContains(response, '#여행')
        self.assertContains(response, '오락용 해석')

    def test_archive_exposes_favorite_and_together_actions(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse('games:progress'))

        self.assertContains(response, '즐겨찾기')
        self.assertContains(response, '함께하기')
        self.assertContains(response, reverse('games:choice_report'))


@override_settings(OPENAI_API_KEY='')
class TogetherChoiceFlowTest(TestCase):
    def setUp(self) -> None:
        self.creator = get_user_model().objects.create_user(
            username='inviter',
            password='A-strong-password-2026',
        )
        self.participant = get_user_model().objects.create_user(
            username='friend',
            password='A-strong-password-2026',
        )
        self.outsider = get_user_model().objects.create_user(
            username='outsider',
            password='A-strong-password-2026',
        )
        self.source_result = make_saved_member_result(self.creator)

    def create_invite(self) -> ChoiceComparisonInvite:
        self.client.force_login(self.creator)
        response = self.client.post(
            reverse(
                'games:together_create',
                kwargs={'result_id': self.source_result.pk},
            )
        )
        invite = ChoiceComparisonInvite.objects.get(creator=self.creator)
        self.assertRedirects(
            response,
            reverse('games:together_detail', kwargs={'invite_id': invite.pk}),
            fetch_redirect_response=False,
        )
        return invite

    def test_anonymous_invitee_sees_login_and_signup_entry(self) -> None:
        invite = self.create_invite()
        self.client.logout()

        response = self.client.get(
            reverse('games:together_detail', kwargs={'invite_id': invite.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '로그인하고 참여')
        self.assertContains(response, '가입하고 참여')
        self.assertContains(response, self.creator.username)

    def test_two_members_complete_game_and_receive_compatibility(self) -> None:
        invite = self.create_invite()
        self.client.force_login(self.participant)
        detail_url = reverse(
            'games:together_detail',
            kwargs={'invite_id': invite.pk},
        )

        response = self.client.get(detail_url)
        self.assertRedirects(
            response,
            reverse(
                'games:together_play',
                kwargs={'invite_id': invite.pk, 'question_number': 1},
            ),
            fetch_redirect_response=False,
        )
        play_response = self.client.get(
            reverse(
                'games:together_play',
                kwargs={'invite_id': invite.pk, 'question_number': 1},
            )
        )
        self.assertContains(play_response, '선택하면 자동으로 다음 문항')

        for question_number in range(1, 8):
            answer_response = self.client.post(
                reverse(
                    'games:together_answer',
                    kwargs={
                        'invite_id': invite.pk,
                        'question_number': question_number,
                    },
                ),
                {'choice': 'B'},
            )

        self.assertRedirects(
            answer_response,
            detail_url,
            fetch_redirect_response=False,
        )
        invite.refresh_from_db()
        self.assertEqual(invite.status, ChoiceComparisonInvite.Status.COMPLETED)
        self.assertEqual(invite.participant, self.participant)
        self.assertEqual(invite.participant_answers, ['B'] * 7)
        self.assertTrue(
            SavedInstantResult.objects.filter(
                user=self.participant,
                game_token=invite.pk.hex,
            ).exists()
        )

        result_page = self.client.get(detail_url)
        self.assertContains(result_page, '우리의 결정 궁합')
        self.assertContains(result_page, '같은 선택 3개')
        self.assertContains(result_page, '엇갈린 선택 4개')
        self.assertContains(result_page, '가장 크게 의견이 갈린 문항')

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def test_expired_invite_closes_and_creator_can_reissue(self) -> None:
        invite = self.create_invite()
        ChoiceComparisonInvite.objects.filter(pk=invite.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        closed_page = self.client.get(
            reverse('games:together_detail', kwargs={'invite_id': invite.pk})
        )

        self.assertContains(closed_page, '초대 기간이 만료되었어요')
        invite.refresh_from_db()
        self.assertEqual(invite.status, ChoiceComparisonInvite.Status.EXPIRED)

        reissue_response = self.client.post(
            reverse('games:together_reissue', kwargs={'invite_id': invite.pk})
        )
        new_invite = (
            ChoiceComparisonInvite.objects
            .filter(creator=self.creator)
            .exclude(pk=invite.pk)
            .get()
        )
        self.assertRedirects(
            reissue_response,
            reverse(
                'games:together_detail',
                kwargs={'invite_id': new_invite.pk},
            ),
            fetch_redirect_response=False,
        )
        self.assertGreater(new_invite.expires_at, timezone.now())

    def test_creator_can_cancel_open_invite_but_outsider_cannot(self) -> None:
        invite = self.create_invite()
        cancel_url = reverse(
            'games:together_cancel',
            kwargs={'invite_id': invite.pk},
        )
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(cancel_url).status_code, 404)

        self.client.force_login(self.creator)
        self.client.post(cancel_url)
        invite.refresh_from_db()
        self.assertEqual(invite.status, ChoiceComparisonInvite.Status.CANCELED)
        self.assertIsNotNone(invite.canceled_at)

    def test_completed_invite_notifies_creator_until_result_is_opened(self) -> None:
        invite = self.create_invite()
        invite.participant = self.participant
        invite.participant_answers = ['B'] * 7
        invite.participant_result = {'mbti': 'ISTP'}
        invite.status = ChoiceComparisonInvite.Status.COMPLETED
        invite.completed_at = timezone.now()
        invite.save()

        hub_page = self.client.get(reverse('games:member_hub'))
        self.assertContains(hub_page, '친구의 선택이 도착한 함께하기 결과가 1개')

        self.client.get(
            reverse('games:together_detail', kwargs={'invite_id': invite.pk})
        )
        invite.refresh_from_db()
        self.assertIsNotNone(invite.creator_seen_at)

        refreshed_hub = self.client.get(reverse('games:member_hub'))
        self.assertNotContains(
            refreshed_hub,
            '친구의 선택이 도착한 함께하기 결과가 1개',
        )


@override_settings(OPENAI_API_KEY='')
class ArchiveReportAndRecommendationTest(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(
            username='archive-member',
            email='archive@example.com',
            password='A-strong-password-2026',
        )
        self.client.force_login(self.user)

    def test_archive_paginates_and_filters_search_mbti_and_favorites(self) -> None:
        for index in range(12):
            result = make_saved_member_result(
                self.user,
                token=f'{index:032x}',
                topic=(
                    '특별한 섬 선택'
                    if index == 11
                    else f'일상 선택 {index}'
                ),
                mbti='INFP' if index == 11 else 'ENTJ',
            )
            if index == 11:
                result.keywords = ['제주']
                result.is_favorite = True
                result.save(update_fields=['keywords', 'is_favorite'])

        first_page = self.client.get(reverse('games:progress'))
        self.assertEqual(len(first_page.context['saved_instant_results']), 10)
        self.assertEqual(
            first_page.context['saved_instant_results'].paginator.num_pages,
            2,
        )

        second_page = self.client.get(reverse('games:progress'), {'page': 2})
        self.assertEqual(len(second_page.context['saved_instant_results']), 2)

        filtered = self.client.get(reverse('games:progress'), {
            'q': '제주',
            'mbti': 'INFP',
            'favorite': '1',
        })
        self.assertEqual(filtered.context['filtered_result_count'], 1)
        self.assertContains(filtered, '특별한 섬 선택')
        self.assertNotContains(filtered, '일상 선택 1')

    def test_report_stays_exploratory_until_three_games(self) -> None:
        make_saved_member_result(self.user, token='a' * 32)
        make_saved_member_result(self.user, token='b' * 32)

        exploring = self.client.get(reverse('games:choice_report'))

        self.assertFalse(exploring.context['report']['is_ready'])
        self.assertEqual(exploring.context['report']['remaining_to_ready'], 1)
        self.assertIsNone(exploring.context['report']['representative_mbti'])
        self.assertContains(exploring, '탐색 중')

        make_saved_member_result(self.user, token='c' * 32)
        ready = self.client.get(reverse('games:choice_report'))
        self.assertTrue(ready.context['report']['is_ready'])
        self.assertEqual(ready.context['report']['confidence_label'], '초기 방향')
        self.assertIsNotNone(ready.context['report']['representative_mbti'])

    def test_member_game_events_are_recorded_once_per_game_stage(self) -> None:
        generated = self.client.post(
            reverse('games:instant_generate'),
            {
                'keywords': '여름휴가',
                'recommendation_source': 'seasonal',
            },
        )
        self.assertEqual(generated.status_code, 302)
        game_token = self.client.session['instant_game']['token']
        started = MemberGameEvent.objects.get(
            user=self.user,
            game_token=game_token,
            event_type=MemberGameEvent.EventType.STARTED,
        )
        self.assertEqual(started.source, 'seasonal')

        for question_number in range(1, 8):
            self.client.post(
                reverse(
                    'games:instant_answer',
                    kwargs={'question_number': question_number},
                ),
                {'choice': 'A'},
            )
        self.client.get(reverse('games:instant_result'))
        self.client.get(reverse('games:instant_result'))

        self.assertEqual(
            MemberGameEvent.objects.filter(
                user=self.user,
                game_token=game_token,
                event_type=MemberGameEvent.EventType.COMPLETED,
            ).count(),
            1,
        )

    def test_feedback_hides_topics_and_saves_liked_topics(self) -> None:
        make_saved_member_result(self.user, topic='여행 선택')
        feedback_url = reverse('games:recommendation_feedback')

        self.client.post(feedback_url, {
            'keyword': '여행',
            'rating': RecommendationFeedback.Rating.HIDE,
        })
        hidden_hub = self.client.get(reverse('games:member_hub'))
        recent_keywords = [
            keyword
            for keyword, _score
            in hidden_hub.context['recommendations']['recent_interests']
        ]
        self.assertNotIn('여행', recent_keywords)

        self.client.post(feedback_url, {
            'keyword': '봄 나들이',
            'rating': RecommendationFeedback.Rating.LIKE,
        })
        liked_hub = self.client.get(reverse('games:member_hub'))
        self.assertIn(
            '봄 나들이',
            liked_hub.context['recommendations']['liked_topics'],
        )
        liked_feedback = RecommendationFeedback.objects.get(
            user=self.user,
            keyword='봄 나들이',
        )
        reset_url = reverse(
            'games:recommendation_feedback_delete',
            kwargs={'feedback_id': liked_feedback.pk},
        )
        other = get_user_model().objects.create_user(
            username='feedback-other',
            password='A-strong-password-2026',
        )
        self.client.force_login(other)
        self.assertEqual(self.client.post(reset_url).status_code, 404)
        self.client.force_login(self.user)
        self.client.post(reset_url)
        self.assertFalse(
            RecommendationFeedback.objects.filter(pk=liked_feedback.pk).exists()
        )


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class AccountManagementTest(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(
            username='account-member',
            email='account@example.com',
            password='A-strong-password-2026',
        )
        self.other = get_user_model().objects.create_user(
            username='other-account',
            email='other@example.com',
            password='A-strong-password-2026',
        )
        self.result = make_saved_member_result(self.user)
        self.other_result = make_saved_member_result(
            self.other,
            token='b' * 32,
        )
        self.client.force_login(self.user)

    def test_password_reset_sends_email_without_revealing_account_state(self) -> None:
        self.client.logout()
        response = self.client.post(
            reverse('games:password_reset'),
            {'email': self.user.email},
        )

        self.assertRedirects(
            response,
            reverse('games:password_reset_done'),
            fetch_redirect_response=False,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('비밀번호 재설정', mail.outbox[0].subject)
        self.assertIn('/accounts/reset/', mail.outbox[0].body)

    def test_export_contains_only_signed_in_members_data(self) -> None:
        response = self.client.get(reverse('games:account_export'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        payload = response.json()
        self.assertEqual(payload['account']['username'], self.user.username)
        self.assertEqual(len(payload['saved_results']), 1)
        self.assertEqual(
            payload['saved_results'][0]['topic'],
            self.result.topic,
        )
        self.assertNotIn(self.other.username, response.content.decode())

    def test_clear_history_requires_phrase_and_scrubs_joined_invite(self) -> None:
        joined_invite = ChoiceComparisonInvite.objects.create(
            creator=self.other,
            source_result=self.other_result,
            participant=self.user,
            participant_answers=['A'] * 7,
            participant_result={'mbti': 'ENTJ'},
            status=ChoiceComparisonInvite.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        clear_url = reverse('games:account_clear_history')

        self.client.post(clear_url, {'confirmation': '잘못입력'})
        self.assertTrue(
            SavedInstantResult.objects.filter(user=self.user).exists()
        )

        self.client.post(clear_url, {'confirmation': '기록삭제'})
        self.assertFalse(
            SavedInstantResult.objects.filter(user=self.user).exists()
        )
        self.assertTrue(
            SavedInstantResult.objects.filter(user=self.other).exists()
        )
        joined_invite.refresh_from_db()
        self.assertIsNone(joined_invite.participant)
        self.assertEqual(joined_invite.participant_answers, [])
        self.assertEqual(joined_invite.status, ChoiceComparisonInvite.Status.CANCELED)

    def test_account_deletion_requires_current_password(self) -> None:
        delete_url = reverse('games:account_delete')
        self.client.post(delete_url, {
            'password': 'wrong-password',
            'confirmation': '회원탈퇴',
        })
        self.assertTrue(
            get_user_model().objects.filter(pk=self.user.pk).exists()
        )

        response = self.client.post(delete_url, {
            'password': 'A-strong-password-2026',
            'confirmation': '회원탈퇴',
        })
        self.assertRedirects(
            response,
            reverse('games:index'),
            fetch_redirect_response=False,
        )
        self.assertFalse(
            get_user_model().objects.filter(pk=self.user.pk).exists()
        )

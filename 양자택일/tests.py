from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from .models import (
    Category,
    Choice,
    GameSet,
    Question,
    ResultGrade,
    ResultTemplate,
    Vote,
)
from .services import (
    ResultData,
    TemplateResultGenerator,
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

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from .models import Category, Choice, Question, ResultGrade, ResultTemplate, Vote
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

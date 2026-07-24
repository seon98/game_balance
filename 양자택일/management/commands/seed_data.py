from __future__ import annotations

from django.core.management.base import BaseCommand

from 양자택일.models import (
    Category,
    Choice,
    GameSet,
    Question,
    ResultGrade,
    ResultTemplate,
)
from 양자택일.official_content import ADDITIONAL_QUESTIONS, OFFICIAL_SETS


CATEGORIES: list[dict] = [
    {'name': '음식', 'slug': 'food'},
    {'name': '연애', 'slug': 'romance'},
    {'name': '직장', 'slug': 'work'},
    {'name': '학교', 'slug': 'school'},
    {'name': '일상', 'slug': 'daily'},
    {'name': '야구', 'slug': 'baseball'},
    {'name': '개발자', 'slug': 'developer'},
]

QUESTIONS: list[dict] = [
    # 음식
    {
        'category': '음식',
        'title': '평생 치킨만 먹기 vs 평생 피자만 먹기',
        'choice_a': '평생 치킨만 먹기',
        'choice_b': '평생 피자만 먹기',
    },
    {
        'category': '음식',
        'title': '라면에 밥 말아먹기 vs 라면 먹고 밥 따로 먹기',
        'choice_a': '라면에 밥 말아먹기',
        'choice_b': '라면 먹고 밥 따로 먹기',
    },
    {
        'category': '음식',
        'title': '단 음식만 먹기 vs 짠 음식만 먹기',
        'choice_a': '단 음식(케이크, 초콜릿 등)만 먹기',
        'choice_b': '짠 음식(김치찌개, 라면 등)만 먹기',
    },
    # 연애
    {
        'category': '연애',
        'title': '외모 최상 성격 최악 vs 외모 최악 성격 최상',
        'choice_a': '외모는 최상이지만 성격은 최악인 사람과 사귀기',
        'choice_b': '외모는 최악이지만 성격은 최상인 사람과 사귀기',
    },
    {
        'category': '연애',
        'title': '썸만 타다 끝나기 vs 사귀자마자 바로 헤어지기',
        'choice_a': '3개월 썸만 타다가 결국 연락 끊기기',
        'choice_b': '사귀자마자 2일 만에 헤어지기',
    },
    {
        'category': '연애',
        'title': '장거리 연애 vs 매일 붙어있는 연애',
        'choice_a': '비행기 타야 만나는 장거리 연애',
        'choice_b': '직장도 집도 같아서 매일 24시간 함께',
    },
    # 직장
    {
        'category': '직장',
        'title': '연봉 2배지만 매일 야근 vs 현재 연봉으로 칼퇴근',
        'choice_a': '연봉 2배지만 매일 밤 11시 퇴근',
        'choice_b': '현재 연봉 그대로 매일 오후 6시 칼퇴',
    },
    {
        'category': '직장',
        'title': '꼰대 상사와 연봉 6천 vs 좋은 상사와 연봉 3천',
        'choice_a': '매일 갈굼받는 꼰대 상사와 함께, 연봉 6천만원',
        'choice_b': '배려 넘치는 좋은 상사와 함께, 연봉 3천만원',
    },
    {
        'category': '직장',
        'title': '재택근무 100% vs 사무실 출근 100%',
        'choice_a': '집에서만 일하는 완전 재택근무',
        'choice_b': '매일 사무실에 출근하는 완전 대면근무',
    },
    # 학교
    {
        'category': '학교',
        'title': '전교 1등이지만 친구 없기 vs 전교 꼴등이지만 인기 최고',
        'choice_a': '성적은 전교 1등이지만 친구가 단 한 명도 없기',
        'choice_b': '성적은 전교 꼴등이지만 누구에게나 사랑받는 인기쟁이',
    },
    {
        'category': '학교',
        'title': '시험 없이 숙제만 vs 숙제 없이 시험만',
        'choice_a': '시험은 없고 매일 숙제 5시간',
        'choice_b': '숙제는 없고 매일 시험 1번',
    },
    # 일상
    {
        'category': '일상',
        'title': '휴대전화 없이 한 달 살기 vs 컴퓨터 없이 한 달 살기',
        'choice_a': '스마트폰 없이 한 달 살기',
        'choice_b': '컴퓨터·태블릿 없이 한 달 살기',
    },
    {
        'category': '일상',
        'title': '평생 여름 vs 평생 겨울',
        'choice_a': '일 년 내내 여름 (35도, 해변과 수박)',
        'choice_b': '일 년 내내 겨울 (-5도, 눈과 따뜻한 코코아)',
    },
    # 야구
    {
        'category': '야구',
        'title': '응원팀이 매년 준우승 vs 10년에 한 번 우승',
        'choice_a': '매년 한국시리즈까지 가지만 항상 준우승',
        'choice_b': '9년 동안 꼴찌이다가 10년째에 극적으로 우승',
    },
    {
        'category': '야구',
        'title': '시즌 내내 1위 달리다 포스트시즌 탈락 vs 꼴찌로 시작해 기적의 우승',
        'choice_a': '4월부터 9월까지 1위였는데 와일드카드에서 탈락',
        'choice_b': '9월까지 꼴찌이다가 기적 같은 역전으로 통합 우승',
    },
    # 개발자
    {
        'category': '개발자',
        'title': '프론트엔드만 하기 vs 백엔드만 하기',
        'choice_a': '평생 프론트엔드(React, CSS 등)만 개발',
        'choice_b': '평생 백엔드(API, DB 등)만 개발',
    },
    {
        'category': '개발자',
        'title': '연봉 1억 레거시 유지보수 vs 연봉 5천 최신 스택 신규 개발',
        'choice_a': '연봉 1억이지만 20년 된 레거시 코드 유지보수',
        'choice_b': '연봉 5천만원이지만 최신 기술로 새 서비스 개발',
    },
]

QUESTIONS.extend(ADDITIONAL_QUESTIONS)

RESULT_TEMPLATES: list[dict] = [
    # LEGENDARY_MINORITY (3개)
    {
        'grade': ResultGrade.LEGENDARY_MINORITY,
        'title': '{choice_text}를 선택한 전설적인 소수파!',
        'description': (
            '전체 {total_votes}명 중 단 {percentage}%만 {choice_text}을(를) 선택했어요. '
            '100명 중 약 {same_people}명만 당신과 같은 길을 걸었답니다. '
            '이런 선택을 하다니, 취향만큼은 정말 독보적이군요! '
            '다수가 가지 않는 길을 걷는 것, 그게 당신만의 매력일 수 있어요.'
        ),
        'keywords': ['독보적', '희귀', '개성'],
        'share_text': '나는 {percentage}% 전설의 소수파 {choice_text}파! 당신의 선택은?',
    },
    {
        'grade': ResultGrade.LEGENDARY_MINORITY,
        'title': '100명 중 {same_people}명의 비밀 클럽, 어서오세요!',
        'description': (
            '{percentage}%라는 놀라운 소수만 {choice_text}을(를) 골랐어요. '
            '대중의 취향과는 다른 나만의 기준이 있는 것 같군요. '
            '이런 선택은 쉽게 흔들리지 않는 확고한 자아를 가진 사람에게서 나올 수 있어요. '
            '비밀 소수파 클럽에 오신 걸 환영합니다!'
        ),
        'keywords': ['확고함', '소신', '특별함'],
        'share_text': '{same_people}명만 선택한 {choice_text}파 클럽 입장! 당신은?',
    },
    {
        'grade': ResultGrade.LEGENDARY_MINORITY,
        'title': '희귀 등급 달성! {choice_text} 선택자 발견!',
        'description': (
            '{total_votes}명 중 {percentage}%, 즉 약 {same_people}명이 같은 선택을 했어요. '
            '혹시 평소에도 남들과 다른 길을 즐기시나요? '
            '다수결보다 자신의 감각을 믿는 사람이라면 이런 선택이 자연스러울 수 있어요. '
            '희귀한 취향, 오히려 좋아!'
        ),
        'keywords': ['독자적', '창의', '비범'],
        'share_text': '희귀 등급 {percentage}% {choice_text}파! 같은 선택이라면 댓글로!',
    },
    # RARE (3개)
    {
        'grade': ResultGrade.RARE,
        'title': '대세를 거부한 {choice_text} 마이웨이형',
        'description': (
            '전체 참여자의 {percentage}%만 {choice_text}을(를) 선택했습니다. '
            '100명 중 약 {same_people}명이 당신과 같은 선택을 했어요. '
            '익숙한 선택보다는 다양성과 개성을 중요하게 생각하는 편이군요. '
            '사람들의 선택보다 자신의 취향을 믿고 움직이는 독립적인 스타일에 가깝습니다.'
        ),
        'keywords': ['개성적', '독립적', '다양성'],
        'share_text': '나는 {percentage}% 희귀 {choice_text}파! 당신의 선택은?',
    },
    {
        'grade': ResultGrade.RARE,
        'title': '{choice_text}를 고른 희귀 취향 발견!',
        'description': (
            '{percentage}%의 소수파로서 {choice_text}을(를) 선택하셨군요. '
            '남들이 잘 가지 않는 선택을 할 수 있다는 건, '
            '자신만의 확고한 기준을 가졌다는 의미일 수 있어요. '
            '희귀한 취향이 오히려 개성이 되는 시대, 당신은 트렌드세터가 될지도 몰라요!'
        ),
        'keywords': ['트렌드세터', '선구자', '개성'],
        'share_text': '희귀 {percentage}% {choice_text}파 발견! 당신은 어느 쪽?',
    },
    {
        'grade': ResultGrade.RARE,
        'title': '소수의 길을 택한 {choice_text} 선택자',
        'description': (
            '{total_votes}명 중 {percentage}%인 약 {same_people}명만이 {choice_text}을(를) 골랐어요. '
            '주류와 다른 선택을 즐기는 편이라면, 새로운 것에 열려 있는 사람일 가능성이 있어요. '
            '이런 선택력이 일상에서도 빛날 수 있답니다!'
        ),
        'keywords': ['개방적', '독창적', '선택력'],
        'share_text': '나는 소수파 {percentage}% {choice_text}! 당신의 취향은?',
    },
    # MINORITY (3개)
    {
        'grade': ResultGrade.MINORITY,
        'title': '소수 취향의 {choice_text} 선택자!',
        'description': (
            '{percentage}%가 같은 선택을 했습니다. '
            '소수파이지만 분명히 공감하는 사람이 있다는 뜻이에요. '
            '자신의 기준이 뚜렷한 편이거나, '
            '다수의 의견보다 본인의 감각을 우선시하는 성향일 수 있어요.'
        ),
        'keywords': ['소수파', '소신', '뚜렷함'],
        'share_text': '나는 소수파 {percentage}% {choice_text}! 당신은?',
    },
    {
        'grade': ResultGrade.MINORITY,
        'title': '{choice_text}, 少 이지만 確한 선택',
        'description': (
            '전체의 {percentage}%가 {choice_text}을(를) 선택했어요. '
            '소수이지만 확실한 취향을 가진 사람들이 같은 선택을 했군요. '
            '한 번의 선택으로 성격을 단정 짓긴 어렵지만, '
            '독자적인 판단을 즐기는 편일 수 있어요.'
        ),
        'keywords': ['독자적', '주관적', '확실함'],
        'share_text': '{percentage}% 소수파이지만 확실한 {choice_text}파! 같은 편 있나요?',
    },
    {
        'grade': ResultGrade.MINORITY,
        'title': '진짜 {choice_text}파 {percentage}% 등장!',
        'description': (
            '100명 중 약 {same_people}명이 {choice_text}을(를) 골랐어요. '
            '소수이긴 하지만, 이 선택에는 나름의 확실한 이유가 있을 것 같아요. '
            '자기 의견을 쉽게 바꾸지 않는 타입이거나, '
            '독특한 시각을 즐기는 사람일 가능성이 있어요.'
        ),
        'keywords': ['일관성', '고집', '자기확신'],
        'share_text': '나는 진짜 {percentage}% {choice_text}파! 당신의 선택은?',
    },
    # BALANCED (3개)
    {
        'grade': ResultGrade.BALANCED,
        'title': '팽팽한 선택, 당신은 {choice_text}!',
        'description': (
            '{percentage}%가 {choice_text}을(를) 선택했습니다. '
            '두 선택지가 팽팽하게 맞서는 상황에서 당신의 선택이 무게추가 됐네요. '
            '어느 쪽이든 충분히 이해할 수 있는 상황, '
            '균형 잡힌 시각으로 양쪽을 바라볼 수 있는 편일 수 있어요.'
        ),
        'keywords': ['균형', '유연함', '이해력'],
        'share_text': '팽팽한 {percentage}% vs {percentage}%! 나는 {choice_text}파, 당신은?',
    },
    {
        'grade': ResultGrade.BALANCED,
        'title': '반반의 균형, 당신의 선택은 {choice_text}',
        'description': (
            '{total_votes}명이 거의 반반으로 나뉜 이 질문에서 {choice_text}을(를) 선택하셨군요. '
            '정말 많은 사람들이 고민했을 것 같아요. '
            '선택하기 어려운 상황에서도 결정을 내릴 수 있는 결단력이 있을 수 있어요!'
        ),
        'keywords': ['결단력', '중용', '균형감'],
        'share_text': '거의 반반인 선택! 나는 {choice_text}파! 당신은?',
    },
    {
        'grade': ResultGrade.BALANCED,
        'title': '오차 범위 안의 선택, {choice_text} 소속!',
        'description': (
            '{percentage}%가 같은 선택이에요. '
            '두 선택지가 얼마나 팽팽한지 느껴지시나요? '
            '이런 균형 잡힌 질문에서 결정을 내린 당신, '
            '양쪽의 장단점을 충분히 고려하는 신중한 스타일일 가능성이 있어요.'
        ),
        'keywords': ['신중함', '고려', '판단력'],
        'share_text': '나는 {percentage}% {choice_text}파! 팽팽한 선택, 당신은?',
    },
    # MAJORITY (3개)
    {
        'grade': ResultGrade.MAJORITY,
        'title': '공감받는 선택, {choice_text}!',
        'description': (
            '{percentage}%가 같은 선택을 했습니다. '
            '절반 이상이 당신과 같은 생각이었군요. '
            '공감 능력이 뛰어나거나 실용적인 판단을 즐기는 편일 수 있어요. '
            '많은 사람의 공감을 얻는 선택이라는 게 나쁜 건 아니에요!'
        ),
        'keywords': ['공감력', '실용적', '대중성'],
        'share_text': '나는 {percentage}% 공감 {choice_text}파! 당신은?',
    },
    {
        'grade': ResultGrade.MAJORITY,
        'title': '다수가 공감한 {choice_text} 선택!',
        'description': (
            '{total_votes}명 중 {percentage}%가 {choice_text}을(를) 선택했어요. '
            '많은 사람이 비슷한 생각을 하고 있었던 것 같아요. '
            '보편적인 가치를 이해하거나, '
            '트렌드를 잘 파악하는 감각이 있을 수 있어요.'
        ),
        'keywords': ['트렌드 감각', '공감대', '보편'],
        'share_text': '{percentage}%가 공감한 {choice_text}파! 함께해요!',
    },
    {
        'grade': ResultGrade.MAJORITY,
        'title': '대세를 읽은 {choice_text} 선택',
        'description': (
            '{percentage}%, 즉 약 {same_people}명이 {choice_text}을(를) 골랐어요. '
            '많은 사람과 같은 선택을 했다는 건, '
            '사회적 흐름을 자연스럽게 읽는 편이거나 '
            '안정적인 선택을 선호하는 성향일 수 있어요.'
        ),
        'keywords': ['안정적', '사회적', '흐름'],
        'share_text': '나는 {percentage}% 대세 {choice_text}파! 당신도?',
    },
    # POPULAR (3개)
    {
        'grade': ResultGrade.POPULAR,
        'title': '인기 선택! {choice_text} {percentage}% 등장',
        'description': (
            '{percentage}%라는 높은 비율이 {choice_text}을(를) 선택했습니다. '
            '많은 사람들이 비슷한 생각을 하고 있었군요. '
            '트렌드를 잘 읽거나 보편적인 가치를 중요시하는 편일 수 있어요. '
            '혹시 주변 사람들에게 인기가 많으신 건 아닌가요?'
        ),
        'keywords': ['인기', '대세', '트렌드'],
        'share_text': '{percentage}% 인기 {choice_text}파! 대세를 따랐어요!',
    },
    {
        'grade': ResultGrade.POPULAR,
        'title': '10명 중 7명의 선택, {choice_text}!',
        'description': (
            '{total_votes}명 중 {percentage}%가 {choice_text}을(를) 골랐어요. '
            '많은 사람이 공감하는 선택이에요. '
            '사람들의 마음을 읽는 감각이 있거나, '
            '다수가 좋다고 하는 것에 이유가 있다는 걸 아는 현실적인 스타일일 수 있어요.'
        ),
        'keywords': ['현실적', '공감', '주류'],
        'share_text': '{percentage}% 인기 선택 {choice_text}! 같은 편 모여라!',
    },
    {
        'grade': ResultGrade.POPULAR,
        'title': '{choice_text}, 대부분의 선택에 함께한 당신',
        'description': (
            '{percentage}%가 같은 길을 선택했어요. '
            '이건 단순히 대세를 따른 게 아니라, '
            '많은 사람이 공감할 수 있는 가치를 선택한 것일 수 있어요. '
            '보편적인 매력을 가진 선택이에요!'
        ),
        'keywords': ['보편적 매력', '공감', '인기'],
        'share_text': '나는 {percentage}% {choice_text}파! 인기 선택 확인!',
    },
    # OVERWHELMING (3개)
    {
        'grade': ResultGrade.OVERWHELMING,
        'title': '압도적! 대세는 {choice_text}!',
        'description': (
            '무려 {percentage}%가 {choice_text}을(를) 선택했습니다. '
            '거의 모든 사람이 같은 생각이었군요! '
            '대세를 함께하는 안정적인 선택을 하거나, '
            '이 선택지가 그만큼 매력적이라는 뜻일 수 있어요!'
        ),
        'keywords': ['대세', '압도적', '대중적'],
        'share_text': '무려 {percentage}%! 압도적 {choice_text}파! 당신은?',
    },
    {
        'grade': ResultGrade.OVERWHELMING,
        'title': '{total_votes}명 중 {percentage}%, 대세의 흐름을 탔어요!',
        'description': (
            '{percentage}%라는 압도적인 비율이 {choice_text}을(를) 선택했어요. '
            '거의 모든 사람이 같은 방향을 바라보고 있었군요. '
            '많은 사람의 공감을 얻는 선택을 했다는 건, '
            '누구와도 통할 수 있는 보편적인 감각을 가졌다는 뜻일 수 있어요.'
        ),
        'keywords': ['보편', '안정', '대세'],
        'share_text': '{percentage}% 압도적 {choice_text}파! 대세에 합류!',
    },
    {
        'grade': ResultGrade.OVERWHELMING,
        'title': '명백한 승자, {choice_text}!',
        'description': (
            '{percentage}%가 {choice_text}을(를) 선택한 결과, 명백한 대세가 형성됐어요. '
            '100명 중 {same_people}명이 같은 선택을 했다니 대단하네요. '
            '사람들이 공감하는 선택을 직관적으로 고르는 감각이 있을 수 있어요. '
            '주변 사람들과 어울리는 것도 좋아하시나요?'
        ),
        'keywords': ['직관력', '어울림', '대중성'],
        'share_text': '{percentage}% 압승! 나는 {choice_text}파! 당신의 선택은?',
    },
]


class Command(BaseCommand):
    help = '밸런스게임 샘플 데이터를 생성합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='기존 데이터를 모두 삭제하고 새로 생성합니다.',
        )

    def handle(self, *args, **options):
        if options['reset']:
            Question.objects.all().delete()
            GameSet.objects.all().delete()
            Category.objects.all().delete()
            ResultTemplate.objects.all().delete()
            self.stdout.write(self.style.WARNING('기존 데이터를 삭제했습니다.'))

        self._create_categories()
        self._create_official_sets()
        self._create_questions()
        self._create_result_templates()

        self.stdout.write(self.style.SUCCESS('샘플 데이터 생성이 완료되었습니다!'))

    def _create_categories(self) -> None:
        for data in CATEGORIES:
            cat, created = Category.objects.get_or_create(
                slug=data['slug'],
                defaults={'name': data['name']},
            )
            if created:
                self.stdout.write(f'  카테고리 생성: {cat.name}')

    def _create_official_sets(self) -> None:
        self.official_sets: dict[str, GameSet] = {}
        for category_name, data in OFFICIAL_SETS.items():
            category = Category.objects.get(name=category_name)
            game_set, created = GameSet.objects.update_or_create(
                category=category,
                is_official=True,
                defaults={
                    'creator': None,
                    'title': data['title'],
                    'description': data['description'],
                    'status': GameSet.Status.APPROVED,
                    'content_basis': GameSet.ContentBasis.HYPOTHETICAL,
                },
            )
            self.official_sets[category_name] = game_set
            if created:
                self.stdout.write(f'  공식 게임 생성: {game_set.title}')

    def _create_questions(self) -> None:
        Question.objects.filter(title__contains='�대 상사').update(
            title='꼰대 상사와 연봉 6천 vs 좋은 상사와 연봉 3천'
        )
        for data in QUESTIONS:
            category = Category.objects.get(name=data['category'])
            game_set = self.official_sets[data['category']]
            question, created = Question.objects.update_or_create(
                title=data['title'],
                defaults={
                    'category': category,
                    'game_set': game_set,
                    'description': data.get('description', ''),
                    'is_active': True,
                },
            )
            Choice.objects.update_or_create(
                question=question,
                code=Choice.Code.A,
                defaults={'text': data['choice_a']},
            )
            Choice.objects.update_or_create(
                question=question,
                code=Choice.Code.B,
                defaults={'text': data['choice_b']},
            )
            if created:
                self.stdout.write(f'  질문 생성: {question.title}')

        for game_set in self.official_sets.values():
            game_set.validate_submission()

    def _create_result_templates(self) -> None:
        for data in RESULT_TEMPLATES:
            _, created = ResultTemplate.objects.get_or_create(
                grade=data['grade'],
                title=data['title'],
                defaults={
                    'description': data['description'],
                    'keywords': data['keywords'],
                    'share_text': data['share_text'],
                    'is_active': True,
                },
            )
            if created:
                grade_display = ResultGrade(data['grade']).label
                self.stdout.write(f'  결과 템플릿 생성: [{grade_display}] {data["title"][:30]}…')

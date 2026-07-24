from __future__ import annotations

import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.forms import BaseFormSet, formset_factory

from .models import (
    Category,
    Choice,
    GameSet,
    Question,
    RecommendationFeedback,
)
from .moderation import requires_reference, validate_safe_text


def clean_generation_keywords(raw_keywords: str) -> list[str]:
    keywords: list[str] = []
    for raw_keyword in re.split(r'[,\n]+', raw_keywords):
        keyword = raw_keyword.strip()
        if keyword.startswith('#'):
            keyword = keyword[1:].strip()
        if not keyword:
            continue
        if len(keyword) > 30:
            raise forms.ValidationError('키워드는 각각 30자 이하로 입력해주세요.')
        if re.search(r'[<>{}\\|;]', keyword):
            raise forms.ValidationError('키워드에 사용할 수 없는 특수문자가 포함되어 있습니다.')
        if not re.search(r'[0-9A-Za-z가-힣]', keyword):
            raise forms.ValidationError('의미가 있는 키워드를 입력해주세요.')
        validate_safe_text(keyword)
        if requires_reference(keyword):
            raise forms.ValidationError(
                '검증이 필요한 단정 표현은 자동 생성 키워드로 사용할 수 없습니다.'
            )
        normalized = keyword.casefold()
        if normalized not in {item.casefold() for item in keywords}:
            keywords.append(keyword)

    if not keywords:
        raise forms.ValidationError('한 개 이상의 키워드를 입력해주세요.')
    if len(keywords) > 5:
        raise forms.ValidationError('키워드는 최대 5개까지 입력할 수 있습니다.')
    return keywords


class VoteForm(forms.Form):
    choice = forms.ModelChoiceField(
        queryset=Choice.objects.none(),
        widget=forms.HiddenInput(),
        error_messages={'required': '선택지를 골라주세요.', 'invalid_choice': '올바른 선택지가 아닙니다.'},
    )

    def __init__(self, *args: object, question: Question | None = None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        if question is not None:
            self.fields['choice'].queryset = question.choices.all()


class SignupForm(UserCreationForm):
    email = forms.EmailField(label='이메일', required=True)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'email')
        labels = {'username': '아이디'}

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def clean_email(self) -> str:
        email = self.cleaned_data['email'].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('이미 사용 중인 이메일입니다.')
        return email


class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields['username'].label = '아이디'
        self.fields['password'].label = '비밀번호'
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class AccountHistoryClearForm(forms.Form):
    confirmation = forms.CharField(
        label='확인 문구',
        max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '기록삭제',
            'autocomplete': 'off',
        }),
    )

    def clean_confirmation(self) -> str:
        confirmation = self.cleaned_data['confirmation'].strip()
        if confirmation != '기록삭제':
            raise forms.ValidationError('확인 문구에 ‘기록삭제’를 입력해주세요.')
        return confirmation


class AccountDeleteForm(forms.Form):
    password = forms.CharField(
        label='현재 비밀번호',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'current-password',
        }),
    )
    confirmation = forms.CharField(
        label='확인 문구',
        max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '회원탈퇴',
            'autocomplete': 'off',
        }),
    )

    def __init__(self, *args: object, user=None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self) -> str:
        password = self.cleaned_data['password']
        if self.user is None or not self.user.check_password(password):
            raise forms.ValidationError('현재 비밀번호가 일치하지 않습니다.')
        return password

    def clean_confirmation(self) -> str:
        confirmation = self.cleaned_data['confirmation'].strip()
        if confirmation != '회원탈퇴':
            raise forms.ValidationError('확인 문구에 ‘회원탈퇴’를 입력해주세요.')
        return confirmation


class RecommendationFeedbackForm(forms.Form):
    keyword = forms.CharField(max_length=30)
    rating = forms.ChoiceField(choices=RecommendationFeedback.Rating.choices)

    def clean_keyword(self) -> str:
        keywords = clean_generation_keywords(self.cleaned_data['keyword'])
        if len(keywords) != 1:
            raise forms.ValidationError('한 번에 하나의 추천 주제만 평가해주세요.')
        return keywords[0]


class NicknameForm(forms.Form):
    nickname = forms.CharField(
        label='결과에 표시할 이름',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '입력하지 않으면 참여자로 표시됩니다.',
            'autocomplete': 'nickname',
        }),
    )

    def clean_nickname(self) -> str:
        nickname = self.cleaned_data['nickname'].strip()
        validate_safe_text(nickname)
        return nickname


class QuestionDraftGeneratorForm(forms.Form):
    keywords = forms.CharField(max_length=160)
    count = forms.IntegerField(
        min_value=GameSet.MIN_QUESTIONS,
        max_value=GameSet.MAX_QUESTIONS,
    )
    category = forms.ModelChoiceField(queryset=Category.objects.all())

    def clean_keywords(self) -> list[str]:
        return clean_generation_keywords(self.cleaned_data['keywords'])


class InstantGameSearchForm(forms.Form):
    keywords = forms.CharField(
        label='플레이할 주제',
        max_length=160,
        widget=forms.TextInput(attrs={
            'id': 'instantKeywords',
            'class': 'instant-search-input',
            'placeholder': '원하는 키워드를 입력하세요...',
            'autocomplete': 'off',
            'aria-label': '바로 플레이할 키워드',
        }),
    )

    def clean_keywords(self) -> list[str]:
        return clean_generation_keywords(self.cleaned_data['keywords'])


class GameSetForm(forms.ModelForm):
    safety_agreement = forms.BooleanField(
        label='성인·혐오·불법 콘텐츠를 포함하지 않았으며 검수 정책에 동의합니다.',
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    class Meta:
        model = GameSet
        fields = [
            'title',
            'description',
            'category',
            'content_basis',
            'reference_url',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '예: 직장인의 현실적인 선택',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '주제와 문항의 기준을 간단히 설명해주세요.',
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'content_basis': forms.Select(attrs={'class': 'form-select'}),
            'reference_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https:// 신뢰할 수 있는 출처',
            }),
        }

    def clean(self) -> dict:
        cleaned_data = super().clean()
        title = cleaned_data.get('title', '')
        description = cleaned_data.get('description', '')
        content_basis = cleaned_data.get('content_basis')
        reference_url = cleaned_data.get('reference_url')

        for field_name, value in (('title', title), ('description', description)):
            try:
                validate_safe_text(value)
            except forms.ValidationError as exc:
                self.add_error(field_name, exc)

        if content_basis == GameSet.ContentBasis.SOURCED and not reference_url:
            self.add_error('reference_url', '사실·정보형 콘텐츠는 검증 자료 URL이 필요합니다.')
        if (
            requires_reference(title, description)
            and content_basis != GameSet.ContentBasis.SOURCED
        ):
            self.add_error(
                'content_basis',
                '검증이 필요한 표현이 포함되어 있습니다. 사실·정보형을 선택하고 근거 URL을 입력해주세요.',
            )
        return cleaned_data


class GameQuestionForm(forms.Form):
    title = forms.CharField(
        label='질문',
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '두 선택이 분명하게 드러나는 질문',
        }),
    )
    description = forms.CharField(
        label='설명',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': '필요한 경우 상황을 보충해주세요.',
        }),
    )
    choice_a = forms.CharField(
        label='선택 A',
        max_length=300,
        widget=forms.TextInput(attrs={
            'class': 'form-control choice-a-input',
            'placeholder': 'A 선택지',
        }),
    )
    choice_b = forms.CharField(
        label='선택 B',
        max_length=300,
        widget=forms.TextInput(attrs={
            'class': 'form-control choice-b-input',
            'placeholder': 'B 선택지',
        }),
    )

    def clean(self) -> dict:
        cleaned_data = super().clean()
        for field_name in ('title', 'description', 'choice_a', 'choice_b'):
            value = cleaned_data.get(field_name, '')
            try:
                validate_safe_text(value)
            except forms.ValidationError as exc:
                self.add_error(field_name, exc)

        choice_a = cleaned_data.get('choice_a', '').strip()
        choice_b = cleaned_data.get('choice_b', '').strip()
        if choice_a and choice_b and choice_a.casefold() == choice_b.casefold():
            self.add_error('choice_b', 'A와 B 선택지는 서로 달라야 합니다.')
        return cleaned_data


class BaseGameQuestionFormSet(BaseFormSet):
    def clean(self) -> None:
        super().clean()
        if any(self.errors):
            return

        titles: set[str] = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            title = form.cleaned_data['title'].strip().casefold()
            if title in titles:
                raise forms.ValidationError('같은 질문을 두 번 등록할 수 없습니다.')
            titles.add(title)


GameQuestionFormSet = formset_factory(
    GameQuestionForm,
    formset=BaseGameQuestionFormSet,
    extra=0,
    min_num=GameSet.MIN_QUESTIONS,
    max_num=GameSet.MAX_QUESTIONS,
    validate_min=True,
    validate_max=True,
    can_delete=True,
)

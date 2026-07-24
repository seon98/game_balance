from __future__ import annotations

from django import forms

from .models import Choice, Question


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

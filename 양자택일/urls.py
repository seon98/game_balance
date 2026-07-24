from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy

from . import views
from .forms import StyledAuthenticationForm

app_name = 'games'

urlpatterns = [
    path('', views.WelcomeView.as_view(), name='welcome'),
    path('home/', views.IndexView.as_view(), name='index'),
    path(
        'instant-game/generate/',
        views.InstantGameGenerateView.as_view(),
        name='instant_generate',
    ),
    path(
        'instant-game/<int:question_number>/',
        views.InstantGamePlayView.as_view(),
        name='instant_play',
    ),
    path(
        'instant-game/<int:question_number>/answer/',
        views.InstantGameAnswerView.as_view(),
        name='instant_answer',
    ),
    path(
        'instant-game/result/',
        views.InstantGameResultView.as_view(),
        name='instant_result',
    ),
    path('games/', views.GameListView.as_view(), name='list'),
    path('games/random/', views.RandomGameView.as_view(), name='random'),
    path('games/<int:question_id>/', views.QuestionDetailView.as_view(), name='detail'),
    path('games/<int:question_id>/vote/', views.VoteView.as_view(), name='vote'),
    path('games/<int:question_id>/result/', views.ResultView.as_view(), name='result'),
    path('my-results/', views.ProgressView.as_view(), name='progress'),
    path('members/', views.MemberHubView.as_view(), name='member_hub'),
    path('my-report/', views.ChoiceReportView.as_view(), name='choice_report'),
    path(
        'members/recommendations/feedback/',
        views.RecommendationFeedbackView.as_view(),
        name='recommendation_feedback',
    ),
    path(
        'members/recommendations/feedback/<int:feedback_id>/delete/',
        views.RecommendationFeedbackDeleteView.as_view(),
        name='recommendation_feedback_delete',
    ),
    path(
        'account/',
        views.AccountSettingsView.as_view(),
        name='account_settings',
    ),
    path(
        'account/export/',
        views.AccountDataExportView.as_view(),
        name='account_export',
    ),
    path(
        'account/clear-history/',
        views.AccountHistoryClearView.as_view(),
        name='account_clear_history',
    ),
    path(
        'account/delete/',
        views.AccountDeleteView.as_view(),
        name='account_delete',
    ),
    path(
        'my-results/instant/<int:result_id>/favorite/',
        views.SavedInstantResultFavoriteView.as_view(),
        name='saved_instant_result_favorite',
    ),
    path(
        'my-results/instant/<int:result_id>/delete/',
        views.SavedInstantResultDeleteView.as_view(),
        name='saved_instant_result_delete',
    ),
    path(
        'together/create/<int:result_id>/',
        views.TogetherInviteCreateView.as_view(),
        name='together_create',
    ),
    path(
        'together/<uuid:invite_id>/',
        views.TogetherInviteDetailView.as_view(),
        name='together_detail',
    ),
    path(
        'together/<uuid:invite_id>/cancel/',
        views.TogetherInviteCancelView.as_view(),
        name='together_cancel',
    ),
    path(
        'together/<uuid:invite_id>/reissue/',
        views.TogetherInviteReissueView.as_view(),
        name='together_reissue',
    ),
    path(
        'together/<uuid:invite_id>/<int:question_number>/',
        views.TogetherPlayView.as_view(),
        name='together_play',
    ),
    path(
        'together/<uuid:invite_id>/<int:question_number>/answer/',
        views.TogetherAnswerView.as_view(),
        name='together_answer',
    ),
    path('games/create/', views.GameSetCreateView.as_view(), name='create'),
    path(
        'games/create/generate/',
        views.QuestionDraftGenerateView.as_view(),
        name='generate_drafts',
    ),
    path('my-games/', views.MyGameSetListView.as_view(), name='my_creations'),
    path(
        'topics/<int:game_set_id>/',
        views.PublicGameSetDetailView.as_view(),
        name='game_set_detail',
    ),
    path(
        'topics/<int:game_set_id>/start/',
        views.GameSetStartView.as_view(),
        name='game_set_start',
    ),
    path(
        'topics/<int:game_set_id>/result/',
        views.GameSetResultView.as_view(),
        name='game_set_result',
    ),
    path(
        'topics/<int:game_set_id>/undo/',
        views.GameSetUndoLastVoteView.as_view(),
        name='game_set_undo',
    ),
    path('accounts/signup/', views.SignupView.as_view(), name='signup'),
    path(
        'accounts/login/',
        auth_views.LoginView.as_view(
            template_name='registration/login.html',
            authentication_form=StyledAuthenticationForm,
        ),
        name='login',
    ),
    path(
        'accounts/logout/',
        auth_views.LogoutView.as_view(),
        name='logout',
    ),
    path(
        'accounts/password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='registration/password_reset_form.html',
            email_template_name='registration/password_reset_email.html',
            subject_template_name='registration/password_reset_subject.txt',
            success_url=reverse_lazy('games:password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'accounts/password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='registration/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'accounts/reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='registration/password_reset_confirm.html',
            success_url=reverse_lazy('games:password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'accounts/reset/complete/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='registration/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
    path('categories/<slug:slug>/', views.CategoryListView.as_view(), name='category'),
]

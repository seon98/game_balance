from django.urls import path
from django.contrib.auth import views as auth_views

from . import views
from .forms import StyledAuthenticationForm

app_name = 'games'

urlpatterns = [
    path('', views.WelcomeView.as_view(), name='welcome'),
    path('home/', views.IndexView.as_view(), name='index'),
    path('games/', views.GameListView.as_view(), name='list'),
    path('games/random/', views.RandomGameView.as_view(), name='random'),
    path('games/<int:question_id>/', views.QuestionDetailView.as_view(), name='detail'),
    path('games/<int:question_id>/vote/', views.VoteView.as_view(), name='vote'),
    path('games/<int:question_id>/result/', views.ResultView.as_view(), name='result'),
    path('my-results/', views.ProgressView.as_view(), name='progress'),
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
    path('categories/<slug:slug>/', views.CategoryListView.as_view(), name='category'),
]

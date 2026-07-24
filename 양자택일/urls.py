from django.urls import path

from . import views

app_name = 'games'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('games/', views.GameListView.as_view(), name='list'),
    path('games/random/', views.RandomGameView.as_view(), name='random'),
    path('games/<int:question_id>/', views.QuestionDetailView.as_view(), name='detail'),
    path('games/<int:question_id>/vote/', views.VoteView.as_view(), name='vote'),
    path('games/<int:question_id>/result/', views.ResultView.as_view(), name='result'),
    path('categories/<slug:slug>/', views.CategoryListView.as_view(), name='category'),
]

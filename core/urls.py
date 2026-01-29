from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('vagas/', views.jobs, name='jobs'),
    path('vagas/<int:job_id>/', views.job_detail, name='job_detail'),
    path('vagas/<int:job_id>/import-status/', views.job_import_status, name='job_import_status'),
    path('vagas/<int:job_id>/search-status/', views.job_search_status, name='job_search_status'),
    path('vagas/<int:job_id>/preview-search/', views.preview_candidates_search, name='preview_candidates_search'),
    path('vagas/<int:job_id>/search-pool/', views.search_candidates_in_pool, name='search_candidates_in_pool'),
    path('vagas/<int:job_id>/candidatos/<int:candidate_job_id>/status/', views.update_candidate_status, name='update_candidate_status'),
    path('vagas/<int:job_id>/status/', views.update_job_status, name='update_job_status'),
    path('vagas/<int:job_id>/gerar-busca/', views.generate_boolean_search, name='generate_boolean_search'),
    path('vagas/<int:job_id>/editar/', views.job_edit, name='job_edit'),
    path('vagas/nova/', views.job_create, name='job_create'),
    path('busca/', views.search, name='search'),
    path('talentos/', views.talent_pool, name='talent_pool'),
    path('talentos/import-status/', views.talent_pool_import_status, name='talent_pool_import_status'),
    path('relatorios/', views.reports, name='reports'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('cadastro/', views.signup, name='signup'),
    path('logout/', views.logout_then_home, name='logout'),
]

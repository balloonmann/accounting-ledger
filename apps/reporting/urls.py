from django.urls import path
from . import views

urlpatterns = [
    path("reports/trial-balance/", views.trial_balance, name="trial_balance"),
    path("reports/income-expenditure/", views.income_expenditure, name="income_expenditure"),
]

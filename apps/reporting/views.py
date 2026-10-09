"""
Views for Financial Reports: Trial Balance and Income & Expenditure Statement.
"""
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone

from apps.identity.policies import is_admin

from .reports import (
    current_fiscal_year_start,
    export_income_expenditure_csv,
    export_trial_balance_csv,
    get_income_expenditure_data,
    get_trial_balance_data,
)


@login_required
def trial_balance(request):
    """
    Admin-only: Trial Balance as of selected date.
    Supports on-screen presentation and sanitized CSV export.
    """
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can view the trial balance.")

    as_of_str = request.GET.get("as_of_date", "").strip()
    as_of_date = None
    if as_of_str:
        try:
            as_of_date = datetime.strptime(as_of_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    if as_of_date is None:
        as_of_date = timezone.localdate()

    data = get_trial_balance_data(as_of_date)

    if request.GET.get("export") == "csv":
        csv_text = export_trial_balance_csv(data)
        response = HttpResponse(csv_text, content_type="text/csv; charset=utf-8")
        filename = f"trial_balance_{as_of_date.strftime('%Y%m%d')}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    return render(request, "reporting/trial_balance.html", {
        "as_of_date": as_of_date.strftime("%Y-%m-%d"),
        "report": data,
    })


@login_required
def income_expenditure(request):
    """
    Admin-only: Household Income and Expenditure statement for a date range.
    Supports on-screen presentation and sanitized CSV export.
    """
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can view the income and expenditure statement.")

    from_str = request.GET.get("from_date", "").strip()
    to_str = request.GET.get("to_date", "").strip()

    from_date = None
    to_date = None
    if from_str:
        try:
            from_date = datetime.strptime(from_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    if to_str:
        try:
            to_date = datetime.strptime(to_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    if from_date is None:
        from_date = current_fiscal_year_start()
    if to_date is None:
        to_date = timezone.localdate()

    data = get_income_expenditure_data(from_date, to_date)

    if request.GET.get("export") == "csv":
        csv_text = export_income_expenditure_csv(data)
        response = HttpResponse(csv_text, content_type="text/csv; charset=utf-8")
        filename = f"income_expenditure_{from_date.strftime('%Y%m%d')}_{to_date.strftime('%Y%m%d')}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    return render(request, "reporting/income_expenditure.html", {
        "from_date": from_date.strftime("%Y-%m-%d"),
        "to_date": to_date.strftime("%Y-%m-%d"),
        "report": data,
    })

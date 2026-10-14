from django.shortcuts import redirect
from django.template import RequestContext

from mezzanine.forms.forms import FormForForm
from mezzanine.forms.models import Form
from mezzanine.forms.services import format_value  # noqa: F401
from mezzanine.forms.services import FormSubmissionService
from mezzanine.pages.page_processors import processor_for


@processor_for(Form)
def form_processor(request, page):
    """
    Display a built form and handle submission.
    """
    form = FormForForm(
        page.form, RequestContext(request), request.POST or None, request.FILES or None
    )
    service = FormSubmissionService(request, page, form)
    if form.is_valid():
        url = page.get_absolute_url() + "?sent=1"
        if not service.is_spam(url):
            service.submit()
        return redirect(url)
    service.reject()
    return {"form": form}

from datetime import datetime
from unittest import mock, skipUnless

from django import forms
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import RequestContext
from django.test import override_settings

from mezzanine.conf import settings
from mezzanine.core.models import CONTENT_STATUS_PUBLISHED
from mezzanine.forms import fields
from mezzanine.forms.field_factories import (
    DEFAULT_FACTORY,
    FACTORIES,
    FormFieldFactory,
    get_factory,
)
from mezzanine.forms.forms import FormForForm
from mezzanine.forms.models import Field, Form, FormEntry
from mezzanine.forms.services import FormSubmissionService
from mezzanine.forms.signals import form_invalid, form_valid
from mezzanine.utils.tests import TestCase


def always_spam(request, form, url):
    return True


class TestsForm(TestCase):
    def test_forms(self):
        """
        Simple 200 status check against rendering and posting to forms
        with both optional and required fields.
        """
        for required in (True, False):
            form = Form.objects.create(title="Form", status=CONTENT_STATUS_PUBLISHED)
            for (i, (field, _)) in enumerate(fields.NAMES):
                form.fields.create(
                    label="Field %s" % i,
                    field_type=field,
                    required=required,
                    visible=True,
                )
            response = self.client.get(form.get_absolute_url())
            self.assertEqual(response.status_code, 200)
            visible_fields = form.fields.visible()
            data = {"field_%s" % f.id: "test" for f in visible_fields}
            response = self.client.post(form.get_absolute_url(), data=data)
            self.assertEqual(response.status_code, 200)

    @skipUnless(
        settings.USE_MODELTRANSLATION and len(settings.LANGUAGES) > 1,
        "modeltranslation configured for several languages required",
    )
    def test_submit_button_text(self):
        """
        Test that Form.button_text has its value displayed properly without
        being translated back to the default language.
        """
        from collections import OrderedDict

        from django.urls import reverse
        from django.utils.translation import activate, get_language
        from django.utils.translation import gettext as _
        from modeltranslation.utils import auto_populate

        default_language = get_language()
        code_list = OrderedDict(settings.LANGUAGES)
        del code_list[default_language]
        for c in code_list:
            try:
                activate(c)
            except:  # noqa
                pass
            else:
                break
            return
        with auto_populate(True):
            form = Form.objects.create(
                title="Form button_text", status=CONTENT_STATUS_PUBLISHED
            )
            form.fields.create(
                label="Field test", field_type=fields.TEXT, required=True, visible=True
            )
        submit_text = _("Submit")
        form.button_text = submit_text
        form.save()
        # Client session still uses default language
        response = self.client.get(form.get_absolute_url())
        activate(default_language)
        # Default language contains the default translation for Submit
        self.assertContains(response, _("Submit"))
        # Language used for form creation contains its own translation
        self.client.post(reverse("set_language"), data={"language": c})
        response = self.client.get(form.get_absolute_url())
        self.client.post(reverse("set_language"), data={"language": default_language})
        self.assertContains(response, submit_text)

    def test_custom_email_type(self):
        class CustomEmailField(forms.EmailField):
            pass

        fields.CLASSES[16] = CustomEmailField
        fields.NAMES += ((16, "Custom email field"),)

        form_page = Form.objects.create(title="Email form tests")
        form_page.fields.create(label="Email field test", field_type=16)

        test_email = "test@example.com"
        request = self._request_factory.post("/", {"field_1": test_email})

        form = FormForForm(
            form_page,
            RequestContext(request),
            request.POST or None,
            request.FILES or None,
        )

        self.assertTrue(form.is_valid())
        self.assertEqual(form.email_to(), test_email)


class TestsFormFieldCreation(TestCase):
    """
    Caracteriza como ``FormForForm`` cria cada campo Django a partir do
    ``field_type`` do ``mezzanine.forms.models.Field``.
    """

    def build(self, **field_kwargs):
        form_page = Form.objects.create(title="Field creation")
        field_kwargs.setdefault("label", "Field")
        field = form_page.fields.create(**field_kwargs)
        request = self._request_factory.get("/")
        form = FormForForm(form_page, RequestContext(request))
        key = "field_%s" % field.id
        return form.fields[key], form.initial.get(key)

    def test_select_gets_placeholder_choice_when_default_not_in_choices(self):
        form_field, _ = self.build(
            field_type=fields.SELECT, choices="a, b", placeholder_text="Escolha"
        )
        self.assertEqual(
            list(form_field.choices), [("", "Escolha"), ("a", "a"), ("b", "b")]
        )

    def test_select_without_placeholder_choice_when_default_in_choices(self):
        form_field, initial = self.build(
            field_type=fields.SELECT, choices="a, b", default="b"
        )
        self.assertEqual(list(form_field.choices), [("a", "a"), ("b", "b")])
        self.assertEqual(initial, "b")

    def test_radio_never_gets_placeholder_choice(self):
        form_field, _ = self.build(field_type=fields.RADIO_MULTIPLE, choices="a, b")
        self.assertEqual(list(form_field.choices), [("a", "a"), ("b", "b")])

    def test_char_fields_get_max_length(self):
        form_field, _ = self.build(field_type=fields.TEXT)
        self.assertEqual(form_field.max_length, settings.FORMS_FIELD_MAX_LENGTH)
        self.assertEqual(form_field.type, "charfield")

    def test_dob_widget_has_120_years(self):
        form_field, _ = self.build(field_type=fields.DOB)
        years = list(form_field.widget.years)
        self.assertEqual(len(years), 120)
        self.assertEqual(years[0], datetime.now().year)

    def test_checkbox_initial_is_converted_to_boolean(self):
        _, initial = self.build(field_type=fields.CHECKBOX, default="False")
        self.assertIs(initial, False)
        _, initial = self.build(field_type=fields.CHECKBOX, default="True")
        self.assertIs(initial, True)

    def test_multiple_initial_is_split_into_list(self):
        for field_type in fields.MULTIPLE:
            _, initial = self.build(
                field_type=field_type, choices="a, b, c", default="a, c"
            )
            self.assertEqual(initial, ["a", "c"])

    def test_placeholder_only_without_default(self):
        form_field, _ = self.build(field_type=fields.TEXT, placeholder_text="Nome")
        self.assertEqual(form_field.widget.attrs["placeholder"], "Nome")
        form_field, _ = self.build(
            field_type=fields.TEXT, placeholder_text="Nome", default="x"
        )
        self.assertNotIn("placeholder", form_field.widget.attrs)

    @override_settings(FORMS_USE_HTML5=True)
    def test_html5_required_except_checkbox_multiple(self):
        form_field, _ = self.build(field_type=fields.TEXT, required=True)
        self.assertEqual(form_field.widget.attrs["required"], "")
        form_field, _ = self.build(
            field_type=fields.CHECKBOX_MULTIPLE, choices="a, b", required=True
        )
        self.assertNotIn("required", form_field.widget.attrs)

    def test_no_html5_required_by_default(self):
        form_field, _ = self.build(field_type=fields.TEXT, required=True)
        self.assertNotIn("required", form_field.widget.attrs)

    def test_extra_field_type_uses_registered_class(self):
        class CustomField(forms.CharField):
            pass

        fields.CLASSES[99] = CustomField
        self.addCleanup(fields.CLASSES.pop, 99)
        form_field, _ = self.build(field_type=99)
        self.assertIsInstance(form_field, CustomField)
        self.assertEqual(form_field.type, "customfield")
        self.assertEqual(form_field.max_length, settings.FORMS_FIELD_MAX_LENGTH)


class TestsFormFieldFactories(TestCase):
    """
    Testes unitarios das fabricas de ``mezzanine.forms.field_factories``.
    """

    def test_select_factory_inserts_placeholder_first(self):
        field = Field(
            label="F", field_type=fields.SELECT, choices="a, b", placeholder_text="P"
        )
        form_field = get_factory(fields.SELECT).create(field)
        self.assertEqual(list(form_field.choices)[0], ("", "P"))

    def test_dob_factory_sets_120_years(self):
        field = Field(label="F", field_type=fields.DOB)
        form_field = get_factory(fields.DOB).create(field)
        self.assertEqual(len(form_field.widget.years), 120)

    def test_checkbox_factory_cleans_false_initial(self):
        field = Field(label="F", field_type=fields.CHECKBOX)
        factory = get_factory(fields.CHECKBOX)
        self.assertIs(factory.clean_initial(field, "False"), False)
        self.assertIs(factory.clean_initial(field, "on"), True)

    @override_settings(FORMS_USE_HTML5=True)
    def test_checkbox_multiple_factory_skips_html5_required(self):
        field = Field(
            label="F", field_type=fields.CHECKBOX_MULTIPLE, choices="a", required=True
        )
        form_field = get_factory(fields.CHECKBOX_MULTIPLE).create(field)
        self.assertNotIn("required", form_field.widget.attrs)

    def test_unknown_type_uses_default_factory(self):
        self.assertIs(get_factory(99), DEFAULT_FACTORY)
        self.assertIs(get_factory(fields.TEXT), DEFAULT_FACTORY)

    def test_custom_factory_registered_without_touching_form(self):
        class UpperFactory(FormFieldFactory):
            def clean_initial(self, field, value):
                return value.upper()

        self.addCleanup(FACTORIES.pop, fields.TEXT, None)
        FACTORIES[fields.TEXT] = UpperFactory()
        form_page = Form.objects.create(title="Custom factory")
        field = form_page.fields.create(
            label="F", field_type=fields.TEXT, default="abc"
        )
        request = self._request_factory.get("/")
        form = FormForForm(form_page, RequestContext(request))
        self.assertEqual(form.initial["field_%s" % field.id], "ABC")


class TestsFormSubmission(TestCase):
    """
    Caracteriza o processamento de uma submissao pelo page processor
    ``form_processor``: persistencia, e-mails, anexos, sinais e spam.
    """

    def setUp(self):
        super().setUp()
        self.valid = []
        self.invalid = []

        def on_valid(sender, **kwargs):
            self.valid.append(kwargs)

        def on_invalid(sender, **kwargs):
            self.invalid.append(kwargs)

        form_valid.connect(on_valid, weak=False)
        form_invalid.connect(on_invalid, weak=False)
        self.addCleanup(form_valid.disconnect, on_valid)
        self.addCleanup(form_invalid.disconnect, on_invalid)

    def create_form(self, **kwargs):
        kwargs.setdefault("title", "Contato")
        kwargs.setdefault("status", CONTENT_STATUS_PUBLISHED)
        form = Form.objects.create(**kwargs)
        email = form.fields.create(label="Email", field_type=fields.EMAIL)
        return form, "field_%s" % email.id

    def test_valid_submission_saves_entry_sends_emails_and_signal(self):
        form, email_key = self.create_form(
            send_email=True,
            email_copies="copia@example.com",
            email_subject="Assunto",
            email_from="site@example.com",
        )
        response = self.client.post(
            form.get_absolute_url(), {email_key: "alguem@example.com"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("?sent=1"))
        self.assertEqual(FormEntry.objects.count(), 1)
        entry = FormEntry.objects.get()
        self.assertEqual(entry.fields.get().value, "alguem@example.com")
        self.assertEqual(len(mail.outbox), 2)
        to_sender, copies = mail.outbox
        self.assertEqual(to_sender.to, ["alguem@example.com"])
        self.assertEqual(to_sender.subject, "Assunto")
        self.assertEqual(to_sender.from_email, "site@example.com")
        self.assertEqual(copies.to, ["copia@example.com"])
        self.assertEqual(copies.extra_headers["Reply-To"], "alguem@example.com")
        self.assertEqual(len(self.valid), 1)
        self.assertEqual(self.valid[0]["entry"], entry)
        self.assertEqual(self.invalid, [])

    def test_default_subject_and_sender(self):
        form, email_key = self.create_form(send_email=True)
        self.client.post(form.get_absolute_url(), {email_key: "alguem@example.com"})
        entry = FormEntry.objects.get()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, f"{form.title} - {entry.entry_time}")
        self.assertEqual(mail.outbox[0].from_email, settings.DEFAULT_FROM_EMAIL)

    def test_send_email_disabled_only_sends_copies(self):
        form, email_key = self.create_form(
            send_email=False, email_copies="a@example.com, b@example.com"
        )
        self.client.post(form.get_absolute_url(), {email_key: "alguem@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["a@example.com", "b@example.com"])

    def test_copies_receive_uploaded_file_as_attachment(self):
        form, email_key = self.create_form(
            send_email=False, email_copies="copia@example.com"
        )
        upload = form.fields.create(
            label="Arquivo", field_type=fields.FILE, required=False
        )
        data = {
            email_key: "alguem@example.com",
            "field_%s" % upload.id: SimpleUploadedFile("cv.txt", b"conteudo"),
        }
        with mock.patch("mezzanine.forms.forms.fs.save", return_value="cv.txt"):
            self.client.post(form.get_absolute_url(), data)
        self.assertEqual(len(mail.outbox), 1)
        name, content = mail.outbox[0].attachments[0][:2]
        # Django decodifica anexos text/* para str.
        if isinstance(content, str):
            content = content.encode()
        self.assertEqual((name, content), ("cv.txt", b"conteudo"))

    def test_invalid_submission_fires_form_invalid(self):
        form, email_key = self.create_form(send_email=True)
        response = self.client.post(form.get_absolute_url(), {email_key: "x"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FormEntry.objects.count(), 0)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(len(self.invalid), 1)
        self.assertEqual(self.valid, [])

    @override_settings(SPAM_FILTERS=("tests.test_forms.always_spam",))
    def test_spam_redirects_without_saving_or_signals(self):
        form, email_key = self.create_form(
            send_email=True, email_copies="copia@example.com"
        )
        response = self.client.post(
            form.get_absolute_url(), {email_key: "alguem@example.com"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("?sent=1"))
        self.assertEqual(FormEntry.objects.count(), 0)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(self.valid, [])
        self.assertEqual(self.invalid, [])

    def test_service_can_be_used_outside_page_processor(self):
        page, email_key = self.create_form(
            send_email=True, email_copies="copia@example.com"
        )
        request = self._request_factory.post("/api/", {email_key: "a@example.com"})
        form = FormForForm(page, RequestContext(request), request.POST)
        self.assertTrue(form.is_valid())
        service = FormSubmissionService(request, page, form)
        self.assertFalse(service.is_spam("/api/"))
        entry = service.submit()
        self.assertEqual(entry.form, page)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(self.valid[0]["entry"], entry)

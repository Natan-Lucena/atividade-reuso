"""
Facade para o processamento da submissao de um formulario do app forms.

``FormSubmissionService`` esconde verificacao de spam, coleta de anexos,
persistencia, envio de e-mails e disparo de sinais atras de tres metodos
publicos, para que qualquer adaptador (o page processor, uma view ou uma
API) possa processar uma submissao sem conhecer esses colaboradores.
"""

from mezzanine.conf import settings
from mezzanine.forms.signals import form_invalid, form_valid
from mezzanine.utils.email import send_mail_template, split_addresses
from mezzanine.utils.views import is_spam


def format_value(value):
    """
    Convert a list into a comma separated string, for displaying
    select multiple values in emails.
    """
    if isinstance(value, list):
        value = ", ".join(v.strip() for v in value)
    return value


class FormSubmissionService:
    """
    Processa a submissao de um ``FormForForm`` ja validado.
    """

    def __init__(self, request, page, form):
        self.request = request
        self.page = page
        self.form = form

    def is_spam(self, url):
        return is_spam(self.request, self.form, url)

    def submit(self):
        """
        Salva a entrada, envia as notificacoes e dispara ``form_valid``.
        """
        # Os anexos sao lidos antes do save, que consome os arquivos.
        attachments = self._collect_attachments()
        entry = self.form.save()
        self._send_notifications(entry, attachments)
        form_valid.send(sender=self.request, form=self.form, entry=entry)
        return entry

    def reject(self):
        form_invalid.send(sender=self.request, form=self.form)

    def _collect_attachments(self):
        attachments = []
        for f in self.form.files.values():
            f.seek(0)
            attachments.append((f.name, f.read()))
        return attachments

    def _subject(self, entry):
        subject = self.page.form.email_subject
        if not subject:
            subject = f"{self.page.form.title} - {entry.entry_time}"
        return subject

    def _context(self):
        fields = [
            (v.label, format_value(self.form.cleaned_data[k]))
            for (k, v) in self.form.fields.items()
        ]
        return {
            "fields": fields,
            "message": self.page.form.email_message,
            "request": self.request,
        }

    def _send_notifications(self, entry, attachments):
        subject = self._subject(entry)
        context = self._context()
        email_from = self.page.form.email_from or settings.DEFAULT_FROM_EMAIL
        email_to = self.form.email_to()
        if email_to and self.page.form.send_email:
            send_mail_template(
                subject, "email/form_response", email_from, email_to, context
            )
        headers = None
        if email_to:
            # Add the email entered as a Reply-To header
            headers = {"Reply-To": email_to}
        email_copies = split_addresses(self.page.form.email_copies)
        if email_copies:
            send_mail_template(
                subject,
                "email/form_response_copies",
                email_from,
                email_copies,
                context,
                attachments=attachments,
                headers=headers,
            )

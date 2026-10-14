"""
Factory Method para a criacao dos campos Django de ``FormForForm``.

Cada tipo de ``mezzanine.forms.models.Field`` e criado por uma fabrica.
``FormFieldFactory`` implementa o algoritmo comum e as subclasses
sobrescrevem apenas o passo que varia para o seu tipo. Tipos sem fabrica
propria, incluindo os registrados via ``FORMS_EXTRA_FIELDS``, usam a
fabrica padrao. Um projeto pode registrar a sua propria fabrica em
``FACTORIES`` sem alterar ``FormForForm``.
"""

from datetime import datetime

from mezzanine.conf import settings
from mezzanine.forms import fields
from mezzanine.utils.email import split_addresses as split_choices


class FormFieldFactory:
    """
    Cria o campo Django para um ``mezzanine.forms.models.Field``.
    """

    # Se o campo obrigatorio recebe o atributo HTML5 ``required``.
    html5_required = True

    def create(self, field):
        """
        Factory method: instancia e configura o campo Django.
        """
        field_class = fields.CLASSES[field.field_type]
        form_field = field_class(**self.get_field_args(field, field_class))
        self.configure(form_field, field)
        return form_field

    def get_field_args(self, field, field_class):
        args = {
            "label": field.label,
            "required": field.required,
            "help_text": field.help_text,
        }
        arg_names = field_class.__init__.__code__.co_varnames
        if "max_length" in arg_names:
            args["max_length"] = settings.FORMS_FIELD_MAX_LENGTH
        if "choices" in arg_names:
            args["choices"] = self.get_choices(field)
        widget = fields.WIDGETS.get(field.field_type)
        if widget is not None:
            args["widget"] = widget
        return args

    def get_choices(self, field):
        return list(field.get_choices())

    def clean_initial(self, field, value):
        """
        Converte o valor inicial (sempre uma string) para o tipo do campo.
        """
        return value

    def configure(self, form_field, field):
        # Add identifying type attr to the field for styling.
        setattr(form_field, "type", form_field.__class__.__name__.lower())
        if field.required and settings.FORMS_USE_HTML5 and self.html5_required:
            form_field.widget.attrs["required"] = ""
        if field.placeholder_text and not field.default:
            form_field.widget.attrs["placeholder"] = field.placeholder_text


class SelectFieldFactory(FormFieldFactory):
    def get_choices(self, field):
        choices = super().get_choices(field)
        if field.default not in [c[0] for c in choices]:
            choices.insert(0, ("", field.placeholder_text))
        return choices


class MultipleChoiceFactory(FormFieldFactory):
    def clean_initial(self, field, value):
        return split_choices(value)


class CheckboxMultipleFactory(MultipleChoiceFactory):
    html5_required = False


class CheckboxFactory(FormFieldFactory):
    def clean_initial(self, field, value):
        return value != "False"


class DateOfBirthFactory(FormFieldFactory):
    def configure(self, form_field, field):
        _now = datetime.now()
        form_field.widget.years = list(range(_now.year, _now.year - 120, -1))
        super().configure(form_field, field)


DEFAULT_FACTORY = FormFieldFactory()

FACTORIES = {
    fields.SELECT: SelectFieldFactory(),
    fields.CHECKBOX: CheckboxFactory(),
    fields.CHECKBOX_MULTIPLE: CheckboxMultipleFactory(),
    fields.SELECT_MULTIPLE: MultipleChoiceFactory(),
    fields.DOB: DateOfBirthFactory(),
}


def get_factory(field_type):
    """
    Retorna a fabrica do tipo de campo, ou a fabrica padrao.
    """
    return FACTORIES.get(field_type, DEFAULT_FACTORY)

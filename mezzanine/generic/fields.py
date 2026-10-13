from copy import copy

from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import AppRegistryNotReady, ImproperlyConfigured
from django.db.models import CharField, FloatField, IntegerField
from django.db.models.signals import post_delete, post_save

from mezzanine.utils.deprecation import get_related_model


class BaseGenericRelation(GenericRelation):
    """
    Extends ``GenericRelation`` to:

    - Add a consistent default value for ``object_id_field`` and
      check for a ``default_related_model`` attribute which can be
      defined on subclasses as a default for the ``to`` argument.

    - Add one or more custom fields to the model that the relation
      field is applied to, and then call a ``related_items_changed``
      method each time related items are saved or deleted, so that a
      calculated value can be stored against the custom fields since
      aggregates aren't available for GenericRelation instances.

    ``related_items_changed`` is a template method: it fixes the
    algorithm (calculate the denormalised values, apply them to the
    instance, persist the instance) and subclasses only provide the
    varying step by implementing ``calculate_values``.

    """

    # Mapping of field names to model fields that will be added.
    fields = {}

    # Persistence policy hook: when ``True`` the instance is only saved
    # if at least one of the calculated values actually changed.
    save_only_if_changed = False

    def __init__(self, *args, **kwargs):
        """
        Set up some defaults and check for a ``default_related_model``
        attribute for the ``to`` argument.
        """
        kwargs.setdefault("object_id_field", "object_pk")
        to = getattr(self, "default_related_model", None)
        # Avoid having both a positional arg and a keyword arg for
        # the parameter ``to``
        if to and not args:
            kwargs.setdefault("to", to)
        try:
            # Check if ``related_model`` has been modified by a subclass
            self.related_model
        except (AppRegistryNotReady, AttributeError):
            # if not, all is good
            super().__init__(*args, **kwargs)
        else:
            # otherwise, warn the user to stick to the new (as of 4.0)
            # ``default_related_model`` attribute
            raise ImproperlyConfigured(
                "BaseGenericRelation changed the "
                "way it handled a default ``related_model`` in mezzanine "
                "4.0. Please override ``default_related_model`` instead "
                "and do not tamper with django's ``related_model`` "
                "property anymore."
            )

    def contribute_to_class(self, cls, name):
        """
        Add each of the names and fields in the ``fields`` attribute
        to the model the relationship field is applied to, and set up
        the related item save and delete signals for calling
        ``related_items_changed``.
        """
        for field in cls._meta.many_to_many:
            if isinstance(field, self.__class__):
                e = "Multiple {} fields are not supported ({}.{}, {}.{})".format(
                    self.__class__.__name__,
                    cls.__name__,
                    cls.__name__,
                    name,
                    field.name,
                )
                raise ImproperlyConfigured(e)
        self.related_field_name = name
        super().contribute_to_class(cls, name)
        # Not applicable to abstract classes, and in fact will break.
        if not cls._meta.abstract:
            for (name_string, field) in self.fields.items():
                if "%s" in name_string:
                    name_string = name_string % name
                extant_fields = cls._meta._forward_fields_map
                if name_string in extant_fields:
                    continue
                if field.verbose_name is None:
                    field.verbose_name = self.verbose_name
                cls.add_to_class(name_string, copy(field))
            # Add a getter function to the model we can use to retrieve
            # the field/manager by name.
            getter_name = "get_%s_name" % self.__class__.__name__.lower()
            cls.add_to_class(getter_name, lambda self: name)

            sender = get_related_model(self)
            post_save.connect(self._related_items_changed, sender=sender)
            post_delete.connect(self._related_items_changed, sender=sender)

    def _related_items_changed(self, **kwargs):
        """
        Ensure that the given related item is actually for the model
        this field applies to, and pass the instance to the real
        ``related_items_changed`` handler.
        """
        for_model = kwargs["instance"].content_type.model_class()
        if for_model and issubclass(for_model, self.model):
            instance_id = kwargs["instance"].object_pk
            try:
                instance = for_model.objects.get(id=instance_id)
            except self.model.DoesNotExist:
                # Instance itself was deleted - signals are irrelevant.
                return
            if hasattr(instance, "get_content_model"):
                instance = instance.get_content_model()
            related_manager = getattr(instance, self.related_field_name)
            self.related_items_changed(instance, related_manager)

    def related_items_changed(self, instance, related_manager):
        """
        Template method called whenever the state of related items
        change, eg they're saved or deleted. The instance for this
        field and the related manager for the field are passed as
        arguments. Runs the fixed sequence of steps:

        1. ``calculate_values`` (hook implemented by subclasses);
        2. ``apply_values`` (common: store each value on the instance);
        3. save the instance, according to ``save_only_if_changed``.
        """
        values = self.calculate_values(instance, related_manager)
        changed = self.apply_values(instance, values)
        if changed or not self.save_only_if_changed:
            instance.save()

    def calculate_values(self, instance, related_manager):
        """
        Hook for subclasses: return a dict mapping each field name
        template declared in ``fields`` (eg ``"%s_count"``) to the
        value that should be stored on the instance.
        """
        raise NotImplementedError(
            "%s must implement calculate_values()" % self.__class__.__name__
        )

    def apply_values(self, instance, values):
        """
        Store each calculated value on the instance, resolving the
        field name templates against ``related_field_name``. Returns
        ``True`` if any value differs from the one currently stored.
        """
        changed = False
        for name_template, value in values.items():
            field_name = name_template % self.related_field_name
            if getattr(instance, field_name) != value:
                setattr(instance, field_name, value)
                changed = True
        return changed

    def value_from_object(self, obj):
        """
        Returns the value of this field in the given model instance.
        See: https://code.djangoproject.com/ticket/22552
        """
        return getattr(obj, self.attname).all()


class CommentsField(BaseGenericRelation):
    """
    Stores the number of comments against the
    ``COMMENTS_FIELD_NAME_count`` field when a comment is saved or
    deleted.
    """

    default_related_model = "generic.ThreadedComment"
    fields = {"%s_count": IntegerField(editable=False, default=0)}

    def calculate_values(self, instance, related_manager):
        """
        Calculates the number of comments. A custom ``count_filter``
        queryset gets checked for, allowing managers to implement
        custom count logic.
        """
        try:
            count = related_manager.count_queryset()
        except AttributeError:
            count = related_manager.count()
        return {"%s_count": count}


class KeywordsField(BaseGenericRelation):
    """
    Stores the keywords as a single string into the
    ``KEYWORDS_FIELD_NAME_string`` field for convenient access when
    searching.
    """

    default_related_model = "generic.AssignedKeyword"
    fields = {"%s_string": CharField(editable=False, blank=True, max_length=500)}
    # Only hit the database when the keywords string actually changed.
    save_only_if_changed = True

    def __init__(self, *args, **kwargs):
        """
        Mark the field as editable so that it can be specified in
        admin class fieldsets and pass validation, and also so that
        it shows up in the admin form.
        """
        super().__init__(*args, **kwargs)
        self.editable = True

    def formfield(self, **kwargs):
        """
        Provide the custom form widget for the admin, since there
        isn't a form field mapped to ``GenericRelation`` model fields.
        """
        from mezzanine.generic.forms import KeywordsWidget

        kwargs["widget"] = KeywordsWidget
        return super().formfield(**kwargs)

    def save_form_data(self, instance, data):
        """
        The ``KeywordsWidget`` field will return data as a string of
        comma separated IDs for the ``Keyword`` model - convert these
        into actual ``AssignedKeyword`` instances. Also delete
        ``Keyword`` instances if their last related ``AssignedKeyword``
        instance is being removed.
        """
        from mezzanine.generic.models import Keyword

        related_manager = getattr(instance, self.name)
        # Get a list of Keyword IDs being removed.
        old_ids = [str(a.keyword_id) for a in related_manager.all()]
        new_ids = data.split(",")
        removed_ids = set(old_ids) - set(new_ids)
        # Remove current AssignedKeyword instances.
        related_manager.all().delete()
        # Convert the data into AssignedKeyword instances.
        if data:
            data = [related_manager.create(keyword_id=i) for i in new_ids]
        # Remove keywords that are no longer assigned to anything.
        Keyword.objects.delete_unused(removed_ids)

        getattr(instance, self.name).set(data)

    def contribute_to_class(self, cls, name):
        """
        Swap out any reference to ``KeywordsField`` with the
        ``KEYWORDS_FIELD_string`` field in ``search_fields``.
        """
        super().contribute_to_class(cls, name)
        string_field_name = list(self.fields.keys())[0] % self.related_field_name
        if hasattr(cls, "search_fields") and name in cls.search_fields:
            try:
                weight = cls.search_fields[name]
            except TypeError:
                # search_fields is a sequence.
                index = cls.search_fields.index(name)
                search_fields_type = type(cls.search_fields)
                cls.search_fields = list(cls.search_fields)
                cls.search_fields[index] = string_field_name
                cls.search_fields = search_fields_type(cls.search_fields)
            else:
                del cls.search_fields[name]
                cls.search_fields[string_field_name] = weight

    def calculate_values(self, instance, related_manager):
        """
        Joins the keywords into a single string for searching.
        """
        assigned = related_manager.select_related("keyword")
        keywords = " ".join(str(a.keyword) for a in assigned)
        return {"%s_string": keywords}


class RatingField(BaseGenericRelation):
    """
    Stores the rating count and average against the
    ``RATING_FIELD_NAME_count`` and ``RATING_FIELD_NAME_average``
    fields when a rating is saved or deleted.
    """

    default_related_model = "generic.Rating"
    fields = {
        "%s_count": IntegerField(default=0, editable=False),
        "%s_sum": IntegerField(default=0, editable=False),
        "%s_average": FloatField(default=0, editable=False),
    }

    def calculate_values(self, instance, related_manager):
        """
        Calculates the rating count, sum and average.
        """
        ratings = [r.value for r in related_manager.all()]
        count = len(ratings)
        _sum = sum(ratings)
        average = _sum / count if count > 0 else 0
        return {"%s_count": count, "%s_sum": _sum, "%s_average": average}

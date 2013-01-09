from django import forms
from django.db.models import FieldDoesNotExist
from django.forms.formsets import DELETION_FIELD_NAME
from django.forms.models import (
    _get_foreign_key, ModelForm, ModelFormMetaclass, InlineForeignKeyField
)
from django.utils import six
from django.utils.text import capfirst
from django.utils.translation import ugettext_lazy as _


class RelatedModelFormOptions(object):
    def __init__(self, options=None):
        if options is None:
            return

        self.parent_model = getattr(options, 'parent_model', None)
        self.fk = getattr(options, 'fk', None)


class RelatedModelFormMetaclass(ModelFormMetaclass):
    def __new__(cls, name, bases, attrs):

        new_class = super(RelatedModelFormMetaclass, cls).__new__(
            cls, name, bases, attrs)

        new_class._related_meta = RelatedModelFormOptions(
            getattr(new_class, 'RelatedMeta', None))

        return new_class


class RelatedModelFormBase(forms.ModelForm):

    can_delete = False

    def __init__(self, data, files, instance, **kwargs):

        self.parent_instance = parent_instance = instance
        instance = None

        related_fk_name = self._related_meta.fk.related.get_accessor_name()
        if parent_instance:
            try:
                instance = getattr(parent_instance, related_fk_name)
            except self._meta.model.DoesNotExist:
                pass

        super(RelatedModelFormBase, self).__init__(data, files,
                                                   instance=instance,
                                                   **kwargs)

        self.add_fields()

    def _get_will_delete(self):
        return getattr(self, 'cleaned_data', {}).get(
            DELETION_FIELD_NAME, False)

    def _set_will_delete(self, value):
        if hasattr(self, 'cleaned_data'):
            self.cleaned_data[DELETION_FIELD_NAME] = value

    will_delete = property(_get_will_delete, _set_will_delete)

    def is_valid(self):
        if self.empty_permitted and not self.has_changed():
            return True

        if self.can_delete and self.will_delete:
            return True

        return super(RelatedModelFormBase, self).is_valid()

    def save(self, commit=True):
        # If this form is marked for deletion, just delete it and return, with
        # out even looking at the `commit` value. This is how FormSets work. A
        # bit weird, but consistency is good.
        if self.empty_permitted and not self.has_changed() and \
                not self.instance.pk:
            return None

        if self.can_delete and self.will_delete:
            if self.instance.pk:
                self.instance.delete()
            return None

        instance = super(RelatedModelFormBase, self).save(commit=False)

        fk_name = self._related_meta.fk.name

        # Set the relation if it does not already exist
        try:
            getattr(instance, fk_name)
        except AttributeError, self._related_meta.parent_model.DoesNotExist:
            setattr(instance, fk_name, self.related_instance)

        if commit:
            instance.save()
            self.save_m2m()

        return instance

    def add_fields(self):
        # This is mostly taken from the ModelFormSet `add_fields` methods, but
        # modified to work on itself instead of each form in turn.

        if self.can_delete:
            self.fields[DELETION_FIELD_NAME] = forms.BooleanField(
                label=_('Delete'), required=False)

        """Add a hidden field for the object's primary key."""
        from django.db.models import AutoField, OneToOneField, ForeignKey
        self._pk_field = pk = self._meta.model._meta.pk

        # If a pk isn't editable, then it won't be on the form, so we need to
        # add it here so we can tell which object is which when we get the
        # data back. Generally, pk.editable should be false, but for some
        # reason, auto_created pk fields and AutoField's editable attribute is
        # True, so check for that as well.
        def pk_is_not_editable(pk):
            return ((not pk.editable) or pk.auto_created
                    or isinstance(pk, AutoField) or
                    (pk.rel and pk.rel.parent_link and
                        pk_is_not_editable(pk.rel.to._meta.pk)))
        if pk_is_not_editable(pk) or pk.name not in self.fields:
            if self.is_bound:
                pk_value = self.instance.pk
            else:
                pk_value = None
            if isinstance(pk, OneToOneField) or isinstance(pk, ForeignKey):
                qs = pk.rel.to._default_manager.get_query_set()
            else:
                qs = self._meta.model._default_manager.get_query_set()
            qs = qs.using(self.instance._state.db)
            self.fields[self._pk_field.name] = forms.ModelChoiceField(
                qs, initial=pk_value, required=False, widget=forms.HiddenInput)

        fk = self._related_meta.fk

        if self._pk_field == self._related_meta.fk:
            name = self._pk_field.name
            kwargs = {'pk_field': True}
        else:
            # The foreign key field might not be on the form, so we poke at the
            # Model field to get the label, since we need that for error messages.
            name = fk.name
            kwargs = {'label': getattr(self.fields.get(name), 'label',
                                       capfirst(fk.verbose_name))}
            if fk.rel.field_name != fk.rel.to._meta.pk.name:
                kwargs['to_field'] = fk.rel.field_name

        self.fields[name] = InlineForeignKeyField(self.parent_instance,
                                                  **kwargs)

        # Add the generated field to self._meta.fields if it's defined to make
        # sure validation isn't skipped on that field.
        if self._meta.fields:
            if isinstance(self._meta.fields, tuple):
                self._meta.fields = list(self._meta.fields)
            self._meta.fields.append(fk.name)


class RelatedModelForm(six.with_metaclass(
        RelatedModelFormMetaclass, RelatedModelFormBase)):
    pass


def _make_meta(form, name, attrs):
    parents = (object,)
    if hasattr(form, name):
        parents = (getattr(form, name), object)
    return type(name, parents, attrs)


def inlinerelatedform_factory(parent_model, model, form=RelatedModelForm,
                              fields=None, exclude=None, widgets=None,
                              fk_name=None, can_delete=False,
                              empty_permitted=False):
    """
    Returns an ``InlineFormSet`` for the given kwargs.

    You must provide ``fk_name`` if ``model`` has more than one ``ForeignKey``
    to ``parent_model``.
    """

    fk = _get_foreign_key(parent_model, model, fk_name=fk_name)

    meta_attrs = {'model': model}
    if fields is not None:
        meta_attrs['fields'] = fields
    if exclude is not None:
        meta_attrs['exclude'] = exclude
    if widgets is not None:
        meta_attrs['widgets'] = widgets
    Meta = _make_meta(form, 'Meta', meta_attrs)

    RelatedMeta = _make_meta(form, 'RelatedMeta', {
        'fk': fk,
        'parent_model': parent_model,
    })

    name = '{0}{1}RelatedForm'.format(parent_model.__name__, model.__name__)
    bases = (form,)
    attrs = {
        'Meta': Meta,
        'RelatedMeta': RelatedMeta,
        'can_delete': can_delete,
        'empty_permitted': empty_permitted,
    }
    Form = type(name, bases, attrs)
    return Form

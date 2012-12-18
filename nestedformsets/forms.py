from collections import OrderedDict

from django.forms.models import ModelForm, ModelFormMetaclass

from django.forms.util import ErrorList


class NestedModelFormOptions(object):
    def __init__(self, options=None):
        if options is None:
            return

        formsets = getattr(options, 'formsets', {})

        if isinstance(formsets, dict):
            # Support dicts for backward-compatibility reasons.
            # Order will be undefined, unless it is an OrderedDict.
            formsets = formsets.items()

        elif not isinstance(formsets, (list, tuple)):
            # Otherwise, it must be a list or tuple of (name, FormsetClass)
            raise ValueError('NestedMeta.formsets must be an list or tuple of '
                             '"(name, FormSetClass)" tuples')

        self.formsets = formsets


class NestedModelFormMetaclass(ModelFormMetaclass):
    def __new__(cls, name, bases, attrs):
        new_class = super(NestedModelFormMetaclass, cls).__new__(
            cls, name, bases, attrs)

        base_options = getattr(new_class, 'NestedMeta', None)
        new_class._nested_meta = NestedModelFormOptions(base_options)

        return new_class


class NestedModelForm(ModelForm):

    __metaclass__ = NestedModelFormMetaclass

    def __init__(self, data=None, files=None, auto_id='id_%s', prefix=None,
                 initial=None, formset_extra={}, error_class=ErrorList,
                 label_suffix=':', empty_permitted=False, instance=None):

        super(NestedModelForm, self).__init__(
            data, files, auto_id, prefix, initial, error_class, label_suffix,
            empty_permitted, instance)

        formsets = self._nested_meta.formsets
        nested_prefix = (prefix + '_') if prefix is not None else ''

        def make_formset(name, NestedFormSet):
            kwargs = {
                'data': data,
                'files': files,
                'instance': self.instance,
                'prefix': nested_prefix + name,
            }
            extra = formset_extra.get(name, {})
            kwargs.update(extra)
            return NestedFormSet(**kwargs)

        self.formsets = OrderedDict((name, make_formset(name, NestedFormSet))
                                    for name, NestedFormSet in formsets)

    def is_valid(self):
        is_valid = super(NestedModelForm, self).is_valid()

        for name, formset in self.formsets.items():
            is_valid = formset.is_valid() and is_valid

        return is_valid

    def _get_formset_errors(self):
        if self._formset_errors is None:
            self.full_clean()
        return self._formset_errors
    formset_errors = property(_get_formset_errors)

    def full_clean(self):
        super(NestedModelForm, self).full_clean()

        self._formset_errors = {}
        for name, formset in self.formsets.items():
            if any(formset.errors):
                self._formset_errors[name] = formset.errors

    def save(self, commit=True):
        instance = super(NestedModelForm, self).save(commit)

        # The formset forms copy the instance when they are created, so they do
        # not know that this instance has just gotten a nice shiny new primary
        # key (if this is a create form, not an edit form). As such, we need to
        # loop through and tell all the related instances about our updated top
        # level instance
        formset_instances = {}
        for name, formset in self.formsets.items():
            instances = formset_instances[name] = []
            fk_name = formset.fk.name
            for form in formset:
                if form.has_changed():
                    if form not in formset.deleted_forms:
                        form.cleaned_data[fk_name] = instance
            formset.save(commit)

        if not commit:
            # if you pass `commit=False`, you have to save the formset
            # instances yourself. This helper should help.
            # Simply call `form.save_formsets()`
            # after you call `instance.save()`
            def save_formsets():
                for name, formset in self.formsets.items():
                    fk_name = formset.fk.name
                    for form in formset:
                        if form.has_changed():
                            if form not in formset.deleted_forms:
                                form.cleaned_data[fk_name] = instance
                                form.save()
            self.save_formsets = save_formsets

        self.formset_instances = formset_instances

        return instance

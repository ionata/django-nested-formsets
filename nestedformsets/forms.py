try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

from itertools import chain

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
                             '"(name, FormSet)" tuples')
        self.formsets = formsets

        related_forms = getattr(options, 'related_forms', ())
        if not isinstance(related_forms, (list, tuple)):
            # Otherwise, it must be a list or tuple of (name, FormsetClass)
            raise ValueError('NestedMeta.related_forms must be an list or '
                             'tuple of "(name, RelatedForm)" tuples')
        self.related_forms = related_forms


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
                 initial=None, formset_extra={}, related_form_extra={},
                 error_class=ErrorList,
                 label_suffix=':', empty_permitted=False, instance=None):

        super(NestedModelForm, self).__init__(
            data, files, auto_id, prefix, initial, error_class, label_suffix,
            empty_permitted, instance)

        # `self.data != data` after running __init__, so we must pass it in
        self.formsets = self._init_formsets(data, files, formset_extra)
        self.related_forms = self._init_related_forms(data, files,
                                                      related_form_extra)

    @property
    def subforms(self):
        return OrderedDict(chain(self.formsets.iteritems(),
                                 self.related_forms.iteritems()))

    def _init_formsets(self, data, files, extra):
        formsets = self._nested_meta.formsets
        prefix = (self.prefix + '_') if self.prefix is not None else ''

        def make_formset(name, FormSet):
            kwargs = {
                'data': data,
                'files': files,
                'instance': self.instance,
                'prefix': prefix + name,
            }
            kwargs.update(extra.get(name, {}))
            return (name, FormSet(**kwargs))

        return OrderedDict(make_formset(name, FormSet)
                           for name, FormSet in formsets)

    def _init_related_forms(self, data, files, extra):
        related_forms = self._nested_meta.related_forms
        prefix = (self.prefix + '_') if self.prefix is not None else ''

        def make_related_form(name, RelatedForm):
            kwargs = {
                'data': data,
                'files': files,
                'instance': self.instance,
                'prefix': prefix + name,
            }
            kwargs.update(extra.get(name, {}))
            return (name, RelatedForm(**kwargs))

        return OrderedDict(make_related_form(name, RelatedForm)
                           for name, RelatedForm in related_forms)

    def is_valid(self):
        is_valid = super(NestedModelForm, self).is_valid()

        for name, subform in self.subforms.items():
            is_valid = subform.is_valid() and is_valid

        return is_valid

    def _get_formset_errors(self):
        if self._formset_errors is None:
            self.full_clean()
        return self._formset_errors
    formset_errors = property(_get_formset_errors)

    def _get_related_form_errors(self):
        if self._related_form_errors is None:
            self.full_clean()
        return self._related_form_errors
    related_form_errors = property(_get_related_form_errors)

    def full_clean(self):
        super(NestedModelForm, self).full_clean()

        self._formset_errors = {}
        for name, formset in self.formsets.items():
            if any(formset.errors):
                self._formset_errors[name] = formset.errors

        self._related_form_errors = {}
        for name, related_form in self.related_forms.items():
            if any(related_form.errors):
                self._related_form_errors[name] = related_form.errors

        if self.is_bound:
            self.post_subform_clean()

    def post_subform_clean(self):
        """ A hook for subclasses that wish to do some extra `clean()` work,
            but after the subforms have all been `clean()`ed as well.
        """
        pass

    def save(self, commit=True):

        instance = super(NestedModelForm, self).save(commit)

        # The formset forms copy the instance when they are created, so they do
        # not know that this instance has just gotten a nice shiny new primary
        # key (if this is a create form, not an edit form). As such, we need to
        # loop through and tell all the related instances about our updated top
        # level instance
        formset_instances = {}
        for name, formset in self.formsets.items():
            fk_name = formset.fk.name
            for form in formset:
                if not form.empty_permitted or form.has_changed():
                    if not (formset.can_delete and
                            form in formset.deleted_forms):
                        form.cleaned_data[fk_name] = instance

            instances = formset.save(commit)
            formset_instances[name] = instances

        related_instances = {}
        for name, form in self.related_forms.items():
            fk_name = form._related_meta.fk.name
            if not form.empty_permitted or form.has_changed():
                if not (form.can_delete and form.will_delete):
                    form.cleaned_data[fk_name] = instance
            related_instance = form.save(commit)
            related_instances[name] = related_instance

        if not commit:
            # if you pass `commit=False`, you have to save the formset
            # instances yourself. This helper should help.
            # Simply call `form.save_subforms()`
            # after you call `instance.save()`
            def save_formsets():
                for name, instances in formset_instances.items():
                    for subinstance in instances:
                        subinstance.save()

            def save_related_forms():
                for name, related_instance in related_instances.items():
                    related_instance.save()

            def save_subforms():
                save_formsets()
                save_related_forms()

            self.save_formsets = save_formsets
            self.save_related_forms = save_related_forms
            self.save_subforms = save_subforms

            # Just like normal forms, if you use commit=False you must call
            # `form.save_m2m()` when you have saved the form and all its
            # subforms.
            def save_m2m():
                old_save_m2m()
                for formset in self.formsets.values():
                    formset.save_m2m()
                for related_form in self.related_forms.values():
                    related_form.save_m2m()
            old_save_m2m = self.save_m2m
            self.save_m2m = save_m2m

        self.formset_instances = formset_instances

        return instance

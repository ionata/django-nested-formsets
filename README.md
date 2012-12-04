django-nested-formsets
======================

Simple nested formsets for Django

Installing
----------

    pip install django-nested-formsets

Using
-----

    # in forms.py
    from nestedformsets.forms import NestedModelForm
    from .models import Article, Photo
    
    PhotoFormset = inlineformset_factory(Article, Photo,
        fields=('photo', 'caption'))
    
    class ArticleForm(NestedModelForm):
        class Meta:
            model = Article
            
        class NestedMeta:
            formsets = {
                'photos': PhotoFormset,
            }

And to render it

    # in a template
    
    {{ article_form }}
    
    {% for name, subformset in article_form.formsets %}
        {% for subform in subformset %}
            {{ subform }}
        {% endfor %}
    {% endfor %}

from pyramid.view import view_config, notfound_view_config
from pyramid.response import Response
from pyramid.httpexceptions import HTTPNotFound, HTTPFound
from deform import Form, ValidationFailure, ZPTRendererFactory
from deform.form import Button
import webhelpers.paginate as paginate
from sqlalchemy import desc, or_, types
from sqlalchemy.orm.exc import NoResultFound
from geoalchemy2.elements import WKBElement
from translationstring import TranslationStringFactory
import uuid

from .models import DBSession
from .schema import forms
from .ext import deform_ext

_ = TranslationStringFactory('c2cgeoform')


def _get_schema(request):
    schema_name = request.matchdict['schema']

    if _is_favicon_request(schema_name):
        # send a 404 for favicon requests that were mapped to the route
        raise HTTPNotFound()
    elif schema_name in forms:
        return forms.get(schema_name)
    else:
        raise HTTPNotFound('invalid schema \'' + schema_name + '\'')


@notfound_view_config(append_slash=True)
def notfound(request):
    """ Automatically append a slash if no route can be found for a
        request and try again.
        This allows to make requests with ".../fouille/form/" and also
        ".../fouille/form".
    """
    return HTTPNotFound()


@view_config(route_name='form', renderer='templates/site/form.pt')
def form(request):
    geo_form_schema = _get_schema(request)
    session = request.session

    renderer = _get_renderer(geo_form_schema.templates_user)
    form_action = request.route_url('form', schema=geo_form_schema.name)
    submit_button = Button(name='formsubmit', title=_('Submit'))
    form = Form(
        geo_form_schema.schema_user, buttons=(submit_button,),
        renderer=renderer, action=form_action)
    _populate_widgets(form.schema, DBSession)

    submission_id = request.params.get('__submission_id__')
    if len(request.POST) > 0 or submission_id is not None:
        store_form = request.params.get('__store_form__')

        if submission_id is not None and submission_id in session:
            # restoring the form from the session when going back from the
            # confirmation page, or when submitting on the confirmation page
            form_data = session[submission_id]
            custom_data = None
            only_validate = '0' if store_form == '1' else '1'
        else:
            form_data = request.POST.items()
            custom_data = request.POST.get('__custom_data__')
            only_validate = request.POST.get('__only_validate__')

        try:
            obj_dict = form.validate(form_data)
        except ValidationFailure, e:
            # FIXME see https://github.com/Pylons/deform/pull/243
            rendered = e.field.widget.serialize(
                e.field, e.cstruct, custom_data=custom_data, request=request)
        else:
            if only_validate == '1':
                # even if the validation was successful, do not save the entity
                rendered = form.render(obj_dict, custom_data=custom_data,
                                       request=request)
            else:
                # the form data is valid, ready to be stored in the database
                if store_form != '1':
                    # but first show a confirmation page and store the form
                    # data in a session, so that it can be restored
                    submission_id = str(uuid.uuid4())
                    session[submission_id] = form_data
                    session.save()
                    back_link = request.route_url(
                        'form', schema=geo_form_schema.name,
                        _query={'__submission_id__': submission_id})
                    rendered = form.render(
                        obj_dict, readonly=True,
                        custom_data=custom_data, submission_id=submission_id,
                        back_link=back_link)
                else:
                    obj = geo_form_schema.schema_user.objectify(obj_dict)
                    hash = str(uuid.uuid4())
                    setattr(obj, geo_form_schema.hash_column_name, hash)
                    DBSession.add(obj)
                    DBSession.flush()

                    url = request.route_url(
                        'view_user',
                        schema=geo_form_schema.name,
                        hash=hash)

                    return HTTPFound(url)
    else:
        rendered = form.render(custom_data=None, request=request)

    return {'form': rendered,
            'deform_dependencies': form.get_widget_resources()}


@view_config(route_name='view_user', renderer='templates/site/view_user.pt')
def view_user(request):
    if 'hash' not in request.matchdict or not request.matchdict['hash']:
        return {'form': None}

    hash = request.matchdict['hash']
    geo_form_schema = _get_schema(request)
    renderer = _get_renderer(geo_form_schema.templates_user)
    form = Form(geo_form_schema.schema_user, renderer=renderer)

    hash_field = getattr(
        geo_form_schema.model, geo_form_schema.hash_column_name)
    try:
        obj = DBSession \
            .query(geo_form_schema.model) \
            .filter(hash_field == hash) \
            .one()
    except NoResultFound:
        return {'form': None}

    rendered = form.render(geo_form_schema.schema_user.dictify(obj),
                           readonly=True, request=request)
    return {
        'form': rendered,
        'schema': geo_form_schema,
        'deform_dependencies': form.get_widget_resources()}


@view_config(route_name='list', renderer='templates/site/list.pt')
def list(request):
    geo_form_schema = _get_schema(request)
    entities = DBSession.query(geo_form_schema.model).all()
    return {'entities': entities, 'schema': geo_form_schema}


@view_config(route_name='grid', renderer='json', request_method='POST')
def grid(request):
    """API method which serves the JSON data for the Bootgrid table
    in the admin view.
    """
    geo_form_schema = _get_schema(request)

    current_page = int(request.POST.get('current'))
    row_count = int(request.POST.get('rowCount'))
    search_phrase = request.POST.get('searchPhrase', '').strip()
    sort = _get_sort_param(request.POST)

    query = _get_query(geo_form_schema, sort, search_phrase)
    page = paginate.Page(query, page=current_page, items_per_page=row_count)

    return {
        "current": page.page,
        "rowCount": page.items_per_page,
        "rows": _get_grid_rows(page.items, geo_form_schema),
        "total": page.item_count
    }


def _get_sort_param(params):
    for key in params:
        # Bootgrid sends the sort field as "sort[first_name]: asc"
        if key.startswith('sort'):
            field = key.replace('sort[', '').replace(']', '')
            sort_order = 'asc' if params[key] == 'asc' else 'desc'
            return (field, sort_order)
    return None


def _get_query(geo_form_schema, sort, search_phrase):
    query = DBSession.query(geo_form_schema.model)

    # order by
    if sort is not None and hasattr(geo_form_schema.model, sort[0]):
        sort_field = getattr(geo_form_schema.model, sort[0])
        if sort[1] == 'desc':
            sort_field = desc(sort_field)
        query = query.order_by(sort_field)

    # search
    if search_phrase != '':
        search_expr = '%' + '%'.join(search_phrase.split()) + '%'

        # create `ilike` filters for every list text field
        filters = []
        for field in geo_form_schema.list_fields:
            column = getattr(geo_form_schema.model, field)
            # NOTE only text fields are searched
            if isinstance(column.type, types.String):
                like = getattr(column, 'ilike')
                filters.append(like(search_expr))

        # then join the filters into one `or` condition
        if len(filters) > 0:
            filter_expr = filters.pop()
            filter_expr = reduce(
                lambda filter_expr, filter: or_(filter_expr, filter),
                filters,
                filter_expr)
            query = query.filter(filter_expr)

    return query


def _get_grid_rows(entities, schema):
    """Creates plain objects for the given entities containing
    only those properties flagged with `admin_list`.
    """
    rows = []

    for entity in entities:
        obj = {}
        for field in schema.list_fields:
            value = getattr(entity, field)
            if value is None:
                value = ''
            else:
                if isinstance(value, WKBElement):
                    value = 'Geometry'
                else:
                    value = str(value)
            obj[field] = value
        # set the entity id on a special property
        obj['_id_'] = str(getattr(entity, schema.id_field))
        rows.append(obj)

    return rows


@view_config(route_name='edit', renderer='templates/site/edit.pt')
def edit(request):
    geo_form_schema = _get_schema(request)

    renderer = _get_renderer(geo_form_schema.templates_admin)
    form = Form(
        geo_form_schema.schema_admin, buttons=('submit',), renderer=renderer)
    _populate_widgets(form.schema, DBSession)

    if 'submit' in request.POST:
        form_data = request.POST.items()

        try:
            obj_dict = form.validate(form_data)
        except ValidationFailure, e:
            rendered = e.render()
        else:
            obj = geo_form_schema.schema_admin.objectify(obj_dict)
            obj = DBSession.merge(obj)
            DBSession.flush()

            # FIXME create a fresh form, otherwise the IDs of objects in
            # relationships will not be rendered
            # see https://github.com/Pylons/deform/issues/236
            form = Form(
                geo_form_schema.schema_admin, buttons=('submit',),
                renderer=renderer)

            rendered = form.render(geo_form_schema.schema_admin.dictify(obj),
                                   request=request)
    else:
        id = request.matchdict['id']
        obj = DBSession.query(geo_form_schema.model).get(id)
        rendered = form.render(geo_form_schema.schema_admin.dictify(obj),
                               request=request)

    return {
        'form': rendered,
        'schema': geo_form_schema,
        'deform_dependencies': form.get_widget_resources()}


@view_config(route_name='view_admin', renderer='templates/site/view_admin.pt')
def view_admin(request):
    id_ = request.matchdict['id']
    geo_form_schema = _get_schema(request)
    renderer = _get_renderer(geo_form_schema.templates_admin)
    form = Form(geo_form_schema.schema_admin, buttons=('submit',),
                renderer=renderer)
    obj = DBSession.query(geo_form_schema.model).get(id_)
    rendered = form.render(geo_form_schema.schema_admin.dictify(obj),
                           readonly=True, request=request)
    return {
        'form': rendered,
        'schema': geo_form_schema,
        'deform_dependencies': form.get_widget_resources()}


@view_config(route_name='locale')
def set_locale_cookie(request):
    """ View to change the preferred language.
    """
    if request.GET['language']:
        language = request.GET['language']
        response = Response()
        response.set_cookie('_LOCALE_',
                            value=language,
                            max_age=31536000)  # max_age = year
    return HTTPFound(location=request.environ['HTTP_REFERER'],
                     headers=response.headers)


def _populate_widgets(node, session):
    """ Populate ``deform_ext.RelationSelectMixin`` widgets.
    """
    if isinstance(node.widget, deform_ext.RelationSelectMixin):
        node.widget.populate(session)

    for child in node:
        _populate_widgets(child, session)


def _get_renderer(search_paths):
    if search_paths is None:
        return None
    else:
        from c2cgeoform import translator
        return ZPTRendererFactory(search_paths, translator=translator)


def _is_favicon_request(text):
    return text in [
        'favicon.ico',
        'apple-touch-icon-precomposed.png',
        'apple-touch-icon.png']

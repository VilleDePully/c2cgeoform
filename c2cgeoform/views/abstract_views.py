import logging
from deform import Form, ValidationFailure  # , ZPTRendererFactory
from deform.form import Button
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape
from pyramid.httpexceptions import HTTPNotFound
from pyramid.httpexceptions import HTTPFound
from pyramid.response import Response
from sqlalchemy import desc, or_, types
from sqlalchemy.exc import DBAPIError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm.properties import ColumnProperty, RelationshipProperty
from translationstring import TranslationString
from geojson import FeatureCollection, Feature
from c2cgeoform import _, default_map_settings

logger = logging.getLogger(__name__)

db_err_msg = """\
Pyramid is having a problem using your SQL database.  The problem
might be caused by one of the following things:

1.  You may need to run the "initialize_c2cgeoportal_admin_db" script
    to initialize your database tables.  Check your virtual
    environment's "bin" directory for this script and try to run it.

2.  Your database server may not be running.  Check that the
    database server referred to by the "sqlalchemy.url" setting in
    your "development.ini" file is running.

After you fix the problem, please restart the Pyramid application to
try it again.
"""


def model_attr_info(attr, *keys, default=None):
    if attr is None:
        return default
    value = attr.info
    for key in keys:
        if key not in value:
            return default
        value = value[key]
    return value


class ListField():
    def __init__(self,
                 model=None,
                 attr=None,
                 key=None,
                 label=None,
                 renderer=None,
                 sort_column=None,
                 filter_column=None,
                 visible=True):
        self._attr = getattr(model, attr) if model else attr
        self._key = key or self._attr.key
        self._label = (label or
                       model_attr_info(self._attr,
                                       'colanderalchemy',
                                       'title') or
                       self._key)
        self._renderer = renderer or self._prop_renderer
        is_column = isinstance(self._attr.property, ColumnProperty)
        self._sort_column = sort_column or (self._attr if is_column else None)
        self._filter_column = filter_column if filter_column is not None \
            else self._attr if is_column \
            else None
        self._visible = visible

    def _prop_renderer(self, entity):
        value = None
        if self._attr is not None:
            value = getattr(entity, self._attr.key)
        if value is None:
            value = ''
        else:
            if isinstance(value, WKBElement):
                value = 'Geometry'
            else:
                value = str(value)
        return value

    def id(self):
        return self._key

    def label(self):
        return self._label

    def value(self, entity):
        return self._renderer(entity)

    def sortable(self):
        return self._sort_column is not None

    def filtrable(self):
        return self._filter_column is not None and \
            isinstance(self._filter_column.type, types.String)

    def sort_column(self):
        return self._sort_column

    def filter_expression(self, term):
        return self._filter_column.ilike(term)

    def visible(self):
        return self._visible


class ItemAction():

    def __init__(self,
                 name,
                 url,
                 method=False,
                 label=None,
                 css_class='',
                 icon=None,
                 confirmation="",
                 ):
        self._name = name
        self._url = url
        self._method = method
        self._label = label or self._name
        self._css_class = css_class
        self._icon = icon
        self._confirmation = confirmation

    def name(self):
        return self._name

    def url(self):
        return self._url

    def method(self):
        return self._method

    def label(self):
        return self._label

    def css_class(self):
        return self._css_class

    def icon(self):
        return self._icon

    def confirmation(self):
        return self._confirmation

    def to_dict(self, request):
        return {
            'name': self._name,
            'url': self._url,
            'method': self._method,
            'label': request.localizer.translate(self._label),
            'css_class': self._css_class,
            'icon': self._icon,
            'confirmation': self._confirmation
        }


class UserMessage:
    def __init__(self, text, css_class="alert-success"):
        self._text = text
        self._css_class = css_class

    def text(self):
        return self._text

    def css_class(self):
        return self._css_class

    def __str__(self):
        # For compatibility with old templates
        return self._text


class AbstractViews():

    _model = None  # sqlalchemy model
    _list_fields = []  # Fields in list
    _list_ordered_fields = []  # Fields in list used for default orderby
    _id_field = None  # Primary key
    _geometry_field = None  # Geometry field
    _base_schema = None  # base colander schema

    MSG_COL = {
        'submit_ok': UserMessage(_('Your submission has been taken into account.'), "alert-success"),
        'copy_ok': UserMessage(_('Please check that the copy fits before submitting.'), "alert-info"),
    }

    def __init__(self, request):
        self._request = request
        self._schema = None
        self._appstruct = None
        self._obj = None

    def index(self):
        return {
            'grid_actions': self._grid_actions(),
            'list_fields': self._list_fields,
        }

    def grid(self):
        """
        API method which serves the JSON data for the Bootgrid table in the admin view.
        """
        try:
            params = self._request.params
            offset = int(params.get('offset', 0) if params.get('offset') != 'NaN' else 0)
            limit = int(params.get('limit', -1) if params.get('limit') != 'NaN' else -1)
            search = params.get('search', '').strip()
            sort = params.get('sort', '')
            order = params.get('order', '')

            query = self._base_query()
            query = self._filter_query(query, search)
            query = self._sort_query(query, sort, order)

            return {
                "rows": self._grid_rows(query, offset, limit),
                "total": query.count()
            }
        except DBAPIError as e:
            logger.error(str(e), exc_info=True)
            return Response(db_err_msg, content_type='text/plain', status=500)

    def map(self, map_settings={}):
        map_options = {
            **default_map_settings,
            **{
                'url': self._request.route_url(
                    'c2cgeoform_geojson',
                    _query={
                        'srid': map_settings.get('srid', default_map_settings['srid']),
                    },
                ),
            },
            **map_settings
        }
        return {
            "map_options": {
                key: (
                    self._request.translate(value)
                    if isinstance(value, TranslationString)
                    else value
                )
                for key, value in map_options.items()
            }
        }

    def geojson(self):
        srid = int(self._request.params.get("srid", 3857))

        query = self._base_query().add_column(
            getattr(self._model, self._geometry_field).
            ST_Transform(srid).
            label('_geometry')
        )

        features = list()
        for entity, geometry in query:
            features.append(Feature(
                id=getattr(entity, self._id_field),
                geometry=to_shape(geometry) if geometry is not None else None,
                properties={
                    f.id(): f.value(entity)
                    for f in self._list_fields
                }
            ))
        return FeatureCollection(features)

    def _base_query(self):
        return self._request.dbsession.query(self._model)

    def _filter_query(self, query, search_phrase):
        if search_phrase != '':
            search_expr = '%' + '%'.join(search_phrase.split()) + '%'

            # create `ilike` filters for every list text field
            filters = []
            for field in self._list_fields:
                if field.filtrable():
                    filters.append(field.filter_expression(search_expr))

            # then join the filters into one `or` condition
            if len(filters) > 0:
                query = query.filter(or_(*filters))

        return query

    def _sort_query(self, query, sort, order):
        for field in self._list_fields:
            if field.id() == sort:
                if order == 'desc':
                    query = query.order_by(desc(field.sort_column()))
                else:
                    query = query.order_by(field.sort_column())
        # default order by
        for order_field in self._list_ordered_fields:
            query = query.order_by(order_field)
        return query

    def _grid_rows(self, query, offset, limit):
        # Sort on primary key as subqueryload with limit need deterministic order
        for pkey_column in inspect(self._model).primary_key:
            query = query.order_by(pkey_column)

        if limit != -1:
            query = query.limit(limit) \
                .offset(offset)
        rows = []

        for entity in query:
            row = {
                f.id(): f.value(entity) for f in (
                    self._list_fields + [ListField(self._model, self._id_field, key='_id_')]
                )
            }
            row['actions'] = self._grid_item_actions(entity)
            rows.append(row)
        return rows

    def _form(self, schema=None, **kwargs):
        self._schema = (schema or self._base_schema).bind(
            request=self._request,
            dbsession=self._request.dbsession)

        form = Form(
            self._schema,
            buttons=[Button(name='formsubmit', title=_('Submit'))],
            **kwargs
        )

        return form

    def _populate_widgets(self, node):
        """ Populate ``deform_ext.RelationSelectMixin`` widgets.
        """
        if hasattr(node.widget, 'populate'):
            node.widget.populate(self._request.dbsession, self._request)

        for child in node:
            self._populate_widgets(child)

    def _is_new(self):
        return self._request.matchdict.get('id') == "new"

    def _get_object(self):
        if self._is_new():
            return self._model()
        pk = self._request.matchdict.get('id')
        obj = self._request.dbsession.query(self._model). \
            filter(getattr(self._model, self._id_field) == pk). \
            one_or_none()
        if obj is None:
            raise HTTPNotFound()
        return obj

    def _model_config(self):
        return getattr(inspect(self._model).class_, '__c2cgeoform_config__', {})

    def _grid_actions(self):
        return [
            ItemAction(
                name='new',
                label=_('New'),
                css_class='btn btn-primary btn-new',
                url=self._request.route_url('c2cgeoform_item', id='new')
            )
        ]

    def _grid_item_actions(self, item):
        actions = self._item_actions(item)
        actions.insert(0, ItemAction(
            name='edit',
            label=_('Edit'),
            icon='glyphicon glyphicon-pencil',
            url=self._request.route_url(
                'c2cgeoform_item',
                id=getattr(item, self._id_field))))
        return {
            'dropdown': [action.to_dict(self._request) for action in actions],
            'dblclick': self._request.route_url(
                'c2cgeoform_item',
                id=getattr(item, self._id_field))}

    def _item_actions(self, item, readonly=False):
        actions = []

        if inspect(item).persistent and self._model_config().get('duplicate', False):
            actions.append(ItemAction(
                name='duplicate',
                label=_('Duplicate'),
                icon='glyphicon glyphicon-duplicate',
                url=self._request.route_url(
                    'c2cgeoform_item_duplicate',
                    id=getattr(item, self._id_field))))

        if inspect(item).persistent and not readonly:
            actions.append(ItemAction(
                name='delete',
                label=_('Delete'),
                icon='glyphicon glyphicon-remove',
                url=self._request.route_url(
                    'c2cgeoform_item',
                    id=getattr(item, self._id_field)),
                method='DELETE',
                confirmation=_('Are your sure you want to delete this record ?')))

        return actions

    def edit(self, schema=None, readonly=False):
        obj = self._get_object()
        form = self._form(schema=schema,
                          readonly=readonly)
        self._populate_widgets(form.schema)
        dict_ = form.schema.dictify(obj)
        if self._is_new():
            dict_.update(self._request.GET)
        kwargs = {
            "request": self._request,
            "actions": self._item_actions(obj, readonly=readonly),
            "readonly": readonly,
            "obj": obj,
        }
        if (
            'msg_col' in self._request.params.keys() and
            self._request.params['msg_col'] in self.MSG_COL.keys()
        ):
            msg = self.MSG_COL[self._request.params['msg_col']]
            if isinstance(msg, str):
                # For compatibility with old views
                msg = UserMessage(msg, "alert-success")
            kwargs.update({'msg_col': [msg]})
        return {
            'title': form.title,
            'form': form,
            'form_render_args': (dict_,),
            'form_render_kwargs': kwargs,
            'deform_dependencies': form.get_widget_resources()
        }

    def copy_members_if_duplicates(self, source, excludes=None):
        dest = source.__class__()
        insp = inspect(source.__class__)

        for prop in insp.attrs:
            if isinstance(prop, ColumnProperty):
                is_primary_key = prop.columns[0].primary_key
                to_duplicate = model_attr_info(prop.columns[0], 'c2cgeoform', 'duplicate', default=True)
                to_exclude = excludes and prop.columns[0].key in excludes
                if not is_primary_key and to_duplicate and not to_exclude:
                    setattr(dest, prop.key, getattr(source, prop.key))
            if isinstance(prop, RelationshipProperty):
                if model_attr_info(prop, 'c2cgeoform', 'duplicate', default=True):
                    if prop.cascade.delete:
                        if not prop.uselist:
                            duplicate = self.copy_members_if_duplicates(getattr(source, prop.key))
                        else:
                            duplicate = [self.copy_members_if_duplicates(m)
                                         for m in getattr(source, prop.key)]
                    else:
                        duplicate = getattr(source, prop.key)
                    setattr(dest, prop.key, duplicate)
        return dest

    def copy(self, src, excludes=None):
        # excludes only apply at first level
        form = self._form(action=self._request.route_url('c2cgeoform_item', id='new'))
        with self._request.dbsession.no_autoflush:
            dest = self.copy_members_if_duplicates(src, excludes)
            dict_ = form.schema.dictify(dest)
            if self._is_new():
                dict_.update(self._request.GET)
            if dest in self._request.dbsession:
                self._request.dbsession.expunge(dest)
                self._request.dbsession.expire_all()

        self._populate_widgets(form.schema)
        kwargs = {
            "request": self._request,
            "actions": self._item_actions(dest),
            "msg_col": [self.MSG_COL['copy_ok']],
        }

        return {
            'title': form.title,
            'form': form,
            'form_render_args': (dict_,),
            'form_render_kwargs': kwargs,
            'deform_dependencies': form.get_widget_resources()
        }

    def duplicate(self):
        src = self._get_object()
        return self.copy(src)

    def save(self):
        obj = self._get_object()
        try:
            form = self._form()
            self._populate_widgets(form.schema)
            form_data = self._request.POST.items()
            self._appstruct = form.validate(form_data)
            with self._request.dbsession.no_autoflush:
                obj = form.schema.objectify(self._appstruct, obj)
            self._obj = self._request.dbsession.merge(obj)
            self._request.dbsession.flush()
            return HTTPFound(
                self._request.route_url(
                    'c2cgeoform_item',
                    action='edit',
                    id=self._obj.__getattribute__(self._id_field),
                    _query=[('msg_col', 'submit_ok')]))
        except ValidationFailure as e:
            self._populate_widgets(form.schema)
            kwargs = {
                "request": self._request,
                "actions": self._item_actions(obj),
                "obj": obj
            }
            return {
                'title': form.title,
                'form': e,
                'form_render_args': tuple(),
                'form_render_kwargs': kwargs,
                'deform_dependencies': form.get_widget_resources()
            }

    def delete(self):
        obj = self._get_object()
        self._request.dbsession.delete(obj)
        self._request.dbsession.flush()
        return {
            'success': True,
            'redirect': self._request.route_url('c2cgeoform_index')
        }

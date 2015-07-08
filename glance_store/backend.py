# Copyright 2010-2011 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging

from oslo_config import cfg
from stevedore import driver
from stevedore import extension

from glance_store import capabilities
from glance_store.common import utils
from glance_store import exceptions
from glance_store import i18n
from glance_store import location


CONF = cfg.CONF
LOG = logging.getLogger(__name__)

_ = i18n._

_STORE_OPTS = [
    cfg.ListOpt('stores', default=['file', 'http'],
                help=_('List of stores enabled')),
    cfg.StrOpt('default_store', default='file',
               help=_("Default scheme to use to store image data. The "
                      "scheme must be registered by one of the stores "
                      "defined by the 'stores' config option.")),
    cfg.IntOpt('store_capabilities_update_min_interval', default=0,
               help=_("Minimum interval seconds to execute updating "
                      "dynamic storage capabilities based on backend "
                      "status then. It's not a periodic routine, the "
                      "update logic will be executed only when interval "
                      "seconds elapsed and an operation of store has "
                      "triggered. The feature will be enabled only when "
                      "the option value greater then zero."))
]

_STORE_CFG_GROUP = 'glance_store'


def _list_opts():
    driver_opts = []
    mgr = extension.ExtensionManager('glance_store.drivers')
    # NOTE(zhiyan): Handle available drivers entry_points provided
    drivers = [ext.name for ext in mgr]
    handled_drivers = []  # Used to handle backwards-compatible entries
    for store_entry in drivers:
        driver_cls = _load_store(None, store_entry, False)
        if driver_cls and driver_cls not in handled_drivers:
            if getattr(driver_cls, 'OPTIONS', None) is not None:
                driver_opts += driver_cls.OPTIONS
            handled_drivers.append(driver_cls)

    # NOTE(zhiyan): This separated approach could list
    # store options before all driver ones, which easier
    # to read and configure by operator.
    return ([(_STORE_CFG_GROUP, _STORE_OPTS)] +
            [(_STORE_CFG_GROUP, driver_opts)])


def register_opts(conf):
    opts = _list_opts()
    for group, opt_list in opts:
        LOG.debug("Registering options for group %s" % group)
        for opt in opt_list:
            conf.register_opt(opt, group=group)


class Indexable(object):
    """Indexable for file-like objs iterators

    Wrapper that allows an iterator or filelike be treated as an indexable
    data structure. This is required in the case where the return value from
    Store.get() is passed to Store.add() when adding a Copy-From image to a
    Store where the client library relies on eventlet GreenSockets, in which
    case the data to be written is indexed over.
    """

    def __init__(self, wrapped, size):
        """
        Initialize the object

        :param wrappped: the wrapped iterator or filelike.
        :param size: the size of data available
        """
        self.wrapped = wrapped
        self.size = int(size) if size else (wrapped.len
                                            if hasattr(wrapped, 'len') else 0)
        self.cursor = 0
        self.chunk = None

    def __iter__(self):
        """
        Delegate iteration to the wrapped instance.
        """
        for self.chunk in self.wrapped:
            yield self.chunk

    def __getitem__(self, i):
        """
        Index into the next chunk (or previous chunk in the case where
        the last data returned was not fully consumed).

        :param i: a slice-to-the-end
        """
        start = i.start if isinstance(i, slice) else i
        if start < self.cursor:
            return self.chunk[(start - self.cursor):]

        self.chunk = self.another()
        if self.chunk:
            self.cursor += len(self.chunk)

        return self.chunk

    def another(self):
        """Implemented by subclasses to return the next element."""
        raise NotImplementedError

    def getvalue(self):
        """
        Return entire string value... used in testing
        """
        return self.wrapped.getvalue()

    def __len__(self):
        """
        Length accessor.
        """
        return self.size


def _load_store(conf, store_entry, invoke_load=True):
    try:
        LOG.debug("Attempting to import store %s", store_entry)
        mgr = driver.DriverManager('glance_store.drivers',
                                   store_entry,
                                   invoke_args=[conf],
                                   invoke_on_load=invoke_load)
        return mgr.driver
    except RuntimeError as e:
        LOG.warn("Failed to load driver %(driver)s."
                 "The driver will be disabled" % dict(driver=str([driver, e])))


def _load_stores(conf):
    for store_entry in set(conf.glance_store.stores):
        try:
            # FIXME(flaper87): Don't hide BadStoreConfiguration
            # exceptions. These exceptions should be propagated
            # to the user of the library.
            store_instance = _load_store(conf, store_entry)

            if not store_instance:
                continue

            yield (store_entry, store_instance)

        except exceptions.BadStoreConfiguration:
            continue


def create_stores(conf=CONF):
    """
    Registers all store modules and all schemes
    from the given config. Duplicates are not re-registered.
    """
    store_count = 0

    for (store_entry, store_instance) in _load_stores(conf):
        try:
            schemes = store_instance.get_schemes()
            store_instance.configure(re_raise_bsc=False)
        except NotImplementedError:
            continue
        if not schemes:
            raise exceptions.BackendException('Unable to register store %s. '
                                              'No schemes associated with it.'
                                              % store_entry)
        else:
            LOG.debug("Registering store %s with schemes %s",
                      store_entry, schemes)

            scheme_map = {}
            loc_cls = store_instance.get_store_location_class()
            for scheme in schemes:
                scheme_map[scheme] = {
                    'store': store_instance,
                    'location_class': loc_cls,
                    'store_entry': store_entry
                }
            location.register_scheme_map(scheme_map)
            store_count += 1

    return store_count


def verify_default_store():
    scheme = CONF.glance_store.default_store
    try:
        get_store_from_scheme(scheme)
    except exceptions.UnknownScheme:
        msg = _("Store for scheme %s not found") % scheme
        raise RuntimeError(msg)


def get_known_schemes():
    """Returns list of known schemes."""
    return location.SCHEME_TO_CLS_MAP.keys()


def get_store_from_scheme(scheme):
    """
    Given a scheme, return the appropriate store object
    for handling that scheme.
    """
    if scheme not in location.SCHEME_TO_CLS_MAP:
        raise exceptions.UnknownScheme(scheme=scheme)
    scheme_info = location.SCHEME_TO_CLS_MAP[scheme]
    store = scheme_info['store']
    if not store.is_capable(capabilities.BitMasks.DRIVER_REUSABLE):
        # Driver instance isn't stateless so it can't
        # be reused safely and need recreation.
        store_entry = scheme_info['store_entry']
        store = _load_store(store.conf, store_entry, invoke_load=True)
        store.configure()
        try:
            scheme_map = {}
            loc_cls = store.get_store_location_class()
            for scheme in store.get_schemes():
                scheme_map[scheme] = {
                    'store': store,
                    'location_class': loc_cls,
                    'store_entry': store_entry
                }
                location.register_scheme_map(scheme_map)
        except NotImplementedError:
            scheme_info['store'] = store
    return store


def get_store_from_uri(uri):
    """
    Given a URI, return the store object that would handle
    operations on the URI.

    :param uri: URI to analyze
    """
    scheme = uri[0:uri.find('/') - 1]
    return get_store_from_scheme(scheme)


def get_from_backend(uri, offset=0, chunk_size=None, context=None):
    """Yields chunks of data from backend specified by uri."""

    loc = location.get_location_from_uri(uri, conf=CONF)
    store = get_store_from_uri(uri)

    return store.get(loc, offset=offset,
                     chunk_size=chunk_size,
                     context=context)


def get_size_from_backend(uri, context=None):
    """Retrieves image size from backend specified by uri."""

    loc = location.get_location_from_uri(uri, conf=CONF)
    store = get_store_from_uri(uri)
    return store.get_size(loc, context=context)


def delete_from_backend(uri, context=None):
    """Removes chunks of data from backend specified by uri."""

    loc = location.get_location_from_uri(uri, conf=CONF)
    store = get_store_from_uri(uri)
    return store.delete(loc, context=context)


def get_store_from_location(uri):
    """
    Given a location (assumed to be a URL), attempt to determine
    the store from the location.  We use here a simple guess that
    the scheme of the parsed URL is the store...

    :param uri: Location to check for the store
    """
    loc = location.get_location_from_uri(uri, conf=CONF)
    return loc.store_name


def check_location_metadata(val, key=''):
    if isinstance(val, dict):
        for key in val:
            check_location_metadata(val[key], key=key)
    elif isinstance(val, list):
        ndx = 0
        for v in val:
            check_location_metadata(v, key='%s[%d]' % (key, ndx))
            ndx = ndx + 1
    elif not isinstance(val, unicode):
        raise exceptions.BackendException(_("The image metadata key %(key)s "
                                            "has an invalid type of %(type)s. "
                                            "Only dict, list, and unicode are "
                                            "supported.")
                                          % dict(key=key, type=type(val)))


def store_add_to_backend(image_id, data, size, store, context=None):
    """
    A wrapper around a call to each stores add() method.  This gives glance
    a common place to check the output

    :param image_id:  The image add to which data is added
    :param data: The data to be stored
    :param size: The length of the data in bytes
    :param store: The store to which the data is being added
    :return: The url location of the file,
             the size amount of data,
             the checksum of the data
             the storage systems metadata dictionary for the location
    """
    (location, size, checksum, metadata) = store.add(image_id,
                                                     data,
                                                     size,
                                                     context=context)
    if metadata is not None:
        if not isinstance(metadata, dict):
            msg = (_("The storage driver %(driver)s returned invalid "
                     " metadata %(metadata)s. This must be a dictionary type")
                   % dict(driver=str(store), metadata=str(metadata)))
            LOG.error(msg)
            raise exceptions.BackendException(msg)
        try:
            check_location_metadata(metadata)
        except exceptions.BackendException as e:
            e_msg = (_("A bad metadata structure was returned from the "
                       "%(driver)s storage driver: %(metadata)s.  %(e)s.") %
                     dict(driver=utils.exception_to_str(store),
                          metadata=utils.exception_to_str(metadata),
                          e=utils.exception_to_str(e)))
            LOG.error(e_msg)
            raise exceptions.BackendException(e_msg)
    return (location, size, checksum, metadata)


def add_to_backend(conf, image_id, data, size, scheme=None, context=None):
    if scheme is None:
        scheme = conf['glance_store']['default_store']
    store = get_store_from_scheme(scheme)
    return store_add_to_backend(image_id, data, size, store, context)


def set_acls(location_uri, public=False, read_tenants=[],
             write_tenants=None, context=None):

    if write_tenants is None:
        write_tenants = []

    loc = location.get_location_from_uri(location_uri, conf=CONF)
    scheme = get_store_from_location(location_uri)
    store = get_store_from_scheme(scheme)
    try:
        store.set_acls(loc, public=public,
                       read_tenants=read_tenants,
                       write_tenants=write_tenants,
                       context=context)
    except NotImplementedError:
        LOG.debug(_("Skipping store.set_acls... not implemented."))

# Copyright 2011 OpenStack Foundation
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

"""
Routines for configuring Glance
"""

import logging
import logging.config
import logging.handlers
import os

from oslo_config import cfg
from paste import deploy

from glance.version import version_info as version
from glance_store.common import utils

paste_deploy_opts = [
    cfg.StrOpt('flavor',
               help=_('Partial name of a pipeline in your paste configuration '
                      'file with the service name removed. For example, if '
                      'your paste section name is '
                      '[pipeline:glance-api-keystone] use the value '
                      '"keystone"')),
    cfg.StrOpt('config_file',
               help=_('Name of the paste configuration file.')),
]
image_format_opts = [
    cfg.ListOpt('container_formats',
                default=['ami', 'ari', 'aki', 'bare', 'ovf'],
                help=_("Supported values for the 'container_format' "
                       "image attribute"),
                deprecated_opts=[cfg.DeprecatedOpt('container_formats',
                                                   group='DEFAULT')]),
    cfg.ListOpt('disk_formats',
                default=['ami', 'ari', 'aki', 'vhd', 'vmdk', 'raw', 'qcow2',
                         'vdi', 'iso'],
                help=_("Supported values for the 'disk_format' "
                       "image attribute"),
                deprecated_opts=[cfg.DeprecatedOpt('disk_formats',
                                                   group='DEFAULT')]),
]
task_opts = [
    cfg.IntOpt('task_time_to_live',
               default=48,
               help=_("Time in hours for which a task lives after, either "
                      "succeeding or failing"),
               deprecated_opts=[cfg.DeprecatedOpt('task_time_to_live',
                                                  group='DEFAULT')]),
]
common_opts = [
    cfg.BoolOpt('allow_additional_image_properties', default=True,
                help=_('Whether to allow users to specify image properties '
                       'beyond what the image schema provides')),
    cfg.IntOpt('image_member_quota', default=128,
               help=_('Maximum number of image members per image. '
                      'Negative values evaluate to unlimited.')),
    cfg.IntOpt('image_property_quota', default=128,
               help=_('Maximum number of properties allowed on an image. '
                      'Negative values evaluate to unlimited.')),
    cfg.IntOpt('image_tag_quota', default=128,
               help=_('Maximum number of tags allowed on an image. '
                      'Negative values evaluate to unlimited.')),
    cfg.IntOpt('image_location_quota', default=10,
               help=_('Maximum number of locations allowed on an image. '
                      'Negative values evaluate to unlimited.')),
    cfg.StrOpt('data_api', default='glance.db.sqlalchemy.api',
               help=_('Python module path of data access API')),
    cfg.IntOpt('limit_param_default', default=25,
               help=_('Default value for the number of items returned by a '
                      'request if not specified explicitly in the request')),
    cfg.IntOpt('api_limit_max', default=1000,
               help=_('Maximum permissible number of items that could be '
                      'returned by a request')),
    cfg.BoolOpt('show_image_direct_url', default=False,
                help=_('Whether to include the backend image storage location '
                       'in image properties. Revealing storage location can '
                       'be a security risk, so use this setting with '
                       'caution!')),
    cfg.BoolOpt('show_multiple_locations', default=False,
                help=_('Whether to include the backend image locations '
                       'in image properties. Revealing storage location can '
                       'be a security risk, so use this setting with '
                       'caution!  The overrides show_image_direct_url.')),
    cfg.IntOpt('image_size_cap', default=1099511627776,
               help=_("Maximum size of image a user can upload in bytes. "
                      "Defaults to 1099511627776 bytes (1 TB).")),
    cfg.IntOpt('user_storage_quota', default=0,
               help=_("Set a system wide quota for every user.  This value is "
                      "the total number of bytes that a user can use across "
                      "all storage systems.  A value of 0 means unlimited.")),
    cfg.BoolOpt('enable_v1_api', default=True,
                help=_("Deploy the v1 OpenStack Images API.")),
    cfg.BoolOpt('enable_v2_api', default=True,
                help=_("Deploy the v2 OpenStack Images API.")),
    cfg.StrOpt('pydev_worker_debug_host', default=None,
               help=_('The hostname/IP of the pydev process listening for '
                      'debug connections')),
    cfg.IntOpt('pydev_worker_debug_port', default=5678,
               help=_('The port on which a pydev process is listening for '
                      'connections.')),
    cfg.StrOpt('metadata_encryption_key', secret=True,
               help=_('Key used for encrypting sensitive metadata while '
                      'talking to the registry or database.')),
]

CONF = cfg.CONF
CONF.register_opts(paste_deploy_opts, group='paste_deploy')
CONF.register_opts(image_format_opts, group='image_format')
CONF.register_opts(task_opts, group='task')
CONF.register_opts(common_opts)


def parse_args(args=None, usage=None, default_config_files=None):
    CONF(args=args,
         project='glance',
         version=version.cached_version_string(),
         usage=usage,
         default_config_files=default_config_files)


def parse_cache_args(args=None):
    config_files = cfg.find_config_files(project='glance', prog='glance-cache')
    parse_args(args=args, default_config_files=config_files)


def _get_deployment_flavor(flavor=None):
    """
    Retrieve the paste_deploy.flavor config item, formatted appropriately
    for appending to the application name.

    :param flavor: if specified, use this setting rather than the
                   paste_deploy.flavor configuration setting
    """
    if not flavor:
        flavor = CONF.paste_deploy.flavor
    return '' if not flavor else ('-' + flavor)


def _get_paste_config_path():
    paste_suffix = '-paste.ini'
    conf_suffix = '.conf'
    if CONF.config_file:
        # Assume paste config is in a paste.ini file corresponding
        # to the last config file
        path = CONF.config_file[-1].replace(conf_suffix, paste_suffix)
    else:
        path = CONF.prog + paste_suffix
    return CONF.find_file(os.path.basename(path))


def _get_deployment_config_file():
    """
    Retrieve the deployment_config_file config item, formatted as an
    absolute pathname.
    """
    path = CONF.paste_deploy.config_file
    if not path:
        path = _get_paste_config_path()
    if not path:
        msg = "Unable to locate paste config file for %s." % CONF.prog
        raise RuntimeError(msg)
    return os.path.abspath(path)


def load_paste_app(app_name, flavor=None, conf_file=None):
    """
    Builds and returns a WSGI app from a paste config file.

    We assume the last config file specified in the supplied ConfigOpts
    object is the paste config file, if conf_file is None.

    :param app_name: name of the application to load
    :param flavor: name of the variant of the application to load
    :param conf_file: path to the paste config file

    :raises RuntimeError when config file cannot be located or application
            cannot be loaded from config file
    """
    # append the deployment flavor to the application name,
    # in order to identify the appropriate paste pipeline
    app_name += _get_deployment_flavor(flavor)

    if not conf_file:
        conf_file = _get_deployment_config_file()

    try:
        logger = logging.getLogger(__name__)
        logger.debug(_("Loading %(app_name)s from %(conf_file)s"),
                     {'conf_file': conf_file, 'app_name': app_name})

        app = deploy.loadapp("config:%s" % conf_file, name=app_name)

        # Log the options used when starting if we're in debug mode...
        if CONF.debug:
            CONF.log_opt_values(logger, logging.DEBUG)

        return app
    except (LookupError, ImportError) as e:
        msg = (_("Unable to load %(app_name)s from "
                 "configuration file %(conf_file)s."
                 "\nGot: %(e)r") % {'app_name': app_name,
                                    'conf_file': conf_file,
                                    'e': utils.exception_to_str(e)})
        logger.error(msg)
        raise RuntimeError(msg)

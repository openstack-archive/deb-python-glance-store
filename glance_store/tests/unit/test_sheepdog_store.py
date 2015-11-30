# Copyright 2013 OpenStack Foundation
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

import mock
from oslo_concurrency import processutils
import six

from glance_store._drivers import sheepdog
from glance_store import exceptions
from glance_store import location
from glance_store.tests import base
from glance_store.tests.unit import test_store_capabilities


class TestSheepdogStore(base.StoreBaseTest,
                        test_store_capabilities.TestStoreCapabilitiesChecking):

    def setUp(self):
        """Establish a clean test environment."""
        super(TestSheepdogStore, self).setUp()

        def _fake_execute(*cmd, **kwargs):
            pass

        self.config(default_store='sheepdog',
                    group='glance_store')

        execute = mock.patch.object(processutils, 'execute').start()
        execute.side_effect = _fake_execute
        self.addCleanup(execute.stop)
        self.store = sheepdog.Store(self.conf)
        self.store.configure()
        self.store_specs = {'image': 'fake_image',
                            'addr': 'fake_addr',
                            'port': 'fake_port'}

    def test_add_image(self):
        called_commands = []

        def _fake_run_command(command, data, *params):
            called_commands.append(command)

        with mock.patch.object(sheepdog.SheepdogImage, '_run_command') as cmd:
            cmd.side_effect = _fake_run_command
            data = six.BytesIO(b'xx')
            ret = self.store.add('fake_image_id', data, 2)
            self.assertEqual(called_commands, ['list -r', 'create', 'write'])
            self.assertEqual(ret[1], 2)

    def test_cleanup_when_add_image_exception(self):
        called_commands = []

        def _fake_run_command(command, data, *params):
            if command == 'write':
                raise exceptions.BackendException
            else:
                called_commands.append(command)

        with mock.patch.object(sheepdog.SheepdogImage, '_run_command') as cmd:
            cmd.side_effect = _fake_run_command
            data = six.BytesIO(b'xx')
            self.assertRaises(exceptions.BackendException, self.store.add,
                              'fake_image_id', data, 2)
            self.assertTrue('delete' in called_commands)

    def test_add_duplicate_image(self):
        def _fake_run_command(command, data, *params):
            if command == "list -r":
                return "= fake_volume 0 1000"

        with mock.patch.object(sheepdog.SheepdogImage, '_run_command') as cmd:
            cmd.side_effect = _fake_run_command
            data = six.BytesIO(b'xx')
            self.assertRaises(exceptions.Duplicate, self.store.add,
                              'fake_image_id', data, 2)

    def test_get(self):
        def _fake_run_command(command, data, *params):
            if command == "list -r":
                return "= fake_volume 0 1000"

        with mock.patch.object(sheepdog.SheepdogImage, '_run_command') as cmd:
            cmd.side_effect = _fake_run_command
            loc = location.Location('test_sheepdog_store',
                                    sheepdog.StoreLocation,
                                    self.conf, store_specs=self.store_specs)
            ret = self.store.get(loc)
            self.assertEqual(ret[1], 1000)

    def test_partial_get(self):
        loc = location.Location('test_sheepdog_store', sheepdog.StoreLocation,
                                self.conf, store_specs=self.store_specs)
        self.assertRaises(exceptions.StoreRandomGetNotSupported,
                          self.store.get, loc, chunk_size=1)

    def test_get_size(self):
        def _fake_run_command(command, data, *params):
            if command == "list -r":
                return "= fake_volume 0 1000"

        with mock.patch.object(sheepdog.SheepdogImage, '_run_command') as cmd:
            cmd.side_effect = _fake_run_command
            loc = location.Location('test_sheepdog_store',
                                    sheepdog.StoreLocation,
                                    self.conf, store_specs=self.store_specs)
            ret = self.store.get_size(loc)
            self.assertEqual(ret, 1000)

    def test_delete(self):
        called_commands = []

        def _fake_run_command(command, data, *params):
            called_commands.append(command)
            if command == "list -r":
                return "= fake_volume 0 1000"

        with mock.patch.object(sheepdog.SheepdogImage, '_run_command') as cmd:
            cmd.side_effect = _fake_run_command
            loc = location.Location('test_sheepdog_store',
                                    sheepdog.StoreLocation,
                                    self.conf, store_specs=self.store_specs)
            self.store.delete(loc)
            self.assertEqual(called_commands, ['list -r', 'delete'])

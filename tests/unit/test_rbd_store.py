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

import StringIO

import mock
from oslo_utils import units

from glance_store._drivers import rbd as rbd_store
from glance_store import exceptions
from glance_store.location import Location
from glance_store.tests import base
from tests.unit import test_store_capabilities


class MockRados(object):

    class ioctx(object):
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self, *args, **kwargs):
            return self

        def __exit__(self, *args, **kwargs):
            return False

        def close(self, *args, **kwargs):
            pass

    class Rados(object):

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self, *args, **kwargs):
            return self

        def __exit__(self, *args, **kwargs):
            return False

        def connect(self, *args, **kwargs):
            pass

        def open_ioctx(self, *args, **kwargs):
            return MockRados.ioctx()

        def shutdown(self, *args, **kwargs):
            pass


class MockRBD(object):

    class ImageExists(Exception):
        pass

    class ImageBusy(Exception):
        pass

    class ImageNotFound(Exception):
        pass

    class Image(object):

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self, *args, **kwargs):
            return self

        def __exit__(self, *args, **kwargs):
            pass

        def create_snap(self, *args, **kwargs):
            pass

        def remove_snap(self, *args, **kwargs):
            pass

        def protect_snap(self, *args, **kwargs):
            pass

        def unprotect_snap(self, *args, **kwargs):
            pass

        def read(self, *args, **kwargs):
            raise NotImplementedError()

        def write(self, *args, **kwargs):
            raise NotImplementedError()

        def resize(self, *args, **kwargs):
            raise NotImplementedError()

        def discard(self, offset, length):
            raise NotImplementedError()

        def close(self):
            pass

        def list_snaps(self):
            raise NotImplementedError()

        def parent_info(self):
            raise NotImplementedError()

        def size(self):
            raise NotImplementedError()

    class RBD(object):

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self, *args, **kwargs):
            return self

        def __exit__(self, *args, **kwargs):
            return False

        def create(self, *args, **kwargs):
            pass

        def remove(self, *args, **kwargs):
            pass

        def list(self, *args, **kwargs):
            raise NotImplementedError()

        def clone(self, *args, **kwargs):
            raise NotImplementedError()


class TestStore(base.StoreBaseTest,
                test_store_capabilities.TestStoreCapabilitiesChecking):

    def setUp(self):
        """Establish a clean test environment."""
        super(TestStore, self).setUp()

        rbd_store.rados = MockRados
        rbd_store.rbd = MockRBD

        self.store = rbd_store.Store(self.conf)
        self.store.configure()
        self.store.chunk_size = 2
        self.called_commands_actual = []
        self.called_commands_expected = []
        self.store_specs = {'pool': 'fake_pool',
                            'image': 'fake_image',
                            'snapshot': 'fake_snapshot'}
        self.location = rbd_store.StoreLocation(self.store_specs,
                                                self.conf)
        # Provide enough data to get more than one chunk iteration.
        self.data_len = 3 * units.Ki
        self.data_iter = StringIO.StringIO('*' * self.data_len)

    def test_add_w_image_size_zero(self):
        """Assert that correct size is returned even though 0 was provided."""
        self.store.chunk_size = units.Ki
        with mock.patch.object(rbd_store.rbd.Image, 'resize') as resize:
            with mock.patch.object(rbd_store.rbd.Image, 'write') as write:
                ret = self.store.add('fake_image_id', self.data_iter, 0)

                self.assertTrue(resize.called)
                self.assertTrue(write.called)
                self.assertEqual(ret[1], self.data_len)

    @mock.patch.object(MockRBD.Image, '__enter__')
    @mock.patch.object(rbd_store.Store, '_create_image')
    @mock.patch.object(rbd_store.Store, '_delete_image')
    def test_add_w_rbd_image_exception(self, delete, create, enter):
        def _fake_create_image(*args, **kwargs):
            self.called_commands_actual.append('create')
            return self.location

        def _fake_delete_image(target_pool, image_name, snapshot_name=None):
            self.assertEqual(self.location.pool, target_pool)
            self.assertEqual(self.location.image, image_name)
            self.assertEqual(self.location.snapshot, snapshot_name)
            self.called_commands_actual.append('delete')

        def _fake_enter(*args, **kwargs):
            raise exceptions.NotFound(image="fake_image_id")

        create.side_effect = _fake_create_image
        delete.side_effect = _fake_delete_image
        enter.side_effect = _fake_enter

        self.assertRaises(exceptions.NotFound, self.store.add,
                          'fake_image_id', self.data_iter, self.data_len)

        self.called_commands_expected = ['create', 'delete']

    def test_add_duplicate_image(self):

        def _fake_create_image(*args, **kwargs):
            self.called_commands_actual.append('create')
            raise MockRBD.ImageExists()

        with mock.patch.object(self.store, '_create_image') as create_image:
            create_image.side_effect = _fake_create_image

            self.assertRaises(exceptions.Duplicate, self.store.add,
                              'fake_image_id', self.data_iter, self.data_len)
            self.called_commands_expected = ['create']

    def test_delete(self):
        def _fake_remove(*args, **kwargs):
            self.called_commands_actual.append('remove')

        with mock.patch.object(MockRBD.RBD, 'remove') as remove_image:
            remove_image.side_effect = _fake_remove

            self.store.delete(Location('test_rbd_store',
                                       rbd_store.StoreLocation,
                                       self.conf,
                                       uri=self.location.get_uri()))
            self.called_commands_expected = ['remove']

    def test_delete_image(self):
        def _fake_remove(*args, **kwargs):
            self.called_commands_actual.append('remove')

        with mock.patch.object(MockRBD.RBD, 'remove') as remove_image:
            remove_image.side_effect = _fake_remove

            self.store._delete_image('fake_pool', self.location.image)
            self.called_commands_expected = ['remove']

    @mock.patch.object(MockRBD.RBD, 'remove')
    @mock.patch.object(MockRBD.Image, 'remove_snap')
    @mock.patch.object(MockRBD.Image, 'unprotect_snap')
    def test_delete_image_w_snap(self, unprotect, remove_snap, remove):
        def _fake_unprotect_snap(*args, **kwargs):
            self.called_commands_actual.append('unprotect_snap')

        def _fake_remove_snap(*args, **kwargs):
            self.called_commands_actual.append('remove_snap')

        def _fake_remove(*args, **kwargs):
            self.called_commands_actual.append('remove')

        remove.side_effect = _fake_remove
        unprotect.side_effect = _fake_unprotect_snap
        remove_snap.side_effect = _fake_remove_snap
        self.store._delete_image('fake_pool', self.location.image,
                                 snapshot_name='snap')

        self.called_commands_expected = ['unprotect_snap', 'remove_snap',
                                         'remove']

    def test_delete_image_w_snap_exc_image_not_found(self):
        def _fake_unprotect_snap(*args, **kwargs):
            self.called_commands_actual.append('unprotect_snap')
            raise MockRBD.ImageNotFound()

        with mock.patch.object(MockRBD.Image, 'unprotect_snap') as mocked:
            mocked.side_effect = _fake_unprotect_snap

            self.assertRaises(exceptions.NotFound, self.store._delete_image,
                              'fake_pool', self.location.image,
                              snapshot_name='snap')

            self.called_commands_expected = ['unprotect_snap']

    def test_delete_image_exc_image_not_found(self):
        def _fake_remove(*args, **kwargs):
            self.called_commands_actual.append('remove')
            raise MockRBD.ImageNotFound()

        with mock.patch.object(MockRBD.RBD, 'remove') as remove:
            remove.side_effect = _fake_remove
            self.assertRaises(exceptions.NotFound, self.store._delete_image,
                              'fake_pool', self.location.image,
                              snapshot_name='snap')

            self.called_commands_expected = ['remove']

    def test_get_partial_image(self):
        loc = Location('test_rbd_store', rbd_store.StoreLocation, self.conf,
                       store_specs=self.store_specs)
        self.assertRaises(exceptions.StoreRandomGetNotSupported,
                          self.store.get, loc, chunk_size=1)

    def tearDown(self):
        self.assertEqual(self.called_commands_actual,
                         self.called_commands_expected)
        super(TestStore, self).tearDown()

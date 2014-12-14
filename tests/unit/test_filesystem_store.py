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

"""Tests the filesystem backend store"""

import __builtin__
import errno
import hashlib
import json
import mock
import os
import stat
import StringIO
import uuid

import fixtures
from oslo.utils import units
import six

from glance_store._drivers.filesystem import ChunkedFile
from glance_store._drivers.filesystem import Store
from glance_store import exceptions
from glance_store import location
from glance_store.tests import base


KB = 1024


class TestStore(base.StoreBaseTest):

    def setUp(self):
        """Establish a clean test environment."""
        super(TestStore, self).setUp()
        self.orig_chunksize = Store.READ_CHUNKSIZE
        Store.READ_CHUNKSIZE = 10
        self.store = Store(self.conf)
        self.config(filesystem_store_datadir=self.test_dir,
                    group="glance_store")
        self.store.configure()

    def tearDown(self):
        """Clear the test environment."""
        super(TestStore, self).tearDown()
        ChunkedFile.CHUNKSIZE = self.orig_chunksize

    def test_get(self):
        """Test a "normal" retrieval of an image in chunks."""
        # First add an image...
        image_id = str(uuid.uuid4())
        file_contents = "chunk00000remainder"
        image_file = StringIO.StringIO(file_contents)

        loc, size, checksum, _ = self.store.add(image_id,
                                                image_file,
                                                len(file_contents))

        # Now read it back...
        uri = "file:///%s/%s" % (self.test_dir, image_id)
        loc = location.get_location_from_uri(uri, conf=self.conf)
        (image_file, image_size) = self.store.get(loc)

        expected_data = "chunk00000remainder"
        expected_num_chunks = 2
        data = ""
        num_chunks = 0

        for chunk in image_file:
            num_chunks += 1
            data += chunk
        self.assertEqual(expected_data, data)
        self.assertEqual(expected_num_chunks, num_chunks)

    def test_get_random_access(self):
        """Test a "normal" retrieval of an image in chunks."""
        # First add an image...
        image_id = str(uuid.uuid4())
        file_contents = "chunk00000remainder"
        image_file = StringIO.StringIO(file_contents)

        loc, size, checksum, _ = self.store.add(image_id,
                                                image_file,
                                                len(file_contents))

        # Now read it back...
        uri = "file:///%s/%s" % (self.test_dir, image_id)
        loc = location.get_location_from_uri(uri, conf=self.conf)

        data = ""
        for offset in range(len(file_contents)):
            (image_file, image_size) = self.store.get(loc,
                                                      offset=offset,
                                                      chunk_size=1)
            for chunk in image_file:
                data += chunk

        self.assertEqual(data, file_contents)

        data = ""
        chunk_size = 5
        (image_file, image_size) = self.store.get(loc,
                                                  offset=chunk_size,
                                                  chunk_size=chunk_size)
        for chunk in image_file:
            data += chunk

        self.assertEqual(data, '00000')
        self.assertEqual(image_size, chunk_size)

    def test_get_non_existing(self):
        """
        Test that trying to retrieve a file that doesn't exist
        raises an error
        """
        loc = location.get_location_from_uri(
            "file:///%s/non-existing" % self.test_dir, conf=self.conf)
        self.assertRaises(exceptions.NotFound,
                          self.store.get,
                          loc)

    def test_add(self):
        """Test that we can add an image via the filesystem backend."""
        ChunkedFile.CHUNKSIZE = 1024
        expected_image_id = str(uuid.uuid4())
        expected_file_size = 5 * KB  # 5K
        expected_file_contents = "*" * expected_file_size
        expected_checksum = hashlib.md5(expected_file_contents).hexdigest()
        expected_location = "file://%s/%s" % (self.test_dir,
                                              expected_image_id)
        image_file = StringIO.StringIO(expected_file_contents)

        loc, size, checksum, _ = self.store.add(expected_image_id,
                                                image_file,
                                                expected_file_size)

        self.assertEqual(expected_location, loc)
        self.assertEqual(expected_file_size, size)
        self.assertEqual(expected_checksum, checksum)

        uri = "file:///%s/%s" % (self.test_dir, expected_image_id)
        loc = location.get_location_from_uri(uri, conf=self.conf)
        (new_image_file, new_image_size) = self.store.get(loc)
        new_image_contents = ""
        new_image_file_size = 0

        for chunk in new_image_file:
            new_image_file_size += len(chunk)
            new_image_contents += chunk

        self.assertEqual(expected_file_contents, new_image_contents)
        self.assertEqual(expected_file_size, new_image_file_size)

    def test_add_check_metadata_success(self):
        expected_image_id = str(uuid.uuid4())
        in_metadata = {'akey': u'some value', 'list': [u'1', u'2', u'3']}
        jsonfilename = os.path.join(self.test_dir,
                                    "storage_metadata.%s" % expected_image_id)

        self.config(filesystem_store_metadata_file=jsonfilename,
                    group="glance_store")
        with open(jsonfilename, 'w') as fptr:
            json.dump(in_metadata, fptr)
        expected_file_size = 10
        expected_file_contents = "*" * expected_file_size
        image_file = StringIO.StringIO(expected_file_contents)

        location, size, checksum, metadata = self.store.add(expected_image_id,
                                                            image_file,
                                                            expected_file_size)

        self.assertEqual(metadata, in_metadata)

    def test_add_check_metadata_bad_data(self):
        expected_image_id = str(uuid.uuid4())
        in_metadata = {'akey': 10}  # only unicode is allowed
        jsonfilename = os.path.join(self.test_dir,
                                    "storage_metadata.%s" % expected_image_id)

        self.config(filesystem_store_metadata_file=jsonfilename,
                    group="glance_store")
        with open(jsonfilename, 'w') as fptr:
            json.dump(in_metadata, fptr)
        expected_file_size = 10
        expected_file_contents = "*" * expected_file_size
        image_file = StringIO.StringIO(expected_file_contents)

        location, size, checksum, metadata = self.store.add(expected_image_id,
                                                            image_file,
                                                            expected_file_size)

        self.assertEqual(metadata, {})

    def test_add_check_metadata_bad_nosuch_file(self):
        expected_image_id = str(uuid.uuid4())
        jsonfilename = os.path.join(self.test_dir,
                                    "storage_metadata.%s" % expected_image_id)

        self.config(filesystem_store_metadata_file=jsonfilename,
                    group="glance_store")
        expected_file_size = 10
        expected_file_contents = "*" * expected_file_size
        image_file = StringIO.StringIO(expected_file_contents)

        location, size, checksum, metadata = self.store.add(expected_image_id,
                                                            image_file,
                                                            expected_file_size)

        self.assertEqual(metadata, {})

    def test_add_already_existing(self):
        """
        Tests that adding an image with an existing identifier
        raises an appropriate exception
        """
        ChunkedFile.CHUNKSIZE = 1024
        image_id = str(uuid.uuid4())
        file_size = 5 * KB  # 5K
        file_contents = "*" * file_size
        image_file = StringIO.StringIO(file_contents)

        location, size, checksum, _ = self.store.add(image_id,
                                                     image_file,
                                                     file_size)
        image_file = StringIO.StringIO("nevergonnamakeit")
        self.assertRaises(exceptions.Duplicate,
                          self.store.add,
                          image_id, image_file, 0)

    def _do_test_add_write_failure(self, errno, exception):
        ChunkedFile.CHUNKSIZE = 1024
        image_id = str(uuid.uuid4())
        file_size = 5 * KB  # 5K
        file_contents = "*" * file_size
        path = os.path.join(self.test_dir, image_id)
        image_file = StringIO.StringIO(file_contents)

        with mock.patch.object(__builtin__, 'open') as popen:
            e = IOError()
            e.errno = errno
            popen.side_effect = e

            self.assertRaises(exception,
                              self.store.add,
                              image_id, image_file, 0)
            self.assertFalse(os.path.exists(path))

    def test_add_storage_full(self):
        """
        Tests that adding an image without enough space on disk
        raises an appropriate exception
        """
        self._do_test_add_write_failure(errno.ENOSPC, exceptions.StorageFull)

    def test_add_file_too_big(self):
        """
        Tests that adding an excessively large image file
        raises an appropriate exception
        """
        self._do_test_add_write_failure(errno.EFBIG, exceptions.StorageFull)

    def test_add_storage_write_denied(self):
        """
        Tests that adding an image with insufficient filestore permissions
        raises an appropriate exception
        """
        self._do_test_add_write_failure(errno.EACCES,
                                        exceptions.StorageWriteDenied)

    def test_add_other_failure(self):
        """
        Tests that a non-space-related IOError does not raise a
        StorageFull exceptions.
        """
        self._do_test_add_write_failure(errno.ENOTDIR, IOError)

    def test_add_cleanup_on_read_failure(self):
        """
        Tests the partial image file is cleaned up after a read
        failure.
        """
        ChunkedFile.CHUNKSIZE = 1024
        image_id = str(uuid.uuid4())
        file_size = 5 * KB  # 5K
        file_contents = "*" * file_size
        path = os.path.join(self.test_dir, image_id)
        image_file = StringIO.StringIO(file_contents)

        def fake_Error(size):
            raise AttributeError()

        with mock.patch.object(image_file, 'read') as mock_read:
            mock_read.side_effect = fake_Error

            self.assertRaises(AttributeError,
                              self.store.add,
                              image_id, image_file, 0)
            self.assertFalse(os.path.exists(path))

    def test_delete(self):
        """
        Test we can delete an existing image in the filesystem store
        """
        # First add an image
        image_id = str(uuid.uuid4())
        file_size = 5 * KB  # 5K
        file_contents = "*" * file_size
        image_file = StringIO.StringIO(file_contents)

        loc, size, checksum, _ = self.store.add(image_id,
                                                image_file,
                                                file_size)

        # Now check that we can delete it
        uri = "file:///%s/%s" % (self.test_dir, image_id)
        loc = location.get_location_from_uri(uri, conf=self.conf)
        self.store.delete(loc)

        self.assertRaises(exceptions.NotFound, self.store.get, loc)

    def test_delete_non_existing(self):
        """
        Test that trying to delete a file that doesn't exist
        raises an error
        """
        loc = location.get_location_from_uri(
            "file:///tmp/glance-tests/non-existing", conf=self.conf)
        self.assertRaises(exceptions.NotFound,
                          self.store.delete,
                          loc)

    def test_configure_add_with_multi_datadirs(self):
        """
        Tests multiple filesystem specified by filesystem_store_datadirs
        are parsed correctly.
        """
        store_map = [self.useFixture(fixtures.TempDir()).path,
                     self.useFixture(fixtures.TempDir()).path]
        self.conf.clear_override('filesystem_store_datadir',
                                 group='glance_store')
        self.conf.set_override('filesystem_store_datadirs',
                               [store_map[0] + ":100",
                                store_map[1] + ":200"],
                               group='glance_store')
        self.store.configure_add()

        expected_priority_map = {100: [store_map[0]], 200: [store_map[1]]}
        expected_priority_list = [200, 100]
        self.assertEqual(self.store.priority_data_map, expected_priority_map)
        self.assertEqual(self.store.priority_list, expected_priority_list)

    def test_configure_add_same_dir_multiple_times(self):
        """
        Tests BadStoreConfiguration exception is raised if same directory
        is specified multiple times in filesystem_store_datadirs.
        """
        store_map = [self.useFixture(fixtures.TempDir()).path,
                     self.useFixture(fixtures.TempDir()).path]
        self.conf.clear_override('filesystem_store_datadir',
                                 group='glance_store')
        self.conf.set_override('filesystem_store_datadirs',
                               [store_map[0] + ":100",
                                store_map[1] + ":200",
                                store_map[0] + ":300"],
                               group='glance_store')
        self.assertRaises(exceptions.BadStoreConfiguration,
                          self.store.configure_add)

    def test_add_with_multiple_dirs(self):
        """Test adding multiple filesystem directories."""
        store_map = [self.useFixture(fixtures.TempDir()).path,
                     self.useFixture(fixtures.TempDir()).path]
        self.conf.clear_override('filesystem_store_datadir',
                                 group='glance_store')
        self.conf.set_override('filesystem_store_datadirs',
                               [store_map[0] + ":100",
                                store_map[1] + ":200"],
                               group='glance_store')

        self.store.configure()

        """Test that we can add an image via the filesystem backend"""
        ChunkedFile.CHUNKSIZE = 1024
        expected_image_id = str(uuid.uuid4())
        expected_file_size = 5 * units.Ki  # 5K
        expected_file_contents = "*" * expected_file_size
        expected_checksum = hashlib.md5(expected_file_contents).hexdigest()
        expected_location = "file://%s/%s" % (store_map[1],
                                              expected_image_id)
        image_file = six.StringIO(expected_file_contents)

        loc, size, checksum, _ = self.store.add(expected_image_id,
                                                image_file,
                                                expected_file_size)

        self.assertEqual(expected_location, loc)
        self.assertEqual(expected_file_size, size)
        self.assertEqual(expected_checksum, checksum)

        loc = location.get_location_from_uri(expected_location,
                                             conf=self.conf)
        (new_image_file, new_image_size) = self.store.get(loc)
        new_image_contents = ""
        new_image_file_size = 0

        for chunk in new_image_file:
            new_image_file_size += len(chunk)
            new_image_contents += chunk

        self.assertEqual(expected_file_contents, new_image_contents)
        self.assertEqual(expected_file_size, new_image_file_size)

    def test_add_with_multiple_dirs_storage_full(self):
        """
        Test StorageFull exception is raised if no filesystem directory
        is found that can store an image.
        """
        store_map = [self.useFixture(fixtures.TempDir()).path,
                     self.useFixture(fixtures.TempDir()).path]
        self.conf.clear_override('filesystem_store_datadir',
                                 group='glance_store')
        self.conf.set_override('filesystem_store_datadirs',
                               [store_map[0] + ":100",
                                store_map[1] + ":200"],
                               group='glance_store')

        self.store.configure_add()

        def fake_get_capacity_info(mount_point):
            return 0

        with mock.patch.object(self.store, '_get_capacity_info') as capacity:
            capacity.return_value = 0

            ChunkedFile.CHUNKSIZE = 1024
            expected_image_id = str(uuid.uuid4())
            expected_file_size = 5 * units.Ki  # 5K
            expected_file_contents = "*" * expected_file_size
            image_file = six.StringIO(expected_file_contents)

            self.assertRaises(exceptions.StorageFull, self.store.add,
                              expected_image_id, image_file,
                              expected_file_size)

    def test_configure_add_with_file_perm(self):
        """
        Tests filesystem specified by filesystem_store_file_perm
        are parsed correctly.
        """
        store = self.useFixture(fixtures.TempDir()).path
        self.conf.set_override('filesystem_store_datadir', store,
                               group='glance_store')
        self.conf.set_override('filesystem_store_file_perm', 700,  # -rwx------
                               group='glance_store')
        self.store.configure_add()
        self.assertEqual(self.store.datadir, store)

    def test_configure_add_with_unaccessible_file_perm(self):
        """
        Tests BadStoreConfiguration exception is raised if an invalid
        file permission specified in filesystem_store_file_perm.
        """
        store = self.useFixture(fixtures.TempDir()).path
        self.conf.set_override('filesystem_store_datadir', store,
                               group='glance_store')
        self.conf.set_override('filesystem_store_file_perm', 7,  # -------rwx
                               group='glance_store')
        self.assertRaises(exceptions.BadStoreConfiguration,
                          self.store.configure_add)

    def test_add_with_file_perm_for_group_other_users_access(self):
        """
        Test that we can add an image via the filesystem backend with a
        required image file permission.
        """
        store = self.useFixture(fixtures.TempDir()).path
        self.conf.set_override('filesystem_store_datadir', store,
                               group='glance_store')
        self.conf.set_override('filesystem_store_file_perm', 744,  # -rwxr--r--
                               group='glance_store')

        # -rwx------
        os.chmod(store, 0o700)
        self.assertEqual(0o700, stat.S_IMODE(os.stat(store)[stat.ST_MODE]))

        self.store.configure_add()

        Store.WRITE_CHUNKSIZE = 1024
        expected_image_id = str(uuid.uuid4())
        expected_file_size = 5 * units.Ki  # 5K
        expected_file_contents = "*" * expected_file_size
        expected_checksum = hashlib.md5(expected_file_contents).hexdigest()
        expected_location = "file://%s/%s" % (store,
                                              expected_image_id)
        image_file = six.StringIO(expected_file_contents)

        location, size, checksum, _ = self.store.add(expected_image_id,
                                                     image_file,
                                                     expected_file_size)

        self.assertEqual(expected_location, location)
        self.assertEqual(expected_file_size, size)
        self.assertEqual(expected_checksum, checksum)

        # -rwx--x--x for store directory
        self.assertEqual(0o711, stat.S_IMODE(os.stat(store)[stat.ST_MODE]))
        # -rwxr--r-- for image file
        mode = os.stat(expected_location[len('file:/'):])[stat.ST_MODE]
        perm = int(str(self.conf.glance_store.filesystem_store_file_perm), 8)
        self.assertEqual(perm, stat.S_IMODE(mode))

    def test_add_with_file_perm_for_owner_users_access(self):
        """
        Test that we can add an image via the filesystem backend with a
        required image file permission.
        """
        store = self.useFixture(fixtures.TempDir()).path
        self.conf.set_override('filesystem_store_datadir', store,
                               group='glance_store')
        self.conf.set_override('filesystem_store_file_perm', 600,  # -rw-------
                               group='glance_store')

        # -rwx------
        os.chmod(store, 0o700)
        self.assertEqual(0o700, stat.S_IMODE(os.stat(store)[stat.ST_MODE]))

        self.store.configure_add()

        Store.WRITE_CHUNKSIZE = 1024
        expected_image_id = str(uuid.uuid4())
        expected_file_size = 5 * units.Ki  # 5K
        expected_file_contents = "*" * expected_file_size
        expected_checksum = hashlib.md5(expected_file_contents).hexdigest()
        expected_location = "file://%s/%s" % (store,
                                              expected_image_id)
        image_file = six.StringIO(expected_file_contents)

        location, size, checksum, _ = self.store.add(expected_image_id,
                                                     image_file,
                                                     expected_file_size)

        self.assertEqual(expected_location, location)
        self.assertEqual(expected_file_size, size)
        self.assertEqual(expected_checksum, checksum)

        # -rwx------ for store directory
        self.assertEqual(0o700, stat.S_IMODE(os.stat(store)[stat.ST_MODE]))
        # -rw------- for image file
        mode = os.stat(expected_location[len('file:/'):])[stat.ST_MODE]
        perm = int(str(self.conf.glance_store.filesystem_store_file_perm), 8)
        self.assertEqual(perm, stat.S_IMODE(mode))

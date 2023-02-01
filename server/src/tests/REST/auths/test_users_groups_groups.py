# -*- coding: utf-8 -*-
#
# Copyright (c) 2022 Virtual Cable S.L.U.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#    * Redistributions of source code must retain the above copyright notice,
#      this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above copyright notice,
#      this list of conditions and the following disclaimer in the documentation
#      and/or other materials provided with the distribution.
#    * Neither the name of Virtual Cable S.L.U. nor the names of its contributors
#      may be used to endorse or promote products derived from this software
#      without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
@author: Adolfo Gómez, dkmaster at dkmon dot com
"""
import typing
import functools
import logging

from uds import models
from uds.core import VERSION
from uds.core.managers import cryptoManager

from ...utils import rest


logger = logging.getLogger(__name__)


class GroupsTest(rest.test.RESTActorTestCase):
    """
    Test users group rest api
    """
    def setUp(self) -> None:
        # Override number of items to create
        rest.test.NUMBER_OF_ITEMS_TO_CREATE = 16
        super().setUp()
        self.login()

    def test_groups(self) -> None:
        url = f'authenticators/{self.auth.uuid}/groups'

        # Now, will work
        response = self.client.rest_get(f'{url}/overview')
        self.assertEqual(response.status_code, 200)
        groups = response.json()
        self.assertEqual(
            len(groups), rest.test.NUMBER_OF_ITEMS_TO_CREATE * 2  # simple + meta
        )
        group: typing.Mapping[str, typing.Any]
        for group in groups:
            # Locate the group in the auth
            dbgrp = self.auth.groups.get(name=group['name'])
            self.assertEqual(dbgrp.uuid, group['id'])
            self.assertEqual(dbgrp.comments, group['comments'])
            self.assertEqual(dbgrp.state, group['state'])
            self.assertEqual(dbgrp.is_meta, group['type'] == 'meta')
            self.assertEqual(dbgrp.meta_if_any, group['meta_if_any'])
            if dbgrp.is_meta:
                self.assertEqual(
                    sorted([x.uuid for x in dbgrp.groups.all()]),
                    sorted(group['groups'])
                )

    def test_groups_tableinfo(self) -> None:
        url = f'authenticators/{self.auth.uuid}/groups/tableinfo'

        # Now, will work
        response = self.client.rest_get(url)
        self.assertEqual(response.status_code, 200)
        tableinfo = response.json()
        self.assertIn('title', tableinfo)
        self.assertIn('subtitle', tableinfo)
        self.assertIn('fields', tableinfo)
        self.assertIn('row-style', tableinfo)

        # Ensure at least name, comments ans state are present on tableinfo['fields']
        fields: typing.List[typing.Mapping[str, typing.Any]] = tableinfo['fields']
        self.assertTrue(
            functools.reduce(
                lambda x, y: x and y,
                map(
                    lambda f: next(iter(f.keys()))
                    in (
                        'name',
                        'comments',
                        'state',
                    ),
                    fields,
                ),
            )
        )

    def test_group(self) -> None:
        url = f'authenticators/{self.auth.uuid}/groups'
        # Now, will work
        for i in self.groups:
            response = self.client.rest_get(f'{url}/{i.uuid}')
            self.assertEqual(response.status_code, 200)
            group = response.json()

            self.assertEqual(group['name'], i.name)
            self.assertEqual(group['id'], i.uuid)
            self.assertEqual(group['comments'], i.comments)
            self.assertEqual(group['state'], i.state)
            self.assertEqual(group['type'], 'meta' if i.is_meta else 'group')
            self.assertEqual(group['meta_if_any'], i.meta_if_any)
            if i.is_meta:
                self.assertEqual(sorted(group['groups']), sorted([x.uuid for x in i.groups.all()]))

        # invalid user
        response = self.client.rest_get(f'{url}/invalid')
        self.assertEqual(response.status_code, 404)


    def test_group_create_edit(self) -> None:
        return
        url = f'authenticators/{self.auth.uuid}/users'
        user_dct: typing.Dict[str, typing.Any] = {
            'name': 'test',
            'real_name': 'test real name',
            'comments': 'test comments',
            'state': 'A',
            'is_admin': True,
            'staff_member': True,
            'groups': [self.groups[0].uuid, self.groups[1].uuid],
        }

        # Now, will work
        response = self.client.rest_put(
            url,
            user_dct,
            content_type='application/json',
        )

        # Get user from database and ensure values are correct
        dbusr = self.auth.users.get(name=user_dct['name'])
        self.assertEqual(user_dct['name'], dbusr.name)
        self.assertEqual(user_dct['real_name'], dbusr.real_name)
        self.assertEqual(user_dct['comments'], dbusr.comments)
        self.assertEqual(user_dct['is_admin'], dbusr.is_admin)
        self.assertEqual(user_dct['staff_member'], dbusr.staff_member)
        self.assertEqual(user_dct['state'], dbusr.state)
        self.assertEqual(user_dct['groups'], [i.uuid for i in dbusr.groups.all()])

        self.assertEqual(response.status_code, 200)
        # Returns nothing

        # Now, will fail because name is already in use
        response = self.client.rest_put(
            url,
            user_dct,
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

        # Modify saved user
        user_dct['name'] = 'test2'
        user_dct['real_name'] = 'test real name 2'
        user_dct['comments'] = 'test comments 2'
        user_dct['state'] = 'D'
        user_dct['is_admin'] = False
        user_dct['staff_member'] = False
        user_dct['groups'] = [self.groups[2].uuid]
        user_dct['id'] = dbusr.uuid
        user_dct['password'] = 'test'  # nosec: test password
        user_dct['mfa_data'] = 'mfadata'

        response = self.client.rest_put(
            url,
            user_dct,
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)

        # Get user from database and ensure values are correct
        dbusr = self.auth.users.get(name=user_dct['name'])
        self.assertEqual(user_dct['name'], dbusr.name)
        self.assertEqual(user_dct['real_name'], dbusr.real_name)
        self.assertEqual(user_dct['comments'], dbusr.comments)
        self.assertEqual(user_dct['is_admin'], dbusr.is_admin)
        self.assertEqual(user_dct['staff_member'], dbusr.staff_member)
        self.assertEqual(user_dct['state'], dbusr.state)
        self.assertEqual(user_dct['groups'], [i.uuid for i in dbusr.groups.all()])
        self.assertEqual(cryptoManager().checkHash(user_dct['password'], dbusr.password), True)

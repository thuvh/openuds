# -*- coding: utf-8 -*-
#
# Copyright (c) 2022 Virtual Cable S.L.
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
#    * Neither the name of Virtual Cable S.L. nor the names of its contributors
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
import logging
import typing

from django.db import models

logger = logging.getLogger(__name__)


def compare_dicts(
    expected: typing.Mapping[str, typing.Any],
    actual: typing.Mapping[str, typing.Any],
    ignore_keys: typing.Optional[typing.List[str]] = None,
    ignore_values: typing.Optional[typing.List[str]] = None,
    ignore_keys_startswith: typing.Optional[typing.List[str]] = None,
    ignore_values_startswith: typing.Optional[typing.List[str]] = None,
) -> typing.List[typing.Tuple[str, str]]:
    """
    Compares two dictionaries, returning a list of differences
    """
    ignore_keys = ignore_keys or []
    ignore_values = ignore_values or []
    ignore_keys_startswith = ignore_keys_startswith or []
    ignore_values_startswith = ignore_values_startswith or []

    errors = []

    for k, v in expected.items():
        if k in ignore_keys:
            continue

        if any(k.startswith(ik) for ik in ignore_keys_startswith):
            continue

        if k not in actual:
            errors.append((k, f'Key "{k}" not found in actual'))
            continue

        if actual[k] in ignore_values:
            continue

        if any(actual[k].startswith(iv) for iv in ignore_values_startswith):
            continue

        if v != actual[k]:
            errors.append((k, f'Value for key "{k}" is "{actual[k]}" instead of "{v}"'))

    if errors:
        logger.info('Errors found: %s', errors)

    return errors


def ensure_data(
    item: models.Model,
    dct: typing.Mapping[str, typing.Any],
    ignore_keys: typing.Optional[typing.List[str]] = None,
    ignore_values: typing.Optional[typing.List[str]] = None,
) -> bool:
    """
    Reads model as dict, fix some fields if needed and compares to dct
    """
    db_data = item.__class__.objects.filter(pk=item.pk).values()[0]
    # Remove if id and uuid in db_data, store uuid in id and remove uuid
    if 'id' in db_data and 'uuid' in db_data:
        db_data['id'] = db_data['uuid']
        del db_data['uuid']

    return not compare_dicts(
        dct, db_data, ignore_keys=ignore_keys, ignore_values=ignore_values
    )

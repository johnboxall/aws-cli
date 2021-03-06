# Copyright 2013 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
"""This module has customizations to unify paging paramters.

For any operation that can be paginated, we will:

    * Hide the service specific pagination params.  This can vary across
    services and we're going to replace them with a consistent set of
    arguments.  The arguments will still work, but they are not
    documented.  This allows us to add a pagination config after
    the fact and still remain backwards compatible with users that
    were manually doing pagination.
    * Add a ``--starting-token`` and a ``--max-items`` argument.

"""
import logging
from functools import partial

from awscli.arguments import BaseCLIArgument
from botocore.parameters import StringParameter

logger = logging.getLogger(__name__)


STARTING_TOKEN_HELP = """
<p>A token to specify where to start paginating.  This is the
<code>NextToken</code> from a previously truncated response.</p>
"""

MAX_ITEMS_HELP = """
<p>The total number of items to return.  If the total number
of items available is more than the value specified in
max-items then a <code>NextToken</code> will
be provided in the output that you can use to resume pagination.
"""


def register_pagination(event_handlers):
    event_handlers.register('building-argument-table',
                            unify_paging_params)


def unify_paging_params(argument_table, operation, event_name, **kwargs):
    if not operation.can_paginate:
        # We only apply these customizations to paginated responses.
        return
    logger.debug("Modifying paging parameters for operation: %s", operation)
    _remove_existing_paging_arguments(argument_table, operation)
    parsed_args_event = event_name.replace('building-argument-table.',
                                           'operation-args-parsed.')
    operation.session.register(
        parsed_args_event,
        partial(check_should_enable_pagination,
                list(_get_all_cli_input_tokens(operation))))
    argument_table['starting-token'] = PageArgument('starting-token',
                                                    STARTING_TOKEN_HELP,
                                                    operation,
                                                    parse_type='string')
    # Try to get the pagination parameter type
    limit_param = None
    if 'limit_key' in operation.pagination:
        for param in operation.params:
            if param.name == operation.pagination['limit_key']:
                limit_param = param
                break

    type_ = limit_param and limit_param.type or 'integer'
    if limit_param and limit_param.type not in PageArgument.type_map:
        raise TypeError(('Unsupported pagination type {0} for operation {1}'
                         ' and parameter {2}').format(type_, operation.name,
                                                      limit_param.name))

    argument_table['max-items'] = PageArgument('max-items', MAX_ITEMS_HELP,
                                               operation, parse_type=type_)


def check_should_enable_pagination(input_tokens, parsed_args, parsed_globals, **kwargs):
    for token in input_tokens:
        py_name = token.replace('-', '_')
        if getattr(parsed_args, py_name) is not None:
            # The user has specified a manual (undocumented) pagination arg.
            # We need to automatically turn pagination off.
            logger.debug("User has specified a manual pagination arg. "
                         "Automatically setting --no-paginate.")
            parsed_globals.paginate = False


def _remove_existing_paging_arguments(argument_table, operation):
    for cli_name in _get_all_cli_input_tokens(operation):
        argument_table[cli_name]._UNDOCUMENTED = True


def _get_all_cli_input_tokens(operation):
    # Get all input tokens including the limit_key
    # if it exists.
    tokens = _get_input_tokens(operation)
    for token_name in tokens:
        cli_name = _get_cli_name(operation.params, token_name)
        yield cli_name
    if 'limit_key' in operation.pagination:
        key_name = operation.pagination['limit_key']
        cli_name = _get_cli_name(operation.params, key_name)
        yield cli_name

def _get_input_tokens(operation):
    config = operation.pagination
    tokens = config['input_token']
    if not isinstance(tokens, list):
        return [tokens]
    return tokens


def _get_cli_name(param_objects, token_name):
    for param in param_objects:
        if param.name == token_name:
            return param.cli_name.lstrip('-')


class PageArgument(BaseCLIArgument):
    type_map = {
        'string': str,
        'integer': int,
    }

    def __init__(self, name, documentation, operation, parse_type):
        param = StringParameter(operation, name=name, type=parse_type)
        self._name = name
        self.argument_object = param
        self._name = name
        self._documentation = documentation
        self._parse_type = parse_type

    @property
    def cli_name(self):
        return '--' + self._name

    @property
    def cli_type_name(self):
        return self._parse_type

    @property
    def required(self):
        return False

    @property
    def documentation(self):
        return self._documentation

    def add_to_parser(self, parser):
        parser.add_argument(self.cli_name, dest=self.py_name,
                            type=self.type_map[self._parse_type])

    def add_to_params(self, parameters, value):
        if value is not None:
            parameters[self.py_name] = value

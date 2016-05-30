#!/usr/bin/python
# -*- coding: utf-8 -*-
# pylint: disable=too-many-locals,too-many-arguments,too-many-public-methods
# pylint: disable=fixme, unused-variable, pointless-string-statement
# pylint: disable=too-many-nested-blocks, useless-else-on-loop, protected-access

# Copyright (c) 2015-2016:
#   Frederic Mohier, frederic.mohier@gmail.com
#
# This file is part of (WebUI).
#
# (WebUI) is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# (WebUI) is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with (WebUI).  If not, see <http://www.gnu.org/licenses/>.

"""
    Application data manager
"""

import re
import json
import time
import traceback
from urlparse import urljoin
from datetime import datetime
from logging import getLogger, INFO

from alignak_backend_client.client import Backend, BackendException
from alignak_backend_client.client import BACKEND_PAGINATION_LIMIT, BACKEND_PAGINATION_DEFAULT

# Import all objects we will need
from alignak_webui.objects.item import User, Command, Host
from alignak_webui.backend.glpi_ws_client import Glpi, GlpiException
from alignak_webui.backend.glpi_ws_client import GLPI_PAGINATION_LIMIT, GLPI_PAGINATION_DEFAULT


# Set logger level to INFO, this to allow global application DEBUG logs without being spammed... ;)
logger = getLogger(__name__)
# logger.setLevel(INFO)


class DataManager(object):
    '''
    Base class for all data manager objects
    '''
    id = 1

    """
        Application data manager object
    """

    def __init__(self, backend_endpoint='http://127.0.0.1:5000', glpi=None):
        """
        Create an instance
        """
        # Set a unique id for each DM object
        self.__class__.id += 1

        # Associated backend object
        self.backend_endpoint = backend_endpoint
        self.backend = Backend(backend_endpoint)

        # Associated Glpi backend object
        self.glpi = None
        if glpi:
            self.glpi = Glpi(glpi.get('glpi_ws_backend', None))
            self.glpi_ws_login = glpi.get('glpi_ws_login', None)
            self.glpi_ws_password = glpi.get('glpi_ws_password', None)

        # Backend available objects (filled with objects received from backend)
        # self.backend_available_objets = []

        # Get known objects type from the imported modules
        # Search for classes including an _type attribute
        self.known_classes = []
        for k, v in globals().items():
            if isinstance(globals()[k], type) and '_type' in globals()[k].__dict__:
                self.known_classes.append(globals()[k])
                logger.debug(
                    "Known class %s for object type: %s",
                    globals()[k], globals()[k].getType()
                )

        self.connected = False
        self.logged_in_user = None
        self.connection_message = None
        self.loading = 0
        self.loaded = False

        self.refresh_required = False
        self.refresh_done = False

        self.updated = datetime.utcnow()

    def __repr__(self):
        return ("<DM, id: %s, objects count: %d, user: %s, updated: %s>") % (
            self.id,
            self.get_objects_count(),
            self.get_logged_user().get_username() if self.get_logged_user() else 'Not logged in',
            self.updated
        )

    ##
    # Connected user
    ##
    def user_login(self, username, password=None, load=True):
        """
        Set the data manager user

        If password is provided, use the backend login function to authenticate the user

        If no password is provided, the username is assumed to be an authentication token and we
        use the backend connect function.
        """
        logger.info("user_login, connection requested: %s, load: %s", username, load)

        self.connection_message = _('Backend connecting...')
        if not password:
            # Set backend token (no login request).
            # Do not include the token in the application logs !
            logger.debug("Update backend token")
            self.backend.token = username
            self.connected = True
            self.connection_message = _('Backend connected')
            # Load data if load required...
            if load:
                self.load(reset=True)
            return self.connected

        try:
            # Backend real login
            logger.info("Requesting backend authentication, username: %s", username)
            self.connected = self.backend.login(username, password)
            if self.connected:
                self.connection_message = _('Connection successful')

                # Fetch the logged-in user
                users = self.find_object(
                    'contact', {'where': {'token': self.backend.token}}
                )
                # Tag user as authenticated
                users[0].authenticated = True
                self.logged_in_user = users[0]

                # Get total objects count from the backend
                objects_count = self.get_objects_count(refresh=True, log=True)

                # Load data if load required...
                if load:
                    self.load(reset=True)
            else:
                self.connection_message = _('Backend connection refused...')
        except BackendException as e:  # pragma: no cover, should not happen
            logger.warning("configured applications backend is not available!")
            self.connection_message = e.message
            self.connected = False
        except Exception as e:  # pragma: no cover, should not happen
            logger.warning("User login exception: %s", str(e))
            logger.error("traceback: %s", traceback.format_exc())

        logger.info("user_login, connection message: %s", self.connection_message)
        return self.connected

    def user_logout(self):
        """
        Logout the data manager user. Do not log-out from the backend. Need to reset the
        datamanager to do it.
        """
        self.logged_in_user = None

    def get_logged_user(self):
        """
        Get the current logged in user
        """
        return self.logged_in_user

    ##
    # Find objects and load objects cache
    ##
    def find_object(self, object_type, params=None, all_elements=False):
        """
        Find an object ...

        Search in internal objects cache for an object matching the required parameters

        If params is a string, it is considered to be an object id and params
        is modified to {'_id': params}.

        Else, params is a dictionary of key/value to find a matching object in the objects cache
        If no objects are found in the cache, params is user to 'get' objects from the backend.

        Default behavior is to search in the backend if objects are not found in the cache. Call
        with backend=False to search only in local cache.

        If the backend search is successful, a new object is created if it exists a class in the
        imported modules (presumably alignak_webui.objects.item) which contains a 'bo_type' property
        and this property is valued as 'object_type'.

        Returns an array of matching objects
        """
        logger.debug("find_object, self: %s, updated:%s", self, self.updated)
        logger.debug("find_object, %s, params: %s", object_type, params)

        # -----------------------------------------------------------------------------------------
        # TODO: manage parameters like:
        # {'sort': '-opening_date', 'where': u'{"service_name": "userservice_1"}'}
        # -> ignore sort, ... but take car of 'where' to search in the cache!
        # -----------------------------------------------------------------------------------------
        # if params is None:
        # params = {'page': 0, 'max_results': BACKEND_PAGINATION_LIMIT}

        unique_element = False
        if isinstance(params, basestring):
            params = {'where': {'_id': params}}
            unique_element = True
            logger.debug("find_object, %s, params: %s", object_type, params)

        items = []

        # Update backend search parameters
        if params is None:
            params = {'page': 0, 'max_results': BACKEND_PAGINATION_LIMIT}
        if 'where' in params:
            params['where'] = json.dumps(params['where'])
        if 'embedded' in params:
            params['embedded'] = json.dumps(params['embedded'])
        if 'where' not in params:
            params['where'] = {}
        if 'page' not in params:
            params['page'] = 0
        if 'max_results' not in params:
            params['max_results'] = BACKEND_PAGINATION_LIMIT
        logger.debug(
            "find_object, search in the backend for %s: parameters=%s", object_type, params
        )

        try:
            if all_elements:
                result = self.backend.get_all(object_type, params=params)
            else:
                result = self.backend.get(object_type, params=params)
        except BackendException as e:  # pragma: no cover, simple protection
            logger.warning("find_object, backend exception: %s", str(e))
            return items

        logger.debug(
            "find_object, search result for %s: result=%s", object_type, result
        )
        if result['_status'] != 'OK':  # pragma: no cover, should not happen
            error = []
            if "content" in result:
                error.append(result["content"])
            if "_issues" in result:
                error.append(result["_issues"])
            logger.warning("find_object, %s: %s, not found: %s", object_type, params, error)
            raise ValueError(
                '%s, where %s was not found in the backend, error: %s' % (
                    object_type, params, error
                )
            )

        if not result['_items']:  # pragma: no cover, should occur rarely
            if items:
                logger.debug(
                    "find_object, no data in backend, found in the cache: %s: %s",
                    object_type, items
                )
                return items
            logger.debug(
                "find_object, %s: %s: not found: %s", object_type, params, result
            )
            raise ValueError(
                '%s, %s was not found in the cache nor in the backend' % (
                    object_type, params['where']
                )
            )

        logger.debug("find_object, found in the backend: %s: %s", object_type, result['_items'])
        for item in result['_items']:
            # Find "Backend object type" classes in file imported modules ...
            for k, v in globals().items():
                if isinstance(globals()[k], type) and '_type' in globals()[k].__dict__:
                    if globals()[k].getType() == object_type:
                        # Create a new object
                        bo_object = globals()[k](item)
                        items.append(bo_object)
                        self.updated = datetime.utcnow()
                        logger.debug("find_object, created: %s", bo_object)
                        break
            else:  # pragma: no cover, should not happen
                # No break, so not found a relative class!
                logger.error("find_object, %s class not found for: %s", object_type, item)

        return items

    def load(self, reset=False, refresh=False):
        """
            Load data in the data manager objects

            If reset is set, then all the existing objects are deleted and then created from
            scratch (first load ...). Else, existing objects are updated and new objects are
            created.

            Get all the users (related to current logged-in user)
            Get all the user services (related to current logged-in user)
            Get all the relations between users and services
            Get the most recent sessions for each user service

            :returns: the number of newly created objects
        """
        if not self.get_logged_user():
            logger.error("load, must be logged-in before loading")
            return False

        if self.loading > 0:  # pragma: no cover, protection if application shuts down ...
            logger.error("load, already loading: trial: %d", self.loading)
            if self.loading < 3:
                self.loading += 1
                return False
            logger.error("load, already loading: reset counter")
            self.loading = 0

        logger.debug("load, start loading: %s for %s", self, self.get_logged_user())
        logger.debug(
            "load, start as administrator: %s", self.get_logged_user().is_administrator()
        )
        start = time.time()

        if reset:
            logger.warning("Objects cache reset")
            self.reset(logout=False)

        self.loading += 1
        self.loaded = False

        # Get internal objects count
        objects_count = self.get_objects_count()
        logger.debug("Load, start, objects in cache: %d", objects_count)

        # -----------------------------------------------------------------------------------------
        # Get all users if current user is an administrator
        # -----------------------------------------------------------------------------------------
        self.get_users()

        # -----------------------------------------------------------------------------------------
        # Get all commands
        # -----------------------------------------------------------------------------------------
        commands = self.get_commands()

        # -----------------------------------------------------------------------------------------
        # Get all hosts
        # -----------------------------------------------------------------------------------------
        hosts = self.get_hosts()

        # Get internal objects count
        new_objects_count = self.get_objects_count()
        logger.debug("Load, end, objects in cache: %d", new_objects_count)

        logger.warning(
            "Data manager load (%s), new objects: %d,  duration: %s",
            refresh, new_objects_count - objects_count, (time.time() - start)
        )

        if new_objects_count > objects_count:
            self.require_refresh()

        self.loaded = True
        self.loading = 0
        return new_objects_count - objects_count

    def reset(self, logout=False):
        """
        Reset data in the data manager objects
        """
        logger.info("Data manager reset...")

        # Clean internal objects cache
        for known_class in self.known_classes:
            logger.info("Cleaning %s cache...", known_class.getType())
            known_class.cleanCache()

        if logout:
            self.backend.logout()
            self.user_logout()

        self.loaded = False
        self.loading = 0
        self.refresh_required = True

    def require_refresh(self):
        '''
        Require an immediate refresh
        '''
        self.refresh_required = True
        self.refresh_done = False

    def get_objects_count(self, object_type=None, refresh=False, log=False, search=None):
        '''
        Get the count of the objects stored in the data manager cache

        If an object_type is specified, only returns the count for this object type

        If refresh is True, get the total count from the backend. This is only useful if total
        count is required...

        If log is set, an information log is made
        '''
        log_function = logger.debug
        if log:
            log_function = logger.info

        if object_type:
            for known_class in self.known_classes:
                if object_type == known_class.getType():
                    objects_count = known_class.getCount()
                    log_function(
                        "get_objects_count, currently %d cached %ss",
                        objects_count, object_type
                    )
                    if refresh:
                        if hasattr(known_class, '_total_count'):
                            objects_count = known_class.getTotalCount()
                            log_function(
                                "get_objects_count, got _total_count attribute: %d",
                                objects_count
                            )
                        else:
                            objects_count = self.count_objects(object_type, search=search)

                        log_function(
                            "get_objects_count, currently %d total %ss for %s",
                            objects_count, object_type, search
                        )
                    return objects_count
            else:  # pragma: no cover, should not happen
                logger.warning("count_objects, unknown object type: %s", object_type)
                return 0

        objects_count = 0
        for known_class in self.known_classes:
            count = known_class.getCount()
            log_function(
                "get_objects_count, currently %d cached %ss",
                count, known_class.getType()
            )
            if refresh:
                count = self.count_objects(known_class.getType(), search=search)
                log_function(
                    "get_objects_count, currently %d total %ss for %s",
                    count, known_class.getType(), search
                )
            objects_count += count

        log_function("get_objects_count, currently %d elements", objects_count)
        return objects_count

    ##
    #
    # Elements add, delete, update, ...
    ##
    def count_objects(self, object_type, search=None):
        """
        Request objects from the backend to pick-up total records count.
        Make a simple request for 1 element and we will get back the total count of elements

        search is a dictionary of key / value to search for

        If log is set, an information log is made
        """
        total = 0

        params = {
            'page': 0, 'max_results': 1
        }
        if search is not None:
            params['where'] = json.dumps(search)

        # Request objects from the backend ...
        try:
            resp = self.backend.get(object_type, params)
            logger.debug("count_objects %s: %s", object_type, resp)

            # Total number of records
            if '_meta' in resp:
                total = int(resp['_meta']['total'])
        except BackendException as e:
            logger.warning(
                "count_objects exception for object type: %s: %s",
                object_type, e.message
            )

        return total

    def add_object(self, object_type, data=None, files=None):
        """ Add an element """
        logger.info("add_object, request to add a %s: data: %s", object_type, data)

        # Do not set header to use the client default behavior:
        # - set headers as {'Content-Type': 'application/json'}
        # - encode provided data to JSON
        headers = None
        if files:
            logger.info("add_object, request to add a %s with files: %s", object_type, files)
            # Set header to disable client default behavior
            headers = {'Content-type': 'multipart/form-data'}

        try:
            result = self.backend.post(object_type, data=data, files=files, headers=headers)
            logger.debug("add_object, response: %s", result)
            if result['_status'] != 'OK':
                logger.warning("add_object, error: %s", result)
                return None

            self.find_object(object_type, result['_id'])
        except BackendException as e:
            logger.error("add_object, backend exception: %s", str(e))
            return None
        except ValueError as e:  # pragma: no cover, should never happen
            logger.warning("add_object, error: %s", str(e))
            return None

        return result['_id']

    def delete_object(self, object_type, element):
        """
        Delete an element
        - object_type is the element type
        - element may be a string. In this case it is considered to be the element id
        """
        logger.info("delete_object, request to delete the %s: %s", object_type, element)

        if isinstance(element, basestring):
            object_id = element
        else:
            object_id = element.get_id()

        try:
            # Get most recent version of the element
            items = self.find_object(object_type, object_id)
            element = items[0]
        except ValueError:  # pragma: no cover, should never happen
            logger.warning("delete_object, object %s, _id=%s not found", object_type, object_id)
            return False

        try:
            # Request deletion
            headers = {'If-Match': element['_etag']}
            endpoint = '/'.join([object_type, object_id])
            logger.info("delete_object, endpoint: %s", endpoint)
            result = self.backend.delete(endpoint, headers)
            logger.debug("delete_object, response: %s", result)
            if result['_status'] != 'OK':  # pragma: no cover, should never happen
                error = []
                if "content" in result:
                    error.append(result["content"])
                if "_issues" in result:
                    error.append(result["_issues"])
                    for issue in result["_issues"]:
                        error.append(result["_issues"][issue])
                logger.warning("delete_object, error: %s", error)
                return False
        except BackendException as e:  # pragma: no cover, should never happen
            logger.error("delete_object, backend exception: %s", str(e))
            return False
        except ValueError as e:  # pragma: no cover, should never happen
            logger.warning("delete_object, not found %s: %s", object_type, element)
            return False

        try:
            # Try to get most recent version of the element
            items = self.find_object(object_type, object_id)
        except ValueError:
            logger.info("delete_object, object deleted: %s, _id=%s", object_type, object_id)
            # Object deletion
            element._delete()

        return True

    def update_object(self, object_type, element, data):
        """
        Update an element
        - object_type is the element type
        - element may be a string. In this case it is considered to be the element id
        """
        logger.info("update_object, request to update the %s: %s", object_type, element)

        if isinstance(element, basestring):
            object_id = element
        else:
            object_id = element.get_id()

        try:
            # Get most recent version of the element
            items = self.find_object(object_type, object_id)
            element = items[0]
        except ValueError:
            logger.warning("update_object, object %s, _id=%s not found", object_type, object_id)
            return False

        try:
            # Request update
            headers = {'If-Match': element['_etag']}
            endpoint = '/'.join([object_type, object_id])
            logger.info("update_object, endpoint: %s, data: %s", endpoint, data)
            result = self.backend.patch(endpoint, data, headers)
            logger.debug("update_object, response: %s", result)
            if result['_status'] != 'OK':  # pragma: no cover, should never happen
                error = []
                if "content" in result:
                    error.append(result["content"])
                if "_issues" in result:
                    error.append(result["_issues"])
                    for issue in result["_issues"]:
                        error.append(result["_issues"][issue])
                logger.warning("update_object, error: %s", error)
                return False

            items = self.find_object(object_type, object_id)
            logger.info("update_object, updated: %s", items[0])
        except BackendException as e:  # pragma: no cover, should never happen
            logger.error("update_object, backend exception: %s", str(e))
            return False
        except ValueError:  # pragma: no cover, should never happen
            logger.warning("update_object, not found %s: %s", object_type, element)
            return False

        return True

    ##
    # Hosts
    ##
    def get_hosts(self, search=None):
        """ Get a list of all hosts. """
        if search is None:
            search = {}
        if 'embedded' not in search:
            search.update({'embedded': {'userservice_session': 1, 'user': 1}})

        try:
            logger.info("get_hosts, search: %s", search)
            items = self.find_object('host', search)
            logger.info("get_hosts, got: %d elements, %s", len(items), items)
            return items
        except ValueError:
            logger.debug("get_hosts, none found")

        return []

    def get_host(self, search):
        """ Get a host by its id (default). """

        if isinstance(search, basestring):
            search = {'max_results': 1, 'where': {'_id': search}}
        elif 'max_results' not in search:
            search.update({'max_results': 1})

        items = self.get_hosts(search=search)
        return items[0] if items else None

    def get_hosts_synthesis(self, elts=None):
        """
        Hosts synthesis by status
        """
        if elts:
            hosts = [item for item in elts if item.getType() == 'host']
        else:
            # Use internal object list ...
            hosts = [item for _id, item in Host.getCache().items()]
        logger.debug("get_hosts_synthesis, %d hosts", len(hosts))

        synthesis = dict()
        synthesis['nb_elts'] = len(hosts)
        synthesis['nb_problem'] = 0
        if hosts:
            for state in 'up', 'unreachable', 'down', 'unknown':
                synthesis['nb_' + state] = sum(
                    1 for host in hosts if host.get_status().lower() == state
                )
                synthesis['pct_' + state] = round(
                    100.0 * synthesis['nb_' + state] / synthesis['nb_elts'], 2
                )
        else:
            for state in 'up', 'unreachable', 'down', 'unknown':
                synthesis['nb_' + state] = 0
                synthesis['pct_' + state] = 0

        logger.debug("get_hosts_synthesis: %s", synthesis)
        return synthesis

    def add_host(self, data, files):
        """
        Add a host.
        Update the concerned session internal objects.
        """

        return self.add_object('host', data, files)

    ##
    # Commands
    ##
    def get_commands(self, search=None):
        """ Get a list of all commands. """
        if search is None:
            search = {}
        if 'embedded' not in search:
            search.update({'embedded': {'userservice_session': 1, 'user': 1}})

        try:
            logger.info("get_commands, search: %s", search)
            items = self.find_object('command', search)
            return items
        except ValueError:
            logger.debug("get_commands, none found")

        return []

    def get_command(self, search):
        """ Get a command by its id. """

        if isinstance(search, basestring):
            search = {'max_results': 1, 'where': {'_id': search}}
        elif 'max_results' not in search:
            search.update({'max_results': 1})

        items = self.get_commands(search=search)
        return items[0] if items else None

    def get_commands_synthesis(self, elts=None):
        """
        Documents synthesis by status
        """
        if elts:
            commands = [item for item in elts if item.getType() == 'command']
        else:
            # Use internal object list ...
            commands = [item for _id, item in Command.getCache().items()]
        logger.debug("get_commands_synthesis, %d commands", len(commands))

        synthesis = dict()
        synthesis['nb_elts'] = len(commands)
        if commands:
            for state in 'attached', 'empty', 'problem', 'unknown':
                synthesis['nb_' + state] = sum(
                    1 for command in commands if command.get_status().lower() == state
                )
                synthesis['pct_' + state] = round(
                    100.0 * synthesis['nb_' + state] / synthesis['nb_elts'], 2
                )
        else:
            for state in 'attached', 'empty', 'problem', 'unknown':
                synthesis['nb_' + state] = 0
                synthesis['pct_' + state] = 0

        logger.debug("get_commands_synthesis: %s", synthesis)
        return synthesis

    def add_command(self, data):  # pragma: no cover, not yet implemented!
        """
        Add a command.
        Update the concerned session internal objects.
        """

        return self.add_object('command', data)

    ##
    # Users
    ##
    def get_users(self, search=None):
        """ Get a list of known users """
        if not self.get_logged_user().is_administrator():
            return [self.get_logged_user()]

        try:
            logger.info("get_users, search: %s", search)
            items = self.find_object('contact', search)
            return items
        except ValueError:
            logger.debug("get_users, none found")

        return []

    def get_user(self, search):
        """
        Get a user by its id or a search pattern
        """
        if isinstance(search, basestring):
            search = {'max_results': 1, 'where': {'_id': search}}
        elif 'max_results' not in search:
            search.update({'max_results': 1})

        items = self.get_users(search=search)
        return items[0] if items else None

    def add_user(self, data):
        """ Add a user. """

        return self.add_object('user', data)

    def delete_user(self, user):
        """ Delete a user.

        Cannot delete the currently logged in user ...

        If user is a string it is assumed to be the User object id to be searched in the objects
        cache.

        :param user: User object instance
        :type user: User (or string)

        Returns True/False depending if user closed
        """
        logger.info("delete_user, request to delete the user: %s", user)

        if isinstance(user, basestring):
            user = self.get_user(user)
            if not user:
                return False

        user_id = user.get_id()
        if user_id == self.get_logged_user().get_id():
            logger.warning("delete_user, request to delete the current logged-in user: %s", user_id)
            return False

        return self.delete_object('user', user)
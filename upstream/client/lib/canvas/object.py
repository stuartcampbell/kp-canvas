#
# Copyright (C) 2013-2016   Ian Firns   <firnsy@kororaproject.org>
#                           Chris Smart <csmart@kororaproject.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import hashlib
import json
import os
import urllib.request

from pykickstart.base import KickstartCommand
from pykickstart.parser import Script
import pykickstart.constants

import canvas.utilities

from canvas.set import CanvasSet

class ErrorInvalidObject(Exception):
    def __init__(self, reason, code=0):
        self.reason = reason.lower()
        self.code = code

        self._db = None

    def __str__(self):
        return 'error: {0}'.format(str(self.reason))


class Object(object):
    """ A Canvas object that represents a template Object. """

    # CONSTANTS
    ACTIONS_ALL = ['copy', 'extract',
                   'execute', 'execute-command', 'ks-command',
                   'ks-post', 'ks-pre', 'ks-pre-install', 'ks-traceback']

    ACTIONS_KS_ONLY = ['ks-command', 'ks-post', 'ks-pre', 'ks-pre-install', 'ks-traceback']

    MAP_OBJ_STRING_TO_SCRIPT_TYPE = {
        'ks-post':          pykickstart.constants.KS_SCRIPT_POST,
        'ks-pre':           pykickstart.constants.KS_SCRIPT_PRE,
        'ks-pre-install':   pykickstart.constants.KS_SCRIPT_PREINSTALL,
        'ks-traceback':     pykickstart.constants.KS_SCRIPT_TRACEBACK
    }

    MAP_SCRIPT_TYPE_TO_OBJ_STRING = {
        pykickstart.constants.KS_SCRIPT_PRE:        'ks-pre',
        pykickstart.constants.KS_SCRIPT_POST:       'ks-post',
        pykickstart.constants.KS_SCRIPT_TRACEBACK:  'ks-traceback',
        pykickstart.constants.KS_SCRIPT_PREINSTALL: 'ks-pre-install'
    }

    def __init__(self, *args, **kwargs):
        self._name = None
        self._xsum = None
        self._source = None
        self._data = None
        self._actions = []

        self._cache_dir = os.getenv('CANVAS_CACHE_DIR', '/var/cache/canvas')

        if kwargs:
            self._name     = kwargs.get('name', self._name)
            self._xsum     = kwargs.get('xsum', self._xsum)
            self._source   = kwargs.get('source', self._source)
            self._data     = kwargs.get('data', self._data)
            self._actions  = kwargs.get('actions', self._actions)
            self._template = kwargs.get('template', None)

            # check if we've got a data_file to read data from
            if kwargs.get('data_file', None) is not None:
                try:
                    with open(kwargs.get('data_file'), 'r') as f:
                        self._data = f.read()

                    self._source = 'raw'

                except:
                    raise ErrorInvalidObject('unable to read data-file')

            elif self._data is not None:
                self._source = 'raw'

        elif args:
            if len(args) > 1:
                raise ErrorInvalidObject('too many positional arguments')

            elif (isinstance(args[0], Script)):
                self._from_ks_script(args[0])

            elif (isinstance(args[0], KickstartCommand)):
                self._from_ks_command(args[0])

            # parse the dict form, the most common form and directly
            # relates to the json structures returned by canvas server
            elif (isinstance(args[0], dict)):
                self._name     = args[0].get('name', self._name)
                self._xsum     = args[0].get('checksum', {}).get('sha256', None)
                self._actions  = args[0].get('actions', self._actions)
                self._source   = args[0].get('source', self._source)
                self._data     = args[0].get('data', self._data)
                self._template = args[0].get('template', None)

        # calculate checksum if not defined
        if self._xsum is None:
            if (self._data is None and self._source == 'raw'):
                raise ErrorInvalidObject('checksum defined without data')
            elif self._data:
                self._xsum = hashlib.sha256(self._data.encode('utf-8')).hexdigest()

        # process actions
        actions = []
        for a in self._actions:
            if isinstance(a, str):
                t, p = a.split(":", 1)

                if t not in Object.ACTIONS_ALL:
                    continue

                if t == 'copy':
                    actions.append({'type': t, 'path': p})

                elif t == 'execute':
                    actions.append({'type': t})

                elif t == 'execute-command':
                    actions.append({'type': t, 'command': p})

                elif t == 'extract':
                    actions.append({'type': t, 'path': p})

            elif isinstance(a, dict):
                if 'type' in a and a['type'] in Object.ACTIONS_ALL:
                    actions.append(a)

                else:
                    print('STRIPPING', a)

        self._actions = actions


    def __eq__(self, other):
        if isinstance(other, Object):
            if (self._xsum and other._xsum):
                return (self._xsum == other._xsum)
            else:
                return (self._name == other._name)
        else:
            return False

    def __hash__(self):
        return self._name + self._xsum

    def __ne__(self, other):
        return (not self.__eq__(other))

    def __repr__(self):
        if self._xsum is None:
            xsum = "unknown"

        else:
            xsum = self._xsum[0:7]

        return 'Object: {0} (xsum: {1}, actions: {2})'.format(self._name, xsum, len(self._actions))

    def _cached_object_path(self):
        filename = '{0}-{1}'.format(self._name, os.path.basename(self._source))
        return os.path.join(self._cache_dir, filename)

    def _from_ks_command(self, command):
        self._data = str(command)
        self._xsum = hashlib.sha256(self._data.encode('utf-8')).hexdigest()
        self._name = "ks-command-{0}".format(self._xsum[0:7])

        action = {
            'type':     'ks-command',
            'priority': command.writePriority,
            'command':  command.currentCmd,
        }

        self._actions = [action]

    def _from_ks_script(self, script):
        self._data = script.script
        self._xsum = hashlib.sha256(self._data.encode('utf-8')).hexdigest()
        self._name = "ks-script-{0}".format(self._xsum[0:7])

        type = self.MAP_SCRIPT_TYPE_TO_OBJ_STRING[script.type]

        action = {
            'type':          type,
            'interp':        script.interp,
            'in_chroot':     script.inChroot,
            'line_no':       script.lineno,
            'error_on_fail': script.errorOnFail,
        }

        self._actions = [action]

    #
    # PROPERTIES
    @property
    def actions(self):
        return self._actions

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, data):
        self._data = data
        self._source = 'raw'
        self._xsum = hashlib.sha256(self._data.encode('utf-8')).hexdigest()

    @property
    def name(self):
        return self._name

    @property
    def source(self):
        return self._source

    @source.setter
    def source(self, source):
        self._source = source

        if source != 'raw':
            self._data = None

    @property
    def template(self):
        return self._template

    @property
    def xsum(self):
        return self._xsum

    @xsum.setter
    def xsum(self, xsum):
        self._xsum = xsum

    #
    # PUBLIC METHODS
    def add_action(self, action):
        pass

    def apply_actions(self):
        nonks_actions = [a for a in self.actions if a['type'] not in Object.ACTIONS_KS_ONLY]

        for a in nonks_actions:
            if a['type'] == 'copy':
                print('object copying ...')
                canvas.utilities.copy_file(self._cached_object_path(), a['path'])

            elif a['type'] == 'execute':
                print('object executing ...')
                canvas.utilities.execute_command(self._cached_object_path())

            elif a['type'] == 'execute-command':
                print('executing command ...')
                canvas.utilities.execute_command(a['command'])

            elif a['type'] == 'extract':
                print('object extracting ...')
                canvas.utilities.extract_file(self._cached_object_path(), a['path'])

    def download(self, force=False):
        if self._source == 'raw':
            return

        cached_object_path = self._cached_object_path()

        if os.path.exists(cached_object_path):
            return

        elif not os.path.exists(self._cache_dir):
            os.mkdir(self._cache_dir)

        urllib.request.urlretrieve(self._source, cached_object_path)

    def get_ks_command(self):
        if len(self._actions) != 1:
            return None

        action = self._actions[0]
        return action.get('command', None)

    def get_ks_command_priority(self):
        if len(self._actions) != 1:
            return 0

        action = self._actions[0]
        return action.get('priority', None)

    def is_downloaded(self):
        if self._source != 'raw':
            return os.path.exists(self._cached_object_path)

        else:
            return True

    def is_complete(self):
        return self._xsum and ((self._source != 'raw') or (self._data is not None))

    def is_ks_command(self):
        if len(self._actions) != 1:
            return None

        action = self._actions[0]
        type = action.get('type', '')

        # check we we're a ks-command
        return type == 'ks-command'

    def is_ks_script(self):
        if len(self._actions) != 1:
            return None

        action = self._actions[0]
        type = action.get('type', '')

        # check we we're a ks-script
        return type in self.MAP_OBJ_STRING_TO_SCRIPT_TYPE.keys()

    def to_kickstart(self):
        if len(self._actions) != 1:
            return ''

        action = self._actions[0]
        type = action.get('type', '')

        if type == 'ks-command':
            return self.data

        elif type in self.MAP_OBJ_STRING_TO_SCRIPT_TYPE.keys():
            header = ''
            footer = "%end\n"

            if type == 'ks-post':
                header = '%post'

                if not action.get('in_chroot', True):
                    header += ' --nochroot'

                if action.get('interp', '/bin/sh') != '/bin/sh':
                    header += ' --interpreter={0}'.format(action.get('interp'))

            elif type == 'ks-pre':
                header = '%pre'

                if action.get('interp', '/bin/sh') != '/bin/sh':
                    header += ' --interpreter={0}'.format(action.get('interp'))

            elif type == 'ks-pre-install':
                header = '%preinstall'

                if action.get('interp', '/bin/sh') != '/bin/sh':
                    header += ' --interpreter={0}'.format(action.get('interp'))

            elif type == 'ks-traceback':
                header = '%traceback'

                if action.get('interp', '/bin/sh') != '/bin/sh':
                    header += ' --interpreter={0}'.format(action.get('interp'))

            return header + "\n" + self.data + footer

        return ''

    def to_ks_script(self):
        # kickstart scripts only have a single action
        if len(self._actions) != 1:
            return None

        action = self._actions[0]
        type = action.get('type', '')

        # check we contain ks-script
        if type not in self.MAP_OBJ_STRING_TO_SCRIPT_TYPE.keys():
            return None

        return pykickstart.parser.Script(self._data,
            errorOnFail = action.get('error_on_fail', None),
            interp      = action.get('interp', None),
            inChroot    = action.get('in_chroot', None),
            type        = self.MAP_OBJ_STRING_TO_SCRIPT_TYPE[type]
        )


    def to_object(self):
        return {
            'name': self._name,
            'source': self._source,
            'data': self._data,
            'checksum': {
                'sha256': self._xsum
            },
            'actions': self._actions
        }

    def to_json(self):
        return json.dumps(self.to_object(), separators=(',', ':'), sort_keys=True)

class ObjectSet(CanvasSet):
    def __init__(self, initvalue=()):
        CanvasSet.__init__(self, initvalue)

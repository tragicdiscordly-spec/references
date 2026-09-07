# This file is part of BeeRef.
#
# BeeRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# BeeRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with BeeRef.  If not, see <https://www.gnu.org/licenses/>.

MENU_SEPARATOR = 0

menu_structure = [
    {
        'menu': '&File',
        'items': [
            'insert_images', 'open',
            {'menu': 'Open &Recent', 'items': '_build_recent_files'},
            MENU_SEPARATOR, 'save', 'save_as', 'new_scene',
            MENU_SEPARATOR, 'quit',
        ],
    },
    {
        'menu': '&Edit',
        'items': [
            'undo', 'redo', MENU_SEPARATOR,
            'cut', 'copy', 'paste', 'delete',
            MENU_SEPARATOR, 'select_all', 'deselect_all',
        ],
    },
    {
        'menu': '&Images',
        'items': ['change_opacity', 'grayscale'],
    },
]

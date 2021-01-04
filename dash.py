#
# Copyright 2020 Thomas Engel <thomas.engel.web@gmail.de>
# License:  same as zim (gpl)
#
# DESCRIPTION:
#
# Zim plugin to search and execute menu entries via dialog.
#
# CHANGELOG:
#
# 2020-11-22 1st working version
# 2020-11-23 Improved usability
#            - Selecting item in autocomplete list will directly execute
# 2020-12-13 Improved code and usability
#            - Removed '{'-keybinding used to open dash.
# 2020-12-29 Added history support
# 2021-01-01 Improved usability
#            - Popups can now be reopened using arrow keys.
# 2021-01-03 Improved usability
#            - History can now be controlled using buttons

import json
import logging
from collections import deque

import gi
import os

gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, Gtk

from zim.actions import action
from zim.config import XDG_DATA_HOME
from zim.gui.mainwindow import MainWindowExtension
from zim.gui.widgets import Dialog
from zim.plugins import PluginClass


logger = logging.getLogger('zim.plugins.dashboard')

WORKING_DIR = str(XDG_DATA_HOME.subdir(('zim', 'plugins')))
HISTORY_FILE = os.path.join(WORKING_DIR, 'dash.json')
HISTORY_SIZE_DEFAULT = 5
HISTORY_SIZE_MIN = 1
HISTORY_SIZE_MAX = 99
css = b"""
.small-button {
  min-height: 0px;
  padding-bottom: 0px;
  padding-top: 0px;
}
"""

class DashPlugin(PluginClass):
    plugin_info = {
        'name': _('Dash'),  # T: plugin name
        'description': _('This plugin opens a search dialog to allow quickly '
                         'executing menu entries.'),  # T: plugin description
        'author': 'Thomas Engel <thomas.engel.web@gmail.com>',
        'help': 'Plugins:Dash',
    }

    plugin_preferences = (
        ('history_size', 'int', _('History size'), HISTORY_SIZE_DEFAULT, (HISTORY_SIZE_MIN, HISTORY_SIZE_MAX)),
    )


class DashMainWindowExtension(MainWindowExtension):
    """ Listener for the show dash dialog shortcut. """

    def __init__(self, plugin, window):
        MainWindowExtension.__init__(self, plugin, window)
        self.window = window

    def _init_store(self):
        """ Construct the store containing all menu-items and associated actions. """
        store = Gtk.ListStore(str, object)
        for label, action in ZimMenuBarCrawler().run(self.window.menubar).items():
            store.append((label, action))
        return store

    @action('', accelerator='<alt>x', menuhints='accelonly')
    def do_show_dash_dialog(self):
        store = self._init_store()
        history_whitelist = [item[0] for item in store]
        history = ZimDashHistory(HISTORY_FILE, self.plugin.preferences["history_size"], history_whitelist)
        dialog = ZimDashDialog(self.window, store, history)
        if dialog.run() == Gtk.ResponseType.OK:
            dialog.action()
            # The return value is only relevant for the on_key_press_event function and makes sure that the
            # pressed key is not processed any further.
            return True


class ZimDashHistory:

    def __init__(self, history_file, history_size, history_whitelist):
        self.history_file = history_file
        self.history_whitelist = history_whitelist
        self.history_size = history_size
        self.history = deque(self._load(), maxlen=history_size)

    def _load(self):
        if not os.path.isfile(self.history_file):
            # Either not initialized yet, path does not exist or no permission to write history file.
            logger.warning("ZimDashPlugin: History file does not exist!")
            return []
        try:
            with open(self.history_file) as input_file:
                data = json.load(input_file)
            # Remove any entries which are not whitelisted
            history_entries =  [entry for entry in data["history"] if entry in self.history_whitelist]
            logger.info("ZimDashPlugin: Successfully loaded history file!")
            return history_entries
        except (Exception, json.decoder.JSONDecodeError) as err:
            # Either invalid format, path does not exist or no permission to read history file.
            logger.error("ZimDashPlugin: Error reading history file!")
            logger.exception(err)
            return []

    def _save(self):
        try:
            with open(self.history_file, "w") as output_file:
                json.dump({"history": list(self.history)}, output_file)
            logger.info("ZimDashPlugin: Successfully updated history file!")
        except Exception as err:
            # Either path does not exist or no permission to write history file.
            logger.error("ZimDashPlugin: Error writing history file!")
            logger.exception(err)

    def current(self):
        if not self.history:
            return None
        return self.history[0]

    def next(self):
        if not self.history:
            return None
        self.history.rotate(-1)
        return self.history[0]

    def previous(self):
        if not self.history:
            return None
        self.history.rotate(+1)
        return self.history[0]

    def update(self, new_entry):
        if new_entry in self.history_whitelist:
            # When new entry already in history, delete it and re-add it as first entry
            logger.debug("ZimDashPlugin: Adding new entry to history: {}".format(new_entry))
            self.history = deque(filter(lambda entry: entry != new_entry, self.history), maxlen=self.history_size)
            self.history.appendleft(new_entry)
            self._save()
        else:
            logger.debug("ZimDashPlugin: Updating history failed! Entry not in white list: {}".format(new_entry))


class ZimMenuBarCrawler:
    """ Crawler for Gtk.MenuBar to return all item labels and associated actions in a dictionary. """

    def run(self, menu_bar: Gtk.MenuBar):

        result = {}

        def crawl(container: Gtk.MenuItem, path: str):
            if container.get_submenu():
                for child in container.get_submenu():
                    if hasattr(child, "get_label") and child.get_label():
                        child_path = path + " > " + child.get_label().replace("_", "")
                        crawl(child, child_path)
            else:
                result[path] = container.activate

        for child in menu_bar:
            if hasattr(child, "get_label") and child.get_label():
                crawl(child, child.get_label().replace("_", ""))

        return result


class ZimDashDialog(Dialog):
    """ A search dialog with auto-complete feature. """

    def __init__(self, parent, store, history):
        title = _('Dash')
        Dialog.__init__(self, parent, title)

        self.action = None
        self.store = store
        self.entries = {item[0]: item[1] for item in self.store}  # { label: action }

        self.history = history
        # Indicates whether the user has already selected an entry from history yet.
        self.history_activated = False

        # Configure completion for search field.
        completion = Gtk.EntryCompletion()
        completion.set_model(store)
        completion.set_text_column(0)
        completion.set_minimum_key_length(0)
        completion.connect("match-selected", self.on_match_selected)

        def match_anywhere(_completion, _entrystr, _iter, _data):
            """ Match any part. """
            _modelstr = _completion.get_model()[_iter][0].lower()
            return _entrystr in _modelstr

        completion.set_match_func(match_anywhere, None)

        self.hbox = Gtk.HBox()

        # Add history buttons.
        prev_icon = Gtk.Image.new_from_icon_name("go-previous", Gtk.IconSize.SMALL_TOOLBAR)
        self.btn_history_prev = Gtk.ToolButton.new(prev_icon, "Previous")
        self.btn_history_prev.set_tooltip_text("Select previous entry from history (Ctrl+Shift+Tab)")
        self.btn_history_prev.connect("clicked", lambda widget: self.do_show_previous_history_entry())
        next_icon = Gtk.Image.new_from_icon_name("go-next", Gtk.IconSize.SMALL_TOOLBAR)
        self.btn_history_next = Gtk.ToolButton.new(next_icon, "Next")
        self.btn_history_next.set_tooltip_text("Select next entry from history (Ctrl+Tab)")
        self.btn_history_next.connect("clicked", lambda widget: self.do_show_next_history_entry())

        # Add search field.
        self.txt_search = Gtk.Entry()
        self.txt_search.set_activates_default(True)  # Make ENTER key press trigger the OK button.
        self.txt_search.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, Gtk.STOCK_FIND)
        self.txt_search.set_placeholder_text("Search actions")
        self.txt_search.set_completion(completion)
        self.txt_search.connect("changed", self.do_validate, parent)
        self.txt_search.connect("key-press-event", self.on_key_pressed, parent)

        # Add ok button.
        self.btn_ok = self.get_widget_for_response(response_id=Gtk.ResponseType.OK)
        self.btn_ok.set_can_default(True)
        self.btn_ok.grab_default()
        self.btn_ok.set_sensitive(False)

        # Configure dialog.
        self.set_modal(True)
        self.set_default_size(380, 100)
        self.hbox.pack_start(self.btn_history_prev, False, False, 0)
        self.hbox.pack_start(self.btn_history_next, False, False, 0)
        self.hbox.pack_start(self.txt_search, True, True, 0)
        self.vbox.pack_start(self.hbox, True, True, 0)

        # Set focus to search field
        self.txt_search.grab_focus()

    def on_key_pressed(self, widget, event, data=None):
        """ Listener for gtk.Entry key press events. """
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        shift = event.state & Gdk.ModifierType.SHIFT_MASK
        tab = Gdk.KEY_Tab == event.keyval or Gdk.KEY_ISO_Left_Tab == event.keyval
        if tab and ctrl and not shift:
            self.do_show_next_history_entry()
            return True
        elif tab and ctrl and shift:
            self.do_show_previous_history_entry()
            return True
        elif event.keyval == Gdk.KEY_Up or event.keyval == Gdk.KEY_Down:
            self.txt_search.emit('changed')
            return True

    def on_match_selected(self, completion, model, iter):
        """ Directly close dialog when selecting an entry in the completion list. """
        logger.debug("ZimDashPlugin: Match selected from popup menu: {}".format(model[iter][0]))
        self.txt_search.set_text(model[iter][0])
        if self.do_response_ok():
            self.close()

    def do_show_previous_history_entry(self):
        """ Shows previous history entry in search field, if available """
        history_entry = self.history.previous()
        self.history_activated = True
        logger.debug("ZimDashPlugin: Selected previous entry from history: {}".format(history_entry))
        if history_entry:
            self.txt_search.set_text(history_entry)

    def do_show_next_history_entry(self):
        """ Shows next history entry in search field, if available """
        if not self.history_activated:
            # Makes sure that the first entry of the history is returned the first time
            history_entry = self.history.current()
            self.history_activated = True
        else:
            # Next history entry, if available
            history_entry = self.history.next()
        logger.debug("ZimDashPlugin: Selected next entry from history: {}".format(history_entry))
        if history_entry:
            self.txt_search.set_text(history_entry)

    def do_validate(self, entry, data):
        """ Validating selected text entry and enable/disable ok button. """
        self.btn_ok.set_sensitive(entry.get_text() in self.entries)

    def do_response_ok(self):
        """ Finishing up when activating the ok button. """
        if self.txt_search.get_text() in self.entries:
            self.action = self.entries[self.txt_search.get_text()]
            self.history.update(self.txt_search.get_text())
            self.result = Gtk.ResponseType.OK
            return True
        else:
            logger.error("ZimDashPlugin: Aborting, invalid entry selected: {}".format(self.txt_search.get_text()))

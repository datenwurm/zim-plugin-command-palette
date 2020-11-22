#
# Copyright 2020 Thomas Engel <thomas.engel.web@gmail.de>
# License:  same as zim (gpl)
#
#
# NOTE:
#
# ChangeLog
# 2020-11-22 1st working version
#
# TODO:
# [ ] ...


'''Zim plugin to search and execute menu entries.'''

import logging

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from zim.actions import action
from zim.plugins import PluginClass
from zim.gui.mainwindow import MainWindowExtension
from zim.gui.widgets import Dialog


logger = logging.getLogger('zim.plugins.dashboard')


DEFAULT_DASH_KEY = "{"


class DashPlugin(PluginClass):
    plugin_info = {
        'name': _('Dash'),  # T: plugin name
        'description': _('This plugin opens a search dialog to allow quickly '
                         'executing menu entries.'),  # T: plugin description
        'author': 'Thomas Engel <thomas.engel.web@gmail.com>',
        'help': 'Plugins:Dash',
    }

    plugin_preferences = (
        # key, type, label, default
        ('dash_key', 'string', _('Dash key'), DEFAULT_DASH_KEY),
    )


class DashMainWindowExtension(MainWindowExtension):
    """ Listens for any keystroke and takes action. """

    def __init__(self, plugin, window):
        MainWindowExtension.__init__(self, plugin, window)
        self.plugin = plugin
        self.window = window
        self.connectto(window.pageview.textview, 'key-press-event')

    def _init_store(self):
        """ Construct the store containing all menu-items and associated actions. """
        store = Gtk.ListStore(str, object)
        for label, action in ZimMenuBarCrawler().run(self.window.menubar).items():
            store.append((label, action))
        return store

    def on_key_press_event(self, widget, event):
        """ Catch the dash key and show zim dash dialog. """
        if event.keyval == ord(self.dash_key):
            return self.do_show_dash_dialog()

    @action('', accelerator='<alt>x', menuhints='accelonly')
    def do_show_dash_dialog(self):
        dialog = ZimDashDialog(self.window, self._init_store())
        if dialog.run() == Gtk.ResponseType.OK:
            dialog.action()
            # The return value is only relevant for the on_key_press_event function and makes sure that the
            # pressed key is not processed any further.
            return True

    def _get_dash_key(self):
        return self.plugin.preferences['dash_key']

    dash_key = property(fget=_get_dash_key)


class ZimMenuBarCrawler:
    """ Crawler for Gtk.MenuBar to return all item labels and associated actions in a dictionary. """

    def run(self, menu_bar: Gtk.MenuBar):

        result = {}

        def crawl(container: Gtk.MenuItem, path: str):
            if container.get_submenu():
                for child in container.get_submenu():
                    if isinstance(child, Gtk.ImageMenuItem):
                        child_path = path + " > " + child.get_label().replace("_", "")
                        crawl(child, child_path)
            else:
                result[path] = container.activate

        for child in menu_bar:
            if isinstance(child, Gtk.ImageMenuItem):
                crawl(child, child.get_label().replace("_", ""))

        return result


class ZimDashDialog(Dialog):
    """ A search dialog with auto-complete feature. """

    def __init__(self, parent, store):
        title = _('Zim Dash')
        Dialog.__init__(self, parent, title)

        self.action = None
        self.store = store
        self.entries = {item[0]: item[1] for item in self.store}  # { label: action }

        # Configure completion for search field.
        completion = Gtk.EntryCompletion()
        completion.set_model(store)
        completion.set_text_column(0)

        def match_anywhere(_completion, _entrystr, _iter, _data):
            """ Match any part. """
            _modelstr = _completion.get_model()[_iter][0].lower()
            return _entrystr in _modelstr

        completion.set_match_func(match_anywhere, None)

        # Add search field.
        self.entry = Gtk.Entry()
        self.entry.set_activates_default(True)  # Make ENTER key press trigger the OK button.
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, Gtk.STOCK_FIND)
        self.entry.set_placeholder_text("Search actions")
        self.entry.set_completion(completion)
        self.entry.connect("changed", self.do_validate, parent)

        # Add ok button.
        self.okButton = self.get_widget_for_response(response_id=Gtk.ResponseType.OK)
        self.okButton.set_can_default(True)
        self.okButton.grab_default()
        self.okButton.set_sensitive(False)

        # Configure dialog.
        self.set_modal(True)
        self.set_default_size(380, 100)
        self.vbox.pack_start(self.entry, True, True, 0)

    def do_validate(self, entry, data):
        """ Validating selected text entry and enable/disable ok button. """
        self.okButton.set_sensitive(entry.get_text() in self.entries)

    def do_response_ok(self):
        """ Finishing up when activating the ok button. """
        if self.entry.get_text() in self.entries:
            self.action = self.entries[self.entry.get_text()]
            self.result = Gtk.ResponseType.OK
            return True

import datetime
import gi
import math
import logging

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

from ks_includes.screen_panel import ScreenPanel
from ks_includes.KlippyGcodes import KlippyGcodes
from ks_includes.widgets.graph import HeaterGraph
from ks_includes.widgets.keypad import Keypad

def create_panel(*args):
    return TemperaturePanel(*args)

class TemperaturePanel(ScreenPanel):
    active_heaters = []
    devices = {}
    graph_update = None
    active_heater = None

    def initialize(self, panel_name):
        self.preheat_options = self._screen._config.get_preheat_options()
        logging.debug("Preheat options: %s" % self.preheat_options)
        self.show_preheat = True
        self._gtk.reset_temp_color()
        self.grid = self._gtk.HomogeneousGrid()
        self.grid.attach(self.create_left_panel(), 0, 0, 1, 1)
        self.grid.attach(self.create_right_panel(), 1, 0, 1, 1)
        self.content.add(self.grid)
        self.layout.show_all()

    def create_right_panel(self):
        _ = self.lang.gettext

        cooldown = self._gtk.ButtonImage('cool-down', _('Cooldown'), "color4", 1, 1, Gtk.PositionType.LEFT, False)
        adjust = self._gtk.ButtonImage('fine-tune', '', "color3", 1, 1, Gtk.PositionType.LEFT, False)

        right = self._gtk.HomogeneousGrid()
        right.attach(cooldown, 0, 0, 2, 1)
        right.attach(adjust, 2, 0, 1, 1)
        if self.show_preheat:
            right.attach(self.preheat(), 0, 1, 3, 4)
        else:
            right.attach(self.delta_adjust(), 0, 1, 3, 4)

        cooldown.connect("clicked", self.set_temperature, "cooldown")
        adjust.connect("clicked", self.switch_preheat_adjust)

        return right

    def switch_preheat_adjust(self, widget):
        self.show_preheat ^= True
        self.grid.remove_column(1)
        self.grid.attach(self.create_right_panel(), 1, 0, 1, 1)
        self.grid.show_all()

    def preheat(self):
        self.labels["preheat_grid"] = self._gtk.HomogeneousGrid()
        for i, option in enumerate(self.preheat_options):
            self.labels[option] = self._gtk.Button(option, "color%d" % ((i % 4)+1))
            self.labels[option].connect("clicked", self.set_temperature, option)
            self.labels['preheat_grid'].attach(self.labels[option], (i % 2), int(i/2), 1, 1)
        scroll = Gtk.ScrolledWindow()
        scroll.set_property("overlay-scrolling", False)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.labels["preheat_grid"])
        return scroll

    def delta_adjust(self):
        _ = self.lang.gettext
        self.tempdeltas = ["1", "5", "10", "25"]
        self.tempdelta = "10"

        deltagrid = self._gtk.HomogeneousGrid()
        self.labels["increase"] = self._gtk.ButtonImage("increase", _("Increase"), "color1")
        self.labels["increase"].connect("clicked", self.change_target_temp_incremental, "+")
        self.labels["decrease"] = self._gtk.ButtonImage("decrease", _("Decrease"), "color3")
        self.labels["decrease"].connect("clicked", self.change_target_temp_incremental, "-")

        tempgrid = Gtk.Grid()
        j = 0
        for i in self.tempdeltas:
            self.labels['deg' + i] = self._gtk.ToggleButton(i)
            self.labels['deg' + i].connect("clicked", self.change_temp_delta, i)
            ctx = self.labels['deg' + i].get_style_context()
            if j == 0:
                ctx.add_class("distbutton_top")
            elif j == len(self.tempdeltas)-1:
                ctx.add_class("distbutton_bottom")
            else:
                ctx.add_class("distbutton")
            if i == "10":
                ctx.add_class("distbutton_active")
            tempgrid.attach(self.labels['deg' + i], j, 0, 1, 1)
            j += 1

        self.labels["deg" + self.tempdelta].set_active(True)

        vbox = Gtk.VBox()
        vbox.pack_start(Gtk.Label(_("Temperature") + " (°C)"), False, False, 8)
        vbox.pack_end(tempgrid, True, True, 2)

        deltagrid.attach(vbox, 0, 3, 2, 2)
        deltagrid.attach(self.labels["decrease"], 0, 0, 1, 3)
        deltagrid.attach(self.labels["increase"], 1, 0, 1, 3)
        return deltagrid

    def change_temp_delta(self, widget, tempdelta):
        if self.tempdelta == tempdelta:
            return
        logging.info("### tempdelta " + str(tempdelta))

        ctx = self.labels["deg" + str(self.tempdelta)].get_style_context()
        ctx.remove_class("distbutton_active")

        self.tempdelta = tempdelta
        ctx = self.labels["deg" + self.tempdelta].get_style_context()
        ctx.add_class("distbutton_active")
        for i in self.tempdeltas:
            if i == self.tempdeltas:
                continue
            self.labels["deg" + str(i)].set_active(False)

    def change_target_temp_incremental(self, widget, dir):
        _ = self.lang.gettext
        if len(self.active_heaters) == 0:
            self._screen.show_popup_message(_("Nothing selected"))
        else:
            for heater in self.active_heaters:
                target = self._printer.get_dev_stat(heater, "target")
                if dir == "+":
                    target += int(self.tempdelta)
                    MAX_TEMP = int(self._printer.get_config_section(heater)['max_temp'])
                    if target > MAX_TEMP:
                        target = MAX_TEMP
                        self._screen.show_popup_message(_("Can't set above the maximum:") + (" %s" % MAX_TEMP))
                else:
                    target -= int(self.tempdelta)
                    if target < 0:
                        target = 0
                if heater.startswith('extruder'):
                    self._screen._ws.klippy.set_tool_temp(self._printer.get_tool_number(heater), target)
                elif heater.startswith('heater_bed'):
                    self._screen._ws.klippy.set_bed_temp(target)
                elif heater.startswith('heater_generic '):
                    self._screen._ws.klippy.set_heater_temp(" ".join(heater.split(" ")[1:]), target)
                elif heater.startswith("temperature_fan "):
                    self._screen._ws.klippy.set_temp_fan_temp(" ".join(heater.split(" ")[1:]), target)
                else:
                    logging.info("Unknown heater: %s" % heater)
                    self._screen.show_popup_message(_("Unknown Heater ") + heater)
                self._printer.set_dev_stat(heater, "target", int(target))
                logging.info("Setting %s to %d" % (heater, target))

    def activate(self):
        if self.graph_update is None:
            self.graph_update = GLib.timeout_add_seconds(1, self.update_graph)
        for x in self._printer.get_tools():
            if x not in self.active_heaters:
                self.select_heater(None, x)
        for h in self._printer.get_heaters():
            if h.startswith("temperature_sensor "):
                continue
            if h not in self.active_heaters:
                self.select_heater(None, h)

    def deactivate(self):
        if self.graph_update is not None:
            GLib.source_remove(self.graph_update)
            self.graph_update = None

    def select_heater(self, widget, device):
        _ = self.lang.gettext

        if self.devices[device]["can_target"]:
            if device in self.active_heaters:
                self.active_heaters.pop(self.active_heaters.index(device))
                self.devices[device]['name'].get_style_context().remove_class("active_device")
                self.devices[device]['select'].set_label(_("Select"))
                return
            self.active_heaters.append(device)
            self.devices[device]['name'].get_style_context().add_class("active_device")
            self.devices[device]['select'].set_label(_("Deselect"))
        return

    def set_temperature(self, widget, setting):
        _ = self.lang.gettext
        if len(self.active_heaters) == 0:
            self._screen.show_popup_message(_("Nothing selected"))
        else:
            if setting == "cooldown":
                for heater in self.active_heaters:
                    if heater.startswith('extruder'):
                        self._screen._ws.klippy.set_tool_temp(self._printer.get_tool_number(heater), 0)
                    elif heater.startswith('heater_bed'):
                        self._screen._ws.klippy.set_bed_temp(0)
                    elif heater.startswith('heater_generic '):
                        self._screen._ws.klippy.set_heater_temp(" ".join(heater.split(" ")[1:]), 0)
                    logging.info("Setting %s to %d" % (heater, 0))
                    self._printer.set_dev_stat(heater, "target", 0)
                return

            for heater in self.active_heaters:
                if heater.startswith('extruder'):
                    target = self.preheat_options[setting]["extruder"]
                    self._screen._ws.klippy.set_tool_temp(self._printer.get_tool_number(heater), target)
                elif heater.startswith('heater_bed'):
                    target = self.preheat_options[setting]["bed"]
                    self._screen._ws.klippy.set_bed_temp(target)
                elif heater.startswith('heater_generic '):
                    target = self.preheat_options[setting]["heater_generic"]
                    self._screen._ws.klippy.set_heater_temp(" ".join(heater.split(" ")[1:]), target)
                elif heater.startswith('temperature_fan '):
                    target = self.preheat_options[setting]["temperature_fan"]
                    self._screen._ws.klippy.set_temp_fan_temp(" ".join(heater.split(" ")[1:]), target)
                else:
                    logging.info("Unknown heater: %s" % heater)
                    self._screen.show_popup_message(_("Unknown Heater") + heater)
                self._printer.set_dev_stat(heater, "target", int(target))
                logging.info("Setting %s to %d" % (heater, target))
            if self.preheat_options[setting]['gcode']:
                self._screen._ws.klippy.gcode_script(self.preheat_options[setting]['gcode'])

    def add_device(self, device):
        _ = self.lang.gettext
        logging.info("Adding device: %s" % device)

        temperature = self._printer.get_dev_stat(device, "temperature")
        if temperature is None:
            return

        if not (device.startswith("extruder") or device.startswith("heater_bed")):
            devname = " ".join(device.split(" ")[1:])
            # Support for hiding devices by name
            if devname.startswith("_"):
                return
        else:
            devname = device

        if device.startswith("extruder"):
            i = 0
            for d in self.devices:
                if d.startswith('extruder'):
                    i += 1
            image = "extruder-%s" % i
            class_name = "graph_label_%s" % device
            type = "extruder"
        elif device == "heater_bed":
            image = "bed"
            devname = "Heater Bed"
            class_name = "graph_label_heater_bed"
            type = "bed"
        elif device.startswith("temperature_fan"):
            f = 1
            for d in self.devices:
                if "temperature_fan" in d:
                    f += 1
            image = "fan"
            class_name = "graph_label_fan_%s" % f
            type = "fan"
        else:
            s = 1
            for d in self.devices:
                if "sensor" in d:
                    s += 1
            image = "heat-up"
            class_name = "graph_label_sensor_%s" % s
            type = "sensor"

        rgb, color = self._gtk.get_temp_color(type)

        can_target = self._printer.get_temp_store_device_has_target(device)
        self.labels['da'].add_object(device, "temperatures", rgb, False, True)
        if can_target:
            self.labels['da'].add_object(device, "targets", rgb, True, False)

        text = "<span underline='double' underline_color='#%s'>%s</span>" % (color, devname.capitalize())
        name = self._gtk.ButtonImage(image, devname.capitalize(), None, .5, .5, Gtk.PositionType.LEFT, False)
        name.connect('clicked', self.on_popover_clicked, device)
        name.set_alignment(0, .5)
        name.get_style_context().add_class(class_name)
        child = name.get_children()[0].get_children()[0].get_children()[1]
        child.set_ellipsize(True)
        child.set_ellipsize(Pango.EllipsizeMode.END)

        temp = self._gtk.Button("")
        temp.connect('clicked', self.select_heater, device)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        dev = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        dev.set_hexpand(True)
        dev.set_vexpand(False)
        dev.add(labels)

        self.devices[device] = {
            "class": class_name,
            "type": type,
            "name": name,
            "temp": temp,
            "can_target": can_target
        }

        if self.devices[device]["can_target"]:
            temp.get_child().set_label("%.1f %s" %
                                       (temperature, self.format_target(self._printer.get_dev_stat(device, "target"))))
            self.devices[device]['select'] = self._gtk.Button(label=_("Select"))
            self.devices[device]['select'].connect('clicked', self.select_heater, device)
        else:
            temp.get_child().set_label("%.1f" % temperature)

        devices = sorted(self.devices)
        pos = devices.index(device) + 1

        self.labels['devices'].insert_row(pos)
        self.labels['devices'].attach(name, 0, pos, 1, 1)
        self.labels['devices'].attach(temp, 1, pos, 1, 1)
        self.labels['devices'].show_all()

    def change_target_temp(self, temp):
        _ = self.lang.gettext

        MAX_TEMP = int(self._printer.get_config_section(self.active_heater)['max_temp'])
        if temp > MAX_TEMP:
            self._screen.show_popup_message(_("Can't set above the maximum:") + (" %s" % MAX_TEMP))
            return
        temp = 0 if temp < 0 else temp

        if self.active_heater.startswith('extruder'):
            self._screen._ws.klippy.set_tool_temp(self._printer.get_tool_number(self.active_heater), temp)
        elif self.active_heater == "heater_bed":
            self._screen._ws.klippy.set_bed_temp(temp)
        elif self.active_heater.startswith('heater_generic '):
            self._screen._ws.klippy.set_heater_temp(" ".join(self.active_heater.split(" ")[1:]), temp)
        elif self.active_heater.startswith('temperature_fan '):
            self._screen._ws.klippy.set_temp_fan_temp(" ".join(self.active_heater.split(" ")[1:]), temp)
        else:
            logging.info("Unknown heater: %s" % self.active_heater)
            self._screen.show_popup_message(_("Unknown Heater ") + self.active_heater)
        self._printer.set_dev_stat(self.active_heater, "target", temp)

    def create_left_panel(self):
        _ = self.lang.gettext

        self.labels['devices'] = Gtk.Grid()
        self.labels['devices'].get_style_context().add_class('heater-grid')
        self.labels['devices'].set_vexpand(False)

        name = Gtk.Label("")
        temp = Gtk.Label(_("Temp (°C)"))
        temp.set_size_request(round(self._gtk.get_font_size() * 5.5), 0)

        self.labels['devices'].attach(name, 0, 0, 1, 1)
        self.labels['devices'].attach(temp, 1, 0, 1, 1)

        da = HeaterGraph(self._printer)
        da.set_vexpand(True)
        self.labels['da'] = da

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_vexpand(True)
        box.add(self.labels['devices'])
        box.add(da)


        self.labels['graph_settemp'] = self._gtk.Button(label=_("Set Temp"))
        self.labels['graph_settemp'].connect("clicked", self.show_numpad)
        self.labels['graph_hide'] = self._gtk.Button(label=_("Hide"))
        self.labels['graph_hide'].connect("clicked", self.graph_show_device, False)
        self.labels['graph_show'] = self._gtk.Button(label=_("Show"))
        self.labels['graph_show'].connect("clicked", self.graph_show_device)

        popover = Gtk.Popover()
        self.labels['popover_vbox'] = Gtk.VBox()
        popover.add(self.labels['popover_vbox'])
        popover.set_position(Gtk.PositionType.BOTTOM)
        self.labels['popover'] = popover

        for d in self._printer.get_temp_store_devices():
            self.add_device(d)

        return box


    def graph_show_device(self, widget, show=True):
        logging.info("Graph show: %s %s" % (self.popover_device, show))
        self.labels['da'].set_showing(self.popover_device, show)
        if show:
            self.devices[self.popover_device]['name'].get_style_context().remove_class("graph_label_hidden")
            self.devices[self.popover_device]['name'].get_style_context().add_class(
                self.devices[self.popover_device]['class'])
        else:
            self.devices[self.popover_device]['name'].get_style_context().remove_class(
                self.devices[self.popover_device]['class'])
            self.devices[self.popover_device]['name'].get_style_context().add_class("graph_label_hidden")
        self.labels['da'].queue_draw()
        self.popover_populate_menu()
        self.labels['popover'].show_all()

    def hide_numpad(self, widget):
        self.devices[self.active_heater]['name'].get_style_context().remove_class("button_active")
        self.active_heater = None

        self.grid.remove_column(1)
        self.grid.attach(self.create_right_panel(), 1, 0, 1, 1)
        self.grid.show_all()

    def on_popover_clicked(self, widget, device):
        self.popover_device = device
        po = self.labels['popover']
        po.set_relative_to(widget)
        self.popover_populate_menu()
        po.show_all()

    def popover_populate_menu(self):
        pobox = self.labels['popover_vbox']
        for child in pobox.get_children():
            pobox.remove(child)

        if self.labels['da'].is_showing(self.popover_device):
            pobox.pack_start(self.labels['graph_hide'], True, True, 5)
        else:
            pobox.pack_start(self.labels['graph_show'], True, True, 5)
        if self.devices[self.popover_device]["can_target"]:
            pobox.pack_start(self.labels['graph_settemp'], True, True, 5)
            pobox.pack_end(self.devices[self.popover_device]['select'], True, True, 5)

    def process_update(self, action, data):
        if action != "notify_status_update":
            return

        for x in self._printer.get_tools():
            self.update_temp(
                x,
                self._printer.get_dev_stat(x, "temperature"),
                self._printer.get_dev_stat(x, "target")
            )
        for h in self._printer.get_heaters():
            self.update_temp(
                h,
                self._printer.get_dev_stat(h, "temperature"),
                self._printer.get_dev_stat(h, "target")
            )

    def show_numpad(self, widget):
        _ = self.lang.gettext

        if self.active_heater is not None:
            self.devices[self.active_heater]['name'].get_style_context().remove_class("button_active")
        self.active_heater = self.popover_device
        self.devices[self.active_heater]['name'].get_style_context().add_class("button_active")

        if "keypad" not in self.labels:
            self.labels["keypad"] = Keypad(self._screen, self.change_target_temp, self.hide_numpad)
        self.labels["keypad"].clear()

        self.grid.remove_column(1)
        self.grid.attach(self.labels["keypad"], 1, 0, 1, 1)
        self.grid.show_all()

        self.labels['popover'].popdown()

    def update_graph(self):
        self.labels['da'].queue_draw()
        alloc = self.labels['devices'].get_allocation()
        alloc = self.labels['da'].get_allocation()
        return True

    def update_temp(self, device, temp, target):
        if device not in self.devices:
            return

        if self.devices[device]["can_target"]:
            self.devices[device]["temp"].get_child().set_label("%.1f %s" % (temp, self.format_target(target)))
        else:
            self.devices[device]["temp"].get_child().set_label("%.1f" % temp)

#!/bin/env python

## system-config-printer

## Copyright (C) 2006 Red Hat, Inc.
## Copyright (C) 2006 Florian Festi <ffesti@redhat.com>
## Copyright (C) 2006 Tim Waugh <twaugh@redhat.com>

## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.

## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.

## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import cups, pprint, os, tempfile, re
from rhpl.translate import _, N_

class Printer:

    printer_states = { cups.IPP_PRINTER_IDLE: _("Idle"),
                       cups.IPP_PRINTER_PROCESSING: _("Processing"),
                       cups.IPP_PRINTER_BUSY: _("Busy"),
                       cups.IPP_PRINTER_STOPPED: _("Stopped") }

    def __init__(self, name, connection, set_attributes=[], **kw):
        self.name = name
        self.connection = connection
        self.class_members = []
        self.device_uri = kw.get('device-uri', "")
        self.info = kw.get('printer-info', "")
        self.is_shared = kw.get('printer-is-shared', None)
        self.location = kw.get('printer-location', "")
        self.make_and_model = kw.get('printer-make-and-model', "")
        self.state = kw.get('printer-state', 0)
        self.type = kw.get('printer-type', 0)
        self.uri_supported = kw.get('printer-uri-supported', "")
        self._expand_flags()

        self.state_description = self.printer_states.get(
            self.state, _("Unknown"))

        self._getAttributes(set_attributes)

        self.enabled = self.state != cups.IPP_PRINTER_STOPPED

        if self.is_shared is None:
            self.is_shared = not self.not_shared
        del self.not_shared

        if self.is_class:
            self._ppd = False
        else:
            self._ppd = None # load on demand

    _flags_blacklist = ["options", "local"]

    def _expand_flags(self):
        prefix = "CUPS_PRINTER_"
        prefix_length = len(prefix)
        # loop over cups constants
        for name in cups.__dict__:
            if name.startswith(prefix):
                attr_name = name[prefix_length:].lower()
                if attr_name in self._flags_blacklist: continue
                if attr_name == "class": attr_name = "is_class"
                # set as attribute
                setattr(self, attr_name,
                        bool(self.type & getattr(cups, name)))

    def _getAttributes(self, set_attributes):
        attrs = self.connection.getPrinterAttributes(self.name)
        self.attributes = {}
        self.possible_attributes = {}

        for key, value in attrs.iteritems():
            if key.endswith("-default"):
                name = key[:-len("-default")]
                if not attrs.has_key(name + "-supported"): continue
                if name in ["job-sheets", "printer-error-policy",
                            "printer-op-policy", # handled below
                            "notify-events"]: # not supported by cups
                    continue 
                if name in set_attributes:
                    self.attributes[name] = value
                    
                self.possible_attributes[name] = (value,
                                                  attrs[name+"-supported"]) 
                #print name, value, attrs[name + "-supported"]

        for name, default, supported in (
            ('columns', '1', (1, 4)),
            ('cpi', '10', (1, 100)),
            ('fitplot', 'false', ['true', 'false']),
            ('landscape', 'false', ['true', 'false']),
            ('number-up-layout', 'lrtb', ['btlr', 'btrl', 'lrbt', 'lrtb',
                                          'rlbt', 'rltb', 'tblr', 'tbrl']),
            ('orientation-requested', '3', ['3','4','5','6']),
            ('page-bottom', '72', (0, 500)),
            ('page-top', '72', (0, 500)),
            ('page-left', '72', (0, 500)),
            ('page-right', '72', (0, 500)),
            ('page-border', 'none', ['none', 'single', 'single-thick',
                                     'double', 'double-thick']),
            ('prettyprint', 'false', ['true', 'false']),
            ('lpi', '6', (1, 100)),
            ('scaling', '100', (1, 1000)),
            ('sides', 'one-sided', ['one-sided', 'two-sided-long-edge',
                                    'two-sided-short-edge']),
            ('wrap', 'false', ['true', 'false'])):
            self.possible_attributes.setdefault(name, (default, supported))
        
        #print set_attributes
        #print self.attributes, self.possible_attributes

        self.job_sheet_start, self.job_sheet_end = attrs.get(
            'job-sheets-default', ('none', 'none'))
        self.job_sheets_supported = attrs.get('job-sheets-supported', ['none'])
        self.error_policy = attrs.get('printer-error-policy', 'none')
        self.error_policy_supported = attrs.get(
            'printer-error-policy-supported', ['none'])
        self.op_policy = attrs.get('printer-op-policy', "") or "default"
        self.op_policy_supported = attrs.get(
            'printer-op-policy-supported', ["default"])

        self.default_allow = True
        self.except_users = []
        if attrs.has_key('requesting-user-name-allowed'):
            self.except_users = attrs['requesting-user-name-allowed']
            self.default_allow = False
        elif attrs.has_key('requesting-user-name-denied'):
            self.except_users = attrs['requesting-user-name-denied']
        self.except_users_string = ', '.join(self.except_users)

    def getServer(self):
        """return Server URI or None"""
        if not self.uri_supported.startswith('ipp://'):
            return None
        uri = self.uri_supported[6:]
        uri = uri.split('/')[0]
        uri = uri.split(':')[0]
        if uri == "localhost.localdomain":
            uri = "localhost"
        return uri

    def getPPD(self):
        """
        return cups.PPD object or False for raw queues
        raise cups.IPPError
        """
        if self._ppd is None:
            try:
                filename = self.connection.getPPD(self.name)
            except cups.IPP_NOT_FOUND:
                self._ppd = False
            self._ppd = cups.PPD(filename)
            os.unlink(filename)
        return self._ppd

    def setOption(self, name, value):
        self.connection.addPrinterOptionDefault(self.name, name, value)

    def unsetOption(self, name):
        self.connection.deletePrinterOptionDefault(self.name, name)

    def setEnabled(self, on):
        if on:
            self.connection.enablePrinter(self.name)
        else:
            self.connection.disablePrinter(self.name)

    def setAccepting(self, on):
        if on:
            self.connection.acceptJobs(self.name)
        else:
            self.connection.rejectJobs(self.name)

    def setShared(self,on):
        self.connection.setPrinterShared(self.name, on)

    def setErrorPolicy (self, policy):
        self.connection.setPrinterErrorPolicy(self.name, policy)

    def setOperationPolicy(self, policy):
        self.connection.setPrinterOpPolicy(self.name, policy)    

    def setJobSheets(self, start, end):
        self.connection.setPrinterJobSheets(self.name, start, end)

    def setAccess(self, allow, except_users):
        if isinstance(except_users, str):
            users = except_users.split()
            users = [u.split(",") for u in users]
            except_users = []
            for u in users:
                except_users.extend(u)
            except_users = [u.strip() for u in except_users]
            except_users = filter(None, except_users)
            
        if allow:
            self.connection.setPrinterUsersDenied(self.name, except_users)
        else:
            self.connection.setPrinterUsersAllowed(self.name, except_users)

def getPrinters(connection):
    printers_conf = PrintersConf(connection)
    printers = connection.getPrinters()
    classes = connection.getClasses()
    for name, printer in printers.iteritems():
        printer = Printer(name, connection,
                          set_attributes=printers_conf.get_options(name),
                          **printer)
        printers[name] = printer
        if classes.has_key(name):
            printer.class_members = classes[name]
            printer.class_members.sort()
    return printers

class Device:

    prototypes = {
        'ipp' : "ipp://%s"
        }

    def __init__(self, uri, **kw):
        self.uri = uri
        self.device_class = kw.get('device-class', 'Unknown') # XXX better default
        self.info = kw.get('device-info', '')
        self.make_and_model = kw.get('device-make-and-model', 'Unknown')
        self.id = kw.get('device-id', '')

        uri_pieces = uri.split(":")
        self.type =  uri_pieces[0]
        self.is_class = len(uri_pieces)==1

        #self.id = 'MFG:HEWLETT-PACKARD;MDL:DESKJET 990C;CMD:MLC,PCL,PML;CLS:PRINTER;DES:Hewlett-Packard DeskJet 990C;SN:US05N1J00XLG;S:00808880800010032C1000000C2000000;P:0800,FL,B0;J:                    ;'

        self.id_dict = {}
        pieces = self.id.split(";")
        for piece in pieces:
            if not piece: continue
            name, value = piece.split(":",1)
            if name=="CMD":
                value = value.split(',') 
            self.id_dict[name] = value
        for name in ["MFG", "MDL", "CMD", "CLS", "DES", "SN", "S", "P", "J"]:
            self.id_dict.setdefault(name, "")

    def __cmp__(self, other):
        if self.is_class != other.is_class:
            if other.is_class:
                return -1
            return 1
        if not self.is_class and (self.type != other.type):
            # "hp" before * before "parallel" before "serial"
            if other.type == "serial":
                return -1
            if self.type == "serial":
                return 1
            if other.type == "parallel":
                return -1
            if self.type == "parallel":
                return 1
            if other.type == "hp":
                return 1
            if self.type == "hp":
                return -1
        result = cmp(bool(self.id), bool(other.id))
        if not result:
            result = cmp(self.info, other.info)
        
        return result

class PrintersConf:

    def __init__(self, connection):
        self.connection = connection
        self.fetch()
        self.parse()

    def fetch(self):
        fd, filename = tempfile.mkstemp("printer.conf")
        os.close(fd)
        try:
            self.connection.getFile('/admin/conf/printers.conf', filename)
        except cups.HTTPError, e:
            if e.args[0] == cups.HTTP_UNAUTHORIZED:
                self.lines = []
                return
            else:
                raise e

        self.lines = open(filename).readlines()
        os.unlink(filename)

    def parse(self):
        self.set_options = {}
        current_printer = None
        for line in self.lines:
            words = line.split()
            if len (words) == 0:
                continue
            if words[0] == "Option":
                self.set_options.setdefault(current_printer, []).append(words[1])
                continue
            match = re.match(r"<(Default)?Printer ([^>]+)>\s*\n", line) 
            if match:
                current_printer = match.group(2)
            if line.strip().find("</Printer>") != -1:
                current_printer = None

    def get_options(self, printername):
        return self.set_options.get(printername, [])
                
"""
attrs=c.getPrinterAttributes(printer)
options=map (lambda x: x[:x.rindex ('-')],
             filter (lambda x: x.endswith('-default'), attrs.keys()))

specified_options = []

print "Specified options:"
print map (lambda x: (x, attrs[x + '-default']), specified_options)
"""

def match(s1, s2):
    if s1==s2: return len(s1)
    for nr, (c1, c2) in enumerate(zip(s1, s2)):
        if c1!=c2: return nr
    return min(len(s1), len(s2))

def getDevices(connection, current_uri=None):
    """
    raise cups.IPPError
    """
    devices = connection.getDevices()
    for uri, data in devices.iteritems():
        device = Device(uri, **data)
        devices[uri] = device
    if current_uri and not devices.has_key(current_uri):
        device = Device(current_uri)
        uri_matches = [(match(uri, current_uri), uri)
                       for uri in devices.iterkeys()]
                      # returns list of (match length, uri) 
        m, uri = max(uri_matches)
        device.info = devices[uri].info
        devices[current_uri] = device
    return devices

def getPPDGroupOptions(group):
    options = group.options[:]
    for g in group.subgroups:
        options.extend(getPPDGroupOptions(g))
    return options

def iteratePPDOptions(ppd):
    for group in ppd.optionGroups:
        for option in getPPDGroupOptions(group):
            yield option

def copyPPDOptions(ppd1, ppd2):
    for option in iteratePPDOptions(ppd1):
        new_option = ppd2.findOption(option.keyword)
        if new_option and option.ui==new_option.ui:
            value = option.defchoice
            for choice in new_option.choices:
                if choice["choice"]==value:
                    ppd2.markOption(new_option.keyword, value)
                    
            
def main():
    c = cups.Connection()
    #printers = getPrinters(c)
    for device in getDevices(c).itervalues():
        print device.uri, device.id_dict

if __name__=="__main__":
    main()

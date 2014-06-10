#!/usr/bin/env python
"""jss.py

Python wrapper for JSS API.
Copyright (C) 2014 Shea G Craig <shea.craig@da.org>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

from xml.etree import ElementTree
import os
import re
import copy

import requests
try:
    import FoundationPlist
except ImportError:
    import plistlib


class JSSPrefsMissingFileError(Exception):
    pass


class JSSPrefsMissingKeyError(Exception):
    pass


class JSSGetError(Exception):
    pass


class JSSPutError(Exception):
    pass


class JSSPostError(Exception):
    pass


class JSSDeleteError(Exception):
    pass


class JSSMethodNotAllowedError(Exception):
    pass


class JSSUnsupportedSearchMethodError(Exception):
    pass


class JSSPrefs(object):
    """Uses the OS X preferences system to store credentials and JSS URL."""
    def __init__(self, preferences_file=None):
        """Create a preferences object.

        preferences_file: Alternate location to look for preferences.

        Preference file should include the following keys:
            jss_url:        Full path, including port, to JSS,
                            e.g. 'https://mycasper.donkey.com:8443'
                            (JSS() handles the appending of /JSSResource)
            jss_user:       API username to use.
            jss_password:   API password.

        """
        if preferences_file is None:
            path = '~/Library/Preferences/org.da.python-jss.plist'
            preferences_file = os.path.expanduser(path)
        if os.path.exists(preferences_file):
            try:
                prefs = FoundationPlist.readPlist(os.path.expanduser(preferences_file))
            except NameError:
                # Plist files are probably not binary on non-OS X machines, so
                # this should be safe.
                prefs = plistlib.readPlist(os.path.expanduser(preferences_file))
            try:
                self.user = prefs['jss_user']
                self.password = prefs['jss_pass']
                self.url = prefs['jss_url']
            except KeyError:
                raise JSSPrefsMissingKeyError("Please provide all required"
                                              " preferences!")
        else:
            raise JSSPrefsMissingFileError("Preferences file not found!")


class JSS(object):
    """Connect to a JSS and handle API requests."""
    def __init__(self, jss_prefs=None, url=None, user=None, password=None,
                 ssl_verify=True, verbose=False):
        """Provide either a JSSPrefs object OR specify url, user, and password
        to init.

        jss_prefs:  A JSSPrefs object.
        url:        Path with port to a JSS. See JSSPrefs.__doc__
        user:       API Username.
        password:   API Password.
        ssl_verify: Boolean indicating whether to verify SSL certificates.
                    Defaults to True.

        """
        if jss_prefs is not None:
            url = jss_prefs.url
            user = jss_prefs.user
            password = jss_prefs.password

        self._url = '%s/JSSResource' % url
        self.user = user
        self.password = password
        self.ssl_verify = ssl_verify
        self.verbose = verbose
        self.factory = JSSObjectFactory(self)

    def _error_handler(self, exception_cls, response):
        """Generic error handler. Converts html responses to friendlier
        text.

        """
        # Responses are sent as html. Split on the newlines and give us the
        # <p> text back.
        errorlines = response.text.encode('utf-8').split('\n')
        error = []
        for line in errorlines:
            e = re.search(r'<p.*>(.*)</p>', line)
            if e:
                error.append(e.group(1))

        error = '\n'.join(error)
        raise exception_cls('JSS ERROR. Response Code: %s\tResponse: %s' %
                          (response.status_code, error))

    def get(self, url):
        """Get a url, handle errors, and return an etree from the XML data."""
        # For some objects the JSS tries to return JSON if we don't specify
        # that we want XML.
        url = '%s%s' % (self._url, url)
        headers = {'Accept': 'application/xml'}
        response = requests.get(url, auth=(self.user, self.password),
                                verify=self.ssl_verify, headers=headers)

        if response.status_code == 200:
            if self.verbose:
                print("GET: Success.")
        elif response.status_code >= 400:
            self._error_handler(JSSGetError, response)

        # JSS returns xml encoded in utf-8
        jss_results = response.text.encode('utf-8')
        try:
            xmldata = ElementTree.fromstring(jss_results)
        except ElementTree.ParseError:
            raise JSSGetError("Error Parsing XML:\n%s" % jss_results)
        return xmldata

    def post(self, obj_class, url, data):
        """Post an object to the JSS. For creating new objects only."""
        # The JSS expects a post to ID 0 to create an object
        url = '%s%s' % (self._url, url)
        data = ElementTree.tostring(data.getroot())
        headers = {"content-type": 'text/xml'}
        response = requests.post(url, auth=(self.user, self.password),
                                 data=data, verify=self.ssl_verify,
                                 headers=headers)

        if response.status_code == 201:
            if self.verbose:
                print("POST: Success")
        elif response.status_code >= 400:
            self._error_handler(JSSPostError, response)

        # Get the ID of the new object. JSS returns xml encoded in utf-8
        jss_results = response.text.encode('utf-8')
        id_ =  int(re.search(r'<id>([0-9]+)</id>', jss_results).group(1))

        return self.factory.get_object(obj_class, id_)

    def put(self, url, data):
        """Updates an object on the JSS."""
        url = '%s%s' % (self._url, url)
        data = ElementTree.tostring(data)
        headers = {"content-type": 'text/xml'}
        response = requests.put(url, auth=(self.user, self.password),
                                verify=self.ssl_verify, data=data,
                                headers=headers)
        if response.status_code == 201:
            if self.verbose:
                print("PUT: Success.")
        elif response.status_code >= 400:
            self._error_handler(JSSPutError, response)

    def delete(self, url):
        """Delete an object from the JSS."""
        url = '%s%s' % (self._url, url)
        response = requests.delete(url, auth=(self.user, self.password),
                                 verify=self.ssl_verify)
        if response.status_code == 200:
            if self.verbose:
                print("DEL: Success.")
        elif response.status_code >= 400:
            self._error_handler(JSSDeleteError, response)

    def Account(self, data=None):
        return self.factory.get_object(Account, data)

    def AccountGroup(self, data=None):
        return self.factory.get_object(AccountGroup, data)

    def AdvancedComputerSearch(self, data=None):
        return self.factory.get_object(AdvancedComputerSearch, data)

    def AdvancedMobileDeviceSearch(self, data=None):
        return self.factory.get_object(AdvancedMobileDeviceSearch, data)

    def ActivationCode(self, data=None):
        return self.factory.get_object(ActivationCode, data)

    def Building(self, data=None):
        return self.factory.get_object(Building, data)

    def Category(self, data=None):
        return self.factory.get_object(Category, data)

    def Class(self, data=None):
        return self.factory.get_object(Class, data)

    def Computer(self, data=None):
        return self.factory.get_object(Computer, data)

    def ComputerCheckIn(self, data=None):
        return self.factory.get_object(ComputerCheckIn, data)

    def ComputerCommand(self, data=None):
        return self.factory.get_object(ComputerCommand, data)

    def ComputerExtensionAttribute(self, data=None):
        return self.factory.get_object(ComputerExtensionAttribute, data)

    def ComputerGroup(self, data=None):
        return self.factory.get_object(ComputerGroup, data)

    def ComputerInventoryCollection(self, data=None):
        return self.factory.get_object(ComputerInventoryCollection, data)

    def ComputerInvitation(self, data=None):
        return self.factory.get_object(ComputerInvitation, data)

    def ComputerReport(self, data=None):
        return self.factory.get_object(ComputerReport, data)

    def Department(self, data=None):
        return self.factory.get_object(Department, data)

    def DirectoryBinding(self, data=None):
        return self.factory.get_object(DirectoryBinding, data)

    def DiskEncryptionConfiguration(self, data=None):
        return self.factory.get_object(DiskEncryptionConfiguration, data)

    def DistributionPoint(self, data=None):
        return self.factory.get_object(DistributionPoint, data)

    def DockItem(self, data=None):
        return self.factory.get_object(DockItem, data)

    def EBook(self, data=None):
        return self.factory.get_object(EBook, data)

    #def FileUpload(self, data=None):
    #    return self.factory.get_object(FileUpload, data)

    def GSXConnection(self, data=None):
        return self.factory.get_object(GSXConnection, data)

    def JSSUser(self, data=None):
        return self.factory.get_object(JSSUser, data)

    def LDAPServer(self, data=None):
        return self.factory.get_object(LDAPServer, data)

    def LicensedSoftware(self, data=None):
        return self.factory.get_object(LicensedSoftware, data)

    def ManagedPreferenceProfile(self, data=None):
        return self.factory.get_object(ManagedPreferenceProfile, data)

    def MobileDevice(self, data=None):
        return self.factory.get_object(MobileDevice, data)

    def MobileDeviceApplication(self, data=None):
        return self.factory.get_object(MobileDeviceApplication, data)

    def MobileDeviceCommand(self, data=None):
        return self.factory.get_object(MobileDeviceCommand, data)

    def MobileDeviceConfigurationProfile(self, data=None):
        return self.factory.get_object(MobileDeviceConfigurationProfile, data)

    def MobileDeviceEnrollmentProfile(self, data=None):
        return self.factory.get_object(MobileDeviceEnrollmentProfile, data)

    def MobileDeviceExtensionAttribute(self, data=None):
        return self.factory.get_object(MobileDeviceExtensionAttribute, data)

    def MobileDeviceInvitation(self, data=None):
        return self.factory.get_object(MobileDeviceInvitation, data)

    def MobileDeviceGroup(self, data=None):
        return self.factory.get_object(MobileDeviceGroup, data)

    def MobileDeviceProvisioningProfile(self, data=None):
        return self.factory.get_object(MobileDeviceProvisioningProfile, data)

    def NetbootServer(self, data=None):
        return self.factory.get_object(NetbootServer, data)

    def NetworkSegment(self, data=None):
        return self.factory.get_object(NetworkSegment, data)

    def OSXConfigurationProfile(self, data=None):
        return self.factory.get_object(OSXConfigurationProfile, data)

    def Package(self, data=None):
        return self.factory.get_object(Package, data)

    def Peripheral(self, data=None):
        return self.factory.get_object(Peripheral, data)

    def PeripheralType(self, data=None):
        return self.factory.get_object(PeripheralType, data)

    def Policy(self, data=None):
        return self.factory.get_object(Policy, data)

    def Printer(self, data=None):
        return self.factory.get_object(Printer, data)

    def RestrictedSfotware(self, data=None):
        return self.factory.get_object(RestrictedSoftware, data)

    def RemovableMACAddress(self, data=None):
        return self.factory.get_object(RemovableMACAddress, data)

    def SavedSearch(self, data=None):
        return self.factory.get_object(SavedSearch, data)

    def Script(self, data=None):
        return self.factory.get_object(Script, data)

    def Site(self, data=None):
        return self.factory.get_object(Site, data)

    def SoftwareUpdateServer(self, data=None):
        return self.factory.get_object(SoftwareUpdateServer, data)

    def SMTPServer(self, data=None):
        return self.factory.get_object(SMTPServer, data)

class JSSObjectFactory(object):
    """Create JSSObjects intelligently based on a single data argument."""
    def __init__(self, jss):
        self.jss = jss

    def get_object(self, obj_class, data=None):
        """Return a subclassed JSSObject instance by querying for existing
        objects or posting a new object. List operations return a
        JSSObjectList.

        obj_class is the class to retrieve.
        data is flexible.
            If data is type:
                None:   Perform a list operation, or for non-container objects,
                        return all data.
                int:    Retrieve an object with ID of <data>
                str:    Retrieve an object with name of <str>. For some
                        objects, this may be overridden to include searching
                        by other criteria. See those objects for more info.
                dict:   Get the existing object with <dict>['id']
                xml.etree.ElementTree.Element:    Create a new object from xml

                Warning! Be sure to pass ID's as ints, not str!

        """
        # List objects
        if data is None:
            url = obj_class.get_url(data)
            if obj_class.can_list and obj_class.can_get:
                result = self.jss.get(url)
                if obj_class.container:
                    result = result.find(obj_class.container)
                response_objects = [item for item in result if item is not None and \
                                    item.tag != 'size']
                objects = [JSSListData(obj_class, {i.tag: i.text for i in response_object}) for response_object in response_objects]
                return JSSObjectList(self, obj_class, objects)
            elif obj_class.can_get:
                # Single object
                xmldata = self.jss.get(url)
                return obj_class(self.jss, xmldata)
            else:
                raise JSSMethodNotAllowedError(obj_class.__class__.__name__)
        # Retrieve individual objects
        elif type(data) in [str, int]:
            if obj_class.can_get:
                url = obj_class.get_url(data)
                xmldata = self.jss.get(url)
                if xmldata.find('size') is not None:
                    # May need above treatment, with .find(container), and refactoring out this otherwise duplicate code.
                    # Get returned a list.
                    response_objects = [item for item in xmldata if item is not None and \
                                        item.tag != 'size']
                    objects = [JSSListData(obj_class, {i.tag: i.text for i in response_object}) for response_object in response_objects]
                    return JSSObjectList(self, obj_class, objects)
                else:
                    return obj_class(self.jss, xmldata)
            else:
                raise JSSMethodNotAllowedError(obj_class.__class__.__name__)
        # Create a new object
        elif isinstance(data, JSSObjectTemplate):
            if obj_class.can_post:
                url = obj_class.get_post_url()
                return self.jss.post(obj_class, url, data)
            else:
                raise JSSMethodNotAllowedError(obj_class.__class__.__name__)


class JSSObject(ElementTree.ElementTree):
    """Base class for representing all available JSS API objects.

    """
    _url = None
    can_list = True
    can_get = True
    can_put = True
    can_post = True
    can_delete = True
    id_url = '/id/'
    container = ''
    default_search = 'name'
    search_types = {'name': '/name/'}

    def __init__(self, jss, data):
        """Initialize a new JSSObject

        jss:    JSS object.
        data:   Valid XML.

        """
        self.jss = jss
        if not isinstance(data, ElementTree.Element):
            raise TypeError("JSSObjects data argument must be of type "
                            "xml.etree.ElemenTree.Element")
        super(JSSObject, self).__init__(element=data)

    @classmethod
    def get_url(cls, data):
        """Return the URL for a get request based on data type."""
        if isinstance(data, int):
            return '%s%s%s' % (cls._url, cls.id_url, data)
        elif data is None:
            return cls._url
        else:
            if '=' in data:
                key, value = data.split('=')
                if key in cls.search_types:
                    return '%s%s%s' % (cls._url, cls.search_types[key], value)
                else:
                    raise JSSUnsupportedSearchMethodError("This object cannot"
                            "be queried by %s." % key)
            else:
                return '%s%s%s' % (cls._url, cls.search_types[cls.default_search], data)

    @classmethod
    def get_post_url(cls):
        """Return the post URL for this object class."""
        return '%s%s%s' % (cls._url, cls.id_url, '0')

    def get_object_url(self):
        """Return the complete API url to this object."""
        return '%s%s%s' % (self._url, self.id_url, self.id)

    def delete(self):
        """Delete this object from the JSS."""
        if not self.can_delete:
            raise JSSMethodNotAllowedError(self.__class__.__name__)
        return self.jss.delete(self.get_object_url())

    def update(self):
        """Update this object on the JSS.

        Data validation is up to the client.

        """
        if not self.can_put:
            raise JSSMethodNotAllowedError(self.__class__.__name__)

        url = self.get_object_url()
        return self.jss.put(url, self.getroot())

    def _indent(self, elem, level=0, more_sibs=False):
        """Indent an xml element object to prepare for pretty printing.

        Method is internal to discourage indenting the self._root Element,
        thus potentially corrupting it.

        """
        i = "\n"
        pad = '    '
        if level:
            i += (level - 1) * pad
        num_kids = len(elem)
        if num_kids:
            if not elem.text or not elem.text.strip():
                elem.text = i + pad
                if level:
                    elem.text += pad
            count = 0
            for kid in elem:
                self._indent(kid, level+1, count < num_kids - 1)
                count += 1
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
                if more_sibs:
                    elem.tail += pad
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i
                if more_sibs:
                    elem.tail += pad

    def __repr__(self):
        """Make our data human readable."""
        # deepcopy so we don't mess with the valid XML.
        pretty_data = copy.deepcopy(self._root)
        self._indent(pretty_data)
        s = ElementTree.tostring(pretty_data)
        return s.encode('utf-8')

    # Shared properties:
    # Almost all JSSObjects have at least name and id properties, so provide a
    # convenient accessor.
    @property
    def name(self):
        """Return object name or None."""
        return self.findtext('name') or \
                    self.findtext('general/name')

    @property
    def id(self):
        """Return object ID or None."""
        # Most objects have ID nested in general. Groups don't.
        result = self.findtext('id') or self.findtext('general/id')
        if result:
            result = int(result)
        return result


class JSSDeviceObject(JSSObject):
    """Provides convenient accessors for properties of devices.

    This is helpful since Computers and MobileDevices allow us to query
    based on these properties.

    """
    @property
    def udid(self):
        return self.findtext('general/udid')

    @property
    def serial_number(self):
        return self.findtext('general/serial_number')


class JSSFlatObject(JSSObject):
    """Subclass for JSS objects which do not return a list of objects."""
    search_types = {}
    @classmethod
    def get_url(cls, data):
        """Return the URL for a get request based on data type."""
        if data is not None:
            raise JSSUnsupportedSearchMethodError("This object cannot"
                    "be queried by %s." % key)
        else:
            return cls._url

    def get_object_url(self):
        """Return the complete API url to this object."""
        return self.get_url(None)


class Account(JSSObject):
    _url = '/accounts'
    container = 'users'
    id_url = '/userid/'
    search_types = {'userid': '/userid/', 'username': '/username/',
                    'name': '/username/'}


class AccountGroup(JSSObject):
    """Account groups are groups of users on the JSS. Within the API
    hierarchy they are actually part of accounts, but I seperated them.

    """
    _url = '/accounts'
    container = 'groups'
    id_url = '/groupid/'
    search_types = {'groupid': '/groupid/', 'groupname': '/groupname/',
                    'name': '/groupname/'}


class ActivationCode(JSSFlatObject):
    _url = '/activationcode'
    can_delete = False
    can_post = False
    can_list = False


class AdvancedComputerSearch(JSSObject):
    _url = '/advancedcomputersearches'


class AdvancedMobileDeviceSearch(JSSObject):
    _url = '/advancedmobiledevicesearches'


class Building(JSSObject):
    _url = '/buildings'


class Category(JSSObject):
    _url = '/categories'


class Class(JSSObject):
    _url = '/classes'


class Computer(JSSDeviceObject):
    """Computer objects include a 'match' search type which queries across
    multiple properties.

    """
    _url = '/computers'
    search_types = {'name': '/name/', 'serial_number': '/serialnumber/',
                    'udid': '/udid/', 'macaddress': '/macadress/',
                    'match': '/match/'}

    @property
    def mac_addresses(self):
        """Return a list of mac addresses for this device."""
        # Computers don't tell you which network device is which.
        mac_addresses = [self.findtext('general/mac_address')]
        if self.findtext('general/alt_mac_address'):
            mac_addresses.append(self.findtext(\
                    'general/alt_mac_address'))
            return mac_addresses


class ComputerCheckIn(JSSFlatObject):
    _url = '/computercheckin'
    can_delete = False
    can_list = False
    can_post = False

class ComputerCommand(JSSObject):
    _url = '/computercommands'
    can_delete = False
    can_put = False


class ComputerExtensionAttribute(JSSObject):
    _url = '/computerextensionattributes'


class ComputerGroup(JSSObject):
    _url = '/computergroups'


class ComputerInventoryCollection(JSSFlatObject):
    _url = '/computerinventorycollection'
    can_list = False
    can_post = False
    can_delete = False


class ComputerInvitation(JSSObject):
    _url = '/computerinvitations'
    can_put = False
    search_types = {'name': '/name/', 'invitation': '/invitation/'}


class ComputerReport(JSSObject):
    _url = '/computerreports'
    can_put = False
    can_post = False
    can_delete = False


class Department(JSSObject):
    _url = '/departments'


class DirectoryBinding(JSSObject):
    _url = '/directorybindings'


class DiskEncryptionConfiguration(JSSObject):
    _url = '/diskencryptionconfigurations'


class DistributionPoint(JSSObject):
    _url = '/distributionpoints'


class DockItem(JSSObject):
    _url = '/dockitems'


class EBook(JSSObject):
    _url = '/ebooks'


# Need to think about how to handle this.
#class FileUpload(JSSObject):
#    _url = '/fileuploads'
#    can_put = False
#    can_delete = False
#    can_get = False
#    can_list = False


class GSXConnection(JSSFlatObject):
    _url = '/gsxconnection'
    can_list = False
    can_post = False
    can_delete = False


class JSSUser(JSSFlatObject):
    """JSSUser is deprecated."""
    _url = '/jssuser'
    can_list = False
    can_post = False
    can_put = False
    can_delete = False
    search_types = {}


class LDAPServer(JSSObject):
    _url = '/ldapservers'


class LicensedSoftware(JSSObject):
    _url = '/licensedsoftware'


class ManagedPreferenceProfile(JSSObject):
    _url = '/managedpreferenceprofiles'


class MobileDevice(JSSDeviceObject):
    """Mobile Device objects include a 'match' search type which queries across
    multiple properties.

    """
    _url = '/mobiledevices'
    search_types = {'name': '/name/', 'serial_number': '/serialnumber/',
                    'udid': '/udid/', 'macaddress': '/macadress/',
                    'match': '/match/'}

    @property
    def wifi_mac_address(self):
        return self.findtext('general/wifi_mac_address')

    @property
    def bluetooth_mac_address(self):
        return self.findtext('general/bluetooth_mac_address') or \
                self.findtext('general/mac_address')


class MobileDeviceApplication(JSSObject):
    _url = '/mobiledeviceapplications'


class MobileDeviceCommand(JSSObject):
    _url = '/mobiledevicecommands'
    can_put = False
    can_delete = False
    search_types = {'name': '/name/', 'uuid': '/uuid/',
                    'command': '/command/'}
    # TODO: This object _can_ post, but it works a little differently
    can_post = False


class MobileDeviceConfigurationProfile(JSSObject):
    _url = '/mobiledeviceconfigurationprofiles'


class MobileDeviceEnrollmentProfile(JSSObject):
    _url = '/mobiledeviceenrollmentprofiles'
    search_types = {'name': '/name/', 'invitation': '/invitation/'}


class MobileDeviceExtensionAttribute(JSSObject):
    _url = '/mobiledeviceextensionattributes'


class MobileDeviceInvitation(JSSObject):
    _url = '/mobiledeviceinvitations'
    can_put = False
    search_types = {'invitation': '/invitation/'}


class MobileDeviceGroup(JSSObject):
    _url = '/mobiledevicegroups'


class MobileDeviceProvisioningProfile(JSSObject):
    _url = '/mobiledeviceprovisioningprofiles'
    search_types = {'name': '/name/', 'uuid': '/uuid/'}


class NetbootServer(JSSObject):
    _url = '/netbootservers'


class NetworkSegment(JSSObject):
    _url = '/networksegments'


class OSXConfigurationProfile(JSSObject):
    _url = '/osxconfigurationprofiles'


class Package(JSSObject):
    _url = '/packages'


class Peripheral(JSSObject):
    _url = '/peripherals'
    search_types = {}


class PeripheralType(JSSObject):
    _url = '/peripheraltypes'
    search_types = {}


class Policy(JSSObject):
    _url = '/policies'


class Printer(JSSObject):
    _url = '/printers'


class RestrictedSoftware(JSSObject):
    _url = '/restrictedsoftware'


class RemovableMACAddress(JSSObject):
    _url = '/removablemacaddresses'


class SavedSearch(JSSObject):
    _url = '/savedsearches'
    can_put = False
    can_post = False
    can_delete = False


class Script(JSSObject):
    _url = '/scripts'


class Site(JSSObject):
    _url = '/sites'


class SoftwareUpdateServer(JSSObject):
    _url = '/softwareupdateservers'


class SMTPServer(JSSFlatObject):
    _url = '/smtpserver'
    id_url = ''
    can_list = False
    can_post = False
    search_types = {}


class JSSObjectTemplate(ElementTree.ElementTree):
    """Base class for generating the skeleton XML required to post a new
    object.

    """
    # I don't see that the JSS requires the <?xml version="1.0"
    # encoding="UTF-8"?> element at the beginning.
    def _indent(self, elem, level=0, more_sibs=False):
        """Indent an xml element object to prepare for pretty printing.

        Method is internal to discourage indenting the self._root Element,
        thus potentially corrupting it.

        """
        i = "\n"
        pad = '    '
        if level:
            i += (level - 1) * pad
        num_kids = len(elem)
        if num_kids:
            if not elem.text or not elem.text.strip():
                elem.text = i + pad
                if level:
                    elem.text += pad
            count = 0
            for kid in elem:
                self._indent(kid, level+1, count < num_kids - 1)
                count += 1
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
                if more_sibs:
                    elem.tail += pad
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i
                if more_sibs:
                    elem.tail += pad

    def __repr__(self):
        """Make our data human readable."""
        # deepcopy so we don't mess with the valid XML.
        pretty_data = copy.deepcopy(self._root)
        self._indent(pretty_data)
        s = ElementTree.tostring(pretty_data)
        return s.encode('utf-8')


class JSSSimpleTemplate(JSSObjectTemplate):
    """Abstract class for simple JSS Objects."""
    template_type = 'abstract_simple_object'
    def __init__(self, name):
        self._root = ElementTree.Element(self.template_type)
        element_name = ElementTree.SubElement(self._root, "name")
        element_name.text = name


class JSSCategoryTemplate(JSSSimpleTemplate):
    template_type = 'category'


class JSSPolicyTemplate(JSSObjectTemplate):
    def __init__(self):
        super(JSSPolicyTemplate, self).__init__(self, file='doc/policy_template.xml')


class JSSPackageTemplate(JSSObjectTemplate):
    """Template for constructing package objects."""
    def __init__(self, filename, cat_name):
        self._root = ElementTree.Element("package")
        name = ElementTree.SubElement(self._root, "name")
        name.text = filename
        category = ElementTree.SubElement(self._root, "category")
        category.text = cat_name
        fname = ElementTree.SubElement(self._root, "filename")
        fname.text = filename
        ElementTree.SubElement(self._root, "info")
        ElementTree.SubElement(self._root, "notes")
        priority = ElementTree.SubElement(self._root, "priority")
        priority.text = "10"
        reboot = ElementTree.SubElement(self._root, "reboot_required")
        reboot.text = "false"
        fut = ElementTree.SubElement(self._root, "fill_user_template")
        fut.text = "false"
        feu = ElementTree.SubElement(self._root, "fill_existing_users")
        feu.text = "false"
        boot_volume = ElementTree.SubElement(self._root, "boot_volume_required")
        boot_volume.text = "false"
        allow_uninstalled = ElementTree.SubElement(self._root, "allow_uninstalled")
        allow_uninstalled.text = "false"
        ElementTree.SubElement(self._root, "os_requirements")
        required_proc = ElementTree.SubElement(self._root, "required_processor")
        required_proc.text = "None"
        switch_w_package = ElementTree.SubElement(self._root, "switch_with_package")
        switch_w_package.text = "Do Not Install"
        install_if = ElementTree.SubElement(self._root, "install_if_reported_available")
        install_if.text = "false"
        reinstall_option = ElementTree.SubElement(self._root, "reinstall_option")
        reinstall_option.text = "Do Not Reinstall"
        ElementTree.SubElement(self._root, "triggering_files")
        send_notification = ElementTree.SubElement(self._root, "send_notification")
        send_notification.text = "false"



class JSSListData(dict):
    """Holds information retrieved as part of a list operation."""
    def __init__(self, obj_class, d):
        self.obj_class = obj_class
        super(JSSListData, self).__init__(d)

    @property
    def id(self):
        return int(self['id'])

    @property
    def name(self):
        return self['name']

class JSSObjectList(list):
    """A list style collection of JSSObjects.

    List operations retrieve only minimal information for most object types.
    Further, we may want to know all Computer(s) to get their ID's, but that
    does not mean we want to do a full object search for each one. Thus,
    methods are provided to both retrieve individual members' full
    information, and to retrieve the full information for the entire list.

    """
    def __init__(self, factory, obj_class, objects):
        self.factory = factory
        self.obj_class = obj_class
        super(JSSObjectList, self).__init__(objects)


    def __repr__(self):
        """Make our data human readable.

        Note: Large lists of large objects may take a long time due to
        indenting!

        """
        delimeter = 50 * '-' + '\n'
        s = delimeter
        for object in self:
            s += "List index: \t%s\n" % self.index(object)
            for k, v in object.items():
                s += "%s:\t\t%s\n" % (k, v)
            s += delimeter
        return s.encode('utf-8')

    def sort(self):
        """Sort list elements by ID."""
        super(JSSObjectList, self).sort(key=lambda k: k.id)

    def sort_by_name(self):
        super(JSSObjectList, self).sort(key=lambda k: k.name)

    def retrieve(self, index):
        """Return a JSSObject for the JSSListData element at index."""
        return self.factory.get_object(self.obj_class, self[index].id)

    def retrieve_by_id(self, id_):
        """Return a JSSObject for the JSSListData element with ID id_."""
        list_index = [int(i) for i, j in enumerate(self) if j.id == id_]
        if len(list_index) == 1:
            list_index = list_index[0]
            return self.factory.get_object(self.obj_class, self[list_index].id)

    def retrieve_all(self):
        """Return a list of all JSSListData elements as full JSSObjects.

        At least on my JSS, I end up with some harmless SSL errors, which are
        dealth with.

        Note: This can take a long time given a large number of objects, and
        depending on the size of each object.

        """
        final_list = []
        for i in range(0, len(self)):
            result = []
            while result == []:
                try:
                    result = self.factory.get_object(self.obj_class, int(self[i]['id']))
                except requests.exceptions.SSLError as e:
                    print("SSL Exception: %s\nTrying again." % e)

            final_list.append(result)
        return final_list

from twisted.internet import reactor, defer
from twisted.application.service import IService, Service
from twisted.cred.portal import IRealm, Portal
from twisted.cred.checkers import ICredentialsChecker
from axiom.attributes import integer, inmemory, bytes, reference, timestamp
from axiom.item import Item, InstallableMixin
from axiom.slotmachine import hyper as super
from epsilon.extime import Time
from sine import sip
from xmantissa import ixmantissa, website, webapp
from zope.interface import implements

import time

class SIPConfigurationError(RuntimeError):
    """You specified some invalid configuration."""


class SIPServer(Item, Service):
    typeName = 'mantissa_sip_powerup'
    schemaVersion = 1
    portno = integer(default=5060)
    hostnames =  bytes()
    installedOn = reference()
    
    parent = inmemory()
    running = inmemory()
    name = inmemory()

    proxy = inmemory()
    port = inmemory()
    site = inmemory()

    def installOn(self, other):
        assert self.installedOn is None, "You cannot install a SIPServer on more than one thing"
        other.powerUp(self, IService)
        self.installedOn = other

    def privilegedStartService(self):
        realm = IRealm(self.store, None)
        if realm is None:
            raise SIPConfigurationError(
                'No realm: '
                'you need to install a userbase before using this service.')
        chkr = ICredentialsChecker(self.store, None)
        if chkr is None:
            raise SIPConfigurationError(
                'No checkers: '
                'you need to install a userbase before using this service.')
        portal = Portal(realm, [chkr])
        self.proxy = sip.Proxy(portal)

        f = sip.SIPTransport(self.proxy, self.hostnames.split(','), self.portno)
        self.port = reactor.listenUDP(self.portno, f)

class SineBenefactor(Item):
    implements(ixmantissa.IBenefactor)

    typeName = 'sine_benefactor'
    schemaVersion = 1

    # Number of users this benefactor has endowed
    endowed = integer(default = 0)

    def endow(self, ticket, avatar):
        self.endowed += 1

        avatar.findOrCreate(website.WebSite).installOn(avatar)
        avatar.findOrCreate(webapp.PrivateApplication).installOn(avatar)
        avatar.findOrCreate(TrivialContact).installOn(avatar)

class TrivialContact(Item, InstallableMixin):
    implements(sip.IContact)

    typeName = "sine_trivialcontact"
    schemaVersion = 1

    physicalURL = bytes()
    expiryTime = timestamp()

    def installOn(self, other):
        super(TrivialContact, self).installOn(other)
        other.powerUp(self, sip.IContact)

    def registerAddress(self, physicalURL, expiryTime):
        self.physicalURL = str(physicalURL)
        self.expiryTime = Time.fromPOSIXTimestamp(expiryTime)

    def unregisterAddress(self, physicalURL):
        if self.physicalURL != physicalURL:
            raise ValueError, "what"
        self.physicalURL = None

    def getRegistrationInfo(self):
        registered = False
        if self.physicalURL is not None:
            now = time.time()
            if now < self.expiryTime:
                registered = True
        if registered:
            return [(self.physicalURL, int(self.expiryTime.asPOSIXTimestamp() - now))]
        else:
            return defer.fail(sip.RegistrationError(480))
 

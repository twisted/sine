import time

from zope.interface import implements

from twisted.python.util import sibpath
from twisted.internet import reactor, defer
from twisted.python.components import registerAdapter
from twisted.application.service import IService, Service
from twisted.cred.portal import IRealm, Portal
from twisted.cred.checkers import ICredentialsChecker

from nevow import athena, tags, static

from epsilon.extime import Time

from axiom import userbase, batch
from axiom.attributes import integer, inmemory, bytes, text, reference, timestamp, AND
from axiom.item import Item, InstallableMixin
from axiom.slotmachine import hyper as super
from axiom.errors import NoSuchUser

from xmantissa import ixmantissa, website, webapp, liveform
from xmantissa import prefs, webnav, tdb, tdbview
from xmantissa.webtheme import getLoader
from xmantissa.publicresource import PublicPage

import sine
from sine import sip, useragent, tpcc


class SIPConfigurationError(RuntimeError):
    """You specified some invalid configuration."""


class SIPServer(Item, Service, InstallableMixin):
    typeName = 'mantissa_sip_powerup'
    schemaVersion = 1
    portno = integer(default=5060)
    hostnames =  bytes(default="localhost")
    installedOn = reference()
    pstn = bytes()
    parent = inmemory()
    running = inmemory()
    name = inmemory()

    proxy = inmemory()
    dispatcher = inmemory()
    mediaController = inmemory()
    port = inmemory()
    site = inmemory()
    transport = inmemory()

    def installOn(self, other):
        super(SIPServer, self).installOn(other)
        other.powerUp(self, IService)
        if self.parent is None:
            self.setServiceParent(other)


    def startService(self):
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

        tacPath = sibpath(sine.__file__, "media.tac")
        self.mediaController = batch.ProcessController(
            "rtp-transceiver",
            useragent.LocalControlProtocol(False),
            tacPath=tacPath)

        if self.pstn:
            pstnurl = sip.parseURL(self.pstn)
            portal = PSTNPortalWrapper(Portal(realm, [chkr]), pstnurl.host, pstnurl.port)
        else:
            portal = Portal(realm, [chkr])
        self.proxy = sip.Proxy(portal)
        self.dispatcher = sip.SIPDispatcher(portal, self.proxy)
        regs = list(self.store.query(Registration, Registration.parent==self))
        if regs:
            rc = sip.RegistrationClient()
            self.proxy.installRegistrationClient(rc)
            for reg in regs:
                if not (reg.username and reg.domain):
                    raise SIPConfigurationError("Bad registration URL:", "You need both a username and a domain to register")
                rc.register(reg.username, reg.password, reg.domain)
                self.proxy.addProxyAuthentication(reg.username, reg.domain, reg.password)
        self.transport = sip.SIPTransport(self.dispatcher, self.hostnames.split(','), self.portno)
        self.port = reactor.listenUDP(self.portno, self.transport)

    def get_hostname(self):
        return self.hostnames.split(',')[0]
    hostname = property(get_hostname)


    def setupCallBetween(self, partyA, partyB):
        """
        Set up a call between party A and party B, and control the
        signalling for the call.  Either URL may refer to any SIP
        address, there is no requirement that either participant be
        registered with this proxy.

        @param partyA: a SIP address (a three-tuple of (name, URL,
        parameters)) that represents the party initiating the call,
        i.e. the SIP address of the user who is logged in to the web
        UI and pushing the button to place the call. (Specifically,
        this is the user who will be called first and will have to
        wait for the other user to pick up the call.)

        @param partyB: a SIP address that represents the party receiving
        the call.

        @return: None
        """
        # XXX TODO should probably return a deferred which
        # fires... something... that would let us take advantage of
        # the intermediary call signalling, such as ending the call
        # early...
        localpart = "clicktocall"
        host = self.hostnames.split(',')[0]
        controller = tpcc.ThirdPartyCallController(self.dispatcher, localpart, host, self.mediaController, partyA[0], partyB[1])
        uac = useragent.UserAgent.client(controller, localpart, host, self.mediaController, self.dispatcher.dialogs)
        uac.transport = self.dispatcher.transport
        self.dispatcher.installTemporaryProcessor(sip.URL(host, localpart), uac)

        uac._doCall(partyA[1], "Divmod")

class Registration(Item):
    typename = "sine_registration"
    schemaVersion = 1
    parent = reference()
    username = text()
    domain = text()
    password = text()

class _LocalpartPreference(prefs.Preference):
    def __init__(self, value, collection):
        prefs.Preference.__init__(self, 'localpart', value,
                                  'Localpart', collection, 'Localpart')

    def choices(self):
        return None

    def displayToValue(self, display):
        value = unicode(display)
        store = self.collection.store.parent

        for loginMethod in store.query(userbase.LoginMethod,
                                       AND(userbase.LoginMethod.localpart == value,
                                       userbase.LoginMethod.protocol == u'sip')):
            raise prefs.PreferenceValidationError('Localpart is not unique')
        return value

    def valueToDisplay(self, value):
        return str(value)

    def settable(self):
        return self.value is None

class ListenToRecordingAction(tdbview.Action):
    def __init__(self):
        tdbview.Action.__init__(self, 'listen',
                            '/Sine/static/images/listen.png',
                            'Listen to this recording')
    def toLinkStan(self, idx, item):
            return tags.a(href='/' + item.prefixURL)[
                tags.img(src=self.iconURL, border=0)]

    def performOn(self, recording):
        raise NotImplementedError()

    def actionable(self, thing):
        return True

class SinePublicPage(Item, InstallableMixin):
    implements(ixmantissa.IPublicPage)

    typeName = 'sine_public_page'
    schemaVersion = 1

    installedOn = reference()

    def installOn(self, other):
        super(SinePublicPage, self).installOn(other)
        other.powerUp(self, ixmantissa.IPublicPage)

    def getResource(self):
        return PublicIndexPage(self,
                ixmantissa.IStaticShellContent(self.installedOn, None))

class PublicIndexPage(PublicPage):
    implements(ixmantissa.ICustomizable)

    title = 'Sine'

    def __init__(self, original, staticContent, forUser=None):
        super(PublicIndexPage, self).__init__(
                original, tags.h1["Sine"], staticContent, forUser)

    def child_static(self, ctx):
        return static.File(sibpath(__file__, 'static'))

    def customizeFor(self, forUser):
        return self.__class__(self.original, self.staticContent, forUser)

class SinePreferenceCollection(Item, InstallableMixin):

    implements(ixmantissa.IPreferenceCollection)

    schemaVersion = 1
    typeName = 'sine_preference_collection'
    applicationName = 'Sine'

    installedOn = reference()
    localpart = text()
    _cachedPrefs = inmemory()

    def installOn(self, other):
        super(SinePreferenceCollection, self).installOn(other)
        other.powerUp(self, ixmantissa.IPreferenceCollection)

    def activate(self):
        self._cachedPrefs = {"localpart": _LocalpartPreference(self.localpart, self)}

    def getPreferences(self):
        return self._cachedPrefs

    def _localpartSet(self):
        # localpart can only be set once - so we'll create a
        # LoginMethod the first and only time it's value changes

        substore = self.store.parent.getItemByID(self.store.idInParent)
        hostname = self.store.parent.findUnique(SIPServer).hostname

        for acc in self.store.parent.query(userbase.LoginAccount,
                                           userbase.LoginAccount.avatars == substore):

            userbase.LoginMethod(store=self.store.parent,
                                localpart=self.localpart,
                                internal=True,
                                protocol=u'sip',
                                verified=True,
                                domain=unicode(hostname),
                                account=acc)
            break

    def setPreferenceValue(self, pref, value):
        assert hasattr(self, pref.key)
        setattr(pref, 'value', value)
        setattr(self, pref.key, value)

        if pref.key == 'localpart':
            self._localpartSet()

    def getSections(self):
        return None

class SineBenefactor(Item):
    implements(ixmantissa.IBenefactor)

    typeName = 'sine_benefactor'
    schemaVersion = 1
    domain=text()
    # Number of users this benefactor has endowed
    endowed = integer(default = 0)

    def endow(self, ticket, avatar):
        self.endowed += 1
        avatar.findOrCreate(website.WebSite).installOn(avatar)
        avatar.findOrCreate(webapp.PrivateApplication).installOn(avatar)
        avatar.findOrCreate(SinePreferenceCollection).installOn(avatar)
        avatar.findOrCreate(TrivialContact).installOn(avatar)
        from sine import voicemail, confession
        avatar.findOrCreate(voicemail.VoicemailDispatcher).installOn(avatar)
        avatar.findOrCreate(confession.AnonConfessionUser).installOn(avatar)
class PSTNContact:
    implements(sip.IContact)
    def __init__(self, avatarId, targethost, targetport):
        self.id = avatarId
        self.targetport = targetport
        self.targethost = targethost

    def getRegistrationInfo(self, caller):
        return [(sip.URL(self.targethost, port=self.targetport, username=self.id), 0)]

    def callIncoming(self, name, uri, caller):
        if caller is None:
            # ta da
            raise sip.SIPError(401)

    def registerAddress(self, *args):
        from twisted.cred.error import UnauthorizedLogin
        raise UnauthorizedLogin

    def incompleteImplementation(self, *args, **kw):
        raise NotImplementedError("Asterisk PSTN numbers are NOT general-purpose IContacts!")

    unregisterAddress = incompleteImplementation
    callOutgoing = incompleteImplementation

class PSTNPortalWrapper:

    def __init__(self, realPortal, targetHost, targetPort):
        self.realPortal = realPortal
        self.targethost = targetHost
        self.targetport = targetPort

    def login(self, credentials, mind, interface):
        D = self.realPortal.login(credentials, mind, interface)
        def logcb(thing):
            return thing
        def eb(fail):
            fail.trap(NoSuchUser)
            localpart = credentials.username.split('@')[0]
            if interface == sip.IContact and localpart.isdigit():
                return (interface, PSTNContact(localpart, self.targethost, self.targetport), lambda: None)
            else:
                return fail
        D.addCallback(logcb)
        D.addErrback(eb)
        return D

class TrivialContact(Item, InstallableMixin):
    implements(sip.IContact, ixmantissa.INavigableElement)

    typeName = "sine_trivialcontact"
    schemaVersion = 1

    physicalURL = bytes()
    altcontact = bytes()
    expiryTime = timestamp()
    installedOn = reference()

    def installOn(self, other):
        super(TrivialContact, self).installOn(other)
        other.powerUp(self, ixmantissa.INavigableElement)
        other.powerUp(self, sip.IContact)

    def registerAddress(self, physicalURL, expiryTime):
        self.physicalURL = physicalURL.toString()
        self.expiryTime = Time.fromPOSIXTimestamp(time.time() + expiryTime)
        return [(physicalURL, self.expiryTime)]

    def unregisterAddress(self, physicalURL):
        storedURL = sip.parseURL(self.physicalURL)
        if storedURL != physicalURL:
            raise ValueError, "what"
        self.physicalURL = None
        return [(physicalURL, 0)]

    def getRegistrationInfo(self, caller):
        registered = False
        if self.physicalURL is not None:
            now = time.time()
            if now < self.expiryTime.asPOSIXTimestamp():
                registered = True
        if registered:
            return [(sip.parseURL(self.physicalURL), int(self.expiryTime.asPOSIXTimestamp() - now))]
        elif self.altcontact:
            return [(sip.parseURL(self.altcontact), -1)]
        else:
            return defer.fail(sip.RegistrationError(480))

    def placeCall(self, target):
        svc = self.store.parent.findUnique(SIPServer)
        svc.setupCallBetween(("", self.getRegistrationInfo(target)[0][0], {}),
                             ("", target, {}))

    def callIncoming(self, name, uri, caller):
        Call(store=self.store, name=name, time=Time(), uri=unicode(str(uri)), kind=u'from')

    def callOutgoing(self, name, uri):
        Call(store=self.store, name=name, time=Time(), uri=unicode(str(uri)), kind=u'to')

    def getTabs(self):
        return [webnav.Tab('Voice', self.storeID, 0.0)]

class TrivialContactFragment(athena.LiveFragment):
    implements(ixmantissa.INavigableFragment)

    fragmentName = 'trivial-contact'
    live = 'athena'
    title = ''

    def data_physicalURL(self, ctx, data):
        return self.original.physicalURL or self.original.altcontact or 'Unregistered'

    def data_expiryTime(self, ctx, data):
        expiryTime = self.original.expiryTime
        if expiryTime is not None and expiryTime != -1:
            return expiryTime.asHumanly()
        return 'No Expiry'

    def render_callTDB(self, ctx, data):
        prefs = ixmantissa.IPreferenceAggregator(self.original.store)

        tdm = tdb.TabularDataModel(self.original.store,
                                   Call, (Call.time, Call.uri, Call.kind),
                                   itemsPerPage=prefs.getPreferenceValue('itemsPerPage'))

        cviews = (tdbview.DateColumnView('time'),
                  tdbview.ColumnViewBase('uri'),
                  tdbview.ColumnViewBase('kind'))

        tdv = tdbview.TabularDataView(tdm, cviews, width='100%')
        tdv.docFactory = getLoader(tdv.fragmentName)
        tdv.setFragmentParent(self)
        return tdv

    def render_voicemailTDB(self, ctx, data):
        from sine.confession import Recording
        prefs = ixmantissa.IPreferenceAggregator(self.original.store)

        tdm = tdb.TabularDataModel(self.original.store,
                                   Recording, (Recording.fromAddress, Recording.length, Recording.time),
                                   itemsPerPage=prefs.getPreferenceValue('itemsPerPage'))

        cviews = (tdbview.ColumnViewBase('fromAddress'),
                  tdbview.ColumnViewBase('length'),
                  tdbview.DateColumnView('time'))

        tdv = tdbview.TabularDataView(tdm, cviews,  (ListenToRecordingAction(),),width='100%')
        tdv.docFactory = getLoader(tdv.fragmentName)
        tdv.setFragmentParent(self)
        return tdv

    def render_altcontactForm(self, ctx, data):
        lf = liveform.LiveForm(self.setAltContact, [liveform.Parameter(
        "altcontact", liveform.TEXT_INPUT, self.parseURLorPhoneNum, "An alternate SIP URL or phone number to forward calls to when you are not registered", "")], "Set")
        lf.setFragmentParent(self)
        return lf

    def render_placeCall(self, ctx, data):
        lf = liveform.LiveForm(self.original.placeCall, [liveform.Parameter(
            "target", liveform.TEXT_INPUT, self.parseURLorPhoneNum, "Place call:")])
        lf.setFragmentParent(self)
        return lf

    def parseURLorPhoneNum(self, val):
        pstn = self.original.store.parent.findUnique(SIPServer).pstn
        if '@' in val:
            if not val.startswith("sip:"):
                val = "sip:" + val
            return sip.parseURL(val)
        elif pstn:
            pstnurl = sip.parseURL(pstn)
            num = ''.join([c for c in val if c.isdigit()])
            pstn = self.original.store.parent.findUnique(SIPServer).pstn
            if len(num) == 10:
                return sip.URL(host=pstnurl.host, username="1"+num, port=pstnurl.port)
            elif len(num) == 11 and num[0] == '1':
                return sip.URL(host=pstnurl.host, username=num, port=pstnurl.port)
            else:
                raise liveform.InvalidInput("Please enter a SIP URL or a North American ten-digit phone number.")
        else:
            raise liveform.InvalidInput("Please enter a SIP URL.")

    def setAltContact(self, altcontact):
        self.original.altcontact = str(altcontact)

    def head(self):
        return None


registerAdapter(TrivialContactFragment, TrivialContact, ixmantissa.INavigableFragment)

class SIPDispatcherService(Item, Service):
    typeName = 'sine_sipdispatcher_service'
    schemaVersion = 1
    portno = integer(default=5060)
    hostnames =  bytes()
    installedOn = reference()

    parent = inmemory()
    running = inmemory()
    name = inmemory()

    dispatcher = inmemory()
    proxy = inmemory()
    port = inmemory()
    site = inmemory()

    def installOn(self, other):
        assert self.installedOn is None, "You cannot install a SIPDispatcherService on more than one thing"
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
        self.dispatcher = sip.SIPDispatcher(portal, self.proxy)
        f = sip.SIPTransport(self.dispatcher, self.hostnames.split(','), self.portno)
        self.port = reactor.listenUDP(self.portno, f)

class Call(Item):
    typeName = "sine_call"
    schemaVersion = 1
    name=text()
    uri = text()
    time = timestamp()
    kind = text()

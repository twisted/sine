import os, getpass

from zope.interface import classProvides

from twisted.python import usage, util
from twisted.cred import portal
from twisted import plugin
from axiom.scripts import axiomatic
from axiom import iaxiom, errors as eaxiom, userbase, scheduler
from sine import sipserver

from xmantissa import webadmin, website, signup
from vertex.scripts import certcreate

class Install(usage.Options, axiomatic.AxiomaticSubCommandMixin):
    "Install a SIP proxy and registrar backed by an Axiom user database."

    longdesc = __doc__

    optParameters = [
        ('domain', 'd', 'localhost',
         "Domain this registrar is authoritative for;\
         i.e., the domain local users belong to."),
        ('port', 'p', '5060',
         'Port to listen on for SIP.'),
        ('pstn', None, '',
         'SIP URL that PSTN calls should be directed to.' ),
        ]

    def postOptions(self):
        s = self.parent.getStore()
        svc = s.findOrCreate(sipserver.SIPServer,
                       portno=int(self['port']),
                       hostnames=self['domain'],
                       pstn=self['pstn'])
        svc.installOn(s)

        s.findOrCreate(scheduler.Scheduler).installOn(s)
        s.findOrCreate(userbase.LoginSystem).installOn(s)

        for ws in s.query(website.WebSite):
            break
        else:
            website.WebSite(
                store=s,
                portNumber=8081,
                securePortNumber=8444,
                certificateFile='server.pem').installOn(s)
            if not os.path.exists('server.pem'):
                certcreate.main([])

        s.findOrCreate(
            website.StaticSite,
            prefixURL=u'static/sine',
            staticContentPath=util.sibpath(sipserver.__file__, u'static')).installOn(s)

        booth = s.findOrCreate(signup.TicketBooth)
        booth.installOn(s)

        benefactor = s.findOrCreate(sipserver.SineBenefactor, domain=unicode(self['domain']))

        ticketSignup = s.findOrCreate(
            signup.FreeTicketSignup,
            prefixURL=u'signup',
            benefactor=benefactor,
            booth=booth)

        ticketSignup.installOn(s)

class AddUser(usage.Options, axiomatic.AxiomaticSubCommandMixin):
    "Add a SIP proxy user."

    longdesc = __doc__
    synopsis = "<username> <domain> [password]"

    def parseArgs(self, username, domain, password=None):
        self['username'] = self.decodeCommandLine(username)
        self['domain'] = self.decodeCommandLine(domain)
        self['password'] = password

    def postOptions(self):
        for ls in self.store.query(userbase.LoginSystem):
            break
        else:
            raise usage.UsageError("No userbase found!")

        msg = 'Enter new SIP password: '
        while not self['password']:
            password = getpass.getpass(msg)
            second = getpass.getpass('Repeat to verify: ')
            if password == second:
                self['password'] = password
            else:
                msg = 'Passwords do not match.  Enter new SIP password: '

        try:
            acc = ls.addAccount(unicode(self['username']),
                                unicode(self['domain']),
                                unicode(self['password']))
            userbase.LoginMethod(store=self.store,
                                 localpart=self['username'],
                                 internal=True,
                                 protocol=u'sip',
                                 verified=True,
                                 domain=self['domain'],
                                 account=acc)
            av = acc.avatars.open()
            av.findOrCreate(sipserver.TrivialContact).installOn(av)
        except userbase.DuplicateUser:
            raise usage.UsageError("An account by that name already exists.")


class Register(usage.Options, axiomatic.AxiomaticSubCommandMixin):
    "Add an account on another host for the proxy to register with on startup."

    longdesc = __doc__
    synopsis = "<username> <domain> [password]"

    def parseArgs(self, username, domain, password=None):
        self['username'] = self.decodeCommandLine(username)
        self['domain'] = self.decodeCommandLine(domain)
        self['password'] = password

    def postOptions(self):
        s = self.parent.getStore()
        srv = s.findUnique(sipserver.SIPServer)
        if not self['username'] and self['domain']:
            raise usage.UsageError("Both a username and domain are required")
        r = sipserver.Registration(store=s,username=self['username'], password=unicode(self['password']), 
                               domain=self['domain'], parent=srv)
        print vars(r)

class SIPProxyConfiguration(usage.Options, axiomatic.AxiomaticSubCommandMixin):
    classProvides(plugin.IPlugin, iaxiom.IAxiomaticCommand)

    name = "sip-proxy"
    description = "SIP proxy and registrar"

    longdesc = __doc__

    optParameters = [
        ('ticket-signup-url', None, 'signup', 'URL at which to place a ticket request page')]

    subCommands = [('install', None, Install, "Install SIP Proxy components"),
                   ('adduser', None, AddUser, "Add a SIP user"),
                   ('register', None, Register, "Register with an external SIP registrar")
                  ] 
    didSomething = False

    def getStore(self):
        return self.parent.getStore()

    def _benefactorAndSignup(self):
        s = self.getStore()
        bene = s.findUnique(sipserver.SineBenefactor)

        ticketSignup = s.findUnique(
            signup.FreeTicketSignup,
            signup.FreeTicketSignup.benefactor == bene)
        return bene, ticketSignup

    def postOptions(self):
        s = self.getStore()

        def _():
            try:
                benefactor, ticketSignup = self._benefactorAndSignup()
            except eaxiom.ItemNotFound:
                raise usage.UsageError("SIP Proxy components not yet installed.")

            if self['ticket-signup-url'] is not None:
                self.didSomething = True
                ticketSignup.prefixURL = self.decodeCommandLine(self['ticket-signup-url'])

        s.transact(_)
        if not self.didSomething:
            self.opt_help()

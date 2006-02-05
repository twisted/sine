import os

from twisted.python import usage
from twisted.cred import portal
from vertex.scripts import certcreate

from axiom import errors as eaxiom, scheduler, userbase
from axiom.scripts import axiomatic

from xmantissa import signup, website
from sine import confession, echo

class Install(axiomatic.AxiomaticSubCommand):
    longdesc = """
    Install confession things
    """


    optParameters = [
        ('domain', 'd', 'localhost',
         "Domain this registrar is authoritative for;\
         i.e., the domain local users belong to."),
        ('port', 'p', '5060',
         'Port to listen on for SIP.')
        ]

    def postOptions(self):
        s = self.parent.getStore()
        s.findOrCreate(scheduler.Scheduler).installOn(s)
        s.findOrCreate(userbase.LoginSystem).installOn(s)

        for ws in s.query(website.WebSite):
            break
        else:
            website.WebSite(
                store=s,
                portNumber=8080,
                securePortNumber=8443,
                certificateFile='server.pem').installOn(s)
            if not os.path.exists('server.pem'):
                certcreate.main([])

        booth = s.findOrCreate(signup.TicketBooth)
        booth.installOn(s)

        benefactor = s.findOrCreate(confession.ConfessionBenefactor, localHost=self['domain'])

        ticketSignup = s.findOrCreate(
            signup.FreeTicketSignup,
            benefactor=benefactor,
            prefixURL=u'signup',
            booth=booth)
        ticketSignup.installOn(s)


        #Is there a real way to do this?
        u = portal.IRealm(s).addAccount(u'confession', self['domain'], u'no password :(')
        us = u.avatars.open()
        confession.AnonConfessionUser(store=us).installOn(us)
        confession.ConfessionDispatcher(store=us, localHost=self['domain']).installOn(us)
        
        #u = portal.IRealm(s).addAccount(u'echo', self['domain'], u'no password :(')
        #us = u.avatars.open()
        #echo.EchoTest(store=us).installOn(us)
        #echo.EchoDispatcher(store=us, localHost=self['domain']).installOn(us)
        
class ConfessionConfiguration(axiomatic.AxiomaticCommand):
    name = 'confession-site'
    description = 'Chronicler of confessions'

    subCommands = [
        ('install', None, Install, "Install site-wide Confession components"),
        ]

    optParameters = [
        ('ticket-signup-url', None, 'signup', 'URL at which to place a ticket request page')]

    didSomething = False

    def getStore(self):
        return self.parent.getStore()

    def _benefactorAndSignup(self):
        s = self.getStore()
        bene = s.findUnique(confession.ConfessionBenefactor)

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
                raise usage.UsageError("Site-wide Confession components not yet installed.")

            if self['ticket-signup-url'] is not None:
                self.didSomething = True
                ticketSignup.prefixURL = self.decodeCommandLine(self['ticket-signup-url'])

        s.transact(_)
        if not self.didSomething:
            self.opt_help()


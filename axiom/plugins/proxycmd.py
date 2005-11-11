import os

from zope.interface import classProvides

from twisted.python import usage, util
from twisted.cred import portal
from twisted import plugin
from axiom.scripts import axiomatic
from axiom import iaxiom, errors as eaxiom, userbase, scheduler
from sine import sipserver

from xmantissa import webadmin, website, signup
from vertex.scripts import certcreate

class SIPProxy(usage.Options, axiomatic.AxiomaticSubCommandMixin):
    "A SIP proxy and registrar backed by an Axiom user database."

    classProvides(plugin.IPlugin, iaxiom.IAxiomaticCommand)

    name = "sip-proxy"
    description = "SIP proxy and registrar"

    longdesc = __doc__

    optParameters = [
        ('domain', 'd', 'localhost',
         "Domain this registrar is authoritative for;\
         i.e., the domain local users belong to."),
        ('port', 'p', '5060',
         'Port to listen on for SIP.')
        ]

    def postOptions(self):
        s = self.parent.getStore()
        svc = s.findOrCreate(sipserver.SIPServer,
                       portno=int(self['port']),
                       hostnames=self['domain'])
        svc.installOn(s)

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

        benefactor = s.findOrCreate(sipserver.SineBenefactor)

        ticketSignup = s.findOrCreate(
            signup.FreeTicketSignup,
            prefixURL=u'signup',
            benefactor=benefactor,
            booth=booth)

        ticketSignup.installOn(s)


import os
from zope.interface import classProvides

from twisted.python import usage
from twisted import plugin
from twisted.cred import portal
from twisted.application.service import IService, Service
from vertex.scripts import certcreate

from axiom import iaxiom, errors as eaxiom, scheduler, userbase, item, attributes
from axiom.scripts import axiomatic

from xmantissa import signup, website
from sine import confession, sipserver, echo, sip

class TPCC(usage.Options, axiomatic.AxiomaticSubCommandMixin):
    classProvides(plugin.IPlugin, iaxiom.IAxiomaticCommand)
    longdesc = """
    Install TPCC tester (calls washort@divmod.com, confession@watt.divmod.com)
    """

    name = '3pcc'
    description = '3pcc hooray'
    optParameters = [
        ('domain', 'd', 'faraday.divmod.com',
         "the domain local users belong to."),
        ('port', 'p', '5060',
         'Port to listen on for SIP.')
        ]

    def postOptions(self):
        s = self.parent.getStore()
        s.findOrCreate(scheduler.Scheduler).installOn(s)
        s.findOrCreate(userbase.LoginSystem).installOn(s)
        svc = s.findOrCreate(sipserver.SIPDispatcherService, hostnames=self['domain'])
        svc.installOn(s)
        testsvc = s.findOrCreate(TestService, dispatcherSvc=svc)
        testsvc.installOn(s)
        
class TestService(item.Item, Service):
    typeName = 'sine_tpcc_test_service'
    schemaVersion = 1
    installedOn = attributes.reference()
    parent = attributes.inmemory()
    running = attributes.inmemory()
    name = attributes.inmemory()

    dispatcherSvc = attributes.reference()

    def installOn(self, other):
        other.powerUp(self, IService)
        self.installedOn = other

    def startService(self):
        print "YAY"
        self.dispatcherSvc.setupCallBetween(
            ("Confession Hotline (watt)", sip.URL("watt.divmod.com", "confession"), {},),
            ("Some Bozo", sip.URL("divmod.com", "washort"), {}),
            )

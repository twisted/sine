
from zope.interface import classProvides

from twisted.python import usage, util
from twisted.cred import portal
from twisted import plugin
from axiom.scripts import axiomatic
from axiom import iaxiom, errors as eaxiom, userbase
from sine import sipserver

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
        svc = sipserver.SIPServer(store=s,portno=int(self['port']),
                                  hostnames=self['domain'])
        svc.installOn(s)

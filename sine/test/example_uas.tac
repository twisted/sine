from twisted.application import service, internet
from sine import sip
HOSTNAME = LOCAL_HOST = "faraday.divmod.com"
uas = sip.SimpleCallAcceptor(LOCAL_HOST)
f = sip.SIPTransport(uas, [HOSTNAME], 5060)

application = service.Application("example_uas")
internet.UDPServer(5060, f).setServiceParent(application)

from twisted.application import service, internet
from sine import useragent, sip
HOSTNAME = LOCAL_HOST = "watt.divmod.com"
uas = useragent.SimpleCallAcceptor(LOCAL_HOST)
f = sip.SIPTransport(uas, [HOSTNAME], 5060)

application = service.Application("example_uas")
internet.UDPServer(5060, f).setServiceParent(application)

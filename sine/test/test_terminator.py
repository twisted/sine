from xshtoom.sdp import SDP, MediaDescription
from xshtoom.rtp.formats import PT_PCMU
from sine.test.test_sip import FakeClockTestCase
from sine import sip, useragent
from twisted.internet import reactor, defer
from twisted.trial import unittest
from zope.interface import implements
from axiom import store, userbase, item, attributes

exampleInvite = """INVITE sip:bob@proxy2.org SIP/2.0\r
Via: SIP/2.0/UDP client.com:5060;branch=z9hG4bK74bf9\r
Max-Forwards: 70\r
From: Alice <sip:alice@proxy1.org>;tag=9fxced76sl\r
To: Bob <sip:bob@proxy2.org>\r
Call-ID: 3848276298220188511@client.com\r
CSeq: 1 INVITE\r
Contact: <sip:alice@client.com>\r
\r
v=0\r
o=alice 2890844526 2890844526 IN IP4 server.com\r
s=-\r
c=IN IP4 10.0.0.1\r
t=0 0\r
m=audio 49172 RTP/AVP 0\r
a=rtpmap:0 PCMU/8000\r
"""


response180 = """\
SIP/2.0 180 Ringing\r
Via: SIP/2.0/UDP client.com:5060;branch=z9hG4bK74bf9;received=10.0.0.1;received=10.0.0.1\r
From: Alice <sip:alice@proxy1.org>;tag=9fxced76sl\r
To: Bob <sip:bob@proxy2.org>;tag=314159\r
Call-ID: 3848276298220188511@client.com\r
Contact: <sip:bob@server.com>\r
CSeq: 1 INVITE\r
\r
"""

response200 = """SIP/2.0 200 OK\r
Via: SIP/2.0/UDP client.com:1234;branch=z9hG4bK74bf9;received=10.0.0.1\r
From: Alice <sip:alice@proxy1.org>;tag=9fxced76sl\r
To: Bob <sip:bob@proxy2.org>;tag=314159\r
Call-ID: 3848276298220188511@client.com\r
CSeq: 1 INVITE\r
User-Agent: Divmod Sine\r
Content-Length: 123\r
Content-Type: application/sdp\r
Contact: sip:bob@127.0.0.2\r
\r
v=0\r
o=bob 69086 69086 IN IP4 127.0.0.2\r
s=shtoom\r
c=IN IP4 127.0.0.2\r
t=0 0\r
m=audio 17692 RTP/AVP 0\r
a=rtpmap:0 PCMU/8000\r

"""

ackRequest = """\
ACK sip:bob@proxy2.org SIP/2.0\r
Via: SIP/2.0/UDP client.com:5060;branch=z9hG4bK74b76\r
Max-Forwards: 70\r
Route: sip:proxy2.org:5060;lr\r
From: Alice <sip:alice@proxy1.org>;tag=9fxced76sl\r
To: Bob <sip:bob@proxy2.org>;tag=314159\r
Call-ID: 3848276298220188511@client.com\r
CSeq: 1 ACK\r
\r
"""

byeRequest = """\
BYE sip:bob@proxy2.org SIP/2.0\r
Via: SIP/2.0/UDP server.com:5060;branch=z9hG4bKnashds7\r
Max-Forwards: 70\r
To: Bob <sip:bob@proxy2.org>;tag=314159\r
From: Alice <sip:alice@proxy1.org>;tag=9fxced76sl\r
Call-ID: 3848276298220188511@client.com\r
CSeq: 1 BYE\r
\r
"""

byeResponse = """\
SIP/2.0 200 OK\r
Via: SIP/2.0/UDP server.com:5060;branch=z9hG4bKnashds7;received=10.0.0.2\r
To: Bob <sip:bob@proxy2.org>;tag=314159\r
From: Alice <sip:alice@proxy1.org>;tag=9fxced76sl\r
Call-ID: 3848276298220188511@client.com\r
User-Agent: Divmod Sine\r
CSeq: 1 BYE\r
Content-Length: 0\r
\r
"""

class FakeAvatar(item.Item, item.InstallableMixin):
    typeName = "fakeavatar"
    schemaVersion = 1
    installedOn = attributes.reference()
    implements(sip.IVoiceSystem)
    def localElementByName(self, name):
        return FakeCallRecipient()


    def installOn(self, other):
        super(FakeAvatar, self).installOn(other)
        other.powerUp(self, sip.IVoiceSystem)

class FakeCallRecipient:
    implements(useragent.ICallControllerFactory, useragent.ICallController)

    def acceptCall(self, dialog):
        pass

    def callBegan(self, dialog):
        pass
    def receivedDTMF(self, key):
        pass
    def callEnded(self, dialog):
        pass

    def receivedAudio(self, dialog, bytes):
        pass

    def buildCallController(self, dialog):
        return self

class FakeMediaController:
    def getProcess(self):
        class FakeRTP:
            transport=None
            def createRTPSocket(self, dialog, host):
                return defer.succeed(None)
            def getSDP(self, dialog, othersdp):
                s = SDP()
                m = MediaDescription()
                s.addMediaDescription(m)
                m.addRtpMap(PT_PCMU)
                s.intersect(othersdp)
                return s
            def sendBoxCommand(self, *args):
                return defer.succeed({})
        return defer.succeed(FakeRTP())

class CallTerminateTest(FakeClockTestCase):

    def setUp(self):
        self.dbdir = self.mktemp()
        self.store = store.Store(self.dbdir)
        self.login = userbase.LoginSystem(store=self.store)
        self.login.installOn(self.store)
        account = self.login.addAccount('bob', 'proxy2.org', None)
        us = account.avatars.open()
        FakeAvatar(store=us).installOn(us)
        self.uas = useragent.UserAgent.server(sip.IVoiceSystem(us), "127.0.0.2", FakeMediaController())
        self.sent = []
        self.sip = sip.SIPTransport(self.uas, ["server.com"], 5060)
        self.sip.startProtocol()
        self.sip.sendMessage = lambda dest, msg: self.sent.append((dest, msg))
        self.testMessages = []
        self.parser = sip.MessagesParser(self.testMessages.append)

        #XXX this is probably not good
        useragent.Dialog.genTag = lambda self: "314159"

    def tearDown(self):
        self.clock.advance(33)
        reactor.iterate()
        self.clock.advance(33)
        reactor.iterate()

    def assertMsgEqual(self, first, second):
        self.testMessages[:] = []
        if isinstance(first, basestring):
            self.parser.dataReceived(first)
            self.parser.dataDone()
        else:
            #presumably a Message
            self.testMessages.append(first)
        if isinstance(second, basestring):
            self.parser.dataReceived(second)
            self.parser.dataDone()
        else:
            self.testMessages.append(second)
        self.fuzzyMatch(self.testMessages[0],  self.testMessages[1])

    def fuzzyMatch(self, first, second):
        "try to ignore bits randomly generated by our code"
        self.assertEqual(first.__class__, second.__class__)
        self.assertEqual(first.version, second.version)
        if isinstance(first, sip.Request):
            self.assertEqual(first.method, second.method)
            self.assertEqual(first.uri, second.uri)
        else:
            self.assertEqual(first.code, second.code)

        for header in first.headers.keys():
            if not second.headers.get(header):
                if not first.headers[header]:
                    #woops, it's empty, never mind
                    continue
                raise unittest.FailTest("%s not present in %s" % (header, second))
            if header in ('from', 'to', 'contact'):
                #strip tags
                if isinstance(first.headers[header][0], sip.URL):
                    firsturl = first.headers[header][0]
                else:
                    firsturl = sip.parseAddress(first.headers[header][0])[1]
                secondurl = sip.parseAddress(second.headers[header][0])[1]
                self.assertEqual(firsturl, secondurl)
            elif header == "via":
                firstvia = [sip.parseViaHeader(h)
                            for h in first.headers['via']]
                secondvia = [sip.parseViaHeader(h)
                            for h in second.headers['via']]
                #convert to strings for easy reading of output
                self.assertEqual([x.toString() for x in firstvia],
                                 [x.toString() for x in firstvia])
            elif header == "content-length":
                continue
            else:
                self.assertEqual([str(x) for x in first.headers[header]],
                                 [str(x) for x in second.headers[header]])
    def testCallTermination(self):
        self.sip.datagramReceived(exampleInvite, ('10.0.0.1', 5060))
        reactor.iterate()
        self.assertEquals(len(self.sent), 1)
        self.assertMsgEqual(self.sent[0][0], response200)
        self.sent = []

        self.sip.datagramReceived(ackRequest, ('10.0.0.1', 5060))
        self.assertEquals(len(self.sent), 0)
        self.sip.datagramReceived(byeRequest, ('10.0.0.1', 5060))
        self.assertEquals(len(self.sent), 1)
        self.assertMsgEqual(self.sent[0][0], byeResponse)


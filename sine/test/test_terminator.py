from sine.test.test_sip import FakeClockTestCase, TestRealm, PermissiveChecker
from sine import sip
from twisted import cred
from twisted.internet import reactor

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
Via: SIP/2.0/UDP client.com:5060;branch=z9hG4bK74bf9;received=10.0.0.1\r
From: Alice <sip:alice@proxy1.org>;tag=9fxced76sl\r
To: Bob <sip:bob@proxy2.org>;tag=314159\r
Call-ID: 3848276298220188511@client.com\r
Contact: <sip:bob@server.com>\r
CSeq: 1 INVITE\r
\r
"""

response200 = """SIP/2.0 200 OK\r
Via: SIP/2.0/UDP client.com:1234;branch=z9hG4bK74bf9\r
From: Alice <sip:alice@proxy1.org>;tag=9fxced76sl\r
To: Bob <sip:bob@proxy2.org>\r
Call-ID: 3848276298220188511@client.com\r
CSeq: 1 INVITE\r
Contact: <sip:alice@client.com>\r
\r
v=0\r
o=bob 2890844527 2890844527 IN IP4 server.com\r
s=-\r
c=IN IP4 10.0.0.2\r
t=0 0\r
m=audio 3456 RTP/AVP 0\r
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
BYE sip:alice@proxy1.org SIP/2.0\r
Via: SIP/2.0/UDP server.com:5060;branch=z9hG4bKnashds7\r
Max-Forwards: 70\r
Route: sip:proxy2.org:5060;lr\r
Route: sip:proxy1.org:5060;lr\r
From: Bob <sip:bob@proxy2.org>;tag=314159\r
To: Alice <sip:alice@proxy1.org>;tag=9fxced76sl\r
Call-ID: 3848276298220188511@client.com\r
CSeq: 1 BYE\r
\r
"""

byeResponse = """\
SIP/2.0 200 OK\r
Via: SIP/2.0/UDP server.com:5060;branch=z9hG4bKnashds7;received=10.0.0.2\r
From: Bob <sip:bob@proxy2.org>;tag=314159\r
To: Alice <sip:alice@proxy1.org>;tag=9fxced76sl\r
Call-ID: 3848276298220188511@client.com\r
CSeq: 1 BYE\r
\r
"""

class CallTerminateTest(FakeClockTestCase):
    
    def setUp(self):
        r = TestRealm("server.com")
        p = cred.portal.Portal(r)
        p.registerChecker(PermissiveChecker())
        self.uas = sip.Terminator()
        self.sent = []
        self.sip = sip.SIPTransport(self.uas, ["server.com"], 5060)
        self.sip.sendMessage = lambda dest, msg: self.sent.append((dest, msg))
        self.testMessages = []
        self.parser = sip.MessagesParser(self.testMessages.append)
    def tearDown(self):
        self.clock.advance(33)
        reactor.iterate()
        self.clock.advance(33)
        reactor.iterate()

    def assertMsgEqual(self, first, second):
        self.testMessages[:] = []
        self.parser.dataReceived(first)
        self.parser.dataDone()
        self.parser.dataReceived(second)
        self.parser.dataDone()
        self.assertEqual(self.testMessages[0],  self.testMessages[1])

    def testCallTermination(self):
        self.sip.datagramReceived(exampleInvite, ('10.0.0.1', 5060))
        reactor.iterate()
        self.assertEquals(len(self.sent), 2)
        self.assertMsgEqual(self.sent[0], response180)
        self.assertMsgEqual(self.sent[1], response200)
        self.sent = []
        self.sip.datagramReceived(ackRequest, ('10.0.0.1', 5060))
        self.assertEquals(len(self.sent), 0)
        self.sip.datagramReceived(byeRequest, ('10.0.0.1', 5060))
        self.assertEquals(len(self.sent), 1)
        self.assertMsgEqual(self.sent[1], byeResponse)
    
        

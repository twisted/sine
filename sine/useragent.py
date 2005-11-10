from xshtoom.sdp import SDP
from xshtoom.rtp.protocol import RTPProtocol
from xshtoom.audio.converters import Codecker, PT_PCMU, PT_GSM
from sine.sip import responseFromRequest, parseAddress, formatAddress
from sine.sip import Response, URL, T1, T2, SIPError, ServerTransaction, SIPLookupError
from twisted.internet import reactor, defer, task
from twisted.cred.error import UnauthorizedLogin
from axiom.userbase  import Preauthenticated
from axiom.errors import NoSuchUser
import random, wave
from zope.interface import Interface, implements


class Dialog:
    """
    I represent the state of a SIP call, and am responsible for
    providing appropriate information for generating requests or
    responses in that call.

    Note that RFC 3261 distinguishes between dialogs and sessions,
    because under certain circumstances you can have multiple dialogs
    in a single session, for instance if the request forks and
    receives multiple 2xx responses. The right thing to do in that
    situation isn't clear, so I don't deal with that specially.
    """

    def __init__(self, tu, contactURI, msg, direction=None):
        self.msg = msg
        self.contactURI = contactURI
        self.callID = msg.headers['call-id'][0]
        toAddress = parseAddress(msg.headers['to'][0])
        fromAddress = parseAddress(msg.headers['from'][0])
        if direction == "server":
            self.localAddress = toAddress
            self.remoteAddress = fromAddress
        elif direction == "client":
            self.localAddress = fromAddress
            self.remoteAddress = toAddress
        else:
            raise ValueError, "Dialog needs a direction"

        self.localAddress[2]['tag'] = self.genTag()
        self.localCSeq = random.randint(1E11,1E12)
        self.direction = direction
        self.rtp = RTPProtocol(tu, self)
        #XXX move this to a friendlier place
        self.codec = Codecker(PT_PCMU)
        self.avatar = None

    def getDialogID(self):
        return (self.callID,
                self.localAddress[2].get('tag',''),
                self.remoteAddress[2].get('tag',''))

    def genTag(self):
        tag = ('%04x'%(random.randint(0, 2**10)))[:4]
        tag += ('%04x'%(random.randint(0, 2**10)))[:4]
        return tag

    def responseFromRequest(self, code, msg, body, bodyType="application/sdp"):
        response = Response(code)
        for name in ("via", "call-id", "record-route", "cseq"):
           response.headers[name] = msg.headers.get(name, [])[:]
        if self.direction == 'server':
            response.addHeader('to', formatAddress(self.localAddress))
            response.addHeader('from', formatAddress(self.remoteAddress))
        elif self.direction == 'client':
            response.addHeader('from', formatAddress(self.localAddress))
            response.addHeader('to', formatAddress(self.remoteAddress))
        response.addHeader('user-agent', "Divmod Sine")
        if msg.method == 'INVITE' and code == 200:
            response.addHeader('contact', self.contactURI)
            response.addHeader('content-length', len(body))
            response.addHeader('content-type', bodyType)
            response.bodyDataReceived(body)
        else:
            response.addHeader('content-length', 0)
        response.creationFinished()
        return response

    def playFile(self, f):
        d = defer.Deferred()
        def playSample():
            data = f.read(320)
            if data == '':
                self.LC.stop()
                del self.LC
                d.callback(True)
            else:
                sample = self.codec.handle_audio(data)
                self.rtp.handle_media_sample(sample)

        self.LC = task.LoopingCall(playSample)
        self.LC.start(0.020)
        return d

    def end(self):
        self.rtp.stopSendingAndReceiving()
        self.avatar.callEnded(self)


class ICallRecipient(Interface):
    """
    The order of calls received is:
    - acceptCall
    - callBegan
    - one or many receiveAudio and/or receiveDTMF
    - callEnded
    """

    def acceptCall(dialog):
        """
        Decide if this call will be accepted or not: raise a
        SIPError(code) if the call should be rejected, where 'code' is
        the SIP error code desired.
        """

    def callBegan(dialog):
        """
        Called after the INVITE response has been ACKed and audio started.
        """

    def callEnded(dialog):
        """
        Called after BYE received.
        """

    def receivedAudio(dialog, packet):
        """
        Called with a chunk of audio data, decode into shtoom's
        preferred format (signed linear 16bit 8000Hz).
        """

    def receivedDTMF(dialog, key):
        """
        Called with the numeric value of the pressed key. * and # are
        10 and 11.
        """


class UserAgentServer:
    """
    I listen on a sine.sip.SIPTransport and accept incoming SIP calls,
    directing events from them to an ICallRecipient implementor,
    looked up via cred.
    """

    def __init__(self, portal, localHost, dialogs=None):
        self.portal = portal
        self.localHost = localHost
        if dialogs is not None:
            self.dialogs = dialogs
        else:
            self.dialogs = {}

        self.host = localHost

    def start(self, transport):
        self.transport = transport

    def requestReceived(self, msg, addr):
        st = ServerTransaction(self.transport, self, msg, addr)
        #dialog checking

        dialog = self.matchDialog(msg)
        #untagged requests must be checked against ongoing transactions
        # see 8.2.2.2


        if not dialog and parseAddress(msg.headers['to'][0])[2].get('tag',None):
            #uh oh, there was an expectation of a dialog
            #but we can't remember it (maybe we crashed?)
            st.messageReceivedFromTU(responseFromRequest(481, msg))
            return defer.succeed(st)

            #authentication
            #check for Require
        m = getattr(self, "process_" + msg.method, None)
        if not m:
            st.messageReceivedFromTU(responseFromRequest(405, msg))
            return defer.succeed(st)
        else:
            return defer.maybeDeferred(m, st, msg, addr, dialog).addCallback(
                lambda x: st)

    def ackTimerRetry(self, dialog,  msg):
        timer, tries = dialog.ackTimer
        if tries > 10:
            #more than 64**T1 seconds since we've heard from the other end
            #so say bye and give up
            self.sendBye(dialog)
            return
        if tries > 0:
            self.transport.sendResponse(msg)
        dialog.ackTimer = (reactor.callLater(min((2**tries)*T1, T2),
                                             self.ackTimerRetry,
                                             dialog, msg),
                           tries+1)

    def process_INVITE(self, st, msg, addr, dialog):
        if dialog:
            #mid-request!
            #something special needs to happen with INVITEs here
            print "Target refresh requests are unimplemented"
            st.messageReceivedFromTU(dialog.responseFromRequest(501, msg))
            return st
        #otherwise, time to start a new one
        dialog = Dialog(self,
                        URL(self.host,
                            parseAddress(msg.headers['to'][0])[1].username),
                        msg,
                        direction="server")
        d = dialog.rtp.createRTPSocket(self.host, False)

        def credulate(_):
            return self.portal.login(Preauthenticated(
                parseAddress(msg.headers['to'][0])[1].toCredString()),
                                     None, ICallRecipient).addErrback(
                failedLookup)

        def failedLookup(err):
            err.trap(NoSuchUser, UnauthorizedLogin)
            raise SIPLookupError(604)

        def start((interface, avatar, logout)):
            dialog.avatar = avatar
            if hasattr(avatar, 'acceptCall'):
                avatar.acceptCall(dialog)

            sdp = SDP(msg.body)
            mysdp = dialog.rtp.getSDP(sdp)
            if not sdp.hasMediaDescriptions():
                st.messageReceivedFromTU(responseFromRequest(406, msg))
                return st
            md = sdp.getMediaDescription('audio')
            ipaddr = md.ipaddr or sdp.ipaddr
            remoteAddr = (ipaddr, md.port)
            dialog.rtp.start(remoteAddr)
            self.dialogs[dialog.getDialogID()] = dialog
            response = dialog.responseFromRequest(200, msg, mysdp.show())
            st.messageReceivedFromTU(response)

            dialog.ackTimer = [None, 0]
            self.ackTimerRetry(dialog, response)
        return d.addCallback(credulate).addCallback(start)

    def process_ACK(self, st, msg, addr, dialog):
        #woooo it is an ack for a 200, it is call setup time
        timer = dialog.ackTimer[0]
        if timer.active():
            timer.cancel()
        dialog.avatar.callBegan(dialog)

    def matchDialog(self, msg):
        """
        Look up the dialog that this message belongs to, if any.
        Returns None if no such dialog exists.
        """
        dialog= self.dialogs.get(
            (msg.headers['call-id'][0],
             parseAddress(msg.headers['to'][0])[2].get('tag',''),
             parseAddress(msg.headers['from'][0])[2].get('tag','')),
            None)
        return dialog

    def process_BYE(self, st, msg, addr, dialog):
        if not dialog:
            raise SIPError(481)
        #stop RTP stuff
        dialog.end()
        response = dialog.responseFromRequest(200, msg, None)
        st.messageReceivedFromTU(response)

        del self.dialogs[dialog.getDialogID()]

    def sendBye(self, dialog):
        ## actually send a BYE, etc. that's a UAC problem really, i'll
        ## deal with that later
        pass

    def incomingRTP(self, dialog, packet):
        from xshtoom.rtp.formats import PT_NTE
        if packet.header.ct is PT_NTE:
            data = packet.data
            key = ord(data[0])
            start = (ord(data[1]) & 128) and True or False
            if start:
                #print "start inbound dtmf", key
                dialog.avatar.receivedDTMF(dialog, key)
            else:
                #print "stop inbound dtmf", key
                return
        else:
            dialog.avatar.receivedAudio(dialog, dialog.codec.decode(packet))

    def dropCall(self, *args, **kwargs):
        "For shtoom compatibility."
        pass


class SimpleCallRecipient:
    """
    An example SIP application: upon receipt of a call, a greeting is
    played, then audio is recorded until hangup or # is pressed.
    """

    implements(ICallRecipient)
    file = None

    def acceptCall(self, dialog):
        pass

    def callBegan(self, dialog):
        import os
        f = open(os.path.join(os.path.split(__file__)[0], 'test_audio.raw'))
        dialog.playFile(f).addCallback(lambda _: self.beginRecording())

    def receivedDTMF(self, key):
        if key == 11:
            self.endRecording()

    def callEnded(self, dialog):
        self.endRecording()

    def beginRecording(self):
        self.file = wave.open('recording.wav', 'wb')
        self.file.setparams((1,2,8000,0,'NONE','NONE'))

    def receivedAudio(self, dialog, bytes):
        if self.file:
            self.file.writeframes(bytes)

    def endRecording(self):
        if self.file:
            self.file.close()

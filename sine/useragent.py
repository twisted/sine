from xshtoom.sdp import SDP
from xshtoom.rtp.protocol import RTPProtocol
from xshtoom.rtp.formats import SDPGenerator
from xshtoom.audio.converters import Codecker, PT_PCMU
from xshtoom.audio.aufile import WavReader
from sine.sip import responseFromRequest, parseAddress, formatAddress
from sine.sip import Response, Request, URL, T1, T2, SIPError, Via
from sine.sip import ClientTransaction, ServerTransaction, SIPLookupError
from sine.sip import IVoiceSystem, ITransactionUser, SIPResolverMixin
from sine.sip import ClientInviteTransaction, computeBranch
from twisted.internet import reactor, defer, task
from twisted.cred.error import UnauthorizedLogin
from axiom.errors import NoSuchUser
import random, wave, md5
from zope.interface import Interface, implements

class Hangup(Exception):
    """
    Raise this in ITransactionUser.receivedAudio or .receivedDTMF to
    end the call.
    """

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

    callController = None

    def forServer(cls, tu, contactURI, msg):
        """
        Create a dialog from a received INVITE.

        tu: the transaction user handling this dialog.
        contactURI: the contact for the other party.
        msg: the initial INVITE that establishes this dialog.
        """
        #RFC 3261 12.1.1
        self = cls(tu, contactURI)
        self.msg = msg
        toAddress, fromAddress = self._finishInit()
        self.localAddress = toAddress
        self.remoteAddress = fromAddress
        self.localAddress[2]['tag'] = self.genTag()
        self.direction = "server"
        self.routeSet = [parseAddress(route) for route in self.msg.headers.get('record-route', [])]
        return self.rtp.createRTPSocket(contactURI.host, False).addCallback(lambda _: self)

    forServer = classmethod(forServer)

    def forClient(cls, tu, contactURI, targetURI, controller):
        """
        Create a dialog with a remote party by sending an INVITE.

        tu: the transaction user handling this dialog.
        contactURI: the _local_ contact URI (port and host media will be received on)
        targetURI: URI of the remote party.
        controller: an ICallController instance that will handle media for this call.
        """

        #XXX Need to distinguish between contact and "logical" address
        #Contact usually includes the IP this element is actually listening on,
        #rather than some address that may proxy to here
        #this code assumes that they are identical
        #and specifically, that you can RTP-listen on contactURI.host

        # RFC 3261 12.1.2
        
        self = cls(tu, contactURI)
        self.callController = controller
        self.direction = "client"
        return self._generateInvite(contactURI, targetURI)

    forClient = classmethod(forClient)

    def _generateInvite(self, contacturi, uri):
        #RFC 3261 8.1.1
        #RFC 3261 13.2.1
        invite = Request("INVITE", uri)
        invite.addHeader("to", formatAddress(uri))
        invite.addHeader("from", formatAddress(("", URL(contacturi.host, contacturi.username), {'tag': self.genTag()})))
        invite.addHeader("call-id",
                         "%s@%s" % (md5.md5(str(random.random())).hexdigest(),
                                    contacturi.host))
        invite.addHeader("cseq", "%s INVITE" % self.localCSeq)
        invite.addHeader("user-agent", "Divmod Sine")
        invite.addHeader("content-type", "application/sdp")
        #XXX maybe rip off IP discovered in SDP phase?
        invite.addHeader("contact", formatAddress(contacturi))
        def finishMessage(_):
            sdp = self.rtp.getSDP().show()
            invite.body = sdp
            invite.addHeader("content-length", len(sdp))
            invite.creationFinished()
            self.msg = invite
            toAddress,fromAddress = self._finishInit()
            self.localAddress = fromAddress
            self.remoteAddress = toAddress

            return self
        return self.rtp.createRTPSocket(contacturi.host, True).addCallback(finishMessage)


    def __init__(self, tu, contactURI):
        self.tu = tu
        self.contactURI = contactURI
        self.localCSeq = random.randint(1E4,1E5)
        self.rtp = RTPProtocol(tu, self)
        #XXX move this to a friendlier place
        self.codec = Codecker(PT_PCMU)
        self.LC = None
        #UAC bits
        self.clientState = "early"

    def _finishInit(self):
        self.callID = self.msg.headers['call-id'][0]
        toAddress = parseAddress(self.msg.headers['to'][0])
        fromAddress = parseAddress(self.msg.headers['from'][0])
        return toAddress, fromAddress

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
            response.addHeader('contact', formatAddress(self.contactURI))
            response.addHeader('content-length', len(body))
            response.addHeader('content-type', bodyType)
            response.bodyDataReceived(body)
        else:
            response.addHeader('content-length', 0)
        response.creationFinished()
        return response

    def generateRequest(self, method):
        #RFC 3261 12.2.1.1
        r = Request(method, self.remoteAddress[1])

        if self.routeSet:
            r.headers['route'] = [formatAddress(route) for route in self.routeSet]
            if 'lr' not in self.routeSet[0][1].other:
                r.headers['route'].append(formatAddress(("", r.uri, {})))
                r.uri = parseAddress(r.headers['route'].pop())[1]

        r.addHeader('to', formatAddress(self.remoteAddress))
        r.addHeader('from', formatAddress(self.localAddress))
        r.addHeader('cseq', "%s %s" % (self.localCSeq, method))
        self.localCSeq += 1
        r.addHeader('call-id', self.msg.headers['call-id'][0])
        r.addHeader('contact', formatAddress(self.contactURI))
        r.addHeader('content-length', 0)
        return r

    def _sendRequest(self, method):
        msg = self.generateRequest(method)

    def _findDest(self, msg):
        rs = msg.headers.get('route', None)
        if rs:
            dest = parseAddress(rs[0])[1]
        else:
            dest = msg.uri
        return dest


    def sendBye(self):
        "Send a BYE and stop media."
        msg = self.generateRequest('BYE')
        dest = self._findDest(msg)
        ct = ClientTransaction(self.tu.transport, self.tu, msg, (dest.host, dest.port))
        self.tu.cts[ct] = self #is this bad?
        self.end()

    def sendAck(self):
        msg = self.generateRequest('ACK')
        msg.headers['cseq'] = ["%s ACK" % self.msg.headers['cseq'][0].split(' ')[0]]
        dest = self._findDest(msg)
        msg.headers.setdefault('via', []).insert(0, Via(self.tu.transport.host, self.tu.transport.port,
                                                        rport=True,
                                                        branch=computeBranch(msg)).toString())
        self.tu.transport.sendRequest(msg, (dest.host, dest.port))

    def playFile(self, f, samplesize=320):
        """
        Play a shtoom-format sound file. (Raw unsigned linear, 16 bit
        8000Hz audio. sox options: -u -w -r 8000)
        """

        d = defer.Deferred()
        def playSample():
            data = f.read(samplesize)
            if data == '':
                self.stopPlaying()
                d.callback(True)
            else:
                sample = self.codec.handle_audio(data)
                self.rtp.handle_media_sample(sample)
        if self.LC:
            self.LC.stop()
        self.LC = task.LoopingCall(playSample)
        self.LC.start(0.020)
        return d

    def playWave(self, f):
        "Play a PCM-encoded WAV file. (Compressed WAVs probably won't work.)"
        return self.playFile(WavReader(f), samplesize=160)

    def stopPlaying(self):
        if self.LC:
            self.LC.stop()
            self.LC = None

    def end(self):
        self.rtp.stopSendingAndReceiving()
        self.callController.callEnded(self)

class ICallControllerFactory(Interface):
    def buildCallController(self, dialog):
        "Return an ICallController"

class ICallController(Interface):
    """
    The order of calls received is:
    - acceptCall
    - callBegan
    - zero or more receiveAudio and/or receiveDTMF (if zero, there is probably a network problem)
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

    def callFailed(dialog, message):
        """
        Called when an incoming call is canceled or an outgoing call
        receives a failure response.
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
    directing events from them to an ICallController implementor,
    looked up via cred.
    """
    implements(ITransactionUser)
    def __init__(self, store, localHost, dialogs=None):
        self.store = store
        self.localHost = localHost
        if dialogs is not None:
            self.dialogs = dialogs
        else:
            self.dialogs = {}
        self.host = localHost

    def start(self, transport):
        self.transport = transport

    def requestReceived(self, msg, addr):
        #RFC 3261 12.2.2
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
            dialog.sendBye()
            return
        if tries > 0:
            self.transport.sendResponse(msg)
        dialog.ackTimer = (reactor.callLater(min((2**tries)*T1, T2),
                                             self.ackTimerRetry,
                                             dialog, msg),
                           tries+1)

    def process_INVITE(self, st, msg, addr, dialog):
        #RFC 3261 13.3.1
        if dialog:
            #mid-request!
            #something special needs to happen with INVITEs here
            print "Target refresh requests are unimplemented"
            st.messageReceivedFromTU(dialog.responseFromRequest(501, msg))
            return st
        #otherwise, time to start a new one

        d = Dialog.forServer(self, URL(self.host,
                             parseAddress(msg.headers['to'][0])[1].username),
                             msg)

        def lookupElement(dialog):
            def startAudio(sdp):
                md = sdp.getMediaDescription('audio')
                ipaddr = md.ipaddr or sdp.ipaddr
                remoteAddr = (ipaddr, md.port)
                dialog.rtp.start(remoteAddr)
            avatar = IVoiceSystem(self.store).localElementByName(parseAddress(msg.headers['to'][0])[1].username)

            dialog.callController = avatar.buildCallController(dialog)
            sdp = SDP(msg.body)
            mysdp = dialog.rtp.getSDP(sdp)
            if not sdp.hasMediaDescriptions():
                st.messageReceivedFromTU(responseFromRequest(406, msg))
                return st
            startAudio(sdp)
            self.dialogs[dialog.getDialogID()] = dialog
            response = dialog.responseFromRequest(200, msg, mysdp.show())
            st.messageReceivedFromTU(response)

            dialog.ackTimer = [None, 0]
            self.ackTimerRetry(dialog, response)

        def failedLookup(err):
            err.trap(NoSuchUser, UnauthorizedLogin)
            raise SIPLookupError(604)

        return d.addCallback(lookupElement).addErrback(failedLookup)

    def process_ACK(self, st, msg, addr, dialog):
        #woooo it is an ack for a 200, it is call setup time
        timer = dialog.ackTimer[0]
        if timer.active():
            timer.cancel()
        dialog.callController.callBegan(dialog)

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


    def responseReceived(self, response, ct=None):
        #presumably just BYE responses
        pass

    def clientTransactionTerminated(self, ct=None):
        #do we care?
        pass

    def incomingRTP(self, dialog, packet):
        from xshtoom.rtp.formats import PT_NTE
        if packet.header.ct is PT_NTE:
            data = packet.data
            key = ord(data[0])
            start = (ord(data[1]) & 128) and True or False
            if start:
                #print "start inbound dtmf", key
                d = defer.maybeDeferred(dialog.callController.receivedDTMF, dialog, key)
            else:
                #print "stop inbound dtmf", key
                return
        else:
            d = defer.maybeDeferred(dialog.callController.receivedAudio, dialog, dialog.codec.decode(packet))
        def e(err):
            err.trap(Hangup)
            #fudge a little to let playback finish
            reactor.callLater(0.5, dialog.sendBye)
        d.addErrback(e)


    def dropCall(self, *args, **kwargs):
        "For shtoom compatibility."
        pass


class SimpleCallRecipient:
    """
    An example SIP application: upon receipt of a call, a greeting is
    played, then audio is recorded until hangup or # is pressed.
    """

    implements(ICallController)
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

class UserAgentClient(SIPResolverMixin):
    implements(ITransactionUser)
    """
    I listen on a sine.sip.SIPTransport and set up calls to SIP addresses from ICallController instances.
    """
    def __init__(self, controller, localpart, localHost, dialogs=None):
        self.controller = controller
        if dialogs is None:
            self.dialogs = {}
        else:
            self.dialogs = dialogs
        self.cts = {}
        self.host = localHost
        self.user = localpart
    def start(self, transport):
        self.transport = transport

    def call(self, uri):
        """
        Call the specified URI and notify our controller when it is set up.
        """
        def _cb(dlg):
            def _send(targets):
                #'targets' is a list of (host, port) obtained from SRV lookup
                #ideally, if there's a 503 response to this message, we can
                #resend through another target.
                #For now we'll just send to the first and hope for the best.

                ct = ClientInviteTransaction(self.transport, self, dlg.msg, targets[0])
                self.cts[ct] = dlg
            self._lookupURI(uri).addCallback(_send)

        #XXX Should call() return a deferred that fires after ACK?
        #    Or should all call control be done via self.controller?
        Dialog.forClient(self, URL(self.host, self.user), uri, self.controller).addCallback(_cb)

    def responseReceived(self, response, ct=None):
        
        #OK this function is a bit hairy because I don't want to track
        #any call state in this class and responses to various things
        #need to be handled differently. The main event is 2xx
        #responses to the INVITE -- that changes the early dialog
        #(created when the INVITE was sent) to an confirmed dialog.
        #Error responses result in dialog teardown, as do responses to BYEs.

        #RFC 3261 12.2.1.2
        
        dialog = self.cts.get(ct, None)
        if dialog is None:
            dialog = self.matchResponseToDialog(response)

        def startAudio(sdp):
            md = sdp.getMediaDescription('audio')
            ipaddr = md.ipaddr or sdp.ipaddr
            remoteAddr = (ipaddr, md.port)
            dialog.rtp.start(remoteAddr)

        if dialog.clientState == "early":
            if 200 <= response.code < 300:
                #RFC 3261 12.1.2
                dialog.clientState = "confirmed"
                dialog.remoteAddress = parseAddress(response.headers['to'][0])
                dialog.routeSet = [parseAddress(route) for route in response.headers.get('record-route', [])[::-1]]
                self.dialogs[dialog.getDialogID()] = dialog
                startAudio(SDP(response.body))
                self.controller.callBegan(dialog)
            elif 300 <= response.code < 400:
                raise NotImplemented, "Dunno about redirects yet"
            elif 400 <= response.code < 700:
                if dialog.getDialogID() in self.dialogs:
                    del self.dialogs[dialog.getDialogID()]
                del self.cts[ct]
                self.controller.callFailed(dialog, response)

        if 'INVITE' in response.headers['cseq'][0] and 200 <= response.code < 300:
            #RFC 3261, 13.2.2.4
            dialog.sendAck()

        if dialog.clientState == "byeSent":
            del self.cts[ct]
            del self.dialogs[dialog.getDialogID()]

        

    def requestReceived(self, msg, addr):
        st = ServerTransaction(self.transport, self, msg, addr)
        #dialog checking
        dialog = self.matchRequestToDialog(msg)
        if not dialog and parseAddress(msg.headers['to'][0])[2].get('tag',None):
            st.messageReceivedFromTU(responseFromRequest(481, msg))
            return
        if msg.method == 'BYE':
            dialog.end()
            response = dialog.responseFromRequest(200, msg, None)
            st.messageReceivedFromTU(response)

            del self.dialogs[dialog.getDialogID()]

    def matchResponseToDialog(self, msg):
        dialog= self.dialogs.get(
            (msg.headers['call-id'][0],
             parseAddress(msg.headers['from'][0])[2].get('tag',''),
             parseAddress(msg.headers['to'][0])[2].get('tag','')),
            None)
        return dialog

    def matchRequestToDialog(self, msg):
        dialog= self.dialogs.get(
            (msg.headers['call-id'][0],
             parseAddress(msg.headers['to'][0])[2].get('tag',''),
             parseAddress(msg.headers['from'][0])[2].get('tag','')),
            None)
        return dialog

    def clientTransactionTerminated(self, ct):
        dialog = self.cts[ct]
        if dialog.clientState != "confirmed":
            self.responseReceived(ct.response)

    def incomingRTP(self, dialog, packet):
        from xshtoom.rtp.formats import PT_NTE
        if packet.header.ct is PT_NTE:
            data = packet.data
            key = ord(data[0])
            start = (ord(data[1]) & 128) and True or False
            if start:
                #print "start inbound dtmf", key
                d = defer.maybeDeferred(dialog.callController.receivedDTMF, dialog, key)
            else:
                #print "stop inbound dtmf", key
                return
        else:
            d = defer.maybeDeferred(dialog.callController.receivedAudio, dialog, dialog.codec.decode(packet))
        def e(err):
            err.trap(Hangup)
            #fudge a little to let playback finish
            reactor.callLater(0.5, dialog.sendBye)
        d.addErrback(e)


    def dropCall(self, *args, **kwargs):
        "For shtoom compatibility."
        pass

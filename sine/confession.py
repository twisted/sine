# VoIP confession booth -- because angst is easier to convey with your voice

from axiom.item import Item, InstallableMixin
from axiom.slotmachine import hyper as super
from xmantissa import website, webapp, ixmantissa
from zope.interface import implements
from sine import sip, useragent
from xshtoom.audio.aufile import GSMReader
from axiom.attributes import inmemory, reference, integer, text, bytes
from twisted.internet import reactor, defer
from nevow import static
from epsilon.modal import ModalType, mode
import tempfile, wave, os

ASTERISK_SOUNDS_DIR = "/usr/share/asterisk/sounds"

def soundFile(name):
    return GSMReader(open(os.path.join(ASTERISK_SOUNDS_DIR, name+".gsm")))

class ConfessionBenefactor(Item):
    implements(ixmantissa.IBenefactor)

    typeName = 'confession_benefactor'
    schemaVersion = 1

    # Number of users this benefactor has endowed
    endowed = integer(default = 0)

    localHost = bytes()

    def endow(self, ticket, avatar):
        self.endowed += 1

        avatar.findOrCreate(website.WebSite).installOn(avatar)
        avatar.findOrCreate(webapp.PrivateApplication).installOn(avatar)
        avatar.findOrCreate(ConfessionUser).installOn(avatar)
        avatar.findOrCreate(ConfessionDispatcher, localHost=self.localHost).installOn(avatar)

class ConfessionDispatcher(Item, InstallableMixin):
    implements(sip.IVoiceSystem)
    typeName = "sine_confession_dispatcher"
    schemaVersion = 1

    installedOn = reference()
    localHost = bytes()
    uas = inmemory()

    def installOn(self, other):
        super(ConfessionDispatcher, self).installOn(other)
        other.powerUp(self, sip.IVoiceSystem)
    def activate(self):
        self.uas = useragent.UserAgentServer(self.store, self.localHost)

    def lookupProcessor(self, msg, dialogs):
        #XXX haaaaack
        if 'confession@' in msg.headers['to'][0]:
            #double hack =/
            self.uas.dialogs = dialogs
            return self.uas

    def localElementByName(self, name):
        if name == 'confession':
            return useragent.ICallControllerFactory(self.store)
        else:
            raise sip.SIPLookupError(404)

class ConfessionUser(Item, InstallableMixin):
    implements(useragent.ICallControllerFactory)

    typeName = "sine_confession_user"
    schemaVersion = 1

    installedOn = reference()

    def installOn(self, other):
        super(ConfessionUser, self).installOn(other)
        other.powerUp(self, useragent.ICallControllerFactory)

    def buildCallController(self, dialog):
        return ConfessionCall(self)

class ConfessionCall(object):
    __metaclass__ = ModalType
    initialMode = 'recording'
    modeAttribute = 'mode'
    implements(useragent.ICallController)
    recordingTarget = None
    recordingTimer = None
    temprecording = None
    def __init__(self, avatar, anon=False):
        self.avatar = avatar
        self.anon=anon

    def callBegan(self, dialog):
        def playBeep(_):
            dialog.playFile(soundFile("beep"))
        d = dialog.playFile(soundFile("vm-intro")).addCallback(playBeep)
        if self.anon:
            d.addCallback(lambda _: self.beginRecording(dialog.remoteAddress[1].toCredString()))
        else:
            d.addCallback(lambda _: self.beginRecording())

    def beginRecording(self, target=None):
        if self.anon:
            timeLimit = 45
        else:
            timeLimit = 180
        self.recordingTarget = TempRecording(target)
        self.recordingTimer = reactor.callLater(timeLimit, self.endRecording)

    def receivedAudio(self, dialog, bytes):
        if self.recordingTarget:
            self.recordingTarget.write(bytes)

    def playReviewMessage(self, dialog):
        dialog.playFile(soundFile("vm-review")).addCallback(
            lambda _: dialog.playFile(soundFile("vm-star-cancel")))

    class recording(mode):
        def receivedDTMF(self, dialog, key):
            if self.recordingTarget and key == 11:
                self.temprecordingName = self.recordingTarget.filename
                r = self.endRecording()
                self.temprecording = r
                self.playReviewMessage(dialog)
                self.mode = "review"

    class review(mode):
        def receivedDTMF(self, dialog, key):
            #1 - accept
            #2 - replay
            #3 - re-record
            #10 - give up
            dialog.stopPlaying()
            if key == 1:
                 self.temprecording.saveTo(self.avatar.store)
                 self.temprecording = None
                 return dialog.playFile(soundFile("auth-thankyou")).addCallback(lambda _: defer.fail(useragent.Hangup()))

            elif key == 2:
                return dialog.playWave(self.temprecordingName).addCallback(lambda _: self.playReviewMessage(dialog))
            elif key == 3:
                self.mode = "recording"
                def beginAgain():
                    dialog.playFile(soundFile("beep"))
                    self.beginRecording()
                reactor.callLater(0.5, beginAgain)
            elif key == 10:
                self.temprecording = None
                self.endRecording()
                return dialog.playFile(soundFile("vm-goodbye")).addCallback(lambda _: defer.fail(useragent.Hangup()))


    def endRecording(self):
        if self.recordingTimer and self.recordingTimer.active():
            self.recordingTimer.cancel()
        if self.recordingTarget:
            self.recordingTarget.close()
            r = self.recordingTarget
            self.recordingTarget = None
            return r

    def callEnded(self, dialog):
        r = self.endRecording()
        if self.temprecording:
            self.temprecording.saveTo(self.avatar.store)


class TempRecording:

    def __init__(self, fromAddress):
        fileno, self.filename = tempfile.mkstemp()
        self.file = wave.open(os.fdopen(fileno, 'wb'), 'wb')
        self.file.setparams((1,2,8000,0,'NONE','NONE'))
        self.fromAddress = fromAddress

    def write(self, bytes):
        self.file.writeframes(bytes)

    def close(self):
        self.file.close()

    def saveTo(self, store):
        r = Recording(store=store, fromAddress=unicode(self.fromAddress))
        r.audioFromFile(self.filename)
        r.installOn(store)


class Recording(Item, website.PrefixURLMixin):
    typeName = "sine_confession_recording"
    schemaVersion = 1

    prefixURL = text()
    length = integer() #seconds in recording
    fromAddress = text()

    def __init__(self, **args):
        super(Recording, self).__init__(**args)

    def installOn(self, other):
        #XXX is this bad? I don't know anymore
        self.prefixURL = unicode("recordings/" + str(self.storeID))
        super(Recording, self).installOn(other)
    def getFile(self):
        dir = self.store.newDirectory("recordings")
        if not dir.exists():
            dir.makedirs() #should i really have to do this?
        return dir.child("%s.wav" % self.storeID)

    file = property(getFile)

    def audioFromFile(self, filename):
        f = self.file.path
        import shutil
        #don't hate me, exarkun
        shutil.move(filename, f)
        w = wave.open(f)
        self.length = w.getnframes() / w.getframerate()
        w.close()

    def createResource(self):
        return static.Data(self.file, 'audio/x-wav')



class AnonConfessionUser(Item, InstallableMixin):
    implements(useragent.ICallControllerFactory)

    typeName = "sine_anonconfession_user"
    schemaVersion = 1

    installedOn = reference()

    def installOn(self, other):
        super(AnonConfessionUser, self).installOn(other)
        other.powerUp(self, useragent.ICallControllerFactory)

    def buildCallController(self, dialog):
        return ConfessionCall(self, True)

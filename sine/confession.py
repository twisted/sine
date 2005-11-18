# VoIP confession booth -- because angst is easier to convey with your voice

from axiom.item import Item, InstallableMixin
from axiom.slotmachine import hyper as super
from xmantissa import website, webapp, ixmantissa
from zope.interface import implements
from sine import sip, useragent
from axiom.attributes import inmemory, reference, integer, text, bytes
from twisted.internet import reactor
from nevow import static
import tempfile, wave, os


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
            return useragent.ICallRecipient(self.store)
        else:
            raise sip.SIPLookupError(404)
        
class ConfessionUser(Item, InstallableMixin):
    implements(useragent.ICallRecipient)

    typeName = "sine_confession_user"
    schemaVersion = 1

    installedOn = reference()

    connected = inmemory()
    recordingTarget = inmemory()
    recordingTimer = inmemory()
    def activate(self):
        #sigh
        self.connected = False
        
    def installOn(self, other):
        super(ConfessionUser, self).installOn(other)
        other.powerUp(self, useragent.ICallRecipient)

    def acceptCall(self, dialog):
        if self.connected:
            raise sip.SIPError(486)
    
    def callBegan(self, dialog):
        self.connected = True
        self.recordingTarget = None
        import os
        f = open(os.path.join(os.path.split(__file__)[0], 'test_audio.raw'))
        dialog.playFile(f).addCallback(lambda _: self.beginRecording())

    def beginRecording(self):
        self.recordingTarget = TempRecording(None)
        self.recordingTimer = reactor.callLater(180, self.endRecording)
        
    def receivedAudio(self, dialog, bytes):
        if self.connected and self.recordingTarget:            
            self.recordingTarget.write(bytes)

    def receivedDTMF(self, dialog, key):
        if self.recordingTarget and key == 11:
            name = self.recordingTarget.filename
            r = self.endRecording()
            dialog.playWave(name).addCallback(lambda x: self.chooseSavingOrRecording(r))

    def chooseSavingOrRecording(self, r):
        #for purposes of demonstration, just save it
        r.saveTo(self.store)
    
    def endRecording(self):        
        if self.recordingTimer.active():
            self.recordingTimer.cancel()        
        if self.recordingTarget:
            self.recordingTarget.close()
            r = self.recordingTarget
            self.recordingTarget = None
            return r
        
    def callEnded(self, dialog):
        self.endRecording()
        self.connected = False


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
    implements(useragent.ICallRecipient)

    typeName = "sine_anonconfession_user"
    schemaVersion = 1

    installedOn = reference()

    connected = inmemory()
    recordingTarget = inmemory()
    recordingTimer = inmemory()
    
    def activate(self):
        #sigh
        self.connected = False
        
    def installOn(self, other):
        super(AnonConfessionUser, self).installOn(other)
        other.powerUp(self, useragent.ICallRecipient)

    def acceptCall(self, dialog):
        if self.connected:
            raise sip.SIPError(486)
    
    def callBegan(self, dialog):
        self.connected = True
        self.recordingTarget = None
        import os
        f = open(os.path.join(os.path.split(__file__)[0], 'test_audio.raw'))
        dialog.playFile(f).addCallback(lambda _: self.beginRecording(dialog.remoteAddress[1].toCredString()))

    def beginRecording(self, fromUser):
        self.recordingTarget = TempRecording(fromUser)
        self.recordingTimer = reactor.callLater(45, self.endRecording)
        
    def receivedAudio(self, dialog, bytes):
        if self.connected and self.recordingTarget:            
            self.recordingTarget.write(bytes)

    def receivedDTMF(self, dialog, key):
        if self.recordingTarget and key == 11:
            name = self.recordingTarget.filename
            r = self.endRecording()
            dialog.playWave(name).addCallback(lambda x: self.chooseSavingOrRecording(r))

    def chooseSavingOrRecording(self, r):
        #for purposes of demonstration, just save it
        r.saveTo(self.store)
    
    def endRecording(self):        
        if self.recordingTimer.active():
            self.recordingTimer.cancel()        
        if self.recordingTarget:
            self.recordingTarget.close()
            r = self.recordingTarget
            self.recordingTarget = None
            return r
        
    def callEnded(self, dialog):
        self.endRecording()
        self.connected = False

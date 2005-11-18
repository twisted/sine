from axiom.item import Item, InstallableMixin
from zope.interface import implements
from sine import sip, useragent
from axiom.attributes import reference, inmemory, bytes

import os
class EchoDispatcher(Item, InstallableMixin):
    implements(sip.IVoiceSystem)
    typeName = "sine_echo_dispatcher"
    schemaVersion = 1

    installedOn = reference()
    localHost = bytes()
    uas = inmemory()
    
    def installOn(self, other):
        super(EchoDispatcher, self).installOn(other)
        other.powerUp(self, sip.IVoiceSystem)
    def activate(self):
        self.uas = useragent.UserAgentServer(self.store, self.localHost)
        
    def lookupProcessor(self, msg, dialogs):
        self.uas.dialogs = dialogs
        return self.uas

    def localElementByName(self, name):
        if name == 'echo':
            return useragent.ICallRecipient(self.store)
        else:
            raise sip.SIPLookupError(404)

class EchoTest(Item, InstallableMixin):
    implements(useragent.ICallRecipient)

    typeName = "sine_echo_test"
    schemaVersion = 1

    installedOn = reference()
    connected = inmemory()

    def activate(self):
        #sigh
        self.connected = False
        
    def installOn(self, other):
        super(EchoTest, self).installOn(other)
        other.powerUp(self, useragent.ICallRecipient)

    def acceptCall(self, dialog):
        return True

    def callBegan(self, dialog):
        f = open(os.path.join(os.path.split(__file__)[0], 'echo_greeting.raw'))
        dialog.playFile(f).addCallback(lambda _: self.beginEchoing(dialog))

    def beginEchoing(self, dialog):
        dialog.echoing = True

    def receivedAudio(self, dialog, bytes):
        if getattr(dialog, 'echoing', False):
            sample = dialog.codec.handle_audio(bytes)
            dialog.rtp.handle_media_sample(sample)

    def receivedDTMF(self, dialog):
        pass
    def callEnded(self, dialog):
        pass
    

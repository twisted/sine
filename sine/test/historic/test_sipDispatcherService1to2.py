from axiom.test.historic import stubloader
from sine.sipserver import SIPDispatcherService
from axiom.scheduler import Scheduler
from axiom.userbase import LoginSystem
class SIPServerTest(stubloader.StubbedTest):
    def testUpgrade(self):
        ss = self.store.findUnique(SIPDispatcherService)
        self.failUnless(isinstance(ss.scheduler, Scheduler))
        self.failUnless(isinstance(ss.userbase, LoginSystem))

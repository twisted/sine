from axiom import iaxiom, userbase

from xmantissa import website, offering, provisioning

import hyperbola

from sine import sipserver

sineproxy = provisioning.BenefactorFactory(
    name = u'sineproxy',
    description = u'Sine SIP Proxy',
    benefactorClass = sipserver.SineBenefactor)

plugin = offering.Offering(
    name = u"Hyperbola",

    description = u"""
    The Sine SIP proxy and registrar.
    """,

    siteRequirements = (
        (userbase.IRealm, userbase.LoginSystem),
        (None, website.WebSite)),

    appPowerups = (
        ),

    benefactorFactories = (sineproxy,)
    )


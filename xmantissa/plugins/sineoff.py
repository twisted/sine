from axiom import iaxiom, userbase

from xmantissa import website, offering, provisioning

from sine import sipserver, sinetheme

sineproxy = provisioning.BenefactorFactory(
    name = u'sineproxy',
    description = u'Sine SIP Proxy',
    benefactorClass = sipserver.SineBenefactor)

plugin = offering.Offering(
    name = u"Sine",

    description = u"""
    The Sine SIP proxy and registrar.
    """,

    siteRequirements = (
        (userbase.IRealm, userbase.LoginSystem),
        (None, website.WebSite),
        (None, sipserver.SIPServer)),

    appPowerups = (sipserver.SinePublicPage,
        ),

    benefactorFactories = (sineproxy,),

    themes = (sinetheme.XHTMLDirectoryTheme('base'),)
    )


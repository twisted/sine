from epsilon import setuphelper

from sine import version

setuphelper.autosetup(
    name="Sine",
    version=version.short(),
    maintainer="Divmod, Inc.",
    maintainer_email="support@divmod.org",
    url="http://divmod.org/trac/wiki/DivmodSine",
    license="MIT",
    platforms=["any"],
    description=
        """
        Divmod Sine is a standards-based voice-over-IP application server,
        built as an offering for the Mantissa application server platform.
        """,
    classifiers=[
        "Intended Audience :: Developers",
        "Programming Language :: Python",
        "Development Status :: 2 - Pre-Alpha",
        "Topic :: Internet"],
    )

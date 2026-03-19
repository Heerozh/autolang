import gettext
import locale
import sys

from autolang.config import get_domain


def get_system_language() -> str:
    """Return the system UI language as a short code (e.g. 'en', 'zh')."""
    if sys.platform == "win32":
        import ctypes

        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        # locale.windows_locale 将 Windows LCID 映射到 POSIX locale
        posix = locale.windows_locale.get(lang_id)
    else:
        posix = locale.getlocale()[0]

    if posix:
        return posix
    return "en"


def get_translator(language=None, directory: str = "i18n"):
    print(language)
    if language:
        return gettext.translation(
            get_domain(),
            localedir=directory,
            languages=[language, "en"],
            fallback=True,
        )
    return gettext.translation(
        get_domain(),
        localedir=directory,
        fallback=True,
    )


translator = get_translator(get_system_language())
_ = translator.gettext

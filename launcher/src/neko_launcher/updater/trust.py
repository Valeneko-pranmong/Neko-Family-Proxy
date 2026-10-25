from typing import Mapping

CURRENT_PROFILE_AUTHORITY_KEY_ID = "neko-update-profile-v520-2"
CURRENT_PRODUCTION_RELEASE_KEY_ID = "neko-update-prod-3"

# Historical keys remain registered so published releases can still be verified;
# the installed v5.2.0 profile authorizes only the current release key.
PROFILE_AUTHORITY_PUBLIC_KEYS: Mapping[str, bytes] = {
    "neko-update-profile-v512-1": bytes.fromhex(
        "eabc58f00289b8bf0c1ac1fcf1fa608b418b718b25efbcb209f4c28afc260504"
    ),
    "neko-update-profile-v520-1": bytes.fromhex(
        "c8efdbd809cd9dcf7e0ceaa8b832a9a68840470ba4f2daf028c25ba213415c18"
    ),
    "neko-update-profile-v520-2": bytes.fromhex(
        "6c70a2d21919f6f6ed164b2983ab78b63c7c0ef21bb285d1a35bf8091c805bff"
    ),
}

PRODUCTION_RELEASE_PUBLIC_KEYS: Mapping[str, bytes] = {
    "neko-update-prod-1": bytes.fromhex(
        "c98941b472a01967a54e4f1cb215f71a479cf187ebdd0fa37f4ee9a5693fe9cf"
    ),
    "neko-update-prod-2": bytes.fromhex(
        "d17fed34a28fd1a120caf45cf2d75863a55ef76ecebb2538fa729576772b3bda"
    ),
    "neko-update-prod-3": bytes.fromhex(
        "0136d024dff5d2df4d52474fe0c01ac17a223534f0571998413b23e7553bd4d8"
    ),
}

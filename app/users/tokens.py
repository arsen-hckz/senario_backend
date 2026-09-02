from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Same HMAC scheme as Django's password-reset token, salted separately
    and keyed off is_email_verified so a token stops working once used."""

    key_salt = 'users.tokens.EmailVerificationTokenGenerator'

    def _make_hash_value(self, user, timestamp):
        return f'{user.pk}{user.email}{user.is_email_verified}{timestamp}'


email_verification_token = EmailVerificationTokenGenerator()

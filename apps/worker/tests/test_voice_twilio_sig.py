from app.voice.twilio_sig import compute_signature, is_valid

# Twilio's published example (twilio-python RequestValidator tests).
URL = "https://mycompany.com/myapp.php?foo=1&bar=2"
TOKEN = "12345"
PARAMS = [
    ("CallSid", "CA1234567890ABCDE"),
    ("Caller", "+14158675309"),
    ("Digits", "1234"),
    ("From", "+14158675309"),
    ("To", "+18005551212"),
]
EXPECTED = "RSOYDt4T1cUTdK1PDd93/VVr8B8="


def test_matches_twilios_published_vector():
    assert compute_signature(TOKEN, URL, PARAMS) == EXPECTED


def test_param_order_does_not_matter():
    assert is_valid(TOKEN, URL, list(reversed(PARAMS)), EXPECTED)


def test_tampered_param_fails():
    params = PARAMS[:-1] + [("To", "+18005550000")]
    assert not is_valid(TOKEN, URL, params, EXPECTED)


def test_missing_token_or_signature_fails():
    assert not is_valid(None, URL, PARAMS, EXPECTED)
    assert not is_valid(TOKEN, URL, PARAMS, None)
    assert not is_valid(TOKEN, URL, PARAMS, "")

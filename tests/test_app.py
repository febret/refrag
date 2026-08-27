"""Tests for server startup configuration."""

import os
import ssl
import unittest
from unittest import mock

from server import app


class SslConfigurationTests(unittest.TestCase):
    def test_ssl_generated_and_loaded_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(
                    app, "ensure_self_signed_certificate") as generate, \
                mock.patch("server.app.ssl.SSLContext") as context:
            result = app.ssl_context_from_env()

        generate.assert_called_once_with(
            app.DEFAULT_SSL_CERT, app.DEFAULT_SSL_KEY)
        context.assert_called_once_with(ssl.PROTOCOL_TLS_SERVER)
        result.load_cert_chain.assert_called_once_with(
            app.DEFAULT_SSL_CERT, app.DEFAULT_SSL_KEY)

    def test_ssl_requires_certificate_and_key(self):
        with mock.patch.dict(
                os.environ, {"REFRAG_SSL_CERT": "cert.pem"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "must both be set"):
                app.ssl_context_from_env()

        with mock.patch.dict(
                os.environ, {"REFRAG_SSL_KEY": "key.pem"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "must both be set"):
                app.ssl_context_from_env()

    def test_ssl_loads_configured_certificate_chain(self):
        with mock.patch.dict(os.environ, {
                "REFRAG_SSL_CERT": "cert.pem",
                "REFRAG_SSL_KEY": "key.pem",
        }, clear=True), mock.patch("server.app.ssl.SSLContext") as context:
            result = app.ssl_context_from_env()

        context.assert_called_once_with(ssl.PROTOCOL_TLS_SERVER)
        result.load_cert_chain.assert_called_once_with("cert.pem", "key.pem")


if __name__ == "__main__":
    unittest.main()

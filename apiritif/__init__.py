import re
from unittest import TestCase

import jsonpath_rw
import requests


def headers_as_text(headers_dict):
    return "\n".join("%s: %s" % (key, value) for key, value in headers_dict.items())


class APITestCase(TestCase):
    """
    Base class for API test cases.

    Contains a bunch of utility functions (request, get, post, etc) and a few helpful assertions.
    """
    def setUp(self):
        self.request_log = []
        self.keep_alive = True
        self.session = None
        self.default_address = None
        self.path_prefix = None

    def tearDown(self):
        pass

    # Utility functions

    def request(self, url, method='GET', **kwargs):
        if self.keep_alive and self.session is None:
            self.session = requests.Session()

        address = ''
        if self.default_address is not None:
            address += self.default_address
        if self.path_prefix is not None:
            address += self.path_prefix
        address += url

        if self.keep_alive:
            response = self.session.request(method, address, **kwargs)
        else:
            response = requests.request(method, address, **kwargs)

        log_item = {
            "url": address,
            "method": method,
            "response": response
        }
        log_item.update(kwargs)

        self.request_log.append(log_item)
        return response

    def head(self, url, **kwargs):
        return self.request(url, method='HEAD', **kwargs)

    def get(self, url, **kwargs):
        return self.request(url, method='GET', **kwargs)

    def post(self, url, **kwargs):
        return self.request(url, method='POST', **kwargs)

    def put(self, url, **kwargs):
        return self.request(url, method='PUT', **kwargs)

    def patch(self, url, **kwargs):
        return self.request(url, method='PATCH', **kwargs)

    def delete(self, url, **kwargs):
        return self.request(url, method='DELETE', **kwargs)

    # Utility asserts

    def assertRegex(self, regex, text, match=False, msg=None):
        if match:
            if re.match(regex, text) is None:
                text = text[:100] + "..." if len(text) > 100 else text
                msg = msg or "Regex %r didn't match expected value: %r" % (regex, text)
                self.fail(msg)
        else:
            if not re.findall(regex, text):
                text = text[:100] + "..." if len(text) > 100 else text
                msg = msg or "Regex %r didn't find anything in string %r" % (regex, text)
                self.fail(msg)

    def assertNotRegex(self, regex, text, match=False, msg=None):
        if match:
            if re.match(regex, text) is not None:
                text = text[:100] + "..." if len(text) > 100 else text
                msg = msg or "Regex %r unexpectedly matched expected value: %r" % (regex, text)
                raise AssertionError(msg)
        else:
            if re.findall(regex, text):
                text = text[:100] + "..." if len(text) > 100 else text
                msg = msg or "Regex %r unexpectedly found something in string %r" % (regex, text)
                raise AssertionError(msg)

    # Asserts for HTTP responses

    def assertOk(self, response, msg=None):  # NOTE: should we make 'response' parameter implicit?
        self.assertTrue(response.ok, msg=msg)

    def assertFailed(self, response, msg=None):
        self.assertTrue(response.status_code >= 400, msg=msg)

    def assert200(self, response, msg=None):
        self.assertEqual(response.status_code, 200, msg=msg)

    # TODO: asserts for HTTP codes (assertWasRedirected, etc)

    def assertStatusCode(self, code, response, msg=None):
        self.assertEqual(str(response.status_code), str(code), msg=msg)

    def assertNotStatusCode(self, code, response, msg=None):
        self.assertNotEqual(str(response.status_code), str(code), msg=msg)

    def assertInBody(self, member, response, msg=None):
        self.assertIn(member, response.text, msg=msg)

    def assertNotInBody(self, member, response, msg=None):
        self.assertNotIn(member, response, msg=msg)

    def assertRegexInBody(self, regex, response, match=False, msg=None):
        self.assertRegex(regex, response.text, match=match, msg=msg)

    def assertRegexNotInBody(self, regex, response, match=False, msg=None):
        self.assertNotRegex(regex, response.text, match=match, msg=msg)

    def assertHasHeader(self, header, response, msg=None):
        self.assertIn(header, response.headers, msg=msg)

    def assertHeaderValue(self, header, value, response, msg=None):
        self.assertIn(header, response.headers, msg=msg)
        self.assertEqual(response.headers[header], value, msg=msg)

    def assertInHeaders(self, member, response, msg=None):
        self.assertIn(member, headers_as_text(response.headers), msg=msg)

    def assertNotInHeaders(self, member, response, msg=None):
        self.assertNotIn(member, headers_as_text(response.headers), msg=msg)

    def assertRegexInHeaders(self, member, response, msg=None):
        self.assertIn(member, headers_as_text(response.headers), msg=msg)

    def assertRegexNotInHeaders(self, member, response, msg=None):
        self.assertNotIn(member, headers_as_text(response.headers), msg=msg)

    def assertJSONPath(self, jsonpath_query, response, msg=None):
        jsonpath_expr = jsonpath_rw.parse(jsonpath_query)
        body = response.json()
        matches = jsonpath_expr.find(body)
        if not matches:
            msg = msg or "JSONPath query %r didn't match response content" % jsonpath_query
            self.fail(msg=msg)

    def assertNotJSONPath(self, jsonpath_query, response, msg=None):
        jsonpath_expr = jsonpath_rw.parse(jsonpath_query)
        body = response.json()
        matches = jsonpath_expr.find(body)
        if matches:
            msg = msg or "JSONPath query %r didn't match response content" % jsonpath_query
            self.fail(msg=msg)

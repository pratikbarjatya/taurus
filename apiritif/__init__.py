import re
from io import BytesIO
from unittest import TestCase

import jsonpath_rw
import requests
from lxml import etree


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

    def _get_last_response(self):
        if self.request_log:
            return self.request_log[-1]["response"]
        raise ValueError("Can't take last response because no requests were made")

    # Utility asserts

    def assertRegexp(self, regex, text, match=False, msg=None):
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

    def assertNotRegexp(self, regex, text, match=False, msg=None):
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

    def assertOk(self, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertTrue(response.ok, msg=msg)

    def assertFailed(self, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertTrue(response.status_code >= 400, msg=msg)

    def assert2xx(self, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertTrue(200 <= response.status_code < 300, msg=msg)

    def assert3xx(self, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertTrue(300 <= response.status_code < 400, msg=msg)

    def assert4xx(self, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertTrue(400 <= response.status_code < 500, msg=msg)

    def assert5xx(self, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertTrue(500 <= response.status_code < 600, msg=msg)

    # TODO: asserts for HTTP codes (assertWasRedirected, etc)

    def assertStatusCode(self, code, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertEqual(str(response.status_code), str(code), msg=msg)

    def assertNotStatusCode(self, code, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertNotEqual(str(response.status_code), str(code), msg=msg)

    def assertInBody(self, member, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertIn(member, response.text, msg=msg)

    def assertNotInBody(self, member, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertNotIn(member, response, msg=msg)

    def assertRegexInBody(self, regex, response=None, match=False, msg=None):
        response = response or self._get_last_response()
        self.assertRegexp(regex, response.text, match=match, msg=msg)

    def assertRegexNotInBody(self, regex, response=None, match=False, msg=None):
        response = response or self._get_last_response()
        self.assertNotRegexp(regex, response.text, match=match, msg=msg)

    def assertHasHeader(self, header, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertIn(header, response.headers, msg=msg)

    def assertHeaderValue(self, header, value, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertIn(header, response.headers, msg=msg)
        self.assertEqual(response.headers[header], value, msg=msg)

    def assertInHeaders(self, member, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertIn(member, headers_as_text(response.headers), msg=msg)

    def assertNotInHeaders(self, member, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertNotIn(member, headers_as_text(response.headers), msg=msg)

    def assertRegexInHeaders(self, member, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertIn(member, headers_as_text(response.headers), msg=msg)

    def assertRegexNotInHeaders(self, member, response=None, msg=None):
        response = response or self._get_last_response()
        self.assertNotIn(member, headers_as_text(response.headers), msg=msg)

    def assertJSONPath(self, jsonpath_query, response=None, expected_value=None, msg=None):
        response = response or self._get_last_response()
        jsonpath_expr = jsonpath_rw.parse(jsonpath_query)
        body = response.json()
        matches = jsonpath_expr.find(body)
        if not matches:
            msg = msg or "JSONPath query %r didn't match response content" % jsonpath_query
            self.fail(msg=msg)
        if expected_value is not None and matches[0].value != expected_value:
            msg = msg or "Actual value at JSONPath query %r isn't equal to expected" % jsonpath_query
            self.fail(msg)

    def assertNotJSONPath(self, jsonpath_query, response=None, expected_value=None, msg=None):
        response = response or self._get_last_response()
        jsonpath_expr = jsonpath_rw.parse(jsonpath_query)
        body = response.json()
        matches = jsonpath_expr.find(body)
        if matches:
            msg = msg or "JSONPath query %r did match response content" % jsonpath_query
            self.fail(msg=msg)
        if expected_value is not None and matches[0].value == expected_value:
            msg = msg or "Actual value at JSONPath query %r is equal to expected" % jsonpath_query
            self.fail(msg)

    def assertXPath(self, xpath_query, response=None, parser_type='html', validate=False, msg=None):
        response = response or self._get_last_response()
        parser = etree.HTMLParser() if parser_type == 'html' else etree.XMLParser(dtd_validation=validate)
        tree = etree.parse(BytesIO(response.content), parser)
        matches = tree.xpath(xpath_query)
        if not matches:
            msg = msg or "XPath query %r didn't match response content" % xpath_query
            self.fail(msg=msg)

    def assertNotXPath(self, xpath_query, response=None, parser_type='html', validate=False, msg=None):
        response = response or self._get_last_response()
        parser = etree.HTMLParser() if parser_type == 'html' else etree.XMLParser(dtd_validation=validate)
        tree = etree.parse(BytesIO(response.content), parser)
        matches = tree.xpath(xpath_query)
        if matches:
            msg = msg or "XPath query %r did match response content" % xpath_query
            self.fail(msg=msg)

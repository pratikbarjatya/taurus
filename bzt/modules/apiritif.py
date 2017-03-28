"""
Copyright 2015 BlazeMeter Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
import os
import re
import sys
from collections import OrderedDict

from bzt import ToolError, TaurusConfigError
from bzt.engine import ScenarioExecutor, Scenario
from bzt.modules.aggregator import ConsolidatingAggregator
from bzt.modules.functional import FunctionalAggregator
from bzt.modules.selenium import FuncSamplesReader, LoadSamplesReader, SeleniumWidget
from bzt.requests_model import HTTPRequest
from bzt.six import string_types, iteritems
from bzt.utils import get_full_path, shutdown_process, PythonGenerator, dehumanize_time, ensure_is_dict


class ApiritifExecutor(ScenarioExecutor):
    def __init__(self):
        super(ApiritifExecutor, self).__init__()
        self.plugin_path = os.path.join(get_full_path(__file__, step_up=2), "resources", "nose_plugin.py")
        self.process = None
        self.stdout_path = None
        self.stderr_path = None
        self.stdout_file = None
        self.stderr_file = None
        self.script = None
        self.report_path = None
        self.generated_script = None

    def prepare(self):
        scenario = self.get_scenario()
        if "requests" in scenario:
            self.script = self._generate_script(scenario)
            self.generated_script = True
        elif "script" in scenario:
            self.script = self.get_script_path()
            self.generated_script = False
        else:
            raise TaurusConfigError("You must specify either 'requests' or 'script' for Apiritif")

        self.stdout_path = self.engine.create_artifact("nose", ".out")
        self.stderr_path = self.engine.create_artifact("nose", ".err")
        self.report_path = self.engine.create_artifact("report", ".ldjson")

        if self.engine.is_functional_mode():
            self.reader = FuncSamplesReader(self.report_path, self.log, [])
            if isinstance(self.engine.aggregator, FunctionalAggregator):
                self.engine.aggregator.add_underling(self.reader)
        else:
            self.reader = LoadSamplesReader(self.report_path, self.log, [])
            if isinstance(self.engine.aggregator, ConsolidatingAggregator):
                self.engine.aggregator.add_underling(self.reader)

    def startup(self):
        load = self.get_load()
        executable = self.settings.get("interpreter", sys.executable)
        nose_command_line = [executable, self.plugin_path, '--report-file', self.report_path]

        if load.iterations:
            nose_command_line += ['-i', str(load.iterations)]

        if load.hold:
            nose_command_line += ['-d', str(load.hold)]

        nose_command_line += [self.script]

        self.stdout_file = open(self.stdout_path, "wt")
        self.stderr_file = open(self.stderr_path, "wt")
        self.process = self.execute(nose_command_line, stdout=self.stdout_file, stderr=self.stderr_file)

    def check(self):
        if self.widget:
            self.widget.update()

        ret_code = self.process.poll()
        if ret_code is not None:
            if ret_code != 0:
                with open(self.stderr_path) as fds:
                    std_err = fds.read()
                msg = "Nose %s (%s) has failed with retcode %s \n %s"
                raise ToolError(msg % (self.label, self.__class__.__name__, ret_code, std_err.strip()))
            return True
        return False

    def shutdown(self):
        shutdown_process(self.process, self.log)
        if self.stdout_file:
            self.stdout_file.close()
        if self.stderr_file:
            self.stderr_file.close()

    def post_process(self):
        pass

    def has_results(self):
        return bool(self.reader and self.reader.read_records)

    def get_widget(self):
        if not self.widget:
            self.widget = SeleniumWidget(self.script, self.stdout_path)
        return self.widget

    def _generate_script(self, scenario):
        test_file = self.engine.create_artifact("test_api", ".py")
        test_gen = ApiritifScriptBuilder(scenario, self.log)
        test_gen.build_source_code()
        test_gen.save(test_file)
        return test_file


class ApiritifScriptBuilder(PythonGenerator):
    IMPORTS = """\
import time

import apiritif

"""

    def __init__(self, scenario, parent_logger):
        super(ApiritifScriptBuilder, self).__init__(scenario, parent_logger)

    def gen_setup_method(self):
        keepalive = self.scenario.get("keepalive", None)
        if keepalive is None:
            keepalive = True

        default_address = self.scenario.get("default-address", None)
        path_prefix = self.scenario.get("path-prefix", None)

        setup_method_def = self.gen_method_definition('setUp', ['self'])
        setup_method_def.append(self.gen_statement("super(TestRequests, self).setUp()", indent=8))
        setup_method_def.append(self.gen_statement("self.keep_alive = %r" % keepalive, indent=8))
        if default_address is not None:
            setup_method_def.append(self.gen_statement("self.default_address = %r" % default_address, indent=8))
        if path_prefix is not None:
            setup_method_def.append(self.gen_statement("self.path_prefix = %r" % path_prefix, indent=8))
        setup_method_def.append(self.gen_new_line())
        return setup_method_def

    def build_source_code(self):
        self.log.debug("Generating Test Case test methods")
        imports = self.add_imports()
        self.root.append(imports)
        test_class = self.gen_class_definition("TestRequests", ["apiritif.APITestCase"])
        self.root.append(test_class)
        test_class.append(self.gen_setup_method())

        for index, req in enumerate(self.scenario.get_requests()):
            if not isinstance(req, HTTPRequest):
                msg = "Apiritif script generator doesn't support '%s' blocks, skipping"
                self.log.warning(msg, req.NAME)
                continue

            mod_label = re.sub('[^0-9a-zA-Z]+', '_', req.url[:30])
            method_name = 'test_%05d_%s' % (index, mod_label)
            test_method = self.gen_test_method(method_name)

            self._add_url_request(req, test_method)

            test_class.append(test_method)
            test_method.append(self.gen_new_line())

    def _add_url_request(self, request, test_method):
        """
        :type request: bzt.requests_model.HTTPRequest
        """
        named_args = OrderedDict()

        method = request.method.lower()
        think_time = dehumanize_time(request.priority_option('think-time', default=None))

        named_args['timeout'] = dehumanize_time(request.priority_option('timeout', default='30s'))
        named_args['allow_redirects'] = request.priority_option('follow-redirects', default=True)

        headers = {}
        scenario_headers = self.scenario.get("headers", None)
        if scenario_headers:
            headers.update(scenario_headers)
        if request.headers:
            headers.update(request.headers)
        if headers:
            named_args['headers'] = headers

        merged_headers = dict([(key.lower(), value) for key, value in iteritems(headers)])
        content_type = merged_headers.get('content-type', None)
        if content_type == 'application/json' and isinstance(request.body, (dict, list)):  # json request body
            named_args['json'] = {key: value for key, value in iteritems(request.body)}
        elif method == "get" and isinstance(request.body, dict):  # request URL params (?a=b&c=d)
            named_args['params'] = {key: value for key, value in iteritems(request.body)}
        elif isinstance(request.body, dict):  # form data
            named_args['data'] = list(iteritems(request.body))
        elif isinstance(request.body, string_types):
            named_args['data'] = request.body
        elif request.body:
            msg = "Cannot handle 'body' option of type %s: %s"
            raise TaurusConfigError(msg % (type(request.body), request.body))

        kwargs = ", ".join("%s=%r" % (name, value) for name, value in iteritems(named_args))

        request_line = "response = self.{method}({url}, {kwargs})".format(
            method=method,
            url=repr(request.url),
            kwargs=kwargs,
        )
        test_method.append(self.gen_statement(request_line))
        test_method.append(self.gen_statement("self.assertOk(response)"))
        self._add_assertions(request, test_method)
        self._add_jsonpath_assertions(request, test_method)
        self._add_xpath_assertions(request, test_method)
        if think_time:
            test_method.append(self.gen_statement('time.sleep(%s)' % think_time))

    def _add_assertions(self, request, test_method):
        assertions = request.config.get("assert", [])
        for idx, assertion in enumerate(assertions):
            assertion = ensure_is_dict(assertions, idx, "contains")
            if not isinstance(assertion['contains'], list):
                assertion['contains'] = [assertion['contains']]
            subject = assertion.get("subject", Scenario.FIELD_BODY)
            if subject in (Scenario.FIELD_BODY, Scenario.FIELD_HEADERS):
                for member in assertion["contains"]:
                    func_table = {
                        (Scenario.FIELD_BODY, False, False): "assertInBody",
                        (Scenario.FIELD_BODY, False, True): "assertNotInBody",
                        (Scenario.FIELD_BODY, True, False): "assertRegexInBody",
                        (Scenario.FIELD_BODY, True, True): "assertRegexNotInBody",
                        (Scenario.FIELD_HEADERS, False, False): "assertInHeaders",
                        (Scenario.FIELD_HEADERS, False, True): "assertNotInHeaders",
                        (Scenario.FIELD_HEADERS, True, False): "assertRegexInHeaders",
                        (Scenario.FIELD_HEADERS, True, True): "assertRegexNotInHeaders",
                    }
                    method = func_table[(subject, assertion.get('regexp', True), assertion.get('not', False))]
                    line = "self.{method}({member}, response)".format(method=method, member=repr(member))
                    test_method.append(self.gen_statement(line))
            elif subject == Scenario.FIELD_RESP_CODE:
                for member in assertion["contains"]:
                    method = "assertStatusCode" if not assertion.get('not', False) else "assertNotStatusCode"
                    line = "self.{method}({member}, response)".format(method=method, member=repr(member))
                    test_method.append(self.gen_statement(line))

    def _add_jsonpath_assertions(self, request, test_method):
        jpath_assertions = request.config.get("assert-jsonpath", [])
        for idx, assertion in enumerate(jpath_assertions):
            assertion = ensure_is_dict(jpath_assertions, idx, "jsonpath")
            exc = TaurusConfigError('JSON Path not found in assertion: %s' % assertion)
            query = assertion.get('jsonpath', exc)
            expected = assertion.get('expected-value', '') or None
            method = "assertNotJSONPath" if assertion.get('invert', False) else "assertJSONPath"
            line = "self.{method}({query}, response, expected_value={expected})".format(
                method=method,
                query=repr(query),
                expected=repr(expected) if expected else None
            )
            test_method.append(self.gen_statement(line))

    def _add_xpath_assertions(self, request, test_method):
        jpath_assertions = request.config.get("assert-xpath", [])
        for idx, assertion in enumerate(jpath_assertions):
            assertion = ensure_is_dict(jpath_assertions, idx, "xpath")
            exc = TaurusConfigError('XPath not found in assertion: %s' % assertion)
            query = assertion.get('xpath', exc)
            method = "assertNotXPath" if assertion.get('invert', False) else "assertXPath"
            line = "self.{method}({query}, response)".format(method=method, query=repr(query))
            test_method.append(self.gen_statement(line))

    def gen_test_method(self, name):
        self.log.debug("Generating test method %s", name)
        test_method = self.gen_method_definition(name, ["self"])
        return test_method

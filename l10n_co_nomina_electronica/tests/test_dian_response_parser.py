"""Fixtures sin datos personales para el parser de respuestas DIAN."""

import base64
import importlib.util
from pathlib import Path
import unittest


_SERVICE = Path(__file__).parents[1] / 'services' / 'soap_client.py'
_SPEC = importlib.util.spec_from_file_location('ne_soap_client', _SERVICE)
soap_client = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(soap_client)


class TestDianResponseParser(unittest.TestCase):
    def test_error_message_list_and_soap_fault_are_not_document_results(self):
        response = soap_client._parse_response(
            '<Envelope><DianResponse><ErrorMessage><string>ZE02</string>'
            '<string>NIE072</string></ErrorMessage></DianResponse></Envelope>'
        )
        self.assertEqual(response['DianResponses'][0]['ErrorMessages'], ['ZE02', 'NIE072'])
        fault = soap_client._parse_response(
            '<Envelope><Fault><Reason><Text>SOAP failed</Text></Reason></Fault></Envelope>'
        )
        self.assertTrue(fault['SOAPFault'])
        self.assertEqual(fault['DianResponses'], [])

    def test_uuid_or_generic_id_never_identifies_a_payslip(self):
        app = '<ApplicationResponse><UUID>CUNE-A</UUID><ID>CUNE-B</ID></ApplicationResponse>'
        self.assertEqual(soap_client.extract_document_references(app), set())

    def test_document_reference_id_requires_real_ubl_path(self):
        app = ('<ApplicationResponse xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
               'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
               '<cac:DocumentResponse><cac:DocumentReference><cbc:ID>CUNE-A</cbc:ID>'
               '</cac:DocumentReference></cac:DocumentResponse></ApplicationResponse>')
        self.assertEqual(soap_client.extract_document_references(app), {'CUNE-A'})

    def test_large_payload_is_not_truncated(self):
        payload = base64.b64encode(b'x' * 6001).decode()
        parsed = soap_client._parse_response(
            '<Envelope><DianResponse><XmlBase64Bytes>%s</XmlBase64Bytes>'
            '</DianResponse></Envelope>' % payload
        )
        self.assertEqual(len(parsed['DianResponses'][0]['ApplicationResponse']), 6001)

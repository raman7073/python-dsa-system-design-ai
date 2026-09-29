import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from bson import ObjectId
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pymongo.errors import PyMongoError

HTTP_CLIENT = httpx.AsyncClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
config = types.ModuleType("config")
config.GEMINI_API_KEY = "test-key"
config.GEMINI_MODEL = "test-model"
config.JWT_SECRET_KEY = "test-secret-" * 4
config.JWT_ALGORITHM = "HS256"
config.ACCESS_TOKEN_EXPIRE_MINUTES = 30
config.validate_auth_config = lambda: None
database = types.ModuleType("database")
database.contracts_collection = Mock()
database.analysis_collection = Mock()
database.users_collection = Mock()
with patch.dict(sys.modules, {"config": config, "database": database}):
    service = importlib.import_module("service.analyse_contract")
    route = importlib.import_module("routes.analysis")


def valid_analysis():
    return {
        "contract_type": None,
        "summary": "A sample agreement.",
        "parties": [],
        "key_terms": {key: None for key in service.KeyTerms.model_fields},
        "obligations": [],
        "risks": [],
        "missing_or_unclear_terms": [],
        "overall_risk_level": "unknown",
        "overall_risk_explanation": "Limited information.",
        "questions_for_review": [],
        "review_limitations": ["Automated review requires verification."],
    }


def gemini_response(text, finish_reason="STOP"):
    return {"candidates": [{
        "finishReason": finish_reason,
        "content": {"parts": [{"text": text}]},
    }]}


class AnalysisTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.contracts = Mock()
        self.contracts.update_one.return_value.matched_count = 1
        self.analyses = Mock()
        for name, value in (("contracts_collection", self.contracts),
                            ("analysis_collection", self.analyses),
                            ("GEMINI_API_KEY", "test-key"), ("GEMINI_MODEL", "test-model")):
            patcher = patch.object(service, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.contract_id = str(ObjectId())

    def mock_http(self, handler):
        client = HTTP_CLIENT(transport=httpx.MockTransport(handler))
        patcher = patch.object(service.httpx, "AsyncClient", return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_success_preserves_full_text_and_returns_json_safe_unique_ids(self):
        contract_text = "A" * 16000 + " FINAL TERMINATION CLAUSE"

        def handler(request):
            self.assertEqual(request.headers['x-goog-api-key'], 'test-key')
            payload = json.loads(request.content)
            self.assertEqual(payload['generationConfig']['responseMimeType'], 'application/json')
            self.assertEqual(payload['generationConfig']['responseJsonSchema'],
                             service.ContractAnalysis.model_json_schema())
            self.assertNotIn('responseFormat', payload['generationConfig'])
            self.assertIn(contract_text, payload['contents'][0]['parts'][0]['text'])
            return httpx.Response(200, json=gemini_response(json.dumps(valid_analysis())))

        def insert(document):
            document['_id'] = ObjectId()

        self.analyses.insert_one.side_effect = insert
        ids = []
        for _ in range(2):
            self.mock_http(handler)
            result = await service.analyze_contract(self.contract_id, contract_text)
            json.dumps(result)
            self.assertNotIn('_id', result)
            ids.append(result['analysis_id'])
        self.assertNotEqual(*ids)
        self.assertEqual(self.contracts.update_one.call_args.args[1],
                         {'$set': {'analysis_status': 'completed'}})

    async def test_bad_responses_are_not_stored_and_mark_failed(self):
        cases = [
            (200, gemini_response('not json'), 502),
            (200, gemini_response('{}'), 502),
            (200, gemini_response(json.dumps(valid_analysis()), 'MAX_TOKENS'), 502),
            (200, {'promptFeedback': {'blockReason': 'SAFETY'}}, 502),
            (429, {}, 503),
            (401, {}, 502),
            (400, {}, 502),
            (404, {}, 502),
            (503, {}, 503),
        ]
        for status, body, expected in cases:
            with self.subTest(status=status, body=body):
                self.mock_http(lambda request: httpx.Response(status, json=body))
                with self.assertRaises(HTTPException) as caught:
                    await service.analyze_contract(self.contract_id, 'Agreement')
                self.assertEqual(caught.exception.status_code, expected)
                self.analyses.insert_one.assert_not_called()
                self.assertEqual(self.contracts.update_one.call_args.args[1],
                                 {'$set': {'analysis_status': 'failed'}})

    async def test_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout('timeout', request=request)
        self.mock_http(handler)
        with self.assertRaises(HTTPException) as caught:
            await service.analyze_contract(self.contract_id, 'Agreement')
        self.assertEqual(caught.exception.status_code, 504)
        self.analyses.insert_one.assert_not_called()

    async def test_database_failure(self):
        self.mock_http(lambda request: httpx.Response(
            200, json=gemini_response(json.dumps(valid_analysis()))))
        self.analyses.insert_one.side_effect = PyMongoError('unavailable')
        with self.assertRaises(HTTPException) as caught:
            await service.analyze_contract(self.contract_id, 'Agreement')
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(self.contracts.update_one.call_args.args[1],
                         {'$set': {'analysis_status': 'failed'}})

    async def test_invalid_id_empty_text_and_missing_contract(self):
        for contract_id, text, expected in [('invalid', 'Text', 400),
                                             (self.contract_id, '  ', 400)]:
            with self.assertRaises(HTTPException) as caught:
                await service.analyze_contract(contract_id, text)
            self.assertEqual(caught.exception.status_code, expected)
        self.contracts.update_one.assert_not_called()
        self.contracts.update_one.return_value.matched_count = 0
        with self.assertRaises(HTTPException) as caught:
            await service.analyze_contract(self.contract_id, 'Agreement')
        self.assertEqual(caught.exception.status_code, 404)
        self.analyses.insert_one.assert_not_called()


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.owner_patch = patch.object(route, 'contracts_collection')
        self.owner_patch.start()
        self.addCleanup(self.owner_patch.stop)

    def test_get_analysis(self):
        app = FastAPI()
        app.include_router(route.router)
        app.dependency_overrides[route.get_current_user] = lambda: {"id": "test-user"}
        analysis_id = 'a' * 32
        document = {
            'analysis_id': analysis_id,
            'contract_id': str(ObjectId()),
            'analysis': valid_analysis(),
        }
        with TestClient(app) as client, patch.object(route, 'analysis_collection') as collection:
            collection.find_one.return_value = document
            response = client.get(f'/analysis/{analysis_id}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'analysis': document})
            collection.find_one.assert_called_once_with(
                {'analysis_id': analysis_id}, {'_id': 0})
            collection.find_one.return_value = None
            response = client.get('/analysis/missing')
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()['detail'], 'Analysis not found')
            collection.find_one.side_effect = PyMongoError('unavailable')
            self.assertEqual(client.get(f'/analysis/{analysis_id}').status_code, 503)

    def test_route_validation_and_success(self):
        app = FastAPI()
        app.include_router(route.router)
        app.dependency_overrides[route.get_current_user] = lambda: {"id": "test-user"}
        contract_id = str(ObjectId())
        with TestClient(app) as client, patch.object(route, 'contracts_collection') as collection:
            self.assertEqual(client.post('/analysis/analyze/invalid').status_code, 400)
            collection.find_one.return_value = None
            self.assertEqual(client.post(f'/analysis/analyze/{contract_id}').status_code, 404)
            collection.find_one.return_value = {'text_content': ''}
            self.assertEqual(client.post(f'/analysis/analyze/{contract_id}').status_code, 400)
            collection.find_one.return_value = {'text_content': 'Agreement'}
            with patch.object(route, 'analyze_contract', return_value={'analysis_id': 'test'}) as analyze:
                response = client.post(f'/analysis/analyze/{contract_id}')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['analysis']['analysis_id'], 'test')
                analyze.assert_awaited_once_with(contract_id, 'Agreement')


if __name__ == '__main__':
    unittest.main()

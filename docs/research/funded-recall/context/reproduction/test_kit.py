"""Offline invariants. Never target execution, credentials, or provider calls."""
import argparse
import copy
import io
import os
import socket
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import live
from build_export import response as sanitize
from common import HERE, read
from reproduce import metrics, verify


def args(**changes):
    values=dict(round='R2',case='JCTX-R2-08b01303638b8b9d',include_historical=False,hydrated=None,
                max_requests=4,budget_usd=.25,max_response_bytes=65536,execute=False,out=None)
    values.update(changes)
    return argparse.Namespace(**values)


class KitTests(unittest.TestCase):
    def test_offline_recording_replay_and_counts(self):
        with patch.object(socket,'socket',side_effect=AssertionError('No network')):
            data=read('recordings.json.gz')
            results,parity=verify(data)
            result=metrics(data,results)
        self.assertEqual(parity,84)
        self.assertEqual(result['fresh_calls'],80)
        self.assertEqual(result['fresh_usd'],.70619572)
        self.assertEqual(result['rounds']['R2']['effects']['claude']['lost_positive'],1)

    def test_recording_tampering_is_rejected(self):
        original=read('recordings.json.gz')
        for mutation in ('wire','identity','answer','candidate'):
            with self.subTest(mutation=mutation):
                data=copy.deepcopy(original)
                if mutation=='wire':
                    q=next(q for q in data['requests'] if 'exact_rendered_json'in q)
                    q['exact_rendered_json']+=' '
                elif mutation=='identity':data['requests'][0]['identity']['model']='different'
                elif mutation=='answer':data['observations'][0]['response']['usage']['input_tokens']+=1
                else:
                    c=next(c for c in data['cases'] if 'candidate'in c)
                    c['candidate']['new']['code']+=' '
                with self.assertRaises(ValueError):verify(data)

    def test_live_dry_run_never_needs_environment_or_network(self):
        a=args()
        with patch.object(socket,'socket',side_effect=AssertionError('No network')), patch.dict(os.environ,{},clear=True):
            result=live.plan(a,live.select(a))
        self.assertEqual(result['blocked'],[])
        self.assertEqual(result['provider_calls'],0)
        self.assertEqual(result['requests'],4)

    def test_caps_and_missing_hydration(self):
        for options,reason in [
            ({'max_requests':3},'request cap'),
            ({'budget_usd':.001},'reservation exceeds frozen-rate budget'),
            ({'round':'R1','case':'KZ-12db7f631134d1ce'},'source hydration required'),
        ]:
            with self.subTest(reason=reason):
                a=args(**options)
                self.assertIn(reason,live.plan(a,live.select(a))['blocked'])
        for value in (float('nan'),float('inf'),0,-1):
            a=args(budget_usd=value)
            with self.assertRaises(ValueError):live.plan(a,live.select(a))

    def test_existing_output_cannot_be_overwritten(self):
        a=args(out=HERE)
        with self.assertRaises(ValueError):live.execute(a,live.select(a))

    def test_live_plan_rejects_altered_payload(self):
        a=args();qs=live.select(a);qs[0]['exact_rendered_json']+=' '
        with self.assertRaises(ValueError):live.plan(a,qs)

    def test_no_reasoning_or_headers_in_sanitized_responses(self):
        raw={'model':'test','content':[{'type':'thinking','thinking':'secret'},{'type':'text','text':'{}'}],
             'usage':{'input_tokens':1,'output_tokens':2,'output_tokens_details':{'thinking_tokens':2}},
             'headers':{'Authorization':'secret'},'id':'private-id'}
        out=sanitize(raw)
        self.assertEqual(out,{'model':'test','content':[{'type':'text','text':'{}'}],
                              'usage':{'input_tokens':1,'output_tokens':2}})

    def test_transport_uses_exact_payload_and_keeps_outputs_separate(self):
        # Only the external HTTP transport is faked; real execution/persistence paths run.
        import urllib.request
        data=read('recordings.json.gz');a=args()
        qs=live.select(a)[:1];q=qs[0]
        raw=next(o['response'] for o in data['observations'] if o['request_id']==q['request_id'])
        from common import canonical
        class Response:
            def __enter__(self):return self
            def __exit__(self,*unused):pass
            def read(self,bound):return canonical(raw).encode()[:bound]
        class Transport:
            def open(inner,request,timeout):
                self.assertEqual(request.data,q['exact_rendered_json'].encode())
                self.assertEqual(request.full_url,q['url'])
                return Response()
        # Keep generated test files inside the assigned kit, never in recordings.
        with tempfile.TemporaryDirectory(prefix='local-test-',dir=HERE) as tmp:
            a.out=Path(tmp)/'local-output'
            with patch.dict(os.environ,{'TYPESAFE_AI_API_KEY':'synthetic-unit-test-only'},clear=True), patch.object(urllib.request,'build_opener',return_value=Transport()), redirect_stdout(io.StringIO()):
                live.execute(a,qs)
            self.assertTrue((a.out/'000-intent.json').exists())
            self.assertTrue((a.out/'000-answer.json').exists())

if __name__=='__main__':unittest.main()
